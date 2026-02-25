/* ════════════════════════════════════════════════════════════════
   UI RENDERING & INTERACTIONS
   ════════════════════════════════════════════════════════════════ */

// ── Mode Rendering ──
function renderMode() {
  const btn = document.getElementById('modeBtn');
  btn.textContent = `MODE: ${tradingMode}`;
  btn.className = `mode-btn ${tradingMode === 'PAPER' ? 'paper' : 'real'}`;
  btn.disabled = false;
}

// ── Strategy & confidence threshold (from bot_config) ──
async function loadStrategies() {
  const select = document.getElementById('strategySelect');
  const thresholdInput = document.getElementById('confidenceThresholdInput');
  if (!select) return;

  try {
    const response = await fetch((typeof API !== 'undefined' ? API : '') + '/api/strategies');
    if (!response.ok) throw new Error('HTTP ' + response.status);
    const data = await response.json();

    const strategies = (data.strategies && Array.isArray(data.strategies)) ? data.strategies : [];
    const active = data.active || 'enhanced_v2';
    const options = [];
    strategies.forEach(function (s) {
      const name = s.name || '';
      const label = (s.displayName || s.display_name || s.name || name).trim() || name;
      if (name) options.push('<option value="' + name + '">' + label + '</option>');
    });
    select.innerHTML = options.length ? options.join('') : '<option value="enhanced_v2">Enhanced v2</option><option value="bollinger_rsi">Bollinger RSI</option><option value="breakout_vol">Breakout Vol</option>';
    select.value = active;
    select.disabled = false;

    const threshold = data.confidence_threshold != null ? Number(data.confidence_threshold) : 80;
    if (thresholdInput) {
      thresholdInput.value = Math.min(100, Math.max(0, threshold));
    }
  } catch (error) {
    select.innerHTML = '<option value="enhanced_v2">Enhanced v2</option>';
    select.value = 'enhanced_v2';
    select.disabled = false;
    if (thresholdInput) thresholdInput.value = 80;
    console.error('Strategy load failed:', error);
  }
}

async function changeStrategy() {
  const select = document.getElementById('strategySelect');
  const strategyName = select && select.value;
  if (!strategyName) return;
  try {
    const res = await fetch((typeof API !== 'undefined' ? API : '') + '/api/strategies', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ strategy: strategyName })
    });
    if (res.ok) {
      console.log('Strategy set to:', strategyName);
      fetchAll();
    } else loadStrategies();
  } catch (e) {
    console.error('Change strategy:', e);
    loadStrategies();
  }
}

async function changeConfidenceThreshold() {
  const input = document.getElementById('confidenceThresholdInput');
  if (!input) return;
  const v = parseFloat(input.value);
  if (isNaN(v) || v < 0 || v > 100) {
    loadStrategies();
    return;
  }
  try {
    const res = await fetch((typeof API !== 'undefined' ? API : '') + '/api/strategies', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ confidence_threshold: v })
    });
    if (res.ok) {
      console.log('Confidence threshold set to:', v + '%');
    } else loadStrategies();
  } catch (e) {
    console.error('Change confidence threshold:', e);
    loadStrategies();
  }
}

// ── Stats Rendering ──
function renderStats(s) {
  const pnl = s.total_pnl ?? 0;
  const el = document.getElementById('totalPnl');
  el.textContent = (pnl >= 0 ? '+' : '') + pnl.toFixed(4) + ' USDT';
  el.className = 'card-value ' + (pnl >= 0 ? 'green' : 'red');
  document.getElementById('winRate').textContent = (s.win_rate ?? 0) + '%';
  document.getElementById('winsLosses').textContent = `${s.wins ?? 0} wins / ${s.losses ?? 0} losses`;
  document.getElementById('totalTrades').textContent = `${s.total ?? 0} total trades`;
}

function renderPaperStats(s, trades) {
  const pnl = s.total_pnl ?? 0;
  const el = document.getElementById('paperTotalPnl');
  el.textContent = (pnl >= 0 ? '+' : '') + pnl.toFixed(4) + ' USDT';
  el.className = 'card-value ' + (pnl >= 0 ? 'green' : 'red');
  document.getElementById('paperWinRate').textContent = (s.win_rate ?? 0) + '%';
  document.getElementById('paperWinsLosses').textContent = `${s.wins ?? 0} wins / ${s.losses ?? 0} losses`;
  document.getElementById('paperTotalTrades').textContent = `${s.total ?? 0} total trades`;

  const open = Array.isArray(trades) ? trades.filter(t => t.status === 'open').length : 0;
  document.getElementById('paperOpenPositions').textContent = open;
}

