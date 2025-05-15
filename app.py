import os
import random
import json
import logging
from flask import Flask, request, jsonify, render_template
from googleapiclient.discovery import build
from google.oauth2 import service_account
from datetime import datetime, timedelta
from threading import Lock, Thread
import hashlib
import hmac
from flask_cors import CORS
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from telegram import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

app = Flask(__name__)
CORS(app)

# Configuration
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SPREADSHEET_ID = os.getenv('GOOGLE_SHEET_ID')

RANGES = {
    'users': 'Users!A2:F',
    'transactions': 'Transactions!A2:D',
    'tasks': 'Tasks!A2:D',
    'referrals': 'Referrals!A2:E'
}

sheet_lock = Lock()

# Initialisation du bot Telegram
telegram_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

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

def build_inline_start_button(user_id: str):
    """
    Crée un bouton inline Telegram avec un lien qui inclut l'user_id dans l'URL.
    """
    url = f"https://t.me/CRYPTORATS_BOT?start=ref_{user_id}"
    button = InlineKeyboardButton(text="🚀 Lancer le bot", url=url)
    keyboard = InlineKeyboardMarkup([[button]])
    return keyboard

async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.is_bot:
        await update.message.reply_text("❌ Les bots ne peuvent pas s'inscrire.")
        return

    try:
        user_id = str(update.effective_user.id)
        username = update.effective_user.username or f"User{user_id[:5]}"
        referral_id = context.args[0] if context.args else None

        logger.info(f"[START] Utilisateur: {user_id}, Parrain: {referral_id}")
        service = get_sheets_service()

        # Récupère tous les utilisateurs
        users_data = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=RANGES['users']
        ).execute()
        users = users_data.get('values', [])

        # Vérifie si l'utilisateur existe déjà
        user_exists = any(row[2] == user_id for row in users if len(row) > 2)
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        if not user_exists:
            # Ajout du nouvel utilisateur
            new_user = [
                now_str,       # Date inscription
                username,
                user_id,
                '0',           # Solde initial
                '',            # Dernier claim
                referral_id if referral_id else ''  # ID du parrain
            ]
            service.spreadsheets().values().append(
                spreadsheetId=SPREADSHEET_ID,
                range=RANGES['users'],
                valueInputOption='USER_ENTERED',
                body={'values': [new_user]}
            ).execute()

            if referral_id:
                # Cherche le parrain
                referrer_row_index = None
                referrer_balance = 0.0
                for i, row in enumerate(users):
                    if len(row) > 2 and row[2] == referral_id:
                        referrer_row_index = i
                        referrer_balance = float(row[3]) if len(row) > 3 else 0.0
                        break

                if referrer_row_index is not None:
                    # Bonus fixe de 1.0 au parrain
                    bonus_points = 1.0

                    # Met à jour le solde du parrain
                    new_balance = referrer_balance + bonus_points
                    service.spreadsheets().values().update(
                        spreadsheetId=SPREADSHEET_ID,
                        range=f"{RANGES['users']}!D{referrer_row_index + 1}",
                        valueInputOption='USER_ENTERED',
                        body={'values': [[str(new_balance)]]}
                    ).execute()

                    # Enregistre le parrainage
                    service.spreadsheets().values().append(
                        spreadsheetId=SPREADSHEET_ID,
                        range=RANGES['referrals'],
                        valueInputOption='USER_ENTERED',
                        body={'values': [[
                            referral_id,        # ID du parrain
                            user_id,            # ID du filleul
                            '0',                # Solde du filleul à l'inscription
                            str(bonus_points),  # Points gagnés par le parrain
                            now_str             # Date
                        ]]}
                    ).execute()
                else:
                    logger.warning(f"⚠️ ID de parrain invalide ou non trouvé: {referral_id}")

        # Message de bienvenue avec bouton inline qui inclut user_id
        keyboard = build_inline_start_button(user_id)
        await update.message.reply_text(
            "🎉 Bienvenue dans TronQuest Airdrop!\n"
            f"🆔 Ton ID: `{user_id}`\n"
            f"🤝 Parrain: `{referral_id if referral_id else 'Aucun'}`\n\n"
            f"🚀 Clique sur le bouton ci-dessous pour commencer.",
            parse_mode='Markdown',
            reply_markup=keyboard,
            disable_web_page_preview=True
        )

    except Exception as e:
        logger.error(f"[ERREUR] handle_start: {str(e)}", exc_info=True)
        await update.message.reply_text("❌ Une erreur est survenue. Contacte le support.")

