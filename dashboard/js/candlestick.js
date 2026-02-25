/* ════════════════════════════════════════════════════════════════
   CANDLESTICK CHART — TradingView Style Interactive Chart (Live via WebSocket)
   ════════════════════════════════════════════════════════════════ */

let candleChart = null;
let candleSeries = null;
let currentTimeframe = '5m';
let selectedCandlePair = '';
let priceChartPair = '';
let chartSocket = null;
let chartLiveConnected = false;
let lastCandleForInfo = null; // so we can refresh confidence when pairSignals updates

// Initialize candlestick chart with lightweight-charts
function initCandleChart() {
  const container = document.getElementById('candleChart');
  if (!container) return;

  candleChart = LightweightCharts.createChart(container, {
    layout: {
      textColor: '#4a6070',
      background: { type: 'solid', color: '#0f1419' },
      fontSize: 12,
      fontFamily: 'Space Mono'
    },
    timeScale: {
      timeVisible: true,
      secondsVisible: false,
      rightOffset: 12,
      barSpacing: 8,
    },
    grid: {
      horzLines: { color: 'rgba(30,42,53,0.4)' },
      vertLines: { color: 'rgba(30,42,53,0.4)' }
    },
    rightPriceScale: {
      textColor: '#4a6070',
      autoScale: true,
      borderColor: '#2a3a45'
    }
  });

  candleSeries = candleChart.addCandlestickSeries({
    upColor: '#00ff88',
    downColor: '#ff3b5c',
    borderUpColor: '#00ff88',
    borderDownColor: '#ff3b5c',
    wickUpColor: '#00ff88',
    wickDownColor: '#ff3b5c'
  });

  candleChart.timeScale().fitContent();
}

// Populate pair dropdowns — use pairSignals (bot's configured pairs with real data)
function populatePairSelectors() {
  // Use pairSignals if available, fall back to allPairs
  const pairs = (pairSignals && pairSignals.length > 0) ? pairSignals : allPairs;
  if (!pairs || pairs.length === 0) return;

  const candleSelect = document.getElementById('candlePairSelect');

  if (candleSelect && candleSelect.children.length <= 1) {
    pairs.forEach(p => {
      const opt = document.createElement('option');
      opt.value = p.pair;
      opt.textContent = p.pair.replace('B-', '').replace('_USDT', '');
      candleSelect.appendChild(opt);
    });
    // Auto-select first pair and load data
    if (pairs.length > 0 && !selectedCandlePair) {
      candleSelect.value = pairs[0].pair;
      selectedCandlePair = pairs[0].pair;
      updateCandleChart();
    }
  }
}

// Fetch candles from server and update chart
async function updateCandleChart() {
  try {
    if (!selectedCandlePair) return;

    const pair = selectedCandlePair;
    const interval = currentTimeframe;

    // Fetch candles from API
    const response = await fetch(`${API}/api/candles?pair=${encodeURIComponent(pair)}&interval=${interval}&limit=50`);
    if (!response.ok) return;

    const data = await response.json();
    if (!Array.isArray(data) || data.length === 0) return;

    // Format data for lightweight-charts
    const candleData = data.map((candle, index) => {
      try {
        let time = null;
        const ts = candle.timestamp ?? candle.time;

        if (ts !== undefined && ts !== null && ts !== '') {
          if (typeof ts === 'number') {
            // CoinDCX returns Unix milliseconds
            time = ts > 1e10 ? Math.floor(ts / 1000) : Math.floor(ts);
          } else {
            // Try parsing as date string
            const date = new Date(ts);
            if (!isNaN(date.getTime())) {
              time = Math.floor(date.getTime() / 1000);
            }
          }
        }

        // Fallback: generate approximate time if timestamp invalid
        if (!time) {
          const now = Math.floor(Date.now() / 1000);
          time = now - (data.length - index - 1) * 300;
        }

        const o = parseFloat(candle.open);
        const h = parseFloat(candle.high);
        const l = parseFloat(candle.low);
        const c = parseFloat(candle.close);

        if (isNaN(o) || isNaN(h) || isNaN(l) || isNaN(c)) return null;

        return { time, open: o, high: h, low: l, close: c };
      } catch (e) {
        console.error('Candle parse error:', e, candle);
        return null;
      }
    }).filter(c => c !== null);

    // lightweight-charts requires data sorted oldest→newest (ascending)
    // CoinDCX returns newest→oldest, so we must sort
    candleData.sort((a, b) => a.time - b.time);

    // Remove duplicate timestamps (lightweight-charts throws on dupes)
    const seen = new Set();
    const dedupedData = candleData.filter(c => {
      if (seen.has(c.time)) return false;
      seen.add(c.time);
      return true;
    });

    if (dedupedData.length > 0) {
      candleSeries.setData(dedupedData);
      candleChart.timeScale().fitContent();
      updateCandleInfo(pair, dedupedData[dedupedData.length - 1]);
    } else {
      console.warn('No valid candle data after parsing');
    }
  } catch (e) {
    console.error('Candlestick chart error:', e);
  }
}

