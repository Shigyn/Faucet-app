import os
import json
import logging
import hashlib
import hmac
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from googleapiclient.discovery import build
from google.oauth2 import service_account
from datetime import datetime
from threading import Lock

app = Flask(__name__)
CORS(app)

# Configuration
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Remplacez par votre vrai token de bot Telegram
TELEGRAM_BOT_TOKEN = 'VOTRE_BOT_TOKEN'  

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SERVICE_ACCOUNT_FILE = 'google/credentials.json'
SPREADSHEET_ID = '1efhyhjqfXzu12fKN5KubPRephwJch4__QDG0ikmUv4s'
USERS_RANGE = 'Users!A2:F'
TRANSACTIONS_RANGE = 'Transactions!A2:D'
TASKS_RANGE = 'Tasks!A2:D'
FRIENDS_RANGE = 'Friends!A2:C'
REFERRALS_RANGE = 'Referrals!A2:D'

sheet_lock = Lock()

def validate_telegram_webapp(data):
    """
    Valide l'authentification Telegram WebApp
    """
    try:
        if not data or not isinstance(data, dict):
            return False
            
        received_hash = data.get('hash', '')
        if not received_hash:
            return False
            
        data_check_string = '\n'.join(
            f"{k}={v}" for k, v in sorted(data.items()) if k != 'hash'
        )
        
        secret_key = hmac.new(
            "WebAppData".encode(), 
            TELEGRAM_BOT_TOKEN.encode(), 
            hashlib.sha256
        ).digest()
        
        computed_hash = hmac.new(
            secret_key, 
            data_check_string.encode(), 
            hashlib.sha256
        ).hexdigest()
        
        return computed_hash == received_hash
    except Exception as e:
        logger.error(f"Erreur validation Telegram: {str(e)}")
        return False

def get_google_sheets_service():
    """Authentification Google Sheets avec fallback"""
    try:
        # 1. Essai avec le fichier local
        if os.path.exists(SERVICE_ACCOUNT_FILE):
            creds = service_account.Credentials.from_service_account_file(
                SERVICE_ACCOUNT_FILE, scopes=SCOPES)
            return build('sheets', 'v4', credentials=creds)
        
        # 2. Fallback sur variable d'environnement
        creds_json = os.getenv('GOOGLE_CREDENTIALS')
        if creds_json:
            creds_dict = json.loads(creds_json)
            creds = service_account.Credentials.from_service_account_info(
                creds_dict, scopes=SCOPES)
            return build('sheets', 'v4', credentials=creds)
            
        raise Exception("Aucune méthode d'authentification valide")
    except Exception as e:
        logger.error(f"Erreur auth: {str(e)}")
        raise

def get_user_data(service, user_id):
    """Récupère les données utilisateur depuis Google Sheets"""
    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=USERS_RANGE
    ).execute()
    
    users = result.get('values', [])
    for i, user in enumerate(users):
        if len(user) > 2 and user[2] == user_id:
            return i, user
    return None, None

# ---------------------------
# ROUTES PRINCIPALES
# ---------------------------

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/get-balance', methods=['POST'])
def get_balance():
    try:
        if not validate_telegram_webapp(request.json):
            return jsonify({"error": "Authentification invalide"}), 401

        user_id = request.json.get('user_id')
        if not user_id:
            return jsonify({"error": "user_id requis"}), 400

        service = get_google_sheets_service()
        _, user = get_user_data(service, user_id)
        
        if not user:
            return jsonify({"error": "Utilisateur non trouvé"}), 404

        return jsonify({
            "balance": user[3] if len(user) > 3 else 0,
            "last_claim": user[4] if len(user) > 4 else None,
            "username": user[1] if len(user) > 1 else "Utilisateur",
            "referral_code": user[5] if len(user) > 5 else user_id
        }), 200

    except Exception as e:
        logger.error(f"Erreur get_balance: {str(e)}", exc_info=True)
        return jsonify({"error": "Erreur serveur"}), 500

