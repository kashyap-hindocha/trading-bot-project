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

  // Load pair mode and signals (after pairs are loaded)
  await loadPairMode();
  await loadPairSignals(); // Load horizontal pair signals

  // NOW populate pair selectors — pairSignals is ready
  populatePairSelectors();

  // Then fetch all data
  await checkBotStatus();
  await fetchAll();
  updateCandleChart(); // Load initial candle data

  // Set up refresh intervals
  setInterval(fetchAll, REFRESH_MS);
  setInterval(checkBotStatus, REFRESH_MS);
  setInterval(loadPairSignals, REFRESH_MS); // Refresh pair signals every cycle
  setInterval(updateReadiness, REFRESH_MS * 2);
  setInterval(updatePriceChart, REFRESH_MS * 2);
  setInterval(updateCandleChart, 10000); // Refresh candlesticks every 10s
});

