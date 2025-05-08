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
app = Flask(__name__, template_folder='templates')
app.config['JSONIFY_PRETTYPRINT_REGULAR'] = False
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

# Configuration CORS
CORS(app)

# Configuration logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constantes
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
COOLDOWN_MINUTES = 5
MIN_CLAIM = 10
MAX_CLAIM = 100
USER_RANGE = "Users!A2:C"
TRANSACTIONS_RANGE = "Transactions!A2:C"

# Verrou pour les accès concurrents
sheet_lock = Lock()

# Décorateur de validation
def validate_user_data(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not request.json or 'user_id' not in request.json:
            logger.error("Données utilisateur manquantes")
            return jsonify({"error": "Données utilisateur manquantes"}), 400
        return f(*args, **kwargs)
    return decorated_function

def get_google_sheets_service():
    """Initialise le service Google Sheets"""
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

def find_user_row(service, sheet_id, user_id):
    """Trouve un utilisateur dans la feuille"""
    try:
        result = service.values().get(
            spreadsheetId=sheet_id,
            range=USER_RANGE
        ).execute()
        values = result.get('values', [])
        for i, row in enumerate(values, start=2):
            if row and str(row[0]) == str(user_id):
                return i, row
        return None, None
    except Exception as e:
        logger.error(f"Erreur recherche utilisateur: {str(e)}")
        raise

def parse_date(date_str):
    """Parse les dates dans différents formats"""
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%m/%d/%Y %H:%M",
        "%d/%m/%Y %H:%M:%S"
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None

def log_transaction(service, sheet_id, user_id, amount):
    """Enregistre une transaction"""
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        values = [[timestamp, user_id, amount]]
        service.values().append(
            spreadsheetId=sheet_id,
            range=TRANSACTIONS_RANGE,
            valueInputOption="USER_ENTERED",
            body={"values": values}
        ).execute()
        return True
    except Exception as e:
        logger.error(f"Erreur transaction: {str(e)}")
        return False

# Routes API
@app.route('/claim', methods=['POST'])
@validate_user_data
def claim_points():
    try:
        user_id = str(request.json['user_id'])
        service = get_google_sheets_service()
        row_num, row = find_user_row(service, os.environ['GOOGLE_SHEET_ID'], user_id)
        
        if not row_num:
            return jsonify({"error": "Utilisateur non trouvé"}), 404

        # Vérification cooldown
        if len(row) > 2 and row[2]:
            last_claim = parse_date(row[2])
            if last_claim and (datetime.now() - last_claim) < timedelta(minutes=COOLDOWN_MINUTES):
                remaining = (last_claim + timedelta(minutes=COOLDOWN_MINUTES) - datetime.now()).seconds // 60
                return jsonify({
                    "error": f"Attendez {remaining} minutes",
                    "cooldown": True
                }), 400

        points = random.randint(MIN_CLAIM, MAX_CLAIM)
        new_balance = (int(row[1]) if len(row) > 1 and row[1] else 0) + points
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with sheet_lock:
            service.values().update(
                spreadsheetId=os.environ['GOOGLE_SHEET_ID'],
                range=f"Users!B{row_num}:C{row_num}",
                valueInputOption="USER_ENTERED",
                body={"values": [[new_balance, now]]}
            ).execute()
            log_transaction(service, os.environ['GOOGLE_SHEET_ID'], user_id, points)

        return jsonify({
            "success": True,
            "new_balance": new_balance,
            "points_earned": points
        })
    except Exception as e:
        logger.error(f"Erreur claim: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/get-balance', methods=['POST'])
@validate_user_data
def get_balance():
    try:
        user_id = str(request.json['user_id'])
        service = get_google_sheets_service()
        _, row = find_user_row(service, os.environ['GOOGLE_SHEET_ID'], user_id)
        
        if not row:
            return jsonify({"error": "Utilisateur non trouvé"}), 404

        balance = int(row[1]) if len(row) > 1 and row[1] else 0
        last_claim = parse_date(row[2]) if len(row) > 2 and row[2] else None
        
        return jsonify({
            "balance": balance,
            "last_claim": last_claim.strftime("%Y-%m-%d %H:%M:%S") if last_claim else None
        })
    except Exception as e:
        logger.error(f"Erreur balance: {str(e)}")
        return jsonify({"error": str(e)}), 500

# Routes Frontend
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/static/<path:path>')
def serve_static(path):
    return send_from_directory('static', path)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)