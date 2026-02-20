/* ════════════════════════════════════════════════════════════════
   PAIR MANAGER - Select & Configure Trading Pairs
   ════════════════════════════════════════════════════════════════ */

let availablePairs = [];
let pairConfigsDB = [];  // Renamed to avoid conflict with app.js pairConfigs
let showOnlyEnabledFilter = false;
let searchFilter = '';
let currentPrices = {};  // Store current prices for dynamic quantity calculation
let pairPage = 1;
const PAIRS_PER_PAGE = 10;
// Store last scanned signals for persistence across renders
let lastScannedSignals = {};

// Calculate quantity based on INR amount, leverage, and current price
function calculateQuantity(inrAmount, leverage, currentPrice) {
    if (!currentPrice || currentPrice <= 0) return null;
    
    // Formula: quantity = (inr_amount * leverage) / current_price
    // This gives the position size in base currency
    const quantity = (inrAmount * leverage) / currentPrice;
    
    // Return with appropriate precision (6 decimal places)
    return parseFloat(quantity.toFixed(6));
}

function getLivePrice(pair) {
    const directPrice = Number(currentPrices[pair] || 0);
    if (directPrice > 0) return directPrice;

    if (typeof pairSignals !== 'undefined' && Array.isArray(pairSignals) && pairSignals.length > 0) {
        const signalPair = pairSignals.find(p => p && p.pair === pair);
        const signalPrice = Number(signalPair?.last_price || 0);
        if (signalPrice > 0) return signalPrice;
    }

    return 0;
}

// Load current prices for all pairs
async function loadCurrentPrices() {
    try {
        const res = await fetch(`${API}/api/pairs/prices`);
        if (!res.ok) return;
        
        const apiPrices = await res.json();
        currentPrices = { ...currentPrices, ...apiPrices };

        if (typeof pairSignals !== 'undefined' && Array.isArray(pairSignals)) {
            pairSignals.forEach(item => {
                const pair = item?.pair;
                const lastPrice = Number(item?.last_price || 0);
                if (pair && lastPrice > 0) {
                    currentPrices[pair] = lastPrice;
                }
            });
        }

        console.log(`Loaded prices for ${Object.keys(currentPrices).length} pairs`);
    } catch (err) {
        console.error('Failed to load current prices:', err);
    }
}

// Load available pairs from CoinDCX
async function loadAvailablePairs() {
    try {
        const res = await fetch(`${API}/api/pairs/available`);
        if (!res.ok) {
            showToast('Failed to load available pairs', 'error');
            return;
        }
        
        availablePairs = await res.json();
        console.log(`Loaded ${availablePairs.length} available pairs from CoinDCX`);
        
        // Load current prices
        await loadCurrentPrices();
        
        // Load current configs
        await loadPairConfigs();
        
        // Render the pair list
        renderPairManager();
    } catch (err) {
        console.error('Failed to load available pairs:', err);
        showToast('Failed to load pairs', 'error');
    }
}

// Load pair configurations from database
async function loadPairConfigs() {
    try {
        const res = await fetch(`${API}/api/pairs/config`);
        if (!res.ok) return;
        
        pairConfigsDB = await res.json();
        console.log(`Loaded ${pairConfigsDB.length} pair configs from database`);
    } catch (err) {
        console.error('Failed to load pair configs:', err);
    }
}

