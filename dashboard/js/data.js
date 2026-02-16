/* ════════════════════════════════════════════════════════════════
   DATA FETCHING & API CALLS
   ════════════════════════════════════════════════════════════════ */

// ── Trading Mode ──
async function fetchMode() {
  try {
    const resp = await fetch(API + '/api/mode');
    const data = await resp.json();
    tradingMode = (data.mode || 'REAL').toUpperCase();
    renderMode();
  } catch (e) {
    // keep previous mode
  }
}

async function toggleMode() {
  const nextMode = tradingMode === 'PAPER' ? 'REAL' : 'PAPER';
  const btn = document.getElementById('modeBtn');
  btn.disabled = true;
  btn.textContent = 'MODE: ...';

  try {
    const resp = await fetch(API + '/api/mode', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode: nextMode })
    });
    const data = await resp.json();
    if (data.success) {
      tradingMode = data.mode;
      renderMode();
      showToast(`Mode switched to ${data.mode}`, 'success');
    } else {
      showToast(data.error || 'Failed to switch mode', 'error');
    }
  } catch (e) {
    showToast('Failed to switch mode', 'error');
  } finally {
    btn.disabled = false;
  }
}

// ── Bot Control ──
async function toggleBot() {
  const btn = document.getElementById('toggleBtn');
  btn.disabled = true;

  const endpoint = botRunning ? '/api/bot/stop' : '/api/bot/start';
  const action   = botRunning ? 'Stopping...' : 'Starting...';
  btn.textContent = action;

  try {
    const resp = await fetch(API + endpoint, { method: 'POST' });
    const data = await resp.json();
    if (data.success) {
      showToast(data.message, 'success');
      setTimeout(checkBotStatus, 1500);
    } else {
      showToast(data.message || 'Failed', 'error');
      btn.disabled = false;
    }
  } catch (e) {
    showToast('Request failed', 'error');
    btn.disabled = false;
  }
}

async function checkBotStatus() {
  try {
    const resp = await fetch(API + '/api/bot/status');
    const data = await resp.json();
    botRunning = data.running;

    const btn = document.getElementById('toggleBtn');
    const dot = document.getElementById('statusDot');
    const txt = document.getElementById('statusText');

    if (botRunning) {
      btn.textContent = '⏹ Stop Bot';
      btn.className = 'toggle-btn stop';
      dot.className = 'dot live';
      txt.textContent = 'LIVE';
    } else {
      btn.textContent = '▶ Start Bot';
      btn.className = 'toggle-btn start';
      dot.className = 'dot stopped';
      txt.textContent = 'STOPPED';
    }
    btn.disabled = false;
  } catch (e) {
    document.getElementById('statusText').textContent = 'OFFLINE';
  }
}

// ── Main Data Fetch ──
async function fetchAll() {
  try {
    const [stats, equity, trades, logs, paperStats, paperTrades] = await Promise.all([
      fetch(API + '/api/stats').then(r => r.json()),
      fetch(API + '/api/equity').then(r => r.json()),
      fetch(API + '/api/trades').then(r => r.json()),
      fetch(API + '/api/logs').then(r => r.json()),
      fetch(API + '/api/paper/stats').then(r => r.json()),
      fetch(API + '/api/paper/trades').then(r => r.json()),
    ]);

    // Balance via status
    fetch(API + '/api/status').then(r => r.json()).then(s => {
      const numericBalance = Number(s.balance);
      const currency = String(s.balance_currency || '').toUpperCase();
      const symbol = currency === 'INR' ? '₹' : currency === 'USDT' || currency === 'USD' ? '$' : '';
      document.getElementById('balance').textContent = Number.isFinite(numericBalance)
        ? `${symbol}${numericBalance.toFixed(2)}${symbol ? '' : ' ' + (currency || '')}`
        : '—';
      document.getElementById('balanceSub').textContent = currency ? `${currency} futures` : 'Futures wallet';
      document.getElementById('openPositions').textContent = s.open_trades ?? 0;

      const paperBal = Number(s.paper_balance);
      document.getElementById('paperBalance').textContent = Number.isFinite(paperBal)
        ? `${symbol}${paperBal.toFixed(2)}${symbol ? '' : ' ' + (currency || '')}`
        : '—';
    });

    latestTrades = trades || [];
    latestPaperTrades = paperTrades || [];

    renderStats(stats);
    renderEquity(equity);
    renderTrades(trades);
    renderPnlChart(trades);
    renderLogs(logs);
    renderPaperStats(paperStats, paperTrades);
    renderPaperTrades(paperTrades);
    updatePairPnlChart();

    document.getElementById('lastUpdate').textContent = 'Updated ' + new Date().toLocaleTimeString();
  } catch (e) {
    console.error('Fetch error:', e);
  }
}

// ── Pair Config ──
async function loadPairs() {
  try {
    const [available, configs] = await Promise.all([
      fetch(API + '/api/pairs/available').then(r => r.json()),
      fetch(API + '/api/pairs/config').then(r => r.json())
    ]);

    allPairs = available || [];

    if (!allPairs.length) {
      document.getElementById('coinGrid').innerHTML = '<div class="loading">No pairs available</div>';
      return;
    }

    renderPairs();
    renderFavorites();
    updatePairSelect();
    document.getElementById('applyCoinsBtn').disabled = false;
    updateReadiness();
  } catch (e) {
    console.error('Error loading pairs:', e);
    document.getElementById('coinGrid').innerHTML = '<div class="loading">Error loading pairs</div>';
  }
}

async function applyPairChanges() {
  const btn = document.getElementById('applyCoinsBtn');
  btn.disabled = true;
  btn.textContent = 'Applying...';

  try {
    const pairs = Object.keys(pairConfigs).map(pair => ({
      pair,
      enabled: pairConfigs[pair].enabled,
      leverage: pairConfigs[pair].leverage,
      quantity: pairConfigs[pair].quantity
    }));

    const resp = await fetch(API + '/api/pairs/config/bulk', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pairs })
    });

    const data = await resp.json();
    if (data.success) {
      showToast('Pair settings updated! Restart bots to apply.', 'success');

      // Auto-restart if bot is running
      if (botRunning) {
        setTimeout(async () => {
          await fetch(API + '/api/bot/stop', { method: 'POST' });
          setTimeout(() => fetch(API + '/api/bot/start', { method: 'POST' }), 2000);
        }, 1000);
      }
    } else {
      showToast(data.error || 'Failed to update settings', 'error');
    }
  } catch (e) {
    showToast('Request failed', 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Apply Changes & Restart Bots';
  }
}

async function updateReadiness() {
  if (!pairsList.length) return;
  try {
    const resp = await fetch(API + '/api/signal/readiness?pairs=' + encodeURIComponent(pairsList.join(',')));
    const data = await resp.json();
    data.forEach(item => {
      const bar = document.querySelector(`[data-readiness="${item.pair}"]`);
      const val = document.querySelector(`[data-readiness-val="${item.pair}"]`);
      if (!bar || !val) return;
      const pct = Math.min(100, Math.max(0, item.readiness || 0));
      bar.style.width = pct + '%';
      val.textContent = `${pct}% ${item.bias}`;
    });
  } catch (e) {
    // ignore readiness errors
  }
}

async function resetPaperBalance() {
  try {
    const resp = await fetch(API + '/api/paper/reset', { method: 'POST' });
    const data = await resp.json();
    if (data.success) {
      showToast('Paper balance reset', 'success');
      fetchAll();
    } else {
      showToast('Failed to reset paper balance', 'error');
    }
  } catch (e) {
    showToast('Failed to reset paper balance', 'error');
  }
}
