// static/js/cooldown.js
class CooldownManager {
  constructor() {
    this.cooldowns = new Map();
    this.COOLDOWN_MINUTES = 5;
  }

  startCooldown(userId) {
    const cooldownEnd = Date.now() + this.COOLDOWN_MINUTES * 60000;
    this.cooldowns.set(userId, cooldownEnd);
    return cooldownEnd;
  }

  getRemainingTime(userId) {
    if (!this.cooldowns.has(userId)) return 0;
    return Math.max(0, this.cooldowns.get(userId) - Date.now());
  }

  isOnCooldown(userId) {
    return this.getRemainingTime(userId) > 0;
  }

  formatTime(ms) {
    const minutes = Math.floor(ms / 60000);
    const seconds = Math.floor((ms % 60000) / 1000);
    return `${minutes}m ${seconds}s`;
  }
}

export const cooldownManager = new CooldownManager();