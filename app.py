import os
import random
import telebot
from flask import Flask, request, render_template
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
from datetime import datetime

app = Flask(__name__)

# Vérifier si les variables d'environnement sont définies correctement
TELEGRAM_BOT_API_KEY = os.getenv('TELEGRAM_BOT_API_KEY')
GOOGLE_SHEET_ID = os.getenv('GOOGLE_SHEET_ID')
USER_RANGE = os.getenv('USER_RANGE')
TRANSACTION_RANGE = os.getenv('TRANSACTION_RANGE')

# Assure-toi que ces variables sont présentes
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

# Fonction pour récupérer les credentials Google
def get_google_sheets_service():
    creds_json = os.environ.get('GOOGLE_CREDS')
    if not creds_json:
        raise Exception("La variable d'environnement 'GOOGLE_CREDS' est manquante.")
    
    creds = Credentials.from_service_account_info(eval(creds_json), scopes=SCOPES)
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
    result = service.values().get(spreadsheetId=GOOGLE_SHEET_ID, range=USER_RANGE).execute()
    values = result.get('values', [])

    # Trouver l'utilisateur dans la feuille et mettre à jour ses points
    for idx, row in enumerate(values):
        if row[0] == user_id:
            # Ajouter les points réclamés au solde actuel
            current_balance = int(row[1]) if row[1] else 0
            new_balance = current_balance + points
            service.values().update(
                spreadsheetId=GOOGLE_SHEET_ID,
                range=f'Users!B{idx + 2}',  # Mettre à jour le solde de l'utilisateur
                valueInputOption="RAW",
                body={'values': [[new_balance]]}
            ).execute()

            # Enregistrer la transaction dans la feuille "Transactions"
            transaction_row = [user_id, 'claim', points, datetime.now().strftime("%d/%m/%Y %H:%M")]
            service.values().append(
                spreadsheetId=GOOGLE_SHEET_ID,
                range="Transactions",
                valueInputOption="RAW",
                body={'values': [transaction_row]}
            ).execute()

            break

    # Afficher la page claim.html avec les points générés
    return render_template("claim.html", points=points)

# Webhook pour recevoir les mises à jour Telegram
@app.route(f"/{TELEGRAM_BOT_API_KEY}", methods=["POST"])
def webhook():
    try:
        json_str = request.get_data().decode("UTF-8")
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
        return '', 200  # Réponse OK
    except Exception as e:
        print(f"Erreur dans le traitement du webhook : {e}")
        return '', 500  # Erreur interne

# Configurer le webhook Telegram
def set_telegram_webhook():
    webhook_url = "https://faucet-app.onrender.com/" + TELEGRAM_BOT_API_KEY
    bot.remove_webhook()  # Supprime tout ancien webhook
    bot.set_webhook(url=webhook_url)  # Définit le nouveau webhook

if __name__ == "__main__":
    set_telegram_webhook()  # Appel pour configurer le webhook
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))  # Démarrer l'application Flask
