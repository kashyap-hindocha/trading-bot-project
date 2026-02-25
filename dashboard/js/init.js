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

  // Load pair signals (enabled pairs + last run status from bot)
  await loadPairSignals();

  // NOW populate pair selectors — pairSignals is ready
  populatePairSelectors();

  // Then fetch all data
  await checkBotStatus();
  await fetchAll();
  updateCandleChart(); // Load initial candle data (REST)
  if (typeof connectChartSocket === 'function') connectChartSocket(); // Live chart via WebSocket

  // Pair selection: filter and Disable all
  const pairFilterInput = document.getElementById('pairFilterInput');
  if (pairFilterInput) pairFilterInput.addEventListener('input', function () { if (typeof onPairFilterInput === 'function') onPairFilterInput(); });
  const disableAllPairsBtn = document.getElementById('disableAllPairsBtn');
  if (disableAllPairsBtn) disableAllPairsBtn.addEventListener('click', function () { if (typeof onDisableAllPairs === 'function') onDisableAllPairs(); });

  // Set up refresh intervals
  setInterval(fetchAll, REFRESH_MS);
  setInterval(checkBotStatus, REFRESH_MS);
  setInterval(updateReadiness, REFRESH_MS * 2);
  setInterval(updatePriceChart, REFRESH_MS * 2);
});

