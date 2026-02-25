/* ════════════════════════════════════════════════════════════════
   PAIR MODE MANAGEMENT - SIMPLIFIED VERSION
   ════════════════════════════════════════════════════════════════ */

// Load current pair mode from API
function loadPairMode() {
    pairMode = 'MULTI';
    selectedSinglePair = null;
    updatePairModeUI();
}

// Populate the pair selector dropdown with all available pairs
function populatePairModeSelector() {
    const selector = document.getElementById('pairSelector');
    if (!selector || !allPairs || allPairs.length === 0) return;

    selector.innerHTML = '<option value="">Select a pair...</option>';

    allPairs.forEach(p => {
        const option = document.createElement('option');
        option.value = p.pair;
        option.textContent = p.pair.replace('B-', '').replace('_USDT', '') + '/USDT';
        if (p.pair === selectedSinglePair) {
            option.selected = true;
        }
        selector.appendChild(option);
    });
}

function setPairMode(mode) {
    pairMode = 'MULTI';
    updatePairModeUI();
}

function onPairSelect() {
    const selector = document.getElementById('pairSelector');
    if (selector && selector.value) selectedSinglePair = selector.value;
    updatePairModeUI();
}

// Update pair mode UI (MULTI only: all enabled pairs, max 3 open)
function updatePairModeUI() {
    const singleBtn = document.getElementById('pairModeSingle');
    const multiBtn = document.getElementById('pairModeMulti');
    const selectorContainer = document.getElementById('pairSelectorContainer');
    const statusDiv = document.getElementById('pairModeStatus');
    if (multiBtn) {
        multiBtn.style.background = 'var(--accent)';
        multiBtn.style.color = '#000';
        multiBtn.style.fontWeight = '700';
        multiBtn.style.borderColor = 'var(--accent)';
    }
    if (singleBtn) {
        singleBtn.style.background = 'var(--gray-3)';
        singleBtn.style.color = 'var(--text)';
        singleBtn.style.fontWeight = '400';
        singleBtn.style.borderColor = 'var(--gray-2)';
    }
    if (selectorContainer) selectorContainer.style.display = 'none';
    if (statusDiv) statusDiv.textContent = 'Trading ALL enabled pairs (max 3 open)';
}

// Load and render pair signals (for horizontal Trading Pairs section)
// Uses recursive setTimeout to wait 7 seconds after each response
async function loadPairSignals() {
    try {
        const startTime = Date.now();
        const res = await fetch(`${API}/api/pair_signals`);
        const fetchTime = ((Date.now() - startTime) / 1000).toFixed(1);
        
        if (!res.ok) {
            console.warn('Pair signals request failed, retrying in 5 seconds...');
            setTimeout(loadPairSignals, 5000);
            return;
        }

        const data = await res.json();
        // API returns { pairs, updated_at }; support legacy array format
        pairSignals = Array.isArray(data) ? data : (data.pairs || []);
        pairSignalsUpdatedAt = data.updated_at || null;

        populatePairModeSelector();

        // Render the horizontal pair cards
        renderPairList();

        // Update favorites panel with latest signal data
        if (typeof renderFavorites === 'function') {
            renderFavorites();
        }

        if (typeof refreshCandleInfo === 'function') {
            refreshCandleInfo();
        }
        
        console.debug(`Pair signals loaded in ${fetchTime}s, scheduling next in 5s`);
    } catch (err) {
        console.error('Failed to load pair signals:', err);
    } finally {
        // Refresh every 5s so confidence and execution status stay current
        setTimeout(loadPairSignals, 5000);
    }
}

// Fetch current (live) confidence for all enabled pairs and re-render cards
async function loadCurrentConfidence() {
    try {
        const res = await fetch(`${API}/api/current_confidence`);
        if (!res.ok) return;
        const data = await res.json();
        const list = data.pairs || [];
        currentConfidenceByPair = {};
        list.forEach(function (item) {
            if (item.pair != null && item.current_confidence != null) currentConfidenceByPair[item.pair] = item.current_confidence;
        });
        renderPairList();
    } catch (err) {
        console.debug('Current confidence fetch failed:', err);
    }
    setTimeout(loadCurrentConfidence, 30000);
}

