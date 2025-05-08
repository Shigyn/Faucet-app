import os
import random
import json
import logging
from flask import Flask, request, jsonify, render_template
from googleapiclient.discovery import build
from google.oauth2 import service_account
from datetime import datetime, timedelta
from threading import Lock
import hashlib
import hmac
from flask_cors import CORS

# Configuration initiale
app = Flask(__name__)
CORS(app)

# Configuration logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constantes
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
COOLDOWN_MINUTES = 5
MIN_CLAIM = 10
MAX_CLAIM = 100

# Configuration Sheets
SHEET_CONFIG = {
    'users': {
        'range': "Users!A2:F",
        'headers': ['timestamp', 'username', 'user_id', 'balance', 'last_claim', 'referral_code']
    },
    'transactions': {
        'range': "Transactions!A2:D"
    },
    'tasks': {
        'range': "Tasks!A2:D",
        'headers': ['id', 'name', 'reward', 'completed']
    },
    'referrals': {
        'range': "Referrals!A2:D",
        'headers': ['referrer_id', 'user_id', 'points_earned', 'timestamp']
    }
}

sheet_lock = Lock()

def validate_telegram_webapp(data):
    """Validation de l'authentification Telegram"""
    try:
        if not data or not isinstance(data, dict) or 'hash' not in data:
            return False
            
        data_check_string = '\n'.join(
            f"{k}={v}" for k, v in sorted(data.items()) if k != 'hash'
        )
        
        secret_key = hmac.new(
            "WebAppData".encode(), 
            TELEGRAM_BOT_TOKEN.encode(), 
            hashlib.sha256
        ).digest()
        
        return hmac.new(
            secret_key, 
            data_check_string.encode(), 
            hashlib.sha256
        ).hexdigest() == data['hash']
    except Exception as e:
        logger.error(f"Validation error: {str(e)}")
        return False

def get_google_sheets_service():
    """Initialisation du service Google Sheets"""
    try:
        creds_json = os.getenv('GOOGLE_CREDENTIALS')
        if not creds_json:
            raise ValueError("Configuration Google Sheets manquante")
        creds = service_account.Credentials.from_service_account_info(
            json.loads(creds_json), scopes=SCOPES)
        return build('sheets', 'v4', credentials=creds, cache_discovery=False)
    except Exception as e:
        logger.error(f"Erreur Google Sheets: {str(e)}")
        raise

def get_sheet_data(service, sheet_id, range_name):
    """Récupération des données d'une feuille"""
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=sheet_id,
            range=range_name,
            majorDimension="ROWS"
        ).execute()
        return result.get('values', [])
    except Exception as e:
        logger.error(f"Erreur lecture sheet {range_name}: {str(e)}")
        raise

def find_user_row(service, sheet_id, user_id):
    """Recherche d'un utilisateur"""
    try:
        values = get_sheet_data(service, sheet_id, SHEET_CONFIG['users']['range'])
        for i, row in enumerate(values, start=2):
            if len(row) > 2 and str(row[2]) == str(user_id):
                return i, dict(zip(SHEET_CONFIG['users']['headers'], row))
        return None, None
    except Exception as e:
        logger.error(f"Erreur recherche utilisateur: {str(e)}")
        raise

def parse_date(date_str):
    """Conversion des dates"""
    if not date_str:
        return None
    formats = ["%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%m/%d/%Y %H:%M:%S"]
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None

def create_new_user(service, sheet_id, user_data):
    """Création d'un nouvel utilisateur"""
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        username = user_data.get('username', f"User{user_data['user_id'][:6]}")
        
        new_user = [
            timestamp,              # A - Date création
            username,              # B - Username
            str(user_data['user_id']), # C - User ID
            '10',                  # D - Balance (offert 10 points)
            timestamp,              # E - Last claim
            str(user_data['user_id']) # F - Referral code
        ]
        
        with sheet_lock:
            # Ajout de l'utilisateur
            service.spreadsheets().values().append(
                spreadsheetId=sheet_id,
                range=SHEET_CONFIG['users']['range'],
                valueInputOption="USER_ENTERED",
                body={"values": [new_user]}
            ).execute()
            
            # Ajout transaction
            service.spreadsheets().values().append(
                spreadsheetId=sheet_id,
                range=SHEET_CONFIG['transactions']['range'],
                valueInputOption="USER_ENTERED",
                body={"values": [[
                    timestamp,
                    str(user_data['user_id']),
                    '10',
                    'new_user'
                ]]}
            ).execute()
        
        return {
            "balance": 10,
            "last_claim": timestamp,
            "username": username,
            "referral_code": str(user_data['user_id'])
        }
    except Exception as e:
        logger.error(f"Erreur création utilisateur: {str(e)}")
        raise

