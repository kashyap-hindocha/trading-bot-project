/* ════════════════════════════════════════════════════════════════
   PAIR MANAGER - Select & Configure Trading Pairs
   ════════════════════════════════════════════════════════════════ */

let availablePairs = [];
let pairConfigsDB = [];  // Renamed to avoid conflict with app.js pairConfigs
let showOnlyEnabledFilter = false;
let searchFilter = '';

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
    
    // Render
    container.innerHTML = filteredPairs.map(pair => {
        const cfg = configMap[pair.pair] || {
            enabled: 0,
            leverage: 5,
            quantity: 0.001,
            inr_amount: 300.0
        };
        
        const isEnabled = cfg.enabled === 1;
        const enabledCount = Object.values(configMap).filter(c => c.enabled === 1).length;
        const canEnable = enabledCount < 10 || isEnabled;
        
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
                
                <!-- Pair Name -->
                <div style="flex: 0 0 100px; font-weight: 700; color: ${isEnabled ? 'var(--accent)' : 'var(--text)'};">
                    ${pair.base}
                    <div style="font-size: 9px; color: var(--gray-1); font-weight: 400;">/USDT</div>
                </div>
                
                <!-- Leverage -->
                <div style="flex: 0 0 120px;">
                    <label style="font-size: 9px; color: var(--gray-1); display: block; margin-bottom: 4px;">LEVERAGE</label>
                    <input type="number" 
                           value="${cfg.leverage}" 
                           min="1" max="25" 
                           ${!isEnabled ? 'disabled' : ''}
                           onchange="updatePairConfig('${pair.pair}', 'leverage', this.value)"
                           style="width: 100%; padding: 6px 8px; background: var(--bg); color: var(--accent); border: 1px solid var(--gray-2); border-radius: 4px; font-family: 'Space Mono'; font-size: 11px;">
                </div>
                
                <!-- INR Amount -->
                <div style="flex: 0 0 140px;">
                    <label style="font-size: 9px; color: var(--gray-1); display: block; margin-bottom: 4px;">INR AMOUNT</label>
                    <input type="number" 
                           value="${cfg.inr_amount}" 
                           min="100" max="10000" 
                           step="50"
                           ${!isEnabled ? 'disabled' : ''}
                           onchange="updatePairConfig('${pair.pair}', 'inr_amount', this.value)"
                           style="width: 100%; padding: 6px 8px; background: var(--bg); color: var(--accent); border: 1px solid var(--gray-2); border-radius: 4px; font-family: 'Space Mono'; font-size: 11px;">
                </div>
                
                <!-- Quantity (Auto-calculated, read-only) -->
                <div style="flex: 0 0 120px;">
                    <label style="font-size: 9px; color: var(--gray-1); display: block; margin-bottom: 4px;">QUANTITY</label>
                    <input type="text" 
                           value="${cfg.quantity}" 
                           readonly
                           style="width: 100%; padding: 6px 8px; background: var(--gray-3); color: var(--gray-1); border: 1px solid var(--gray-2); border-radius: 4px; font-family: 'Space Mono'; font-size: 11px; cursor: not-allowed;">
                </div>
                
                <!-- Status -->
                <div style="flex: 1; text-align: right; font-size: 11px; color: var(--gray-1);">
                    ${isEnabled ? '<span style="color: var(--green);">✓ ENABLED</span>' : '<span style="color: var(--gray-2);">○ Disabled</span>'}
                </div>
            </div>
        `;
    }).join('');
    
    updatePairManagerSummary();
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
        
        const res = await fetch(`${API}/api/pairs/config/update`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                pair: pair,
                enabled: enabled ? 1 : 0,
                leverage: 5,  // defaults
                quantity: 0.001,
                inr_amount: 300.0
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
        console.log(`Updated ${pair} ${field} to ${value}`);
        
        // Reload configs
        await loadPairConfigs();
        
    } catch (err) {
        console.error('Failed to update config:', err);
        showToast('Failed to update configuration', 'error');
    }
}

// Filter pairs by search
function filterPairs() {
    const input = document.getElementById('pairSearchInput');
    searchFilter = input ? input.value.trim() : '';
    renderPairManager();
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

// Update summary
function updatePairManagerSummary() {
    const enabledCount = pairConfigsDB.filter(c => c.enabled === 1).length;
    const summaryEl = document.getElementById('enabledCount');
    if (summaryEl) {
        summaryEl.textContent = enabledCount;
        summaryEl.style.color = enabledCount >= 10 ? 'var(--red)' : 'var(--accent)';
    }
}
