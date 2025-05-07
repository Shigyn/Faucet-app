import os
import random
import telebot
from flask import Flask, request, render_template, jsonify, send_from_directory
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta
from threading import Thread
from urllib.parse import quote

app = Flask(__name__, template_folder='templates')

# Config
TELEGRAM_BOT_API_KEY = os.getenv('TELEGRAM_BOT_API_KEY')
GOOGLE_SHEET_ID = os.getenv('GOOGLE_SHEET_ID')
USER_RANGE = "Users!A2:F"
TRANSACTION_RANGE = "Transactions!A2:D"
TASKS_RANGE = "Tasks!A2:D"
PUBLIC_URL = os.getenv('PUBLIC_URL')

bot = telebot.TeleBot(TELEGRAM_BOT_API_KEY)
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

def get_google_sheets_service():
    creds_json = os.environ.get('GOOGLE_CREDS')
    if not creds_json:
        raise ValueError("GOOGLE_CREDS manquant")
    creds = Credentials.from_service_account_info(eval(creds_json), scopes=SCOPES)
    return build('sheets', 'v4', credentials=creds).spreadsheets()

def clean_user_id(user_id):
    return str(user_id).strip().strip("'")

# Routes
# [...] (le reste du code précédent reste inchangé jusqu'aux routes)

@app.route('/complete-task', methods=['POST'])
def complete_task():
    try:
        data = request.get_json()
        user_id = clean_user_id(data.get('user_id'))
        task_name = data.get('task_name')
        points = int(data.get('points', 0))

        if not all([user_id, task_name, points > 0]):
            return jsonify({"error": "Données invalides"}), 400

        # 1. Mettre à jour le solde
        service = get_google_sheets_service()
        now = datetime.now().strftime("%d/%m/%Y %H:%M")
        
        # Trouver l'utilisateur
        result = service.values().get(
            spreadsheetId=GOOGLE_SHEET_ID,
            range=USER_RANGE
        ).execute()
        
        updated = False
        for idx, row in enumerate(result.get('values', [])):
            if row and clean_user_id(row[0]) == user_id:
                new_balance = (int(float(row[1])) if len(row) > 1 and row[1] else 0) + points
                # Mise à jour du solde
                service.values().update(
                    spreadsheetId=GOOGLE_SHEET_ID,
                    range=f"Users!B{idx+2}",
                    valueInputOption="USER_ENTERED",
                    body={"values": [[new_balance]]
                    
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory('static', filename)

@app.route('/get-balance', methods=['POST'])
def get_balance():
    try:
        data = request.get_json()
        user_id = clean_user_id(data.get('user_id'))
        
        service = get_google_sheets_service()
        result = service.values().get(spreadsheetId=GOOGLE_SHEET_ID, range=USER_RANGE).execute()
        
        for row in result.get('values', []):
            if row and clean_user_id(row[0]) == user_id:
                return jsonify({
                    "balance": int(float(row[1])) if len(row) > 1 and row[1] else 0,
                    "last_claim": row[2] if len(row) > 2 else None,
                    "referral_url": f"{PUBLIC_URL}?ref={quote(row[5])}" if len(row) > 5 and row[5] else ""
                })
        
        return jsonify({"balance": 0, "last_claim": None})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/get-tasks', methods=['GET', 'POST'])
def get_tasks():
    try:
        service = get_google_sheets_service()
        result = service.values().get(spreadsheetId=GOOGLE_SHEET_ID, range=TASKS_RANGE).execute()
        
        tasks = []
        for row in result.get('values', []):
            if len(row) >= 4:
                tasks.append({
                    "task_name": row[0],
                    "description": row[1],
                    "points": int(row[2]),
                    "url": row[3]
                })
        return jsonify({"tasks": tasks})
    
    except Exception:
        return jsonify({"tasks": [
            {
                "task_name": "Rejoignez notre Telegram",
                "description": "Abonnez-vous à notre channel",
                "points": 50,
                "url": "https://t.me/CRYPTORATS_annonces"
            }
        ]})

@bot.message_handler(commands=['start'])
def start(message):
    ref_code = message.text.split()[1] if len(message.text.split()) > 1 else None
    start_url = f"{PUBLIC_URL}?ref={ref_code}" if ref_code else PUBLIC_URL
    bot.send_message(message.chat.id, f"🎉 Accédez à l'app: {start_url}")

if __name__ == "__main__":
    Thread(target=bot.infinity_polling).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))