/* ════════════════════════════════════════════════════════════════
   CHARTS — INITIALIZATION & UPDATES
   ════════════════════════════════════════════════════════════════ */

function initCharts() {
  // Destroy existing chart instances to prevent canvas reuse error
  if (equityChart) equityChart.destroy();
  if (pnlChart) pnlChart.destroy();
  if (priceChart) priceChart.destroy();
  if (pairPnlChart) pairPnlChart.destroy();

  const baseOpts = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { display: false } },
    scales: {
      x: {
        ticks: { color: '#4a6070', font: { family: 'Space Mono', size: 10 }, maxTicksLimit: 6 },
        grid:  { color: 'rgba(30,42,53,0.6)' },
        border: { color: '#1e2a35' }
      },
      y: {
        ticks: { color: '#4a6070', font: { family: 'Space Mono', size: 10 } },
        grid:  { color: 'rgba(30,42,53,0.6)' },
        border: { color: '#1e2a35' }
      }
    }
  };

  equityChart = new Chart(document.getElementById('equityChart'), {
    type: 'line',
    data: { labels: [], datasets: [{ data: [], borderColor: '#00e5ff', backgroundColor: 'rgba(0,229,255,0.06)', borderWidth: 2, fill: true, tension: 0.3, pointRadius: 0 }] },
    options: { ...baseOpts }
  });

  pnlChart = new Chart(document.getElementById('pnlChart'), {
    type: 'bar',
    data: { labels: [], datasets: [{ data: [], backgroundColor: ctx => ctx.raw >= 0 ? 'rgba(0,255,136,0.7)' : 'rgba(255,59,92,0.7)', borderRadius: 2 }] },
    options: { ...baseOpts }
  });

  priceChart = new Chart(document.getElementById('priceChart'), {
    type: 'line',
    data: { labels: [], datasets: [
      { label: 'Price', data: [], borderColor: '#00e5ff', backgroundColor: 'rgba(0,229,255,0.08)', borderWidth: 2, fill: true, tension: 0.2, pointRadius: 0 },
      { label: 'Real Trades', type: 'scatter', data: [], pointRadius: 5, pointBackgroundColor: '#00ff88' },
      { label: 'Paper Trades', type: 'scatter', data: [], pointRadius: 5, pointBackgroundColor: '#ffd230' },
    ] },
    options: { ...baseOpts, plugins: { legend: { display: true, labels: { color: '#4a6070', font: { family: 'Space Mono', size: 10 } } } } }
  });

  pairPnlChart = new Chart(document.getElementById('pairPnlChart'), {
    type: 'line',
    data: { labels: [], datasets: [{ data: [], borderColor: '#00ff88', backgroundColor: 'rgba(0,255,136,0.1)', borderWidth: 2, fill: true, tension: 0.25, pointRadius: 0 }] },
    options: { ...baseOpts }
  });
}

async function updatePriceChart() {
  if (!selectedPair) return;
  try {
    const resp = await fetch(API + `/api/candles?pair=${encodeURIComponent(selectedPair)}&limit=200`);
    const candles = await resp.json();
    const labels = candles.map(c => (c.timestamp || c.t || '').toString().slice(11, 16));
    const prices = candles.map(c => Number(c.close ?? c.c ?? 0));

    priceChart.data.labels = labels;
    priceChart.data.datasets[0].data = prices;

    const tradeMarks = buildTradeMarks(selectedPair, candles, latestTrades);
    const paperMarks = buildTradeMarks(selectedPair, candles, latestPaperTrades);
    priceChart.data.datasets[1].data = tradeMarks;
    priceChart.data.datasets[2].data = paperMarks;
    priceChart.update('none');
  } catch (e) {
    // ignore chart errors
  }
}

function buildTradeMarks(pair, candles, trades) {
  if (!Array.isArray(trades)) return [];
  const marks = [];
  const labels = candles.map(c => (c.timestamp || c.t || '').toString().slice(11, 16));

  trades.filter(t => t.pair === pair).forEach(t => {
    const entry = t.entry_price;
    if (entry != null) {
      const idx = findNearestIndex(candles, t.opened_at);
      if (idx !== -1) {
        marks.push({ x: labels[idx], y: entry });
      }
    }
    if (t.status === 'closed' && t.exit_price != null) {
      const idx = findNearestIndex(candles, t.closed_at || t.opened_at);
      if (idx !== -1) {
        marks.push({ x: labels[idx], y: t.exit_price });
      }
    }
  });
  return marks;
}

function findNearestIndex(candles, isoTime) {
  if (!isoTime) return -1;
  const target = new Date(isoTime).getTime();
  let best = -1;
  let bestDiff = Infinity;
  candles.forEach((c, i) => {
    const ts = new Date(c.timestamp || c.t || 0).getTime();
    const diff = Math.abs(ts - target);
    if (diff < bestDiff) {
      bestDiff = diff;
      best = i;
    }
  });
  return best;
}

function updatePairPnlChart() {
  if (!selectedPair) return;
  const closed = latestTrades.filter(t => t.pair === selectedPair && t.status === 'closed' && t.pnl != null);
  const pnlSeries = [];
  let total = 0;
  closed.slice(-50).forEach((t) => {
    total += parseFloat(t.pnl);
    pnlSeries.push(total);
  });

  pairPnlChart.data.labels = pnlSeries.map((_, i) => `T${i + 1}`);
  pairPnlChart.data.datasets[0].data = pnlSeries;
  pairPnlChart.update('none');
}

function renderEquity(data) {
  if (!data || !data.length) return;
  equityChart.data.labels = data.map(d => d.created_at.slice(11, 16));
  equityChart.data.datasets[0].data = data.map(d => d.balance);
  equityChart.update('none');
}

function renderPnlChart(trades) {
  if (!trades) return;
  const closed = trades.filter(t => t.status === 'closed' && t.pnl != null).slice(-20);
  if (!closed.length) return;
  pnlChart.data.labels = closed.map((_, i) => `T${i + 1}`);
  pnlChart.data.datasets[0].data = closed.map(t => parseFloat(t.pnl));
  pnlChart.update('none');
}
