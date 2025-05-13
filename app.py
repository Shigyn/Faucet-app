@app.route('/claim', methods=['POST'])
def claim():
    try:
        data = request.json
        user_id = str(data.get('user_id'))
        now = datetime.now()
        now_str = now.strftime('%Y-%m-%d %H:%M:%S')
        cooldown_minutes = 5  # Durée du cooldown en minutes
        
        service = get_sheets_service()
        
        # Phase 1: Vérification du cooldown
        users_data = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=RANGES['users']
        ).execute().get('values', [])
        
        user_row = next((row for row in users_data if len(row) > 2 and row[2] == user_id), None)
        
        # Vérification cooldown
        if user_row and len(user_row) > 4 and user_row[4]:  # Si last_claim existe
            last_claim = datetime.strptime(user_row[4], '%Y-%m-%d %H:%M:%S')
            cooldown_end = last_claim + timedelta(minutes=cooldown_minutes)
            
            if now < cooldown_end:
                remaining = cooldown_end - now
                return jsonify({
                    'status': 'cooldown',
                    'message': f'Revenez dans {remaining.seconds//60}m {remaining.seconds%60}s',
                    'cooldown_end': cooldown_end.timestamp(),
                    'remaining_seconds': remaining.total_seconds()
                }), 429  # HTTP 429 = Too Many Requests

        # Phase 2: Traitement du claim
        points = random.randint(10, 100)
        
        with sheet_lock:
            # Mise à jour utilisateur
            if user_row:
                row_num = users_data.index(user_row) + 2
                current_balance = int(user_row[3]) if len(user_row) > 3 else 0
                new_balance = current_balance + points
                
                service.spreadsheets().values().update(
                    spreadsheetId=SPREADSHEET_ID,
                    range=f'Users!D{row_num}:E{row_num}',
                    valueInputOption='USER_ENTERED',
                    body={'values': [[str(new_balance), now_str]]}
                ).execute()
            else:
                new_user = [
                    now_str,
                    data.get('username', f'User{user_id[:5]}'),
                    user_id,
                    str(points),
                    now_str,
                    user_id
                ]
                service.spreadsheets().values().append(
                    spreadsheetId=SPREADSHEET_ID,
                    range=RANGES['users'],
                    valueInputOption='USER_ENTERED',
                    body={'values': [new_user]}
                ).execute()
                new_balance = points
            
            # Ajout transaction
            service.spreadsheets().values().append(
                spreadsheetId=SPREADSHEET_ID,
                range=RANGES['transactions'],
                valueInputOption='USER_ENTERED',
                body={'values': [[user_id, str(points), 'claim', now_str]]}
            ).execute()
        
            # Donner les points au parrain
            points_for_referrer = int(points * 0.1)  # 10% pour le parrain

            # Trouve le parrain du user actuel
            referrals_data = service.spreadsheets().values().get(
                spreadsheetId=SPREADSHEET_ID,
                range=RANGES['referrals']
            ).execute().get('values', [])

            for row in referrals_data:
                if len(row) > 1 and row[1] == user_id:  # row[1] = referred_id
                    referrer_id = row[0]  # row[0] = referrer_id
                    
                    # Donne les points au parrain
                    users_data = service.spreadsheets().values().get(
                        spreadsheetId=SPREADSHEET_ID,
                        range=RANGES['users']
                    ).execute().get('values', [])
                    
                    for i, user_row in enumerate(users_data):
                        if len(user_row) > 2 and user_row[2] == referrer_id:
                            row_num = i + 2
                            current_balance = int(user_row[3]) if len(user_row) > 3 else 0
                            new_balance = current_balance + points_for_referrer
                            
                            service.spreadsheets().values().update(
                                spreadsheetId=SPREADSHEET_ID,
                                range=f'Users!D{row_num}',
                                valueInputOption='USER_ENTERED',
                                body={'values': [[str(new_balance)]]}
                            ).execute()
                            
                            # Enregistre la transaction pour le parrain
                            service.spreadsheets().values().append(
                                spreadsheetId=SPREADSHEET_ID,
                                range=RANGES['transactions'],
                                valueInputOption='USER_ENTERED',
                                body={'values': [[referrer_id, str(points_for_referrer), 'referral_bonus', now_str]]}
                            ).execute()
                            break
                    break
        
        return jsonify({
            'status': 'success',
            'new_balance': new_balance,
            'last_claim': now_str,
            'points_earned': points,
            'cooldown_end': (now + timedelta(minutes=cooldown_minutes)).timestamp()
        })
        
    except Exception as e:
        logger.error(f"Erreur claim: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e),
            'error_type': type(e).__name__
        }), 500