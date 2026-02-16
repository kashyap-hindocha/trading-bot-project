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
    renderActivePairs();
    updatePairPnlChart();
    
    // Fetch and display open trades
    await fetchOpenTrades();

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

    const configMap = {};
    (configs || []).forEach(cfg => {
      if (cfg && cfg.pair) configMap[cfg.pair] = cfg;
    });

    pairConfigs = {};
    allPairs.forEach(p => {
      const cfg = configMap[p.pair] || {};
      pairConfigs[p.pair] = {
        enabled: Number.isFinite(cfg.enabled) ? cfg.enabled : 0,
        leverage: Number.isFinite(cfg.leverage) ? cfg.leverage : 5,
        quantity: Number.isFinite(cfg.quantity) ? cfg.quantity : 0.001,
        inr_amount: Number.isFinite(cfg.inr_amount) ? cfg.inr_amount : 300
      };
    });

    if (!allPairs.length) {
      document.getElementById('coinGrid').innerHTML = '<div class="loading">No pairs available</div>';
      return;
    }

    // Set pairsList from allPairs before updateReadiness
    const limit = parseInt(document.getElementById('pairListLimit')?.value || '50', 10);
    pairsList = allPairs.slice(0, limit).map(p => p.pair);

    // Update readiness FIRST, then render with data
    await updateReadiness();
    
    renderPairs();
    renderFavorites();
    updatePairSelect();
    const btn = document.getElementById('applyCoinsBtn');
    if (btn) btn.disabled = false;
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
      quantity: pairConfigs[pair].quantity,
      inr_amount: pairConfigs[pair].inr_amount
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

const savePairTimers = {};

function scheduleSavePairConfig(pair, delayMs = 500) {
  if (savePairTimers[pair]) {
    clearTimeout(savePairTimers[pair]);
  }
  savePairTimers[pair] = setTimeout(() => {
    savePairConfig(pair, true);
  }, delayMs);
}

async function savePairConfig(pair, showSuccess = false) {
  const cfg = pairConfigs[pair];
  if (!cfg) return;

  try {
    const resp = await fetch(API + '/api/pairs/config/update', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        pair,
        enabled: cfg.enabled,
        leverage: cfg.leverage,
        quantity: cfg.quantity,
        inr_amount: cfg.inr_amount
      })
    });

    const data = await resp.json();
    if (!data.success) {
      showToast(data.error || 'Failed to update settings', 'error');
      return;
    }
    if (showSuccess) {
      showToast('Pair settings saved', 'success');
    }
  } catch (e) {
    showToast('Request failed', 'error');
  }
}

