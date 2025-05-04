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
TASKS_RANGE = os.getenv('TASKS_RANGE')

# Vérification des variables d’environnement
required_env_vars = {
    "TELEGRAM_BOT_API_KEY": TELEGRAM_BOT_API_KEY,
    "GOOGLE_SHEET_ID": GOOGLE_SHEET_ID,
    "USER_RANGE": USER_RANGE,
    "TRANSACTION_RANGE": TRANSACTION_RANGE,
    "TASKS_RANGE": TASKS_RANGE
}

for var, val in required_env_vars.items():
    if not val:
        raise ValueError(f"La variable d'environnement '{var}' est manquante.")

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

@app.route('/tasks')
def tasks_page():
    user_id = request.args.get('user_id')
    if not user_id:
        return "ID utilisateur manquant.", 400

    user_balance = get_user_balance(user_id)
    tasks = get_user_tasks(user_id)
    return render_template("tasks.html", balance=user_balance, tasks=tasks, user_id=user_id)

def get_user_tasks(user_id):
    """
    Récupère les tâches spécifiques d’un utilisateur depuis Google Sheets.
    Format attendu : user_id | titre | description | points | statut | lien
    """
    service = get_google_sheets_service()
    result = service.values().get(spreadsheetId=GOOGLE_SHEET_ID, range=TASKS_RANGE).execute()
    values = result.get('values', [])

    tasks_list = []
    for row in values:
        if len(row) < 1 or str(row[0]).strip() != str(user_id):
            continue
        task = {
            'title': row[1] if len(row) > 1 else "Tâche",
            'description': row[2] if len(row) > 2 else "Pas de description",
            'points': row[3] if len(row) > 3 else "0",
            'status': row[4].strip().lower() if len(row) > 4 else "non complété",
            'link': row[5] if len(row) > 5 else "#"
        }
        tasks_list.append(task)

    return tasks_list

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

@app.route('/friends')
def friends_page():
    user_id = request.args.get('user_id')
    user_balance = get_user_balance(user_id) if user_id else None
    friends = get_user_friends(user_id)
    return render_template("friends.html", balance=user_balance, friends=friends, user_id=user_id)

def get_user_friends(user_id):
    service = get_google_sheets_service()
    result = service.values().get(spreadsheetId=GOOGLE_SHEET_ID, range=USER_RANGE).execute()
    values = result.get('values', [])
    friends_list = []

    for row in values:
        if str(row[0]) == str(user_id):
            friends_ids = row[3] if len(row) > 3 else ""
            for friend_id in friends_ids.split(','):
                friend_id = friend_id.strip()
                if friend_id:
                    balance = get_user_balance(friend_id)
                    friends_list.append({'id': friend_id, 'balance': balance})
            break

    return friends_list

if __name__ == "__main__":
    set_telegram_webhook()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
