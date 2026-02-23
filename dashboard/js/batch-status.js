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

    if (progressText) {
      progressText.textContent = totalBatches > 0
        ? `Batch ${batchIndex} of ${totalBatches} (${totalPairs} pairs total)`
        : 'Processing...';
    }

    // Show current 5 pairs with their confidence level
    if (pairsContainer) {
      if (currentBatchResults.length > 0) {
        pairsContainer.innerHTML = currentBatchResults.map(function (r) {
          const pair = r.pair || '';
          const confidence = r.readiness != null ? Number(r.readiness).toFixed(1) : '—';
          const label = formatPairLabel(pair);
          const isHigh = confidence !== '—' && parseFloat(confidence) >= 75;
          const confClass = isHigh ? 'active-pair-confidence high' : (parseFloat(confidence) >= 50 ? 'active-pair-confidence medium' : 'active-pair-confidence low');
          return '<span class="batch-pair-chip ' + confClass + '" style="padding: 6px 10px; border-radius: 6px; background: var(--gray-2); font-size: 12px; font-weight: 600;">' + label + ': ' + confidence + '%</span>';
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

    if (idleDot) {
      idleDot.style.background = 'var(--green)';
      idleDot.classList.remove('pulse');
    }
    if (idleText) idleText.textContent = 'Idle';
    const sec = Math.max(0, typeof secondsUntil === 'number' ? secondsUntil : (data.seconds_until_next ?? 600));
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
}
