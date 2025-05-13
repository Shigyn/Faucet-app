<script>
    // Configuration
    const API_BASE_URL = "https://faucet-app.onrender.com";
    const COOLDOWN_MINUTES = 5;

    let currentUserId = null;
    let currentUsername = "Utilisateur";
    let currentBalance = 0;
    let isClaiming = false;
    let refreshInterval;
    let lastClaimTime = null;

    // Initialisation
    function initApp() {
        console.log("Initialisation de l'application...");
        
        if (window.Telegram?.WebApp?.initData) {
            console.log("Données Telegram détectées");
            initTelegramWebApp();
        } else {
            console.warn("Mode debug activé (pas via Telegram)");
            document.getElementById('telegram-alert').style.display = 'block';
            currentUserId = "debug_user_" + Math.floor(Math.random() * 1000);
            currentUsername = "DebugUser";
            startAutoRefresh();
            loadData();
        }
        
        setupEventListeners();
    }

    function initTelegramWebApp() {
        const tg = window.Telegram.WebApp;
        
        if (!tg.initData || !tg.initDataUnsafe?.user?.id) {
            console.error("Données Telegram incomplètes");
            return;
        }

        tg.expand();
        tg.ready();
        document.getElementById('telegram-alert').style.display = 'none';
        
        const user = tg.initDataUnsafe.user;
        currentUserId = user.id.toString();
        currentUsername = user.username || 
                           [user.first_name, user.last_name].filter(Boolean).join(' ') || 
                           "Joueur";
        
        document.getElementById('username-display').textContent = currentUsername;
        console.log(`Utilisateur initialisé: ${currentUsername} (${currentUserId})`);

        fetch(`${API_BASE_URL}/update-user`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                user_id: currentUserId,
                username: currentUsername,
                initData: tg.initData
            })
        })
        .then(response => {
            if (!response.ok) throw new Error("Erreur serveur");
            startAutoRefresh();
            loadData();
        })
        .catch(error => {
            console.error("Erreur d'enregistrement:", error);
            showToast("Erreur de connexion", 3000, 'error');
        });
    }

    // Gestion des données
    async function loadData() {
        if (!currentUserId) return;

        try {
            console.log("Chargement des données...");
            const [balance, tasks, referrals] = await Promise.all([
                fetchBalance(),
                fetchTasks(),
                fetchReferrals()
            ]);
            
            updateUI({ balance, tasks, referrals });
        } catch (error) {
            console.error("Erreur de chargement:", error);
            showToast("Erreur de chargement", 3000, 'error');
        }
    }

    async function fetchBalance() {
        try {
            const response = await fetch(`${API_BASE_URL}/get-balance`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                    user_id: currentUserId,
                    initData: window.Telegram?.WebApp?.initData
                })
            });
            
            if (!response.ok) throw new Error("Erreur API");
            return await response.json();
        } catch (error) {
            console.error("Erreur fetchBalance:", error);
            throw error;
        }
    }

    async function fetchTasks() {
        try {
            const response = await fetch(`${API_BASE_URL}/get-tasks`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                    user_id: currentUserId,
                    initData: window.Telegram?.WebApp?.initData
                })
            });
            
            if (!response.ok) throw new Error("Erreur API");
            return await response.json();
        } catch (error) {
            console.error("Erreur fetchTasks:", error);
            return { tasks: [] };
        }
    }

    async function fetchReferrals() {
        try {
            const response = await fetch(`${API_BASE_URL}/get-referrals`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                    user_id: currentUserId,
                    initData: window.Telegram?.WebApp?.initData
                })
            });
            
            if (!response.ok) throw new Error("Erreur API");
            return await response.json();
        } catch (error) {
            console.error("Erreur fetchReferrals:", error);
            return { referrals: [] };
        }
    }

    // Mise à jour de l'interface
    function updateUI({ balance, tasks, referrals }) {
        if (balance) {
            updateBalanceDisplay(balance);
            updateClaimButton(balance);
        }
        
        if (tasks) {
            updateTasksList(tasks);
        }
        
        if (referrals) {
            updateReferralsList(referrals);
        }
    }

    function updateBalanceDisplay(data) {
        currentBalance = data.balance || 0;
        document.getElementById('balance-value').textContent = currentBalance;
        
        const lastClaimElement = document.getElementById('last-claim-value');
        if (data.last_claim) {
            lastClaimTime = new Date(data.last_claim);
            lastClaimElement.textContent = lastClaimTime.toLocaleTimeString();
        } else {
            lastClaimElement.textContent = 'Jamais';
        }
        
        document.getElementById('level-badge').textContent = `Niveau ${Math.floor(currentBalance / 100) + 1}`;
        
        // Mettre à jour le lien de parrainage
        if (data.referral_code) {
            document.getElementById('referral-link').value = 
                `https://t.me/CRYPTORATS_bot?start=${data.referral_code}`;
        }
    }

    function updateTasksList(tasks) {
        const container = document.getElementById('tasks-list');
        if (!tasks?.tasks?.length) {
            container.innerHTML = "<p>Aucune tâche disponible</p>";
            return;
        }

        container.innerHTML = tasks.tasks.map(task => `
            <div class="task-card">
                <h3>${escapeHTML(task.name || 'Tâche sans nom')}</h3>
                <p>${escapeHTML(task.description || 'Description non disponible')}</p>
                <span class="points-badge">${task.reward || 0} pts</span>
                <button class="task-btn" onclick="completeTask('${escapeString(task.name)}', ${task.reward || 0})">
                    ${isTaskCompleted(task.name) ? '✅ Terminé' : 'Commencer'}
                </button>
            </div>`).join('');
    }

    function updateReferralsList(referrals) {
        const container = document.getElementById('referrals-container');
        if (!referrals?.referrals?.length) {
            container.innerHTML = "<p>Aucun membre pour le moment</p>";
            return;
        }

        container.innerHTML = referrals.referrals.map(ref => `
            <div class="referral-item">
                <span class="referral-id">${ref.user_id.substring(0, 8)}...</span>
                <span class="referral-points">+${ref.points_earned || 0} pts</span>
                <span class="referral-date">${ref.timestamp ? new Date(ref.timestamp).toLocaleDateString() : ''}</span>
            </div>`).join('');
    }

    function updateClaimButton() {
        const claimBtn = document.getElementById('claim-btn');
        if (!claimBtn) return;

        if (lastClaimTime) {
            const cooldownEnd = new Date(lastClaimTime.getTime() + COOLDOWN_MINUTES * 60000);
            if (Date.now() < cooldownEnd) {
                startCooldownTimer(cooldownEnd);
                return;
            }
        }

        claimBtn.disabled = false;
        claimBtn.innerHTML = '<span class="button-icon">🎁</span><span class="button-text">Claim Now</span>';
    }

    // Actions utilisateur
    async function claimPoints() {
        if (isClaiming || !currentUserId) return;

        const claimBtn = document.getElementById('claim-btn');
        try {
            isClaiming = true;
            claimBtn.disabled = true;
            claimBtn.innerHTML = '<span class="button-icon">⏳</span><span class="button-text">Processing...</span>';

            const response = await fetch(`${API_BASE_URL}/claim`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                    user_id: currentUserId,
                    initData: window.Telegram?.WebApp?.initData
                })
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.message || "Erreur serveur");
            }

            const result = await response.json();
            console.log("Claim réussi:", result);
            
            showToast(`+${result.points_earned || 10} points !`, 3000, 'success');
            await loadData();

            if (result.last_claim) {
                lastClaimTime = new Date(result.last_claim);
                const cooldownEnd = new Date(lastClaimTime.getTime() + COOLDOWN_MINUTES * 60000);
                startCooldownTimer(cooldownEnd);
            }
        } catch (error) {
            console.error("Erreur claim:", error);
            showToast(error.message || "Erreur", 3000, 'error');
            claimBtn.disabled = false;
        } finally {
            isClaiming = false;
        }
    }

    async function completeTask(taskName, points) {
        try {
            const response = await fetch(`${API_BASE_URL}/complete-task`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    user_id: currentUserId,
                    task_name: taskName,
                    points: points,
                    initData: window.Telegram?.WebApp?.initData
                })
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.message || "Erreur serveur");
            }

            const result = await response.json();
            
            const completedTasks = JSON.parse(localStorage.getItem('completedTasks') || '[]');
            completedTasks.push(taskName);
            localStorage.setItem('completedTasks', JSON.stringify(completedTasks));
            
            showToast(`Tâche complétée ! +${points} points`, 3000, 'success');
            await loadData();
        } catch (error) {
            console.error("Erreur completeTask:", error);
            showToast(error.message || "Erreur", 3000, 'error');
        }
    }

    // Utilitaires
    function startAutoRefresh() {
        clearInterval(refreshInterval);
        refreshInterval = setInterval(() => {
            if (document.visibilityState === 'visible') {
                loadData();
            }
        }, 30000);
    }

    function startCooldownTimer(cooldownEnd) {
        const claimBtn = document.getElementById('claim-btn');
        if (!claimBtn) return;

        claimBtn.disabled = true;

        function updateTimer() {
            const remaining = Math.max(0, cooldownEnd - Date.now());
            if (remaining <= 0) {
                claimBtn.disabled = false;
                claimBtn.innerHTML = '<span class="button-icon">🎁</span><span class="button-text">Claim Now</span>';
                return;
            }

            const minutes = Math.floor(remaining / 60000);
            const seconds = Math.floor((remaining % 60000) / 1000);

            claimBtn.innerHTML = `
                <span class="button-icon">⏳</span>
                <span class="button-text">${minutes}m ${seconds}s</span
