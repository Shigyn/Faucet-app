import os
import random
import telebot
from flask import Flask, request, render_template, redirect, url_for
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
PUBLIC_URL = os.getenv('PUBLIC_URL')  # ex: https://faucet-app.onrender.com

# Vérification des variables d'environnement
if not TELEGRAM_BOT_API_KEY:
    raise ValueError("TELEGRAM_BOT_API_KEY manquant.")
if not GOOGLE_SHEET_ID:
    raise ValueError("GOOGLE_SHEET_ID manquant.")
if not USER_RANGE:
    raise ValueError("USER_RANGE manquant.")
if not TRANSACTION_RANGE:
    raise ValueError("TRANSACTION_RANGE manquant.")
if not PUBLIC_URL:
    raise ValueError("PUBLIC_URL manquant.")

bot = telebot.TeleBot(TELEGRAM_BOT_API_KEY)
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

def get_google_sheets_service():
    creds_json = os.environ.get('GOOGLE_CREDS')
    if not creds_json:
        raise Exception("GOOGLE_CREDS manquant.")
    creds = Credentials.from_service_account_info(eval(creds_json), scopes=SCOPES)
    return build('sheets', 'v4', credentials=creds).spreadsheets()

@app.route('/', methods=['GET'])
def home():
    user_id = request.args.get('user_id')  # Récupération de l'ID utilisateur depuis l'URL
    print(f"[INFO] Accès à / avec user_id={user_id}")
    if not user_id:
        return "L'ID utilisateur est manquant !", 400
    balance = get_user_balance(user_id)  # Appel pour récupérer le solde de l'utilisateur
    return render_template('index.html', balance=balance, user_id=user_id)

@app.route('/claim', methods=['GET'])
def claim_page():
    user_id = request.args.get('user_id')  # Récupérer l'ID utilisateur depuis l'URL
    if not user_id:
        return "ID utilisateur manquant.", 400
    balance = get_user_balance(user_id)  # Appel pour récupérer le solde de l'utilisateur
    points = request.args.get('points')  # Récupérer les points depuis l'URL
    return render_template("claim.html", balance=balance, user_id=user_id, points=points)

@app.route('/submit_claim', methods=['POST'])
def submit_claim():
    user_id = request.form.get('user_id')
    if not user_id:
        return "ID utilisateur manquant.", 400

    points = random.randint(10, 100)  # Générer des points aléatoires
    service = get_google_sheets_service()
    result = service.values().get(spreadsheetId=GOOGLE_SHEET_ID, range=USER_RANGE).execute()
    values = result.get('values', [])

    user_found = False
    for idx, row in enumerate(values):
        if str(row[0]) == str(user_id):  # Si l'utilisateur existe déjà
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

    return redirect(url_for('claim_page', user_id=user_id, points=points))

def get_user_balance(user_id):
    service = get_google_sheets_service()
    result = service.values().get(spreadsheetId=GOOGLE_SHEET_ID, range=USER_RANGE).execute()
    values = result.get('values', [])
    for row in values:
        if str(row[0]) == str(user_id):
            return int(row[1]) if row[1] else 0
    return 0

# Bot Telegram
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id  # Récupérer l'ID Telegram de l'utilisateur
    url = f"{PUBLIC_URL}/?user_id={user_id}"  # Créer l'URL avec l'ID de l'utilisateur
    print(f"[BOT] Envoi de l'URL au user : {url}")
    bot.send_message(user_id, "Bienvenue ! Vous pouvez maintenant réclamer des points.")
    bot.send_message(user_id, f"👉 Pour réclamer des points, clique ici : {url}")

# Lancer Flask et Telegram bot
if __name__ == "__main__":
    Thread(target=bot.polling, kwargs={'none_stop': True}).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
