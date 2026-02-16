/* ════════════════════════════════════════════════════════════════
   INITIALIZATION & BOOT SEQUENCE
   ════════════════════════════════════════════════════════════════ */

// Boot up the application
document.addEventListener('DOMContentLoaded', async function() {
  initCharts();
  
  // Load pairs FIRST and wait for completion
  await loadPairs();
  await fetchMode();
  
  // Then fetch all data
  await checkBotStatus();
  await fetchAll();
  
  // Set up refresh intervals
  setInterval(fetchAll, REFRESH_MS);
  setInterval(checkBotStatus, REFRESH_MS);
  setInterval(updateReadiness, REFRESH_MS * 2);
  setInterval(updatePriceChart, REFRESH_MS * 2);
});
