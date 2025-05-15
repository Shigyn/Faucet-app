import os
import random
import json
import logging
from flask import Flask, request, jsonify, render_template
from googleapiclient.discovery import build
from google.oauth2 import service_account
from datetime import datetime, timedelta
from threading import Lock, Thread
from flask_cors import CORS
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, ContextTypes

app = Flask(__name__)
CORS(app)

# Configuration logging
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

# Initialisation bot Telegram
telegram_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

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
    url = f"https://t.me/CRYPTORATS_BOT?start=ref_{user_id}"
    button = InlineKeyboardButton(text="🚀 Lancer le bot", url=url)
    keyboard = InlineKeyboardMarkup([[button]])
    return keyboard

async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Commande /start reçue de {update.effective_user.id}")
    
    if update.effective_user.is_bot:
        await update.message.reply_text("❌ Les bots ne peuvent pas s'inscrire.")
        return

    try:
        user_id = str(update.effective_user.id)
        username = update.effective_user.username or f"User{user_id[:5]}"
        
        # Nouvelle logique pour récupérer le referral_id
        referral_id = None
        if context.args:
            # Gère les formats: /start 12345 et /start ref_12345
            referral_arg = context.args[0]
            if referral_arg.startswith('ref_'):
                referral_id = referral_arg[4:] # Enlève le préfixe ref_
            else:
                referral_id = referral_arg # Prend directement l'ID

        logger.info(f"[START] Utilisateur: {user_id}, Parrain: {referral_id}")
        service = get_sheets_service()

        users_data = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=RANGES['users']
        ).execute()
        users = users_data.get('values', [])

        user_exists = any(len(row) > 2 and row[2] == user_id for row in users)
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        if not user_exists:
            new_user = [
                now_str,
                username,
                user_id,
                '0',
                '',
                referral_id if referral_id else ''
            ]
            service.spreadsheets().values().append(
                spreadsheetId=SPREADSHEET_ID,
                range=RANGES['users'],
                valueInputOption='USER_ENTERED',
                body={'values': [new_user]}
            ).execute()

            if referral_id:
                referrer_row_index = None
                referrer_balance = 0.0
                for i, row in enumerate(users):
                    if len(row) > 2 and row[2] == referral_id:
                        referrer_row_index = i
                        referrer_balance = float(row[3]) if len(row) > 3 else 0.0
                        break

                if referrer_row_index is not None:
                    bonus_points = 1.0
                    new_balance = referrer_balance + bonus_points
                    service.spreadsheets().values().update(
                        spreadsheetId=SPREADSHEET_ID,
                        range=f"{RANGES['users']}!D{referrer_row_index + 2}",
                        valueInputOption='USER_ENTERED',
                        body={'values': [[str(new_balance)]]}
                    ).execute()

                    service.spreadsheets().values().append(
                        spreadsheetId=SPREADSHEET_ID,
                        range=RANGES['referrals'],
                        valueInputOption='USER_ENTERED',
                        body={'values': [[
                            referral_id,
                            user_id,
                            '0',
                            str(bonus_points),
                            now_str
                        ]]}
                    ).execute()
                else:
                    logger.warning(f"⚠️ ID de parrain invalide ou non trouvé: {referral_id}")

        # Modification du bouton pour utiliser le nouveau format
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(
            text="🚀 Lancer le bot",
            url=f"https://t.me/CRYPTORATS_BOT?start=ref_{user_id}"
        )]])
        
        await update.message.reply_text(
            "🎉 Bienvenue dans TronQuest Airdrop!\n"
            f"🆔 Ton ID: `{user_id}`\n"
            f"🤝 Parrain: `{referral_id if referral_id else 'Aucun'}`\n\n"
            "🔗 Partage ton lien de parrainage:\n"
            f"`https://t.me/CRYPTORATS_BOT?start=ref_{user_id}`\n\n"
            "🚀 Clique sur le bouton ci-dessous pour commencer.",
            parse_mode='Markdown',
            reply_markup=keyboard,
            disable_web_page_preview=True
        )

    except Exception as e:
        logger.error(f"[ERREUR] handle_start: {str(e)}", exc_info=True)
        await update.message.reply_text("❌ Une erreur est survenue. Contacte le support.")

