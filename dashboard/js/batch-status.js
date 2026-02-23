/* ════════════════════════════════════════════════════════════════
   BATCH CONFIDENCE CHECKER UI
   Live batch display during processing + countdown during wait
   ════════════════════════════════════════════════════════════════ */

let batchCountdownInterval = null;
let batchPollHandle = null;
const BATCH_POLL_MS = 2000;   // Poll every 2s during processing for live updates
const BATCH_IDLE_POLL_MS = 30000;  // Poll every 30s when idle

async function loadBatchStatus() {
  try {
    const res = await fetch(API + '/api/batch/status');
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || 'Failed to load batch status');
    }
    renderBatchStatus(data);
    loadConfidenceHistory(confHistoryCurrentPage);

    // Poll more frequently during processing for live batch updates
    if (batchPollHandle) clearTimeout(batchPollHandle);
    if (data.is_processing) {
      batchPollHandle = setTimeout(loadBatchStatus, BATCH_POLL_MS);
    } else {
      batchPollHandle = setTimeout(loadBatchStatus, BATCH_IDLE_POLL_MS);
    }
  } catch (e) {
    console.error('Batch status load failed:', e);
    const liveEl = document.getElementById('batchLiveDisplay');
    const idleEl = document.getElementById('batchIdleDisplay');
    if (liveEl) liveEl.style.display = 'none';
    if (idleEl) idleEl.style.display = 'flex';
    const txt = document.getElementById('batchIdleText');
    const countdownVal = document.getElementById('batchCountdownVal');
    if (txt) txt.textContent = 'Offline';
    if (countdownVal) countdownVal.textContent = '—';
    if (batchPollHandle) clearTimeout(batchPollHandle);
    batchPollHandle = setTimeout(loadBatchStatus, BATCH_IDLE_POLL_MS);
  }
}

function formatPairLabel(pair) {
  if (!pair || typeof pair !== 'string') return '—';
  return pair.replace('B-', '').replace('_USDT', '') + '/USDT';
}

function renderBatchStatus(data) {
  const liveDisplay = document.getElementById('batchLiveDisplay');
  const idleDisplay = document.getElementById('batchIdleDisplay');
  const progressText = document.getElementById('batchProgressText');
  const pairsContainer = document.getElementById('batchPairsWithConfidence');
  const countdownVal = document.getElementById('batchCountdownVal');
  const idleDot = document.getElementById('batchIdleDot');
  const idleText = document.getElementById('batchIdleText');

  if (!liveDisplay || !idleDisplay) return;

  const isProcessing = data.is_processing || false;
  const currentBatch = data.current_batch || [];
  const currentBatchResults = data.current_batch_results || [];
  const batchIndex = data.batch_index || 0;
  const totalBatches = data.total_batches || 0;
  const totalPairs = data.total_pairs || 0;
  const secondsUntil = data.seconds_until_next ?? data.seconds_until_next;
  const lastError = data.last_error;

  if (lastError) {
    liveDisplay.style.display = 'none';
    idleDisplay.style.display = 'flex';
    if (idleDot) idleDot.style.background = 'var(--red)';
    if (idleText) idleText.textContent = 'Error';
    if (countdownVal) countdownVal.textContent = '—';
    return;
  }

  if (isProcessing) {
    liveDisplay.style.display = 'block';
    idleDisplay.style.display = 'none';

    var currentStrategyKey = data.current_strategy || data.batch_strategy_mode || '';
    var strategyDisplayName = currentStrategyKey ? (currentStrategyKey === 'auto' ? 'Auto (cycling all 3)' : currentStrategyKey.replace(/_/g, ' ').replace(/\b\w/g, function(c) { return c.toUpperCase(); })) : '—';
    var strategyNameEl = document.getElementById('batchCurrentStrategyName');
    var strategyRowEl = document.getElementById('batchCurrentStrategyRow');
    if (strategyNameEl) strategyNameEl.textContent = strategyDisplayName;
    if (strategyRowEl) strategyRowEl.style.display = currentStrategyKey ? 'block' : 'none';

    if (progressText) {
      progressText.textContent = totalBatches > 0
        ? (strategyDisplayName !== '—' ? strategyDisplayName + ' · ' : '') + 'Batch ' + batchIndex + ' of ' + totalBatches + ' (' + totalPairs + ' pairs)'
        : 'Processing...';
    }

    // Show current 5 pairs with their confidence level (and strategy name if present)
    if (pairsContainer) {
      if (currentBatchResults.length > 0) {
        pairsContainer.innerHTML = currentBatchResults.map(function (r) {
          const pair = r.pair || '';
          const confidence = r.readiness != null ? Number(r.readiness).toFixed(1) : '—';
          const label = formatPairLabel(pair);
          const strat = r.strategy_name || r.strategy_key || '';
          const isHigh = confidence !== '—' && parseFloat(confidence) >= 75;
          const confClass = isHigh ? 'active-pair-confidence high' : (parseFloat(confidence) >= 50 ? 'active-pair-confidence medium' : 'active-pair-confidence low');
          const stratPart = strat ? ' · ' + strat : '';
          return '<span class="batch-pair-chip ' + confClass + '" style="padding: 6px 10px; border-radius: 6px; background: var(--gray-2); font-size: 12px; font-weight: 600;">' + label + ': ' + confidence + '%' + stratPart + '</span>';
        }).join('');
      } else {
        pairsContainer.innerHTML = currentBatch.length > 0
          ? currentBatch.map(function (p) { return '<span class="batch-pair-chip" style="padding: 6px 10px; border-radius: 6px; background: var(--gray-2); font-size: 12px;">' + formatPairLabel(p) + ': …</span>'; }).join('')
          : '<span style="color: var(--gray-1); font-size: 12px;">Calculating confidence…</span>';
      }
    }
  } else {
    liveDisplay.style.display = 'none';
    idleDisplay.style.display = 'flex';
    var strategyRowElIdle = document.getElementById('batchCurrentStrategyRow');
    if (strategyRowElIdle) strategyRowElIdle.style.display = 'none';

    if (idleDot) {
      idleDot.style.background = 'var(--green)';
      idleDot.classList.remove('pulse');
    }
    if (idleText) idleText.textContent = 'Idle';
    const sec = Math.max(0, typeof secondsUntil === 'number' ? secondsUntil : (data.seconds_until_next ?? 300));
    if (countdownVal) countdownVal.textContent = formatCountdown(sec);
  }

  if (!batchCountdownInterval) {
    batchCountdownInterval = setInterval(tickBatchCountdown, 1000);
  }
}