// ── Trade Tables ──
function renderTrades(trades) {
  const tbody = document.getElementById('tradesBody');
  if (!trades.length) {
    tbody.innerHTML = '<tr><td colspan="14" class="loading">No trades yet</td></tr>';
    return;
  }
  tbody.innerHTML = trades.map(t => {
    const pnl = t.pnl != null ? parseFloat(t.pnl).toFixed(4) : '—';
    const pnlCls = t.pnl > 0 ? 'pnl-pos' : t.pnl < 0 ? 'pnl-neg' : '';
    const opened = t.opened_at ? t.opened_at.slice(0, 16).replace('T', ' ') : '—';
    const posType = t.side === 'buy' ? 'LONG' : 'SHORT';
    const confidence = t.confidence != null ? parseFloat(t.confidence).toFixed(1) : '—';
    const atr = t.atr != null ? parseFloat(t.atr).toFixed(4) : '—';
    const trailing_stop = t.trailing_stop != null ? parseFloat(t.trailing_stop).toFixed(2) : '—';
    const confClass = confidence > 0 && confidence !== '—' ?
      (parseFloat(confidence) >= 80 ? 'high' : parseFloat(confidence) >= 60 ? 'medium' : 'low') : '';
    return `<tr>
      <td>${t.pair}</td>
      <td><span class="badge ${t.side}">${posType}</span></td>
      <td>${t.entry_price ?? '—'}</td>
      <td>${t.exit_price ?? '—'}</td>
      <td>${t.tp_price ?? '—'}</td>
      <td>${t.sl_price ?? '—'}</td>
      <td>${t.quantity ?? '—'}</td>
      <td>${t.leverage ?? '—'}x</td>
      <td class="${pnlCls}">${pnl !== '—' ? (t.pnl > 0 ? '+' : '') + pnl : '—'}</td>
      <td><span class="badge ${t.status}">${t.status}</span></td>
      <td class="conf-cell ${confClass}">${confidence}%</td>
      <td>${atr}</td>
      <td>${trailing_stop}</td>
      <td>${opened}</td>
    </tr>`;
  }).join('');
}

function renderPaperTrades(trades) {
  const tbody = document.getElementById('paperTradesBody');
  if (!trades.length) {
    tbody.innerHTML = '<tr><td colspan="14" class="loading">No paper trades yet</td></tr>';
    return;
  }
  tbody.innerHTML = trades.map(t => {
    const pnl = t.pnl != null ? parseFloat(t.pnl).toFixed(4) : '—';
    const pnlCls = t.pnl > 0 ? 'pnl-pos' : t.pnl < 0 ? 'pnl-neg' : '';
    const opened = t.opened_at ? t.opened_at.slice(0, 16).replace('T', ' ') : '—';
    const posType = t.side === 'buy' ? 'LONG' : 'SHORT';
    const confidence = t.confidence != null ? parseFloat(t.confidence).toFixed(1) : '—';
    const atr = t.atr != null ? parseFloat(t.atr).toFixed(4) : '—';
    const trailing_stop = t.trailing_stop != null ? parseFloat(t.trailing_stop).toFixed(2) : '—';
    const confClass = confidence > 0 && confidence !== '—' ?
      (parseFloat(confidence) >= 80 ? 'high' : parseFloat(confidence) >= 60 ? 'medium' : 'low') : '';
    return `<tr>
      <td>${t.pair}</td>
      <td><span class="badge ${t.side}">${posType}</span></td>
      <td>${t.entry_price ?? '—'}</td>
      <td>${t.exit_price ?? '—'}</td>
      <td>${t.tp_price ?? '—'}</td>
      <td>${t.sl_price ?? '—'}</td>
      <td>${t.quantity ?? '—'}</td>
      <td>${t.leverage ?? '—'}x</td>
      <td class="${pnlCls}">${pnl !== '—' ? (t.pnl > 0 ? '+' : '') + pnl : '—'}</td>
      <td><span class="badge ${t.status}">${t.status}</span></td>
      <td class="conf-cell ${confClass}">${confidence}%</td>
      <td>${atr}</td>
      <td>${trailing_stop}</td>
      <td>${opened}</td>
    </tr>`;
  }).join('');
}

