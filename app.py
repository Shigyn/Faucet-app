# (début du fichier inchangé)
import os
import random
import json
import logging
import threading
import time
from flask import Flask, request, jsonify, render_template, send_from_directory
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
import google.api_core
import google.auth.transport.requests
import google.oauth2.credentials

google.api_core.client_options.ClientOptions.disable_cache = True

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SPREADSHEET_ID = os.getenv('GOOGLE_SHEET_ID')

app = Flask(__name__)
CORS(app)

gunicorn_conf = {
    'workers': (os.cpu_count() or 1) * 2 + 1,
    'worker_class': 'sync',
    'timeout': 30,
    'graceful_timeout': 30,
    'keepalive': 5,
    'max_requests': 1000,
    'max_requests_jitter': 50,
    'accesslog': '-',
    'errorlog': '-'
}

@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory('static', filename)
    
@app.before_first_request
def setup_webhook():
    if TELEGRAM_BOT_TOKEN:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook"
        webhook_url = "https://faucet-app.onrender.com/webhook"
        try:
            response = requests.post(url, data={"url": webhook_url}, timeout=10)
            logger.info(f"Webhook setup response: {response.text}")
        except Exception as e:
            logger.error(f"Failed to setup webhook: {str(e)}")

bot = Bot(token=TELEGRAM_BOT_TOKEN) if TELEGRAM_BOT_TOKEN else None

def log_all(update, context):
    logger.info(f"Update reçu: {update}")

def start_command(update, context):
    logger.info("🚀 start_command lancé")
    logger.info(f"/start reçu de {update.effective_user.id} avec args={context.args}")
    
    if update.message is None:
        logger.error("🚨 update.message est None, impossible d'envoyer le message")
        return
    
    try:
        user_id = update.effective_user.id
        args = context.args
        refid = args[0] if args else None
        
        # Construire l'URL Telegram avec paramètre start=refid ou user_id
        # Si refid existe, on l'utilise sinon on met user_id
        start_param = refid if refid else str(user_id)
        
        telegram_bot_url = f"https://t.me/CRYPTORATS_bot?start={start_param}"

        keyboard = [[InlineKeyboardButton("Open Bot", url=telegram_bot_url)]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        welcome_text = "Bienvenue sur TronQuest Airdrop! Collectez vos tokens chaque jour."
        
        update.message.reply_text(
            text=welcome_text,
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Erreur dans start_command: {str(e)}")


if bot:
    update_queue = Queue()
    dispatcher = Dispatcher(bot, update_queue, use_context=True)
    dispatcher.add_handler(CommandHandler("start", start_command))
    dispatcher.add_handler(MessageHandler(Filters.all, log_all))

RANGES = {
    'users': 'Users!A2:F',
    'transactions': 'Transactions!A2:D',
    'tasks': 'Tasks!A2:D',
    'referrals': 'Referrals!A2:D'
}
CLAIM_COOLDOWN_MINUTES = 5

sheet_lock = Lock()

def get_sheets_service_with_retry(max_retries=3):
    for attempt in range(max_retries):
        try:
            creds_json = os.getenv('GOOGLE_CREDS')
            if not creds_json:
                raise ValueError("GOOGLE_CREDS environment variable is missing")
            creds = service_account.Credentials.from_service_account_info(
                json.loads(creds_json), scopes=SCOPES)
            return build('sheets', 'v4', credentials=creds)
        except Exception as e:
            logger.error(f"Attempt {attempt + 1} failed: {str(e)}")
            if attempt == max_retries - 1:
                raise
            time.sleep(2 ** attempt)

def validate_telegram_webapp(data):
    if not data or not TELEGRAM_BOT_TOKEN:
        return False
    return True

@app.before_request
def log_request_info():
    logger.debug(f"Request: {request.method} {request.path}")
    if request.method == 'POST' and request.content_type == 'application/json':
        logger.debug(f"Request body: {request.get_data()}")

@app.after_request
def log_response_info(response):
    logger.debug(f"Response: {response.status}")
    return response

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/health')
def health_check():
    try:
        service = get_sheets_service_with_retry()
        service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range="Users!A1:A1"
        ).execute()
        return jsonify({
            "status": "healthy",
            "details": {
                "sheets_connection": "ok",
                "telegram_bot": "ok" if TELEGRAM_BOT_TOKEN else "disabled"
            }
        }), 200
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return jsonify({
            "status": "unhealthy",
            "error": str(e)
        }), 500

@app.route('/webhook', methods=['POST'])
def webhook():
    if not bot:
        return jsonify({'status': 'error', 'message': 'Telegram bot not configured'}), 500
    logger.info("Webhook received an update")
    try:
        update = Update.de_json(request.get_json(force=True), bot)
        dispatcher.process_update(update)
        return 'ok'
    except Exception as e:
        logger.error(f"Webhook error: {str(e)}")
        return jsonify({'status': 'error'}), 500

@app.route('/validate-telegram', methods=['POST'])
def validate_telegram():
    try:
        data = request.json
        init_data = data.get('initData')
        if not init_data:
            return jsonify({'status': 'error', 'message': 'Missing initData'}), 400
        if not isinstance(init_data, str) or len(init_data) < 10:
            return jsonify({'status': 'error', 'message': 'Invalid initData format'}), 400
        return jsonify({'status': 'success'})
    except Exception as e:
        logger.error(f"Validation error: {str(e)}")
        return jsonify({'status': 'error'}), 500
        
@app.route('/init-data', methods=['POST'])
def handle_init_data():
    try:
        data = request.json
        init_data = data.get('initData')
        
        if not init_data:
            return jsonify({'status': 'error', 'message': 'Init data required'}), 400

        # Validation basique de l'utilisateur Telegram
        user_data = {}
        if 'user' in init_data:
            user_data = {
                'id': init_data['user'].get('id'),
                'first_name': init_data['user'].get('first_name'),
                'username': init_data['user'].get('username')
            }
        
        return jsonify({
            'status': 'success',
            'user': user_data
        })
    except Exception as e:
        logger.error(f"Init data error: {str(e)}")
        return jsonify({'status': 'error'}), 500

@app.route('/user-data', methods=['POST'])
def get_user_data():
    try:
        data = request.json
        user_id = str(data.get('user_id'))
        
        if not user_id:
            return jsonify({'status': 'error', 'message': 'user_id required'}), 400

        service = get_sheets_service_with_retry()
        row, _ = get_user_row_and_index(service, user_id)
        if not row:
            return jsonify({'status': 'error', 'message': 'User not found'}), 404
        
        # Récupération des tâches
        tasks = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=RANGES['tasks']
        ).execute().get('values', [])
        
        # Récupération des références
        referrals = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=RANGES['referrals']
        ).execute().get('values', [])
        
        return jsonify({
            'status': 'success',
            'balance': int(row[3]) if len(row) > 3 and row[3] else 0,
            'last_claim': row[4] if len(row) > 4 else None,
            'referral_code': row[5] if len(row) > 5 else user_id,
            'tasks': [
                {
                    'name': task[0],
                    'description': task[1],
                    'reward': int(task[2])
                } for task in tasks if len(task) >= 3
            ],
            'referrals': [
                {
                    'user_id': ref[1],
                    'points': int(ref[2]) if len(ref) > 2 else 0,
                    'date': ref[3] if len(ref) > 3 else None
                } for ref in referrals if len(ref) > 1 and ref[0] == user_id
            ]
        })
    except Exception as e:
        logger.error(f"User data error: {str(e)}")
        return jsonify({'status': 'error'}), 500