// Render pair manager list
function renderPairManager() {
    const container = document.getElementById('pairManagerList');
    if (!container) return;
    
    if (!availablePairs || availablePairs.length === 0) {
        container.innerHTML = `
            <div style="color: var(--gray-2); text-align: center; padding: 20px;">
                No pairs available. Click "Refresh Pairs" to load.
            </div>
        `;
        return;
    }
    
    // Build a map of existing configs for quick lookup
    const configMap = {};
    pairConfigsDB.forEach(cfg => {
        configMap[cfg.pair] = cfg;
    });
    
    // Filter pairs based on search and enabled filter
    let filteredPairs = availablePairs;
    
    if (searchFilter) {
        const search = searchFilter.toLowerCase();
        filteredPairs = filteredPairs.filter(p => 
            p.base.toLowerCase().includes(search) || 
            p.pair.toLowerCase().includes(search)
        );
    }
    
    if (showOnlyEnabledFilter) {
        filteredPairs = filteredPairs.filter(p => {
            const cfg = configMap[p.pair];
            return cfg && cfg.enabled === 1;
        });
    }
    
    // Sort: enabled first, then by name
    filteredPairs.sort((a, b) => {
        const cfgA = configMap[a.pair];
        const cfgB = configMap[b.pair];
        const enabledA = cfgA ? cfgA.enabled : 0;
        const enabledB = cfgB ? cfgB.enabled : 0;
        
        if (enabledA !== enabledB) return enabledB - enabledA;
        return a.base.localeCompare(b.base);
    });

    // Pagination
    const totalPages = Math.max(1, Math.ceil(filteredPairs.length / PAIRS_PER_PAGE));
    if (pairPage > totalPages) pairPage = totalPages;
    if (pairPage < 1) pairPage = 1;
    const startIdx = (pairPage - 1) * PAIRS_PER_PAGE;
    const pagePairs = filteredPairs.slice(startIdx, startIdx + PAIRS_PER_PAGE);

    // Update page indicators
    const pageEl = document.getElementById('pairPage');
    const totalEl = document.getElementById('pairTotalPages');
    if (pageEl) pageEl.textContent = String(pairPage);
    if (totalEl) totalEl.textContent = String(totalPages);
    
    // Render current page
    container.innerHTML = pagePairs.map(pair => {
        const cfg = configMap[pair.pair] || {
            enabled: 0,
            leverage: 5,
            quantity: 0.001,
            inr_amount: 300.0
        };
        
        const isEnabled = cfg.enabled === 1;
        const enabledCount = Object.values(configMap).filter(c => c.enabled === 1).length;
        const canEnable = enabledCount < 10 || isEnabled;
        
        // Get current price and calculate quantity
        const currentPrice = getLivePrice(pair.pair);
        const calculatedQty = calculateQuantity(cfg.inr_amount, cfg.leverage, currentPrice);
        const quantityDisplay = calculatedQty !== null ? calculatedQty : '—';
        const qtyTitle = calculatedQty !== null
            ? `Calculated: (${cfg.inr_amount} × ${cfg.leverage}) ÷ ${currentPrice.toFixed(2)} = ${calculatedQty}`
            : 'Waiting for live price to calculate quantity';
        const priceDisplay = currentPrice > 0 ? `₹${currentPrice.toLocaleString()}` : 'Syncing...';
        
        return `
            <div class="pair-manager-row" data-pair="${pair.pair}" 
                 style="display: flex; align-items: center; gap: 12px; padding: 12px; 
                        background: ${isEnabled ? 'var(--gray-3)' : 'transparent'}; 
                        border: 1px solid ${isEnabled ? 'var(--accent)' : 'var(--gray-2)'}; 
                        border-radius: 6px; margin-bottom: 8px;">
                
                <!-- Enable Toggle -->
                <div style="flex: 0 0 60px;">
                    <label class="toggle-switch" title="${!canEnable ? 'Max 10 pairs can be enabled' : ''}">
                        <input type="checkbox" 
                               ${isEnabled ? 'checked' : ''} 
                               ${!canEnable ? 'disabled' : ''}
                               onchange="togglePairEnabled('${pair.pair}', this.checked)">
                        <span class="slider"></span>
                    </label>
                </div>
                
                <!-- Pair Name & Price -->
                <div style="flex: 0 0 120px; font-weight: 700; color: ${isEnabled ? 'var(--accent)' : 'var(--text)'};">
                    ${pair.base}
                    <div style="font-size: 9px; color: var(--gray-1); font-weight: 400;">/USDT</div>
                    <div style="font-size: 9px; color: var(--gray-2); font-weight: 400; margin-top: 2px;">${priceDisplay}</div>
                </div>
                
                <!-- Leverage -->
                <div style="flex: 0 0 110px;">
                    <label style="font-size: 9px; color: var(--gray-1); display: block; margin-bottom: 4px;">LEVERAGE</label>
                    <input type="number" 
                           value="${cfg.leverage}" 
                           min="1" max="25" 
                           ${!isEnabled ? 'disabled' : ''}
                           oninput="updatePairConfigLive('${pair.pair}', 'leverage', this.value)"
                           onchange="updatePairConfig('${pair.pair}', 'leverage', this.value)"
                           style="width: 100%; padding: 6px 8px; background: var(--bg); color: var(--accent); border: 1px solid var(--gray-2); border-radius: 4px; font-family: 'Space Mono'; font-size: 11px;">
                </div>
                
                <!-- INR Amount -->
                <div style="flex: 0 0 130px;">
                    <label style="font-size: 9px; color: var(--gray-1); display: block; margin-bottom: 4px;">INR AMOUNT</label>
                    <input type="number" 
                           value="${cfg.inr_amount}" 
                           min="100" max="10000" 
                           step="50"
                           ${!isEnabled ? 'disabled' : ''}
                           oninput="updatePairConfigLive('${pair.pair}', 'inr_amount', this.value)"
                           onchange="updatePairConfig('${pair.pair}', 'inr_amount', this.value)"
                           style="width: 100%; padding: 6px 8px; background: var(--bg); color: var(--accent); border: 1px solid var(--gray-2); border-radius: 4px; font-family: 'Space Mono'; font-size: 11px;">
                </div>
                
                <!-- Quantity (Auto-calculated, read-only) -->
                <div style="flex: 0 0 140px;">
                    <label style="font-size: 9px; color: var(--gray-1); display: block; margin-bottom: 4px;">QUANTITY (Auto)</label>
                    <input type="text" 
                           id="qty-${pair.pair}"
                              value="${quantityDisplay}" 
                           readonly
                              title="${qtyTitle}"
                           style="width: 100%; padding: 6px 8px; background: var(--gray-3); color: ${currentPrice > 0 ? 'var(--accent)' : 'var(--gray-1)'}; border: 1px solid var(--gray-2); border-radius: 4px; font-family: 'Space Mono'; font-size: 11px; cursor: help;">
                </div>
                
                <!-- Status + Signal proximity placeholder -->
                <div style="flex: 1; text-align: right; font-size: 11px; color: var(--gray-1);">
                    <div>
                        ${isEnabled ? '<span style="color: var(--green);">✓ ENABLED</span>' : '<span style="color: var(--gray-2);">○ Disabled</span>'}
                    </div>
                    <div class="signal-meter" data-signal="${pair.pair}"
                         style="margin-top: 4px; font-size: 10px; color: var(--gray-2);">
                        Signal: —
                    </div>
                </div>
            </div>
        `;
    }).join('');
    
    updatePairManagerSummary();
    // After rendering, re-apply last scanned signals if available
    applyLastScannedSignals();
}

