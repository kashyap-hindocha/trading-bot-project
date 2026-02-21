/* ════════════════════════════════════════════════════════════════
   BATCH CONFIDENCE CHECKER UI
   Auto-enabled pairs, batch status, countdown timer
   ════════════════════════════════════════════════════════════════ */

let batchCountdownInterval = null;

async function loadBatchStatus() {
  try {
    const res = await fetch(API + '/api/batch/status');
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || 'Failed to load batch status');
    }
    renderBatchStatus(data);
  } catch (e) {
    console.error('Batch status load failed:', e);
    document.getElementById('batchStatusText').textContent = 'Offline';
    document.getElementById('batchCurrentPairs').textContent = '—';
    document.getElementById('batchCountdownVal').textContent = '—';
    document.getElementById('autoEnabledPanel').innerHTML =
      '<div style="color: var(--gray-2); font-size: 12px;">Unable to load status</div>';
  }
}

function renderBatchStatus(data) {
  const dot = document.getElementById('batchStatusDot');
  const text = document.getElementById('batchStatusText');
  const currentPairs = document.getElementById('batchCurrentPairs');
  const countdownVal = document.getElementById('batchCountdownVal');

  if (!dot || !text) return;

  const isProcessing = data.is_processing || false;
  const currentBatch = data.current_batch || [];
  const secondsUntil = data.seconds_until_next ?? data.seconds_until_next;
  const lastError = data.last_error;

  if (lastError) {
    dot.style.background = 'var(--red)';
    text.textContent = 'Error';
  } else if (isProcessing) {
    dot.style.background = 'var(--accent)';
    dot.classList.add('pulse');
    text.textContent = 'Processing...';
    if (currentBatch.length > 0) {
      const labels = currentBatch.map(p => p.replace('B-', '').replace('_USDT', ''));
      currentPairs.textContent = `Evaluating: ${labels.join(', ')}`;
    } else {
      currentPairs.textContent = '—';
    }
  } else {
    dot.style.background = 'var(--green)';
    dot.classList.remove('pulse');
    text.textContent = 'Idle';
    currentPairs.textContent = '—';
  }

  const sec = Math.max(0, typeof secondsUntil === 'number' ? secondsUntil : (data.seconds_until_next ?? 600));
  countdownVal.textContent = formatCountdown(sec);

  // Start countdown ticker if not already running
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
    loadBatchStatus(); // Refresh to get new countdown
    return;
  }
  el.textContent = formatCountdown(m * 60 + s);
}

async function loadAutoEnabledPairs() {
  try {
    const res = await fetch(API + '/api/batch/auto-enabled');
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || 'Failed');
    }
    renderAutoEnabledPanel(Array.isArray(data) ? data : []);
  } catch (e) {
    console.error('Auto-enabled pairs load failed:', e);
    document.getElementById('autoEnabledPanel').innerHTML =
      '<div style="color: var(--gray-2); font-size: 12px;">Unable to load</div>';
  }
}

function renderAutoEnabledPanel(pairs) {
  const panel = document.getElementById('autoEnabledPanel');
  if (!panel) return;

  if (!pairs || pairs.length === 0) {
    panel.innerHTML =
      '<div style="color: var(--gray-2); font-size: 12px; padding: 10px;">No pairs auto-enabled yet</div>';
    return;
  }

  panel.innerHTML = pairs.map(p => {
    const baseCoin = p.pair.replace('B-', '').replace('_USDT', '');
    const readiness = Math.min(100, Math.max(0, p.readiness || 0));
    const bias = p.bias || '—';
    const barColor = readiness >= 75 ? 'var(--green)' : readiness >= 50 ? 'var(--accent)' : 'var(--yellow)';
    return `
      <div class="auto-enabled-card" style="padding: 12px 16px; background: var(--gray-3); border: 1px solid var(--gray-2); border-radius: 6px; min-width: 140px;">
        <div style="font-size: 13px; font-weight: 700; color: var(--accent); margin-bottom: 6px;">${baseCoin}</div>
        <div style="font-size: 11px; color: var(--gray-1); margin-bottom: 4px;">Confidence: ${readiness.toFixed(1)}% · ${bias}</div>
        <div style="height: 6px; background: var(--gray-2); border-radius: 3px; overflow: hidden;">
          <div style="height: 100%; width: ${readiness}%; background: ${barColor}; transition: width 0.3s;"></div>
        </div>
      </div>
    `;
  }).join('');
}

async function refreshBatchUI() {
  await loadBatchStatus();
  await loadAutoEnabledPairs();
}
