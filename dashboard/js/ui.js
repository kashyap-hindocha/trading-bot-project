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

// ── Strategy Management ──
async function loadStrategies() {
  const select = document.getElementById('strategySelect');

  try {
    const response = await fetch('/api/strategies');

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const data = await response.json();

    if (data.strategies && Array.isArray(data.strategies) && data.strategies.length > 0) {
      select.innerHTML = data.strategies.map(s =>
        `<option value="${s.name}">${s.displayName || s.name}</option>`
      ).join('');

      if (data.active) {
        select.value = data.active;
      }
    } else {
      select.innerHTML = '<option value="">No strategies</option>';
    }
    select.disabled = false;
  } catch (error) {
    // Fallback: show status message
    select.innerHTML = '<option value="">Strategies unavailable</option>';
    select.disabled = true;
    console.error('Strategy load failed:', error);
  }
}

async function changeStrategy() {
  const select = document.getElementById('strategySelect');
  const strategyName = select.value;

  if (!strategyName) return;

  try {
    const response = await fetch('/api/strategies', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ strategy: strategyName })
    });

    if (response.ok) {
      console.log(`Strategy changed to: ${strategyName}`);
      // Optionally reload data to reflect new strategy
      loadData();
    } else {
      console.error('Failed to change strategy');
      // Reset to previous value
      loadStrategies();
    }
  } catch (error) {
    console.error('Error changing strategy:', error);
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

  if (favoritePairs.size === 0) {
    panel.innerHTML = '<div class="loading" style="padding: 10px 0; font-size: 11px;">Add favorites to watch</div>';
    return;
  }

  const favList = Array.from(favoritePairs)
    .filter(p => allPairs.some(ap => ap.pair === p))
    .slice(0, 15);

  panel.innerHTML = favList.map(pair => {
    const baseCoin = pair.replace('B-', '').replace('_USDT', '');

    return `
      <div class="fav-item" data-pair="${pair}">
        <div class="fav-name">${baseCoin}</div>
        <button class="fav-remove" onclick="toggleFavorite('${pair}')" title="Remove">✕</button>
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
async function renderActivePairs() {
  try {
    const response = await fetch(API + '/api/pairs/active');
    if (!response.ok) return;

    const data = await response.json();
    const container = document.getElementById('activePairsContainer');

    if (!data.active_pairs || data.active_pairs.length === 0) {
      container.innerHTML = '<div style="color: var(--gray-2); font-size: 12px; padding: 10px;">No active trades</div>';
      return;
    }

    container.innerHTML = data.active_pairs.map(pairData => {
      const confidence = pairData.avg_confidence || 0;
      const confClass = confidence >= 90 ? 'high' : confidence >= 70 ? 'medium' : 'low';
      const baseCoin = pairData.pair.replace('B-', '').replace('_USDT', '');

      return `
        <div class="active-pair-badge">
          <div class="active-pair-name">${baseCoin}</div>
          <div class="active-pair-info">
            <div class="active-pair-trades">
              📈 ${pairData.open_positions} trade${pairData.open_positions !== 1 ? 's' : ''}
            </div>
            <div class="active-pair-confidence ${confClass}">
              ✓ ${confidence.toFixed(1)}%
            </div>
          </div>
        </div>
      `;
    }).join('');
  } catch (e) {
    console.error('Error fetching active pairs:', e);
  }
}