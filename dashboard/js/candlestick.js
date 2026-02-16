/* ════════════════════════════════════════════════════════════════
   CANDLESTICK CHART — TradingView Style Interactive Chart
   ════════════════════════════════════════════════════════════════ */

let candleChart = null;
let candleSeries = null;
let currentTimeframe = '5m';
let selectedCandlePair = '';
let priceChartPair = '';

// Initialize candlestick chart with lightweight-charts
function initCandleChart() {
  const container = document.getElementById('candleChart');
  if (!container) return;
  
  candleChart = LightweightCharts.createChart(container, {
    layout: {
      textColor: '#4a6070',
      backgroundColor: '#0f1419',
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
      hStyle: { color: 'rgba(30,42,53,0.4)' },
      vStyle: { color: 'rgba(30,42,53,0.4)' }
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

// Populate pair dropdowns
function populatePairSelectors() {
  if (!allPairs || allPairs.length === 0) return;
  
  const candleSelect = document.getElementById('candlePairSelect');
  const priceSelect = document.getElementById('priceChartPairSelect');
  
  if (candleSelect && candleSelect.children.length <= 1) {
    allPairs.forEach(p => {
      const opt = document.createElement('option');
      opt.value = p.pair;
      opt.textContent = p.pair.replace('B-', '').replace('_USDT', '');
      candleSelect.appendChild(opt);
    });
  }
  
  if (priceSelect && priceSelect.children.length <= 1) {
    allPairs.forEach(p => {
      const opt = document.createElement('option');
      opt.value = p.pair;
      opt.textContent = p.pair.replace('B-', '').replace('_USDT', '');
      priceSelect.appendChild(opt);
    });
  }
}

// Fetch candles from server and update chart
async function updateCandleChart() {
  try {
    if (!selectedCandlePair) return;
    
    const pair = selectedCandlePair;
    const interval = currentTimeframe;
    
    // Fetch candles from API
    const response = await fetch(`${API}/api/candles?pair=${encodeURIComponent(pair)}&interval=${interval}&limit=100`);
    if (!response.ok) return;

    const data = await response.json();
    if (!Array.isArray(data) || data.length === 0) return;

    // Format data for lightweight-charts
    const candleData = data.map(candle => ({
      time: Math.floor(new Date(candle.timestamp).getTime() / 1000),
      open: parseFloat(candle.open),
      high: parseFloat(candle.high),
      low: parseFloat(candle.low),
      close: parseFloat(candle.close),
    }));

    // Set data on series
    candleSeries.setData(candleData);
    candleChart.timeScale().fitContent();

    // Update info with current price and confidence
    if (candleData.length > 0) {
      const last = candleData[candleData.length - 1];
      const baseCoin = pair.replace('B-', '').replace('_USDT', '');
      const readiness = pairReadiness[pair]?.readiness || 0;
      document.getElementById('candleInfo').textContent = 
        `${baseCoin} | O: ${last.open.toFixed(4)} H: ${last.high.toFixed(4)} L: ${last.low.toFixed(4)} C: ${last.close.toFixed(4)} | Confidence: ${readiness.toFixed(1)}%`;
    }
  } catch (e) {
    console.error('Candlestick chart error:', e);
  }
}

// Handle pair selection for candlestick
function onCandlePairSelect() {
  const select = document.getElementById('candlePairSelect');
  if (select && select.value) {
    selectedCandlePair = select.value;
    updateCandleChart();
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
  }
}

// Auto-refresh candlestick data
setInterval(() => {
  if (candleChart && selectedCandlePair) updateCandleChart();
}, 10000); // Update every 10 seconds
