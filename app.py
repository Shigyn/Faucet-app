import os
import random
import json
import logging
import threading
from flask import Flask, request, jsonify, render_template
from googleapiclient.discovery import build
from google.oauth2 import service_account
from datetime import datetime, timedelta
from threading import Lock
import hashlib
import hmac
from flask_cors import CORS
from telegram import Update, Bot
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from queue import Queue
from telegram.ext import Dispatcher, CommandHandler, MessageHandler, Filters
import requests

# === Logging config ===
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# === Config vars ===
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SPREADSHEET_ID = os.getenv('GOOGLE_SHEET_ID')

# === Flask app + CORS ===
app = Flask(__name__)
CORS(app)

@app.before_first_request
def setup_webhook():
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook"
    webhook_url = "https://faucet-app.onrender.com/webhook"
    response = requests.post(url, data={"url": webhook_url})
    logger.info(f"Webhook setup response: {response.text}")

# === Telegram Bot + Dispatcher ===
bot = Bot(token=TELEGRAM_BOT_TOKEN)

def log_all(update, context):
    logger.info(f"Update reçu: {update}")

def start_command(update, context):
    logger.info("🚀 start_command lancé")
    logger.info(f"/start reçu de {update.effective_user.id} avec args={context.args}")
    
    if update.message is None:
        logger.error("🚨 update.message est None, impossible d'envoyer le message")
        return
    
    try:
        args = context.args
        refid = args[0] if args else None
        
        base_url = "https://faucet-app.onrender.com"
        url = f"{base_url}/?refid={refid}" if refid else base_url

        keyboard = [[InlineKeyboardButton("Open App", url=url)]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        welcome_text = "Bienvenue sur TronQuest Airdrop! Collectez vos tokens chaque jour."
        
        update.message.reply_text(
            text=welcome_text,
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Erreur dans start_command: {str(e)}")

update_queue = Queue()
dispatcher = Dispatcher(bot, update_queue, use_context=True)  # Dispatcher doit être défini AVANT handlers
dispatcher.add_handler(CommandHandler("start", start_command))
dispatcher.add_handler(MessageHandler(Filters.all, log_all))

# === Constants ===
RANGES = {
    'users': 'Users!A2:F',
    'transactions': 'Transactions!A2:D',
    'tasks': 'Tasks!A2:D',
    'referrals': 'Referrals!A2:D'
}
CLAIM_COOLDOWN_MINUTES = 5  # modifier plus tard 30-60

sheet_lock = Lock()  # Verrou pour accès Sheets

# === Fonctions utilitaires ===

def validate_telegram_webapp(data):
    if not data or not TELEGRAM_BOT_TOKEN:
        return False
    return True  # TODO: Renforcer validation en production

def get_sheets_service():
    try:
        creds_json = os.getenv('GOOGLE_CREDS')
        creds = service_account.Credentials.from_service_account_info(
            json.loads(creds_json), scopes=SCOPES)
        return build('sheets', 'v4', credentials=creds)
    except Exception as e:
        logger.error(f"Erreur Google Sheets: {str(e)}")
        raise

# === Flask routes ===

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/webhook', methods=['POST'])
def webhook():
    logger.info("Webhook received an update")
    update = Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(update)
    return 'ok'

@app.route('/import-ref', methods=['POST'])
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
    startuserid = request.args.get('startuserid', '')  # Get param
    base_url = 'https://t.me/CRYPTORATS_bot'
    
    if startuserid:
        url = f"{base_url}?start={startuserid}"  # URL avec param startuserid
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
                user_id  # Code parrainage complet
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

@app.route('/get-tasks', methods=['GET'])
def get_tasks_frontend():
    try:
        user_id = request.args.get('user_id')
        service = get_sheets_service()
        tasks = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=RANGES['tasks']
        ).execute().get('values', [])
        
        tasks_list = []
        for row in tasks:
            if len(row) >= 3:
                tasks_list.append({
                    'name': row[0],  # Changé de task_name à name
                    'description': row[1],
                    'reward': int(row[2])  # Changé de points à reward
                })
        return jsonify({'status': 'success', 'tasks': tasks_list})
    except Exception as e:
        logger.error(f"Erreur get_tasks: {str(e)}")
        return jsonify({'status': 'error', 'tasks': []}), 500

@app.route('/get-balance', methods=['GET'])
def get_balance_frontend():
    try:
        user_id = request.args.get('user_id')
        service = get_sheets_service()
        row, _ = get_user_row_and_index(service, user_id)
        if not row:
            return jsonify({'status': 'error', 'message': 'User not found'}), 404
        
        balance = int(row[3]) if len(row) > 3 else 0
        last_claim = row[4] if len(row) > 4 else None
        referral_code = row[5] if len(row) > 5 else user_id
        
        return jsonify({
            'status': 'success',
            'balance': balance,
            'last_claim': last_claim,
            'referral_code': referral_code
        })
    except Exception as e:
        logger.error(f"Erreur get_balance: {str(e)}")
        return jsonify({'status': 'error'}), 500
        
        @app.route('/get-referrals', methods=['GET'])
def get_referrals_frontend():
    try:
        user_id = request.args.get('user_id')
        service = get_sheets_service()
        
        referrals = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=RANGES['referrals']
        ).execute().get('values', [])
        
        user_referrals = [
            {
                'user_id': row[1],
                'points_earned': int(row[2]) if len(row) > 2 else 0,
                'timestamp': row[3] if len(row) > 3 else None
            }
            for row in referrals if len(row) > 1 and row[0] == user_id
        ]
        
        return jsonify({
            'status': 'success',
            'referrals': user_referrals
        })
    except Exception as e:
        logger.error(f"Erreur get_referrals: {str(e)}")
        return jsonify({'status': 'error', 'referrals': []}), 500
        