// Toggle pair enabled/disabled
async function togglePairEnabled(pair, enabled) {
    try {
        // Check limit
        if (enabled) {
            const enabledCount = pairConfigsDB.filter(c => c.enabled === 1).length;
            if (enabledCount >= 10) {
                showToast('Maximum 10 pairs can be enabled', 'error');
                // Reload to reset checkbox
                renderPairManager();
                return;
            }
        }
        
        // Get existing config or use defaults
        const existing = pairConfigsDB.find(c => c.pair === pair) || {};
        const leverage = existing.leverage || 5;
        const inr_amount = existing.inr_amount || 300.0;
        
        // Calculate quantity based on current price
        const currentPrice = getLivePrice(pair);
        const quantity = calculateQuantity(inr_amount, leverage, currentPrice) ?? Number(existing.quantity || 0.001);
        
        const res = await fetch(`${API}/api/pairs/config/update`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                pair: pair,
                enabled: enabled ? 1 : 0,
                leverage: leverage,
                quantity: quantity,
                inr_amount: inr_amount
            })
        });
        
        if (!res.ok) {
            showToast('Failed to update pair', 'error');
            return;
        }
        
        const data = await res.json();
        showToast(data.message, 'success');
        
        // Reload configs and re-render
        await loadPairConfigs();
        renderPairManager();
        
        // Update favorites panel if function exists
        if (typeof renderFavorites === 'function') {
            renderFavorites();
        }
        
    } catch (err) {
        console.error('Failed to toggle pair:', err);
        showToast('Failed to update pair', 'error');
    }
}

// Update pair configuration (leverage or inr_amount)
async function updatePairConfig(pair, field, value) {
    try {
        // Get existing config
        const existing = pairConfigsDB.find(c => c.pair === pair) || {
            enabled: 0,
            leverage: 5,
            quantity: 0.001,
            inr_amount: 300.0
        };
        
        // Update the specific field
        const updatedConfig = { ...existing };
        if (field === 'leverage') {
            updatedConfig.leverage = parseInt(value);
        } else if (field === 'inr_amount') {
            updatedConfig.inr_amount = parseFloat(value);
        }
        
        // Calculate new quantity
        const currentPrice = getLivePrice(pair);
        updatedConfig.quantity = calculateQuantity(
            updatedConfig.inr_amount, 
            updatedConfig.leverage, 
            currentPrice
        ) ?? Number(existing.quantity || 0.001);
        
        const res = await fetch(`${API}/api/pairs/config/update`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                pair: pair,
                enabled: updatedConfig.enabled,
                leverage: updatedConfig.leverage,
                quantity: updatedConfig.quantity,
                inr_amount: updatedConfig.inr_amount
            })
        });
        
        if (!res.ok) {
            showToast('Failed to update configuration', 'error');
            return;
        }
        
        const data = await res.json();
        console.log(`Updated ${pair} ${field} to ${value}, quantity: ${updatedConfig.quantity}`);
        
        // Reload configs
        await loadPairConfigs();
        
    } catch (err) {
        console.error('Failed to update config:', err);
        showToast('Failed to update configuration', 'error');
    }
}