@app.route('/claim', methods=['POST'])
def claim():
    try:
        if not validate_telegram_webapp(request.json):
            return jsonify({"error": "Authentification invalide"}), 401

        user_id = request.json.get('user_id')
        amount = int(request.json.get('amount', 10))

        if not user_id:
            return jsonify({"error": "user_id requis"}), 400

        service = get_google_sheets_service()
        user_index, user = get_user_data(service, user_id)
        
        if not user:
            return jsonify({"error": "Utilisateur non trouvé"}), 404

        current_balance = int(user[3]) if len(user) > 3 and user[3] else 0
        new_balance = current_balance + amount
        timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

        with sheet_lock:
            # Mise à jour balance
            service.spreadsheets().values().update(
                spreadsheetId=SPREADSHEET_ID,
                range=f"Users!D{user_index+2}",
                valueInputOption='USER_ENTERED',
                body={'values': [[str(new_balance)]]}
            ).execute()

            # Mise à jour last claim
            service.spreadsheets().values().update(
                spreadsheetId=SPREADSHEET_ID,
                range=f"Users!E{user_index+2}",
                valueInputOption='USER_ENTERED',
                body={'values': [[timestamp]]}
            ).execute()

            # Ajout transaction
            service.spreadsheets().values().append(
                spreadsheetId=SPREADSHEET_ID,
                range=TRANSACTIONS_RANGE,
                valueInputOption='USER_ENTERED',
                body={'values': [[user_id, str(amount), 'claim', timestamp]]}
            ).execute()

        return jsonify({
            "message": "Claim réussi",
            "new_balance": new_balance,
            "last_claim": timestamp,
            "points_earned": amount
        }), 200

    except Exception as e:
        logger.error(f"Erreur claim: {str(e)}", exc_info=True)
        return jsonify({"error": "Erreur serveur"}), 500

# ---------------------------
# ROUTES TÂCHES
# ---------------------------

@app.route('/get-tasks', methods=['POST'])
def get_tasks():
    try:
        if not validate_telegram_webapp(request.json):
            return jsonify({"error": "Authentification invalide"}), 401

        user_id = request.json.get('user_id')
        if not user_id:
            return jsonify({"error": "user_id requis"}), 400

        service = get_google_sheets_service()
        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=TASKS_RANGE
        ).execute()

        tasks = []
        for task in result.get('values', []):
            if len(task) >= 4 and task[0] == user_id:
                tasks.append({
                    "id": task[0],
                    "name": task[1],
                    "description": task[2],
                    "points": int(task[3]) if task[3].isdigit() else 0,
                    "completed": False  # À implémenter avec un système de suivi
                })

        return jsonify({"tasks": tasks}), 200

    except Exception as e:
        logger.error(f"Erreur get_tasks: {str(e)}", exc_info=True)
        return jsonify({"error": "Erreur serveur"}), 500

@app.route('/complete-task', methods=['POST'])
def complete_task():
    try:
        if not validate_telegram_webapp(request.json):
            return jsonify({"error": "Authentification invalide"}), 401

        user_id = request.json.get('user_id')
        task_name = request.json.get('task_name')
        points = int(request.json.get('points', 0))

        if not all([user_id, task_name]):
            return jsonify({"error": "Données manquantes"}), 400

        service = get_google_sheets_service()
        user_index, user = get_user_data(service, user_id)
        
        if not user:
            return jsonify({"error": "Utilisateur non trouvé"}), 404

        current_balance = int(user[3]) if len(user) > 3 and user[3] else 0
        new_balance = current_balance + points
        timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

        with sheet_lock:
            # Mise à jour balance
            service.spreadsheets().values().update(
                spreadsheetId=SPREADSHEET_ID,
                range=f"Users!D{user_index+2}",
                valueInputOption='USER_ENTERED',
                body={'values': [[str(new_balance)]]}
            ).execute()

            # Ajout transaction
            service.spreadsheets().values().append(
                spreadsheetId=SPREADSHEET_ID,
                range=TRANSACTIONS_RANGE,
                valueInputOption='USER_ENTERED',
                body={'values': [[user_id, str(points), f'task:{task_name}', timestamp]]}
            ).execute()

        return jsonify({
            "message": "Tâche complétée",
            "new_balance": new_balance,
            "points_earned": points,
            "task_name": task_name
        }), 200

    except Exception as e:
        logger.error(f"Erreur complete_task: {str(e)}", exc_info=True)
        return jsonify({"error": "Erreur serveur"}), 500

