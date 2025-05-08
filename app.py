import os
import logging
from flask import Flask, render_template, request, redirect, url_for, jsonify
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from google.oauth2 import service_account
import time
from datetime import datetime
from threading import Lock  # Importation du verrou pour la gestion concurrente

app = Flask(__name__)

# Configurez le logging
logging.basicConfig(level=logging.INFO)

# Configuration des credentials Google API
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SERVICE_ACCOUNT_FILE = 'path/to/your/service-account-file.json'

# ID du spreadsheet et des feuilles
SPREADSHEET_ID = 'votre_id_de_spreadsheet'
USERS_RANGE = 'Users!A2:F'
TRANSACTIONS_RANGE = 'Transactions!A2:D'
TASKS_RANGE = 'Tasks!A2:D'
FRIENDS_RANGE = 'Friends!A2:C'

# Verrou pour sécuriser l'accès à Google Sheets
sheet_lock = Lock()

# Fonction d'authentification Google
def get_google_sheets_service():
    creds = None
    if os.path.exists('token.json'):
        creds = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            raise Exception("Credentials are missing or invalid")
    service = build('sheets', 'v4', credentials=creds)
    return service

# Page d'accueil
@app.route('/')
def home():
    return render_template('index.html')  # Assurez-vous que ce fichier existe dans templates

# Récupérer la balance utilisateur
@app.route('/get-balance', methods=['POST'])
def get_balance():
    user_id = request.json.get('user_id')
    service = get_google_sheets_service()
    
    try:
        # Récupérer les données des utilisateurs
        sheet = service.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range=USERS_RANGE).execute()
        users = sheet.get('values', [])
        
        # Chercher la balance de l'utilisateur
        for user in users:
            if user[2] == user_id:
                balance = user[3]
                return jsonify({"balance": balance}), 200
        
        return jsonify({"error": "User not found"}), 404
    
    except Exception as e:
        logging.error(f"Error retrieving balance: {e}")
        return jsonify({"error": "Unable to retrieve balance"}), 500

# Ajouter une transaction
@app.route('/add-transaction', methods=['POST'])
def add_transaction():
    user_id = request.json.get('user_id')
    amount = request.json.get('amount')
    action = request.json.get('action')
    
    service = get_google_sheets_service()
    
    try:
        # Ajouter une ligne dans la feuille de transactions
        sheet = service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=TRANSACTIONS_RANGE,
            valueInputOption='RAW',
            body={'values': [[user_id, amount, action]]}
        ).execute()

        return jsonify({"message": "Transaction added successfully"}), 200

    except Exception as e:
        logging.error(f"Error adding transaction: {e}")
        return jsonify({"error": "Unable to add transaction"}), 500

# Mise à jour de la balance après un claim
@app.route('/claim', methods=['POST'])
def claim():
    user_id = request.json.get('user_id')
    amount = request.json.get('amount')
    
    service = get_google_sheets_service()
    
    try:
        # Récupérer les données des utilisateurs
        sheet = service.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range=USERS_RANGE).execute()
        users = sheet.get('values', [])
        
        # Chercher l'utilisateur et mettre à jour la balance
        for user in users:
            if user[2] == user_id:
                current_balance = int(user[3])
                new_balance = current_balance + int(amount)
                user[3] = str(new_balance)

                with sheet_lock:  # Utilisation du verrou pour la mise à jour de la feuille
                    # Mise à jour de la balance dans la feuille
                    service.spreadsheets().values().update(
                        spreadsheetId=SPREADSHEET_ID,
                        range=f"Users!D{users.index(user) + 2}",
                        valueInputOption='RAW',
                        body={'values': [[str(new_balance)]]}
                    ).execute()

                    # Ajouter une transaction pour le claim
                    service.spreadsheets().values().append(
                        spreadsheetId=SPREADSHEET_ID,
                        range=TRANSACTIONS_RANGE,
                        valueInputOption='RAW',
                        body={'values': [[user_id, amount, 'claim']]},
                    ).execute()

                return jsonify({"message": f"Claim successful, new balance: {new_balance}"}), 200
        
        return jsonify({"error": "User not found"}), 404
    
    except Exception as e:
        logging.error(f"Error handling claim: {e}")
        return jsonify({"error": "Unable to process claim"}), 500

# Mettre à jour la dernière action de claim
@app.route('/update-last-claim', methods=['POST'])
def update_last_claim():
    user_id = request.json.get('user_id')
    timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    
    service = get_google_sheets_service()
    
    try:
        # Récupérer les données des utilisateurs
        sheet = service.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range=USERS_RANGE).execute()
        users = sheet.get('values', [])
        
        # Chercher l'utilisateur et mettre à jour le champ 'last_claim'
        for user in users:
            if user[2] == user_id:
                # Update last claim timestamp
                service.spreadsheets().values().update(
                    spreadsheetId=SPREADSHEET_ID,
                    range=f"Users!E{users.index(user) + 2}",
                    valueInputOption='RAW',
                    body={'values': [[timestamp]]}
                ).execute()
                return jsonify({"message": "Last claim updated"}), 200
        
        return jsonify({"error": "User not found"}), 404
    
    except Exception as e:
        logging.error(f"Error updating last claim: {e}")
        return jsonify({"error": "Unable to update last claim"}), 500

# Route pour gérer les amis
@app.route('/add-friend', methods=['POST'])
def add_friend():
    user_id = request.json.get('user_id')
    friend_id = request.json.get('friend_id')
    
    service = get_google_sheets_service()
    
    try:
        # Ajouter un ami à la feuille "Friends"
        sheet = service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=FRIENDS_RANGE,
            valueInputOption='RAW',
            body={'values': [[user_id, friend_id]]}
        ).execute()

        return jsonify({"message": "Friend added successfully"}), 200

    except Exception as e:
        logging.error(f"Error adding friend: {e}")
        return jsonify({"error": "Unable to add friend"}), 500

# Route pour gérer les tâches
@app.route('/add-task', methods=['POST'])
def add_task():
    user_id = request.json.get('user_id')
    task = request.json.get('task')
    
    service = get_google_sheets_service()
    
    try:
        # Ajouter une tâche à la feuille "Tasks"
        sheet = service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=TASKS_RANGE,
            valueInputOption='RAW',
            body={'values': [[user_id, task]]}
        ).execute()

        return jsonify({"message": "Task added successfully"}), 200

    except Exception as e:
        logging.error(f"Error adding task: {e}")
        return jsonify({"error": "Unable to add task"}), 500

# Route pour récupérer les tâches d'un utilisateur
@app.route('/get-tasks', methods=['POST'])
def get_tasks():
    user_id = request.json.get('user_id')
    service = get_google_sheets_service()
    
    try:
        # Récupérer les données des tâches
        sheet = service.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range=TASKS_RANGE).execute()
        tasks = sheet.get('values', [])
        
        # Chercher les tâches pour l'utilisateur
        user_tasks = [task for task in tasks if task[0] == user_id]
        return jsonify({"tasks": user_tasks}), 200
    
    except Exception as e:
        logging.error(f"Error retrieving tasks: {e}")
        return jsonify({"error": "Unable to retrieve tasks"}), 500

# Lancer l'application
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=10000)
