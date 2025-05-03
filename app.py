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
    result = service.values().get(spreadsheetId=GOOGLE_SHEET_ID, range=USER_RANGE).execute()
    values = result.get('values', [])

    # Trouver l'utilisateur dans la feuille et mettre à jour ses points
    for idx, row in