// Update quantity display in real-time as user types (without saving to DB)
function updatePairConfigLive(pair, field, value) {
    // Find the quantity input for this pair
    const qtyInput = document.getElementById(`qty-${pair}`);
    if (!qtyInput) return;
    
    // Get the current row to extract current values
    const row = document.querySelector(`[data-pair="${pair}"]`);
    if (!row) return;
    
    // Get leverage and inr_amount inputs
    const leverageInput = row.querySelector('input[type="number"][min="1"]');
    const inrInput = row.querySelector('input[type="number"][min="100"]');
    
    if (!leverageInput || !inrInput) return;
    
    // Get current values (use the updated value for the field being changed)
    const leverage = field === 'leverage' ? parseFloat(value) : parseFloat(leverageInput.value);
    const inrAmount = field === 'inr_amount' ? parseFloat(value) : parseFloat(inrInput.value);
    
    // Get current price
    const currentPrice = getLivePrice(pair);
    
    // Calculate and update quantity display
    const newQty = calculateQuantity(inrAmount, leverage, currentPrice);
    if (newQty === null) {
        qtyInput.value = '—';
        qtyInput.title = 'Waiting for live price to calculate quantity';
        return;
    }

    qtyInput.value = newQty;
    qtyInput.title = `Calculated: (${inrAmount} × ${leverage}) ÷ ${currentPrice.toFixed(2)} = ${newQty}`;
}

// Filter pairs by search
function filterPairs() {
    const input = document.getElementById('pairSearchInput');
    searchFilter = input ? input.value.trim() : '';
    renderPairManager();
    // After changing the visible list, prompt user to rescan if desired
}

// Show only enabled pairs
function showOnlyEnabled() {
    showOnlyEnabledFilter = !showOnlyEnabledFilter;
    const btn = document.getElementById('showEnabledBtn');
    if (btn) {
        if (showOnlyEnabledFilter) {
            btn.textContent = 'Show All Pairs';
            btn.style.background = 'var(--accent)';
            btn.style.color = '#000';
            btn.style.fontWeight = '700';
        } else {
            btn.textContent = 'Show Enabled Only';
            btn.style.background = 'var(--gray-3)';
            btn.style.color = 'var(--text)';
            btn.style.fontWeight = '400';
        }
    }
    renderPairManager();
}

// Refresh available pairs from CoinDCX
async function refreshAvailablePairs() {
    const btn = event.target;
    btn.disabled = true;
    btn.textContent = '🔄 Loading...';
    
    await loadAvailablePairs();
    
    btn.disabled = false;
    btn.textContent = '🔄 Refresh Pairs';
    showToast('Pairs refreshed', 'success');
}

