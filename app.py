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
        'range': "Users!A2:F",
        'headers': ['timestamp', 'action', 'user_id', 'balance', 'last_claim', 'referral_code']
    },
    'transactions': {
        'range': "Transactions!A2:D",
        'headers': ['timestamp', 'user_id', 'amount', 'action']
    },
    'tasks': {
        'range': "Tasks!A2:D",
        'headers': ['task_name', 'description', 'points', 'url']
    },
    'friends': {
        'range': "Referrals!A2:D",
        'headers': ['user_id', 'referred_user_id', 'username', 'total_points']
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
        return build('sheets', 'v4', credentials=creds, cache_discovery=False)
    except Exception as e:
        logger.error(f"Erreur Google Sheets: {str(e)}")
        raise

def get_sheet_data(service, sheet_id, range_name):
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=sheet_id,
            range=range_name
        ).execute()

        # Log de la réponse brute pour analyse
        logger.info(f"Réponse brute de Google Sheets pour {range_name}: {result}")

        # Vérification et récupération des valeurs
        if 'values' in result:
            return result['values']
        else:
            logger.error(f"Aucune valeur trouvée pour {range_name}")
            return []
    except Exception as e:
        logger.error(f"Erreur lecture sheet {range_name}: {str(e)}")
        raise

def find_user_row(service, sheet_id, user_id):
    try:
        values = get_sheet_data(service, sheet_id, SHEET_CONFIG['users']['range'])
        for i, row in enumerate(values, start=2):
            if len(row) >= 3 and str(row[2]) == str(user_id):
                return i, dict(zip(SHEET_CONFIG['users']['headers'], row + [""] * (6 - len(row))))
        return None, None
    except Exception as e:
        logger.error(f"Erreur recherche utilisateur: {str(e)}")
        raise

# Fonction pour ajouter ou mettre à jour un utilisateur
def add_or_update_user(service, sheet_id, user_id, balance, last_claim=None):
    try:
        # Vérifier si l'utilisateur existe déjà
        row_num, user = find_user_row(service, sheet_id, user_id)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        if row_num:
            # Mise à jour de l'utilisateur existant
            service.spreadsheets().values().update(
                spreadsheetId=sheet_id,
                range=f"Users!C{row_num}:F{row_num}",
                valueInputOption="USER_ENTERED",
                body={"values": [[user_id, balance, last_claim or "", user.get('referral_code', user_id)]]}
            ).execute()
        else:
            # Si l'utilisateur n'existe pas, créer une nouvelle ligne
            new_row = [now, "claim", user_id, balance, last_claim or "", user_id]
            service.spreadsheets().values().append(
                spreadsheetId=sheet_id,
                range=SHEET_CONFIG['users']['range'],
                valueInputOption="USER_ENTERED",
                body={"values": [new_row]}
            ).execute()

    except Exception as e:
        logger.error(f"Erreur ajout ou mise à jour utilisateur: {str(e)}")
        raise

def parse_date(date_str):
    if not date_str:
        return None
    try:
        if isinstance(date_str, (int, float)):
            return datetime(1899, 12, 30) + timedelta(days=float(date_str))
        formats = ["%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y %H:%M:%S"]
        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        return None
    except Exception as e:
        logger.warning(f"Erreur parsing date {date_str}: {str(e)}")
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

        # Cooldown
        if user and user.get('last_claim'):
            last_claim = parse_date(user['last_claim'])
            if last_claim and (datetime.now() - last_claim) < timedelta(minutes=COOLDOWN_MINUTES):
                remaining = (last_claim + timedelta(minutes=COOLDOWN_MINUTES) - datetime.now()).seconds // 60
                return jsonify({
                    "status": "error",
                    "message": f"Attendez {remaining} minutes",
                    "cooldown": True
                }), 400

        points = random.randint(MIN_CLAIM, MAX_CLAIM)
        current_balance = int(user.get('balance') or 0)
        new_balance = current_balance + points
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with sheet_lock:
            # Mise à jour utilisateur ou création
            add_or_update_user(service, sheet_id, user_id, new_balance, last_claim=now)

            # Ajout transaction
            service.spreadsheets().values().append(
                spreadsheetId=sheet_id,
                range=SHEET_CONFIG['transactions']['range'],
                valueInputOption="USER_ENTERED",
                body={"values": [[now, user_id, points, "claim"]]}
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

# Routes restantes inchangées...

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG", "false").lower() == "true")
