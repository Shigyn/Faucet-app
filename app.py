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
USER_RANGE = "Users!A2:E"  # À adapter selon votre configuration exacte
TRANSACTION_RANGE = "Transactions!A2:D"  # À adapter selon votre configuration exacte
PUBLIC_URL = os.getenv('PUBLIC_URL')

# Vérification des variables
if not all([TELEGRAM_BOT_API_KEY, GOOGLE_SHEET_ID, PUBLIC_URL]):
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
    result = service.values().get(
        spreadsheetId=GOOGLE_SHEET_ID,
        range=USER_RANGE
    ).execute()
    values = result.get('values', [])

    for row in values:
        if str(row[0]) == str(user_id):
            return jsonify({
                "balance": int(row[1]) if len(row) > 1 and row[1] else 0,
                "last_claim": row[2] if len(row) > 2 else None
            })
    
    return jsonify({"balance": 0, "last_claim": None})

@app.route('/claim', methods=['POST'])
def claim():
    data = request.get_json()
    user_id = data.get('user_id')
    if not user_id:
        return jsonify({"error": "ID utilisateur manquant"}), 400

    service = get_google_sheets_service()
    
    # 1. Récupérer toutes les données utilisateurs
    user_result = service.values().get(
        spreadsheetId=GOOGLE_SHEET_ID,
        range=USER_RANGE,
        majorDimension="ROWS"
    ).execute()
    user_values = user_result.get('values', [])

    points = random.randint(10, 100)
    now = datetime.now().strftime("%d/%m/%Y %H:%M")

    # 2. Vérifier le délai entre les claims
    for row in user_values:
        if str(row[0]) == str(user_id) and len(row) > 2 and row[2]:
            try:
                last_claim = datetime.strptime(row[2], "%d/%m/%Y %H:%M")
                if (datetime.now() - last_claim) < timedelta(minutes=5):
                    return jsonify({"error": "Attends 5 minutes entre chaque réclamation"}), 400
            except ValueError:
                pass  # Si le format de date est invalide, on ignore

    try:
        updated = False
        # 3. Parcourir les lignes pour trouver l'utilisateur
        for idx, row in enumerate(user_values):
            if str(row[0]) == str(user_id):
                current_balance = int(row[1]) if len(row) > 1 and row[1] else 0
                new_balance = current_balance + points
                
                # Mise à jour de la ligne existante (Balance en B, last_claim en C)
                service.values().update(
                    spreadsheetId=GOOGLE_SHEET_ID,
                    range=f"Users!B{idx+2}:C{idx+2}",  # +2 car header + index 0-based
                    valueInputOption="USER_ENTERED",
                    body={
                        "values": [[new_balance, now]]
                    }
                ).execute()
                updated = True
                break

        # 4. Si nouvel utilisateur
        if not updated:
            service.values().append(
                spreadsheetId=GOOGLE_SHEET_ID,
                range=USER_RANGE,
                valueInputOption="USER_ENTERED",
                body={
                    "values": [[user_id, points, now, 0, ""]]  # user_id, balance, last_claim, ads_watched, last_ads
                }
            ).execute()

        # 5. Enregistrer la transaction
        service.values().append(
            spreadsheetId=GOOGLE_SHEET_ID,
            range=TRANSACTION_RANGE,
            valueInputOption="USER_ENTERED",
            body={
                "values": [[user_id, "claim", points, now]]
            }
        ).execute()

        return jsonify({
            "success": f"{points} points ajoutés !",
            "new_balance": new_balance if updated else points,
            "last_claim": now
        })

    except Exception as e:
        print(f"Erreur Sheets: {str(e)}")
        return jsonify({"error": "Erreur serveur lors de la mise à jour"}), 500

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