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
app = Flask(__name__, static_folder='static')
app.config['JSONIFY_PRETTYPRINT_REGULAR'] = False
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

# Configuration CORS
CORS(app, resources={
    r"/get-balance": {"origins": "*"},
    r"/claim": {"origins": "*"},
    r"/get-tasks": {"origins": "*"},
    r"/get-friends": {"origins": "*"},
    r"/complete-task": {"origins": "*"}
})

# Configuration logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constantes
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
COOLDOWN_HOURS = 5
MIN_CLAIM = 10
MAX_CLAIM = 50
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
        logger.error(f"Erreur d'initialisation Google Sheets: {str(e)}")
        raise

def validate_user_data(func):
    """Décorateur pour valider les données utilisateur"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        if request.method == 'OPTIONS':
            return _build_cors_preflight_response()
            
        data = request.get_json()
        if not data or 'user_id' not in data:
            return jsonify({"error": "Données utilisateur manquantes"}), 400
        return func(*args, **kwargs)
    return wrapper

def _build_cors_preflight_response():
    response = jsonify({"success": True})
    response.headers.add("Access-Control-Allow-Origin", "*")
    response.headers.add("Access-Control-Allow-Headers", "Content-Type")
    response.headers.add("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
    return response

def _corsify_actual_response(response):
    response.headers.add("Access-Control-Allow-Origin", "*")
    return response

def find_user_row(service, sheet_id, user_id):
    """Trouve la ligne d'un utilisateur dans la feuille"""
    with sheet_lock:
        result = service.values().get(
            spreadsheetId=sheet_id,
            range=USER_RANGE
        ).execute()
        
    for idx, row in enumerate(result.get('values', [])):
        if row and str(row[0]) == str(user_id):
            return idx + 2, row  # +2 car les lignes commencent à 1 et l'en-tête est ligne 1
    return None, None

@app.route('/')
def serve_index():
    return send_from_directory('templates', 'index.html')

@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory('static', filename)

@app.route('/get-balance', methods=['POST', 'OPTIONS'])
@validate_user_data
def get_balance():
    try:
        service = get_google_sheets_service()
        user_id = str(request.json['user_id'])
        
        row_num, row = find_user_row(service, os.environ['GOOGLE_SHEET_ID'], user_id)
        if not row:
            return _corsify_actual_response(jsonify({
                "balance": 0, 
                "last_claim": None, 
                "referral_code": user_id
            }))
        
        response = {
            "balance": int(row[1]) if len(row) > 1 else 0,
            "last_claim": row[2] if len(row) > 2 else None,
            "referral_code": row[5] if len(row) > 5 else user_id
        }
        
        # Vérifier le cooldown
        if response['last_claim']:
            last_claim = datetime.strptime(response['last_claim'], "%Y-%m-%d %H:%M:%S")
            if datetime.now() - last_claim < timedelta(hours=COOLDOWN_HOURS):
                response['cooldown'] = True
        
        return _corsify_actual_response(jsonify(response))
        
    except Exception as e:
        logger.error(f"Erreur get-balance: {str(e)}")
        return _corsify_actual_response(jsonify({"error": "Erreur serveur"})), 500

@app.route('/claim', methods=['POST', 'OPTIONS'])
@validate_user_data
def claim_points():
    try:
        service = get_google_sheets_service()
        user_id = str(request.json['user_id'])
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        points = random.randint(MIN_CLAIM, MAX_CLAIM)
        
        row_num, row = find_user_row(service, os.environ['GOOGLE_SHEET_ID'], user_id)
        if not row_num:
            return _corsify_actual_response(jsonify({"error": "Utilisateur non trouvé"})), 404
            
        # Vérifier le cooldown
        if len(row) > 2 and row[2]:
            last_claim = datetime.strptime(row[2], "%Y-%m-%d %H:%M:%S")
            if datetime.now() - last_claim < timedelta(hours=COOLDOWN_HOURS):
                return _corsify_actual_response(jsonify({
                    "error": f"Attendez {COOLDOWN_HOURS}h entre chaque claim"
                })), 400
        
        new_balance = (int(row[1]) if len(row) > 1 else 0) + points
        
        with sheet_lock:
            service.values().update(
                spreadsheetId=os.environ['GOOGLE_SHEET_ID'],
                range=f"Users!B{row_num}:C{row_num}",
                valueInputOption="USER_ENTERED",
                body={"values": [[new_balance, now]]}
            ).execute()
        
        return _corsify_actual_response(jsonify({
            "success": True,
            "new_balance": new_balance,
            "points_earned": points,
            "last_claim": now
        }))
        
    except Exception as e:
        logger.error(f"Erreur claim: {str(e)}")
        return _corsify_actual_response(jsonify({"error": "Erreur lors de la réclamation"})), 500

@app.route('/get-tasks', methods=['GET', 'OPTIONS'])
def get_tasks():
    if request.method == 'OPTIONS':
        return _build_cors_preflight_response()
    
    try:
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
        return _corsify_actual_response(jsonify({"tasks": tasks}))
    except Exception as e:
        logger.error(f"Erreur get-tasks: {str(e)}")
        return _corsify_actual_response(jsonify({"error": "Erreur serveur"})), 500

@app.route('/get-friends', methods=['GET', 'OPTIONS'])
def get_friends():
    if request.method == 'OPTIONS':
        return _build_cors_preflight_response()
    
    try:
        user_id = request.args.get('user_id')
        if not user_id:
            return _corsify_actual_response(jsonify({"error": "ID utilisateur manquant"})), 400
            
        return _corsify_actual_response(jsonify({
            "referrals": [
                {"username": "user1", "total_points": 100},
                {"username": "user2", "total_points": 50}
            ]
        }))
    except Exception as e:
        logger.error(f"Erreur get-friends: {str(e)}")
        return _corsify_actual_response(jsonify({"error": "Erreur serveur"})), 500

@app.route('/complete-task', methods=['POST', 'OPTIONS'])
@validate_user_data
def complete_task():
    try:
        data = request.json
        required = ['user_id', 'task_name', 'points']
        if not all(k in data for k in required):
            return _corsify_actual_response(jsonify({"error": "Données manquantes"})), 400
            
        return _corsify_actual_response(jsonify({
            "success": True,
            "points_added": data['points'],
            "task": data['task_name']
        }))
        
    except Exception as e:
        logger.error(f"Erreur complete-task: {str(e)}")
        return _corsify_actual_response(jsonify({"error": "Erreur serveur"})), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)