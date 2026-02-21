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

function renderBatchStatus(data) {
  const liveDisplay = document.getElementById('batchLiveDisplay');
  const idleDisplay = document.getElementById('batchIdleDisplay');
  const currentPairs = document.getElementById('batchCurrentPairs');
  const countdownVal = document.getElementById('batchCountdownVal');
  const idleDot = document.getElementById('batchIdleDot');
  const idleText = document.getElementById('batchIdleText');

  if (!liveDisplay || !idleDisplay) return;

  const isProcessing = data.is_processing || false;
  const currentBatch = data.current_batch || [];
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

    if (currentBatch.length > 0) {
      const labels = currentBatch.map(p => p.replace('B-', '').replace('_USDT', ''));
      currentPairs.textContent = labels.join(', ');
    } else {
      currentPairs.textContent = '—';
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
