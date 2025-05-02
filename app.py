import os
import telebot
from flask import Flask, request
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
from datetime import datetime
import base64
from io import BytesIO

app = Flask(__name__)
bot = telebot.TeleBot(TELEGRAM_BOT_API_KEY)

SHEET_ID = GOOGLE_SHEET_ID
RANGE_USERS = USER_RANGE
RANGE_TRANSACTIONS = TRANSACTION_RANGE

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

# Fonction pour récupérer les credentials Google
def download_credentials():
    creds_base64 = os.environ.get('GOOGLE_CREDS_B64')
    if not creds_base64:
        raise Exception("La variable d'environnement 'GOOGLE_CREDS_B64' est manquante.")
    
    creds_json = base64.b64decode(creds_base64).decode('utf-8')
    creds_file = os.path.join(os.getcwd(), 'google', 'service_account_credentials.json')
    with open(creds_file, 'w') as f:
        f.write(creds_json)
    
    return creds_file

def get_google_sheets_service():
    creds = Credentials.from_service_account_file(download_credentials(), scopes=SCOPES)
    service = build('sheets', 'v4', credentials=creds)
    return service.spreadsheets()

# Route pour l'index de base
@app.route('/', methods=['GET'])
def home():
    return "Application Flask en cours d'exécution. L'API est accessible."

# Fonction pour envoyer un bouton de réclamation (qui ouvre un webapp)
def send_claim_button(chat_id, user_id):
    markup = telebot.types.InlineKeyboardMarkup()
    # Ajouter un bouton qui ouvre une page web avec le user_id dynamique
    claim_button = telebot.types.InlineKeyboardButton(
        text="Réclamer des points", 
        url=f"https://faucet-app-psi.vercel.app/claim?user_id={user_id}"  # URL avec user_id dynamique
    )
    markup.add(claim_button)
    bot.send_message(chat_id, "Clique sur le bouton ci-dessous pour réclamer des points :", reply_markup=markup)

# Fonction pour gérer le /start
@bot.message_handler(commands=['start'])
def handle_start(message):
    user_id = message.chat.id  # Utilise l'ID du chat comme user_id
    send_claim_button(message.chat.id, user_id)  # Envoie le bouton de réclamation avec l'ID utilisateur

# Webhook
@app.route(f"/{TELEGRAM_BOT_API_KEY}", methods=["POST"])
def webhook():
    json_str = request.get_data().decode("UTF-8")
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "", 200

if __name__ == "__main__":
    # Configurer le webhook pour Telegram
    bot.remove_webhook()
    bot.set_webhook(url=f"https://faucet-app-psi.vercel.app/{TELEGRAM_BOT_API_KEY}")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
