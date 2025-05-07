import os
import random
from flask import Flask, request, jsonify, send_from_directory
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta
from functools import wraps
import json
import logging
from threading import Lock
from flask_cors import CORS

# Configuration initiale
app = Flask(__name__, static_folder='static', static_url_path='')
app.config['JSONIFY_PRETTYPRINT_REGULAR'] = False
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

# Configuration CORS plus permissive
CORS(app)

# Configuration logging améliorée
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constantes
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
COOLDOWN_HOURS = 0.08
MIN_CLAIM = 10
MAX_CLAIM = 100
USER_RANGE = "Users!A2:G"

# Verrou pour les accès concurrents
sheet_lock = Lock()

def get_google_sheets_service():
    """Crée le service Google Sheets avec gestion d'erreur améliorée"""
    try:
        creds_json = os.environ.get('GOOGLE_CREDS')
        if not creds_json:
            raise ValueError("Configuration Google Sheets manquante")
        
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        return build('sheets', 'v4', credentials=creds).spreadsheets()
    except Exception as e:
        logger.error(f"Erreur d'initialisation Google Sheets: {str(e)}", exc_info=True)
        raise

def validate_user_data(func):
    """Décorateur pour valider les données utilisateur"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            data = request.get_json()
            if not data or 'user_id' not in data:
                logger.warning("Données utilisateur manquantes dans la requête")
                return jsonify({"error": "Données utilisateur manquantes"}), 400
            return func(*args, **kwargs)
        except Exception as e:
            logger.error(f"Erreur validation données: {str(e)}", exc_info=True)
            return jsonify({"error": "Erreur de traitement des données"}), 400
    return wrapper

def find_user_row(service, sheet_id, user_id):
    """Trouve la ligne d'un utilisateur dans la feuille avec logging"""
    try:
        with sheet_lock:
            result = service.values().get(
                spreadsheetId=sheet_id,
                range=USER_RANGE
            ).execute()
            
        rows = result.get('values', [])
        logger.info(f"Trouvé {len(rows)} lignes dans la feuille")
        
        for idx, row in enumerate(rows):
            if row and str(row[0]) == str(user_id):
                logger.info(f"Utilisateur trouvé à la ligne {idx + 2}")
                return idx + 2, row
                
        logger.warning(f"Utilisateur {user_id} non trouvé")
        return None, None
    except Exception as e:
        logger.error(f"Erreur recherche utilisateur: {str(e)}", exc_info=True)
        raise

@app.route('/favicon.ico')
def favicon():
    return send_from_directory('static', 'favicon.ico', mimetype='image/vnd.microsoft.icon')

@app.route('/')
def serve_index():
    return send_from_directory('templates', 'index.html')

@app.route('/<path:path>')
def catch_all(path):
    return send_from_directory('templates', 'index.html')

@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory('static', filename)

@app.route('/get-balance', methods=['POST'])
@validate_user_data
def get_balance():
    try:
        user_id = str(request.json['user_id'])
        logger.info(f"Requête balance reçue pour user_id: {user_id}")
        
        service = get_google_sheets_service()
        row_num, row = find_user_row(service, os.environ['GOOGLE_SHEET_ID'], user_id)
        
        if not row:
            logger.info(f"Nouvel utilisateur détecté: {user_id}")
            return jsonify({
                "balance": 0, 
                "last_claim": None, 
                "referral_code": user_id
            })
        
        response = {
            "balance": int(row[1]) if len(row) > 1 and row[1] else 0,
            "last_claim": row[2] if len(row) > 2 else None,
            "referral_code": row[5] if len(row) > 5 and row[5] else user_id
        }
        
        if response['last_claim']:
            try:
                last_claim = datetime.strptime(response['last_claim'], "%Y-%m-%d %H:%M:%S")
                if datetime.now() - last_claim < timedelta(hours=COOLDOWN_HOURS):
                    response['cooldown'] = True
                    logger.info(f"Cooldown actif pour user_id: {user_id}")
            except ValueError as e:
                logger.warning(f"Format de date invalide: {response['last_claim']}")
                response['last_claim'] = None
        
        logger.info(f"Réponse balance pour {user_id}: {response}")
        return jsonify(response)
        
    except Exception as e:
        logger.error(f"Erreur get-balance: {str(e)}", exc_info=True)
        return jsonify({"error": "Erreur serveur", "details": str(e)}), 500