@app.route('/get-balance', methods=['POST'])
def get_balance():
    try:
        data = request.get_json()
        user_id = str(data.get('user_id', ''))
        if not user_id:
            return jsonify({'status': 'error', 'message': 'user_id required'}), 400
        service = get_sheets_service_with_retry()
        row, _ = get_user_row_and_index(service, user_id)
        if not row:
            return jsonify({'status': 'error', 'message': 'User not found'}), 404
        balance = int(row[3]) if len(row) > 3 and row[3] else 0
        last_claim = row[4] if len(row) > 4 else None
        referral_code = row[5] if len(row) > 5 else user_id
        return jsonify({
            'status': 'success',
            'balance': balance,
            'last_claim': last_claim,
            'referral_code': referral_code
        })
    except Exception as e:
        logger.error(f"Error in get_balance: {str(e)}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/claim', methods=['POST'])
def claim():
    try:
        data = request.get_json()
        user_id = str(data.get('user_id', ''))
        if not user_id:
            return jsonify({'status': 'error', 'message': 'user_id required'}), 400

        now = datetime.utcnow()
        service = get_sheets_service_with_retry()
        with sheet_lock:
            row, row_number = get_user_row_and_index(service, user_id)
            if not row:
                return jsonify({'status': 'error', 'message': 'User not found'}), 404

            last_claim_str = row[4] if len(row) > 4 else None
            if last_claim_str:
                last_claim = datetime.strptime(last_claim_str, "%Y-%m-%d %H:%M:%S")
                if now - last_claim < timedelta(minutes=CLAIM_COOLDOWN_MINUTES):
                    remaining = timedelta(minutes=CLAIM_COOLDOWN_MINUTES) - (now - last_claim)
                    return jsonify({'status': 'error', 'message': f'Wait {remaining.seconds//60} minutes'}), 403

            new_balance = int(row[3]) + 10 if len(row) > 3 and row[3] else 10
            values = [[
                row[0] if len(row) > 0 else '',
                row[1] if len(row) > 1 else '',
                user_id,
                new_balance,
                now.strftime("%Y-%m-%d %H:%M:%S"),
                row[5] if len(row) > 5 else user_id
            ]]
            service.spreadsheets().values().update(
                spreadsheetId=SPREADSHEET_ID,
                range=f"Users!A{row_number}:F{row_number}",
                valueInputOption="RAW",
                body={"values": values}
            ).execute()
            return jsonify({'status': 'success', 'balance': new_balance})
    except Exception as e:
        logger.error(f"Error in claim: {str(e)}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/get-tasks', methods=['POST'])
def get_tasks():
    try:
        data = request.get_json()
        user_id = str(data.get('user_id', ''))
        if not user_id:
            return jsonify({'status': 'error', 'message': 'user_id required'}), 400

        service = get_sheets_service_with_retry()
        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=RANGES['tasks']
        ).execute()
        tasks = result.get('values', [])

        tasks_data = []
        for task in tasks:
            task_data = {
                'title': task[0] if len(task) > 0 else '',
                'description': task[1] if len(task) > 1 else '',
                'reward': int(task[2]) if len(task) > 2 and task[2].isdigit() else 0,
                'completed': task[3].lower() == 'true' if len(task) > 3 else False
            }
            tasks_data.append(task_data)

        return jsonify({'status': 'success', 'tasks': tasks_data})
    except Exception as e:
        logger.error(f"Error in get_tasks: {str(e)}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/get-referrals', methods=['POST'])
def get_referrals():
    try:
        data = request.get_json()
        user_id = str(data.get('user_id', ''))
        if not user_id:
            return jsonify({'status': 'error', 'message': 'user_id required'}), 400

        service = get_sheets_service_with_retry()
        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=RANGES['referrals']
        ).execute()
        referrals = result.get('values', [])

        user_referrals = [ref for ref in referrals if ref[0] == user_id]

        return jsonify({'status': 'success', 'referrals': user_referrals})
    except Exception as e:
        logger.error(f"Error in get_referrals: {str(e)}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/get-leaderboard', methods=['GET'])
def get_leaderboard():
    try:
        service = get_sheets_service_with_retry()
        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=RANGES['users']
        ).execute()
        users = result.get('values', [])

        leaderboard = []
        for user in users:
            if len(user) >= 4:
                leaderboard.append({
                    'username': user[1],
                    'balance': int(user[3]) if user[3].isdigit() else 0
                })

        leaderboard = sorted(leaderboard, key=lambda x: x['balance'], reverse=True)[:10]

        return jsonify({'status': 'success', 'leaderboard': leaderboard})
    except Exception as e:
        logger.error(f"Error in get_leaderboard: {str(e)}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/watchads', methods=['POST'])
def watch_ads():
    try:
        data = request.get_json()
        user_id = str(data.get('user_id', ''))
        if not user_id:
            return jsonify({'status': 'error', 'message': 'user_id required'}), 400

        service = get_sheets_service_with_retry()
        with sheet_lock:
            row, row_number = get_user_row_and_index(service, user_id)
            if not row:
                return jsonify({'status': 'error', 'message': 'User not found'}), 404

            reward = 5
            new_balance = int(row[3]) + reward if len(row) > 3 and row[3] else reward

            values = [[
                row[0] if len(row) > 0 else '',
                row[1] if len(row) > 1 else '',
                user_id,
                new_balance,
                datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                row[5] if len(row) > 5 else user_id
            ]]
            service.spreadsheets().values().update(
                spreadsheetId=SPREADSHEET_ID,
                range=f"Users!A{row_number}:F{row_number}",
                valueInputOption="RAW",
                body={"values": values}
            ).execute()

        return jsonify({'status': 'success', 'message': 'Ad watched, reward added', 'balance': new_balance})
    except Exception as e:
        logger.error(f"Error in watch_ads: {str(e)}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500

def get_user_row_and_index(service, user_id):
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=RANGES['users']
        ).execute()
        rows = result.get('values', [])
        for i, row in enumerate(rows):
            if len(row) > 2 and str(row[2]) == str(user_id):
                return row, i + 2
        return None, None
    except Exception as e:
        logger.error(f"Error in get_user_row_and_index: {str(e)}")
        raise

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
