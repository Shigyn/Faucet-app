import os
import json
import logging
import time
from flask import Flask, request, jsonify, render_template, send_from_directory
from googleapiclient.discovery import build
from google.oauth2 import service_account
from datetime import datetime, timedelta
from threading import Lock
from flask_cors import CORS
from telegram import Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup
from queue import Queue
from telegram.ext import Dispatcher, CommandHandler, MessageHandler, Filters
import requests

# Désactivation du cache client Google API
import google.api_core
google.api_core.client_options.ClientOptions.disable_cache = True

# Logging configuration
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Variables d'environnement
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SPREADSHEET_ID = os.getenv('GOOGLE_SHEET_ID')

app = Flask(__name__)
CORS(app, resources={
    r"/user-data": {"origins": ["https://web.telegram.org"]},
    r"/claim": {"origins": ["https://web.telegram.org"]},
    r"/get-*": {"origins": ["https://web.telegram.org"]}
})

# CORS headers
@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', 'https://web.telegram.org')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,X-Requested-With')
    response.headers.add('Access-Control-Allow-Methods', 'POST,OPTIONS,GET')
    response.headers.add('Access-Control-Allow-Credentials', 'true')
    return response

# Gunicorn config (si utilisé)
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

def validate_telegram_data(init_data):
    if not init_data:
        return False
    # TODO: Implémenter la validation selon https://core.telegram.org/bots/webapps#validating-data-received-via-the-web-app
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

@app.route('/user-data', methods=['POST', 'OPTIONS'])
def get_user_data():
    if request.method == 'OPTIONS':
        return _build_cors_preflight_response()

    try:
        data = request.get_json()
        if not data:
            return jsonify({'status': 'error', 'message': 'No data'}), 400

        init_data = data.get('initData')
        if not validate_telegram_data(init_data):
            return jsonify({'status': 'error', 'message': 'Invalid Telegram data'}), 403

        user_id = str(data.get('user_id'))
        logger.debug(f"🔎 Recherche user_id: {user_id}")

        service = get_sheets_service_with_retry()
        row, _ = get_user_row_and_index(service, user_id)

        if not row:
            logger.error(f"❌ Utilisateur {user_id} non trouvé")
            return jsonify({'status': 'error', 'message': 'User not found'}), 404

        logger.debug(f"✅ Utilisateur trouvé: {row}")

        tasks = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=RANGES['tasks']
        ).execute().get('values', [])

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
        logger.error(f"Error: {str(e)}")
        return jsonify({'status': 'error'}), 500

def _build_cors_preflight_response():
    response = jsonify({'status': 'cors_preflight'})
    response.headers.add("Access-Control-Allow-Origin", "https://web.telegram.org")
    response.headers.add("Access-Control-Allow-Headers", "Content-Type,Telegram-Data")
    return response

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
        return jsonify({'status': 'success', 'balance': balance})
    except Exception as e:
        logger.error(f"get_balance error: {str(e)}")
        return jsonify({'status': 'error'}), 500

@app.route('/claim', methods=['POST'])
def claim():
    try:
        data = request.get_json()
        user_id = str(data.get('user_id', ''))
        if not user_id:
            return jsonify({'status': 'error', 'message': 'user_id required'}), 400

        service = get_sheets_service_with_retry()

        with sheet_lock:
            row, idx = get_user_row_and_index(service, user_id)
            if not row:
                return jsonify({'status': 'error', 'message': 'User not found'}), 404

            last_claim_str = row[4] if len(row) > 4 else None
            now = datetime.utcnow()

            if last_claim_str:
                try:
                    last_claim_time = datetime.strptime(last_claim_str, "%Y-%m-%d %H:%M:%S")
                    if now < last_claim_time + timedelta(minutes=CLAIM_COOLDOWN_MINUTES):
                        remaining = (last_claim_time + timedelta(minutes=CLAIM_COOLDOWN_MINUTES) - now).total_seconds()
                        return jsonify({
                            'status': 'error',
                            'message': f'Claim cooldown active. Try again in {int(remaining)} seconds.'
                        }), 429
                except Exception as e:
                    logger.warning(f"Invalid last_claim format: {last_claim_str} ({str(e)})")

            new_balance = int(row[3]) + 100  # Example reward
            update_range = f"Users!D{idx + 2}"
            service.spreadsheets().values().update(
                spreadsheetId=SPREADSHEET_ID,
                range=update_range,
                valueInputOption='USER_ENTERED',
                body={'values': [[str(new_balance)]]}
            ).execute()

            update_range_time = f"Users!E{idx + 2}"
            service.spreadsheets().values().update(
                spreadsheetId=SPREADSHEET_ID,
                range=update_range_time,
                valueInputOption='USER_ENTERED',
                body={'values': [[now.strftime("%Y-%m-%d %H:%M:%S")]]}
            ).execute()

            return jsonify({'status': 'success', 'new_balance': new_balance})
    except Exception as e:
        logger.error(f"claim error: {str(e)}")
        return jsonify({'status': 'error'}), 500

def get_user_row_and_index(service, user_id):
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=RANGES['users']
        ).execute()
        rows = result.get('values', [])
        for idx, row in enumerate(rows):
            if len(row) > 0 and row[0] == user_id:
                return row, idx
        return None, None
    except Exception as e:
        logger.error(f"get_user_row_and_index error: {str(e)}")
        return None, None

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