# Routes API
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/get-balance', methods=['POST'])
def get_balance():
    try:
        if not validate_telegram_webapp(request.json):
            return jsonify({"status": "error", "message": "Authentification invalide"}), 401

        user_id = str(request.json.get('user_id'))
        if not user_id:
            return jsonify({"status": "error", "message": "User ID manquant"}), 400

        service = get_google_sheets_service()
        sheet_id = os.getenv('GOOGLE_SHEET_ID')
        row_num, user = find_user_row(service, sheet_id, user_id)
        
        if not row_num:
            # Création automatique pour nouvel utilisateur
            user_data = create_new_user(service, sheet_id, request.json)
            return jsonify({
                "status": "success",
                "balance": user_data["balance"],
                "last_claim": user_data["last_claim"],
                "username": user_data["username"],
                "referral_code": user_data["referral_code"]
            })

        return jsonify({
            "status": "success",
            "balance": int(user.get('balance', 0)),
            "last_claim": user.get('last_claim'),
            "username": user.get('username', f"User{user_id[:6]}"),
            "referral_code": user.get('referral_code', user_id)
        })
    except Exception as e:
        logger.error(f"Erreur balance: {str(e)}")
        return jsonify({"status": "error", "message": "Erreur serveur"}), 500

@app.route('/claim', methods=['POST'])
def claim_points():
    try:
        if not validate_telegram_webapp(request.json):
            return jsonify({"status": "error", "message": "Authentification invalide"}), 401

        user_id = str(request.json.get('user_id'))
        if not user_id:
            return jsonify({"status": "error", "message": "User ID manquant"}), 400

        service = get_google_sheets_service()
        sheet_id = os.getenv('GOOGLE_SHEET_ID')
        row_num, user = find_user_row(service, sheet_id, user_id)
        
        if not row_num:
            # Création automatique pour nouvel utilisateur
            user_data = create_new_user(service, sheet_id, request.json)
            return jsonify({
                "status": "success",
                "message": "Bienvenue ! 10 points offerts",
                "new_balance": user_data["balance"],
                "last_claim": user_data["last_claim"],
                "points_earned": 10
            })

        # Vérification cooldown
        if user.get('last_claim'):
            last_claim = parse_date(user['last_claim'])
            if last_claim and (datetime.now() - last_claim) < timedelta(minutes=COOLDOWN_MINUTES):
                remaining = (last_claim + timedelta(minutes=COOLDOWN_MINUTES) - datetime.now()).seconds // 60
                return jsonify({
                    "status": "error",
                    "message": f"Attendez {remaining} minutes",
                    "cooldown": True
                }), 400

        points = random.randint(MIN_CLAIM, MAX_CLAIM)
        new_balance = int(user.get('balance', 0)) + points
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with sheet_lock:
            # Mise à jour utilisateur
            service.spreadsheets().values().update(
                spreadsheetId=sheet_id,
                range=f"Users!D{row_num}:E{row_num}",  # Balance et last_claim
                valueInputOption="USER_ENTERED",
                body={"values": [[str(new_balance), now]]}
            ).execute()
            
            # Ajout transaction
            service.spreadsheets().values().append(
                spreadsheetId=sheet_id,
                range=SHEET_CONFIG['transactions']['range'],
                valueInputOption="USER_ENTERED",
                body={"values": [[now, user_id, str(points), 'claim']]}
            ).execute()

        return jsonify({
            "status": "success",
            "message": "Points réclamés avec succès",
            "new_balance": new_balance,
            "last_claim": now,
            "points_earned": points
        })
    except Exception as e:
        logger.error(f"Erreur claim: {str(e)}")
        return jsonify({"status": "error", "message": "Erreur serveur"}), 500

@app.route('/get-tasks', methods=['POST'])
def get_tasks():
    try:
        if not validate_telegram_webapp(request.json):
            return jsonify({"status": "error", "message": "Authentification invalide"}), 401

        service = get_google_sheets_service()
        tasks_data = get_sheet_data(service, os.getenv('GOOGLE_SHEET_ID'), SHEET_CONFIG['tasks']['range'])
        
        tasks = []
        for row in tasks_data:
            if len(row) >= 3:
                task = {
                    "id": row[0],
                    "name": row[1],
                    "reward": int(row[2]) if row[2].isdigit() else 0
                }
                if len(row) >= 4:
                    task["completed"] = row[3].lower() in ("true", "vrai", "1", "oui")
                tasks.append(task)
        
        return jsonify({"status": "success", "tasks": tasks})
    except Exception as e:
        logger.error(f"Erreur get-tasks: {str(e)}")
        return jsonify({"status": "error", "message": "Erreur serveur"}), 500

@app.route('/get-referrals', methods=['POST'])
def get_referrals():
    try:
        if not validate_telegram_webapp(request.json):
            return jsonify({"status": "error", "message": "Authentification invalide"}), 401

        user_id = request.json.get('user_id')
        if not user_id:
            return jsonify({"status": "error", "message": "User ID manquant"}), 400
            
        service = get_google_sheets_service()
        friends_data = get_sheet_data(service, os.getenv('GOOGLE_SHEET_ID'), SHEET_CONFIG['referrals']['range'])
        
        referrals = []
        for row in friends_data:
            if len(row) >= 2 and str(row[0]) == str(user_id):
                referrals.append({
                    "user_id": row[1],
                    "points_earned": int(row[2]) if len(row) > 2 and row[2].isdigit() else 0,
                    "timestamp": row[3] if len(row) > 3 else None
                })
        
        return jsonify({"status": "success", "referrals": referrals})
    except Exception as e:
        logger.error(f"Erreur get-referrals: {str(e)}")
        return jsonify({"status": "error", "message": "Erreur serveur"}), 500

if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)