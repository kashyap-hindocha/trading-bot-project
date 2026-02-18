/* ════════════════════════════════════════════════════════════════
   PAIR MODE MANAGEMENT - SIMPLIFIED VERSION
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

        // Populate pair selector with available pairs
        populatePairModeSelector();
    } catch (err) {
        console.error('Failed to load pair mode:', err);
    }
}

// Populate the pair selector dropdown with all available pairs
function populatePairModeSelector() {
    const selector = document.getElementById('pairSelector');
    if (!selector || !allPairs || allPairs.length === 0) return;

    selector.innerHTML = '<option value="">Select a pair...</option>';

    allPairs.forEach(p => {
        const option = document.createElement('option');
        option.value = p.pair;
        option.textContent = p.pair.replace('B-', '').replace('_USDT', '') + '/USDT';
        if (p.pair === selectedSinglePair) {
            option.selected = true;
        }
        selector.appendChild(option);
    });
}

// Set pair mode (SINGLE or MULTI)
async function setPairMode(mode) {
    try {
        // If switching to SINGLE and no pair selected, auto-select first pair
        if (mode === 'SINGLE' && !selectedSinglePair && allPairs && allPairs.length > 0) {
            selectedSinglePair = allPairs[0].pair;
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
    if (!selector) return;

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

// Load and render pair signals (for horizontal Trading Pairs section)
async function loadPairSignals() {
    try {
        const res = await fetch(`${API}/api/pair_signals`);
        if (!res.ok) return;

        const data = await res.json();
        // API returns a plain array; handle both array and {pairs:[]} formats
        pairSignals = Array.isArray(data) ? data : (data.pairs || []);

        // Populate pair selector for SINGLE mode
        populatePairModeSelector();

        // Render the horizontal pair cards
        renderPairList();
    } catch (err) {
        console.error('Failed to load pair signals:', err);
    }
}

// Render horizontal pair list (top 10 by default)
function renderPairList() {
    const container = document.getElementById('pairSignalsContainer');
    if (!container) return;

    if (!pairSignals || pairSignals.length === 0) {
        container.innerHTML = '<div style="color: var(--gray-2); font-size: 12px; padding: 10px;">No pairs available</div>';
        return;
    }

    // Always show top 10 by default
    const pairsToShow = pairSignals.slice(0, 10);

    container.innerHTML = '';

    pairsToShow.forEach(p => {
        const card = document.createElement('div');
        card.style.cssText = `
      padding: 12px 16px;
      background: var(--gray-3);
      border: 1px solid var(--gray-2);
      border-radius: 6px;
      min-width: 120px;
      cursor: pointer;
      transition: all 0.2s;
    `;

        const baseCoin = p.pair.replace('B-', '').replace('_USDT', '');
        const signalPct = Math.min(100, Math.max(0, p.signal_strength || 0));

        card.innerHTML = `
      <div style="font-size: 13px; font-weight: 700; color: var(--accent); margin-bottom: 6px;">${baseCoin}</div>
      <div style="font-size: 11px; color: var(--gray-1); margin-bottom: 4px;">Signal: ${signalPct}%</div>
      <div style="height: 4px; background: var(--gray-2); border-radius: 2px; overflow: hidden;">
        <div style="height: 100%; width: ${signalPct}%; background: var(--accent); transition: width 0.3s;"></div>
      </div>
    `;

        card.onmouseenter = () => {
            card.style.borderColor = 'var(--accent)';
            card.style.transform = 'translateY(-2px)';
        };
        card.onmouseleave = () => {
            card.style.borderColor = 'var(--gray-2)';
            card.style.transform = 'translateY(0)';
        };

        container.appendChild(card);
    });

    // Add "Show All" / "Show Less" toggle
    const showAllBtn = document.createElement('button');
    let expanded = false;
    const extraCount = pairSignals.length > 10 ? pairSignals.length - 10 : 0;
    showAllBtn.textContent = extraCount > 0 ? `+${extraCount} more` : 'Show all pairs';
    showAllBtn.style.cssText = `
      padding: 12px 16px;
      background: var(--gray-3);
      color: var(--accent);
      border: 1px dashed var(--gray-2);
      border-radius: 6px;
      font-family: 'Space Mono';
      font-size: 11px;
      cursor: pointer;
      transition: all 0.2s;
    `;

    showAllBtn.onclick = async () => {
        expanded = !expanded;

        if (!expanded) {
            // Collapse back to top 10
            while (container.firstChild) container.removeChild(container.firstChild);
            renderPairList();
            return;
        }

        // Fetch ALL available pairs from CoinDCX API
        showAllBtn.textContent = 'Loading...';
        showAllBtn.disabled = true;

        try {
            const res = await fetch(`${API}/api/pairs/available`);
            const allAvailable = await res.json();

            // Build a signal map from pairSignals for quick lookup
            const signalMap = {};
            pairSignals.forEach(p => { signalMap[p.pair] = p.signal_strength || 0; });

            // Clear container and render all pairs
            while (container.firstChild) container.removeChild(container.firstChild);

            allAvailable.forEach(p => {
                const card = document.createElement('div');
                card.style.cssText = `
                  padding: 12px 16px;
                  background: var(--gray-3);
                  border: 1px solid var(--gray-2);
                  border-radius: 6px;
                  min-width: 120px;
                  cursor: pointer;
                  transition: all 0.2s;
                `;
                const baseCoin = (p.base || p.pair.replace('B-', '').replace('_USDT', ''));
                const signalPct = Math.min(100, Math.max(0, signalMap[p.pair] || 0));
                card.innerHTML = `
                  <div style="font-size: 13px; font-weight: 700; color: var(--accent); margin-bottom: 6px;">${baseCoin}</div>
                  <div style="font-size: 11px; color: var(--gray-1); margin-bottom: 4px;">Signal: ${signalPct.toFixed(1)}%</div>
                  <div style="height: 4px; background: var(--gray-2); border-radius: 2px; overflow: hidden;">
                    <div style="height: 100%; width: ${signalPct}%; background: var(--accent); transition: width 0.3s;"></div>
                  </div>
                `;
                card.onmouseenter = () => { card.style.borderColor = 'var(--accent)'; card.style.transform = 'translateY(-2px)'; };
                card.onmouseleave = () => { card.style.borderColor = 'var(--gray-2)'; card.style.transform = 'translateY(0)'; };
                container.appendChild(card);
            });

            showAllBtn.textContent = 'Show less';
            showAllBtn.disabled = false;
            container.appendChild(showAllBtn);

        } catch (err) {
            console.error('Failed to load all pairs:', err);
            showAllBtn.textContent = 'Error - try again';
            showAllBtn.disabled = false;
        }
    };

    container.appendChild(showAllBtn);
}

