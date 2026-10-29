window.currentService = 'oi';

const state = {
    lastReport: null,
    isRunning: false,
    controller: null,
    view: null,
};

const els = {
    credits: document.getElementById('credits'),
    queryType: document.getElementById('queryType'),
    queryInput: document.getElementById('queryInput'),
    submitQuery: document.getElementById('submitQuery'),
    stopQuery: document.getElementById('stopQuery'),
    runPremiumOnly: document.getElementById('runPremiumOnly'),
    status: document.getElementById('oiStatus'),
    statusIcon: document.getElementById('oiStatusIcon'),
    statusText: document.getElementById('oiStatusText'),
    error: document.getElementById('oiError'),
    result: document.getElementById('result'),
    cards: document.getElementById('oiCards'),
    pdfFormat: document.getElementById('pdfFormat'),
    sandbox: document.getElementById('sandboxMode'),
    pdfDownload: document.getElementById('pdfDownload'),
    pdfLink: document.getElementById('pdfLink'),
    queryTypeBtns: document.querySelectorAll('.query-type-btn'),
    searchModeValue: document.getElementById('searchModeValue'),
    searchModeBtns: document.querySelectorAll('.search-mode-btn'),
};

window.loadResultIntoView = function (data) {
    resetResult();
    if (data && data.url) {
        showPdf(data.url);
    } else if (data && Array.isArray(data.modules)) {
        state.view.add(data.modules);
        if (data.modules_checked != null) state.view.setSites(data.modules_checked);
        const { accounts, breaches } = state.view.counts();
        setStatus('done', `Saved result${data.query ? ` for ${data.query}` : ''}: ${summaryText(accounts, breaches)}`);
        if (data.error) showError(data.error);
    }
    els.result.classList.remove('hidden');
};

function setBusy(isBusy) {
    state.isRunning = isBusy;
    els.submitQuery.disabled = isBusy;
    els.runPremiumOnly.disabled = isBusy;
    els.stopQuery.classList.toggle('hidden', !isBusy);
    els.searchModeBtns.forEach((button) => {
        button.disabled = isBusy;
    });
}

function summaryText(accounts, breaches) {
    const parts = [`${accounts} account${accounts === 1 ? '' : 's'}`];
    if (breaches) parts.push(`${breaches} breach${breaches === 1 ? '' : 'es'}`);
    return parts.join(', ');
}

function setStatus(kind, text) {
    els.status.classList.remove('hidden');
    els.statusIcon.innerHTML = kind === 'running'
        ? '<span class="block w-2.5 h-2.5 rounded-full bg-purple-400 animate-pulse"></span>'
        : `<i data-lucide="${kind === 'done' ? 'check-circle-2' : 'circle-alert'}" class="w-4 h-4 ${kind === 'done' ? 'text-emerald-400' : 'text-amber-400'}"></i>`;
    els.statusText.textContent = text;
    lucide.createIcons();
}

function showError(message) {
    els.error.textContent = message;
    els.error.classList.remove('hidden');
}

function resetResult() {
    els.error.classList.add('hidden');
    els.pdfDownload.classList.add('hidden');
    els.runPremiumOnly.classList.add('hidden');
    els.pdfLink.classList.add('hidden');
    els.status.classList.add('hidden');
    state.view = new OiResultsView(els.cards);
}

function showPdf(url) {
    els.pdfLink.href = url;
    els.pdfLink.classList.remove('hidden');
    els.pdfDownload.classList.remove('hidden');
    setStatus('done', 'PDF report generated');
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

// Reads the SSE stream from /api/oi/stream and adds each module's cards as it arrives
async function streamOi({ type, query, premium, premiumModulesOnly, sandbox }) {
    const params = new URLSearchParams({ type, query });
    if (!sandbox) {
        params.set('premium', String(premium));
        params.set('premium_modules_only', String(premiumModulesOnly));
    }
    state.controller = new AbortController();
    const started = Date.now();
    let modules = 0;
    let finished = false;
    const progress = () => {
        const { accounts, breaches } = state.view.counts();
        setStatus('running', `Searching${sandbox ? ' the sandbox' : ''}… ${modules} sites answered, ${summaryText(accounts, breaches)} so far`);
    };
    progress();

    const handle = (event) => {
        if (event.event === 'module') {
            modules += 1;
            state.view.add(event.cards);
            state.view.setSites(modules);
            progress();
        } else if (event.event === 'error') {
            showError(event.detail || 'OSINT Industries request failed');
        } else if (event.event === 'done') {
            finished = true;
        }
    };

    try {
        const response = await fetch(`/api/oi/${sandbox ? 'sandbox/' : ''}stream?${params}`, { signal: state.controller.signal });
        if (!response.ok) {
            const data = await response.json().catch(() => ({}));
            const detail = Array.isArray(data.detail) ? data.detail.map(d => d.msg).join(', ') : data.detail;
            throw new Error(detail || `Request failed (${response.status})`);
        }
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        for (;;) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const blocks = buffer.split('\n\n');
            buffer = blocks.pop();
            for (const block of blocks) {
                const data = block.split('\n').filter(l => l.startsWith('data:')).map(l => l.slice(5).trimStart()).join('\n');
                if (!data) continue;
                try {
                    handle(JSON.parse(data));
                } catch (e) {
                    console.error('Bad OSINT Industries event', e);
                }
            }
        }
    } catch (error) {
        if (error.name !== 'AbortError') showError(error.message);
    } finally {
        state.controller = null;
    }

    const { accounts, breaches } = state.view.counts();
    const seconds = Math.round((Date.now() - started) / 1000);
    if (finished) {
        setStatus('done', `${summaryText(accounts, breaches)} · ${modules} sites answered in ${seconds}s`);
    } else {
        setStatus('stopped', `Stopped after ${seconds}s · ${summaryText(accounts, breaches)}`);
    }
}

async function runPdfReport({ type, query, premium, premiumModulesOnly }) {
    const params = new URLSearchParams({
        type,
        query,
        premium: String(premium),
        premium_modules_only: String(premiumModulesOnly),
        format: 'pdf',
    });
    setStatus('running', 'Generating the PDF report - usually under a minute…');
    const response = await fetch(`/api/oi/query?${params}`);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || 'Request failed');
    showPdf(data.url);
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
    const sandbox = els.sandbox.checked;

    if (!query) {
        els.queryInput.focus();
        return;
    }
    if (state.isRunning) return;

    state.lastReport = { type, query, searchMode, sandbox };
    resetResult();
    els.result.classList.remove('hidden');
    setBusy(true);

    try {
        const request = { type, query, sandbox, ...getPremiumFlags(searchMode) };
        if (els.pdfFormat.checked && !sandbox) {
            await runPdfReport(request);
        } else {
            await streamOi(request);
            els.runPremiumOnly.classList.toggle('hidden', searchMode !== 'standard' || sandbox);
        }
        if (!sandbox) await updateCredits();
    } catch (error) {
        state.lastReport = null;
        showError(error.message);
        els.status.classList.add('hidden');
    } finally {
        setBusy(false);
    }
}

// After a standard search: run only the premium modules and add them to the same results
async function submitPremiumOnlyReport() {
    if (!state.lastReport || state.isRunning) return;
    els.runPremiumOnly.classList.add('hidden');
    setBusy(true);
    try {
        await streamOi({ type: state.lastReport.type, query: state.lastReport.query, premium: true, premiumModulesOnly: true, sandbox: false });
        await updateCredits();
    } catch (error) {
        showError(error.message);
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
els.stopQuery.addEventListener('click', () => state.controller?.abort());
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
