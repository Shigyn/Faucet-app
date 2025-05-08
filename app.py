import os
import json
import logging
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from googleapiclient.discovery import build
from google.oauth2 import service_account
from datetime import datetime
from threading import Lock

app = Flask(__name__)
CORS(app)

# Configuration
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SERVICE_ACCOUNT_FILE = 'google/credentials.json'
SPREADSHEET_ID = '1efhyhjqfXzu12fKN5KubPRephwJch4__QDG0ikmUv4s'
USERS_RANGE = 'Users!A2:F'
TRANSACTIONS_RANGE = 'Transactions!A2:D'
TASKS_RANGE = 'Tasks!A2:D'
FRIENDS_RANGE = 'Friends!A2:C'

sheet_lock = Lock()

def get_google_sheets_service():
    """Authentification Google Sheets avec fallback"""
    try:
        # 1. Essai avec le fichier local
        if os.path.exists(SERVICE_ACCOUNT_FILE):
            creds = service_account.Credentials.from_service_account_file(
                SERVICE_ACCOUNT_FILE, scopes=SCOPES)
            return build('sheets', 'v4', credentials=creds)
        
        # 2. Fallback sur variable d'environnement
        creds_json = os.getenv('GOOGLE_CREDENTIALS')
        if creds_json:
            creds_dict = json.loads(creds_json)
            creds = service_account.Credentials.from_service_account_info(
                creds_dict, scopes=SCOPES)
            return build('sheets', 'v4', credentials=creds)
            
        raise Exception("Aucune méthode d'authentification valide")
    except Exception as e:
        logger.error(f"Erreur auth: {str(e)}")
        raise

# ---------------------------
# ROUTES PRINCIPALES
# ---------------------------

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/get-balance', methods=['POST'])
def get_balance():
    try:
        user_id = request.json.get('user_id')
        if not user_id:
            return jsonify({"error": "user_id requis"}), 400

        service = get_google_sheets_service()
        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=USERS_RANGE
        ).execute()

        for user in result.get('values', []):
            if len(user) > 2 and user[2] == user_id:
                return jsonify({
                    "balance": user[3] if len(user) > 3 else 0,
                    "last_claim": user[4] if len(user) > 4 else None
                }), 200

        return jsonify({"error": "Utilisateur non trouvé"}), 404

    except Exception as e:
        logger.error(f"Erreur get_balance: {str(e)}")
        return jsonify({"error": "Erreur serveur"}), 500

@app.route('/claim', methods=['POST'])
def claim():
    try:
        user_id = request.json.get('user_id')
        amount = int(request.json.get('amount', 10))

        if not user_id:
            return jsonify({"error": "user_id requis"}), 400

        service = get_google_sheets_service()
        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=USERS_RANGE
        ).execute()

        users = result.get('values', [])
        for i, user in enumerate(users):
            if len(user) > 2 and user[2] == user_id:
                current_balance = int(user[3]) if len(user) > 3 and user[3] else 0
                new_balance = current_balance + amount
                timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

                with sheet_lock:
                    # Mise à jour balance
                    service.spreadsheets().values().update(
                        spreadsheetId=SPREADSHEET_ID,
                        range=f"Users!D{i+2}",
                        valueInputOption='USER_ENTERED',
                        body={'values': [[str(new_balance)]]}
                    ).execute()

                    # Mise à jour last claim
                    service.spreadsheets().values().update(
                        spreadsheetId=SPREADSHEET_ID,
                        range=f"Users!E{i+2}",
                        valueInputOption='USER_ENTERED',
                        body={'values': [[timestamp]]}
                    ).execute()

                    # Ajout transaction
                    service.spreadsheets().values().append(
                        spreadsheetId=SPREADSHEET_ID,
                        range=TRANSACTIONS_RANGE,
                        valueInputOption='USER_ENTERED',
                        body={'values': [[user_id, str(amount), 'claim', timestamp]]}
                    ).execute()

                return jsonify({
                    "message": "Claim réussi",
                    "new_balance": new_balance,
                    "last_claim": timestamp
                }), 200

        return jsonify({"error": "Utilisateur non trouvé"}), 404

    except Exception as e:
        logger.error(f"Erreur claim: {str(e)}")
        return jsonify({"error": "Erreur serveur"}), 500

