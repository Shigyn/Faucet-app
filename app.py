import os
import random
import telebot
from flask import Flask, request, render_template
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
def send_claim_button(chat_id):
    markup = telebot.types.InlineKeyboardMarkup()
    # Ajouter un bouton qui ouvre une page web
    claim_button = telebot.types.InlineKeyboardButton(
        text="Réclamer des points", 
        url="https://faucet-app-psi.vercel.app/claim"  # URL mise à jour vers la page de réclamation sur le domaine Vercel
    )
    markup.add(claim_button)
    bot.send_message(chat_id, "Clique sur le bouton ci-dessous pour réclamer des points :", reply_markup=markup)

# Fonction pour gérer le /start
@bot.message_handler(commands=['start'])
def handle_start(message):
    send_claim_button(message.chat.id)  # Envoie le bouton de réclamation quand l'utilisateur démarre le bot

# Route pour afficher la page de réclamation
@app.route('/claim', methods=['GET'])
def claim_page():
    user_id = request.args.get('user_id')
    if not user_id:
        return "ID utilisateur manquant."
    
    # Générer un nombre de points aléatoires entre 10 et 100
    points = random.randint(10, 100)

    # Enregistrer les points réclamés dans Google Sheets ou autre logique pour mettre à jour la base de données
    service = get_google_sheets_service()
    result = service.values().get(spreadsheetId=SHEET_ID, range=RANGE_USERS).execute()
    values = result.get('values', [])

    # Trouver l'utilisateur dans la feuille et mettre à jour ses points
    for idx, row in enumerate(values):
        if row[0] == user_id:
            # Ajouter les points réclamés au solde actuel
            current_balance = int(row[1]) if row[1] else 0
            new_balance = current_balance + points
            service.values().update(
                spreadsheetId=SHEET_ID,
                range=f'Users!B{idx + 2}',  # Mettre à jour le solde de l'utilisateur
                valueInputOption="RAW",
                body={'values': [[new_balance]]}
            ).execute()

            # Enregistrer la transaction dans la feuille "Transactions"
            transaction_row = [user_id, 'claim', points, datetime.now().strftime("%d/%m/%Y %H:%M")]
            service.values().append(
                spreadsheetId=SHEET_ID,
                range="Transactions",
                valueInputOption="RAW",
                body={'values': [transaction_row]}
            ).execute()

            break

    # Afficher la page claim.html avec les points générés
    return render_template("claim.html", points=points)

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