function formatCountdown(seconds) {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

function tickBatchCountdown() {
  const liveDisplay = document.getElementById('batchLiveDisplay');
  if (liveDisplay && liveDisplay.style.display !== 'none') return;

  const el = document.getElementById('batchCountdownVal');
  if (!el) return;
  const txt = el.textContent;
  const match = txt.match(/^(\d+):(\d+)$/);
  if (!match) return;
  let m = parseInt(match[1], 10);
  let s = parseInt(match[2], 10);
  if (s > 0) {
    s--;
  } else if (m > 0) {
    m--;
    s = 59;
  } else {
    loadBatchStatus();
    return;
  }
  el.textContent = formatCountdown(m * 60 + s);
}

async function refreshBatchUI() {
  await loadBatchStatus();
  loadConfidenceHistory(confHistoryCurrentPage);
}

// ── Confidence history (last checked pairs, 15 per page) ──
let confHistoryCurrentPage = 1;
const CONF_HISTORY_PER_PAGE = 15;

async function loadConfidenceHistory(page) {
  try {
    const res = await fetch(API + '/api/batch/confidence_history?page=' + page + '&per_page=' + CONF_HISTORY_PER_PAGE);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed');
    renderConfidenceHistory(data);
  } catch (e) {
    console.debug('Confidence history load failed:', e);
    const tbody = document.getElementById('confidenceHistoryBody');
    if (tbody) tbody.innerHTML = '<tr><td colspan="6" style="padding: 12px; color: var(--gray-1);">No history yet</td></tr>';
  }
}

function renderConfidenceHistory(data) {
  const tbody = document.getElementById('confidenceHistoryBody');
  const summary = document.getElementById('confidenceHistorySummary');
  const pageInfo = document.getElementById('confHistoryPageInfo');
  const prevBtn = document.getElementById('confHistoryPrev');
  const nextBtn = document.getElementById('confHistoryNext');
  if (!tbody) return;

  const items = data.items || [];
  const total = data.total || 0;
  const page = data.page || 1;
  const totalPages = data.total_pages || 0;

  if (items.length === 0) {
    tbody.innerHTML = '<tr><td colspan="6" style="padding: 12px; color: var(--gray-1);">No confidence history yet. Run a cycle to see last checked pairs.</td></tr>';
  } else {
    tbody.innerHTML = items.map(function (r) {
      const pair = r.pair || '—';
      const label = formatPairLabel(pair);
      const confidence = r.readiness != null ? Number(r.readiness).toFixed(1) : '—';
      const strategyName = r.strategy_name || r.strategy_key || '—';
      const strategyDisplay = strategyName !== '—' ? strategyName.replace(/_/g, ' ').replace(/\b\w/g, function(c) { return c.toUpperCase(); }) : '—';
      const bias = r.bias || '—';
      const rsi = r.rsi != null ? Number(r.rsi).toFixed(1) : '—';
      const checkedAt = r.checked_at ? (r.checked_at.replace('T', ' ').slice(0, 19)) : '—';
      const confClass = confidence !== '—' && parseFloat(confidence) >= 75 ? 'high' : (parseFloat(confidence) >= 50 ? 'medium' : 'low');
      return '<tr style="border-bottom: 1px solid var(--gray-3);">' +
        '<td style="padding: 8px;">' + label + '</td>' +
        '<td style="text-align: right; padding: 8px;" class="active-pair-confidence ' + confClass + '">' + confidence + '%</td>' +
        '<td style="padding: 8px; font-size: 11px;">' + strategyDisplay + '</td>' +
        '<td style="padding: 8px;">' + bias + '</td>' +
        '<td style="text-align: right; padding: 8px;">' + rsi + '</td>' +
        '<td style="padding: 8px; font-size: 11px; color: var(--gray-1);">' + checkedAt + '</td></tr>';
    }).join('');
  }

  if (summary) summary.textContent = total ? 'Total ' + total + ' entries (15 per page)' : '—';
  if (pageInfo) pageInfo.textContent = totalPages ? 'Page ' + page + ' of ' + totalPages : 'Page 1';
  if (prevBtn) prevBtn.disabled = page <= 1;
  if (nextBtn) nextBtn.disabled = page >= totalPages || totalPages === 0;
}

function initConfidenceHistoryPagination() {
  const prevBtn = document.getElementById('confHistoryPrev');
  const nextBtn = document.getElementById('confHistoryNext');
  if (prevBtn) prevBtn.onclick = function () { if (confHistoryCurrentPage > 1) { confHistoryCurrentPage--; loadConfidenceHistory(confHistoryCurrentPage); } };
  if (nextBtn) nextBtn.onclick = function () { confHistoryCurrentPage++; loadConfidenceHistory(confHistoryCurrentPage); };
}
