/* ════════════════════════════════════════════════════════════════
   PAIR MODE MANAGEMENT
   ════════════════════════════════════════════════════════════════ */

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

        // Reload pair signals to update the list
        await loadPairSignals();
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

        // Render pair list
        renderPairList();
    } catch (err) {
        console.error('Failed to load pair signals:', err);
    }
}

// Update pair selector dropdown with all pairs
function updatePairSelector() {
    const selector = document.getElementById('pairSelector');
    if (!selector) return;

    selector.innerHTML = '<option value="">Select a pair...</option>';

    pairSignals.forEach(p => {
        const option = document.createElement('option');
        option.value = p.pair;
        option.textContent = `${p.pair} (Signal: ${p.signal_strength}%)`;
        if (p.pair === selectedSinglePair) {
            option.selected = true;
        }
        selector.appendChild(option);
    });
}

// Render pair list (sorted by signal strength, top 10 default)
function renderPairList() {
    const container = document.getElementById('activePairsContainer');
    if (!container) return;

    if (!pairSignals || pairSignals.length === 0) {
        container.innerHTML = '<div style="color: var(--gray-2); font-size: 12px; padding: 10px;">No pairs available</div>';
        return;
    }

    // Show top 10 by default (already sorted by signal strength from API)
    const topPairs = pairSignals.slice(0, 10);

    container.innerHTML = '';

    topPairs.forEach(p => {
        const card = document.createElement('div');
        card.className = 'pair-card';
        card.style.cssText = `
      background: var(--card-bg);
      border: 1px solid var(--gray-3);
      border-radius: 8px;
      padding: 12px 16px;
      min-width: 200px;
      flex: 1;
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

        container.appendChild(card);
    });

    // Add "Show More" button if there are more than 10 pairs
    if (pairSignals.length > 10) {
        const showMoreBtn = document.createElement('button');
        showMoreBtn.textContent = `Show All (${pairSignals.length} pairs)`;
        showMoreBtn.style.cssText = `
      padding: 8px 16px;
      background: var(--gray-3);
      color: var(--accent);
      border: 1px solid var(--gray-2);
      border-radius: 4px;
      font-family: 'Space Mono';
      font-size: 12px;
      cursor: pointer;
      transition: all 0.2s;
    `;
        showMoreBtn.onclick = () => renderAllPairs();
        container.appendChild(showMoreBtn);
    }
}

// Render all pairs (not just top 10)
function renderAllPairs() {
    const container = document.getElementById('activePairsContainer');
    if (!container) return;

    container.innerHTML = '';

    pairSignals.forEach(p => {
        const card = document.createElement('div');
        card.className = 'pair-card';
        card.style.cssText = `
      background: var(--card-bg);
      border: 1px solid var(--gray-3);
      border-radius: 8px;
      padding: 12px 16px;
      min-width: 200px;
      flex: 1;
      display: flex;
      justify-content: space-between;
      align-items: center;
      transition: all 0.2s;
    `;

        let signalColor = '#4a6070';
        if (p.signal_strength >= 80) signalColor = '#00ff88';
        else if (p.signal_strength >= 60) signalColor = '#ffcc00';

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

        container.appendChild(card);
    });

    // Add "Show Less" button
    const showLessBtn = document.createElement('button');
    showLessBtn.textContent = 'Show Top 10';
    showLessBtn.style.cssText = `
    padding: 8px 16px;
    background: var(--gray-3);
    color: var(--accent);
    border: 1px solid var(--gray-2);
    border-radius: 4px;
    font-family: 'Space Mono';
    font-size: 12px;
    cursor: pointer;
    transition: all 0.2s;
  `;
    showLessBtn.onclick = () => renderPairList();
    container.appendChild(showLessBtn);
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

        // Update local state
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
