import os
import random
import telebot
from flask import Flask, request, render_template, jsonify
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta
from threading import Thread
from urllib.parse import quote

app = Flask(__name__)

# Config
TELEGRAM_BOT_API_KEY = os.getenv('TELEGRAM_BOT_API_KEY')
GOOGLE_SHEET_ID = os.getenv('GOOGLE_SHEET_ID')
USER_RANGE = "Users!A2:F"
TRANSACTION_RANGE = "Transactions!A2:D"
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

        # 1. Mettre à jour le solde utilisateur
        user_result = service.values().get(
            spreadsheetId=GOOGLE_SHEET_ID,
            range=USER_RANGE,
            majorDimension="ROWS"
        ).execute()
        user_values = user_result.get('values', [])

        updated = False
        for idx, row in enumerate(user_values):
            if str(row[0]) == str(user_id):
                current_balance = int(row[1]) if len(row) > 1 and row[1] else 0
                new_balance = current_balance + points

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

        # 3. Notifier l'utilisateur via Telegram
        try:
            bot.send_message(
                user_id,
                f"🎉 Tâche validée : {task_name}\n"
                f"➕ {points} points ajoutés à ton solde !",
                parse_mode="Markdown"
            )
        except Exception as e:
            print(f"Erreur Telegram: {str(e)}")

        return jsonify({
            "success": f"{points} points ajoutés pour la tâche '{task_name}'",
            "new_balance": new_balance
        })

    except Exception as e:
        print(f"Erreur Sheets: {str(e)}")
        return jsonify({"error": "Erreur serveur"}), 500

# [...] (Conserve TOUS tes autres endpoints existants ici - /claim, /get-balance, etc.)

@bot.message_handler(commands=['start'])
def start(message):
    ref_code = None
    if len(message.text.split()) > 1:
        ref_code = message.text.split()[1]
    
    start_url = f"{PUBLIC_URL}?ref={ref_code}" if ref_code else PUBLIC_URL
    bot.send_message(
        message.chat.id,
        f"🎉 Bienvenue dans *CRYPTORATS_bot* !\n"
        f"Clique ici pour commencer :\n{start_url}",
        parse_mode="Markdown",
        disable_web_page_preview=True
    )

if __name__ == "__main__":
    Thread(target=bot.polling, kwargs={'none_stop': True}).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))