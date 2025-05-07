import os
import random
import telebot
from flask import Flask, request, render_template, jsonify
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta
from threading import Thread
from urllib.parse import quote

app = Flask(__name__, template_folder='templates')

# Config
TELEGRAM_BOT_API_KEY = os.getenv('TELEGRAM_BOT_API_KEY')
GOOGLE_SHEET_ID = os.getenv('GOOGLE_SHEET_ID')
USER_RANGE = "Users!A2:F"
TRANSACTION_RANGE = "Transactions!A2:D"
TASKS_RANGE = "Tasks!A2:D"
PUBLIC_URL = os.getenv('PUBLIC_URL')

# Initialisation
bot = telebot.TeleBot(TELEGRAM_BOT_API_KEY)
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

def get_google_sheets_service():
    creds_json = os.environ.get('GOOGLE_CREDS')
    if not creds_json:
        raise ValueError("GOOGLE_CREDS manquant dans les variables d'environnement")
    return build('sheets', 'v4', credentials=Credentials.from_service_account_info(eval(creds_json), scopes=SCOPES)).spreadsheets()

def generate_referral_code(user_id):
    return f"REF-{user_id}-{random.randint(1000,9999)}"

# Middleware pour vérifier le Content-Type
@app.before_request
def check_content_type():
    if request.method in ['POST', 'PUT'] and not request.is_json:
        return jsonify({"error": "Content-Type must be application/json"}), 415

# Routes API
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/get-balance', methods=['POST'])
def get_balance():
    try:
        data = request.get_json()
        user_id = str(data.get('user_id', ''))
        
        if not user_id:
            return jsonify({"error": "user_id est requis"}), 400

        service = get_google_sheets_service()
        result = service.values().get(spreadsheetId=GOOGLE_SHEET_ID, range=USER_RANGE).execute()
        rows = result.get('values', [])
        
        for row in rows:
            if row and str(row[0]) == user_id:
                return jsonify({
                    "balance": int(row[1]) if len(row) > 1 and row[1] else 0,
                    "last_claim": row[2] if len(row) > 2 else None,
                    "referral_url": f"{PUBLIC_URL}?ref={quote(row[5])}" if len(row) > 5 and row[5] else ""
                })
        
        # Si utilisateur non trouvé, créer un nouvel enregistrement
        referral_code = generate_referral_code(user_id)
        service.values().append(
            spreadsheetId=GOOGLE_SHEET_ID,
            range=USER_RANGE,
            valueInputOption="USER_ENTERED",
            body={"values": [[user_id, 0, "", "", "", referral_code]]}
        ).execute()
        
        return jsonify({
            "balance": 0,
            "last_claim": None,
            "referral_url": f"{PUBLIC_URL}?ref={quote(referral_code)}"
        })

    except Exception as e:
        app.logger.error(f"Erreur get-balance: {str(e)}")
        return jsonify({"error": "Erreur serveur", "details": str(e)}), 500

@app.route('/get-tasks', methods=['GET', 'POST'])
def get_tasks():
    try:
        # Accepte GET et POST pour compatibilité
        user_id = str(request.args.get('user_id') or (request.get_json() or {}).get('user_id', ''))
        
        service = get_google_sheets_service()
        result = service.values().get(spreadsheetId=GOOGLE_SHEET_ID, range=TASKS_RANGE).execute()
        
        tasks = []
        for row in result.get('values', []):
            if len(row) >= 4:
                tasks.append({
                    "task_name": row[0],
                    "description": row[1],
                    "points": int(row[2]) if row[2].isdigit() else 0,
                    "url": row[3]
                })
        
        return jsonify({"tasks": tasks})

    except Exception as e:
        app.logger.error(f"Erreur get-tasks: {str(e)}")
        # Fallback si erreur
        return jsonify({
            "tasks": [
                {
                    "task_name": "Rejoindre le channel",
                    "description": "Abonnez-vous à notre channel Telegram",
                    "points": 50,
                    "url": "https://t.me/CRYPTORATS_annonces"
                },
                {
                    "task_name": "Follow Twitter",
                    "description": "Suivez-nous sur Twitter",
                    "points": 30,
                    "url": "https://twitter.com/CRYPTORATS_off"
                }
            ]
        })

@app.route('/get-friends', methods=['GET'])
def get_friends():
    try:
        user_id = request.args.get('user_id')
        if not user_id:
            return jsonify({"error": "user_id est requis"}), 400
        
        # Implémentation simplifiée - à adapter selon ta structure de données
        return jsonify({
            "referrals": [],
            "message": "Fonctionnalité en développement"
        })

    except Exception as e:
        app.logger.error(f"Erreur get-friends: {str(e)}")
        return jsonify({"referrals": []})

@app.route('/claim', methods=['POST'])
def claim():
    try:
        data = request.get_json()
        user_id = str(data.get('user_id', ''))
        referrer_code = data.get('referrer_code', '')

        if not user_id:
            return jsonify({"error": "user_id est requis"}), 400

        service = get_google_sheets_service()
        now = datetime.now().strftime("%d/%m/%Y %H:%M")
        points = random.randint(10, 100)

        # Vérification délai entre claims
        result = service.values().get(spreadsheetId=GOOGLE_SHEET_ID, range=USER_RANGE).execute()
        for row in result.get('values', []):
            if row and str(row[0]) == user_id and len(row) > 2 and row[2]:
                last_claim = datetime.strptime(row[2], "%d/%m/%Y %H:%M")
                if (datetime.now() - last_claim) < timedelta(minutes=5):
                    return jsonify({"error": "Attendez 5 minutes entre chaque réclamation"}), 400

        # Mise à jour du solde
        service.values().append(
            spreadsheetId=GOOGLE_SHEET_ID,
            range=USER_RANGE,
            valueInputOption="USER_ENTERED",
            body={"values": [[user_id, points, now, "", "", generate_referral_code(user_id)]]}
        ).execute()

        return jsonify({
            "success": f"{points} points ajoutés !",
            "new_balance": points
        })

    except Exception as e:
        app.logger.error(f"Erreur claim: {str(e)}")
        return jsonify({"error": "Erreur serveur"}), 500

# Routes Telegram
@bot.message_handler(commands=['start'])
def start(message):
    ref_code = message.text.split()[1] if len(message.text.split()) > 1 else None
    start_url = f"{PUBLIC_URL}?ref={quote(ref_code)}" if ref_code else PUBLIC_URL
    
    bot.send_message(
        message.chat.id,
        f"🪙 *CRYPTORATS_bot* 🐭\n\n"
        f"Gagne des points en complétant des tâches !\n"
        f"Commence ici : {start_url}",
        parse_mode="Markdown",
        disable_web_page_preview=True
    )

if __name__ == "__main__":
    # Démarrer le bot Telegram dans un thread séparé
    Thread(target=bot.infinity_polling, daemon=True).start()
    
    # Démarrer le serveur Flask
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)