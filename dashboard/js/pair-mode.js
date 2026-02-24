/* ════════════════════════════════════════════════════════════════
   PAIR MODE MANAGEMENT - SIMPLIFIED VERSION
   ════════════════════════════════════════════════════════════════ */

// Load current pair mode from API
async function loadPairMode() {
    try {
        const res = await fetch(`${API}/api/pair_mode`);
        const data = await res.json();

        pairMode = data.pair_mode || 'MULTI';
        selectedSinglePair = data.selected_pair;

        // Update UI
        updatePairModeUI();

        // Populate pair selector with available pairs
        populatePairModeSelector();
    } catch (err) {
        console.error('Failed to load pair mode:', err);
    }
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

// Set pair mode (SINGLE or MULTI)
async function setPairMode(mode) {
    try {
        // If switching to SINGLE and no pair selected, auto-select first pair
        if (mode === 'SINGLE' && !selectedSinglePair && allPairs && allPairs.length > 0) {
            selectedSinglePair = allPairs[0].pair;
            const selector = document.getElementById('pairSelector');
            if (selector) {
                selector.value = selectedSinglePair;
            }
        }

        const payload = {
            pair_mode: mode,
            selected_pair: mode === 'SINGLE' ? selectedSinglePair : null
        };

        const res = await fetch(`${API}/api/pair_mode`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        if (!res.ok) {
            const error = await res.json();
            showToast(error.error || 'Failed to set pair mode', 'error');
            return;
        }

        pairMode = mode;
        updatePairModeUI();
        showToast(`Switched to ${mode} mode`, 'success');
    } catch (err) {
        console.error('Failed to set pair mode:', err);
        showToast('Failed to set pair mode', 'error');
    }
}

// Handle pair selection (for SINGLE mode)
async function onPairSelect() {
    const selector = document.getElementById('pairSelector');
    if (!selector) return;

    selectedSinglePair = selector.value;

    if (!selectedSinglePair) return;

    try {
        const res = await fetch(`${API}/api/pair_mode`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                pair_mode: 'SINGLE',
                selected_pair: selectedSinglePair
            })
        });

        if (!res.ok) {
            const error = await res.json();
            showToast(error.error || 'Failed to select pair', 'error');
            return;
        }

        pairMode = 'SINGLE';
        updatePairModeUI();
        showToast(`Now trading ${selectedSinglePair}`, 'success');
    } catch (err) {
        console.error('Failed to select pair:', err);
        showToast('Failed to select pair', 'error');
    }
}

