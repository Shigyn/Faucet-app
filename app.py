import os
import random
import telebot
from flask import Flask, request, render_template, jsonify
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta
from threading import Thread
from urllib.parse import quote

app = Flask(__name__)

# Config
TELEGRAM_BOT_API_KEY = os.getenv('TELEGRAM_BOT_API_KEY')
GOOGLE_SHEET_ID = os.getenv('GOOGLE_SHEET_ID')
USER_RANGE = "Users!A2:F"  # Ajout colonne referral_code
TRANSACTION_RANGE = "Transactions!A2:D"
TASKS_RANGE = "Tasks!A2:C"
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

def generate_referral_code(user_id):
    return f"REF-{user_id}-{random.randint(1000,9999)}"

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
                "last_claim": row[2] if len(row) > 2 else None,
                "referral_code": row[5] if len(row) > 5 else generate_referral_code(user_id),
                "referral_url": f"{PUBLIC_URL}?ref={quote(row[5])}" if len(row) > 5 else ""
            })
    
    return jsonify({
        "balance": 0,
        "last_claim": None,
        "referral_code": generate_referral_code(user_id),
        "referral_url": f"{PUBLIC_URL}?ref={quote(generate_referral_code(user_id))}"
    })

@app.route('/claim', methods=['POST'])
def claim():
    data = request.get_json()
    user_id = data.get('user_id')
    referrer_code = data.get('referrer_code', None)
    if not user_id:
        return jsonify({"error": "ID utilisateur manquant"}), 400

    service = get_google_sheets_service()
    user_result = service.values().get(
        spreadsheetId=GOOGLE_SHEET_ID,
        range=USER_RANGE,
        majorDimension="ROWS"
    ).execute()
    user_values = user_result.get('values', [])

    points = random.randint(10, 100)
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    referral_bonus = 0

    # Vérification délai entre claims
    for row in user_values:
        if str(row[0]) == str(user_id) and len(row) > 2 and row[2]:
            try:
                last_claim = datetime.strptime(row[2], "%d/%m/%Y %H:%M")
                if (datetime.now() - last_claim) < timedelta(minutes=5):
                    return jsonify({"error": "Attends 5 minutes entre chaque réclamation"}), 400
            except ValueError:
                pass

    try:
        # Trouver le parrain si code de parrainage fourni
        referrer_id = None
        if referrer_code:
            for row in user_values:
                if len(row) > 5 and row[5] == referrer_code:
                    referrer_id = row[0]
                    referral_bonus = int(points * 0.05)  # 5% de bonus
                    break

        updated = False
        # Mise à jour utilisateur existant
        for idx, row in enumerate(user_values):
            if str(row[0]) == str(user_id):
                current_balance = int(row[1]) if len(row) > 1 and row[1] else 0
                new_balance = current_balance + points
                
                # Générer un code de parrainage si inexistant
                referral_code = row[5] if len(row) > 5 else generate_referral_code(user_id)
                
                service.values().update(
                    spreadsheetId=GOOGLE_SHEET_ID,
                    range=f"Users!B{idx+2}:F{idx+2}",  # Mise à jour jusqu'à la colonne F
                    valueInputOption="USER_ENTERED",
                    body={"values": [[new_balance, now, row[3] if len(row) > 3 else "", row[4] if len(row) > 4 else "", referral_code]]}
                ).execute()
                updated = True
                break

        # Nouvel utilisateur (insertion en haut)
        if not updated:
            referral_code = generate_referral_code(user_id)
            service.values().append(
                spreadsheetId=GOOGLE_SHEET_ID,
                range=USER_RANGE,
                valueInputOption="USER_ENTERED",
                body={"values": [[user_id, points, now, referrer_id if referrer_id else "", "", referral_code]]},
                insertDataOption="INSERT_ROWS"
            ).execute()

        # Transaction utilisateur (insertion en haut)
        service.values().append(
            spreadsheetId=GOOGLE_SHEET_ID,
            range=TRANSACTION_RANGE,
            valueInputOption="USER_ENTERED",
            body={"values": [[user_id, "claim", points, now]]},
            insertDataOption="INSERT_ROWS"
        ).execute()

        # Bonus parrainage si applicable
        if referrer_id and referral_bonus > 0:
            for idx, row in enumerate(user_values):
                if str(row[0]) == str(referrer_id):
                    current_balance = int(row[1]) if len(row) > 1 and row[1] else 0
                    new_balance = current_balance + referral_bonus
                    
                    service.values().update(
                        spreadsheetId=GOOGLE_SHEET_ID,
                        range=f"Users!B{idx+2}",
                        valueInputOption="USER_ENTERED",
                        body={"values": [[new_balance]]}
                    ).execute()
                    
                    # Enregistrement transaction parrain
                    service.values().append(
                        spreadsheetId=GOOGLE_SHEET_ID,
                        range=TRANSACTION_RANGE,
                        valueInputOption="USER_ENTERED",
                        body={"values": [[referrer_id, "referral_bonus", referral_bonus, now]]},
                        insertDataOption="INSERT_ROWS"
                    ).execute()
                    break

        return jsonify({
            "success": f"{points} points ajoutés !" + (f" (+{referral_bonus} points pour ton parrain !" if referral_bonus else ""),
            "new_balance": new_balance if updated else points,
            "last_claim": now,
            "referral_bonus": referral_bonus
        })

    except Exception as e:
        print(f"Erreur Sheets: {str(e)}")
        return jsonify({"error": "Erreur serveur lors de la mise à jour"}), 500

# [...] (Les autres endpoints get-tasks et get-friends restent identiques)

@bot.message_handler(commands=['start'])
def start(message):
    ref_code = None
    if len(message.text.split()) > 1:
        ref_code = message.text.split()[1]
    
    start_url = f"{PUBLIC_URL}?ref={ref_code}" if ref_code else PUBLIC_URL
    bot.send_message(
        message.chat.id,
        f"🎉 Bienvenue ! Clique ici pour commencer :\n{start_url}",
        disable_web_page_preview=True
    )

if __name__ == "__main__":
    Thread(target=bot.polling, kwargs={'none_stop': True}).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))