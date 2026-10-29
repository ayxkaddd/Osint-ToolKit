window.currentService = 'oi';

const state = {
    lastReport: null,
    isRunning: false,
};

const els = {
    credits: document.getElementById('credits'),
    queryType: document.getElementById('queryType'),
    queryInput: document.getElementById('queryInput'),
    submitQuery: document.getElementById('submitQuery'),
    runPremiumOnly: document.getElementById('runPremiumOnly'),
    loading: document.getElementById('loading'),
    result: document.getElementById('result'),
    resultContent: document.getElementById('resultContent'),
    cards: document.getElementById('oiCards'),
    pdfFormat: document.getElementById('pdfFormat'),
    pdfDownload: document.getElementById('pdfDownload'),
    pdfLink: document.getElementById('pdfLink'),
    queryTypeBtns: document.querySelectorAll('.query-type-btn'),
    searchModeValue: document.getElementById('searchModeValue'),
    searchModeBtns: document.querySelectorAll('.search-mode-btn'),
};

window.loadResultIntoView = function (data) {
    renderResult(data, { allowPremiumOnly: false });
};

function setBusy(isBusy) {
    state.isRunning = isBusy;
    els.loading.classList.toggle('hidden', !isBusy);
    els.submitQuery.disabled = isBusy;
    els.runPremiumOnly.disabled = isBusy;
    els.searchModeBtns.forEach((button) => {
        button.disabled = isBusy;
    });
}

function renderResult(data, options = {}) {
    const allowPremiumOnly = Boolean(options.allowPremiumOnly && state.lastReport);
    els.cards.classList.add('hidden');

    if (Array.isArray(data.modules)) {
        // Only the "run premium modules" follow-up applies; there is no PDF to link
        els.pdfLink.classList.add('hidden');
        els.pdfDownload.classList.toggle('hidden', !allowPremiumOnly);
        els.runPremiumOnly.classList.toggle('hidden', !allowPremiumOnly);
        els.resultContent.textContent = '';
        els.cards.innerHTML = oiCardsHtml(data.modules, data.query);
        els.cards.classList.remove('hidden');
    } else if (data.url) {
        els.pdfLink.classList.remove('hidden');
        els.pdfLink.href = data.url;
        els.pdfDownload.classList.remove('hidden');
        els.runPremiumOnly.classList.toggle('hidden', !allowPremiumOnly);
        els.resultContent.textContent = options.message || 'PDF report generated successfully';
    } else {
        els.pdfDownload.classList.add('hidden');
        els.runPremiumOnly.classList.add('hidden');
        els.resultContent.textContent = JSON.stringify(data, null, 2);
    }

    els.result.classList.remove('hidden');
}

function renderError(error) {
    els.pdfDownload.classList.add('hidden');
    els.runPremiumOnly.classList.add('hidden');
    els.resultContent.textContent = 'Error: ' + error.message;
    els.result.classList.remove('hidden');
}

function buildQueryUrl({ type, query, premium = false, premiumModulesOnly = false }) {
    const params = new URLSearchParams({
        type: type.toLowerCase(),
        query,
        premium: String(premium),
        premium_modules_only: String(premiumModulesOnly),
        format: els.pdfFormat.checked ? 'pdf' : 'json',
    });

    return `/api/oi/query?${params.toString()}`;
}

function getSearchMode() {
    return els.searchModeValue.value || 'standard';
}

function getPremiumFlags(mode) {
    return {
        premium: mode === 'premium' || mode === 'premium_only',
        premiumModulesOnly: mode === 'premium_only',
    };
}

async function runOiQuery({ type, query, premium = false, premiumModulesOnly = false }) {
    const response = await fetch(buildQueryUrl({ type, query, premium, premiumModulesOnly }));
    const data = await response.json();

    if (!response.ok) {
        throw new Error(data.detail || 'Request failed');
    }

    return data;
}

async function updateCredits() {
    try {
        const response = await fetch('/api/oi/credits');
        if (!response.ok) throw new Error('Network response was not ok');
        const data = await response.json();
        els.credits.textContent = `${data.credits} credits left.`;
    } catch (error) {
        els.credits.textContent = 'Error loading credits: ' + error.message;
    }
}

async function submitBaseReport() {
    const type = els.queryType.value;
    const query = els.queryInput.value.trim();
    const searchMode = getSearchMode();
    const premiumFlags = getPremiumFlags(searchMode);

    if (!query) {
        alert('Please enter a query');
        return;
    }

    state.lastReport = { type, query, searchMode };
    els.result.classList.add('hidden');
    els.runPremiumOnly.classList.add('hidden');
    setBusy(true);

    try {
        const data = await runOiQuery({
            type,
            query,
            ...premiumFlags,
        });

        renderResult(data, {
            allowPremiumOnly: searchMode === 'standard',
            message: searchMode === 'premium_only'
                ? 'Premium-only PDF report generated successfully'
                : 'PDF report generated successfully',
        });
        await updateCredits();
    } catch (error) {
        state.lastReport = null;
        renderError(error);
    } finally {
        setBusy(false);
    }
}

async function submitPremiumOnlyReport() {
    if (!state.lastReport) return;

    setBusy(true);

    try {
        const data = await runOiQuery({
            type: state.lastReport.type,
            query: state.lastReport.query,
            premium: true,
            premiumModulesOnly: true,
        });

        renderResult(data, {
            allowPremiumOnly: false,
            message: 'Premium-only PDF report generated successfully',
        });
        await updateCredits();
    } catch (error) {
        renderError(error);
    } finally {
        setBusy(false);
    }
}

function setActiveTypeButton(activeButton) {
    els.queryTypeBtns.forEach((button) => button.classList.toggle('active', button === activeButton));
}

function setActiveSearchMode(activeButton) {
    els.searchModeValue.value = activeButton.dataset.mode;
    els.searchModeBtns.forEach((button) => button.classList.toggle('active', button === activeButton));
}

els.submitQuery.addEventListener('click', submitBaseReport);
els.runPremiumOnly.addEventListener('click', submitPremiumOnlyReport);
els.queryInput.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') submitBaseReport();
});

els.queryTypeBtns.forEach((button) => {
    button.addEventListener('click', () => {
        setActiveTypeButton(button);
        els.queryType.value = button.dataset.type;
        els.queryInput.placeholder = `Enter ${button.dataset.type}...`;
    });
});

els.searchModeBtns.forEach((button) => {
    button.addEventListener('click', () => setActiveSearchMode(button));
});

setActiveTypeButton(els.queryTypeBtns[0]);
setActiveSearchMode(els.searchModeBtns[0]);
updateCredits();
lucide.createIcons();