// Update pair mode UI elements
function updatePairModeUI() {
    const singleBtn = document.getElementById('pairModeSingle');
    const multiBtn = document.getElementById('pairModeMulti');
    const selectorContainer = document.getElementById('pairSelectorContainer');
    const statusDiv = document.getElementById('pairModeStatus');

    if (!singleBtn || !multiBtn || !selectorContainer || !statusDiv) return;

    // Update button states
    if (pairMode === 'SINGLE') {
        singleBtn.style.background = 'var(--accent)';
        singleBtn.style.color = '#000';
        singleBtn.style.fontWeight = '700';
        singleBtn.style.borderColor = 'var(--accent)';

        multiBtn.style.background = 'var(--gray-3)';
        multiBtn.style.color = 'var(--text)';
        multiBtn.style.fontWeight = '400';
        multiBtn.style.borderColor = 'var(--gray-2)';

        selectorContainer.style.display = 'block';
        statusDiv.textContent = selectedSinglePair ? `Trading ${selectedSinglePair}` : 'Select a pair';
    } else {
        multiBtn.style.background = 'var(--accent)';
        multiBtn.style.color = '#000';
        multiBtn.style.fontWeight = '700';
        multiBtn.style.borderColor = 'var(--accent)';

        singleBtn.style.background = 'var(--gray-3)';
        singleBtn.style.color = 'var(--text)';
        singleBtn.style.fontWeight = '400';
        singleBtn.style.borderColor = 'var(--gray-2)';

        selectorContainer.style.display = 'none';
        statusDiv.textContent = 'Trading ALL enabled pairs';
    }
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

        // Populate pair selector for SINGLE mode
        populatePairModeSelector();

        // Render the horizontal pair cards
        renderPairList();
        
        // Update favorites panel with latest signal data
        if (typeof renderFavorites === 'function') {
            renderFavorites();
        }

        if (typeof refreshBatchUI === 'function') {
            refreshBatchUI();
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

    pairsToShow.forEach(p => {
        const hasError = !!(p.last_error && String(p.last_error).trim());
        const card = document.createElement('div');
        card.style.cssText = `
      padding: 12px 16px;
      background: ${hasError ? 'rgba(255, 80, 80, 0.12)' : 'var(--gray-3)'};
      border: 1px solid ${hasError ? 'rgba(255, 80, 80, 0.5)' : 'var(--gray-2)'};
      border-radius: 6px;
      min-width: 120px;
      cursor: pointer;
      transition: all 0.2s;
    `;

        const baseCoin = p.pair.replace('B-', '').replace('_USDT', '');
        const signalPct = Math.min(100, Math.max(0, p.signal_strength || 0));
        const byStrategy = p.enabled_by_strategy;
        const atConf = p.enabled_at_confidence != null ? Number(p.enabled_at_confidence).toFixed(1) : null;
        const strategyDisplay = byStrategy ? byStrategy.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()) : '';
        const enabledByLine = (byStrategy && atConf) ? `<div style="font-size: 10px; color: var(--gray-2); margin-top: 6px;">Enabled by ${strategyDisplay} when confidence was ${atConf}%</div>` : '';
        const errText = (p.last_error || '').replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
        const errorIcon = hasError ? `<span class="pair-error-icon" title="${errText}" style="cursor: help; margin-left: 4px; color: rgba(255,80,80,0.9); font-size: 12px;">ⓘ</span>` : '';
        const titleLine = `<div style="font-size: 13px; font-weight: 700; color: var(--accent); margin-bottom: 6px;">${baseCoin}${errorIcon}</div>`;

        card.innerHTML = titleLine + `
      <div style="font-size: 11px; color: var(--gray-1); margin-bottom: 4px;">Confidence: ${signalPct}%</div>
      <div style="height: 4px; background: var(--gray-2); border-radius: 2px; overflow: hidden;">
        <div style="height: 100%; width: ${signalPct}%; background: var(--accent); transition: width 0.3s;"></div>
      </div>${enabledByLine}
    `;

        card.onmouseenter = () => {
            card.style.borderColor = hasError ? 'rgba(255, 80, 80, 0.8)' : 'var(--accent)';
            card.style.transform = 'translateY(-2px)';
        };
        card.onmouseleave = () => {
            card.style.borderColor = hasError ? 'rgba(255, 80, 80, 0.5)' : 'var(--gray-2)';
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

        pairSignals.forEach(p => {
            const hasError = !!(p.last_error && String(p.last_error).trim());
            const card = document.createElement('div');
            card.style.cssText = `
              padding: 12px 16px;
              background: ${hasError ? 'rgba(255, 80, 80, 0.12)' : 'var(--gray-3)'};
              border: 1px solid ${hasError ? 'rgba(255, 80, 80, 0.5)' : 'var(--gray-2)'};
              border-radius: 6px;
              min-width: 120px;
              cursor: pointer;
              transition: all 0.2s;
            `;
            const baseCoin = p.pair.replace('B-', '').replace('_USDT', '');
            const signalPct = Math.min(100, Math.max(0, p.signal_strength || 0));
            const byStrategy = p.enabled_by_strategy;
            const atConf = p.enabled_at_confidence != null ? Number(p.enabled_at_confidence).toFixed(1) : null;
            const strategyDisplay = byStrategy ? byStrategy.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()) : '';
            const enabledByLine = (byStrategy && atConf) ? `<div style="font-size: 10px; color: var(--gray-2); margin-top: 6px;">Enabled by ${strategyDisplay} when confidence was ${atConf}%</div>` : '';
            const errText = (p.last_error || '').replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
            const errorIcon = hasError ? `<span title="${errText}" style="cursor: help; margin-left: 4px; color: rgba(255,80,80,0.9); font-size: 12px;">ⓘ</span>` : '';
            card.innerHTML = `
              <div style="font-size: 13px; font-weight: 700; color: var(--accent); margin-bottom: 6px;">${baseCoin}${errorIcon}</div>
              <div style="font-size: 11px; color: var(--gray-1); margin-bottom: 4px;">Confidence: ${signalPct.toFixed(1)}%</div>
              <div style="height: 4px; background: var(--gray-2); border-radius: 2px; overflow: hidden;">
                <div style="height: 100%; width: ${signalPct}%; background: var(--accent); transition: width 0.3s;"></div>
              </div>${enabledByLine}
            `;
            card.onmouseenter = () => { card.style.borderColor = hasError ? 'rgba(255, 80, 80, 0.8)' : 'var(--accent)'; card.style.transform = 'translateY(-2px)'; };
            card.onmouseleave = () => { card.style.borderColor = hasError ? 'rgba(255, 80, 80, 0.5)' : 'var(--gray-2)'; card.style.transform = 'translateY(0)'; };
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

