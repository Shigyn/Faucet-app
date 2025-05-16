import os
import json
import logging
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from datetime import datetime, timedelta
from threading import Lock
from google.oauth2 import service_account
from googleapiclient.discovery import build

# Configuration initiale
app = Flask(__name__)
CORS(app, resources={
    r"/*": {
        "origins": ["https://web.telegram.org"],
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type", "Telegram-Init-Data"]
    }
})

# Middleware critique
@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = 'https://web.telegram.org'
    response.headers['Access-Control-Allow-Credentials'] = 'true'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Telegram-Init-Data'
    return response

# Config Google Sheets
SHEET_ID = os.getenv('GOOGLE_SHEET_ID')
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
creds = service_account.Credentials.from_service_account_info(
    json.loads(os.getenv('GOOGLE_CREDS')), scopes=SCOPES)
service = build('sheets', 'v4', credentials=creds)
sheet = service.spreadsheets()

# Routes principales
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/user-data', methods=['POST', 'OPTIONS'])
def user_data():
    if request.method == 'OPTIONS':
        return _build_cors_preflight_response()
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({'status': 'error', 'message': 'No data'}), 400

        user_id = str(data.get('user_id'))
        init_data = data.get('initData')
        
        # Validation basique Telegram
        if not init_data or not user_id:
            return jsonify({'status': 'error', 'message': 'Missing required data'}), 400

        # Récupération des données
        result = sheet.values().get(
            spreadsheetId=SHEET_ID,
            range='Users!A2:F'
        ).execute()
        
        users = result.get('values', [])
        user = next((u for u in users if len(u) > 2 and str(u[2]) == user_id), None)
        
        if not user:
            return jsonify({'status': 'error', 'message': 'User not found'}), 404
            
        return jsonify({
            'status': 'success',
            'balance': int(user[3]) if len(user) > 3 else 0,
            'last_claim': user[4] if len(user) > 4 else None,
            'referral_code': user[5] if len(user) > 5 else user_id
        })
        
    except Exception as e:
        logging.error(f"Error: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/claim', methods=['POST', 'OPTIONS'])
def claim():
    if request.method == 'OPTIONS':
        return _build_cors_preflight_response()
        
    try:
        data = request.get_json()
        user_id = str(data.get('user_id'))
        
        if not user_id:
            return jsonify({'status': 'error', 'message': 'user_id required'}), 400

        # Récupération utilisateur
        result = sheet.values().get(
            spreadsheetId=SHEET_ID,
            range='Users!A2:F'
        ).execute()
        
        users = result.get('values', [])
        user_idx = next((i for i, u in enumerate(users) if len(u) > 2 and str(u[2]) == user_id), None)
        
        if user_idx is None:
            return jsonify({'status': 'error', 'message': 'User not found'}), 404

        # Vérification cooldown
        user = users[user_idx]
        last_claim = user[4] if len(user) > 4 else None
        if last_claim:
            last_claim_time = datetime.strptime(last_claim, "%Y-%m-%d %H:%M:%S")
            if datetime.utcnow() - last_claim_time < timedelta(minutes=5):
                return jsonify({'status': 'error', 'message': 'Cooldown active'}), 429

        # Mise à jour
        new_balance = int(user[3]) + 10 if len(user) > 3 and user[3] else 10
        sheet.values().update(
            spreadsheetId=SHEET_ID,
            range=f'Users!D{user_idx+2}',
            valueInputOption='USER_ENTERED',
            body={'values': [[str(new_balance)]]}
        ).execute()
        
        sheet.values().update(
            spreadsheetId=SHEET_ID,
            range=f'Users!E{user_idx+2}',
            valueInputOption='USER_ENTERED',
            body={'values': [[datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")]]}
        ).execute()

        return jsonify({
            'status': 'success',
            'balance': new_balance,
            'last_claim': datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        })
        
    except Exception as e:
        logging.error(f"Error: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

def _build_cors_preflight_response():
    response = jsonify({'status': 'cors_preflight'})
    response.headers.add("Access-Control-Allow-Origin", "https://web.telegram.org")
    response.headers.add("Access-Control-Allow-Headers", "Content-Type,Telegram-Init-Data")
    response.headers.add("Access-Control-Allow-Methods", "POST,OPTIONS")
    return response

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)