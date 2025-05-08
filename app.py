import os
import random
from flask import Flask, request, jsonify, send_from_directory, render_template
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta
from functools import wraps
import json
import logging
from threading import Lock
from flask_cors import CORS

# Désactive le cache Google API
import googleapiclient.discovery_cache
googleapiclient.discovery_cache.DISCOVERY_URI = 'https://www.googleapis.com/discovery/v1/apis/{api}/{apiVersion}/rest'

# Configuration initiale
app = Flask(__name__, template_folder='templates', static_folder='static')
app.config['JSONIFY_PRETTYPRINT_REGULAR'] = False
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
CORS(app)

# Configuration logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constantes
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
COOLDOWN_MINUTES = 5
MIN_CLAIM = 10
MAX_CLAIM = 100

# Configuration Sheets
SHEET_CONFIG = {
    'users': {
        'range': "Users!A2:C",
        'headers': ['user_id', 'balance', 'last_claim']
    },
    'transactions': {
        'range': "Transactions!A2:C"
    },
    'tasks': {
        'range': "Tasks!A2:D",
        'headers': ['id', 'name', 'reward', 'completed']
    },
    'friends': {
        'range': "Referrals!A2:C",
        'headers': ['user_id', 'friend_id', 'friend_name']
    }
}

sheet_lock = Lock()

def get_google_sheets_service():
    try:
        creds_json = os.environ.get('GOOGLE_CREDS')
        if not creds_json:
            raise ValueError("Configuration Google Sheets manquante")
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        return build('sheets', 'v4', credentials=creds).spreadsheets()
    except Exception as e:
        logger.error(f"Erreur Google Sheets: {str(e)}")
        raise

def get_sheet_data(service, sheet_id, range_name):
    try:
        result = service.values().get(
            spreadsheetId=sheet_id,
            range=range_name,
            majorDimension="ROWS"
        ).execute()
        return result.get('values', [])
    except Exception as e:
        logger.error(f"Erreur lecture sheet {range_name}: {str(e)}")
        raise

def find_user_row(service, sheet_id, user_id):
    try:
        values = get_sheet_data(service, sheet_id, SHEET_CONFIG['users']['range'])
        for i, row in enumerate(values, start=2):
            if row and str(row[0]) == str(user_id):
                return i, dict(zip(SHEET_CONFIG['users']['headers'], row))
        return None, None
    except Exception as e:
        logger.error(f"Erreur recherche utilisateur: {str(e)}")
        raise

def parse_date(date_str):
    if not date_str:
        return None
    formats = ["%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%m/%d/%Y %H:%M:%S"]
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None

@app.route('/claim', methods=['POST'])
def claim_points():
    try:
        user_id = str(request.json.get('user_id'))
        if not user_id:
            return jsonify({"status": "error", "message": "User ID manquant"}), 400

        service = get_google_sheets_service()
        sheet_id = os.environ['GOOGLE_SHEET_ID']
        row_num, user = find_user_row(service, sheet_id, user_id)

        if not row_num:
            return jsonify({"status": "error", "message": "Utilisateur non trouvé"}), 404

        # Cooldown
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
            # Mise à jour balance
            service.values().update(
                spreadsheetId=sheet_id,
                range=f"Users!B{row_num}:C{row_num}",
                valueInputOption="USER_ENTERED",
                body={"values": [[new_balance, now]]}
            ).execute()
            # Ajout transaction
            service.values().append(
                spreadsheetId=sheet_id,
                range=SHEET_CONFIG['transactions']['range'],
                valueInputOption="USER_ENTERED",
                body={"values": [[now, user_id, points]]}
            ).execute()

        return jsonify({
            "status": "success",
            "balance": new_balance,
            "last_claim": now,
            "points_earned": points
        })
    except Exception as e:
        logger.error(f"Erreur claim: {str(e)}")
        return jsonify({"status": "error", "message": "Erreur serveur"}), 500

@app.route('/get-balance', methods=['POST'])
def get_balance():
    try:
        user_id = str(request.json.get('user_id'))
        if not user_id:
            return jsonify({"status": "error", "message": "User ID manquant"}), 400

        service = get_google_sheets_service()
        _, user = find_user_row(service, os.environ['GOOGLE_SHEET_ID'], user_id)

        if not user:
            return jsonify({"status": "error", "message": "Utilisateur non trouvé"}), 404

        return jsonify({
            "status": "success",
            "balance": int(user.get('balance', 0)),
            "last_claim": user.get('last_claim'),
            "referral_code": user_id
        })
    except Exception as e:
        logger.error(f"Erreur balance: {str(e)}")
        return jsonify({"status": "error", "message": "Erreur serveur"}), 500

@app.route('/get-tasks', methods=['GET'])
def get_tasks():
    try:
        service = get_google_sheets_service()
        tasks_data = get_sheet_data(service, os.environ['GOOGLE_SHEET_ID'], SHEET_CONFIG['tasks']['range'])

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

@app.route('/get-friends', methods=['GET'])
def get_friends():
    try:
        user_id = request.args.get('user_id')
        if not user_id:
            return jsonify({"status": "error", "message": "User ID manquant"}), 400

        service = get_google_sheets_service()
        friends_data = get_sheet_data(service, os.environ['GOOGLE_SHEET_ID'], SHEET_CONFIG['friends']['range'])

        friends = []
        for row in friends_data:
            if len(row) >= 2 and str(row[0]) == str(user_id):
                friends.append({
                    "id": row[1],
                    "name": row[2] if len(row) > 2 else "Ami"
                })

        return jsonify({"status": "success", "friends": friends})
    except Exception as e:
        logger.error(f"Erreur get-friends: {str(e)}")
        return jsonify({"status": "error", "message": "Erreur serveur"}), 500

# Endpoint de santé (utilisé par Render)
@app.route('/health')
def health_check():
    return "OK", 200

# Routes Frontend
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/static/<path:path>')
def serve_static(path):
    return send_from_directory('static', path)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG", "false").lower() == "true")