// Next 5m candle close countdown (UTC; trades run at close)
function getNext5mCloseMs() {
    const nowSec = Date.now() / 1000;
    const nextCloseSec = Math.ceil(nowSec / 300) * 300;
    return Math.max(0, Math.floor((nextCloseSec - nowSec) * 1000));
}
function updateNextCloseCountdown() {
    const el = document.getElementById('nextCloseCountdown');
    if (!el) return;
    const ms = getNext5mCloseMs();
    const totalSec = Math.floor(ms / 1000);
    const m = Math.floor(totalSec / 60);
    const s = totalSec % 60;
    el.textContent = 'Next 5m close: ' + (m > 0 ? m + 'm ' : '') + s + 's';
}
if (typeof setInterval !== 'undefined') {
    setInterval(updateNextCloseCountdown, 1000);
}

async function executeTradeForPair(pair, buttonEl) {
    if (!pair) return;
    const origText = buttonEl ? buttonEl.textContent : '';
    if (buttonEl) {
        buttonEl.disabled = true;
        buttonEl.textContent = '…';
    }
    try {
        const res = await fetch(`${API}/api/paper/execute_trade`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ pair: pair }),
        });
        let data = {};
        try {
            data = await res.json();
        } catch (_) {
            data = { error: res.statusText || 'Server error (' + res.status + ')' };
        }
        if (res.ok && data.success) {
            if (typeof showToast === 'function') showToast(data.message || 'Trade placed', 'success');
            if (typeof fetchAll === 'function') fetchAll();
        } else {
            const msg = data.error || data.message || (res.status === 400 ? 'Bad request (check mode & pair)' : 'Execute failed');
            if (typeof showToast === 'function') showToast(msg, 'error');
            else if (typeof alert === 'function') alert(msg);
            if (buttonEl) {
                buttonEl.textContent = 'Failed';
                buttonEl.style.color = 'var(--red, #f55)';
                setTimeout(function () {
                    buttonEl.textContent = origText || 'Execute (paper)';
                    buttonEl.style.color = '';
                }, 3000);
            }
        }
    } catch (e) {
        const msg = 'Request failed: ' + (e.message || String(e));
        if (typeof showToast === 'function') showToast(msg, 'error');
        else if (typeof alert === 'function') alert(msg);
        if (buttonEl) buttonEl.textContent = 'Error';
    } finally {
        if (buttonEl) buttonEl.disabled = false;
        if (buttonEl && buttonEl.textContent !== 'Failed' && buttonEl.textContent !== 'Error') {
            buttonEl.textContent = origText || 'Execute (paper)';
        }
    }
}

function formatPairSignalsUpdatedAt(iso) {
    if (!iso) return '—';
    try {
        const d = new Date(iso);
        if (isNaN(d.getTime())) return iso;
        return d.toLocaleTimeString();
    } catch (_) { return iso; }
}