@app.route('/complete-task', methods=['POST'])
def complete_task():
    try:
        data = request.json
        user_id = str(data.get('user_id'))
        task_name = data.get('task_name')
        points = int(data.get('points', 0))
        
        service = get_sheets_service()
        with sheet_lock:  # Verrou sur accès Sheets
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

def get_user_row_and_index(service, user_id):
    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=RANGES['users']
    ).execute()
    rows = result.get('values', [])
    for i, row in enumerate(rows):
        if len(row) > 2 and row[2] == user_id:
            return row, i+2  # ligne dans Sheets (1-based + header)
    return None, None

def get_last_claim_time(row):
    if len(row) > 4 and row[4]:
        try:
            return datetime.strptime(row[4], '%Y-%m-%d %H:%M:%S')
        except:
            return None
    return None

def update_claim_time(service, row_num):
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=f'Users!E{row_num}',
        valueInputOption='USER_ENTERED',
        body={'values': [[now_str]]}
    ).execute()

def update_balance(service, row_num, current_balance, points):
    new_balance = current_balance + points
    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=f'Users!D{row_num}',
        valueInputOption='USER_ENTERED',
        body={'values': [[str(new_balance)]]}
    ).execute()
    return new_balance

def add_transaction(service, user_id, points, typ='claim'):
    service.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=RANGES['transactions'],
        valueInputOption='USER_ENTERED',
        body={'values': [[user_id, str(points), typ, datetime.now().strftime('%Y-%m-%d %H:%M:%S')]]}
    ).execute()

