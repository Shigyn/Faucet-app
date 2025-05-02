import os
import logging
import telebot
from flask import Flask, request
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
import random
from datetime import datetime
from config import GOOGLE_SHEET_ID, TELEGRAM_BOT_API_KEY, GOOGLE_CREDS_URL, USER_RANGE, TRANSACTION_RANGE, GITHUB_TOKEN
import base64
from io import BytesIO

app = Flask(__name__)
bot = telebot.TeleBot(TELEGRAM_BOT_API_KEY)

SHEET_ID = GOOGLE_SHEET_ID
RANGE_USERS = USER_RANGE
RANGE_TRANSACTIONS = TRANSACTION_RANGE

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

def download_credentials():
    # Récupérer la chaîne base64 de la variable d'environnement
    creds_base64 = os.environ.get('GOOGLE_CREDS_B64')
    
    if not creds_base64:
        raise Exception("La variable d'environnement 'GOOGLE_CREDS_B64' est manquante.")
    
    # Décoder le fichier base64
    creds_json = base64.b64decode(creds_base64).decode('utf-8')
    
    # Créer un fichier temporaire pour y écrire les credentials
    creds_file = os.path.join(os.getcwd(), 'google', 'service_account_credentials.json')
    with open(creds_file, 'w') as f:
        f.write(creds_json)
    
    return creds_file

def get_google_sheets_service():
    creds = Credentials.from_service_account_file(download_credentials(), scopes=SCOPES)
    service = build('sheets', 'v4', credentials=creds)
    return service.spreadsheets()

@app.route('/', methods=['GET'])
def home():
    return "Application Flask en cours d'exécution. L'API est accessible."

@app.route('/register', methods=['GET'])
def register():
    user_id = request.args.get('user_id')
    if not user_id:
        return "ID utilisateur manquant."

    service = get_google_sheets_service()
    result = service.values().get(spreadsheetId=SHEET_ID, range=RANGE_USERS).execute()
    values = result.get('values', [])

    for row in values:
        if row[0] == user_id:
            return "L'utilisateur existe déjà."

    new_row = [user_id, 0, '']
    service.values().append(
        spreadsheetId=SHEET_ID,
        range=RANGE_USERS,
        valueInputOption="RAW",
        body={'values': [new_row]}
    ).execute()

    return f"L'utilisateur {user_id} a été créé avec succès."

@app.route('/claim', methods=['GET'])
def claim():
    user_id = request.args.get('user_id')
    if not user_id:
        return "ID utilisateur manquant."

    service = get_google_sheets_service()
    result = service.values().get(spreadsheetId=SHEET_ID, range=RANGE_USERS).execute()
    values = result.get('values', [])

    user_found = False
    for idx, row in enumerate(values):
        if row[0] == user_id:
            user_found = True
            balance = int(row[1]) if row[1] else 0
            last_claim = row[2] if len(row) > 2 else ""

            last_claim_time = datetime.strptime(last_claim, "%d/%m/%Y %H:%M") if last_claim != '' else None
            now = datetime.now()

            if last_claim_time is None or (now - last_claim_time).total_seconds() > 3600:
                claim_points = random.randint(10, 100)
                new_balance = balance + claim_points
                service.values().update(
                    spreadsheetId=SHEET_ID,
                    range=f'Users!B{idx + 2}',
                    valueInputOption="RAW",
                    body={'values': [[new_balance]]}
                ).execute()
                service.values().update(
                    spreadsheetId=SHEET_ID,
                    range=f'Users!C{idx + 2}',
                    valueInputOption="RAW",
                    body={'values': [[now.strftime("%d/%m/%Y %H:%M")]]}
                ).execute()

                transaction_row = [user_id, 'claim', claim_points, now.strftime("%d/%m/%Y %H:%M")]
                service.values().append(
                    spreadsheetId=SHEET_ID,
                    range="Transactions",  # ✅ corrigé ici
                    valueInputOption="RAW",
                    insertDataOption="INSERT_ROWS",
                    body={'values': [transaction_row]}
                ).execute()

                return f"Félicitations ! Tu as réclamé {claim_points} points. Ton solde est maintenant de {new_balance} points."
            else:
                return "Tu as déjà réclamé aujourd'hui ou moins d'une heure s'est écoulée depuis ta dernière réclamation."

    if not user_found:
        # Créer l'utilisateur dans Users
        new_user_row = [user_id, 0, '']
        service.values().append(
            spreadsheetId=SHEET_ID,
            range=RANGE_USERS,
            valueInputOption="RAW",
            body={'values': [new_user_row]}
        ).execute()

        # Effectuer la réclamation de points juste après la création de l'utilisateur
        balance = 0
        claim_points = random.randint(10, 100)
        new_balance = balance + claim_points
        service.values().update(
            spreadsheetId=SHEET_ID,
            range=f'Users!B{len(values) + 2}',  # Mettre à jour la colonne B de l'utilisateur créé
            valueInputOption="RAW",
            body={'values': [[new_balance]]}
        ).execute()
        service.values().update(
            spreadsheetId=SHEET_ID,
            range=f'Users!C{len(values) + 2}',  # Mettre à jour la colonne C de la date de réclamation
            valueInputOption="RAW",
            body={'values': [[datetime.now().strftime("%d/%m/%Y %H:%M")]]}
        ).execute()

        # Ajouter la transaction dans Transactions
        transaction_row = [user_id, 'claim', claim_points, datetime.now().strftime("%d/%m/%Y %H:%M")]
        service.values().append(
            spreadsheetId=SHEET_ID,
            range="Transactions",  # Utiliser juste le nom de la feuille pour append
            valueInputOption="RAW",
            body={'values': [transaction_row]}
        ).execute()

        return f"Utilisateur {user_id} créé avec succès et {claim_points} points réclamés."

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
    bot.set_webhook(url=f"https://web-production-7271.up.railway.app/{TELEGRAM_BOT_API_KEY}")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
