/* ════════════════════════════════════════════════════════════════
   APP CONFIG & GLOBAL STATE
   ════════════════════════════════════════════════════════════════ */

const API = '';  // empty = same host, goes through Nginx proxy
const REFRESH_MS = 5000;

// Chart instances
let equityChart, pnlChart, priceChart, pairPnlChart;

// State
let botRunning = false;
let tradingMode = 'REAL';
let selectedPair = '';
let pairsList = [];
let allPairs = [];
let pairConfigs = {};
let latestTrades = [];
let latestPaperTrades = [];
let pairReadiness = {}; // Store readiness data for sorting
let favoritePairs = new Set(JSON.parse(localStorage.getItem('favoritePairs') || '[]'));

// Toast notification
function showToast(msg, type = 'success') {
  const t = document.getElementById('toast');
  if (!t) return;
  t.textContent = msg;
  t.className = `toast ${type} show`;
  setTimeout(() => t.classList.remove('show'), 3000);
}
