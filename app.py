import os
import random
import telebot
from flask import Flask, request, render_template, jsonify
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta
from threading import Thread
from urllib.parse import quote

app = Flask(__name__, template_folder='templates')

# Config
TELEGRAM_BOT_API_KEY = os.getenv('TELEGRAM_BOT_API_KEY')
GOOGLE_SHEET_ID = os.getenv('GOOGLE_SHEET_ID')
USER_RANGE = "Users!A2:F"  # user_id | balance | last_claim | referrer_id | username | referral_code
TRANSACTION_RANGE = "Transactions!A2:D"  # user_id | action | points | timestamp
TASKS_RANGE = "Tasks!A2:D"  # task_name | description | points | url
PUBLIC_URL = os.getenv('PUBLIC_URL')

# Vérification des variables
if not all([TELEGRAM_BOT_API_KEY, GOOGLE_SHEET_ID, PUBLIC_URL]):
    raise ValueError("Variables d'environnement manquantes")

bot = telebot.TeleBot(TELEGRAM_BOT_API_KEY)
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

def get_google_sheets_service():
    creds_json = os.environ.get('GOOGLE_CREDS')
    if not creds_json:
        raise Exception("GOOGLE_CREDS manquant")
    creds = Credentials.from_service_account_info(eval(creds_json), scopes=SCOPES)
    return build('sheets', 'v4', credentials=creds).spreadsheets()

def generate_referral_code(user_id):
    return f"REF-{user_id}-{random.randint(1000,9999)}"

@app.route('/')
def home():
    """Route racine pour éviter les 404"""
    return render_template('index.html')

@app.route('/get-balance', methods=['POST'])
def get_balance():
    data = request.get_json()
    user_id = data.get('user_id')
    if not user_id:
        return jsonify({"error": "ID utilisateur manquant"}), 400
    
    try:
        service = get_google_sheets_service()
        result = service.values().get(
            spreadsheetId=GOOGLE_SHEET_ID,
            range=USER_RANGE
        ).execute()
        
        for row in result.get('values', []):
            if str(row[0]) == str(user_id):
                return jsonify({
                    "balance": int(row[1]) if len(row) > 1 and row[1] else 0,
                    "last_claim": row[2] if len(row) > 2 else None,
                    "referral_code": row[5] if len(row) > 5 else generate_referral_code(user_id),
                    "referral_url": f"{PUBLIC_URL}?ref={quote(row[5])}" if len(row) > 5 else ""
                })
        
        return jsonify({"balance": 0, "last_claim": None})
    
    except Exception as e:
        print(f"Erreur get-balance: {str(e)}")
        return jsonify({"error": "Erreur serveur"}), 500

@app.route('/claim', methods=['POST'])
def claim():
    data = request.get_json()
    user_id = data.get('user_id')
    referrer_code = data.get('referrer_code')
    
    if not user_id:
        return jsonify({"error": "ID utilisateur manquant"}), 400

    try:
        service = get_google_sheets_service()
        now = datetime.now().strftime("%d/%m/%Y %H:%M")
        points = random.randint(10, 100)
        referral_bonus = 0

        # Vérification délai entre claims
        result = service.values().get(
            spreadsheetId=GOOGLE_SHEET_ID,
            range=USER_RANGE
        ).execute()
        
        for row in result.get('values', []):
            if str(row[0]) == str(user_id) and len(row) > 2 and row[2]:
                last_claim = datetime.strptime(row[2], "%d/%m/%Y %H:%M")
                if (datetime.now() - last_claim) < timedelta(minutes=5):
                    return jsonify({"error": "Attends 5 minutes entre chaque réclamation"}), 400

        # Gestion parrainage
        if referrer_code:
            for row in result.get('values', []):
                if len(row) > 5 and row[5] == referrer_code:
                    referral_bonus = int(points * 0.05)
                    break

        # Mise à jour utilisateur
        service.values().append(
            spreadsheetId=GOOGLE_SHEET_ID,
            range=USER_RANGE,
            valueInputOption="USER_ENTERED",
            body={"values": [[user_id, points, now, "", "", generate_referral_code(user_id)]]},
            insertDataOption="INSERT_ROWS"
        ).execute()

        # Enregistrement transaction
        service.values().append(
            spreadsheetId=GOOGLE_SHEET_ID,
            range=TRANSACTION_RANGE,
            valueInputOption="USER_ENTERED",
            body={"values": [[user_id, "claim", points, now]]},
            insertDataOption="INSERT_ROWS"
        ).execute()

        return jsonify({
            "success": f"{points} points ajoutés !",
            "new_balance": points,
            "referral_bonus": referral_bonus
        })

    except Exception as e:
        print(f"Erreur claim: {str(e)}")
        return jsonify({"error": "Erreur serveur"}), 500

