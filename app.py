import os
import random
import telebot
from flask import Flask, request, jsonify, send_from_directory
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
from datetime import datetime
from threading import Thread
from urllib.parse import quote
import time

app = Flask(__name__, static_folder='static', template_folder='templates')

# Config
TELEGRAM_BOT_API_KEY = os.getenv('TELEGRAM_BOT_API_KEY')
GOOGLE_SHEET_ID = os.getenv('GOOGLE_SHEET_ID')
USER_RANGE = "Users!A2:G"
PUBLIC_URL = os.getenv('PUBLIC_URL')
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

# Désactive le caching pour les développements
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
app.config['TEMPLATES_AUTO_RELOAD'] = True

def get_google_sheets_service():
    creds_json = os.environ.get('GOOGLE_CREDS')
    if not creds_json:
        raise ValueError("GOOGLE_CREDS manquant")
    creds = Credentials.from_service_account_info(eval(creds_json), scopes=SCOPES)
    return build('sheets', 'v4', credentials=creds).spreadsheets()

@app.route('/')
def home():
    return send_from_directory('templates', 'index.html')

@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory('static', filename)

@app.route('/get-balance', methods=['POST'])
def get_balance():
    try:
        data = request.get_json()
        if not data or 'user_id' not in data:
            return jsonify({"error": "Données manquantes"}), 400
            
        service = get_google_sheets_service()
        result = service.values().get(
            spreadsheetId=GOOGLE_SHEET_ID,
            range=USER_RANGE
        ).execute()
        
        for row in result.get('values', []):
            if row and str(row[0]) == str(data['user_id']):
                return jsonify({
                    "balance": int(row[1]) if len(row) > 1 else 0,
                    "last_claim": row[2] if len(row) > 2 else None,
                    "referral_code": row[5] if len(row) > 5 else ""
                })
        
        return jsonify({"balance": 0, "last_claim": None})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/claim', methods=['POST'])
def claim_points():
    try:
        data = request.get_json()
        if not data or 'user_id' not in data:
            return jsonify({"error": "Données manquantes"}), 400
            
        user_id = str(data['user_id'])
        service = get_google_sheets_service()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        points = random.randint(10, 50)

        # Trouver l'utilisateur
        result = service.values().get(
            spreadsheetId=GOOGLE_SHEET_ID,
            range=USER_RANGE
        ).execute()
        
        for idx, row in enumerate(result.get('values', [])):
            if row and str(row[0]) == user_id:
                new_balance = (int(row[1]) if len(row) > 1 else 0) + points
                
                # Mise à jour
                service.values().update(
                    spreadsheetId=GOOGLE_SHEET_ID,
                    range=f"Users!B{idx+2}:C{idx+2}",
                    valueInputOption="USER_ENTERED",
                    body={"values": [[new_balance, now]]}
                ).execute()
                
                return jsonify({
                    "success": True,
                    "new_balance": new_balance,
                    "last_claim": now
                })

        return jsonify({"error": "Utilisateur non trouvé"}), 404

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)