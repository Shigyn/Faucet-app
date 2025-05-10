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

app = Flask(__name__)
CORS(app)

# Configuration
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SPREADSHEET_ID = os.getenv('GOOGLE_SHEET_ID')
COOLDOWN_MINUTES = 5

RANGES = {
    'users': 'Users!A2:F',
    'transactions': 'Transactions!A2:D',
    'tasks': 'Tasks!A2:D',
    'referrals': 'Referrals!A2:D'
}

sheet_lock = Lock()

def validate_telegram_webapp(data):
    if not data or not TELEGRAM_BOT_TOKEN:
        return False
    return True  # À renforcer en production

def get_sheets_service():
    try:
        creds_json = os.getenv('GOOGLE_CREDS')
        creds = service_account.Credentials.from_service_account_info(
            json.loads(creds_json), scopes=SCOPES)
        return build('sheets', 'v4', credentials=creds)
    except Exception as e:
        logger.error(f"Erreur Google Sheets: {str(e)}")
        raise

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/start', methods=['GET'])
def start():
    return jsonify({
        'status': 'success',
        'message': 'Welcome to TronQuest Airdrop! Collect tokens every day. You will get a bonus every 3 months that will be swapped to TRX. Use your referral code to invite others!',
        'buttons': [{
            'text': 'Open',
            'url': 'https://yourapp.com'  # Remplace par ton lien réel ou l'URL du bot
        }]
    })

@app.route('/update-user', methods=['POST'])
def update_user():
    try:
        data = request.json
        user_id = str(data.get('user_id'))
        username = data.get('username', 'User')
        
        service = get_sheets_service()
        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=RANGES['users']
        ).execute()
        
        user_exists = any(row[2] == user_id for row in result.get('values', []) if len(row) > 2)
        
        if not user_exists:
            new_user = [
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                username,
                user_id,
                '0',
                '',
                user_id  # Code de parrainage complet
            ]
            service.spreadsheets().values().append(
                spreadsheetId=SPREADSHEET_ID,
                range=RANGES['users'],
                valueInputOption='USER_ENTERED',
                body={'values': [new_user]}
            ).execute()
        
        return jsonify({
            'status': 'success',
            'user_id': user_id,
            'username': username
        })
    except Exception as e:
        logger.error(f"Erreur update_user: {str(e)}")
        return jsonify({'status': 'error'}), 500

@app.route('/complete-task', methods=['POST'])
def complete_task():
    try:
        data = request.json
        user_id = str(data.get('user_id'))
        task_name = data.get('task_name')
        points = int(data.get('points', 0))
        
        service = get_sheets_service()
        with sheet_lock:
            # Mise à jour du solde
            result = service.spreadsheets().values().get(
                spreadsheetId=SPREADSHEET_ID,
                range=RANGES['users']
            ).execute()
            
            for i, row in enumerate(result.get('values', [])):
                if len(row) > 2 and row[2] == user_id:
                    row_num = i + 2
                    current_balance = int(row[3]) if len(row) > 3 else 0
                    new_balance = current_balance + points
                    
                    service.spreadsheets().values().update(
                        spreadsheetId=SPREADSHEET_ID,
                        range=f'Users!D{row_num}',
                        valueInputOption='USER_ENTERED',
                        body={'values': [[str(new_balance)]]}
                    ).execute()
                    break
            
            # Ajout transaction
            service.spreadsheets().values().append(
                spreadsheetId=SPREADSHEET_ID,
                range=RANGES['transactions'],
                valueInputOption='USER_ENTERED',
                body={'values': [[user_id, str(points), 'task', datetime.now().strftime('%Y-%m-%d %H:%M:%S')]]}
            ).execute()
        
        return jsonify({
            'status': 'success',
            'points_earned': points
        })
    except Exception as e:
        logger.error(f"Erreur complete_task: {str(e)}")
        return jsonify({'status': 'error'}), 500

@app.route('/get-balance', methods=['POST'])
def get_balance():
    try:
        data = request.json
        user_id = str(data.get('user_id'))
        
        service = get_sheets_service()
        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=RANGES['users']
        ).execute()
        
        for row in result.get('values', []):
            if len(row) > 2 and row[2] == user_id:
                return jsonify({
                    'status': 'success',
                    'balance': int(row[3]) if len(row) > 3 else 0,
                    'last_claim': row[4] if len(row) > 4 else None,
                    'username': row[1] if len(row) > 1 else 'User',
                    'referral_code': row[5] if len(row) > 5 else user_id
                })
        
        return jsonify({
            'status': 'success',
            'balance': 0,
            'last_claim': None,
            'username': 'New User',
            'referral_code': user_id
        })
    except Exception as e:
        logger.error(f"Erreur get_balance: {str(e)}")
        return jsonify({'status': 'error'}), 500

