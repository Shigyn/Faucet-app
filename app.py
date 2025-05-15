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
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from queue import Queue
from telegram.ext import Dispatcher, CommandHandler, MessageHandler, Filters

# === Flask app + CORS ===
app = Flask(__name__)
CORS(app)

# === Logging config ===
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# === Config vars ===
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SPREADSHEET_ID = os.getenv('GOOGLE_SHEET_ID')

# === Telegram Bot + Dispatcher ===
bot = Bot(token=TELEGRAM_BOT_TOKEN)
update_queue = Queue()
dispatcher = Dispatcher(bot, update_queue, use_context=True)  # Dispatcher doit être défini AVANT handlers

# === Constants ===
RANGES = {
    'users': 'Users!A2:F',
    'transactions': 'Transactions!A2:D',
    'tasks': 'Tasks!A2:D',
    'referrals': 'Referrals!A2:D'
}

sheet_lock = Lock()  # Verrou pour accès Sheets

# === Telegram Handlers ===

def log_all(update, context):
    logger.info(f"Update reçu: {update}")

dispatcher.add_handler(MessageHandler(Filters.all, log_all))  # Log toutes les updates

def start_command(update, context):
    logger.info(f"/start reçu de {update.effective_user.id} avec args={context.args}")
    if update.message is None:
        logger.error("update.message est None, impossible d'envoyer le message")
        return
        
    args = context.args
    refid = args[0] if args else None
    
    base_url = "https://faucet-app.onrender.com"
    if refid:
        url = f"{base_url}/?refid={refid}"  # URL avec refid
    else:
        url = base_url

    keyboard = [
        [InlineKeyboardButton("Open App", url=url)]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_text = "Bienvenue sur TronQuest Airdrop! Collectez vos tokens chaque jour."
    
    update.message.reply_text(
        text=welcome_text,
        reply_markup=reply_markup
    )
    
    if refid:
        logger.info(f"Nouvel utilisateur via referral {refid}")
        # Appel possible à import_referral ici

dispatcher.add_handler(CommandHandler("start", start_command))  # Handler /start

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
    update = Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(update)  # Process Telegram update
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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