// Render horizontal pair list — ONLY currently enabled pairs (from pair_signals API)
function renderPairList() {
    updateNextCloseCountdown();
    const updatedEl = document.getElementById('pairSignalsLastUpdated');
    if (updatedEl && typeof pairSignalsUpdatedAt !== 'undefined')
        updatedEl.textContent = 'Updated: ' + formatPairSignalsUpdatedAt(pairSignalsUpdatedAt);
    const container = document.getElementById('pairSignalsContainer');
    if (!container) return;

    if (!pairSignals || pairSignals.length === 0) {
        container.innerHTML = '<div style="color: var(--gray-2); font-size: 12px; padding: 10px;">No enabled pairs</div>';
        return;
    }

    const pairsToShow = pairSignals.slice(0, 10);
    container.innerHTML = '';

    pairsToShow.forEach((p, idx) => {
        const card = document.createElement('div');
        card.style.cssText = `
      padding: 12px 16px;
      background: var(--gray-3);
      border: 1px solid var(--gray-2);
      border-radius: 6px;
      min-width: 140px;
      cursor: pointer;
      transition: all 0.2s;
    `;

        const baseCoin = p.pair.replace('B-', '').replace('_USDT', '');
        const lastPct = p.last_confidence != null ? Number(p.last_confidence) : (p.signal_strength != null ? Number(p.signal_strength) : null);
        const lastStr = lastPct != null ? lastPct.toFixed(1) : '—';
        const currentPct = (currentConfidenceByPair && currentConfidenceByPair[p.pair] != null) ? Number(currentConfidenceByPair[p.pair]) : null;
        const currentStr = currentPct != null ? currentPct.toFixed(1) : '—';
        const titleLine = `<div style="font-size: 13px; font-weight: 700; color: var(--accent); margin-bottom: 8px;">${baseCoin}</div>`;
        card.innerHTML = titleLine + `
      <div style="font-size: 11px; color: var(--gray-1); margin-bottom: 2px;">Last cycle: ${lastStr}%</div>
      <div style="font-size: 11px; color: var(--gray-1); margin-bottom: 6px;">Current: ${currentStr}%</div>
      <div style="height: 4px; background: var(--gray-2); border-radius: 2px; overflow: hidden;">
        <div style="height: 100%; width: ${Math.min(100, Math.max(0, currentPct != null ? currentPct : (lastPct != null ? lastPct : 0))}%; background: var(--accent); transition: width 0.3s;"></div>
      </div>
      <button type="button" class="pair-execute-btn" style="margin-top: 8px; padding: 4px 8px; font-size: 10px; background: var(--accent); color: var(--gray-3); border: none; border-radius: 4px; cursor: pointer; width: 100%;">Execute (paper)</button>
    `;

        const execBtn = card.querySelector('button.pair-execute-btn');
        if (execBtn) {
            execBtn.addEventListener('click', function (ev) {
                ev.stopPropagation();
                ev.preventDefault();
                executeTradeForPair(p.pair, execBtn);
            });
        }

        card.onmouseenter = () => {
            card.style.borderColor = 'var(--accent)';
            card.style.transform = 'translateY(-2px)';
        };
        card.onmouseleave = () => {
            card.style.borderColor = 'var(--gray-2)';
            card.style.transform = 'translateY(0)';
        };

        container.appendChild(card);
    });

    // Show more / Show less — only for enabled pairs (never show disabled pairs)
    const showAllBtn = document.createElement('button');
    let expanded = false;
    const extraCount = pairSignals.length > 10 ? pairSignals.length - 10 : 0;
    showAllBtn.textContent = extraCount > 0 ? `+${extraCount} more` : '';
    showAllBtn.style.cssText = `
      padding: 12px 16px;
      background: var(--gray-3);
      color: var(--accent);
      border: 1px dashed var(--gray-2);
      border-radius: 6px;
      font-family: 'Space Mono';
      font-size: 11px;
      cursor: pointer;
      transition: all 0.2s;
    `;

    showAllBtn.onclick = () => {
        expanded = !expanded;

        if (!expanded) {
            while (container.firstChild) container.removeChild(container.firstChild);
            renderPairList();
            return;
        }

        // Expand to show all enabled pairs only (pairSignals = current enabled from API)
        while (container.firstChild) container.removeChild(container.firstChild);

        pairSignals.forEach((p, idx) => {
            const card = document.createElement('div');
            card.style.cssText = `
              padding: 12px 16px;
              background: var(--gray-3);
              border: 1px solid var(--gray-2);
              border-radius: 6px;
              min-width: 140px;
              cursor: pointer;
              transition: all 0.2s;
            `;
            const baseCoin = p.pair.replace('B-', '').replace('_USDT', '');
            const lastPct = p.last_confidence != null ? Number(p.last_confidence) : (p.signal_strength != null ? Number(p.signal_strength) : null);
            const lastStr = lastPct != null ? lastPct.toFixed(1) : '—';
            const currentPct = (currentConfidenceByPair && currentConfidenceByPair[p.pair] != null) ? Number(currentConfidenceByPair[p.pair]) : null;
            const currentStr = currentPct != null ? currentPct.toFixed(1) : '—';
            const barPct = Math.min(100, Math.max(0, currentPct != null ? currentPct : (lastPct != null ? lastPct : 0)));
            card.innerHTML = `
              <div style="font-size: 13px; font-weight: 700; color: var(--accent); margin-bottom: 8px;">${baseCoin}</div>
              <div style="font-size: 11px; color: var(--gray-1); margin-bottom: 2px;">Last cycle: ${lastStr}%</div>
              <div style="font-size: 11px; color: var(--gray-1); margin-bottom: 6px;">Current: ${currentStr}%</div>
              <div style="height: 4px; background: var(--gray-2); border-radius: 2px; overflow: hidden;">
                <div style="height: 100%; width: ${barPct}%; background: var(--accent); transition: width 0.3s;"></div>
              </div>
              <button type="button" class="pair-execute-btn" style="margin-top: 8px; padding: 4px 8px; font-size: 10px; background: var(--accent); color: var(--gray-3); border: none; border-radius: 4px; cursor: pointer; width: 100%;">Execute (paper)</button>
            `;
            const execBtnExp = card.querySelector('button.pair-execute-btn');
            if (execBtnExp) execBtnExp.addEventListener('click', function (ev) { ev.stopPropagation(); ev.preventDefault(); executeTradeForPair(p.pair, execBtnExp); });
            card.onmouseenter = () => { card.style.borderColor = 'var(--accent)'; card.style.transform = 'translateY(-2px)'; };
            card.onmouseleave = () => { card.style.borderColor = 'var(--gray-2)'; card.style.transform = 'translateY(0)'; };
            container.appendChild(card);
        });

        showAllBtn.textContent = 'Show less';
        container.appendChild(showAllBtn);
    };

    if (extraCount > 0) {
        container.appendChild(showAllBtn);
    }
}

