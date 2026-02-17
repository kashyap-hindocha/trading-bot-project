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
