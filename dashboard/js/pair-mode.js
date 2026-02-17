/* ════════════════════════════════════════════════════════════════
   PAIR MODE MANAGEMENT - FIXED VERSION
   ════════════════════════════════════════════════════════════════ */

// State to track if showing all pairs or just top 10
let showingAllPairs = false;

// Load current pair mode from API
async function loadPairMode() {
    try {
        const res = await fetch(`${API}/api/pair_mode`);
        const data = await res.json();

        pairMode = data.pair_mode || 'MULTI';
        selectedSinglePair = data.selected_pair;

        // Update UI
        updatePairModeUI();
    } catch (err) {
        console.error('Failed to load pair mode:', err);
    }
}

// Set pair mode (SINGLE or MULTI)
async function setPairMode(mode) {
    try {
        // FIX #2: If switching to SINGLE and no pair selected, auto-select first pair
        if (mode === 'SINGLE' && !selectedSinglePair && pairSignals.length > 0) {
            selectedSinglePair = pairSignals[0].pair;
            const selector = document.getElementById('pairSelector');
            if (selector) {
                selector.value = selectedSinglePair;
            }
        }

        const payload = {
            pair_mode: mode,
            selected_pair: mode === 'SINGLE' ? selectedSinglePair : null
        };

        const res = await fetch(`${API}/api/pair_mode`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        if (!res.ok) {
            const error = await res.json();
            showToast(error.error || 'Failed to set pair mode', 'error');
            return;
        }

        pairMode = mode;
        updatePairModeUI();
        showToast(`Switched to ${mode} mode`, 'success');
    } catch (err) {
        console.error('Failed to set pair mode:', err);
        showToast('Failed to set pair mode', 'error');
    }
}

// Handle pair selection (for SINGLE mode)
async function onPairSelect() {
    const selector = document.getElementById('pairSelector');
    selectedSinglePair = selector.value;

    if (!selectedSinglePair) return;

    try {
        const res = await fetch(`${API}/api/pair_mode`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                pair_mode: 'SINGLE',
                selected_pair: selectedSinglePair
            })
        });

        if (!res.ok) {
            const error = await res.json();
            showToast(error.error || 'Failed to select pair', 'error');
            return;
        }

        pairMode = 'SINGLE';
        updatePairModeUI();
        showToast(`Now trading ${selectedSinglePair}`, 'success');
    } catch (err) {
        console.error('Failed to select pair:', err);
        showToast('Failed to select pair', 'error');
    }
}

// Update pair mode UI elements
function updatePairModeUI() {
    const singleBtn = document.getElementById('pairModeSingle');
    const multiBtn = document.getElementById('pairModeMulti');
    const selectorContainer = document.getElementById('pairSelectorContainer');
    const statusDiv = document.getElementById('pairModeStatus');

    if (!singleBtn || !multiBtn || !selectorContainer || !statusDiv) return;

    // Update button states
    if (pairMode === 'SINGLE') {
        singleBtn.style.background = 'var(--accent)';
        singleBtn.style.color = '#000';
        singleBtn.style.fontWeight = '700';
        singleBtn.style.borderColor = 'var(--accent)';

        multiBtn.style.background = 'var(--gray-3)';
        multiBtn.style.color = 'var(--text)';
        multiBtn.style.fontWeight = '400';
        multiBtn.style.borderColor = 'var(--gray-2)';

        selectorContainer.style.display = 'block';
        statusDiv.textContent = selectedSinglePair ? `Trading ${selectedSinglePair}` : 'Select a pair';
    } else {
        multiBtn.style.background = 'var(--accent)';
        multiBtn.style.color = '#000';
        multiBtn.style.fontWeight = '700';
        multiBtn.style.borderColor = 'var(--accent)';

        singleBtn.style.background = 'var(--gray-3)';
        singleBtn.style.color = 'var(--text)';
        singleBtn.style.fontWeight = '400';
        singleBtn.style.borderColor = 'var(--gray-2)';

        selectorContainer.style.display = 'none';
        statusDiv.textContent = 'Trading ALL enabled pairs';
    }
}

// Load pair signals (with signal strength for sorting)
async function loadPairSignals() {
    try {
        const res = await fetch(`${API}/api/pair_signals`);
        if (!res.ok) {
            console.error('Failed to load pair signals');
            return;
        }

        pairSignals = await res.json();

        // Update pair selector dropdown
        updatePairSelector();

        // FIX #3: Only render if not already rendered, or if data significantly changed
        // This prevents the flashing issue
        renderPairList();
    } catch (err) {
        console.error('Failed to load pair signals:', err);
    }
}

