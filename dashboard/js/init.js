/* ════════════════════════════════════════════════════════════════
   INITIALIZATION & BOOT SEQUENCE
   ════════════════════════════════════════════════════════════════ */

// Boot up the application
document.addEventListener('DOMContentLoaded', function() {
  initCharts();
  loadPairs();
  fetchMode();
  checkBotStatus();
  fetchAll();
  
  // Set up refresh intervals
  setInterval(fetchAll, REFRESH_MS);
  setInterval(checkBotStatus, REFRESH_MS);
  setInterval(updateReadiness, REFRESH_MS * 2);
  setInterval(updatePriceChart, REFRESH_MS * 2);
});
