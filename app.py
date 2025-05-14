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
    'referrals': 'Referrals!A2:D'
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

async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = str(update.effective_user.id)
        username = update.effective_user.username or f"User{user_id[:5]}"
        referral_id = context.args[0] if context.args else None
        
        logger.info(f"Nouvel utilisateur: {user_id}, parrain: {referral_id}")
        
        service = get_sheets_service()
        
        # Vérifier si l'utilisateur existe déjà
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
                '0',  # Balance
                '',   # Last claim
                referral_id if referral_id else ''  # Referral ID
            ]
            
            # Ajouter le nouvel utilisateur
            service.spreadsheets().values().append(
                spreadsheetId=SPREADSHEET_ID,
                range=RANGES['users'],
                valueInputOption='USER_ENTERED',
                body={'values': [new_user]}
            ).execute()
            
            if referral_id:
                # Récupérer le solde actuel du parrain
                referrer_data = service.spreadsheets().values().get(
                    spreadsheetId=SPREADSHEET_ID,
                    range=f"{RANGES['users']}!C:D"
                ).execute()
                
                referrer_balance = '0'
                for row in referrer_data.get('values', []):
                    if len(row) > 1 and row[0] == referral_id:
                        referrer_balance = row[1]
                        break
                
                # Calculer les 10% que gagne le parrain
                points_gagnes = float(referrer_balance) * 0.1
                
                # Enregistrer le parrainage avec les nouvelles colonnes
                service.spreadsheets().values().append(
                    spreadsheetId=SPREADSHEET_ID,
                    range=RANGES['referrals'],
                    valueInputOption='USER_ENTERED',
                    body={'values': [[
                        referral_id,       # Referrer_ID
                        user_id,            # Referred_ID
                        referrer_balance,   # Total_Ref_Points (solde du filleul)
                        str(points_gagnes), # Points_gagnés (10% du solde du filleul)
                        datetime.now().strftime('%Y-%m-%d %H:%M:%S')  # Date
                    ]]}
                ).execute()
                
                # Mettre à jour le solde du parrain
                # (On suppose que la colonne Balance est la 4ème colonne - index 3)
                cells = service.spreadsheets().values().get(
                    spreadsheetId=SPREADSHEET_ID,
                    range=RANGES['users'],
                ).execute()
                
                for i, row in enumerate(cells.get('values', [])):
                    if len(row) > 2 and row[2] == referral_id:
                        # Trouvé le parrain, mettre à jour son solde
                        new_balance = float(row[3]) + points_gagnes
                        service.spreadsheets().values().update(
                            spreadsheetId=SPREADSHEET_ID,
                            range=f"{RANGES['users']}!D{i+1}",  # Colonne D (balance)
                            valueInputOption='USER_ENTERED',
                            body={'values': [[str(new_balance)]]}
                        ).execute()
                        break
        
        await update.message.reply_text(
            "🎉 Bienvenue dans TronQuest Airdrop!\n"
            f"Ton ID: {user_id}\n"
            f"Parrain: {referral_id if referral_id else 'Aucun'}\n\n"
            "Clique ici pour commencer: https://ton-lien-webapp.com"
        )
        
    except Exception as e:
        logger.error(f"Erreur dans handle_start: {str(e)}")
        await update.message.reply_text("❌ Une erreur est survenue. Contacte le support.")

@app.route('/update-user', methods=['POST'])
def update_user():
    try:
        data = request.json
        user_id = str(data.get('user_id'))
        username = data.get('username', 'User')
        referrer_id = str(data.get('referrer_id', ''))  # Ajoutez ceci
        
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
                referrer_id if referrer_id else ''  # Modifiez cette ligne
            ]
            service.spreadsheets().values().append(
                spreadsheetId=SPREADSHEET_ID,
                range=RANGES['users'],
                valueInputOption='USER_ENTERED',
                body={'values': [new_user]}
            ).execute()
            
            # Si referrer_id existe, ajoutez une entrée dans Referrals
            if referrer_id:
                service.spreadsheets().values().append(
                    spreadsheetId=SPREADSHEET_ID,
                    range=RANGES['referrals'],
                    valueInputOption='USER_ENTERED',
                    body={'values': [[referrer_id, user_id, '0', datetime.now().strftime('%Y-%m-%d %H:%M:%S')]]}
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
        referrer_bonus = int(points * 0.1) if referrer_id else 0  # 10% pour le parrain

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
                bonus = int(row[2]) if row[2].isdigit() else 0
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
        return jsonify({'status': 'error'}), 500

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