function updateCandleInfo(pair, lastCandle) {
  if (!pair) return;
  if (lastCandle) lastCandleForInfo = lastCandle;
  const candle = lastCandle || lastCandleForInfo;
  const el = document.getElementById('candleInfo');
  if (!el) return;
  const baseCoin = pair.replace('B-', '').replace('_USDT', '');
  // Use same confidence as Quick View / Trading Pairs (pairSignals.signal_strength); fallback to pairReadiness
  const pairData = (typeof pairSignals !== 'undefined' && Array.isArray(pairSignals)) ? pairSignals.find(function (p) { return p.pair === pair; }) : null;
  const confidence = (pairData && pairData.signal_strength != null) ? Number(pairData.signal_strength) : ((typeof pairReadiness !== 'undefined' && pairReadiness && pairReadiness[pair]) ? pairReadiness[pair].readiness : 0);
  const liveTag = chartLiveConnected ? ' \u2022 LIVE' : '';
  if (!candle) {
    el.textContent = baseCoin + ' | Confidence: ' + confidence.toFixed(1) + '%' + liveTag;
    return;
  }
  el.textContent =
    baseCoin + ' | O: ' + candle.open.toFixed(4) + ' H: ' + candle.high.toFixed(4) + ' L: ' + candle.low.toFixed(4) + ' C: ' + candle.close.toFixed(4) + ' | Confidence: ' + confidence.toFixed(1) + '%' + liveTag;
}

function refreshCandleInfo() {
  if (selectedCandlePair) updateCandleInfo(selectedCandlePair, null);
}

// ── Live chart via Socket.IO (no polling) ──
function connectChartSocket() {
  if (typeof io === 'undefined') return;
  const baseUrl = (typeof API !== 'undefined' && API && API.startsWith('http')) ? API.replace(/\/$/, '') : window.location.origin;
  if (chartSocket) {
    chartSocket.disconnect();
    chartSocket = null;
  }
  chartSocket = io(baseUrl, { path: '/socket.io', transports: ['websocket', 'polling'], reconnection: false, reconnectionAttempts: 0 });
  let connectErrorLogged = false;
  chartSocket.on('connect', () => {
    chartLiveConnected = true;
    connectErrorLogged = false;
    subscribeChartCandles();
    const el = document.getElementById('candleInfo');
    if (el && selectedCandlePair) {
      const baseCoin = selectedCandlePair.replace('B-', '').replace('_USDT', '');
      if (el.textContent.indexOf('LIVE') === -1) el.textContent += ' ● LIVE';
    }
  });
  chartSocket.on('connect_error', () => {
    chartLiveConnected = false;
    if (!connectErrorLogged) {
      connectErrorLogged = true;
      console.warn('Chart live socket unavailable (chart uses REST fallback). Manual Execute and trades do not need it.');
    }
  });
  chartSocket.on('disconnect', () => {
    chartLiveConnected = false;
  });
  chartSocket.on('candlestick', (payload) => {
    if (!candleSeries || !payload) return;
    if (payload.pair !== selectedCandlePair || payload.interval !== currentTimeframe) return;
    const bar = {
      time: payload.time,
      open: Number(payload.open),
      high: Number(payload.high),
      low: Number(payload.low),
      close: Number(payload.close)
    };
    if (Number.isFinite(bar.open + bar.high + bar.low + bar.close)) {
      candleSeries.update(bar);
      updateCandleInfo(selectedCandlePair, bar);
    }
  });
}

function subscribeChartCandles() {
  if (!chartSocket || !chartSocket.connected || !selectedCandlePair) return;
  chartSocket.emit('subscribe_candles', { pair: selectedCandlePair, interval: currentTimeframe });
}

// Handle pair selection for candlestick
function onCandlePairSelect() {
  const select = document.getElementById('candlePairSelect');
  if (select && select.value) {
    selectedCandlePair = select.value;
    updateCandleChart();
    subscribeChartCandles();
    if (typeof updateTradingViewSymbol === 'function') updateTradingViewSymbol();
  }
}

// Handle pair selection for price chart
function onPriceChartPairChange() {
  const select = document.getElementById('priceChartPairSelect');
  if (select && select.value) {
    priceChartPair = select.value;
    const baseCoin = select.value.replace('B-', '').replace('_USDT', '');
    const readiness = pairReadiness[select.value]?.readiness || 0;
    document.getElementById('priceChartInfo').textContent = `${baseCoin} | Confidence: ${readiness.toFixed(1)}%`;
  }
}

// Handle timeframe change
function onTimeframeChange() {
  const tf = document.getElementById('candleTimeframe').value;
  if (tf !== currentTimeframe) {
    currentTimeframe = tf;
    updateCandleChart();
    subscribeChartCandles();
    if (typeof updateTradingViewSymbol === 'function') updateTradingViewSymbol();
  }
}

// Fallback: refresh via REST when live socket is down (e.g. every 60s)
setInterval(() => {
  if (candleChart && candleSeries && selectedCandlePair && !chartLiveConnected) updateCandleChart();
}, 60000);
