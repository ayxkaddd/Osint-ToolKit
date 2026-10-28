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

function oiCard(card) {
    const picture = safeUrl(card.picture);
    const profile = safeUrl(card.profile_url);
    const chips = [
        card.username ? pivotChip('username', String(card.username)) : '',
        card.email ? pivotChip('email', String(card.email)) : '',
        card.phone ? pivotChip('phone', String(card.phone)) : '',
    ].join('');
    const meta = [card.location, card.created && `created ${card.created}`, card.last_seen && `last seen ${card.last_seen}`]
        .filter(Boolean).map(v => escapeHtml(v)).join(' · ');
    return `
        <div class="bg-gray-950/60 rounded-lg p-4 border border-gray-800 min-w-0">
            <div class="flex items-start gap-3">
                ${picture ? `<img src="${escapeAttr(picture)}" alt="" loading="lazy" referrerpolicy="no-referrer" class="w-12 h-12 rounded-lg object-cover bg-gray-800 shrink-0" onerror="this.remove()">` : ''}
                <div class="min-w-0 flex-1">
                    <div class="flex items-center justify-between gap-2">
                        <span class="text-xs uppercase tracking-wide text-purple-300">${escapeHtml(card.module)}</span>
                        ${profile ? `<a href="${escapeAttr(profile)}" target="_blank" rel="noopener noreferrer" class="text-xs text-blue-400 hover:underline">profile</a>` : ''}
                    </div>
                    ${card.name ? `<div class="text-white font-medium truncate">${escapeHtml(card.name)}</div>` : ''}
                    ${meta ? `<div class="text-xs text-gray-500 mt-0.5">${meta}</div>` : ''}
                </div>
            </div>
            ${chips ? `<div class="flex flex-wrap gap-1.5 mt-2">${chips}</div>` : ''}
            ${card.bio ? `<p class="text-xs text-gray-400 mt-2">${escapeHtml(card.bio)}</p>` : ''}
            ${(card.fields || []).length ? `<div class="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-xs">${card.fields.slice(0, 12).map(f =>
                `<div class="text-gray-500 truncate">${escapeHtml(f.label)}</div><div class="text-gray-300 break-words">${escapeHtml(f.value)}</div>`).join('')}</div>` : ''}
        </div>`;
}

function renderResult(data, options = {}) {
    const allowPremiumOnly = Boolean(options.allowPremiumOnly && state.lastReport);
    els.cards.classList.add('hidden');

    if (Array.isArray(data.modules)) {
        // Only the "run premium modules" follow-up applies; there is no PDF to link
        els.pdfLink.classList.add('hidden');
        els.pdfDownload.classList.toggle('hidden', !allowPremiumOnly);
        els.runPremiumOnly.classList.toggle('hidden', !allowPremiumOnly);
        const found = data.modules.filter(m => m.registered !== false);
        els.resultContent.textContent = '';
        els.cards.innerHTML = `
            <div class="flex items-center justify-between gap-3 flex-wrap mb-4">
                <div class="text-sm text-gray-300">${found.length} account${found.length === 1 ? '' : 's'} for <span class="text-white">${escapeHtml(data.query || '')}</span></div>
            </div>
            ${found.length ? `<div class="grid grid-cols-1 md:grid-cols-2 gap-3">${found.map(oiCard).join('')}</div>`
                : '<p class="text-sm text-gray-400">No accounts found.</p>'}`;
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