@app.route('/update-user', methods=['POST'])
def update_user():
    try:
        data = request.json

        user_id = str(data.get('user_id'))
        username = data.get('username', 'User')
        referrer_id = str(data.get('referrer_id') or '')  # <-- plus clair
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        service = get_sheets_service()

        # Récupérer la liste des utilisateurs
        user_data = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=RANGES['users']
        ).execute()
        user_rows = user_data.get('values', [])

        # Vérifie si l'utilisateur existe déjà (colonne 2 = user_id)
        user_exists = any(len(row) > 2 and row[2] == user_id for row in user_rows)

        if not user_exists:
            new_user_row = [
                now_str,         # Date de création
                username,        # Nom d'utilisateur
                user_id,         # ID utilisateur
                '0',             # Balance initiale
                '',              # Dernier claim (vide)
                referrer_id      # ID du parrain (si transmis)
            ]

            # Ajoute l'utilisateur dans la feuille "users"
            service.spreadsheets().values().append(
                spreadsheetId=SPREADSHEET_ID,
                range=RANGES['users'],
                valueInputOption='USER_ENTERED',
                body={'values': [new_user_row]}
            ).execute()

            # Si un parrain est présent, l’ajouter dans la feuille "referrals"
            if referrer_id:
                referral_row = [referrer_id, user_id, '0', now_str]
                service.spreadsheets().values().append(
                    spreadsheetId=SPREADSHEET_ID,
                    range=RANGES['referrals'],
                    valueInputOption='USER_ENTERED',
                    body={'values': [referral_row]}
                ).execute()

        return jsonify({
            'status': 'success',
            'user_id': user_id,
            'username': username
        })

    except Exception as e:
        logger.error(f"Erreur update_user: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

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

@app.route('/')
def home():
    return render_template('index.html')  # Si tu veux afficher un fichier HTML spécifique

@app.route('/claim', methods=['POST'])
def claim():
    try:
        data = request.json
        user_id = str(data.get('user_id'))
        referrer_id = data.get('referrer_id')  # Récupérer le referrer_id depuis la requête
        
        now = datetime.now()
        now_str = now.strftime('%Y-%m-%d %H:%M:%S')
        cooldown_minutes = 5

        service = get_sheets_service()

        # 1. Vérifier si l'utilisateur a un parrain
        referrals_data = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=RANGES['referrals']
        ).execute().get('values', [])

        # Logique pour vérifier le parrain (ancien utilisateur)
        if referrer_id:
            # Si referrer_id est présent, vérifie et enregistre
            for row in referrals_data:
                if len(row) >= 2 and row[1] == user_id:  # row[1] = referred_id
                    referrer_id = row[0]  # row[0] = referrer_id
                    break

        # 2. Générer les points
        points = random.randint(10, 100)
        referrer_bonus = int(points * 0.05) if referrer_id else 0  # 5% pour le parrain

        with sheet_lock:
            # 3. Mise à jour de l'utilisateur
            users_data = service.spreadsheets().values().get(
                spreadsheetId=SPREADSHEET_ID,
                range=RANGES['users']
            ).execute().get('values', [])

            user_row = next((row for row in users_data if len(row) > 2 and row[2] == user_id), None)

            if user_row:
                row_num = users_data.index(user_row) + 2
                current_balance = int(user_row[3]) if len(user_row) > 3 else 0
                new_balance = current_balance + points

                service.spreadsheets().values().update(
                    spreadsheetId=SPREADSHEET_ID,
                    range=f'Users!D{row_num}:E{row_num}',
                    valueInputOption='USER_ENTERED',
                    body={'values': [[str(new_balance), now_str]]}
                ).execute()
            else:
                # Nouvel utilisateur : créer une entrée
                new_user = [
                    now_str,
                    data.get('username', f'User{user_id[:5]}'),
                    user_id,
                    str(points),
                    now_str,
                    referrer_id if referrer_id else ''
                ]
                service.spreadsheets().values().append(
                    spreadsheetId=SPREADSHEET_ID,
                    range=RANGES['users'],
                    valueInputOption='USER_ENTERED',
                    body={'values': [new_user]}
                ).execute()
                new_balance = points  # nécessaire pour le return

            # 4. Mise à jour du parrain si existe
            if referrer_id:
                referrer_row = next((row for row in users_data if len(row) > 2 and row[2] == referrer_id), None)
                if referrer_row:
                    ref_row_num = users_data.index(referrer_row) + 2
                    ref_current_balance = int(referrer_row[3]) if len(referrer_row) > 3 else 0
                    ref_new_balance = ref_current_balance + referrer_bonus

                    service.spreadsheets().values().update(
                        spreadsheetId=SPREADSHEET_ID,
                        range=f'Users!D{ref_row_num}',
                        valueInputOption='USER_ENTERED',
                        body={'values': [[str(ref_new_balance)]]}
                    ).execute()

                    # Mettre à jour le bonus dans la table Referrals
                    for i, row in enumerate(referrals_data):
                        if len(row) >= 2 and row[0] == referrer_id and row[1] == user_id:
                            referral_row_num = i + 2
                            current_bonus = int(row[2]) if len(row) > 2 and row[2].isdigit() else 0
                            new_bonus = current_bonus + referrer_bonus

                            service.spreadsheets().values().update(
                                spreadsheetId=SPREADSHEET_ID,
                                range=f'Referrals!C{referral_row_num}',
                                valueInputOption='USER_ENTERED',
                                body={'values': [[str(new_bonus)]]}
                            ).execute()
                            break
                    
                    # Ajouter dans Referrals si manquant
                    if not any(row for row in referrals_data if len(row) >= 2 and row[0] == referrer_id and row[1] == user_id):
                        service.spreadsheets().values().append(
                            spreadsheetId=SPREADSHEET_ID,
                            range=RANGES['referrals'],
                            valueInputOption='USER_ENTERED',
                            body={'values': [[referrer_id, user_id, str(referrer_bonus), now_str]]}
                        ).execute()

            # 5. Enregistrer la transaction
            service.spreadsheets().values().append(
                spreadsheetId=SPREADSHEET_ID,
                range=RANGES['transactions'],
                valueInputOption='USER_ENTERED',
                body={'values': [[user_id, str(points), 'claim', now_str]]}
            ).execute()

            if referrer_id:
                service.spreadsheets().values().append(
                    spreadsheetId=SPREADSHEET_ID,
                    range=RANGES['transactions'],
                    valueInputOption='USER_ENTERED',
                    body={'values': [[referrer_id, str(referrer_bonus), 'referral_bonus', now_str]]}
                ).execute()

        return jsonify({
            'status': 'success',
            'new_balance': new_balance,
            'last_claim': now_str,
            'points_earned': points,
            'referrer_bonus': referrer_bonus if referrer_id else 0,
            'cooldown_end': (now + timedelta(minutes=cooldown_minutes)).timestamp()
        })

    except Exception as e:
        logger.error(f"Erreur claim: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e),
            'error_type': type(e).__name__
        }), 500

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
        total_bonus = 0

        for row in result.get('values', []):
            if len(row) >= 3 and row[0] == user_id:
                try:
                    bonus = int(row[2])
                except ValueError:
                    bonus = 0

                total_bonus += bonus
                referrals.append({
                    'user_id': row[1],
                    'points_earned': bonus,
                    'timestamp': row[3] if len(row) > 3 else None
                })

        return jsonify({
            'status': 'success',
            'referrals': referrals,
            'total_bonus': total_bonus
        })

    except Exception as e:
        logger.error(f"Erreur get_referrals: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/add-referral', methods=['POST'])
def add_referral():
    try:
        data = request.json
        referrer_id = str(data.get('referrer_id'))
        referred_id = str(data.get('referred_id'))
        
        service = get_sheets_service()
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # 1. Enregistrez dans Referrals
        service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range='Referrals!A2:D',
            valueInputOption='USER_ENTERED',
            body={'values': [[referrer_id, referred_id, 0, now]]}
        ).execute()

        # 2. Mettez à jour le ReferralCode dans Users
        users_data = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range='Users!A2:F'
        ).execute().get('values', [])

        for i, row in enumerate(users_data):
            if len(row) > 2 and row[2] == referred_id:  # Trouver le user par User_ID
                service.spreadsheets().values().update(
                    spreadsheetId=SPREADSHEET_ID,
                    range=f'Users!F{i+2}',  # Colonne F = ReferralCode
                    valueInputOption='USER_ENTERED',
                    body={'values': [[referrer_id]]}
                ).execute()
                break

        return jsonify({'status': 'success'})
    except Exception as e:
        logger.error(f"Erreur add_referral: {str(e)}")
        return jsonify({'status': 'error'}), 500

def run_bot():
    """Fonction pour lancer le bot Telegram en parallèle"""
    telegram_app.add_handler(CommandHandler("start", handle_start))
    telegram_app.run_polling()

if __name__ == '__main__':
    # Démarrer le bot Telegram dans un thread séparé
    bot_thread = Thread(target=run_bot)
    bot_thread.start()
    
    # Démarrer le serveur Flask
    app.run(host='0.0.0.0', port=10000)