# ---------------------------
# ROUTES SECONDARES
# ---------------------------

@app.route('/add-transaction', methods=['POST'])
def add_transaction():
    try:
        data = request.json
        required = ['user_id', 'amount', 'action']
        if not all(k in data for k in required):
            return jsonify({"error": "Données manquantes"}), 400

        service = get_google_sheets_service()
        service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=TRANSACTIONS_RANGE,
            valueInputOption='USER_ENTERED',
            body={'values': [[
                data['user_id'],
                str(data['amount']),
                data['action'],
                datetime.now().strftime("%d/%m/%Y %H:%M:%S")
            ]]}
        ).execute()

        return jsonify({"message": "Transaction ajoutée"}), 200

    except Exception as e:
        logger.error(f"Erreur add_transaction: {str(e)}")
        return jsonify({"error": "Erreur serveur"}), 500

@app.route('/update-last-claim', methods=['POST'])
def update_last_claim():
    try:
        user_id = request.json.get('user_id')
        if not user_id:
            return jsonify({"error": "user_id requis"}), 400

        service = get_google_sheets_service()
        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=USERS_RANGE
        ).execute()

        users = result.get('values', [])
        for i, user in enumerate(users):
            if len(user) > 2 and user[2] == user_id:
                timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
                service.spreadsheets().values().update(
                    spreadsheetId=SPREADSHEET_ID,
                    range=f"Users!E{i+2}",
                    valueInputOption='USER_ENTERED',
                    body={'values': [[timestamp]]}
                ).execute()
                return jsonify({"message": "Last claim updated"}), 200

        return jsonify({"error": "User not found"}), 404

    except Exception as e:
        logger.error(f"Erreur update_last_claim: {str(e)}")
        return jsonify({"error": "Erreur serveur"}), 500

@app.route('/add-friend', methods=['POST'])
def add_friend():
    try:
        user_id = request.json.get('user_id')
        friend_id = request.json.get('friend_id')
        if not all([user_id, friend_id]):
            return jsonify({"error": "Données manquantes"}), 400

        service = get_google_sheets_service()
        service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=FRIENDS_RANGE,
            valueInputOption='USER_ENTERED',
            body={'values': [[user_id, friend_id]]}
        ).execute()

        return jsonify({"message": "Ami ajouté"}), 200

    except Exception as e:
        logger.error(f"Erreur add_friend: {str(e)}")
        return jsonify({"error": "Erreur serveur"}), 500

@app.route('/add-task', methods=['POST'])
def add_task():
    try:
        user_id = request.json.get('user_id')
        task = request.json.get('task')
        if not all([user_id, task]):
            return jsonify({"error": "Données manquantes"}), 400

        service = get_google_sheets_service()
        service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=TASKS_RANGE,
            valueInputOption='USER_ENTERED',
            body={'values': [[user_id, task]]}
        ).execute()

        return jsonify({"message": "Tâche ajoutée"}), 200

    except Exception as e:
        logger.error(f"Erreur add_task: {str(e)}")
        return jsonify({"error": "Erreur serveur"}), 500

@app.route('/get-tasks', methods=['POST'])
def get_tasks():
    try:
        user_id = request.json.get('user_id')
        if not user_id:
            return jsonify({"error": "user_id requis"}), 400

        service = get_google_sheets_service()
        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=TASKS_RANGE
        ).execute()

        tasks = [t for t in result.get('values', []) if t[0] == user_id]
        return jsonify({"tasks": tasks}), 200

    except Exception as e:
        logger.error(f"Erreur get_tasks: {str(e)}")
        return jsonify({"error": "Erreur serveur"}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=10000)