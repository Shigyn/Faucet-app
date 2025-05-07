import os
import random
import telebot
from flask import Flask, request, render_template, jsonify, send_from_directory
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta
from threading import Thread
from urllib.parse import quote
import time

app = Flask(__name__, template_folder='templates')

# Config
TELEGRAM_BOT_API_KEY = os.getenv('TELEGRAM_BOT_API_KEY')
GOOGLE_SHEET_ID = os.getenv('GOOGLE_SHEET_ID')
USER_RANGE = "Users!A2:G"  # Colonne G ajoutée pour last_claim_timestamp
TRANSACTION_RANGE = "Transactions!A2:D"
TASKS_RANGE = "Tasks!A2:D"
PUBLIC_URL = os.getenv('PUBLIC_URL')
CLAIM_COOLDOWN = 300  # 5 minutes en secondes

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

def get_current_timestamp():
    return int(time.time())

def parse_timestamp(timestamp_str):
    try:
        if not timestamp_str:
            return 0
        return int(timestamp_str)
    except:
        return 0

@app.route('/complete-task', methods=['POST'])
def complete_task():
    try:
        data = request.get_json()
        user_id = clean_user_id(data.get('user_id'))
        task_name = data.get('task_name')
        points = int(data.get('points', 0))

        if not all([user_id, task_name, points > 0]):
            return jsonify({"error": "Données invalides"}), 400

        service = get_google_sheets_service()
        now = datetime.now().strftime("%d/%m/%Y %H:%M")
        
        result = service.values().get(
            spreadsheetId=GOOGLE_SHEET_ID,
            range=USER_RANGE
        ).execute()
        
        updated = False
        for idx, row in enumerate(result.get('values', [])):
            if row and clean_user_id(row[0]) == user_id:
                new_balance = (int(float(row[1])) if len(row) > 1 and row[1] else 0) + points
                
                service.values().update(
                    spreadsheetId=GOOGLE_SHEET_ID,
                    range=f"Users!B{idx+2}",
                    valueInputOption="USER_ENTERED",
                    body={"values": [[new_balance]]}
                ).execute()

                service.values().append(
                    spreadsheetId=GOOGLE_SHEET_ID,
                    range=TRANSACTION_RANGE,
                    valueInputOption="USER_ENTERED",
                    body={"values": [[user_id, f"task:{task_name}", points, now]]}
                ).execute()

                updated = True
                break

        if not updated:
            return jsonify({"error": "Utilisateur non trouvé"}), 404

        return jsonify({
            "success": True,
            "new_balance": new_balance,
            "message": f"Tâche '{task_name}' validée !"
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500
                    
@app.route('/claim', methods=['POST'])
def claim_points():
    try:
        data = request.get_json()
        user_id = clean_user_id(data.get('user_id'))
        
        if not user_id:
            return jsonify({"error": "ID utilisateur manquant"}), 400

        service = get_google_sheets_service()
        now = datetime.now().strftime("%d/%m/%Y %H:%M")
        current_ts = get_current_timestamp()
        points = random.randint(10, 50)

        # Trouver et mettre à jour l'utilisateur
        result = service.values().get(spreadsheetId=GOOGLE_SHEET_ID, range=USER_RANGE).execute()
        rows = result.get('values', [])
        
        for idx, row in enumerate(rows):
            if row and clean_user_id(row[0]) == user_id:
                # Vérifier le cooldown
                last_claim_ts = parse_timestamp(row[6] if len(row) > 6 else 0)
                if current_ts - last_claim_ts < CLAIM_COOLDOWN:
                    remaining = CLAIM_COOLDOWN - (current_ts - last_claim_ts)
                    return jsonify({
                        "error": f"Attendez {remaining} secondes",
                        "cooldown": remaining
                    }), 429

                # Mise à jour du solde et du timestamp
                new_balance = (int(float(row[1])) if len(row) > 1 and row[1] else 0) + points
                
                # Mettre à jour balance et last_claim_timestamp
                service.values().update(
                    spreadsheetId=GOOGLE_SHEET_ID,
                    range=f"Users!B{idx+2}:G{idx+2}",
                    valueInputOption="USER_ENTERED",
                    body={"values": [[new_balance, now, current_ts]]}
                ).execute()

                # Enregistrer la transaction
                service.values().append(
                    spreadsheetId=GOOGLE_SHEET_ID,
                    range=TRANSACTION_RANGE,
                    valueInputOption="USER_ENTERED",
                    body={"values": [[user_id, "claim", points, now]]}
                ).execute()

                return jsonify({
                    "success": True,
                    "new_balance": new_balance,
                    "last_claim": now,
                    "last_claim_timestamp": current_ts,
                    "message": f"🎉 +{points} points !"
                })

        return jsonify({"error": "Utilisateur non trouvé"}), 404

    except Exception as e:
        return jsonify({"error": str(e)}), 500

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
                    "last_claim_timestamp": parse_timestamp(row[6] if len(row) > 6 else 0),
                    "referral_code": row[5] if len(row) > 5 else "",
                    "referral_url": f"{PUBLIC_URL}?ref={quote(row[5])}" if len(row) > 5 and row[5] else ""
                })
        
        return jsonify({"balance": 0, "last_claim": None, "last_claim_timestamp": 0})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/get-tasks', methods=['GET'])
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