@app.route('/claim', methods=['POST'])
def claim():
    try:
        data = request.json
        user_id = str(data.get('user_id'))
        now = datetime.now()
        points = random.randint(10, 100)
        
        service = get_sheets_service()
        
        # Trouver l'utilisateur
        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=RANGES['users']
        ).execute()
        
        rows = result.get('values', [])
        user_index = None
        
        for i, row in enumerate(rows):
            if len(row) > 2 and row[2] == user_id:
                user_index = i
                break
        
        # Mise à jour ou création
        with sheet_lock:
            if user_index is not None:
                row_num = user_index + 2
                current_balance = int(rows[user_index][3]) if len(rows[user_index]) > 3 else 0
                last_claim = rows[user_index][4] if len(rows[user_index]) > 4 else None
                # Vérification du délai de 5 minutes
                if last_claim:
                    last_claim_time = datetime.strptime(last_claim, '%Y-%m-%d %H:%M:%S')
                    if now - last_claim_time < timedelta(minutes=5):
                        return jsonify({'status': 'error', 'message': 'You can only claim once every 5 minutes.'}), 400
                
                new_balance = current_balance + points
                service.spreadsheets().values().update(
                    spreadsheetId=SPREADSHEET_ID,
                    range=f'Users!D{row_num}:E{row_num}',
                    valueInputOption='USER_ENTERED',
                    body={'values': [[str(new_balance), now.strftime('%Y-%m-%d %H:%M:%S')]]}
                ).execute()
            else:
                new_user = [
                    now.strftime('%Y-%m-%d %H:%M:%S'),
                    data.get('username', f'User{user_id[:5]}'),
                    user_id,
                    str(points),
                    now.strftime('%Y-%m-%d %H:%M:%S'),
                    user_id  # Code complet de parrainage
                ]
                service.spreadsheets().values().append(
                    spreadsheetId=SPREADSHEET_ID,
                    range=RANGES['users'],
                    valueInputOption='USER_ENTERED',
                    body={'values': [new_user]}
                ).execute()
                new_balance = points
            
            # Ajouter transaction
            service.spreadsheets().values().append(
                spreadsheetId=SPREADSHEET_ID,
                range=RANGES['transactions'],
                valueInputOption='USER_ENTERED',
                body={'values': [[user_id, str(points), 'claim', now.strftime('%Y-%m-%d %H:%M:%S')]]}
            ).execute()
        
        return jsonify({
            'status': 'success',
            'new_balance': new_balance,
            'last_claim': now.strftime('%Y-%m-%d %H:%M:%S'),
            'points_earned': points
        })
    except Exception as e:
        logger.error(f"Erreur claim: {str(e)}")
        return jsonify({'status': 'error'}), 500

@app.route('/get-tasks', methods=['POST'])
def get_tasks():
    try:
        service = get_sheets_service()
        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=RANGES['tasks']
        ).execute()
        
        tasks = []
        for row in result.get('values', []):
            if len(row) >= 4:
                tasks.append({
                    'id': row[0],
                    'name': row[1],
                    'reward': int(row[2]) if row[2].isdigit() else 0,
                    'description': row[3]
                })
        
        return jsonify({'status': 'success', 'tasks': tasks})
    except Exception as e:
        logger.error(f"Erreur get_tasks: {str(e)}")
        return jsonify({'status': 'error'}), 500

@app.route('/get-referrals', methods=['POST'])
def get_referrals():
    try:
        user_id = str(request.json.get('user_id'))
        service = get_sheets_service()
        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=RANGES['referrals']
        ).execute()
        
        referrals = []
        for row in result.get('values', []):
            if len(row) >= 3 and row[0] == user_id:
                referrals.append({
                    'user_id': row[1],
                    'points_earned': int(row[2]) if row[2].isdigit() else 0,
                    'timestamp': row[3] if len(row) > 3 else None
                })
        
        return jsonify({'status': 'success', 'referrals': referrals})
    except Exception as e:
        logger.error(f"Erreur get_referrals: {str(e)}")
        return jsonify({'status': 'error'}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
