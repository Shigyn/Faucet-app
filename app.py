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
from telegram import Update, Bot
from telegram.ext import Dispatcher, CommandHandler

app = Flask(__name__)
CORS(app)

@app.route('/webhook', methods=['POST'])
def webhook():
    update = Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(update)
    return 'ok'

def start_command(update, context):
    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Welcome to TronQuest Airdrop! Collect tokens every day..."
    )

dispatcher.add_handler(CommandHandler('start', start_command))

# Configuration
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SPREADSHEET_ID = os.getenv('GOOGLE_SHEET_ID')

# Ajoutez ceci après la création de l'app Flask
bot = Bot(token=TELEGRAM_BOT_TOKEN)
dispatcher = Dispatcher(bot, None, use_context=True)

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

@app.route('/import-ref', methods=['POST'])  # <-- Ce bloc doit être hors de la fonction home
def import_ref():
    try:
        data = request.json
        user_id = str(data.get('user_id'))
        ref_id = str(data.get('ref_id'))

        if user_id == ref_id:
            return jsonify({'status': 'error', 'message': 'You cannot refer yourself'}), 400

        service = get_sheets_service()

        # Vérifier si le référé existe déjà
        users = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=RANGES['users']
        ).execute().get('values', [])

        # Vérifier si le parrain existe
        referrer_exists = any(row[2] == ref_id for row in users if len(row) > 2)
        if not referrer_exists:
            return jsonify({'status': 'error', 'message': 'Referrer does not exist'}), 400

        # Vérifier si la référence existe déjà
        referrals = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=RANGES['referrals']
        ).execute().get('values', [])

        if any(row[1] == user_id for row in referrals if len(row) > 1):
            return jsonify({'status': 'error', 'message': 'Already referred'}), 400

        # Ajouter la référence
        service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=RANGES['referrals'],
            valueInputOption='USER_ENTERED',
            body={'values': [[ref_id, user_id, '10', datetime.now().strftime('%Y-%m-%d %H:%M:%S')]]}
        ).execute()

        return jsonify({'status': 'success', 'message': 'Referral added successfully'})
    except Exception as e:
        logger.error(f"Erreur import_ref: {str(e)}")
        return jsonify({'status': 'error'}), 500

@app.route('/welcome', methods=['GET'])
def welcome():
    startuserid = request.args.get('startuserid', '')  # récupère le paramètre startuserid s'il existe
    base_url = 'https://t.me/CRYPTORATS_bot'
    
    # Si startuserid existe, on l'ajoute en paramètre startuserid à l'URL du bot Telegram
    if startuserid:
        url = f"{base_url}?start={startuserid}"
    else:
        url = base_url
    
    return jsonify({
        'status': 'success',
        'message': 'Welcome to TronQuest Airdrop! Collect tokens every day. You will get a bonus every 3 months that will be swapped to TRX. Use your referral code to invite others!',
        'buttons': [{
            'text': 'Open',
            'url': url
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
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
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
                new_balance = current_balance + points
                
                service.spreadsheets().values().update(
                    spreadsheetId=SPREADSHEET_ID,
                    range=f'Users!D{row_num}:E{row_num}',
                    valueInputOption='USER_ENTERED',
                    body={'values': [[str(new_balance), now]]}
                ).execute()
            else:
                new_user = [
                    now,
                    data.get('username', f'User{user_id[:5]}'),
                    user_id,
                    str(points),
                    now,
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
                body={'values': [[user_id, str(points), 'claim', now]]}
            ).execute()
        
        return jsonify({
            'status': 'success',
            'new_balance': new_balance,
            'last_claim': now,
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
