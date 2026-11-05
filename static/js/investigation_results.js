// investigation_results.js - one investigation's timeline.
// Summaries are listed up front; a result's payload is fetched only when its
// card is expanded (results can be large), then cached.

let currentInvestigation = null;
let allResults = []; // summaries from /results
const detailCache = {}; // result_id -> full record
const openCards = new Set();
const selectedResults = new Set(); // ticked for bulk delete / move / assessment
// Notes opened on this page (Ctrl+K) belong to this investigation, recording or not
window.notesForInvestigation = investigationId;
// Identifiers on this page are this investigation's: badges count the others (main.js)
window.pageInvestigationId = investigationId;

const TRIAGE = {
    confirmed: {
        label: 'Confirmed',
        cls: 'bg-emerald-900/50 text-emerald-300 border-emerald-700/60',
        icon: 'fa-check-circle',
    },
    important: { label: 'Important', cls: 'bg-amber-900/50 text-amber-300 border-amber-700/60', icon: 'fa-star' },
    false_positive: {
        label: 'False positive',
        cls: 'bg-gray-800 text-gray-400 border-gray-700',
        icon: 'fa-times-circle',
    },
};

function triageBadge(status) {
    const t = TRIAGE[status];
    return t
        ? `<span class="text-[10px] uppercase px-1.5 py-0.5 rounded border ${t.cls}"><i class="fas ${t.icon} mr-1"></i>${t.label}</span>`
        : '';
}

document.addEventListener('DOMContentLoaded', () => {
    loadInvestigationData();
    document.getElementById('timelineSearchInput')?.addEventListener('input', debounce(renderResults, 150));
    document.getElementById('moduleFilterSelect')?.addEventListener('change', renderResults);
    document.getElementById('sortSelect')?.addEventListener('change', renderResults);
    document.getElementById('triageFilterSelect')?.addEventListener('change', renderResults);
    document.getElementById('resultsContainer').addEventListener('click', onResultsClick);
    document.getElementById('resultsContainer').addEventListener('contextmenu', onResultContextMenu);
    document.getElementById('bulkSelectAll').addEventListener('change', (e) => {
        selectedResults.clear();
        if (e.target.checked) filteredResults().forEach((r) => selectedResults.add(r.result_id));
        document.querySelectorAll('[data-action="select"]').forEach((box) => {
            box.checked = e.target.checked;
        });
        updateBulkBar();
    });
    document.querySelectorAll('[data-bulk-triage]').forEach((button) =>
        button.addEventListener('click', () => {
            bulkSetTriage(button.dataset.bulkTriage || null);
        })
    );
    document.getElementById('bulkMove').addEventListener('click', () => openMoveModal([...selectedResults]));
    document.getElementById('bulkDelete').addEventListener('click', bulkDelete);
    document.getElementById('resultsContainer').addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && e.target.matches('[data-triage-note]')) {
            e.preventDefault();
            saveResultTriage(e.target.closest('[data-result-id]').dataset.resultId, undefined);
        }
    });
    document
        .querySelectorAll('[data-tab]')
        .forEach((tab) => tab.addEventListener('click', () => switchTab(tab.dataset.tab)));
    setupEntitiesPanel();
    setupEventsPanel();
    setupManualModal();
    // Links from other investigations' pivot menus: ?identifier=<value>#identifiers
    const identifier = new URLSearchParams(location.search).get('identifier');
    if (identifier) {
        document.getElementById('entitySearchInput').value = identifier;
        entityState.q = identifier;
    }
    if (location.hash === '#identifiers') switchTab('entities');
    else if (location.hash === '#events') switchTab('events');
    window.addEventListener('hashchange', openLinkedResult);
});

function switchTab(name) {
    document.querySelectorAll('[data-tab]').forEach((t) => t.classList.toggle('active', t.dataset.tab === name));
    document.getElementById('timelinePanel').classList.toggle('hidden', name !== 'timeline');
    document.getElementById('eventsPanel').classList.toggle('hidden', name !== 'events');
    document.getElementById('entitiesPanel').classList.toggle('hidden', name !== 'entities');
    const hash = { entities: '#identifiers', events: '#events' }[name] || '';
    history.replaceState(null, '', location.pathname + location.search + hash);
    if (name === 'entities' && !entityState.loaded) loadEntities(true);
    if (name === 'events' && !eventState.loaded) loadEvents();
}

function debounce(fn, ms) {
    let t;
    return (...args) => {
        clearTimeout(t);
        t = setTimeout(() => fn(...args), ms);
    };
}

async function loadInvestigationData() {
    try {
        const [infoResponse, resultsResponse] = await Promise.all([
            fetch(`/api/investigations/${investigationId}/info`),
            fetch(`/api/investigations/${investigationId}/results`),
        ]);
        if (infoResponse.status === 404) {
            document.getElementById('loadingResults').innerHTML =
                '<p class="text-gray-400">This investigation no longer exists.</p>';
            return;
        }
        if (!infoResponse.ok || !resultsResponse.ok)
            throw new Error(`HTTP ${infoResponse.ok ? resultsResponse.status : infoResponse.status}`);
        const infoData = await infoResponse.json();
        currentInvestigation = infoData.investigation;
        renderHeader(currentInvestigation);

        const resultsData = await resultsResponse.json();
        allResults = resultsData.results || [];
        document.getElementById('loadingResults').classList.add('hidden');
        populateModuleFilterOptions();
        renderResults();
        openLinkedResult();
    } catch (error) {
        console.error('Error loading investigation data:', error);
        document.getElementById('loadingResults').innerHTML =
            `<p class="text-red-400">Failed to load investigation: ${escapeHtml(error.message)}</p>`;
    }
}

// Links from notes: /api/investigations/<id>/view#result-<result_id>
function openLinkedResult() {
    const match = /^#result-(.+)$/.exec(location.hash);
    if (!match) return;
    const id = decodeURIComponent(match[1]);
    if (!allResults.some((r) => r.result_id === id)) {
        showTemporaryNotification('That result is no longer in this investigation', 'error');
        return;
    }
    switchTab('timeline');
    history.replaceState(null, '', `#result-${encodeURIComponent(id)}`);
    if (!document.querySelector(`[data-result-id="${CSS.escape(id)}"]`)) {
        ['timelineSearchInput'].forEach((i) => {
            const el = document.getElementById(i);
            if (el) el.value = '';
        });
        ['moduleFilterSelect', 'triageFilterSelect'].forEach((i) => {
            const el = document.getElementById(i);
            if (el) el.selectedIndex = 0;
        });
        renderResults();
    }
    const card = document.querySelector(`[data-result-id="${CSS.escape(id)}"]`);
    if (!card) return;
    card.classList.add('ring-2', 'ring-purple-500/60');
    setTimeout(() => card.classList.remove('ring-2', 'ring-purple-500/60'), 2500);
    return expandCard(id, true).then(() => card.scrollIntoView({ block: 'start', behavior: 'smooth' }));
}

// Open a result and point at an identifier in it (from the Identifiers tab)
async function openResultAt(resultId, type, value) {
    history.replaceState(null, '', `#result-${encodeURIComponent(resultId)}`);
    await openLinkedResult();
    const card = document.querySelector(`[data-result-id="${CSS.escape(resultId)}"]`);
    if (!card) return;
    const comparable = (v) =>
        type === 'phone' ? String(v).replace(/\D/g, '') : String(v).trim().replace(/^@/, '').toLowerCase();
    const wanted = comparable(value);
    const find = (inEntities) =>
        [...card.querySelectorAll('[data-pivot-value]')].find(
            (chip) =>
                Boolean(chip.closest('.result-entities')) === inEntities &&
                comparable(chip.dataset.pivotValue) === wanted
        );
    // where the result itself shows it, else its "Identifiers in this result" list (loaded a moment later)
    let chip = find(false);
    for (let i = 0; !chip && i < 20; i++) {
        await new Promise((resolve) => setTimeout(resolve, 100));
        chip = find(false) || find(true);
    }
    if (!chip) return;
    chip.closest('details')?.setAttribute('open', '');
    chip.scrollIntoView({ block: 'center', behavior: 'smooth' });
    chip.classList.add('ring-2', 'ring-amber-400');
    setTimeout(() => chip.classList.remove('ring-2', 'ring-amber-400'), 3000);
}

// ----------------- HEADER -----------------