# Ajout du handler pour la commande /start
telegram_app.add_handler(CommandHandler("start", handle_start))

# Fonction main pour démarrer le bot
async def main():
    await telegram_app.start()
    print("Bot démarré !")
    await telegram_app.run_polling()

@app.route('/update-user', methods=['POST'])
def update_user():
    try:
        data = request.json

        user_id = str(data.get('user_id'))
        username = data.get('username', 'User')
        referrer_id = str(data.get('referrer_id') or '')
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        service = get_sheets_service()
        user_data = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=RANGES['users']
        ).execute()
        user_rows = user_data.get('values', [])

        user_exists = any(len(row) > 2 and row[2] == user_id for row in user_rows)

        if not user_exists:
            new_user_row = [
                now_str,
                username,
                user_id,
                '0',
                '',
                referrer_id
            ]
            service.spreadsheets().values().append(
                spreadsheetId=SPREADSHEET_ID,
                range=RANGES['users'],
                valueInputOption='USER_ENTERED',
                body={'values': [new_user_row]}
            ).execute()

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
    return render_template('index.html')

@app.route('/claim', methods=['POST'])
def claim():
    try:
        data = request.json
        user_id = str(data.get('user_id'))
        referrer_id = data.get('referrer_id')

        now = datetime.now()
        now_str = now.strftime('%Y-%m-%d %H:%M:%S')
        cooldown_minutes = 5

        service = get_sheets_service()

        referrals_data = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=RANGES['referrals']
        ).execute().get('values', [])

        if referrer_id:
            for row in referrals_data:
                if len(row) > 2 and row[1] == user_id and row[0] == referrer_id:
                    last_claim_time = datetime.strptime(row[4], '%Y-%m-%d %H:%M:%S') if len(row) > 4 else None
                    if last_claim_time and (now - last_claim_time) < timedelta(minutes=cooldown_minutes):
                        return jsonify({'status': 'error', 'message': 'Cooldown actif. Merci de patienter.'})

            # On ajoute la récompense
            bonus_points = random.randint(2, 5)
            updated = False

            with sheet_lock:
                users_data = service.spreadsheets().values().get(
                    spreadsheetId=SPREADSHEET_ID,
                    range=RANGES['users']
                ).execute()

                for i, row in enumerate(users_data.get('values', [])):
                    if len(row) > 2 and row[2] == referrer_id:
                        row_num = i + 2
                        current_balance = int(row[3]) if len(row) > 3 else 0
                        new_balance = current_balance + bonus_points

                        service.spreadsheets().values().update(
                            spreadsheetId=SPREADSHEET_ID,
                            range=f'Users!D{row_num}',
                            valueInputOption='USER_ENTERED',
                            body={'values': [[str(new_balance)]]}
                        ).execute()

                        # Met à jour la date de claim dans referrals
                        for j, rrow in enumerate(referrals_data):
                            if len(rrow) > 1 and rrow[0] == referrer_id and rrow[1] == user_id:
                                row_referral_num = j + 2
                                service.spreadsheets().values().update(
                                    spreadsheetId=SPREADSHEET_ID,
                                    range=f'Referrals!E{row_referral_num}',
                                    valueInputOption='USER_ENTERED',
                                    body={'values': [[now_str]]}
                                ).execute()
                                updated = True
                                break
                        break

            if updated:
                return jsonify({'status': 'success', 'message': f'Vous avez gagné {bonus_points} points!'})

        return jsonify({'status': 'error', 'message': 'Réclamation non valide.'})

    except Exception as e:
        logger.error(f"Erreur claim: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

def start_flask():
    app.run(host='0.0.0.0', port=5000, debug=True)

def start_telegram_bot():
    telegram_app.add_handler(CommandHandler('start', handle_start))
    telegram_app.run_polling()

if __name__ == '__main__':
    from threading import Thread
    Thread(target=start_flask).start()
    Thread(target=start_telegram_bot).start()
