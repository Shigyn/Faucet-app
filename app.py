import os
import random
import telebot
from flask import Flask, request, render_template, jsonify
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta
from threading import Thread

app = Flask(__name__)

# Config
TELEGRAM_BOT_API_KEY = os.getenv('TELEGRAM_BOT_API_KEY')
GOOGLE_SHEET_ID = os.getenv('GOOGLE_SHEET_ID')
USER_RANGE = os.getenv('USER_RANGE')
TRANSACTION_RANGE = os.getenv('TRANSACTION_RANGE')
PUBLIC_URL = os.getenv('PUBLIC_URL')

# Vérification des variables
if not all([TELEGRAM_BOT_API_KEY, GOOGLE_SHEET_ID, USER_RANGE, TRANSACTION_RANGE, PUBLIC_URL]):
    raise ValueError("Variables d'environnement manquantes")

bot = telebot.TeleBot(TELEGRAM_BOT_API_KEY)
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

def get_google_sheets_service():
    creds_json = os.environ.get('GOOGLE_CREDS')
    if not creds_json:
        raise Exception("GOOGLE_CREDS manquant")
    creds = Credentials.from_service_account_info(eval(creds_json), scopes=SCOPES)
    return build('sheets', 'v4', credentials=creds).spreadsheets()

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/get-balance', methods=['POST'])
def get_balance():
    data = request.get_json()
    user_id = data.get('user_id')
    if not user_id:
        return jsonify({"error": "ID utilisateur manquant"}), 400
    
    service = get_google_sheets_service()
    result = service.values().get(spreadsheetId=GOOGLE_SHEET_ID, range=USER_RANGE).execute()
    values = result.get('values', [])

    for row in values:
        if str(row[0]) == str(user_id):
            return jsonify({"balance": int(row[1]) if len(row) > 1 and row[1] else 0})
    
    return jsonify({"balance": 0})

@app.route('/claim', methods=['POST'])
def claim():
    data = request.get_json()
    user_id = data.get('user_id')
    if not user_id:
        return jsonify({"error": "ID utilisateur manquant"}), 400

    service = get_google_sheets_service()
    result = service.values().get(spreadsheetId=GOOGLE_SHEET_ID, range=USER_RANGE).execute()
    values = result.get('values', [])
    points = random.randint(10, 100)
    now = datetime.now().strftime("%d/%m/%Y %H:%M")

    # Vérification du dernier claim
    for row in values:
        if str(row[0]) == str(user_id):
            if len(row) > 2 and row[2]:
                last_claim = datetime.strptime(row[2], "%d/%m/%Y %H:%M")
                if (datetime.now() - last_claim) < timedelta(minutes=5):
                    return jsonify({"error": "Attends 5 minutes entre chaque réclamation"}), 400

    # Mise à jour Sheets
    user_found = False
    for idx, row in enumerate(values):
        if str(row[0]) == str(user_id):
            user_found = True
            current_balance = int(row[1]) if len(row) > 1 and row[1] else 0
            new_balance = current_balance + points
            
            service.values().batchUpdate(
                spreadsheetId=GOOGLE_SHEET_ID,
                body={
                    "requests": [
                        {
                            "updateCells": {
                                "range": {"sheetId": 0, "startRowIndex": idx+1, "endRowIndex": idx+2, "startColumnIndex": 1, "endColumnIndex": 2},
                                "rows": [{"values": [{"userEnteredValue": {"numberValue": new_balance}}]}],
                                "fields": "userEnteredValue"
                            }
                        },
                        {
                            "updateCells": {
                                "range": {"sheetId": 0, "startRowIndex": idx+1, "endRowIndex": idx+2, "startColumnIndex": 2, "endColumnIndex": 3},
                                "rows": [{"values": [{"userEnteredValue": {"stringValue": now}}]}],
                                "fields": "userEnteredValue"
                            }
                        }
                    ]
                }
            ).execute()
            break

    if not user_found:
        service.values().append(
            spreadsheetId=GOOGLE_SHEET_ID,
            range=USER_RANGE,
            valueInputOption="RAW",
            body={"values": [[user_id, points, now]]}
        ).execute()

    # Ajout transaction
    service.values().append(
        spreadsheetId=GOOGLE_SHEET_ID,
        range=TRANSACTION_RANGE,
        valueInputOption="RAW",
        body={"values": [[user_id, "claim", points, now]]}
    ).execute()

    return jsonify({"success": f"{points} points ajoutés !"})

@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(
        message.chat.id,
        f"🎉 Bienvenue ! Clique ici pour commencer :\n{PUBLIC_URL}",
        disable_web_page_preview=True
    )

if __name__ == "__main__":
    Thread(target=bot.polling, kwargs={'none_stop': True}).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))