function renderHeader(investigation) {
    const header = document.getElementById('investigationHeader');
    const isCurrent =
        window.getCurrentInvestigationId && window.getCurrentInvestigationId() === investigation.investigation_id;
    const statusColors = {
        active: 'bg-emerald-950/80 text-emerald-300 border-emerald-700/60',
        completed: 'bg-blue-950/80 text-blue-300 border-blue-700/60',
        archived: 'bg-gray-800 text-gray-400 border-gray-700',
    };
    const fmt = (iso) => (iso ? new Date(iso).toLocaleString() : '—');

    header.innerHTML = `
        <div class="flex flex-col lg:flex-row items-start lg:items-center justify-between gap-6">
            <div class="flex items-start gap-5 min-w-0">
                ${
                    investigation.picture_url
                        ? `<img src="${escapeAttr(investigation.picture_url)}" alt="" data-image-view="" data-image-title="${escapeAttr(investigation.name)}" data-image-note="Investigation picture" class="w-20 h-20 rounded-2xl object-cover border border-gray-700 shrink-0">`
                        : `<div class="w-20 h-20 rounded-2xl bg-purple-950/40 border border-purple-800/60 flex items-center justify-center shrink-0"><i data-lucide="folder-open" class="w-9 h-9 text-purple-400"></i></div>`
                }
                <div class="min-w-0">
                    <div class="flex items-center gap-2 flex-wrap mb-1">
                        <h1 class="text-2xl font-bold text-white truncate">${escapeHtml(investigation.name || 'Untitled Case')}</h1>
                        <span class="px-2 py-0.5 rounded-full text-xs font-semibold border ${statusColors[investigation.status] || statusColors.archived}">${escapeHtml(investigation.status || 'active')}</span>
                        ${isCurrent ? '<span class="px-2 py-0.5 rounded-full text-xs font-semibold border border-red-700/60 bg-red-950/60 text-red-300 flex items-center gap-1.5"><span class="rec-dot"></span>Recording</span>' : ''}
                    </div>
                    <p class="text-gray-400 text-sm max-w-2xl leading-relaxed whitespace-pre-line">${escapeHtml(investigation.description || 'No description provided.')}</p>
                    <div class="flex flex-wrap gap-x-5 gap-y-1 mt-3 text-xs text-gray-500">
                        <span><i data-lucide="layers" class="w-3.5 h-3.5 inline mr-1"></i>${escapeHtml(investigation.results_count || 0)} results</span>
                        <span><i data-lucide="sticky-note" class="w-3.5 h-3.5 inline mr-1"></i>${escapeHtml(investigation.notes_count || 0)} notes</span>
                        <span><i data-lucide="calendar" class="w-3.5 h-3.5 inline mr-1"></i>Created ${escapeHtml(fmt(investigation.created_at))}</span>
                        <span><i data-lucide="clock" class="w-3.5 h-3.5 inline mr-1"></i>Updated ${escapeHtml(fmt(investigation.updated_at))}</span>
                        ${sharedStatHtml()}
                    </div>
                </div>
            </div>
            <div class="flex flex-wrap gap-2 shrink-0">
                ${isCurrent ? '' : `<button type="button" onclick="setThisInvestigationAsActive()" class="px-3 py-2 bg-purple-600 hover:bg-purple-500 text-white rounded-lg text-sm font-medium flex items-center gap-1.5"><i data-lucide="radio" class="w-4 h-4"></i>Record here</button>`}
                <a href="/api/investigations/${escapeAttr(investigation.investigation_id)}/notes/view" class="px-3 py-2 bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-lg text-sm flex items-center gap-1.5"><i data-lucide="sticky-note" class="w-4 h-4"></i>Notes</a>
                <button type="button" onclick="openEditModal()" class="px-3 py-2 bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-lg text-sm flex items-center gap-1.5"><i data-lucide="pencil" class="w-4 h-4"></i>Edit</button>
                <a href="/api/investigations/${escapeAttr(investigation.investigation_id)}/report" target="_blank" class="px-3 py-2 bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-lg text-sm flex items-center gap-1.5"><i data-lucide="file-text" class="w-4 h-4"></i>Report</a>
                <button type="button" onclick="exportResults()" class="px-3 py-2 bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-lg text-sm flex items-center gap-1.5"><i data-lucide="download" class="w-4 h-4"></i>Export</button>
                <button type="button" onclick="deleteInvestigation()" class="px-3 py-2 bg-gray-800 hover:bg-red-900/60 border border-gray-700 hover:border-red-700 text-gray-300 hover:text-red-200 rounded-lg text-sm flex items-center gap-1.5"><i data-lucide="trash-2" class="w-4 h-4"></i>Delete</button>
            </div>
        </div>
    `;
    document.getElementById('headerSkeleton').classList.add('hidden');
    header.classList.remove('hidden');
    refreshIcons();
}

// ----------------- TIMELINE -----------------

function populateModuleFilterOptions() {
    const select = document.getElementById('moduleFilterSelect');
    if (!select) return;
    const counts = {};
    allResults.forEach((r) => {
        counts[r.service_name] = (counts[r.service_name] || 0) + 1;
    });
    select.innerHTML =
        '<option value="all">All modules</option>' +
        Object.keys(counts)
            .sort()
            .map((s) => `<option value="${escapeAttr(s)}">${escapeHtml(moduleInfo(s).name)} (${counts[s]})</option>`)
            .join('');
}

function filteredResults() {
    const search = (document.getElementById('timelineSearchInput')?.value || '').toLowerCase().trim();
    const service = document.getElementById('moduleFilterSelect')?.value || 'all';
    const sort = document.getElementById('sortSelect')?.value || 'newest';
    const triage = document.getElementById('triageFilterSelect')?.value || 'all';

    const list = allResults.filter((r) => {
        if (service !== 'all' && r.service_name !== service) return false;
        const status = (r.triage || {}).status || null;
        if (triage === 'marked' && !['confirmed', 'important'].includes(status)) return false;
        if (['confirmed', 'important'].includes(triage) && status !== triage) return false;
        if (triage === 'untriaged' && status) return false;
        if (triage === 'hide_fp' && status === 'false_positive') return false;
        if (!search) return true;
        const haystack = [
            r.target,
            r.summary,
            r.service_name,
            r.method_name,
            moduleInfo(r.service_name).name,
            JSON.stringify(r.parameters || {}),
            (r.triage || {}).note || '',
            ...(r.children || []).map((c) => `${c.method_name} ${c.target || ''} ${c.summary || ''}`),
        ]
            .join(' ')
            .toLowerCase();
        return haystack.includes(search);
    });
    list.sort((a, b) =>
        sort === 'oldest'
            ? (a.timestamp || '').localeCompare(b.timestamp || '')
            : (b.timestamp || '').localeCompare(a.timestamp || '')
    );
    return list;
}

function dayLabel(iso) {
    const d = new Date(iso);
    if (isNaN(d)) return 'Unknown date';
    const today = new Date();
    const yesterday = new Date(today.getTime() - 86400000);
    if (d.toDateString() === today.toDateString()) return 'Today';
    if (d.toDateString() === yesterday.toDateString()) return 'Yesterday';
    return d.toLocaleDateString(undefined, { weekday: 'short', year: 'numeric', month: 'short', day: 'numeric' });
}

function renderResults() {
    const container = document.getElementById('resultsContainer');
    const results = filteredResults();
    // Only what's on screen stays selected, so a filter can't hide what a bulk action touches
    const shown = new Set(results.map((r) => r.result_id));
    [...selectedResults].forEach((id) => {
        if (!shown.has(id)) selectedResults.delete(id);
    });
    updateBulkBar(results.length);
    const badge = document.getElementById('resultsCountBadge');
    if (badge) {
        badge.textContent =
            results.length === allResults.length ? allResults.length : `${results.length} / ${allResults.length}`;
        badge.classList.remove('hidden');
    }
    document.getElementById('noResults').classList.toggle('hidden', results.length > 0);
    document.getElementById('noResultsTitle').textContent = allResults.length
        ? 'Nothing matches the filter'
        : 'No results recorded yet';

    let lastDay = null;
    container.innerHTML = results
        .map((r) => {
            const day = dayLabel(r.timestamp);
            const heading =
                day !== lastDay
                    ? `<h3 class="text-xs font-semibold uppercase tracking-wider text-gray-500 pt-4 pb-1">${escapeHtml(day)}</h3>`
                    : '';
            lastDay = day;
            return heading + renderCard(r);
        })
        .join('');

    // Re-render cards that were open before filtering
    openCards.forEach((id) => {
        if (results.some((r) => r.result_id === id)) expandCard(id, true);
    });
    refreshIcons();
}

function updateBulkBar(shownCount = filteredResults().length) {
    const count = selectedResults.size;
    document.getElementById('bulkBar').classList.toggle('hidden', !shownCount);
    document.getElementById('bulkActions').classList.toggle('hidden', !count);
    document.getElementById('bulkCount').textContent = count ? `${count} selected` : 'Select all';
    const all = document.getElementById('bulkSelectAll');
    all.checked = count > 0 && count === shownCount;
    all.indeterminate = count > 0 && count < shownCount;
}

