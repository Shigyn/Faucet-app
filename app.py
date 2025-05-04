import os
import telebot
from flask import Flask, request, render_template, send_from_directory, jsonify
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta

app = Flask(__name__)

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

@app.route('/')
def index():
    user_id = request.args.get('user_id')
    balance = get_user_balance(user_id) if user_id else None
    return render_template("index.html", balance=balance, user_id=user_id)

@app.route('/claim', methods=['GET'])
def claim_page():
    user_id = request.args.get('user_id')
    user_balance = get_user_balance(user_id) if user_id else None
    return render_template("claim.html", balance=user_balance, user_id=user_id)

@app.route('/submit_claim', methods=['POST'])
def submit_claim():
    user_id = request.form.get('user_id')
    if not user_id:
        return "ID utilisateur manquant."

    points = 100
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
                    return render_template("claim.html", error="Tu as déjà réclamé des points il y a moins de 5 minutes. Essaie plus tard.", balance=int(row[1]), user_id=user_id)

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

    balance = get_user_balance(user_id)
    return render_template("claim.html", points=points, balance=balance, user_id=user_id)

@app.route('/get_balance')
def get_balance():
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({'error': 'user_id manquant'}), 400

    try:
        balance = get_user_balance(user_id)
        return jsonify({'balance': balance})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

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

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'), 'favicon.ico', mimetype='image/vnd.microsoft.icon')

def get_user_balance(user_id):
    if not user_id:
        return 0
    service = get_google_sheets_service()
    result = service.values().get(spreadsheetId=GOOGLE_SHEET_ID, range=USER_RANGE).execute()
    values = result.get('values', [])

    for row in values:
        if str(row[0]) == str(user_id):
            return int(row[1]) if len(row) > 1 and row[1] else 0

    return 0

# Nouvelle route pour la page Friends
@app.route('/friends')
def friends_page():
    user_id = request.args.get('user_id')
    
    # On récupère les informations de l'utilisateur, comme son solde de points
    user_balance = get_user_balance(user_id) if user_id else None

    # Récupérer les amis et leurs points
    friends = get_user_friends(user_id)  # Cette fonction devra être créée pour récupérer les amis
    
    return render_template("friends.html", balance=user_balance, friends=friends, user_id=user_id)

# Fonction pour récupérer les amis et leurs points
def get_user_friends(user_id):
    service = get_google_sheets_service()
    result = service.values().get(spreadsheetId=GOOGLE_SHEET_ID, range=USER_RANGE).execute()
    values = result.get('values', [])

    friends_list = []
    
    for row in values:
        if str(row[0]) == str(user_id):  # Si on trouve l'utilisateur
            # Supposons que les amis sont dans la colonne 3 et les points dans la colonne 2 (ajuste selon ta structure)
            friends_ids = row[3] if len(row) > 3 else []  # Liste des IDs d'amis (si existante)
            for friend_id in friends_ids.split(','):  # Si les amis sont séparés par des virgules
                friend_balance = get_user_balance(friend_id.strip())  # On récupère le solde de chaque ami
                friends_list.append({'id': friend_id.strip(), 'balance': friend_balance})

    return friends_list

if __name__ == "__main__":
    set_telegram_webhook()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
