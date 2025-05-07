import os
import telebot
from flask import Flask, request, render_template, jsonify, redirect, url_for
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta
import random

app = Flask(__name__)

TELEGRAM_BOT_API_KEY = os.getenv('TELEGRAM_BOT_API_KEY')
GOOGLE_SHEET_ID = os.getenv('GOOGLE_SHEET_ID')
USER_RANGE = os.getenv('USER_RANGE')
TRANSACTION_RANGE = os.getenv('TRANSACTION_RANGE')
TASKS_RANGE = os.getenv('TASKS_RANGE')

# Vérification des variables d’environnement
required_env_vars = {
    "TELEGRAM_BOT_API_KEY": TELEGRAM_BOT_API_KEY,
    "GOOGLE_SHEET_ID": GOOGLE_SHEET_ID,
    "USER_RANGE": USER_RANGE,
    "TRANSACTION_RANGE": TRANSACTION_RANGE,
    "TASKS_RANGE": TASKS_RANGE
}
for var, val in required_env_vars.items():
    if not val:
        raise ValueError(f"La variable d'environnement '{var}' est manquante.")

bot = telebot.TeleBot(TELEGRAM_BOT_API_KEY)
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

def get_google_sheets_service():
    creds_json = os.environ.get('GOOGLE_CREDS')
    if not creds_json:
        raise Exception("La variable d'environnement 'GOOGLE_CREDS' est manquante.")
    creds = Credentials.from_service_account_info(eval(creds_json), scopes=SCOPES)
    service = build('sheets', 'v4', credentials=creds)
    return service.spreadsheets()

@app.route('/')
def index():
    user_id = request.args.get('user_id')
    balance = get_user_balance(user_id) if user_id else 0
    return render_template("index.html", balance=balance)

@app.route('/claim', methods=['GET'])
def claim_page():
    user_id = request.args.get('user_id')
    points = request.args.get('points')
    balance = get_user_balance(user_id) if user_id else None
    return render_template("claim.html", balance=balance, user_id=user_id, points=points)

@app.route('/submit_claim', methods=['POST'])
def submit_claim():
    user_id = request.form.get('user_id')
    if not user_id:
        return "ID utilisateur manquant."

    points = random.randint(10, 100)

    service = get_google_sheets_service()
    result = service.values().get(spreadsheetId=GOOGLE_SHEET_ID, range=USER_RANGE).execute()
    values = result.get('values', [])

    user_found = False
    for idx, row in enumerate(values):
        if str(row[0]) == str(user_id):
            user_found = True
            last_claim = row[2] if len(row) > 2 else None
            if last_claim:
                last_claim_time = datetime.strptime(last_claim, "%d/%m/%Y %H:%M")
                if datetime.now() - last_claim_time < timedelta(minutes=5):
                    balance = int(row[1]) if row[1] else 0
                    return render_template("claim.html", error="Tu as déjà réclamé des points il y a moins de 5 minutes. Essaie plus tard.", balance=balance, user_id=user_id)

            current_balance = int(row[1]) if row[1] else 0
            new_balance = current_balance + points

            service.values().update(
                spreadsheetId=GOOGLE_SHEET_ID,
                range=f'Users!B{idx + 2}',
                valueInputOption="RAW",
                body={'values': [[new_balance]]}
            ).execute()

            service.values().update(
                spreadsheetId=GOOGLE_SHEET_ID,
                range=f'Users!C{idx + 2}',
                valueInputOption="RAW",
                body={'values': [[datetime.now().strftime("%d/%m/%Y %H:%M")]]}
            ).execute()
            break

    if not user_found:
        new_user_row = [user_id, points, datetime.now().strftime("%d/%m/%Y %H:%M")]
        service.values().append(
            spreadsheetId=GOOGLE_SHEET_ID,
            range=USER_RANGE,
            valueInputOption="RAW",
            body={'values': [new_user_row]}
        ).execute()

    transaction_row = [user_id, 'claim', points, datetime.now().strftime("%d/%m/%Y %H:%M")]
    service.values().append(
        spreadsheetId=GOOGLE_SHEET_ID,
        range=TRANSACTION_RANGE,
        valueInputOption="RAW",
        body={'values': [transaction_row]}
    ).execute()

    # ✅ Rediriger avec points et user_id dans l’URL pour claim.html
    return redirect(url_for('claim_page', user_id=user_id, points=points))

def get_user_balance(user_id):
    service = get_google_sheets_service()
    result = service.values().get(spreadsheetId=GOOGLE_SHEET_ID, range=USER_RANGE).execute()
    values = result.get('values', [])
    for row in values:
        if str(row[0]) == str(user_id):
            return int(row[1]) if row[1] else 0
    return 0

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