@app.route('/claim', methods=['POST'])
def claim():
    try:
        data = request.json
        user_id = str(data.get('user_id'))
        watchads = data.get('watchads', False)

        service = get_sheets_service()
        with sheet_lock:
            row, row_num = get_user_row_and_index(service, user_id)
            if not row:
                return jsonify({'status': 'error', 'message': 'User not found'}), 404

            last_claim = get_last_claim_time(row)
            now = datetime.now()

            if last_claim and now < last_claim + timedelta(minutes=CLAIM_COOLDOWN_MINUTES):
                wait_sec = int((last_claim + timedelta(minutes=CLAIM_COOLDOWN_MINUTES) - now).total_seconds())
                return jsonify({'status': 'error', 'message': f'Cooldown active, wait {wait_sec} seconds'}), 429

            # Calcul points aléatoires
            base_points = random.randint(10, 100)
            points = base_points * 2 if watchads else base_points

            current_balance = int(row[3]) if len(row) > 3 else 0

            new_balance = update_balance(service, row_num, current_balance, points)
            update_claim_time(service, row_num)
            add_transaction(service, user_id, points, 'claim')

        return jsonify({
            'status': 'success',
            'points_earned': points,
            'new_balance': new_balance,
            'cooldown_seconds': CLAIM_COOLDOWN_MINUTES * 60
        })
    except Exception as e:
        logger.error(f"Erreur claim: {str(e)}")
        return jsonify({'status': 'error', 'message': 'Internal error'}), 500

@app.route('/balance', methods=['GET'])
def get_balance():
    try:
        user_id = request.args.get('user_id')
        service = get_sheets_service()
        row, _ = get_user_row_and_index(service, user_id)
        if not row:
            return jsonify({'status': 'error', 'message': 'User not found'}), 404
        balance = int(row[3]) if len(row) > 3 else 0
        return jsonify({'status': 'success', 'balance': balance})
    except Exception as e:
        logger.error(f"Erreur get_balance: {str(e)}")
        return jsonify({'status': 'error'}), 500

@app.route('/tasks', methods=['GET'])
def get_tasks():
    try:
        service = get_sheets_service()
        tasks = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=RANGES['tasks']
        ).execute().get('values', [])
        # Format tasks as list of dict
        tasks_list = []
        for row in tasks:
            if len(row) >= 3:
                tasks_list.append({
                    'task_name': row[0],
                    'description': row[1],
                    'points': int(row[2])
                })
        return jsonify({'status': 'success', 'tasks': tasks_list})
    except Exception as e:
        logger.error(f"Erreur get_tasks: {str(e)}")
        return jsonify({'status': 'error'}), 500

@app.route('/referrals', methods=['GET'])
def get_referrals():
    try:
        user_id = request.args.get('user_id')
        service = get_sheets_service()
        # Récupérer tous les referrals
        referrals = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=RANGES['referrals']
        ).execute().get('values', [])

        # Récupérer tous les users (pour trouver 2e niveau)
        users = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=RANGES['users']
        ).execute().get('values', [])

        # Filleuls 1er niveau
        direct_refs = [r[1] for r in referrals if len(r) > 1 and r[0] == user_id]

        # Filleuls 2eme niveau
        second_level_refs = []
        for dref in direct_refs:
            second_level_refs += [r[1] for r in referrals if len(r) > 1 and r[0] == dref]

        # Calcul commissions (simulateur simple)
        # Récupérer solde filleuls 1er niveau
        def find_balance(u_id):
            for urow in users:
                if len(urow) > 2 and urow[2] == u_id:
                    return int(urow[3]) if len(urow) > 3 else 0
            return 0

        first_level_commission = sum(find_balance(fid) for fid in direct_refs) * 0.10
        second_level_commission = sum(find_balance(fid) for fid in second_level_refs) * 0.02

        total_commission = first_level_commission + second_level_commission

        return jsonify({
            'status': 'success',
            'first_level_refs': direct_refs,
            'second_level_refs': second_level_refs,
            'commissions': {
                'first_level': round(first_level_commission, 2),
                'second_level': round(second_level_commission, 2),
                'total': round(total_commission, 2)
            }
        })
    except Exception as e:
        logger.error(f"Erreur get_referrals: {str(e)}")
        return jsonify({'status': 'error'}), 500
        
# === App run ===
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)