# ---------------------------
# ROUTES PARRAINAGE
# ---------------------------

@app.route('/get-referrals', methods=['POST'])
def get_referrals():
    try:
        if not validate_telegram_webapp(request.json):
            return jsonify({"error": "Authentification invalide"}), 401

        user_id = request.json.get('user_id')
        if not user_id:
            return jsonify({"error": "user_id requis"}), 400

        service = get_google_sheets_service()
        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=REFERRALS_RANGE
        ).execute()

        referrals = []
        for ref in result.get('values', []):
            if len(ref) >= 3 and ref[0] == user_id:
                referrals.append({
                    "user_id": ref[1],
                    "points_earned": int(ref[2]) if ref[2].isdigit() else 0,
                    "last_active": ref[3] if len(ref) > 3 else None
                })

        return jsonify({"referrals": referrals}), 200

    except Exception as e:
        logger.error(f"Erreur get_referrals: {str(e)}", exc_info=True)
        return jsonify({"error": "Erreur serveur"}), 500

@app.route('/register-referral', methods=['POST'])
def register_referral():
    try:
        if not validate_telegram_webapp(request.json):
            return jsonify({"error": "Authentification invalide"}), 401

        referrer_id = request.json.get('referrer_id')
        user_id = request.json.get('user_id')
        
        if not all([referrer_id, user_id]):
            return jsonify({"error": "Données manquantes"}), 400

        if referrer_id == user_id:
            return jsonify({"error": "Auto-parrainage impossible"}), 400

        service = get_google_sheets_service()
        timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

        with sheet_lock:
            # Enregistrement du parrainage
            service.spreadsheets().values().append(
                spreadsheetId=SPREADSHEET_ID,
                range=REFERRALS_RANGE,
                valueInputOption='USER_ENTERED',
                body={'values': [[referrer_id, user_id, '0', timestamp]]}
            ).execute()

        return jsonify({
            "message": "Parrainage enregistré",
            "referrer_id": referrer_id,
            "user_id": user_id
        }), 200

    except Exception as e:
        logger.error(f"Erreur register_referral: {str(e)}", exc_info=True)
        return jsonify({"error": "Erreur serveur"}), 500

# ---------------------------
# ROUTES UTILITAIRES
# ---------------------------

@app.route('/update-user', methods=['POST'])
def update_user():
    try:
        if not validate_telegram_webapp(request.json):
            return jsonify({"error": "Authentification invalide"}), 401

        user_id = request.json.get('user_id')
        username = request.json.get('username')
        
        if not all([user_id, username]):
            return jsonify({"error": "Données manquantes"}), 400

        service = get_google_sheets_service()
        user_index, user = get_user_data(service, user_id)
        
        if not user:
            # Création d'un nouvel utilisateur
            with sheet_lock:
                service.spreadsheets().values().append(
                    spreadsheetId=SPREADSHEET_ID,
                    range=USERS_RANGE,
                    valueInputOption='USER_ENTERED',
                    body={'values': [[
                        str(datetime.now().strftime("%d/%m/%Y %H:%M:%S")),
                        username,
                        user_id,
                        '0',  # Balance initiale
                        '',   # Last claim
                        user_id  # Code de parrainage
                    ]]}
                ).execute()
            
            return jsonify({
                "message": "Nouvel utilisateur créé",
                "balance": 0,
                "username": username
            }), 201
        else:
            # Mise à jour de l'utilisateur existant
            with sheet_lock:
                service.spreadsheets().values().update(
                    spreadsheetId=SPREADSHEET_ID,
                    range=f"Users!B{user_index+2}",
                    valueInputOption='USER_ENTERED',
                    body={'values': [[username]]}
                ).execute()
            
            return jsonify({
                "message": "Utilisateur mis à jour",
                "username": username
            }), 200

    except Exception as e:
        logger.error(f"Erreur update_user: {str(e)}", exc_info=True)
        return jsonify({"error": "Erreur serveur"}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=10000)