/* TradingView Advanced Chart embed — real-time price (per-tick) and full toolbar/details */

let tradingViewWidget = null;
let chartTabActive = 'our';

function pairToTradingViewSymbol(pair) {
  if (!pair) return 'BINANCE:BTCUSDT';
  var base = pair.replace(/^B-/, '').replace(/_USDT$/i, '');
  return 'BINANCE:' + base + 'USDT';
}

function intervalToTv(interval) {
  var map = { '1m': '1', '3m': '3', '5m': '5', '15m': '15', '30m': '30', '1h': '60', '4h': '240', '1D': 'D', '1W': 'W' };
  return map[interval] || '5';
}

function switchChartTab(tab) {
  chartTabActive = tab;
  var our = document.getElementById('ourChartContainer');
  var tv = document.getElementById('tradingviewContainer');
  var btnOur = document.getElementById('chartTabOur');
  var btnTv = document.getElementById('chartTabTv');
  if (!our || !tv) return;
  if (tab === 'tradingview') {
    our.style.display = 'none';
    tv.style.display = 'block';
    btnOur.classList.remove('active');
    btnTv.classList.add('active');
    initTradingViewWidget();
  } else {
    our.style.display = 'block';
    tv.style.display = 'none';
    btnOur.classList.add('active');
    btnTv.classList.remove('active');
  }
}

function initTradingViewWidget() {
  var container = document.getElementById('tradingview_chart');
  if (!container) return;
  if (typeof TradingView === 'undefined') {
    var script = document.createElement('script');
    script.src = 'https://s3.tradingview.com/tv.js';
    script.onload = function () { createTradingViewWidget(); };
    document.head.appendChild(script);
  } else {
    createTradingViewWidget();
  }
}

function createTradingViewWidget() {
  var container = document.getElementById('tradingview_chart');
  if (!container) return;
  var pair = typeof selectedCandlePair !== 'undefined' ? selectedCandlePair : '';
  var interval = typeof currentTimeframe !== 'undefined' ? currentTimeframe : '5m';
  var symbol = pairToTradingViewSymbol(pair);
  var intervalTv = intervalToTv(interval);
  if (typeof TradingView === 'undefined') return;
  container.innerHTML = '';
  tradingViewWidget = new TradingView.widget({
    width: container.clientWidth || '100%',
    height: 450,
    symbol: symbol,
    interval: intervalTv,
    timezone: 'Etc/UTC',
    theme: 'dark',
    style: '1',
    locale: 'en',
    toolbar_bg: '#0f1419',
    enable_publishing: false,
    hide_side_toolbar: false,
    allow_symbol_change: true,
    container_id: 'tradingview_chart',
    show_volume: true,
    fullscreen: false
  });
}

function updateTradingViewSymbol() {
  if (chartTabActive !== 'tradingview') return;
  tradingViewWidget = null;
  createTradingViewWidget();
}
