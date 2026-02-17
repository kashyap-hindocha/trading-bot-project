/* ════════════════════════════════════════════════════════════════
   INITIALIZATION & BOOT SEQUENCE
   ════════════════════════════════════════════════════════════════ */

// Boot up the application
document.addEventListener('DOMContentLoaded', async function () {
  initCharts();
  initCandleChart(); // Initialize lightweight-charts candlestick

  // Load pairs FIRST and wait for completion
  await loadPairs();
  populatePairSelectors(); // Populate pair dropdowns
  await fetchMode();
  await loadStrategies();

  // Load pair mode and signals
  await loadPairMode();
  await loadPairSignals();

  // Then fetch all data
  await checkBotStatus();
  await fetchAll();
  updateCandleChart(); // Load initial candle data

  // Set up refresh intervals
  setInterval(fetchAll, REFRESH_MS);
  setInterval(checkBotStatus, REFRESH_MS);
  setInterval(updateReadiness, REFRESH_MS * 2);
  setInterval(updatePriceChart, REFRESH_MS * 2);
  setInterval(updateCandleChart, 10000); // Refresh candlesticks every 10s
  setInterval(loadPairSignals, 10000); // Refresh pair signals every 10s
});
