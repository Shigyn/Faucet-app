import os
import random
from flask import Flask, request, jsonify, send_from_directory, send_file
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta
from functools import wraps
import json
import logging
from threading import Lock
from flask_cors import CORS

# Configuration initiale modifiée pour servir depuis le dossier principal
app = Flask(__name__, static_folder='.', static_url_path='')
app.config['JSONIFY_PRETTYPRINT_REGULAR'] = False
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

# Configuration CORS plus permissive
CORS(app)

# Configuration logging améliorée
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constantes
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
COOLDOWN_MINUTES = 5  # Cooldown de 5 minutes
MIN_CLAIM = 10
MAX_CLAIM = 100
USER_RANGE = "Users!A2:C"  # A: user_id, B: balance, C: last_claim
TRANSACTIONS_RANGE = "Transactions!A2:C"  # A: timestamp, B: user_id, C: amount

# Verrou pour les accès concurrents
sheet_lock = Lock()

# Décorateur de validation
def validate_user_data(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not request.json or 'user_id' not in request.json:
            logger.error("Données utilisateur manquantes dans la requête")
            return jsonify({"error": "Données utilisateur manquantes"}), 400
        return f(*args, **kwargs)
    return decorated_function

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

def find_user_row(service, sheet_id, user_id):
    """Trouve la ligne d'un utilisateur dans la feuille Users"""
    try:
        result = service.values().get(
            spreadsheetId=sheet_id,
            range=USER_RANGE
        ).execute()
        
        values = result.get('values', [])
        
        for i, row in enumerate(values, start=2):  # start=2 car on commence à la ligne 2
            if row and str(row[0]) == str(user_id):
                return i, row
        return None, None
    except Exception as e:
        logger.error(f"Erreur lors de la recherche de l'utilisateur: {str(e)}", exc_info=True)
        raise

def parse_date(date_str):
    """Tente de parser la date dans différents formats"""
    formats = [
        "%Y-%m-%d %H:%M:%S",  # Format ISO
        "%d/%m/%Y %H:%M",     # Format français
        "%m/%d/%Y %H:%M",     # Format américain
        "%d/%m/%Y %H:%M:%S",  # Format français avec secondes
        "%d.%m.%Y %H:%M"      # Format alternatif
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    logger.warning(f"Format de date non reconnu: {date_str}")
    return None

def log_transaction(service, sheet_id, user_id, amount):
    """Log une transaction dans l'onglet Transactions"""
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        values = [[timestamp, user_id, amount]]
        
        result = service.values().append(
            spreadsheetId=sheet_id,
            range=TRANSACTIONS_RANGE,
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": values}
        ).execute()
        
        logger.info(f"Transaction enregistrée: {result.get('updates').get('updatedCells')} cellules mises à jour")
        return True
    except Exception as e:
        logger.error(f"Erreur lors de l'enregistrement de la transaction: {str(e)}", exc_info=True)
        return False

@app.route('/claim', methods=['POST'])
@validate_user_data
def claim_points():
    try:
        user_id = str(request.json['user_id'])
        logger.info(f"Requête claim reçue pour user_id: {user_id}")
        
        service = get_google_sheets_service()
        row_num, row = find_user_row(service, os.environ['GOOGLE_SHEET_ID'], user_id)
        
        if not row_num:
            return jsonify({"error": "Utilisateur non trouvé"}), 404

        # Vérification cooldown avec gestion des formats de date multiples
        if len(row) > 2 and row[2]:
            last_claim = parse_date(row[2])
            if last_claim:
                cooldown_end = last_claim + timedelta(minutes=COOLDOWN_MINUTES)
                if datetime.now() < cooldown_end:
                    remaining = (cooldown_end - datetime.now()).total_seconds() / 60
                    logger.info(f"Cooldown actif - Temps restant: {remaining:.1f} minutes")
                    return jsonify({
                        "error": f"Attendez encore {int(remaining)} minutes",
                        "cooldown": True
                    }), 400
            else:
                logger.warning(f"Format de date non reconnu: {row[2]}")

        # Génération des points
        points = random.randint(MIN_CLAIM, MAX_CLAIM)
        current_balance = int(row[1]) if len(row) > 1 and row[1] else 0
        new_balance = current_balance + points
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Mise à jour Sheets
        with sheet_lock:
            # Update user balance and last claim
            service.values().update(
                spreadsheetId=os.environ['GOOGLE_SHEET_ID'],
                range=f"Users!B{row_num}:C{row_num}",
                valueInputOption="USER_ENTERED",
                body={"values": [[new_balance, now]]}
            ).execute()
            
            # Log transaction
            if not log_transaction(service, os.environ['GOOGLE_SHEET_ID'], user_id, points):
                logger.error("Échec de l'enregistrement de la transaction mais le claim a réussi")

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

@app.route('/get-balance', methods=['POST'])
@validate_user_data
def get_balance():
    try:
        user_id = str(request.json['user_id'])
        logger.info(f"Requête balance reçue pour user_id: {user_id}")
        
        service = get_google_sheets_service()
        _, row = find_user_row(service, os.environ['GOOGLE_SHEET_ID'], user_id)
        
        if not row:
            return jsonify({"error": "Utilisateur non trouvé"}), 404

        balance = int(row[1]) if len(row) > 1 and row[1] else 0
        last_claim = parse_date(row[2]) if len(row) > 2 and row[2] else None
        
        return jsonify({
            "balance": balance,
            "last_claim": last_claim.strftime("%Y-%m-%d %H:%M:%S") if last_claim else None,
            "referral_code": user_id  # Utilisation de l'user_id comme code de parrainage
        })
        
    except Exception as e:
        logger.error(f"Erreur balance: {str(e)}", exc_info=True)
        return jsonify({"error": "Erreur lors de la récupération du solde"}), 500

@app.route('/get-friends', methods=['GET'])
def get_friends():
    try:
        user_id = request.args.get('user_id')
        if not user_id:
            return jsonify({"error": "Paramètre user_id manquant"}), 400
            
        logger.info(f"Requête get-friends reçue pour user_id: {user_id}")
        return jsonify({"friends": []})  # Fonctionnalité à implémenter
        
    except Exception as e:
        logger.error(f"Erreur get-friends: {str(e)}", exc_info=True)
        return jsonify({"error": "Erreur lors de la récupération des amis"}), 500

# Routes modifiées pour servir depuis le dossier principal
@app.route('/')
def serve_index():
    try:
        return send_file('index.html')
    except FileNotFoundError:
        return jsonify({
            "status": "API en marche",
            "message": "index.html non trouvé dans le dossier principal",
            "endpoints": {
                "claim": {"method": "POST", "path": "/claim"},
                "balance": {"method": "POST", "path": "/get-balance"},
                "friends": {"method": "GET", "path": "/get-friends"}
            }
        }), 404

@app.route('/favicon.ico')
def serve_favicon():
    return send_from_directory('.', 'favicon.ico', mimetype='image/vnd.microsoft.icon')

@app.route('/static/<path:path>')
def serve_static(path):
    return send_from_directory('static', path)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)