// ── Logs ──
function renderLogs(logs) {
  const el = document.getElementById('logList');
  if (!logs.length) {
    el.innerHTML = '<div class="loading">No logs yet</div>';
    return;
  }
  el.innerHTML = logs.map(l => `
    <div class="log-entry">
      <span class="log-time">${l.created_at ? l.created_at.slice(11, 19) : ''}</span>
      <span class="log-level ${l.level}">${l.level}</span>
      <span class="log-msg">${l.message}</span>
    </div>
  `).join('');
}

// ── Pair Management ──
// REMOVED: renderPairs() - coinGrid element no longer exists
// This function is stubbed out to prevent errors
function renderPairs() {
  // No-op: Coin grid section was removed from UI
  // Keeping function to avoid breaking other code that calls it
  return;
}

// Wrapper for pagination changes
function onPairsPageChange() {
  // No-op: Coin grid section was removed
  return;
}

function renderFavorites() {
  const panel = document.getElementById('favoritesPanel');
  if (!panel) return;

  // Use pair signals (enabled pairs from auto-enabled / pair_signals API)
  const enabledPairs = (typeof pairSignals !== 'undefined' && Array.isArray(pairSignals))
    ? pairSignals
    : [];

  if (enabledPairs.length === 0) {
    panel.innerHTML = '<div class="loading" style="padding: 10px 0; font-size: 11px;">No auto-enabled pairs yet</div>';
    return;
  }

  panel.innerHTML = enabledPairs.slice(0, 10).map(cfg => {
    const baseCoin = cfg.pair.replace('B-', '').replace('_USDT', '');
    const signalPct = Math.min(100, Math.max(0, cfg.signal_strength || 0));
    const signalInfo = `<div style="font-size: 9px; color: var(--gray-1); margin-top: 2px;">Signal: ${signalPct.toFixed(1)}%</div>`;

    return `
      <div class="fav-item" data-pair="${cfg.pair}" style="padding: 8px; background: var(--gray-3); border: 1px solid var(--gray-2); border-radius: 4px; margin-bottom: 4px;">
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <div>
            <div style="font-weight: 700; color: var(--accent); font-size: 12px;">${baseCoin}</div>
            <div style="font-size: 9px; color: var(--gray-1);">Lev: ${cfg.leverage || 5}x | ₹${cfg.inr_amount || 300}</div>
            ${signalInfo}
          </div>
        </div>
      </div>
    `;
  }).join('');
}

function updateFavoritesDisplay() {
  if (favoritePairs.size > 0) {
    renderFavorites();
  }
}

function updatePairSelect() {
  const select = document.getElementById('pairSelect');
  if (!select || !allPairs.length) return;

  const enabled = Object.keys(pairConfigs).filter(p => pairConfigs[p]?.enabled === 1);
  const list = enabled.length ? enabled : allPairs.map(p => p.pair);

  select.innerHTML = list.map(p => `<option value="${p}">${p.replace('B-', '').replace('_USDT', '')}/USDT</option>`).join('');

  if (!selectedPair) {
    selectedPair = list[0] || '';
  }
  select.value = selectedPair;
  updatePriceChart();
}

function onPairChange() {
  const select = document.getElementById('pairSelect');
  selectedPair = select.value;
  updatePriceChart();
  updatePairPnlChart();
}

function togglePair(pair) {
  const cfg = pairConfigs[pair];
  cfg.enabled = cfg.enabled === 1 ? 0 : 1;

  const card = document.querySelector(`[data-pair="${pair}"]`);
  const toggle = card.querySelector('.coin-toggle');

  if (cfg.enabled) {
    card.classList.add('enabled');
    toggle.classList.add('on');
  } else {
    card.classList.remove('enabled');
    toggle.classList.remove('on');
  }

  updatePairSelect();
}

function toggleFavorite(pair) {
  if (favoritePairs.has(pair)) {
    favoritePairs.delete(pair);
  } else {
    favoritePairs.add(pair);
  }
  localStorage.setItem('favoritePairs', JSON.stringify(Array.from(favoritePairs)));
  renderPairs();
  renderFavorites();
}

function updatePairConfig(pair, field, value) {
  const parsed = field === 'leverage' ? parseInt(value, 10) : parseFloat(value);
  if (!Number.isFinite(parsed)) return;
  pairConfigs[pair][field] = parsed;
}
// ── Active Pairs Rendering ──
// REMOVED: renderActivePairs() - activePairsContainer element no longer exists
// This function is stubbed out to prevent errors
async function renderActivePairs() {
  // No-op: Active pairs section was removed from UI
  // Keeping function to avoid breaking other code that might call it
  return;
}