function renderCard(r) {
    const info = moduleInfo(r.service_name);
    const time = r.timestamp
        ? new Date(r.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        : '';
    const children = r.children || [];
    const id = escapeAttr(r.result_id);

    return `
        <div class="result-card inv-result-card bg-[#14151f] border border-[#24283b] rounded-xl overflow-hidden hover:border-purple-500/40 ${(r.triage || {}).status === 'false_positive' ? 'opacity-60' : ''}" data-result-id="${id}">
            <div class="p-4 flex items-center justify-between gap-3 cursor-pointer select-none" data-action="toggle" title="Click to open, right-click for actions">
                <div class="flex items-center gap-3 min-w-0">
                    <label data-action="none" title="Select this result" class="self-stretch shrink-0 flex items-center -my-4 -ml-4 pl-4 pr-3 cursor-pointer hover:bg-purple-500/10">
                        <input type="checkbox" data-action="select" ${selectedResults.has(r.result_id) ? 'checked' : ''} aria-label="Select this result" class="pick-box">
                    </label>
                    <div class="p-2.5 rounded-xl bg-purple-950/50 border border-purple-800/40 text-purple-400 shrink-0">
                        <i data-lucide="${escapeAttr(info.icon)}" class="w-5 h-5"></i>
                    </div>
                    <div class="min-w-0">
                        <div class="flex items-center gap-2 flex-wrap">
                            <span class="font-bold text-white">${escapeHtml(info.name)}</span>
                            <span class="text-xs text-gray-500">${escapeHtml(methodLabel(r.method_name))}</span>
                            ${r.partial ? '<span class="text-[10px] uppercase px-1.5 py-0.5 rounded bg-yellow-900/60 text-yellow-300" title="The search was stopped before it finished">partial</span>' : ''}
                            ${triageBadge((r.triage || {}).status)}
                        </div>
                        ${(r.triage || {}).note ? `<div class="text-xs text-amber-200/80 mt-0.5 truncate"><i class="fas fa-sticky-note mr-1"></i>${escapeHtml(r.triage.note)}</div>` : ''}
                        <div class="text-sm text-gray-300 truncate mt-0.5">
                            ${r.target ? `<span class="font-mono text-purple-200">${escapeHtml(r.target)}</span><span class="text-gray-600"> · </span>` : ''}${escapeHtml(r.summary || '')}
                        </div>
                        ${
                            children.length
                                ? `<div class="flex flex-wrap gap-1.5 mt-1.5">${children
                                      .map(
                                          (c) =>
                                              `<span class="text-[11px] px-1.5 py-0.5 rounded bg-gray-800 text-gray-300 border border-gray-700">${escapeHtml(partTitle(c, c.target))}${c.summary ? ` · ${escapeHtml(c.summary)}` : ''}</span>`
                                      )
                                      .join('')}</div>`
                                : ''
                        }
                    </div>
                </div>
                <div class="flex items-center gap-3 shrink-0">
                    <span class="text-xs text-gray-500 hidden sm:inline">${escapeHtml(time)}</span>
                    <i data-lucide="chevron-down" class="w-5 h-5 text-gray-400 chevron"></i>
                </div>
            </div>
            <div class="result-body hidden border-t border-gray-800/80 bg-gray-950/40"></div>
        </div>
    `;
}

function onResultsClick(event) {
    const card = event.target.closest('[data-result-id]');
    if (!card) return;
    const id = card.dataset.resultId;
    const action = event.target.closest('[data-action]')?.dataset.action;

    if (action === 'select') {
        if (event.target.checked) selectedResults.add(id);
        else selectedResults.delete(id);
        updateBulkBar();
    } else if (action === 'toggle') {
        if (openCards.has(id)) collapseCard(id);
        else expandCard(id);
    } else if (action === 'copy-json') {
        const record = detailCache[id];
        if (record)
            copyTextToClipboard(JSON.stringify(record, null, 2)).then((ok) =>
                showTemporaryNotification(ok ? 'Result JSON copied' : 'Copy failed', ok ? 'success' : 'error')
            );
    } else if (action === 'note-link' || action === 'note-attach') {
        window.addResultToNote(id, { snapshot: action === 'note-attach' }).then(() => loadResultReferences(id));
    } else if (action === 'manual-add') {
        openManualModal(id);
    } else if (action === 'delete-result') {
        deleteResult(id);
    } else if (action === 'move-result') {
        openMoveModal([id]);
    } else if (action === 'triage') {
        const status = event.target.closest('[data-triage-status]').dataset.triageStatus || null;
        const current = ((detailCache[id] || {}).triage || {}).status || null;
        saveResultTriage(id, current === status ? null : status);
    } else if (action === 'triage-note') {
        saveResultTriage(id, undefined);
    } else if (action === 'raw-json') {
        const target = event.target.closest('details');
        const pre = target && target.querySelector('pre');
        if (pre && !pre.dataset.filled) {
            const path = target.dataset.path;
            const record = detailCache[id];
            const value = path === 'record' ? record.result : (record.children || [])[Number(path)]?.result;
            pre.textContent = JSON.stringify(value, null, 2);
            pre.dataset.filled = '1';
        }
    }
}

// Right-click on a result's header row: its actions without opening it.
// Inside an open result the browser's own menu stays (links, selected text).
function onResultContextMenu(event) {
    const header = event.target.closest('[data-action="toggle"]');
    if (!header || event.target.closest('a, [data-pivot-type]')) return;
    const id = header.closest('[data-result-id]').dataset.resultId;
    const summary = allResults.find((r) => r.result_id === id);
    if (!summary) return;
    event.preventDefault();
    const info = moduleInfo(summary.service_name);
    const status = (summary.triage || {}).status || null;
    const triage = (value) => ({
        label: TRIAGE[value].label,
        icon: TRIAGE[value].icon,
        checked: status === value,
        onClick: () => setResultStatus(id, status === value ? null : value),
    });
    const items = [
        {
            label: openCards.has(id) ? 'Close' : 'Open',
            icon: openCards.has(id) ? 'fa-chevron-up' : 'fa-chevron-down',
            onClick: () => (openCards.has(id) ? collapseCard(id) : expandCard(id)),
        },
        info.page && summary.service_name !== 'sharetrace'
            ? {
                  label: `Open in ${info.name}`,
                  icon: 'fa-external-link-alt',
                  href: `${info.page}?load_result=${encodeURIComponent(id)}&investigation=${encodeURIComponent(investigationId)}`,
              }
            : null,
        { divider: true },
        triage('confirmed'),
        triage('important'),
        triage('false_positive'),
        { divider: true },
        { label: 'Link in note', icon: 'fa-link', onClick: () => window.addResultToNote(id, { snapshot: false }) },
        {
            label: 'Attach to note',
            icon: 'fa-paperclip',
            onClick: () => window.addResultToNote(id, { snapshot: true }),
        },
        { label: 'Add to this (file, text)', icon: 'fa-upload', onClick: () => openManualModal(id) },
        { label: 'Copy JSON', icon: 'fa-copy', onClick: () => copyResultJson(id) },
        {
            label: selectedResults.has(id) ? 'Unselect' : 'Select',
            icon: 'fa-check-square',
            onClick: () => toggleSelected(id),
        },
        { divider: true },
        { label: 'Move', icon: 'fa-folder-open', onClick: () => openMoveModal([id]) },
        { label: 'Delete', icon: 'fa-trash', danger: true, onClick: () => deleteResult(id) },
    ].filter(Boolean);
    openContextMenu(event, items, `${info.name}${summary.target ? ` · ${summary.target}` : ''}`, header);
}

// Assessment from the menu: keeps the result's note (the card may be closed)
async function setResultStatus(id, status) {
    try {
        const { done, triage } = await bulkRequest({ action: 'triage', result_ids: [id], status });
        done.forEach((rid) => {
            if (detailCache[rid]) detailCache[rid].triage = triage[rid];
            const summary = allResults.find((r) => r.result_id === rid);
            if (summary) summary.triage = triage[rid];
        });
        renderResults();
        showTemporaryNotification('Assessment saved', 'success');
    } catch (e) {
        showTemporaryNotification(`Failed to save assessment: ${e.message}`, 'error');
    }
}

async function copyResultJson(id) {
    try {
        if (!detailCache[id]) {
            const response = await fetch(`/api/investigations/${investigationId}/results/${encodeURIComponent(id)}`);
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            detailCache[id] = (await response.json()).result;
        }
        const ok = await copyTextToClipboard(JSON.stringify(detailCache[id], null, 2));
        showTemporaryNotification(ok ? 'Result JSON copied' : 'Copy failed', ok ? 'success' : 'error');
    } catch (e) {
        showTemporaryNotification(`Copy failed: ${e.message}`, 'error');
    }
}

function toggleSelected(id) {
    if (selectedResults.has(id)) selectedResults.delete(id);
    else selectedResults.add(id);
    const box = document.querySelector(`[data-result-id="${CSS.escape(id)}"] [data-action="select"]`);
    if (box) box.checked = selectedResults.has(id);
    updateBulkBar();
}

function collapseCard(id) {
    openCards.delete(id);
    const card = document.querySelector(`[data-result-id="${CSS.escape(id)}"]`);
    if (!card) return;
    card.querySelector('.result-body').classList.add('hidden');
    card.querySelector('.chevron').style.transform = '';
}

async function expandCard(id, silent = false) {
    openCards.add(id);
    const card = document.querySelector(`[data-result-id="${CSS.escape(id)}"]`);
    if (!card) return;
    const body = card.querySelector('.result-body');
    card.querySelector('.chevron').style.transform = 'rotate(180deg)';
    body.classList.remove('hidden');

    if (!detailCache[id]) {
        body.innerHTML =
            '<div class="p-6 text-sm text-gray-400 flex items-center gap-2"><i class="fas fa-spinner fa-spin"></i> Loading result...</div>';
        try {
            const response = await fetch(`/api/investigations/${investigationId}/results/${encodeURIComponent(id)}`);
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            detailCache[id] = (await response.json()).result;
        } catch (error) {
            body.innerHTML = `<div class="p-6 text-sm text-red-400">Failed to load result: ${escapeHtml(error.message)}</div>`;
            return;
        }
    }
    if (!openCards.has(id)) return; // collapsed while loading
    body.innerHTML = renderDetail(detailCache[id]);
    masonryPackAll(body);
    refreshIcons();
    loadResultEntities(id);
    loadResultReferences(id);
    if (!silent) card.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}

// A follow-up's heading: its own title when it was added by hand
function partTitle(part, title) {
    return part.service_name === 'manual' && title ? title : methodLabel(part.method_name);
}

function renderDetail(record) {
    const info = moduleInfo(record.service_name);
    const loadable = info.page && record.service_name !== 'sharetrace';
    const openUrl = loadable
        ? `${info.page}?load_result=${encodeURIComponent(record.result_id)}&investigation=${encodeURIComponent(investigationId)}`
        : null;

    const children = (record.children || [])
        .map(
            (child, i) => `
        <section class="mt-6">
            <div class="flex items-center justify-between mb-3 border-b border-gray-800 pb-2">
                <h4 class="text-sm font-bold text-purple-300 flex items-center gap-2">
                    <i data-lucide="corner-down-right" class="w-4 h-4"></i>${escapeHtml(partTitle(child, (child.result || {}).title))}
                    ${child.partial ? '<span class="text-[10px] uppercase px-1.5 py-0.5 rounded bg-yellow-900/60 text-yellow-300">partial</span>' : ''}
                </h4>
                <span class="text-xs text-gray-500">${escapeHtml(child.timestamp ? new Date(child.timestamp).toLocaleString() : '')}</span>
            </div>
            ${safeRender(child.service_name, child.method_name, child.result, child)}
            ${rawJsonBlock(String(i))}
        </section>
    `
        )
        .join('');

    return `
        <div class="p-5">
            <div class="flex flex-wrap items-center justify-between gap-3 mb-4">
                ${renderParameters(record.parameters)}
                <div class="flex items-center gap-2 ml-auto">
                    ${openUrl ? `<a href="${escapeAttr(openUrl)}" class="px-2.5 py-1.5 rounded-lg bg-purple-700/80 hover:bg-purple-600 text-white text-xs flex items-center gap-1.5"><i data-lucide="external-link" class="w-3.5 h-3.5"></i>Open in module</a>` : ''}
                    <button type="button" data-action="note-link" title="Add a link to this result to the open note" class="px-2.5 py-1.5 rounded-lg bg-gray-800 hover:bg-gray-700 border border-gray-700 text-gray-300 text-xs flex items-center gap-1.5"><i data-lucide="link" class="w-3.5 h-3.5"></i>Link in note</button>
                    <button type="button" data-action="note-attach" title="Attach a copy of this result to the open note - it stays there even if the result is deleted" class="px-2.5 py-1.5 rounded-lg bg-gray-800 hover:bg-gray-700 border border-gray-700 text-gray-300 text-xs flex items-center gap-1.5"><i data-lucide="paperclip" class="w-3.5 h-3.5"></i>Attach to note</button>
                    <button type="button" data-action="manual-add" title="Add a screenshot, file or text found elsewhere to this result" class="px-2.5 py-1.5 rounded-lg bg-gray-800 hover:bg-gray-700 border border-gray-700 text-gray-300 text-xs flex items-center gap-1.5"><i data-lucide="upload" class="w-3.5 h-3.5"></i>Add to this</button>
                    <button type="button" data-action="copy-json" class="px-2.5 py-1.5 rounded-lg bg-gray-800 hover:bg-gray-700 border border-gray-700 text-gray-300 text-xs flex items-center gap-1.5"><i data-lucide="copy" class="w-3.5 h-3.5"></i>Copy JSON</button>
                    <button type="button" data-action="move-result" class="px-2.5 py-1.5 rounded-lg bg-gray-800 hover:bg-gray-700 border border-gray-700 text-gray-300 text-xs flex items-center gap-1.5"><i data-lucide="folder-input" class="w-3.5 h-3.5"></i>Move</button>
                    <button type="button" data-action="delete-result" class="px-2.5 py-1.5 rounded-lg bg-gray-800 hover:bg-red-900/60 border border-gray-700 hover:border-red-700 text-gray-300 text-xs flex items-center gap-1.5"><i data-lucide="trash-2" class="w-3.5 h-3.5"></i>Delete</button>
                </div>
            </div>
            ${triageControls(record)}
            <div class="hidden mb-4 text-xs text-gray-400 flex flex-wrap items-center gap-1.5" data-references-for="${escapeAttr(record.result_id)}"></div>
            ${safeRender(record.service_name, record.method_name, record.result, record)}
            ${rawJsonBlock('record')}
            ${children}
            <section class="mt-6">
                <h4 class="text-sm font-bold text-gray-300 mb-2"><i class="fas fa-fingerprint mr-2 text-purple-400"></i>Identifiers in this result</h4>
                <div class="result-entities text-sm text-gray-500" data-entities-for="${escapeAttr(record.result_id)}">Loading…</div>
            </section>
        </div>
    `;
}

function triageControls(record) {
    const triage = record.triage || {};
    const button = (status) => {
        const t = TRIAGE[status];
        const active = triage.status === status;
        return `<button type="button" data-action="triage" data-triage-status="${status}"
            class="px-2.5 py-1 rounded-lg border text-xs ${active ? t.cls : 'border-gray-700 text-gray-400 hover:text-white hover:border-gray-500'}"
            title="${active ? 'Click again to clear' : ''}"><i class="fas ${t.icon} mr-1"></i>${t.label}</button>`;
    };
    return `
        <div class="flex flex-wrap items-center gap-2 mb-5 bg-gray-900/60 border border-gray-800 rounded-lg p-2.5">
            <span class="text-xs text-gray-500 mr-1">Assessment</span>
            ${button('confirmed')}${button('important')}${button('false_positive')}
            <input type="text" data-triage-note value="${escapeAttr(triage.note || '')}" placeholder="Why it matters (Enter to save)"
                class="flex-1 min-w-[12rem] bg-gray-900 border border-gray-700 rounded-lg px-2.5 py-1 text-sm text-white focus:outline-none focus:border-purple-500">
            <button type="button" data-action="triage-note" class="px-2.5 py-1 rounded-lg bg-gray-800 hover:bg-gray-700 text-xs">Save note</button>
        </div>`;
}

async function saveResultTriage(resultId, status) {
    const card = document.querySelector(`[data-result-id="${CSS.escape(resultId)}"]`);
    const note = card?.querySelector('[data-triage-note]')?.value ?? null;
    const current = (detailCache[resultId] || {}).triage || {};
    const body = { status: status === undefined ? current.status || null : status, note };
    try {
        const response = await fetch(
            `/api/investigations/${investigationId}/results/${encodeURIComponent(resultId)}/triage`,
            {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            }
        );
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
        if (detailCache[resultId]) detailCache[resultId].triage = data.triage;
        const summary = allResults.find((r) => r.result_id === resultId);
        if (summary) summary.triage = data.triage;
        renderResults();
        showTemporaryNotification(status === undefined ? 'Note saved' : 'Assessment saved', 'success');
    } catch (e) {
        showTemporaryNotification(`Failed to save: ${e.message}`, 'error');
    }
}

function fetchResultReferences(resultId) {
    return fetch(`/api/investigations/${investigationId}/results/${encodeURIComponent(resultId)}/references`)
        .then((r) => r.json())
        .then((data) => data.notes || []);
}

// "Mentioned in" line on an expanded result
async function loadResultReferences(resultId) {
    const box = document.querySelector(`[data-references-for="${CSS.escape(resultId)}"]`);
    if (!box) return;
    try {
        const notes = await fetchResultReferences(resultId);
        box.classList.toggle('hidden', !notes.length);
        const notesPage = `/api/investigations/${investigationId}/notes/view`;
        box.innerHTML =
            `<i class="fas fa-sticky-note text-purple-400"></i><span>In notes:</span>` +
            notes
                .map(
                    (n) =>
                        `<a href="${escapeAttr(`${notesPage}#note-${n.note_id}`)}" class="px-2 py-0.5 rounded bg-purple-900/30 border border-purple-800/50 text-purple-200 hover:border-purple-500"
                title="${escapeAttr([n.links && `${n.links} link${n.links === 1 ? '' : 's'}`, n.snapshots && `${n.snapshots} snapshot${n.snapshots === 1 ? '' : 's'}`].filter(Boolean).join(', '))}">${escapeHtml(n.title)}</a>`
                )
                .join('');
    } catch (e) {
        box.classList.add('hidden');
    }
}

async function loadResultEntities(resultId) {
    const box = document.querySelector(`[data-entities-for="${CSS.escape(resultId)}"]`);
    if (!box) return;
    try {
        const response = await fetch(
            `/api/investigations/${investigationId}/results/${encodeURIComponent(resultId)}/entities`
        );
        const { entities } = await response.json();
        if (!entities.length) {
            box.textContent = 'No identifiers recognised in this result.';
            return;
        }
        box.innerHTML = identifierGroupsHtml(entities);
    } catch (e) {
        box.textContent = 'Could not load identifiers.';
    }
}

function rawJsonBlock(path) {
    return `
        <details class="mt-4 group" data-path="${escapeAttr(path)}" data-action="raw-json">
            <summary class="text-xs text-gray-500 hover:text-gray-300 cursor-pointer select-none">Raw JSON</summary>
            <pre class="mt-2 bg-gray-950 rounded-lg p-3 border border-gray-800 text-xs text-gray-300 overflow-x-auto max-h-96 whitespace-pre-wrap break-all"></pre>
        </details>`;
}

// ----------------- ACTIONS -----------------

async function deleteResult(resultId) {
    let notes = [];
    try {
        notes = await fetchResultReferences(resultId);
    } catch (e) {
        // the warning is best effort; deleting still asks for confirmation
    }
    const titles = notes.map((n) => `  • ${n.title}`).join('\n');
    const linked = notes.some((n) => n.links);
    const snapshots = notes.some((n) => n.snapshots);
    const warning = notes.length
        ? [
              `\n\nThis result is referenced in ${notes.length} note${notes.length === 1 ? '' : 's'}:\n${titles}`,
              linked ? '\nLinks to it will show as a deleted result.' : '',
              snapshots ? '\nSnapshots attached to notes are kept.' : '',
          ].join('')
        : '';
    if (!confirm(`Delete this result (and any follow-ups grouped under it)? This cannot be undone.${warning}`)) return;
    try {
        const response = await fetch(`/api/investigations/${investigationId}/results/${encodeURIComponent(resultId)}`, {
            method: 'DELETE',
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        removeResultsFromView([resultId]);
        showTemporaryNotification('Result deleted', 'success');
    } catch (e) {
        showTemporaryNotification(`Failed to delete result: ${e.message}`, 'error');
    }
}

function removeResultsFromView(ids) {
    const gone = new Set(ids);
    allResults = allResults.filter((r) => !gone.has(r.result_id));
    ids.forEach((id) => {
        openCards.delete(id);
        selectedResults.delete(id);
        delete detailCache[id];
    });
    entityState.loaded = false;
    eventState.loaded = false;
    currentInvestigation.results_count = allResults.length;
    renderHeader(currentInvestigation);
    populateModuleFilterOptions();
    renderResults();
}

function resultsWord(count) {
    return `${count} result${count === 1 ? '' : 's'}`;
}

async function bulkRequest(body) {
    const response = await fetch(`/api/investigations/${investigationId}/results/bulk`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `HTTP ${response.status}`);
    return data;
}

// What leaving this investigation means for its notes (best effort, never blocks the action)
async function referencesWarning(ids, gerund) {
    const lists = await Promise.all(ids.map((id) => fetchResultReferences(id).catch(() => [])));
    const notes = new Map();
    lists.flat().forEach((n) => notes.set(n.note_id, n));
    if (!notes.size) return '';
    const titles = [...notes.values()].map((n) => `  • ${n.title}`).join('\n');
    const all = [...notes.values()];
    return [
        `${notes.size} note${notes.size === 1 ? '' : 's'} in this investigation ${notes.size === 1 ? 'mentions' : 'mention'} ${ids.length === 1 ? 'this result' : 'these results'}:\n${titles}`,
        all.some((n) => n.links) ? `\nLinks will show as a deleted result after ${gerund}.` : '',
        all.some((n) => n.snapshots) ? '\nSnapshots attached to notes are kept.' : '',
    ].join('');
}

async function bulkDelete() {
    const ids = [...selectedResults];
    const warning = await referencesWarning(ids, 'deleting');
    if (
        !confirm(
            `Delete ${resultsWord(ids.length)} (and any follow-ups grouped under them)? This cannot be undone.${warning ? `\n\n${warning}` : ''}`
        )
    )
        return;
    try {
        const { done } = await bulkRequest({ action: 'delete', result_ids: ids });
        removeResultsFromView(done);
        showTemporaryNotification(
            `${resultsWord(done.length)} deleted`,
            done.length === ids.length ? 'success' : 'error'
        );
    } catch (e) {
        showTemporaryNotification(`Failed to delete: ${e.message}`, 'error');
    }
}

async function bulkSetTriage(status) {
    const ids = [...selectedResults];
    try {
        const { done, triage } = await bulkRequest({ action: 'triage', result_ids: ids, status });
        done.forEach((id) => {
            if (detailCache[id]) detailCache[id].triage = triage[id];
            const summary = allResults.find((r) => r.result_id === id);
            if (summary) summary.triage = triage[id];
        });
        renderResults();
        showTemporaryNotification(
            `Assessment saved for ${resultsWord(done.length)}`,
            done.length === ids.length ? 'success' : 'error'
        );
    } catch (e) {
        showTemporaryNotification(`Failed to save assessment: ${e.message}`, 'error');
    }
}

let moveIds = [];

async function openMoveModal(ids) {
    moveIds = ids;
    const select = document.getElementById('moveModalTarget');
    const warning = document.getElementById('moveModalWarning');
    document.getElementById('moveModalTitle').textContent = `Move ${resultsWord(ids.length)}`;
    warning.classList.add('hidden');
    let others = [];
    try {
        const response = await fetch('/api/investigations/');
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        others = data.investigations.filter((i) => i.investigation_id !== investigationId);
    } catch (e) {
        showTemporaryNotification(`Could not load investigations: ${e.message}`, 'error');
        return;
    }
    select.innerHTML = others
        .map((i) => `<option value="${escapeAttr(i.investigation_id)}">${escapeHtml(i.name)}</option>`)
        .join('');
    select.classList.toggle('hidden', !others.length);
    document.getElementById('moveModalEmpty').classList.toggle('hidden', others.length > 0);
    document.getElementById('moveModalSubmit').disabled = !others.length;

    const modal = document.getElementById('moveResultsModal');
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    requestAnimationFrame(() => modal.classList.add('modal-open'));
    refreshIcons();

    const text = await referencesWarning(ids, 'the move');
    warning.textContent = text;
    warning.classList.toggle('hidden', !text);
}

function closeMoveModal() {
    const modal = document.getElementById('moveResultsModal');
    modal.classList.remove('modal-open');
    setTimeout(() => {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
    }, 150);
}

async function submitMoveModal(event) {
    event.preventDefault();
    const select = document.getElementById('moveModalTarget');
    const name = select.selectedOptions[0]?.textContent;
    const button = document.getElementById('moveModalSubmit');
    button.disabled = true;
    try {
        const { done } = await bulkRequest({
            action: 'move',
            result_ids: moveIds,
            target_investigation_id: select.value,
        });
        removeResultsFromView(done);
        closeMoveModal();
        showTemporaryNotification(
            `${resultsWord(done.length)} moved to ${name}`,
            done.length === moveIds.length ? 'success' : 'error'
        );
    } catch (e) {
        showTemporaryNotification(`Failed to move: ${e.message}`, 'error');
    } finally {
        button.disabled = false;
    }
}

async function setThisInvestigationAsActive() {
    const ok = await window.selectInvestigation(investigationId, currentInvestigation ? currentInvestigation.name : '');
    if (ok && currentInvestigation) renderHeader(currentInvestigation);
}

function exportResults() {
    window.location.href = `/api/investigations/${investigationId}/export`;
}

async function deleteInvestigation() {
    const name = currentInvestigation ? currentInvestigation.name : 'this investigation';
    if (!confirm(`Delete "${name}" with all ${allResults.length} results and its notes? This cannot be undone.`))
        return;
    try {
        const response = await fetch(`/api/investigations/${investigationId}`, { method: 'DELETE' });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        window.location.href = '/investigations';
    } catch (e) {
        showTemporaryNotification(`Failed to delete: ${e.message}`, 'error');
    }
}

function openEditModal() {
    if (!currentInvestigation) return;
    document.getElementById('editModalName').value = currentInvestigation.name || '';
    document.getElementById('editModalDescription').value = currentInvestigation.description || '';
    document.getElementById('editModalStatus').value = currentInvestigation.status || 'active';
    document.getElementById('editModalPicture').value = '';
    const remove = document.getElementById('editModalRemovePicture');
    remove.checked = false;
    remove.closest('label').classList.toggle('hidden', !currentInvestigation.picture_url);

    const modal = document.getElementById('editInvestigationModal');
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    requestAnimationFrame(() => modal.classList.add('modal-open'));
    setTimeout(() => document.getElementById('editModalName').focus(), 50);
}

function closeEditModal() {
    const modal = document.getElementById('editInvestigationModal');
    modal.classList.remove('modal-open');
    setTimeout(() => {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
    }, 150);
}

async function submitEditModal(e) {
    e.preventDefault();
    const submit = e.target.querySelector('button[type="submit"]');
    const form = new FormData();
    form.append('name', document.getElementById('editModalName').value.trim());
    form.append('description', document.getElementById('editModalDescription').value.trim());
    form.append('status', document.getElementById('editModalStatus').value);
    const picture = document.getElementById('editModalPicture').files[0];
    if (picture) form.append('picture', picture);
    if (document.getElementById('editModalRemovePicture').checked) form.append('remove_picture', 'true');

    submit.disabled = true;
    try {
        const response = await fetch(`/api/investigations/${investigationId}`, { method: 'PUT', body: form });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
        currentInvestigation = data.investigation;
        renderHeader(currentInvestigation);
        closeEditModal();
        showTemporaryNotification('Investigation updated', 'success');
        if (window.loadInvestigationsDropdown) window.loadInvestigationsDropdown();
    } catch (err) {
        showTemporaryNotification(`Failed to update: ${err.message}`, 'error');
    } finally {
        submit.disabled = false;
    }
}

document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    if (!document.getElementById('editInvestigationModal').classList.contains('hidden')) closeEditModal();
    if (!document.getElementById('manualModal').classList.contains('hidden')) closeManualModal();
});
document.addEventListener('investigation:changed', () => {
    if (currentInvestigation) renderHeader(currentInvestigation);
});

// ----------------- IDENTIFIERS TAB -----------------

const entityState = {
    type: '',
    q: '',
    status: '',
    shared: false,
    sharedCount: 0,
    offset: 0,
    total: 0,
    loaded: false,
    pageSize: 200,
};

// "N identifiers in other investigations" in the header; opens them in the Identifiers tab
function sharedStatHtml() {
    const n = entityState.sharedCount;
    if (!n) return '';
    return `<button type="button" onclick="showSharedIdentifiers()" class="text-amber-300 hover:text-amber-200" title="Identifiers that other investigations have too">
        <i data-lucide="folder-open" class="w-3.5 h-3.5 inline mr-1"></i>${n.toLocaleString()} in other investigations</button>`;
}

function showSharedIdentifiers() {
    entityState.shared = true;
    switchTab('entities');
    loadEntities(true);
}

function setSharedCount(count) {
    if (count === entityState.sharedCount) return;
    entityState.sharedCount = count || 0;
    if (currentInvestigation) renderHeader(currentInvestigation);
}
const entityCache = new Map(); // key -> entity as last rendered

function setupEntitiesPanel() {
    document.getElementById('entitySearchInput').addEventListener(
        'input',
        debounce(() => {
            entityState.q = document.getElementById('entitySearchInput').value.trim();
            loadEntities(true);
        }, 250)
    );
    document.getElementById('entityStatusSelect').addEventListener('change', (e) => {
        entityState.status = e.target.value;
        loadEntities(true);
    });
    document.getElementById('entityTypeFacets').addEventListener('click', (e) => {
        if (e.target.closest('[data-shared-facet]')) {
            entityState.shared = !entityState.shared;
            loadEntities(true);
            return;
        }
        const facet = e.target.closest('[data-facet]');
        if (!facet) return;
        entityState.type = entityState.type === facet.dataset.facet ? '' : facet.dataset.facet;
        loadEntities(true);
    });
    document.getElementById('entitiesMore').addEventListener('click', () => loadEntities(false));
    document.getElementById('entitiesList').addEventListener('click', onEntityClick);
    document.getElementById('entitiesList').addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && e.target.matches('[data-entity-note]')) {
            e.preventDefault();
            saveEntityTriage(e.target.closest('[data-entity-key]').dataset.entityKey, undefined);
        }
    });
    // Counts for the tab badge without switching to it
    fetch(`/api/investigations/${investigationId}/entities?limit=1`)
        .then((r) => r.json())
        .then((d) => {
            document.getElementById('entitiesCountBadge').textContent = d.total ?? '';
            setSharedCount(d.shared_count);
        })
        .catch(() => {});
}

async function loadEntities(reset) {
    if (reset) entityState.offset = 0;
    const params = new URLSearchParams({ limit: entityState.pageSize, offset: entityState.offset });
    if (entityState.type) params.set('type', entityState.type);
    if (entityState.q) params.set('q', entityState.q);
    if (entityState.status) params.set('status', entityState.status);
    if (entityState.shared) params.set('shared', '1');
    const list = document.getElementById('entitiesList');
    if (reset) list.innerHTML = '<p class="text-gray-400"><i class="fas fa-spinner fa-spin mr-2"></i>Loading…</p>';
    try {
        const response = await fetch(`/api/investigations/${investigationId}/entities?${params}`);
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
        entityState.loaded = true;
        entityState.total = data.total;
        setSharedCount(data.shared_count);
        // the server already said which of these other investigations have (badges, main.js)
        window.primeSharedIdentifiers(data.entities.map((e) => [`${e.type}:${e.value}`, e.elsewhere]));
        renderFacets(data.types);
        const rows = data.entities.map(entityRow).join('');
        if (reset) list.innerHTML = rows || '<p class="text-gray-500 text-sm">No identifiers match.</p>';
        else list.insertAdjacentHTML('beforeend', rows);
        entityState.offset += data.entities.length;
        const more = document.getElementById('entitiesMore');
        more.classList.toggle('hidden', entityState.offset >= data.total);
        more.textContent = `Show more (${(data.total - entityState.offset).toLocaleString()} left)`;
    } catch (e) {
        list.innerHTML = `<p class="text-red-400 text-sm">Failed to load identifiers: ${escapeHtml(e.message)}</p>`;
    }
}

function renderFacets(types) {
    const box = document.getElementById('entityTypeFacets');
    const total = types.reduce((n, t) => n + t.count, 0);
    document.getElementById('entitiesCountBadge').textContent = total;
    box.innerHTML = [
        `<button type="button" data-facet="" class="facet ${entityState.type ? '' : 'active'}">All <span>${total.toLocaleString()}</span></button>`,
    ]
        .concat(
            types.map(
                (t) =>
                    `<button type="button" data-facet="${escapeAttr(t.type)}" class="facet ${entityState.type === t.type ? 'active' : ''}">${escapeHtml(t.label)} <span>${t.count.toLocaleString()}</span></button>`
            )
        )
        .concat(
            entityState.sharedCount || entityState.shared
                ? [
                      `<button type="button" data-shared-facet class="facet ${entityState.shared ? 'active' : ''}" title="Identifiers that other investigations have too"><i class="fas fa-folder-open mr-1 text-amber-300"></i>In other investigations <span>${entityState.sharedCount.toLocaleString()}</span></button>`,
                  ]
                : []
        )
        .join('');
}

function entityRow(e) {
    entityCache.set(e.key, e);
    const status = e.status;
    const button = (s) => {
        const t = TRIAGE[s];
        return `<button type="button" data-entity-status="${s}" title="${t.label}${status === s ? ' (click to clear)' : ''}"
            class="w-7 h-7 rounded border text-xs ${status === s ? t.cls : 'border-gray-800 text-gray-500 hover:text-white hover:border-gray-600'}"><i class="fas ${t.icon}"></i></button>`;
    };
    const searched = (e.searched || []).length
        ? `<span class="text-[10px] px-1.5 py-0.5 rounded bg-purple-900/50 text-purple-300" title="Looked up with ${escapeAttr(e.searched.join(', '))}">looked up</span>`
        : '';
    return `
        <div class="flex items-center gap-3 bg-[#14151f] border border-[#24283b] rounded-lg px-3 py-2 ${status === 'false_positive' ? 'opacity-50' : ''}" data-entity-key="${escapeAttr(e.key)}">
            <span class="text-[11px] text-gray-500 w-28 shrink-0 truncate">${escapeHtml(e.label || e.type)}</span>
            <div class="min-w-0 flex-1">
                <div class="flex items-center gap-2 flex-wrap">${pivotChip(e.type, e.value, e.display || e.value)} ${searched}</div>
                <button type="button" data-entity-sources class="text-[11px] text-gray-500 hover:text-purple-300 mt-0.5 text-left truncate max-w-full"
                    title="Show the results it was looked up or found in">
                    <i class="fas fa-caret-right mr-1"></i>${sourcesSummary(e)}
                </button>
                <div class="hidden mt-1.5 space-y-0.5" data-entity-source-list>${sourceLinks(e)}</div>
            </div>
            <input type="text" data-entity-note value="${escapeAttr(e.note || '')}" placeholder="Note"
                class="hidden md:block w-56 bg-gray-900 border border-gray-800 rounded px-2 py-1 text-xs text-white focus:outline-none focus:border-purple-500">
            <div class="flex gap-1 shrink-0">${button('confirmed')}${button('important')}${button('false_positive')}</div>
        </div>`;
}

// "in 2 results · ghunt, oi" (the line that opens the list of those results)
function sourcesSummary(e) {
    const results = new Set((e.sources || []).map((src) => src.result_id)).size;
    return escapeHtml(
        [
            `in ${results} result${results === 1 ? '' : 's'}`,
            (e.services || []).map((sv) => moduleInfo(sv).name).join(', '),
        ]
            .filter(Boolean)
            .join(' · ')
    );
}

// The results an identifier was looked up or found in, each opening the result at it
function sourceLinks(e) {
    const seen = new Set();
    return (e.sources || [])
        .filter((src) => {
            const key = `${src.result_id}|${src.child_id || ''}|${src.role}`;
            if (!src.result_id || seen.has(key)) return false;
            seen.add(key);
            return true;
        })
        .map(
            (src) => `
        <button type="button" data-source-result="${escapeAttr(src.result_id)}"
            class="block w-full text-left text-xs text-gray-400 hover:text-white truncate" title="${escapeAttr(src.path ? `Where: ${src.path}` : '')}">
            <i class="fas ${src.role === 'searched' ? 'fa-search text-purple-400' : 'fa-arrow-right text-gray-600'} w-3 mr-1"></i>${escapeHtml(src.role === 'searched' ? 'Looked up with' : 'Found in')}
            <span class="text-gray-200">${escapeHtml(moduleInfo(src.service).name)}</span> · ${escapeHtml(methodLabel(src.method))}${src.target ? ` · <span class="font-mono text-purple-200">${escapeHtml(src.target)}</span>` : ''}${src.timestamp ? ` · ${escapeHtml(timeAgo(src.timestamp))}` : ''}
        </button>`
        )
        .join('');
}

function onEntityClick(event) {
    const toggle = event.target.closest('[data-entity-sources]');
    if (toggle) {
        const list = toggle.parentElement.querySelector('[data-entity-source-list]');
        list.classList.toggle('hidden');
        toggle.querySelector('i').className =
            `fas ${list.classList.contains('hidden') ? 'fa-caret-right' : 'fa-caret-down'} mr-1`;
        return;
    }
    const source = event.target.closest('[data-source-result]');
    if (source) {
        const entity = entityCache.get(source.closest('[data-entity-key]').dataset.entityKey) || {};
        openResultAt(source.dataset.sourceResult, entity.type, entity.value);
        return;
    }
    const button = event.target.closest('[data-entity-status]');
    if (!button) return;
    const key = button.closest('[data-entity-key]').dataset.entityKey;
    const entity = entityCache.get(key) || {};
    const status = button.dataset.entityStatus;
    saveEntityTriage(key, entity.status === status ? null : status);
}

async function saveEntityTriage(key, status) {
    const entity = entityCache.get(key) || { key };
    const row = document.querySelector(`[data-entity-key="${CSS.escape(key)}"]`);
    const note = row?.querySelector('[data-entity-note]')?.value ?? entity.note ?? null;
    try {
        const response = await fetch(`/api/investigations/${investigationId}/entities`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ key, status: status === undefined ? entity.status || null : status, note }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
        const updated = { ...entity, status: data.entity.status, note: data.entity.note };
        if (row) row.outerHTML = entityRow(updated);
        showTemporaryNotification(status === undefined ? 'Note saved' : 'Assessment saved', 'success');
    } catch (e) {
        showTemporaryNotification(`Failed to save: ${e.message}`, 'error');
    }
}

// ----------------- TIMELINE: DATES INSIDE RESULTS -----------------

const eventState = { loaded: false, events: [], shown: 300 };

function setupEventsPanel() {
    const rerender = () => {
        eventState.shown = 300;
        renderEvents();
    };
    document.getElementById('eventSearchInput').addEventListener('input', debounce(rerender, 150));
    document.getElementById('eventModuleSelect').addEventListener('change', rerender);
    document.getElementById('eventSortSelect').addEventListener('change', rerender);
    document.getElementById('eventsList').addEventListener('click', (e) => {
        if (e.target.closest('[data-events-more]')) {
            eventState.shown += 500;
            renderEvents();
            return;
        }
        const open = e.target.closest('[data-open-result]');
        if (!open) return;
        e.preventDefault();
        history.replaceState(null, '', `#result-${encodeURIComponent(open.dataset.openResult)}`);
        openLinkedResult();
    });
}

async function loadEvents() {
    const list = document.getElementById('eventsList');
    list.innerHTML =
        '<p class="text-gray-400"><i class="fas fa-spinner fa-spin mr-2"></i>Reading the dates in the results…</p>';
    try {
        const response = await fetch(`/api/investigations/${investigationId}/events`);
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
        eventState.events = data.events || [];
        eventState.loaded = true;
        document.getElementById('eventsCountBadge').textContent = eventState.events.length || '';
        const counts = {};
        eventState.events.forEach((e) => (counts[e.service] = (counts[e.service] || 0) + 1));
        const select = document.getElementById('eventModuleSelect');
        const chosen = select.value;
        select.innerHTML =
            '<option value="all">All modules</option>' +
            Object.keys(counts)
                .sort()
                .map(
                    (m) => `<option value="${escapeAttr(m)}">${escapeHtml(moduleInfo(m).name)} (${counts[m]})</option>`
                )
                .join('');
        if (counts[chosen]) select.value = chosen;
        renderEvents();
    } catch (e) {
        list.innerHTML = `<p class="text-red-400 text-sm">Failed to load the timeline: ${escapeHtml(e.message)}</p>`;
    }
}

function filteredEvents() {
    const search = document.getElementById('eventSearchInput').value.toLowerCase().trim();
    const service = document.getElementById('eventModuleSelect').value;
    const list = eventState.events.filter((e) => {
        if (service !== 'all' && e.service !== service) return false;
        if (!search) return true;
        return [e.label, e.section, e.context && e.context.value, e.target, moduleInfo(e.service).name, e.date, e.end]
            .join(' ')
            .toLowerCase()
            .includes(search);
    });
    if (document.getElementById('eventSortSelect').value === 'oldest')
        list.sort((a, b) => a.date.localeCompare(b.date) || (a.end || '').localeCompare(b.end || ''));
    return list;
}

function renderEvents() {
    const list = document.getElementById('eventsList');
    if (!eventState.events.length) {
        list.innerHTML = `<div class="text-center py-12 bg-[#14151f] border border-[#24283b] rounded-xl">
            <p class="text-gray-300 font-medium mb-1">No dates found in the results yet</p>
            <p class="text-gray-500 text-sm max-w-md mx-auto">Lookups that return creation dates, WHOIS records, leaks or messages fill this in.
                Dates you give when adding something manually are shown here too.</p></div>`;
        return;
    }
    const events = filteredEvents();
    if (!events.length) {
        list.innerHTML = '<p class="text-gray-500 text-sm">Nothing matches the filter.</p>';
        return;
    }
    const oldest = document.getElementById('eventSortSelect').value === 'oldest';
    let lastYear = null;
    const rows = events.slice(0, eventState.shown).map((e) => {
        const year = (oldest ? e.date : e.end || e.date).slice(0, 4);
        const heading =
            year !== lastYear
                ? `<h3 class="text-xs font-semibold uppercase tracking-wider text-gray-500 pt-4 pb-1">${escapeHtml(year)}</h3>`
                : '';
        lastYear = year;
        return heading + eventRow(e);
    });
    const left = events.length - eventState.shown;
    list.innerHTML =
        rows.join('') +
        (left > 0
            ? `<div class="text-center mt-4"><button type="button" data-events-more class="text-sm text-purple-300 hover:text-white">Show more (${left.toLocaleString()} left)</button></div>`
            : '');
    refreshIcons();
}

function eventRow(e) {
    const info = moduleInfo(e.service);
    const when = e.count
        ? `${eventDateText(e.date, e.precision === 'time' ? 'day' : e.precision)} – ${eventDateText(e.end, e.end_precision === 'time' ? 'day' : e.end_precision)}`
        : eventDateText(e.date, e.precision);
    const upcoming = (e.end || e.date) > new Date().toISOString().slice(0, 19);
    const what = e.count
        ? `<span><b class="text-white">${e.count.toLocaleString()}</b> dates · ${escapeHtml(e.section ? `${e.section} · ${e.label}` : e.label)}</span>`
        : e.manual
          ? `<span class="text-white">${escapeHtml(e.label)}</span>`
          : `<span>${escapeHtml(e.label)}${e.section ? ` <span class="text-gray-500">in ${escapeHtml(e.section)}</span>` : ''}</span>`;
    return `
        <div class="flex items-start gap-3 bg-[#14151f] border border-[#24283b] rounded-lg px-3 py-2">
            <div class="w-56 shrink-0 text-xs text-gray-300 font-mono pt-0.5">${escapeHtml(when)}</div>
            <div class="min-w-0 flex-1">
                <div class="text-sm text-gray-300 flex flex-wrap items-center gap-2">
                    ${e.context ? pivotField(e.context.key, e.context.value) : ''}${what}
                    ${e.count ? '<span class="text-[10px] uppercase px-1.5 py-0.5 rounded bg-gray-800 text-gray-400 border border-gray-700" title="Many dates from one list, shown as their first and last">series</span>' : ''}
                    ${upcoming ? '<span class="text-[10px] uppercase px-1.5 py-0.5 rounded bg-blue-950/80 text-blue-300 border border-blue-800/60">upcoming</span>' : ''}
                </div>
                <div class="text-[11px] text-gray-500 mt-0.5 truncate">${escapeHtml(info.name)}${e.method ? ` · ${escapeHtml(methodLabel(e.method))}` : ''}${e.target && e.target !== e.label ? ` · ${escapeHtml(e.target)}` : ''}</div>
            </div>
            <a href="#result-${encodeURIComponent(e.result_id)}" data-open-result="${escapeAttr(e.result_id)}" class="text-xs text-purple-300 hover:text-white shrink-0 pt-0.5">Open result</a>
        </div>`;
}

// ----------------- ADD MANUALLY -----------------

const MANUAL_FILES_MAX = 20;
const MANUAL_FILE_MAX_BYTES = 50 * 1024 * 1024;
let manualParent = null; // result id when adding to an existing result
let manualFiles = [];

function setupManualModal() {
    const input = document.getElementById('manualFiles');
    input.addEventListener('change', () => {
        addManualFiles([...input.files]);
        input.value = '';
    });
    const drop = document.getElementById('manualDrop');
    drop.addEventListener('dragover', (e) => {
        e.preventDefault();
        drop.classList.add('border-purple-500');
    });
    drop.addEventListener('dragleave', () => drop.classList.remove('border-purple-500'));
    drop.addEventListener('drop', (e) => {
        e.preventDefault();
        drop.classList.remove('border-purple-500');
        addManualFiles([...e.dataTransfer.files]);
    });
    // A screenshot pasted anywhere in the form becomes a file; pasted text goes to the field as usual
    document.getElementById('manualModal').addEventListener('paste', (e) => {
        const files = [...((e.clipboardData && e.clipboardData.files) || [])];
        if (!files.length) return;
        e.preventDefault();
        const stamp = new Date().toLocaleString().replace(/[/:]/g, '-');
        addManualFiles(
            files.map((f, i) =>
                f.name && f.name !== 'image.png'
                    ? f
                    : new File([f], `Screenshot ${stamp}${files.length > 1 ? ` (${i + 1})` : ''}.png`, { type: f.type })
            )
        );
    });
    document.getElementById('manualFileList').addEventListener('click', (e) => {
        const remove = e.target.closest('[data-remove-file]');
        if (!remove) return;
        manualFiles.splice(Number(remove.dataset.removeFile), 1);
        renderManualFiles();
    });
}

function addManualFiles(files) {
    for (const file of files) {
        if (manualFiles.length >= MANUAL_FILES_MAX) {
            showTemporaryNotification(`At most ${MANUAL_FILES_MAX} files at once`, 'error');
            break;
        }
        if (file.size > MANUAL_FILE_MAX_BYTES) {
            showTemporaryNotification(`${file.name} is too large (max 50 MB)`, 'error');
            continue;
        }
        manualFiles.push(file);
    }
    renderManualFiles();
}

function renderManualFiles() {
    document.getElementById('manualFileList').innerHTML = manualFiles
        .map(
            (f, i) => `
        <div class="flex items-center gap-2 bg-gray-950 border border-gray-800 rounded-lg px-3 py-1.5 text-sm">
            <i class="fas ${f.type.startsWith('image/') ? 'fa-image' : 'fa-file'} text-purple-300"></i>
            <span class="truncate flex-1 text-gray-200" title="${escapeAttr(f.name)}">${escapeHtml(f.name)}</span>
            <span class="text-xs text-gray-500 shrink-0">${escapeHtml(fileSize(f.size))}</span>
            <button type="button" data-remove-file="${i}" class="text-gray-500 hover:text-red-300" title="Remove"><i class="fas fa-times"></i></button>
        </div>`
        )
        .join('');
}

function openManualModal(parentId = null) {
    manualParent = parentId;
    manualFiles = [];
    ['manualTitle', 'manualSource', 'manualDate', 'manualUrl', 'manualText', 'manualIdentifiers'].forEach((id) => {
        document.getElementById(id).value = '';
    });
    const parent = parentId && allResults.find((r) => r.result_id === parentId);
    document.getElementById('manualModalTitle').textContent = parent
        ? `Add to ${moduleInfo(parent.service_name).name}${parent.target ? ` · ${parent.target}` : ''}`
        : 'Add manually';
    renderManualFiles();
    const modal = document.getElementById('manualModal');
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    requestAnimationFrame(() => modal.classList.add('modal-open'));
    refreshIcons();
    // unless a field was already clicked
    setTimeout(() => {
        if (!modal.contains(document.activeElement)) document.getElementById('manualTitle').focus();
    }, 50);
}

function closeManualModal() {
    const modal = document.getElementById('manualModal');
    modal.classList.remove('modal-open');
    setTimeout(() => {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
    }, 150);
}

async function submitManualModal(event) {
    event.preventDefault();
    const form = new FormData();
    const fields = {
        title: 'manualTitle',
        source: 'manualSource',
        date: 'manualDate',
        url: 'manualUrl',
        text: 'manualText',
        identifiers: 'manualIdentifiers',
    };
    Object.entries(fields).forEach(([name, id]) => form.append(name, document.getElementById(id).value));
    if (manualParent) form.append('parent_result_id', manualParent);
    manualFiles.forEach((f) => form.append('files', f, f.name));
    const button = document.getElementById('manualSubmit');
    button.disabled = true;
    button.textContent = manualFiles.length ? 'Uploading…' : 'Saving…';
    try {
        const response = await fetch(`/api/investigations/${investigationId}/manual`, { method: 'POST', body: form });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `HTTP ${response.status}`);
        closeManualModal();
        delete detailCache[data.result_id];
        entityState.loaded = false;
        eventState.loaded = false;
        await reloadResults();
        const skipped = data.skipped || [];
        showTemporaryNotification(
            skipped.length ? `Saved. Not recognised as identifiers: ${skipped.join(', ')}` : 'Saved',
            skipped.length ? 'error' : 'success'
        );
        history.replaceState(null, '', `#result-${encodeURIComponent(data.result_id)}`);
        openLinkedResult();
    } catch (e) {
        showTemporaryNotification(`Failed to save: ${e.message}`, 'error');
    } finally {
        button.disabled = false;
        button.textContent = 'Save';
    }
}

async function reloadResults() {
    const response = await fetch(`/api/investigations/${investigationId}/results`);
    if (!response.ok) return;
    allResults = (await response.json()).results || [];
    currentInvestigation.results_count = allResults.length;
    renderHeader(currentInvestigation);
    populateModuleFilterOptions();
    renderResults();
}
