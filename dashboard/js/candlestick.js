/* ════════════════════════════════════════════════════════════════
   CANDLESTICK CHART — TradingView Style Interactive Chart
   ════════════════════════════════════════════════════════════════ */

let candleChart = null;
let candleSeries = null;
let currentTimeframe = '5m';
let candleData = {};
let selectedCandlePair = 'B-BTC_USDT';

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

// Fetch candles from server and update chart
async function updateCandleChart() {
  try {
    const pair = selectedCandlePair || 'B-BTC_USDT';
    const interval = currentTimeframe;
    
    // Fetch candles from API
    const response = await fetch(`${API}/api/candles?pair=${encodeURIComponent(pair)}&interval=${interval}&limit=100`);
    if (!response.ok) return;

    const data = await response.json();
    if (!Array.isArray(data) || data.length === 0) return;

    // Format data for lightweight-charts
    const candleData = data.map(candle => ({
      time: Math.floor(new Date(candle.timestamp).getTime() / 1000), // Unix timestamp in seconds
      open: parseFloat(candle.open),
      high: parseFloat(candle.high),
      low: parseFloat(candle.low),
      close: parseFloat(candle.close),
    }));

    // Set data on series
    candleSeries.setData(candleData);
    candleChart.timeScale().fitContent();

    // Update info
    if (candleData.length > 0) {
      const last = candleData[candleData.length - 1];
      document.getElementById('candleInfo').textContent = 
        `${pair} | O: ${last.open.toFixed(4)} H: ${last.high.toFixed(4)} L: ${last.low.toFixed(4)} C: ${last.close.toFixed(4)}`;
    }
  } catch (e) {
    console.error('Candlestick chart error:', e);
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

// Update on pair selection
function onCandlePairChange(pair) {
  if (pair) {
    selectedCandlePair = pair;
    updateCandleChart();
  }
}

// Auto-refresh candlestick data
setInterval(() => {
  if (candleChart) updateCandleChart();
}, 10000); // Update every 10 seconds