@app.route('/complete-task', methods=['POST'])
def complete_task():
    data = request.get_json()
    user_id = data.get('user_id')
    task_name = data.get('task_name')
    points = int(data.get('points', 0))

    if not all([user_id, task_name, points]):
        return jsonify({"error": "Données manquantes"}), 400

    try:
        service = get_google_sheets_service()
        now = datetime.now().strftime("%d/%m/%Y %H:%M")

        # 1. Mettre à jour le solde
        result = service.values().get(
            spreadsheetId=GOOGLE_SHEET_ID,
            range=USER_RANGE
        ).execute()
        
        updated = False
        for idx, row in enumerate(result.get('values', [])):
            if str(row[0]) == str(user_id):
                new_balance = (int(row[1]) if len(row) > 1 and row[1] else 0) + points
                service.values().update(
                    spreadsheetId=GOOGLE_SHEET_ID,
                    range=f"Users!B{idx+2}",
                    valueInputOption="USER_ENTERED",
                    body={"values": [[new_balance]]}
                ).execute()
                updated = True
                break

        if not updated:
            return jsonify({"error": "Utilisateur non trouvé"}), 404

        # 2. Enregistrer la transaction
        service.values().append(
            spreadsheetId=GOOGLE_SHEET_ID,
            range=TRANSACTION_RANGE,
            valueInputOption="USER_ENTERED",
            body={"values": [[user_id, "task", points, now]]},
            insertDataOption="INSERT_ROWS"
        ).execute()

        # 3. Notification Telegram
        try:
            bot.send_message(
                user_id,
                f"✅ Tâche complétée : *{task_name}*\n"
                f"➔ Points reçus : +{points}\n\n"
                f"Merci pour ta participation !",
                parse_mode="Markdown"
            )
        except Exception as e:
            print(f"Erreur notification Telegram: {str(e)}")

        return jsonify({
            "success": f"Tâche '{task_name}' validée !",
            "points_credited": points
        })

    except Exception as e:
        print(f"Erreur complete-task: {str(e)}")
        return jsonify({"error": "Erreur serveur"}), 500

@app.route('/get-tasks')
def get_tasks():
    try:
        service = get_google_sheets_service()
        result = service.values().get(
            spreadsheetId=GOOGLE_SHEET_ID,
            range=TASKS_RANGE
        ).execute()
        
        tasks = []
        for row in result.get('values', []):
            if len(row) >= 3:
                tasks.append({
                    "task_name": row[0],
                    "description": row[1],
                    "points": int(row[2]) if row[2] else 0,
                    "url": row[3] if len(row) > 3 else "#"
                })
        return jsonify(tasks)
    
    except Exception as e:
        print(f"Erreur get-tasks: {str(e)}")
        return jsonify({"error": "Erreur serveur"}), 500

@app.route('/get-telegram-user')
def get_telegram_user():
    """Debug endpoint pour vérifier l'utilisateur Telegram"""
    from flask import request
    return jsonify({
        "is_telegram": "Telegram" in request.headers.get('User-Agent', ''),
        "headers": dict(request.headers),
        "note": "Cette route aide à debugger les problèmes d'authentification WebApp"
    })

@bot.message_handler(commands=['start'])
def start(message):
    ref_code = None
    if len(message.text.split()) > 1:
        ref_code = message.text.split()[1]
    
    start_url = f"{PUBLIC_URL}?ref={quote(ref_code)}" if ref_code else PUBLIC_URL
    bot.send_message(
        message.chat.id,
        f"🪙 *CRYPTORATS_bot* 🐭\n\n"
        f"Gagne des points en complétant des tâches !\n"
        f"Commence ici : {start_url}",
        parse_mode="Markdown",
        disable_web_page_preview=True
    )

if __name__ == "__main__":
    # Démarrer le bot Telegram
    Thread(target=bot.polling, daemon=True, kwargs={'none_stop': True}).start()
    
    # Démarrer le serveur Flask
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)