// Recent bot logs modal (file tail from /api/bot_logs, sorted by time; optional execution-only filter)
async function fetchBotLogs(filterExecution) {
    const q = new URLSearchParams({ n: 300 });
    if (filterExecution) q.set('filter', 'execution');
    const res = await fetch(`${API}/api/bot_logs?${q}`);
    return res.json();
}
async function showBotLogsModal() {
    const modal = document.getElementById('botLogsModal');
    const content = document.getElementById('botLogsModalContent');
    const hint = document.getElementById('botLogsModalHint');
    const filterCb = document.getElementById('botLogsFilterExecution');
    if (!modal || !content) return;
    content.textContent = 'Loading…';
    if (hint) hint.textContent = '';
    modal.style.display = 'flex';
    modal.style.alignItems = 'center';
    modal.style.justifyContent = 'center';
    const filterExecution = !!(filterCb && filterCb.checked);
    try {
        const data = await fetchBotLogs(filterExecution);
        if (data.error) {
            content.textContent = 'Error: ' + data.error;
            return;
        }
        const lines = data.lines || [];
        content.textContent = lines.length ? lines.join('\n') : '(no matching lines)';
        // API returns newest first (desc); keep scroll at top so recent logs are visible
        content.scrollTop = 0;
        if (hint) {
            if (filterExecution && lines.length === 0)
                hint.textContent = 'No execution lines found. Bot may not be receiving closed candles from the exchange (check WebSocket). Look for "Closed candle" in full logs.';
            else if (filterExecution)
                hint.textContent = 'Showing only: Closed candle, Signal:, PAPER entry, Signal rejected, Skip execution, errors. Uncheck to see all logs.';
            else
                hint.textContent = 'Timestamps in IST. Newest first. Last 2 days. Use the checkbox to show only execution-related lines.';
        }
    } catch (e) {
        content.textContent = 'Failed to load logs: ' + e.message;
    }
}
function closeBotLogsModal() {
    const modal = document.getElementById('botLogsModal');
    if (modal) modal.style.display = 'none';
}
document.addEventListener('DOMContentLoaded', function () {
    const link = document.getElementById('showBotLogsLink');
    if (link) link.addEventListener('click', function (e) { e.preventDefault(); showBotLogsModal(); });
    const closeBtn = document.getElementById('botLogsModalClose');
    if (closeBtn) closeBtn.addEventListener('click', closeBotLogsModal);
    const modal = document.getElementById('botLogsModal');
    if (modal) modal.addEventListener('click', function (e) { if (e.target === modal) closeBotLogsModal(); });
    const filterCb = document.getElementById('botLogsFilterExecution');
    if (filterCb) filterCb.addEventListener('change', function () { if (document.getElementById('botLogsModal').style.display === 'flex') showBotLogsModal(); });
});