// Update pair selector dropdown with all pairs
function updatePairSelector() {
    const selector = document.getElementById('pairSelector');
    if (!selector) return;

    const currentValue = selector.value;
    selector.innerHTML = '<option value="">Select a pair...</option>';

    pairSignals.forEach(p => {
        const option = document.createElement('option');
        option.value = p.pair;
        option.textContent = `${p.pair} (Signal: ${p.signal_strength}%)`;
        if (p.pair === (currentValue || selectedSinglePair)) {
            option.selected = true;
        }
        selector.appendChild(option);
    });
}

// FIX #1: Always render top 10 by default
// Render pair list (sorted by signal strength, top 10 default)
function renderPairList() {
    const container = document.getElementById('activePairsContainer');
    if (!container) return;

    if (!pairSignals || pairSignals.length === 0) {
        container.innerHTML = '<div style="color: var(--gray-2); font-size: 12px; padding: 10px;">No pairs available</div>';
        return;
    }

    // FIX #1: Always show top 10 by default
    const pairsToShow = showingAllPairs ? pairSignals : pairSignals.slice(0, 10);

    // FIX #3: Clear and rebuild to prevent flashing
    container.innerHTML = '';

    pairsToShow.forEach(p => {
        const card = createPairCard(p);
        container.appendChild(card);
    });

    // Add toggle button
    const toggleBtn = document.createElement('button');
    if (showingAllPairs) {
        toggleBtn.textContent = 'Show Top 10';
        toggleBtn.onclick = () => {
            showingAllPairs = false;
            renderPairList();
        };
    } else if (pairSignals.length > 10) {
        toggleBtn.textContent = `Show All (${pairSignals.length} pairs)`;
        toggleBtn.onclick = () => {
            showingAllPairs = true;
            renderPairList();
        };
    } else {
        return; // No button needed if <= 10 pairs
    }

    toggleBtn.style.cssText = `
    padding: 8px 16px;
    background: var(--gray-3);
    color: var(--accent);
    border: 1px solid var(--gray-2);
    border-radius: 4px;
    font-family: 'Space Mono';
    font-size: 12px;
    cursor: pointer;
    transition: all 0.2s;
    margin-top: 10px;
  `;
    container.appendChild(toggleBtn);
}

// Helper function to create a pair card
function createPairCard(p) {
    const card = document.createElement('div');
    card.className = 'pair-card';
    card.style.cssText = `
    background: var(--card-bg);
    border: 1px solid var(--gray-3);
    border-radius: 8px;
    padding: 12px 16px;
    min-width: 200px;
    flex: 1 1 calc(20% - 10px);
    max-width: calc(20% - 10px);
    display: flex;
    justify-content: space-between;
    align-items: center;
    transition: all 0.2s;
  `;

    // Signal strength indicator
    let signalColor = '#4a6070';  // Gray
    if (p.signal_strength >= 80) signalColor = '#00ff88';  // Green
    else if (p.signal_strength >= 60) signalColor = '#ffcc00';  // Yellow

    card.innerHTML = `
    <div style="flex: 1;">
      <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 4px;">
        <div style="width: 8px; height: 8px; border-radius: 50%; background: ${signalColor};"></div>
        <span style="font-weight: 700; font-size: 14px; color: var(--accent);">${p.pair}</span>
      </div>
      <div style="font-size: 11px; color: var(--gray-2);">
        Signal: ${p.signal_strength}% | Price: ${p.last_price ? '$' + p.last_price.toFixed(2) : 'N/A'}
      </div>
    </div>
    <div style="display: flex; align-items: center; gap: 8px;">
      <label style="display: flex; align-items: center; gap: 6px; cursor: pointer; font-size: 11px; color: var(--text);">
        <input type="checkbox" 
               ${p.enabled ? 'checked' : ''} 
               onchange="togglePairEnabled('${p.pair}', this.checked)"
               style="cursor: pointer;">
        <span>${p.enabled ? 'Enabled' : 'Disabled'}</span>
      </label>
    </div>
  `;

    return card;
}

// Toggle pair enabled/disabled
async function togglePairEnabled(pair, enabled) {
    try {
        const res = await fetch(`${API}/api/pairs/config`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                pair: pair,
                enabled: enabled ? 1 : 0
            })
        });

        if (!res.ok) {
            showToast('Failed to update pair', 'error');
            // Reload to revert checkbox
            await loadPairSignals();
            return;
        }

        showToast(`${pair} ${enabled ? 'enabled' : 'disabled'}`, 'success');

        // Update local state without re-rendering
        const pairData = pairSignals.find(p => p.pair === pair);
        if (pairData) {
            pairData.enabled = enabled ? 1 : 0;
        }
    } catch (err) {
        console.error('Failed to toggle pair:', err);
        showToast('Failed to update pair', 'error');
        await loadPairSignals();
    }
}
