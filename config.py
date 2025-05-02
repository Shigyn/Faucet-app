import os
import random

# Récupérer les valeurs sensibles depuis les variables d'environnement
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
TELEGRAM_BOT_API_KEY = os.getenv("TELEGRAM_BOT_API_KEY")

# Chemin vers les credentials Google
GOOGLE_CREDENTIALS_FILE = "google/service_account_credentials.json"  # Utilisation du chemin pour le fichier service account
GOOGLE_CREDS_URL = os.getenv("GOOGLE_CREDS_URL")  # Utilisation de la variable d'environnement pour l'URL de récupération

# Définition des plages (ranges) dans la feuille Google Sheets
USER_RANGE = os.getenv("USER_RANGE", "Users!A2:C")  # Plage des utilisateurs, colonne A pour l'ID utilisateur, B pour le solde, C pour la dernière réclamation
TRANSACTION_RANGE = os.getenv("TRANSACTION_RANGE", "Transactions!A2:D")  # Plage des transactions, colonne A pour l'ID utilisateur, B pour la date de transaction, C pour le montant, D pour l'horodatage

# Nombre de points donnés à chaque réclamation - Aléatoire entre 10 et 100
CLAIM_POINTS = random.randint(10, 100)  # Génère un nombre aléatoire entre 10 et 100

# Génération de token.json si nécessaire
TOKEN_PATH = "google/token.json"  # Chemin vers le fichier token.json, utilisé après l'authentification avec Google

# Fonction pour vérifier si le token existe déjà
def get_token_path():
    if not os.path.exists(TOKEN_PATH):
        print("Le fichier token.json n'existe pas, il sera généré lors de l'authentification.")
    return TOKEN_PATH
