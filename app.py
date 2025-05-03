import os
import random
import telebot
from flask import Flask, request, render_template
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta

app = Flask(__name__)

# Vérifier si les variables d'environnement sont définies correctement
TELEGRAM_BOT_API_KEY = os.getenv('TELEGRAM_BOT_API_KEY')
GOOGLE_SHEET_ID = os.getenv('GOOGLE_SHEET_ID')
USER_RANGE = os.getenv('USER_RANGE')
TRANSACTION_RANGE = os.getenv('TRANSACTION_RANGE')

if not TELEGRAM_BOT_API_KEY:
    raise ValueError("La variable d'environnement 'TELEGRAM_BOT_API_KEY' est manquante.")
if not GOOGLE_SHEET_ID:
    raise ValueError("La variable d'environnement 'GOOGLE_SHEET_ID' est manquante.")
if not USER_RANGE:
    raise ValueError("La variable d'environnement 'USER_RANGE' est manquante.")
if not TRANSACTION_RANGE:
    raise ValueError("La variable d'environnement 'TRANSACTION_RANGE' est manquante.")

bot = telebot.TeleBot(TELEGRAM_BOT_API_KEY)

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

def get_google_sheets_service():
    creds_json = os.environ.get('GOOGLE_CREDS')
    if not creds_json:
        raise Exception("La variable d'environnement 'GOOGLE_CREDS' est manquante.")
    
    creds = Credentials.from_service_account_info(eval(creds_json), scopes=SCOPES)
    service = build('sheets', 'v4', credentials=creds)
    return service.spreadsheets()

@app.route('/', methods=['GET'])
def home():
    return render_template('index.html')

# Mise à jour : bouton avec WebAppInfo (pas d'user_id dans URL)
def send_claim_button(chat_id):
    markup = telebot.types.InlineKeyboardMarkup()
    web_app = telebot.types.WebAppInfo(url="https://faucet-app.onrender.com/claim")
    claim_button = telebot.types.InlineKeyboardButton(
        text="Réclamer des points", 
        web_app=web_app
    )
    markup.add(claim_button)
    bot.send_message(chat_id, "Clique sur le bouton ci-dessous pour réclamer des points :", reply_markup=markup)

@bot.message_handler(commands=['start'])
def handle_start(message):
    user_id = message.chat.id
    send_claim_button(user_id)

@app.route('/claim', methods=['GET'])
def claim_page():
    # Le user_id est récupéré via JS dans la WebApp
    return render_template("claim.html")

@app.route('/submit_claim', methods=['POST'])
def submit_claim():
    user_id = request.form.get('user_id')
    if not user_id:
        return "ID utilisateur manquant."

    print(f"ID utilisateur récupéré via POST : {user_id}")

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
                if datetime.now() - last_claim_time < timedelta(minutes=1):
                    return "Tu as déjà réclamé des points il y a moins d'une minute. Essaie à nouveau plus tard."

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
        range="Transactions",
        valueInputOption="RAW",
        body={'values': [transaction_row]}
    ).execute()

    return f"Réclamation réussie ! Tu as gagné {points} points."

@app.route(f"/{TELEGRAM_BOT_API_KEY}", methods=["POST"])
def webhook():
    try:
        json_str = request.get_data().decode("UTF-8")
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
        return '', 200
    except Exception as e:
        print(f"Erreur dans le traitement du webhook : {e}")
        return '', 500

def set_telegram_webhook():
    webhook_url = "https://faucet-app.onrender.com/" + TELEGRAM_BOT_API_KEY
    bot.remove_webhook()
    bot.set_webhook(url=webhook_url)

if __name__ == "__main__":
    set_telegram_webhook()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