// Disable all pairs at once
async function disableAllPairs() {
    try {
        // Confirm before disabling
        const enabledCount = pairConfigsDB.filter(c => c.enabled === 1).length;
        
        if (enabledCount === 0) {
            showToast('No enabled pairs to disable', 'info');
            return;
        }
        
        if (!confirm(`Disable all ${enabledCount} enabled pairs?`)) {
            return;
        }
        
        const btn = event.target;
        btn.disabled = true;
        btn.textContent = 'Disabling...';
        
        const res = await fetch(`${API}/api/pairs/config/disable_all`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        
        if (!res.ok) {
            showToast('Failed to disable pairs', 'error');
            btn.disabled = false;
            btn.textContent = 'Disable All';
            return;
        }
        
        const data = await res.json();
        showToast(data.message, 'success');
        
        // Reload configs and re-render
        await loadPairConfigs();
        renderPairManager();
        
        // Update favorites panel
        if (typeof renderFavorites === 'function') {
            renderFavorites();
        }
        
        btn.disabled = false;
        btn.textContent = 'Disable All';
        
    } catch (err) {
        console.error('Failed to disable all pairs:', err);
        showToast('Failed to disable pairs', 'error');
        if (event && event.target) {
            event.target.disabled = false;
            event.target.textContent = 'Disable All';
        }
    }
}

// Update summary
function updatePairManagerSummary() {
    const enabledCount = pairConfigsDB.filter(c => c.enabled === 1).length;
    const summaryEl = document.getElementById('enabledCount');
    if (summaryEl) {
        summaryEl.textContent = enabledCount;
        summaryEl.style.color = enabledCount >= 10 ? 'var(--red)' : 'var(--accent)';
    }
}

// Pagination controls
function nextPairPage() {
    pairPage += 1;
    renderPairManager();
    // Signals will be scanned explicitly or via button
}

function prevPairPage() {
    pairPage -= 1;
    renderPairManager();
    // Signals will be scanned explicitly or via button
}

// Scan the currently visible pairs (top 10 in the list) for signal proximity
async function scanVisibleSignals() {
    try {
        const container = document.getElementById('pairManagerList');
        if (!container) return;

        const scanBtn = document.getElementById('pairScanBtn');
        const prevBtn = document.getElementById('pairPrevBtn');
        const nextBtn = document.getElementById('pairNextBtn');

        if (scanBtn) {
            scanBtn.disabled = true;
            scanBtn.textContent = 'Scanning...';
        }
        if (prevBtn) prevBtn.disabled = true;
        if (nextBtn) nextBtn.disabled = true;

        const rows = Array.from(container.querySelectorAll('.pair-manager-row'));
        if (!rows.length) return;

        // Take first 10 visible pairs to keep API cost low
        const pairs = rows.slice(0, 10).map(row => row.getAttribute('data-pair')).filter(Boolean);
        if (!pairs.length) return;

        // Show loading text
        pairs.forEach(pair => {
            const meter = container.querySelector(`.signal-meter[data-signal="${pair}"]`);
            if (meter) {
                meter.textContent = 'Signal: scanning...';
                meter.style.color = 'var(--gray-1)';
            }
        });

        const resp = await fetch(`${API}/api/signal/readiness?pairs=` + encodeURIComponent(pairs.join(',')));
        if (!resp.ok) {
            showToast('Failed to scan signals', 'error');
            return;
        }

        const data = await resp.json();
        if (!Array.isArray(data)) return;

        // Persist last scanned signals
        lastScannedSignals = {};
        data.forEach(item => {
            if (!item || !item.pair) return;
            lastScannedSignals[item.pair] = Number(item.readiness || 0);
            const meter = container.querySelector(`.signal-meter[data-signal="${item.pair}"]`);
            if (!meter) return;

            const readiness = Number(item.readiness || 0);
            const pct = Math.min(100, Math.max(0, readiness));
            let color = 'var(--accent)';
            if (pct >= 80) {
                color = 'var(--green)';
            } else if (pct >= 60) {
                color = 'var(--yellow)';
            }

            meter.innerHTML = `
                <div>Signal: ${pct.toFixed(1)}%</div>
                <div style="margin-top: 2px; height: 3px; background: var(--gray-3); border-radius: 2px; overflow: hidden;">
                  <div style="height: 100%; width: ${pct}%; background: ${color}; transition: width 0.3s;"></div>
                </div>
            `;
        });
    } catch (err) {
        console.error('Failed to scan visible signals:', err);
        showToast('Failed to scan signals', 'error');
    } finally {
        const scanBtn = document.getElementById('pairScanBtn');
        const prevBtn = document.getElementById('pairPrevBtn');
        const nextBtn = document.getElementById('pairNextBtn');

        if (scanBtn) {
            scanBtn.disabled = false;
            scanBtn.textContent = '📡 Scan Signals (Top 10)';
        }
        if (prevBtn) prevBtn.disabled = false;
        if (nextBtn) nextBtn.disabled = false;
    }
}

// Apply last scanned signals to the UI after render
function applyLastScannedSignals() {
    if (!lastScannedSignals || Object.keys(lastScannedSignals).length === 0) return;
    const container = document.getElementById('pairManagerList');
    if (!container) return;
    Object.entries(lastScannedSignals).forEach(([pair, readiness]) => {
        const meter = container.querySelector(`.signal-meter[data-signal="${pair}"]`);
        if (!meter) return;
        const pct = Math.min(100, Math.max(0, readiness));
        let color = 'var(--accent)';
        if (pct >= 80) {
            color = 'var(--green)';
        } else if (pct >= 60) {
            color = 'var(--yellow)';
        }
        meter.innerHTML = `
            <div>Signal: ${pct.toFixed(1)}%</div>
            <div style="margin-top: 2px; height: 3px; background: var(--gray-3); border-radius: 2px; overflow: hidden;">
              <div style="height: 100%; width: ${pct}%; background: ${color}; transition: width 0.3s;"></div>
            </div>
        `;
    });
}
