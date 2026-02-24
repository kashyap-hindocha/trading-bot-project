/* ════════════════════════════════════════════════════════════════
   INITIALIZATION & BOOT SEQUENCE
   ════════════════════════════════════════════════════════════════ */

// Boot up the application
document.addEventListener('DOMContentLoaded', async function () {
  initCharts();
  initCandleChart(); // Initialize lightweight-charts candlestick

  // Load pairs FIRST and wait for completion
  await loadPairs();
  await fetchMode();
  await loadStrategies();

  // Load pair signals (multi-pair always enabled; no Trading Mode section)
  await loadPairSignals(); // Load horizontal pair signals

  // Load batch status and auto-enabled pairs
  if (typeof refreshBatchUI === 'function') {
    await refreshBatchUI();
  }

  // NOW populate pair selectors — pairSignals is ready
  populatePairSelectors();

  // Then fetch all data
  await checkBotStatus();
  await fetchAll();
  updateCandleChart(); // Load initial candle data (REST)
  if (typeof connectChartSocket === 'function') connectChartSocket(); // Live chart via WebSocket

  // Set up refresh intervals
  setInterval(fetchAll, REFRESH_MS);
  setInterval(checkBotStatus, REFRESH_MS);
  setInterval(updateReadiness, REFRESH_MS * 2);
  setInterval(updatePriceChart, REFRESH_MS * 2);
  // Candlestick: live via Socket.IO; REST fallback when socket down (candlestick.js)
  
  // Batch status self-schedules: every 2s during processing, 30s when idle
  if (typeof loadBatchStatus === 'function') {
    loadBatchStatus();
  }
  if (typeof initConfidenceHistoryPagination === 'function') {
    initConfidenceHistoryPagination();
  }
});