async function updateReadiness() {
  if (!pairsList || !pairsList.length) return;
  try {
    const resp = await fetch(API + '/api/signal/readiness?pairs=' + encodeURIComponent(pairsList.join(',')));
    const data = await resp.json();
    
    if (!Array.isArray(data)) return;
    
    // Store readiness data globally for sorting
    data.forEach(item => {
      if (!item || !item.pair) return;
      pairReadiness[item.pair] = item;
      
      const bar = document.querySelector(`[data-readiness="${item.pair}"]`);
      const val = document.querySelector(`[data-readiness-val="${item.pair}"]`);
      if (!bar || !val) return;
      const pct = Math.min(100, Math.max(0, item.readiness || 0));
      bar.style.width = pct + '%';
      val.textContent = `${pct}%`;
    });
  } catch (e) {
    console.debug('updateReadiness error:', e);
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
// ── Open Trades Multi-View ──
let openTradesMode = 'real'; // 'real' or 'paper'
let openTrades = [];
let selectedOpenTrade = null;

async function fetchOpenTrades() {
  try {
    const endpoint = openTradesMode === 'real' ? '/api/trades/open' : '/api/paper/trades/open';
    const resp = await fetch(API + endpoint);
    const data = await resp.json();
    openTrades = data || [];
    
    renderOpenTradesTabs();
    
    // Show/hide section based on whether there are open trades
    const section = document.querySelector('.open-trades-section');
    if (section) {
      section.style.display = openTrades.length > 0 ? 'block' : 'none';
    }
    
    // Auto-select first trade if none selected
    if (openTrades.length > 0 && !selectedOpenTrade) {
      switchOpenTrade(openTrades[0]);
    }
  } catch (e) {
    console.error('Error fetching open trades:', e);
  }
}

function switchTradeMode() {
  const select = document.getElementById('openTradesModeSelect');
  if (select) {
    openTradesMode = select.value;
    selectedOpenTrade = null;
    fetchOpenTrades();
  }
}

function switchOpenTrade(trade) {
  selectedOpenTrade = trade;
  renderOpenTradeDetail(trade);
  
  // Update active tab styling
  document.querySelectorAll('.trade-tab').forEach(tab => {
    tab.classList.remove('active');
    if (tab.dataset.tradeId === String(trade.position_id)) {
      tab.classList.add('active');
    }
  });
}

function renderOpenTradesTabs() {
  const container = document.getElementById('openTradesTabs');
  if (!container) return;
  
  if (openTrades.length === 0) {
    container.innerHTML = '<div style="color: var(--gray-2); font-size: 11px;">No open trades</div>';
    return;
  }
  
  container.innerHTML = openTrades.map(trade => {
    const isActive = selectedOpenTrade && selectedOpenTrade.position_id === trade.position_id;
    const posType = trade.side === 'buy' ? 'LONG' : 'SHORT';
    return `
      <button class="trade-tab ${isActive ? 'active' : ''}" data-trade-id="${trade.position_id}" onclick="switchOpenTrade(this.parentNode.parentNode.parentNode.querySelector('[data-trade-obj]'))" title="${trade.pair}">
        <span style="color: ${trade.side === 'buy' ? 'var(--green)' : 'var(--red)'};">${posType}</span>
        ${trade.pair.replace('B-', '').replace('_USDT', '')}
      </button>
    `;
  }).join('');
  
  // Re-bind click handlers properly
  document.querySelectorAll('.trade-tab').forEach((tab, index) => {
    tab.onclick = () => switchOpenTrade(openTrades[index]);
  });
}

function renderOpenTradeDetail(trade) {
  const container = document.getElementById('openTradesDetail');
  if (!container) return;
  
  if (!trade) {
    container.innerHTML = '<div style="color: var(--gray-2); text-align: center; padding: 20px;">Select a trade to view details</div>';
    return;
  }
  
  const posType = trade.side === 'buy' ? 'LONG' : 'SHORT';
  const pnlColor = trade.pnl > 0 ? 'positive' : trade.pnl < 0 ? 'negative' : '';
  const pnlText = trade.pnl !== undefined ? (trade.pnl > 0 ? '+' : '') + parseFloat(trade.pnl).toFixed(4) : '—';
  
  container.innerHTML = `
    <div class="trade-details-grid">
      <div class="trade-detail-item">
        <div class="trade-detail-label">Pair</div>
        <div class="trade-detail-value">${trade.pair}</div>
      </div>
      <div class="trade-detail-item">
        <div class="trade-detail-label">Position</div>
        <div class="trade-detail-value" style="color: ${trade.side === 'buy' ? 'var(--green)' : 'var(--red)'};">${posType}</div>
      </div>
      <div class="trade-detail-item">
        <div class="trade-detail-label">Entry Price</div>
        <div class="trade-detail-value">${parseFloat(trade.entry_price).toFixed(2)}</div>
      </div>
      <div class="trade-detail-item">
        <div class="trade-detail-label">Quantity</div>
        <div class="trade-detail-value">${parseFloat(trade.quantity).toFixed(4)}</div>
      </div>
      <div class="trade-detail-item">
        <div class="trade-detail-label">Leverage</div>
        <div class="trade-detail-value">${trade.leverage}x</div>
      </div>
      <div class="trade-detail-item">
        <div class="trade-detail-label">TP Price</div>
        <div class="trade-detail-value" style="color: var(--green);">${parseFloat(trade.tp_price).toFixed(2)}</div>
      </div>
      <div class="trade-detail-item">
        <div class="trade-detail-label">SL Price</div>
        <div class="trade-detail-value" style="color: var(--red);">${parseFloat(trade.sl_price).toFixed(2)}</div>
      </div>
      <div class="trade-detail-item">
        <div class="trade-detail-label">Position ID</div>
        <div class="trade-detail-value" style="font-size: 11px; word-break: break-all;">${trade.position_id}</div>
      </div>
      <div class="trade-detail-item">
        <div class="trade-detail-label">Opened At</div>
        <div class="trade-detail-value">${trade.opened_at ? trade.opened_at.slice(0, 16).replace('T', ' ') : '—'}</div>
      </div>
      <div class="trade-detail-item">
        <div class="trade-detail-label">Status</div>
        <div class="trade-detail-value">${trade.status || 'open'}</div>
      </div>
    </div>
  `;
}