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

// ── Stats Rendering ──
function renderStats(s) {
  const pnl = s.total_pnl ?? 0;
  const el  = document.getElementById('totalPnl');
  el.textContent = (pnl >= 0 ? '+' : '') + pnl.toFixed(4) + ' USDT';
  el.className   = 'card-value ' + (pnl >= 0 ? 'green' : 'red');
  document.getElementById('winRate').textContent    = (s.win_rate ?? 0) + '%';
  document.getElementById('winsLosses').textContent  = `${s.wins ?? 0} wins / ${s.losses ?? 0} losses`;
  document.getElementById('totalTrades').textContent = `${s.total ?? 0} total trades`;
}

function renderPaperStats(s, trades) {
  const pnl = s.total_pnl ?? 0;
  const el  = document.getElementById('paperTotalPnl');
  el.textContent = (pnl >= 0 ? '+' : '') + pnl.toFixed(4) + ' USDT';
  el.className   = 'card-value ' + (pnl >= 0 ? 'green' : 'red');
  document.getElementById('paperWinRate').textContent    = (s.win_rate ?? 0) + '%';
  document.getElementById('paperWinsLosses').textContent  = `${s.wins ?? 0} wins / ${s.losses ?? 0} losses`;
  document.getElementById('paperTotalTrades').textContent = `${s.total ?? 0} total trades`;

  const open = Array.isArray(trades) ? trades.filter(t => t.status === 'open').length : 0;
  document.getElementById('paperOpenPositions').textContent = open;
}

// ── Trade Tables ──
function renderTrades(trades) {
  const tbody = document.getElementById('tradesBody');
  if (!trades.length) { 
    tbody.innerHTML = '<tr><td colspan="11" class="loading">No trades yet</td></tr>'; 
    return; 
  }
  tbody.innerHTML = trades.map(t => {
    const pnl    = t.pnl != null ? parseFloat(t.pnl).toFixed(4) : '—';
    const pnlCls = t.pnl > 0 ? 'pnl-pos' : t.pnl < 0 ? 'pnl-neg' : '';
    const opened = t.opened_at ? t.opened_at.slice(0, 16).replace('T', ' ') : '—';
    return `<tr>
      <td>${t.pair}</td>
      <td><span class="badge ${t.side}">${t.side.toUpperCase()}</span></td>
      <td>${t.entry_price ?? '—'}</td>
      <td>${t.exit_price ?? '—'}</td>
      <td>${t.tp_price ?? '—'}</td>
      <td>${t.sl_price ?? '—'}</td>
      <td>${t.quantity ?? '—'}</td>
      <td>${t.leverage ?? '—'}x</td>
      <td class="${pnlCls}">${pnl !== '—' ? (t.pnl > 0 ? '+' : '') + pnl : '—'}</td>
      <td><span class="badge ${t.status}">${t.status}</span></td>
      <td>${opened}</td>
    </tr>`;
  }).join('');
}

function renderPaperTrades(trades) {
  const tbody = document.getElementById('paperTradesBody');
  if (!trades.length) { 
    tbody.innerHTML = '<tr><td colspan="11" class="loading">No paper trades yet</td></tr>'; 
    return; 
  }
  tbody.innerHTML = trades.map(t => {
    const pnl    = t.pnl != null ? parseFloat(t.pnl).toFixed(4) : '—';
    const pnlCls = t.pnl > 0 ? 'pnl-pos' : t.pnl < 0 ? 'pnl-neg' : '';
    const opened = t.opened_at ? t.opened_at.slice(0, 16).replace('T', ' ') : '—';
    return `<tr>
      <td>${t.pair}</td>
      <td><span class="badge ${t.side}">${t.side.toUpperCase()}</span></td>
      <td>${t.entry_price ?? '—'}</td>
      <td>${t.exit_price ?? '—'}</td>
      <td>${t.tp_price ?? '—'}</td>
      <td>${t.sl_price ?? '—'}</td>
      <td>${t.quantity ?? '—'}</td>
      <td>${t.leverage ?? '—'}x</td>
      <td class="${pnlCls}">${pnl !== '—' ? (t.pnl > 0 ? '+' : '') + pnl : '—'}</td>
      <td><span class="badge ${t.status}">${t.status}</span></td>
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
function renderPairs() {
  const grid = document.getElementById('coinGrid');
  const query = (document.getElementById('pairSearch')?.value || '').toUpperCase();
  const limit = parseInt(document.getElementById('pairListLimit')?.value || '10', 10);
  
  let filtered = allPairs.filter(p => p.pair.includes(query));
  pairsList = filtered.slice(0, limit).map(p => p.pair);

  if (!filtered.length) {
    grid.innerHTML = '<div class="loading">No pairs match search</div>';
    return;
  }

  const pairs = filtered.slice(0, limit);
  grid.innerHTML = pairs.map(p => {
    const cfg = pairConfigs[p.pair] || { enabled: 0, leverage: 5, quantity: 0.001 };
    pairConfigs[p.pair] = cfg;

    const baseCoin = p.pair.replace('B-', '').replace('_USDT', '');
    const enabled = cfg.enabled === 1;

    return `
      <div class="coin-card ${enabled ? 'enabled' : ''}" data-pair="${p.pair}">
        <div class="coin-toggle ${enabled ? 'on' : ''}" onclick="togglePair('${p.pair}')"></div>
        <div class="coin-info">
          <div class="coin-name">${baseCoin}/USDT</div>
          <div class="coin-params">
            <input type="number" class="coin-input" placeholder="Lev" 
                   value="${cfg.leverage}" min="1" max="20" 
                   onchange="updatePairConfig('${p.pair}', 'leverage', this.value)">
            <input type="number" class="coin-input" placeholder="Qty" 
                   value="${cfg.quantity}" step="0.001" min="0.001"
                   onchange="updatePairConfig('${p.pair}', 'quantity', this.value)">
          </div>
          <div class="readiness">
            <span class="readiness-label">Signal</span>
            <div class="readiness-bar"><span data-readiness="${p.pair}"></span></div>
            <span class="readiness-val" data-readiness-val="${p.pair}">—</span>
          </div>
        </div>
        <button class="coin-fav ${favoritePairs.has(p.pair) ? 'starred' : ''}" onclick="toggleFavorite('${p.pair}')" title="${favoritePairs.has(p.pair) ? 'Remove from favorites' : 'Add to favorites'}">★</button>
      </div>
    `;
  }).join('');

  updateReadiness();
  renderFavorites();
}

function renderFavorites() {
  const panel = document.getElementById('favoritesPanel');
  if (!panel) return;
  
  if (favoritePairs.size === 0) {
    panel.innerHTML = '<div class="loading" style="padding: 10px 0; font-size: 11px;">No favorites yet</div>';
    return;
  }

  const favList = Array.from(favoritePairs)
    .filter(p => allPairs.some(ap => ap.pair === p))
    .slice(0, 15);

  panel.innerHTML = favList.map(pair => {
    const cfg = pairConfigs[pair] || { enabled: 0 };
    const baseCoin = pair.replace('B-', '').replace('_USDT', '');
    const enabled = cfg.enabled === 1;
    
    return `
      <div class="fav-item ${enabled ? 'enabled' : ''}" data-pair="${pair}">
        <div class="fav-toggle ${enabled ? 'on' : ''}" onclick="togglePair('${pair}')"></div>
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

  select.innerHTML = list.map(p => `<option value="${p}">${p.replace('B-', '').replace('_USDT','')}/USDT</option>`).join('');

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
  pairConfigs[pair][field] = field === 'leverage' ? parseInt(value) : parseFloat(value);
}