@app.route('/claim', methods=['POST'])
@validate_user_data
def claim_points():
    try:
        user_id = str(request.json['user_id'])
        logger.info(f"Requête claim reçue pour user_id: {user_id}")
        
        service = get_google_sheets_service()
        row_num, row = find_user_row(service, os.environ['GOOGLE_SHEET_ID'], user_id)
        
        if not row_num:
            logger.warning(f"Utilisateur non trouvé: {user_id}")
            return jsonify({"error": "Utilisateur non trouvé"}), 404
            
        # Vérification cooldown
        if len(row) > 2 and row[2]:
            try:
                last_claim = datetime.strptime(row[2], "%Y-%m-%d %H:%M:%S")
                if datetime.now() - last_claim < timedelta(hours=COOLDOWN_HOURS):
                    logger.info(f"Cooldown actif pour user_id: {user_id}")
                    return jsonify({
                        "error": f"Attendez {COOLDOWN_HOURS}h entre chaque claim",
                        "cooldown": True
                    }), 400
            except ValueError as e:
                logger.warning(f"Format de date invalide: {row[2]}")
        
        # Calcul nouveau solde
        points = random.randint(MIN_CLAIM, MAX_CLAIM)
        current_balance = int(row[1]) if len(row) > 1 and row[1] else 0
        new_balance = current_balance + points
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Mise à jour Google Sheets
        with sheet_lock:
            service.values().update(
                spreadsheetId=os.environ['GOOGLE_SHEET_ID'],
                range=f"Users!B{row_num}:C{row_num}",
                valueInputOption="USER_ENTERED",
                body={"values": [[new_balance, now]]}
            ).execute()
        
        logger.info(f"Claim réussi pour {user_id}: +{points} points")
        return jsonify({
            "success": True,
            "new_balance": new_balance,
            "points_earned": points,
            "last_claim": now
        })
        
    except Exception as e:
        logger.error(f"Erreur claim: {str(e)}", exc_info=True)
        return jsonify({"error": "Erreur lors de la réclamation", "details": str(e)}), 500

@app.route('/get-tasks', methods=['GET'])
def get_tasks():
    try:
        logger.info("Requête get-tasks reçue")
        tasks = [
            {
                "task_name": "Rejoindre Telegram",
                "description": "Rejoignez notre groupe Telegram",
                "points": 50,
                "url": "https://t.me/CRYPTORATS_bot"
            },
            {
                "task_name": "Suivre Twitter",
                "description": "Suivez-nous sur Twitter",
                "points": 30,
                "url": "https://twitter.com/CRYPTORATS_bot"
            }
        ]
        return jsonify({"tasks": tasks})
    except Exception as e:
        logger.error(f"Erreur get-tasks: {str(e)}", exc_info=True)
        return jsonify({"error": "Erreur serveur"}), 500

@app.route('/get-friends', methods=['GET'])
def get_friends():
    try:
        user_id = request.args.get('user_id')
        logger.info(f"Requête get-friends reçue pour user_id: {user_id}")
        
        if not user_id:
            logger.warning("Paramètre user_id manquant")
            return jsonify({"error": "ID utilisateur manquant"}), 400
            
        # Exemple de réponse - À remplacer par votre logique réelle
        return jsonify({
            "referrals": [
                {"username": "user1", "total_points": 100},
                {"username": "user2", "total_points": 50}
            ]
        })
    except Exception as e:
        logger.error(f"Erreur get-friends: {str(e)}", exc_info=True)
        return jsonify({"error": "Erreur serveur"}), 500

@app.route('/complete-task', methods=['POST'])
@validate_user_data
def complete_task():
    try:
        data = request.json
        logger.info(f"Requête complete-task reçue: {data}")
        
        required = ['user_id', 'task_name', 'points']
        if not all(k in data for k in required):
            logger.warning("Données manquantes dans complete-task")
            return jsonify({"error": "Données manquantes"}), 400
            
        # Ici vous devriez enregistrer la tâche complétée
        # Exemple simplifié:
        return jsonify({
            "success": True,
            "points_added": data['points'],
            "task": data['task_name']
        })
        
    except Exception as e:
        logger.error(f"Erreur complete-task: {str(e)}", exc_info=True)
        return jsonify({"error": "Erreur serveur"}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)