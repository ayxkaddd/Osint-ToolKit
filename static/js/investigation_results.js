// investigation_results.js - one investigation's timeline.
// Summaries are listed up front; a result's payload is fetched only when its
// card is expanded (results can be large), then cached.

let currentInvestigation = null;
let allResults = [];       // summaries from /results
const detailCache = {};    // result_id -> full record
const openCards = new Set();

const MODULES = {
    ns: { name: 'Shared NS Domains', icon: 'network', page: '/ns' },
    whois: { name: 'WHOIS', icon: 'info', page: '/whois' },
    dns_recon: { name: 'DNS Reconnaissance', icon: 'globe', page: '/dnsrecon' },
    username: { name: 'Username Search', icon: 'user-check', page: '/username' },
    hlr: { name: 'HLR Phone Lookup', icon: 'phone', page: '/hlr' },
    gitfive: { name: 'GitHub Recon (GitFive)', icon: 'github', page: '/git' },
    vk_profile: { name: 'VK Profile History', icon: 'user', page: '/vk' },
    oi: { name: 'OSINT Industries', icon: 'shield-alert', page: '/api' },
    cavalier: { name: 'Hudson Rock Cavalier', icon: 'shield', page: '/cavalier' },
    ghunt: { name: 'GHunt Google Recon', icon: 'mail', page: '/ghunt' },
    web_search: { name: 'Web Dorking', icon: 'search', page: '/websearch' },
    data_search: { name: 'Local Data Search', icon: 'file-text' },  // removed module; old results stay readable
    face_search: { name: 'Face Search', icon: 'scan-face', page: '/face-search' },
    sharetrace: { name: 'ShareTrace Link Enrichment', icon: 'share-2', page: null },
    funstat: { name: 'Telegram Funstat', icon: 'message-square', page: '/funstat' },
    ip: { name: 'IP Lookup', icon: 'map-pin', page: '/ip' },
    phone: { name: 'Phone analysis', icon: 'phone', page: '/hlr' },
};

const TRIAGE = {
    confirmed: { label: 'Confirmed', cls: 'bg-emerald-900/50 text-emerald-300 border-emerald-700/60', icon: 'fa-check-circle' },
    important: { label: 'Important', cls: 'bg-amber-900/50 text-amber-300 border-amber-700/60', icon: 'fa-star' },
    false_positive: { label: 'False positive', cls: 'bg-gray-800 text-gray-400 border-gray-700', icon: 'fa-times-circle' },
};

function triageBadge(status) {
    const t = TRIAGE[status];
    return t ? `<span class="text-[10px] uppercase px-1.5 py-0.5 rounded border ${t.cls}"><i class="fas ${t.icon} mr-1"></i>${t.label}</span>` : '';
}

const METHOD_LABELS = {
    tme_profile: 't.me profile',
    lookup_ns: 'Shared domains',
    whois_analysis: 'WHOIS analysis',
    lookup_whois: 'WHOIS lookup',
    lookup_whois_history: 'WHOIS history',
    fingerprint: 'Website fingerprints',
    lookup_dns_recon: 'Recon',
    lookup_username: 'Username search',
    hlr_lookup: 'HLR lookup',
    lookup_gitfive: 'Profile',
    lookup_vk_profile: 'Profile history',
    lookup_oi: 'Report',
    search_infostealers: 'Infostealer lookup',
    lookup_ghunt_email: 'Email',
    lookup_ghunt_gaia: 'Gaia ID',
    lookup_ghunt_drive: 'Drive',
    lookup_ghunt_geolocate: 'BSSID geolocation',
    lookup_ghunt_spiderdal: 'Digital Asset Links',
    search_osint: 'Auto dorks',
    search_custom_dorks: 'Custom dorks',
    search_data: 'Search',
    search_data_get: 'Search',
    search_faces: 'Face match',
    lookup_user: 'User',
    lookup_group: 'Group',
    stats_min: 'Stats',
    stats: 'Full stats',
    groups: 'Groups',
    messages: 'Messages (page)',
    all_messages: 'All messages',
    names_history: 'Names history',
    names_and_usernames_history: 'Name & username history',
    usernames_history: 'Usernames history',
    common_groups_stat: 'Common groups',
    group_members: 'Members',
    search_text: 'Text search',
    username_usage: 'Username usage',
    ip_lookup: 'IP info',
    phone_info: 'Offline analysis',
    enrich_links: 'Link enrichment',
};

const moduleInfo = (service) => MODULES[service] || {
    name: (service || 'unknown').replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase()),
    icon: 'terminal',
    page: null,
};
const methodLabel = (method) => METHOD_LABELS[method] || (method || '').replace(/_/g, ' ');

document.addEventListener('DOMContentLoaded', () => {
    loadInvestigationData();
    document.getElementById('timelineSearchInput')?.addEventListener('input', debounce(renderResults, 150));
    document.getElementById('moduleFilterSelect')?.addEventListener('change', renderResults);
    document.getElementById('sortSelect')?.addEventListener('change', renderResults);
    document.getElementById('triageFilterSelect')?.addEventListener('change', renderResults);
    document.getElementById('resultsContainer').addEventListener('click', onResultsClick);
    document.getElementById('resultsContainer').addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && e.target.matches('[data-triage-note]')) {
            e.preventDefault();
            saveResultTriage(e.target.closest('[data-result-id]').dataset.resultId, undefined);
        }
    });
    document.querySelectorAll('[data-tab]').forEach(tab => tab.addEventListener('click', () => switchTab(tab.dataset.tab)));
    setupEntitiesPanel();
    if (location.hash === '#identifiers') switchTab('entities');
});

function switchTab(name) {
    document.querySelectorAll('[data-tab]').forEach(t => t.classList.toggle('active', t.dataset.tab === name));
    document.getElementById('timelinePanel').classList.toggle('hidden', name !== 'timeline');
    document.getElementById('entitiesPanel').classList.toggle('hidden', name !== 'entities');
    history.replaceState(null, '', name === 'entities' ? '#identifiers' : location.pathname);
    if (name === 'entities' && !entityState.loaded) loadEntities(true);
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
            document.getElementById('loadingResults').innerHTML = '<p class="text-gray-400">This investigation no longer exists.</p>';
            return;
        }
        if (!infoResponse.ok || !resultsResponse.ok) throw new Error(`HTTP ${infoResponse.ok ? resultsResponse.status : infoResponse.status}`);
        const infoData = await infoResponse.json();
        currentInvestigation = infoData.investigation;
        renderHeader(currentInvestigation);

        const resultsData = await resultsResponse.json();
        allResults = resultsData.results || [];
        document.getElementById('loadingResults').classList.add('hidden');
        populateModuleFilterOptions();
        renderResults();
    } catch (error) {
        console.error('Error loading investigation data:', error);
        document.getElementById('loadingResults').innerHTML = `<p class="text-red-400">Failed to load investigation: ${escapeHtml(error.message)}</p>`;
    }
}

// ----------------- HEADER -----------------

function renderHeader(investigation) {
    const header = document.getElementById('investigationHeader');
    const isCurrent = window.getCurrentInvestigationId && window.getCurrentInvestigationId() === investigation.investigation_id;
    const statusColors = {
        active: 'bg-emerald-950/80 text-emerald-300 border-emerald-700/60',
        completed: 'bg-blue-950/80 text-blue-300 border-blue-700/60',
        archived: 'bg-gray-800 text-gray-400 border-gray-700',
    };
    const fmt = (iso) => iso ? new Date(iso).toLocaleString() : '—';

    header.innerHTML = `
        <div class="flex flex-col lg:flex-row items-start lg:items-center justify-between gap-6">
            <div class="flex items-start gap-5 min-w-0">
                ${investigation.picture_url
                    ? `<img src="${escapeAttr(investigation.picture_url)}" alt="" class="w-20 h-20 rounded-2xl object-cover border border-gray-700 shrink-0">`
                    : `<div class="w-20 h-20 rounded-2xl bg-purple-950/40 border border-purple-800/60 flex items-center justify-center shrink-0"><i data-lucide="folder-open" class="w-9 h-9 text-purple-400"></i></div>`}
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
    allResults.forEach(r => { counts[r.service_name] = (counts[r.service_name] || 0) + 1; });
    select.innerHTML = '<option value="all">All modules</option>' + Object.keys(counts).sort().map(s =>
        `<option value="${escapeAttr(s)}">${escapeHtml(moduleInfo(s).name)} (${counts[s]})</option>`
    ).join('');
}

function filteredResults() {
    const search = (document.getElementById('timelineSearchInput')?.value || '').toLowerCase().trim();
    const service = document.getElementById('moduleFilterSelect')?.value || 'all';
    const sort = document.getElementById('sortSelect')?.value || 'newest';
    const triage = document.getElementById('triageFilterSelect')?.value || 'all';

    const list = allResults.filter(r => {
        if (service !== 'all' && r.service_name !== service) return false;
        const status = (r.triage || {}).status || null;
        if (triage === 'marked' && !['confirmed', 'important'].includes(status)) return false;
        if (['confirmed', 'important'].includes(triage) && status !== triage) return false;
        if (triage === 'untriaged' && status) return false;
        if (triage === 'hide_fp' && status === 'false_positive') return false;
        if (!search) return true;
        const haystack = [
            r.target, r.summary, r.service_name, r.method_name, moduleInfo(r.service_name).name,
            JSON.stringify(r.parameters || {}), (r.triage || {}).note || '',
            ...(r.children || []).map(c => `${c.method_name} ${c.target || ''} ${c.summary || ''}`),
        ].join(' ').toLowerCase();
        return haystack.includes(search);
    });
    list.sort((a, b) => sort === 'oldest'
        ? (a.timestamp || '').localeCompare(b.timestamp || '')
        : (b.timestamp || '').localeCompare(a.timestamp || ''));
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
    const badge = document.getElementById('resultsCountBadge');
    if (badge) {
        badge.textContent = results.length === allResults.length ? allResults.length : `${results.length} / ${allResults.length}`;
        badge.classList.remove('hidden');
    }
    document.getElementById('noResults').classList.toggle('hidden', results.length > 0);
    document.getElementById('noResultsTitle').textContent = allResults.length ? 'Nothing matches the filter' : 'No results recorded yet';

    let lastDay = null;
    container.innerHTML = results.map(r => {
        const day = dayLabel(r.timestamp);
        const heading = day !== lastDay ? `<h3 class="text-xs font-semibold uppercase tracking-wider text-gray-500 pt-4 pb-1">${escapeHtml(day)}</h3>` : '';
        lastDay = day;
        return heading + renderCard(r);
    }).join('');

    // Re-render cards that were open before filtering
    openCards.forEach(id => {
        if (results.some(r => r.result_id === id)) expandCard(id, true);
    });
    refreshIcons();
}

function renderCard(r) {
    const info = moduleInfo(r.service_name);
    const time = r.timestamp ? new Date(r.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '';
    const children = r.children || [];
    const id = escapeAttr(r.result_id);

    return `
        <div class="result-card inv-result-card bg-[#14151f] border border-[#24283b] rounded-xl overflow-hidden hover:border-purple-500/40 ${(r.triage || {}).status === 'false_positive' ? 'opacity-60' : ''}" data-result-id="${id}">
            <div class="p-4 flex items-center justify-between gap-3 cursor-pointer select-none" data-action="toggle">
                <div class="flex items-center gap-3.5 min-w-0">
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
                        ${children.length ? `<div class="flex flex-wrap gap-1.5 mt-1.5">${children.map(c =>
                            `<span class="text-[11px] px-1.5 py-0.5 rounded bg-gray-800 text-gray-300 border border-gray-700">${escapeHtml(methodLabel(c.method_name))}${c.summary ? ` · ${escapeHtml(c.summary)}` : ''}</span>`).join('')}</div>` : ''}
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

    if (action === 'toggle') {
        if (openCards.has(id)) collapseCard(id);
        else expandCard(id);
    } else if (action === 'copy-json') {
        const record = detailCache[id];
        if (record) copyTextToClipboard(JSON.stringify(record, null, 2)).then(ok =>
            showTemporaryNotification(ok ? 'Result JSON copied' : 'Copy failed', ok ? 'success' : 'error'));
    } else if (action === 'delete-result') {
        deleteResult(id);
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
        body.innerHTML = '<div class="p-6 text-sm text-gray-400 flex items-center gap-2"><i class="fas fa-spinner fa-spin"></i> Loading result...</div>';
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
    refreshIcons();
    loadResultEntities(id);
    if (!silent) card.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}

function renderDetail(record) {
    const info = moduleInfo(record.service_name);
    const loadable = info.page && record.service_name !== 'sharetrace';
    const openUrl = loadable
        ? `${info.page}?load_result=${encodeURIComponent(record.result_id)}&investigation=${encodeURIComponent(investigationId)}`
        : null;

    const children = (record.children || []).map((child, i) => `
        <section class="mt-6">
            <div class="flex items-center justify-between mb-3 border-b border-gray-800 pb-2">
                <h4 class="text-sm font-bold text-purple-300 flex items-center gap-2">
                    <i data-lucide="corner-down-right" class="w-4 h-4"></i>${escapeHtml(methodLabel(child.method_name))}
                    ${child.partial ? '<span class="text-[10px] uppercase px-1.5 py-0.5 rounded bg-yellow-900/60 text-yellow-300">partial</span>' : ''}
                </h4>
                <span class="text-xs text-gray-500">${escapeHtml(child.timestamp ? new Date(child.timestamp).toLocaleString() : '')}</span>
            </div>
            ${safeRender(child.service_name, child.method_name, child.result, child)}
            ${rawJsonBlock(String(i))}
        </section>
    `).join('');

    return `
        <div class="p-5">
            <div class="flex flex-wrap items-center justify-between gap-3 mb-4">
                ${renderParameters(record.parameters)}
                <div class="flex items-center gap-2 ml-auto">
                    ${openUrl ? `<a href="${escapeAttr(openUrl)}" class="px-2.5 py-1.5 rounded-lg bg-purple-700/80 hover:bg-purple-600 text-white text-xs flex items-center gap-1.5"><i data-lucide="external-link" class="w-3.5 h-3.5"></i>Open in module</a>` : ''}
                    <button type="button" data-action="copy-json" class="px-2.5 py-1.5 rounded-lg bg-gray-800 hover:bg-gray-700 border border-gray-700 text-gray-300 text-xs flex items-center gap-1.5"><i data-lucide="copy" class="w-3.5 h-3.5"></i>Copy JSON</button>
                    <button type="button" data-action="delete-result" class="px-2.5 py-1.5 rounded-lg bg-gray-800 hover:bg-red-900/60 border border-gray-700 hover:border-red-700 text-gray-300 text-xs flex items-center gap-1.5"><i data-lucide="trash-2" class="w-3.5 h-3.5"></i>Delete</button>
                </div>
            </div>
            ${triageControls(record)}
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
    const body = { status: status === undefined ? (current.status || null) : status, note };
    try {
        const response = await fetch(`/api/investigations/${investigationId}/results/${encodeURIComponent(resultId)}/triage`, {
            method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
        if (detailCache[resultId]) detailCache[resultId].triage = data.triage;
        const summary = allResults.find(r => r.result_id === resultId);
        if (summary) summary.triage = data.triage;
        renderResults();
        showTemporaryNotification(status === undefined ? 'Note saved' : 'Assessment saved', 'success');
    } catch (e) {
        showTemporaryNotification(`Failed to save: ${e.message}`, 'error');
    }
}

async function loadResultEntities(resultId) {
    const box = document.querySelector(`[data-entities-for="${CSS.escape(resultId)}"]`);
    if (!box) return;
    try {
        const response = await fetch(`/api/investigations/${investigationId}/results/${encodeURIComponent(resultId)}/entities`);
        const { entities } = await response.json();
        if (!entities.length) {
            box.textContent = 'No identifiers recognised in this result.';
            return;
        }
        const byType = {};
        entities.forEach(e => (byType[e.type] = byType[e.type] || []).push(e));
        box.innerHTML = Object.entries(byType).map(([type, list]) => `
            <div class="mb-2">
                <div class="text-xs text-gray-500 mb-1">${escapeHtml((window.ENTITY_LABELS || {})[type] || type)} (${list.length})</div>
                <div class="flex flex-wrap gap-1.5">
                    ${list.slice(0, 150).map(e => pivotChip(e.type, e.value, e.display || e.value)).join('')}
                    ${list.length > 150 ? `<span class="text-xs text-gray-500">+${list.length - 150} more in the Identifiers tab</span>` : ''}
                </div>
            </div>`).join('');
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

function renderParameters(params) {
    const kwargs = (params && (params.kwargs || params)) || {};
    const entries = Object.entries(kwargs).filter(([, v]) => v !== null && v !== undefined && v !== '' && v !== false);
    if (!entries.length) return '<div></div>';
    return `<div class="flex flex-wrap gap-1.5">${entries.map(([k, v]) => {
        let text = typeof v === 'object' ? JSON.stringify(v) : String(v);
        if (text.length > 120) text = text.slice(0, 120) + '…';
        return `<span class="px-2 py-1 bg-gray-900 rounded-md text-xs border border-gray-800 font-mono"><span class="text-purple-400">${escapeHtml(k)}:</span> <span class="text-gray-200">${escapeHtml(text)}</span></span>`;
    }).join('')}</div>`;
}

// ----------------- RENDERERS -----------------

function safeRender(service, method, data, record) {
    try {
        const renderer = RENDERERS[`${service}.${method}`] || RENDERERS[service];
        if (renderer) return renderer(data, record) || renderValue(data);
    } catch (e) {
        console.error(`Renderer for ${service}.${method} failed:`, e);
    }
    return renderValue(data);
}

const RENDERERS = {
    'ns.lookup_ns': (data) => renderDomainList(Array.isArray(data) ? data : []),
    'ns.whois_analysis': (data) => renderWhoisAnalysis((data && data.domains) || {}),
    'ns.fingerprint': renderFingerprints,
    'whois.lookup_whois_history': renderWhoisHistory,
    'whois.lookup_whois': renderWhoisRecord,
    dns_recon: renderDnsRecon,
    username: renderUsernameSearch,
    hlr: renderHlr,
    gitfive: renderGitFive,
    vk_profile: renderVkProfile,
    oi: renderOi,
    cavalier: renderCavalier,
    'ghunt.lookup_ghunt_email': renderGhuntProfile,
    'ghunt.lookup_ghunt_gaia': renderGhuntProfile,
    web_search: renderWebSearch,
    face_search: renderFaceSearch,
    'funstat.lookup_user': renderFunstatUsers,
    'funstat.groups': renderFunstatGroups,
    'funstat.tme_profile': renderTmeProfile,
    'funstat.messages': (data) => renderFunstatMessages(data && data.messages),
    'funstat.all_messages': (data) => renderFunstatMessages(data && data.messages),
    'funstat.group_members': (data) => renderTable(Array.isArray(data) ? data : [], ['first_name', 'last_name', 'username', 'id', 'is_admin', 'today_msg']),
    'funstat.search_text': renderFunstatTextSearch,
    'phone.phone_info': renderPhoneInfo,
    ip: renderIpInfo,
};

function renderPhoneInfo(d) {
    if (!d || !d.e164) return renderValue(d);
    return `
        <div class="space-y-3">
            <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
                ${stat('Number', d.international)}
                ${stat('Country', d.location || d.region)}
                ${stat('Original carrier', d.carrier || 'unknown')}
                ${stat('Line type', d.line_type)}
            </div>
            <div class="text-xs text-gray-500">${d.valid ? 'Valid number' : 'Not a valid number'} · ${escapeHtml((d.timezones || []).join(', '))}</div>
            <div class="flex flex-wrap gap-2 text-xs">
                ${link(d.links && d.links.whatsapp, 'WhatsApp')} ${link(d.links && d.links.telegram, 'Telegram')} ${link(d.links && d.links.google, 'Google (all formats)')}
            </div>
        </div>`;
}

function renderIpInfo(d) {
    if (!d || !d.ip) return renderValue(d);
    const b = d.basic_info || {};
    const a = d.abuse_info || null;
    const sh = d.shodan_info || null;
    return `
        <div class="space-y-3">
            <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
                ${stat('IP', d.ip)}
                ${stat('Location', [b.city, b.country].filter(Boolean).join(', ') || '—')}
                ${stat('Network', b.org || '—')}
                ${stat('Reverse DNS', d.reverse_dns || '—')}
            </div>
            ${a && !a.error ? `<div class="text-sm">AbuseIPDB: <b class="${a.abuseConfidenceScore > 50 ? 'text-red-300' : 'text-emerald-300'}">${escapeHtml(a.abuseConfidenceScore)}%</b> confidence, ${escapeHtml(a.totalReports)} reports${a.isTor ? ' · <span class="text-yellow-300">Tor exit</span>' : ''}</div>` : ''}
            ${sh && !sh.error && sh.ports ? `<div class="text-sm">Shodan open ports: ${escapeHtml(sh.ports.join(', ') || 'none')}${(sh.vulns || []).length ? ` · <span class="text-red-300">${escapeHtml(sh.vulns.length)} CVEs</span>` : ''}</div>` : ''}
            ${(d.warnings || []).map(w => `<div class="text-xs text-yellow-300">${escapeHtml(w)}</div>`).join('')}
        </div>`;
}

function stat(label, value, color = 'text-white') {
    return `
        <div class="bg-gray-900 p-3 rounded-xl border border-gray-800 text-center min-w-0">
            <div class="text-lg font-bold ${color} truncate">${escapeHtml(value ?? '—')}</div>
            <div class="text-xs text-gray-400">${escapeHtml(label)}</div>
        </div>`;
}

function link(url, text) {
    const href = safeUrl(url);
    if (!href) return escapeHtml(text || url || '');
    return `<a href="${escapeAttr(href)}" target="_blank" rel="noopener noreferrer" class="text-blue-400 hover:underline break-all">${escapeHtml(text || url)}</a>`;
}

function chips(values, limit = 200, cls = 'font-mono') {
    const shown = values.slice(0, limit).map(v => `<span class="bg-gray-900 px-2 py-1 rounded-md text-xs ${cls} text-gray-200 border border-gray-800 break-all">${escapeHtml(v)}</span>`).join('');
    const more = values.length > limit ? `<span class="text-xs text-gray-500 px-2 py-1">+${values.length - limit} more (see Raw JSON)</span>` : '';
    return `<div class="flex flex-wrap gap-1.5">${shown}${more}</div>`;
}

// Generic, readable rendering for any JSON value.
function renderValue(value, depth = 0) {
    if (value === null || value === undefined || value === '') return '<span class="text-gray-500">—</span>';
    if (typeof value !== 'object') {
        const text = String(value);
        if (/^https?:\/\//i.test(text)) return link(text);
        if (text.length > 300) return `<div class="whitespace-pre-wrap break-words text-sm text-gray-200 max-h-64 overflow-y-auto">${escapeHtml(text)}</div>`;
        return `<span class="text-gray-200 break-words">${escapeHtml(text)}</span>`;
    }
    if (depth >= 3) {
        return `<pre class="text-xs text-gray-400 whitespace-pre-wrap break-all max-h-48 overflow-y-auto">${escapeHtml(JSON.stringify(value, null, 2))}</pre>`;
    }
    if (Array.isArray(value)) {
        if (!value.length) return '<span class="text-gray-500">none</span>';
        if (value.every(v => v === null || typeof v !== 'object')) return chips(value.map(String));
        if (value.every(v => v && typeof v === 'object' && !Array.isArray(v))) return renderTable(value);
        return `<div class="space-y-2">${value.slice(0, 50).map(v => `<div class="bg-gray-900/60 rounded-lg p-2">${renderValue(v, depth + 1)}</div>`).join('')}</div>`;
    }
    const entries = Object.entries(value);
    if (!entries.length) return '<span class="text-gray-500">empty</span>';
    return `
        <dl class="grid grid-cols-1 md:grid-cols-[minmax(8rem,auto)_1fr] gap-x-4 gap-y-1.5 text-sm">
            ${entries.map(([k, v]) => `
                <dt class="text-gray-500 text-xs pt-0.5 break-all">${escapeHtml(k.replace(/_/g, ' '))}</dt>
                <dd class="min-w-0">${renderValue(v, depth + 1)}</dd>
            `).join('')}
        </dl>`;
}

function renderTable(rows, columns = null, limit = 200) {
    if (!rows.length) return '<p class="text-gray-400 text-sm">No entries.</p>';
    if (!columns) {
        const counts = {};
        rows.slice(0, 50).forEach(r => Object.entries(r).forEach(([k, v]) => {
            if (v !== null && v !== '' && typeof v !== 'object') counts[k] = (counts[k] || 0) + 1;
        }));
        columns = Object.keys(counts).sort((a, b) => counts[b] - counts[a]).slice(0, 8);
    }
    const cell = (v) => {
        if (v === null || v === undefined || v === '') return '<span class="text-gray-600">—</span>';
        if (typeof v === 'object') return `<span class="text-gray-400 font-mono text-[11px]">${escapeHtml(JSON.stringify(v).slice(0, 80))}</span>`;
        const text = String(v);
        return /^https?:\/\//i.test(text) ? link(text, text.length > 60 ? text.slice(0, 60) + '…' : text) : escapeHtml(text);
    };
    return `
        <div class="overflow-x-auto border border-gray-800 rounded-lg max-h-[32rem] overflow-y-auto">
            <table class="w-full text-xs">
                <thead class="bg-gray-900 sticky top-0"><tr>${columns.map(c => `<th class="text-left px-3 py-2 text-gray-400 font-semibold whitespace-nowrap">${escapeHtml(c.replace(/_/g, ' '))}</th>`).join('')}</tr></thead>
                <tbody>${rows.slice(0, limit).map(r => `<tr class="border-t border-gray-800/80 hover:bg-gray-900/60">${columns.map(c => `<td class="px-3 py-1.5 text-gray-200 align-top break-words max-w-xs">${cell(r[c])}</td>`).join('')}</tr>`).join('')}</tbody>
            </table>
        </div>
        ${rows.length > limit ? `<p class="text-xs text-gray-500 mt-2">Showing ${limit} of ${rows.length} (see Raw JSON for all)</p>` : ''}`;
}

function renderDomainList(domains) {
    return `
        <div class="space-y-2">
            <span class="text-sm font-semibold text-gray-300">${domains.length} shared domain${domains.length === 1 ? '' : 's'}</span>
            <div class="max-h-80 overflow-y-auto">${chips(domains, 500)}</div>
        </div>`;
}

function renderWhoisAnalysis(domains) {
    const rows = Object.entries(domains).map(([domain, w]) => ({
        domain,
        registrant: w && w.registrant,
        email: w && w.email,
        registrar: w && w.registrar,
        created: w && w.creation_date ? String(w.creation_date).slice(0, 10) : null,
        error: w && w.error,
    }));
    const groupsBy = (key) => {
        const map = {};
        rows.forEach(r => { if (r[key]) (map[r[key]] = map[r[key]] || []).push(r.domain); });
        return Object.entries(map).filter(([, list]) => list.length > 1).sort((a, b) => b[1].length - a[1].length);
    };
    const groupHtml = [['registrant', 'Same registrant'], ['email', 'Same email'], ['registrar', 'Same registrar']].map(([key, label]) => {
        const groups = groupsBy(key);
        if (!groups.length) return '';
        return `
            <div>
                <h5 class="text-xs font-semibold text-gray-400 uppercase mb-2">${label}</h5>
                <div class="space-y-1.5">${groups.slice(0, 20).map(([value, list]) => `
                    <details class="bg-gray-900 rounded-lg px-3 py-2 border border-gray-800">
                        <summary class="text-sm cursor-pointer"><span class="text-gray-200">${escapeHtml(value)}</span> <span class="text-xs text-gray-500">· ${list.length} domains</span></summary>
                        <div class="mt-2">${chips(list)}</div>
                    </details>`).join('')}</div>
            </div>`;
    }).join('');
    return `
        <div class="space-y-5">
            <div class="grid grid-cols-2 md:grid-cols-3 gap-3">
                ${stat('Domains analyzed', rows.length)}
                ${stat('With WHOIS data', rows.filter(r => !r.error).length, 'text-emerald-400')}
                ${stat('Errors', rows.filter(r => r.error).length, 'text-yellow-400')}
            </div>
            ${groupHtml ? `<div class="grid grid-cols-1 lg:grid-cols-3 gap-4">${groupHtml}</div>` : '<p class="text-sm text-gray-400">No shared registrant, email or registrar between these domains.</p>'}
            ${renderTable(rows, ['domain', 'registrant', 'email', 'registrar', 'created', 'error'], 500)}
        </div>`;
}

function renderFingerprints(data) {
    const sites = Object.values((data && data.domains) || {}).filter(Boolean);
    if (!sites.length) return '<p class="text-sm text-gray-400">No website answered.</p>';
    const ids = (f) => Object.values(f.trackers || {}).flat().join(', ');
    return `<div class="space-y-2">
        <span class="text-sm font-semibold text-gray-300">${sites.length} website${sites.length === 1 ? '' : 's'} answered${(data.no_response || []).length ? ` · ${data.no_response.length} didn't` : ''}</span>
        ${renderTable(sites.map(f => ({ domain: f.domain, status: f.status, title: f.title, ips: (f.ips || []).join(', '), tech: (f.tech || []).join(', '), ids: ids(f) })),
            ['domain', 'status', 'title', 'ips', 'tech', 'ids'])}
    </div>`;
}

function renderWhoisHistory(data) {
    const records = (data && data.records) || [];
    if (!records.length) return renderValue(data);
    const contacts = ((data.analysis || {}).contacts || []).filter(c => !c.privacy);
    const nsHtml = nsLookupSuggestion(records.map(r => {
        const date = String((r.audit && r.audit.updatedDate) || r.updatedDateISO8601 || r.createdDateISO8601 || '').slice(0, 10);
        return { servers: r.nameServers || [], first_seen: date, last_seen: date };
    }), { compact: true });
    return `
        <div class="space-y-3">
            <span class="text-sm font-semibold text-gray-300">${records.length} historical record${records.length === 1 ? '' : 's'}</span>
            ${contacts.length ? `<div><h5 class="text-xs font-semibold text-gray-400 uppercase mb-2">Real contacts ever listed</h5>
                <div class="space-y-1.5">${contacts.map(c => `<div class="flex items-center gap-2 flex-wrap text-sm">
                    <span class="text-gray-200">${escapeHtml([c.name, c.organization].filter(Boolean).join(' · ') || 'Unnamed')}</span>
                    ${c.email ? pivotChip('email', c.email) : ''}${c.telephone ? pivotChip('phone', c.telephone) : ''}
                    <span class="text-xs text-gray-500">${escapeHtml((c.roles || []).join(', '))} · ${escapeHtml(c.first_seen || '?')} → ${escapeHtml(c.last_seen || '?')}</span>
                </div>`).join('')}</div></div>` : ''}
            ${nsHtml ? `<div><h5 class="text-xs font-semibold text-gray-400 uppercase mb-2">Same name servers</h5><div class="bg-gray-900 rounded-lg border border-gray-800">${nsHtml}</div></div>` : ''}
            ${renderTable(records.map(r => ({
                updated: (r.updatedDateISO8601 || r.audit?.updatedDate || '').slice(0, 10),
                created: (r.createdDateISO8601 || '').slice(0, 10),
                expires: (r.expiresDateISO8601 || '').slice(0, 10),
                registrar: r.registrarName,
                registrant: r.registrantContact && (r.registrantContact.name || r.registrantContact.organization),
                email: r.registrantContact && r.registrantContact.email,
                name_servers: (r.nameServers || []).join(', '),
            })))}
        </div>`;
}

function renderWhoisRecord(data) {
    if (!data || typeof data !== 'object') return renderValue(data);
    const { domain_raw_text, ip_raw_text, ...fields } = data;
    return `${renderValue(fields)}${domain_raw_text ? `<details class="mt-3"><summary class="text-xs text-gray-500 cursor-pointer">Raw WHOIS</summary><pre class="mt-2 bg-gray-950 rounded-lg p-3 text-xs text-gray-400 whitespace-pre-wrap break-all max-h-80 overflow-y-auto">${escapeHtml(domain_raw_text)}</pre></details>` : ''}`;
}

function renderDnsRecon(data) {
    if (!data || typeof data !== 'object') return renderValue(data);
    const summary = data.summary || {};
    const subdomains = (data.subdomains || []).map(s => typeof s === 'string' ? { name: s } : s);
    const records = Object.entries(data.dns_records || {}).filter(([, v]) => v && v.length);
    const intel = data.intel || {};
    const whois = data.whois_info || {};
    const emails = [...new Set([...(intel.emails || []), ...(intel.cert_emails || []),
        ...((intel.dmarc || {}).report_emails || []), ...[].concat(whois.emails || [])].map(e => String(e).toLowerCase()))];
    const networks = {};
    (data.hosting || []).forEach(h => {
        const key = h.as_name || 'Unknown network';
        (networks[key] = networks[key] || []).push(h.ip);
    });
    const field = (label, value) => value ? `<div><div class="text-xs text-gray-500">${escapeHtml(label)}</div><div class="text-sm text-gray-200">${escapeHtml(value)}</div></div>` : '';
    return `
        <div class="space-y-5">
            <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
                ${stat('Domain', data.domain || data.target_domain)}
                ${stat('Names found', summary.total_subdomains ?? subdomains.length, 'text-purple-400')}
                ${stat('Resolve now', summary.resolving_subdomains ?? '—', 'text-blue-400')}
                ${stat('Respond over HTTP', summary.alive_subdomains ?? subdomains.filter(s => s.is_alive).length, 'text-emerald-400')}
            </div>
            ${data.intel ? `<div class="grid grid-cols-2 md:grid-cols-4 gap-3">
                ${field('Mail provider', (intel.mail_providers || []).join(', '))}
                ${field('DNS provider', (intel.dns_providers || []).join(', '))}
                ${field('Sends email through', ((intel.spf || {}).services || []).join(', '))}
                ${field('First certificate', intel.first_certificate)}
                ${field('Registrar', whois.registrar)}
                ${field('Registered', (whois.creation_date || '').slice(0, 10))}
                ${field('Registrant', [whois.registrant, whois.org, whois.country].filter(Boolean).join(' · '))}
            </div>` : ''}
            ${emails.length ? `<div><h5 class="text-xs font-semibold text-gray-400 uppercase mb-2">Email addresses</h5><div class="flex flex-wrap gap-1.5">${emails.map(e => pivotChip('email', e)).join('')}</div></div>` : ''}
            ${(() => {
                const sets = [{ servers: (data.dns_records || {}).NS || [], label: 'current' },
                    ...((((data.dns_history || {}).securitytrails || {}).NS) || []).map(r => ({ servers: r.values || [], first_seen: r.first_seen, last_seen: r.last_seen || 'now' }))];
                const html = nsLookupSuggestion(sets, { compact: true });
                return html ? `<div><h5 class="text-xs font-semibold text-gray-400 uppercase mb-2">Same name servers</h5><div class="bg-gray-900 rounded-lg border border-gray-800">${html}</div></div>` : '';
            })()}
            ${(intel.verifications || []).length ? `<div><h5 class="text-xs font-semibold text-gray-400 uppercase mb-2">Verification tokens</h5>${renderTable(intel.verifications, ['service', 'token'])}</div>` : ''}
            ${Object.keys(networks).length ? `<div><h5 class="text-xs font-semibold text-gray-400 uppercase mb-2">Hosting</h5><div class="space-y-2">${Object.entries(networks).map(([name, ips]) => `
                <div class="bg-gray-900 rounded-lg p-3 border border-gray-800"><div class="text-sm text-gray-200 mb-2">${escapeHtml(name)}</div><div class="flex flex-wrap gap-1.5">${ips.map(ip => pivotChip('ip', ip)).join('')}</div></div>`).join('')}</div></div>` : ''}
            ${subdomains.length ? `<div><h5 class="text-xs font-semibold text-gray-400 uppercase mb-2">Subdomains</h5>${renderTable(subdomains.map(s => ({ name: s.name, resolves: s.resolves, ips: (s.ips || []).join(', '), status_code: s.status_code, title: s.title, first_cert: s.first_cert })), ['name', 'resolves', 'ips', 'status_code', 'title', 'first_cert'])}</div>` : ''}
            ${records.length ? `<div><h5 class="text-xs font-semibold text-gray-400 uppercase mb-2">DNS records</h5><div class="grid grid-cols-1 md:grid-cols-2 gap-3">${records.map(([type, list]) => `
                <div class="bg-gray-900 rounded-lg p-3 border border-gray-800"><div class="text-xs font-bold text-blue-400 mb-2">${escapeHtml(type)}</div>${chips(list.map(String))}</div>`).join('')}</div></div>` : ''}
            ${!data.intel && whois && Object.keys(whois).length ? `<div><h5 class="text-xs font-semibold text-gray-400 uppercase mb-2">WHOIS</h5>${renderValue(whois)}</div>` : ''}
            ${data.port_scan_results && data.port_scan_results.length ? `<div><h5 class="text-xs font-semibold text-gray-400 uppercase mb-2">Open ports</h5>${renderTable(data.port_scan_results)}</div>` : ''}
        </div>`;
}

function renderUsernameSearch(data) {
    if (!data || typeof data !== 'object' || !Array.isArray(data.results)) return renderValue(data);
    const stats = data.stats || {};
    const found = data.results;
    const byCategory = {};
    found.forEach(acc => { (byCategory[acc.category || 'other'] = byCategory[acc.category || 'other'] || []).push(acc); });
    return `
        <div class="space-y-5">
            <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
                ${stat('Username', data.username)}
                ${stat('Profiles found', found.length, 'text-emerald-400')}
                ${stat('Sites checked', stats.checked ?? stats.total)}
                ${stat('Duration', stats.duration != null ? `${stats.duration}s` : '—')}
            </div>
            ${Object.entries(byCategory).sort().map(([cat, accounts]) => `
                <div>
                    <h5 class="text-xs font-semibold text-gray-400 uppercase mb-2">${escapeHtml(cat)} (${accounts.length})</h5>
                    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
                        ${accounts.map(acc => `
                            <div class="bg-gray-900 p-3 rounded-lg border border-gray-800 min-w-0">
                                <div class="flex items-center justify-between gap-2">
                                    <span class="font-semibold text-white text-sm truncate">${escapeHtml(acc.site_name || 'Site')}</span>
                                    ${safeUrl(acc.url) ? `<a href="${escapeAttr(safeUrl(acc.url))}" target="_blank" rel="noopener noreferrer" class="text-purple-400 hover:text-purple-300 shrink-0"><i data-lucide="external-link" class="w-4 h-4"></i></a>` : ''}
                                </div>
                                ${acc.profile_data && Object.keys(acc.profile_data).length ? `<details class="mt-2"><summary class="text-xs text-gray-500 cursor-pointer">Profile data</summary><div class="mt-2">${renderValue(acc.profile_data, 1)}</div></details>` : ''}
                            </div>`).join('')}
                    </div>
                </div>`).join('')}
            ${data.web_mentions && data.web_mentions.length ? `<div><h5 class="text-xs font-semibold text-gray-400 uppercase mb-2">Web mentions</h5>${renderTable(data.web_mentions, ['title', 'url', 'domain'])}</div>` : ''}
        </div>`;
}

function renderHlr(data) {
    const results = (data && data.results) || [];
    return `
        <div class="space-y-3">
            <div class="grid grid-cols-2 gap-3">
                ${stat('Numbers', results.length)}
                ${stat('Balance after lookup', data && data.balance)}
            </div>
            ${renderTable(results, ['phone', 'status', 'operator', 'region', 'mcc', 'mnc', 'imsi'])}
        </div>`;
}

function renderGitFive(data) {
    if (!data || typeof data !== 'object' || !('username' in data)) return renderValue(data);
    const emails = Object.entries(data.registered_emails || {}).map(([email, info]) => ({ email, username: info && info.username, full_name: info && info.full_name, is_target: info && info.is_target }));
    return `
        <div class="space-y-5">
            <div class="flex items-start gap-5 bg-gray-900 rounded-xl p-5 border border-gray-800">
                ${safeUrl(data.avatar_url) ? `<img src="${escapeAttr(safeUrl(data.avatar_url))}" alt="" loading="lazy" class="w-16 h-16 rounded-xl border border-gray-700 shrink-0">` : ''}
                <div class="min-w-0">
                    <div class="flex items-center gap-2 flex-wrap">
                        <h4 class="text-xl font-bold text-white">${escapeHtml(data.name || data.username)}</h4>
                        <span class="text-sm text-gray-400 font-mono">@${escapeHtml(data.username)}</span>
                        ${data.is_site_admin ? '<span class="px-2 py-0.5 text-xs bg-yellow-500 text-black rounded font-bold">Admin</span>' : ''}
                    </div>
                    ${data.bio ? `<p class="text-gray-300 text-sm mt-1">${escapeHtml(data.bio)}</p>` : ''}
                    <div class="flex flex-wrap gap-x-4 gap-y-1 mt-2 text-xs text-gray-400">
                        ${data.company ? `<span><i data-lucide="building" class="w-3.5 h-3.5 inline mr-1"></i>${escapeHtml(data.company)}</span>` : ''}
                        ${data.location ? `<span><i data-lucide="map-pin" class="w-3.5 h-3.5 inline mr-1"></i>${escapeHtml(data.location)}</span>` : ''}
                        ${data.blog ? `<span><i data-lucide="link" class="w-3.5 h-3.5 inline mr-1"></i>${link(data.blog)}</span>` : ''}
                        <span>${escapeHtml(data.nb_public_repos ?? 0)} repos · ${escapeHtml(data.nb_followers ?? 0)} followers · ${escapeHtml(data.nb_following ?? 0)} following</span>
                        ${data.created_at ? `<span>Joined ${escapeHtml(data.created_at)}</span>` : ''}
                    </div>
                </div>
            </div>
            ${emails.length ? `<div><h5 class="text-xs font-semibold text-gray-400 uppercase mb-2">Emails found (${emails.length})</h5>${renderTable(emails, ['email', 'username', 'full_name', 'is_target'])}</div>` : ''}
            ${(data.usernames || []).length ? `<div><h5 class="text-xs font-semibold text-gray-400 uppercase mb-2">Usernames</h5>${chips(data.usernames)}</div>` : ''}
            ${(data.domains || []).length ? `<div><h5 class="text-xs font-semibold text-gray-400 uppercase mb-2">Domains</h5>${chips(data.domains)}</div>` : ''}
            ${(data.ssh_keys || []).length ? `<div><h5 class="text-xs font-semibold text-gray-400 uppercase mb-2">SSH keys</h5>${chips(data.ssh_keys)}</div>` : ''}
            ${(data.repos || []).length ? `<div><h5 class="text-xs font-semibold text-gray-400 uppercase mb-2">Repositories (${data.repos.length})</h5>${renderTable(data.repos, ['name', 'main_language', 'stars', 'forks', 'is_fork'])}</div>` : ''}
        </div>`;
}

function renderVkProfile(data) {
    if (!data || typeof data !== 'object' || !Array.isArray(data.entries)) return renderValue(data);
    return `
        <div class="space-y-4">
            <span class="text-sm font-semibold text-gray-300">${data.entries.length} snapshot${data.entries.length === 1 ? '' : 's'}${(data.photos || []).length ? `, ${data.photos.length} photos` : ''}</span>
            ${renderTable(data.entries, ['year_month', 'full_name', 'username', 'city', 'country', 'birth_date', 'last_login', 'device', 'followers', 'university'])}
            ${(data.photos || []).length ? `<div><h5 class="text-xs font-semibold text-gray-400 uppercase mb-2">Photos</h5><div class="space-y-1">${data.photos.map(p => `<div class="text-xs">${link(p)}</div>`).join('')}</div></div>` : ''}
        </div>`;
}

function renderOi(data) {
    if (data && data.url) {
        return `
            <div class="bg-gray-900 p-5 rounded-xl border border-gray-800 flex items-center justify-between gap-4">
                <div class="flex items-center gap-3"><i data-lucide="file-check" class="w-8 h-8 text-emerald-400"></i><span class="text-white font-semibold">PDF report generated</span></div>
                <a href="${escapeAttr(safeUrl(data.url))}" target="_blank" class="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-sm font-semibold"><i data-lucide="download" class="w-4 h-4"></i>Open report</a>
            </div>`;
    }
    if (data && Array.isArray(data.modules)) {
        const found = data.modules.filter(m => m.registered !== false);
        if (!found.length) return '<p class="text-sm text-gray-400">No accounts found.</p>';
        return `<div class="grid grid-cols-1 md:grid-cols-2 gap-2">${found.map(m => `
            <div class="bg-gray-900 rounded-lg p-3 border border-gray-800 min-w-0">
                <div class="flex items-center justify-between gap-2"><span class="text-xs uppercase text-purple-300">${escapeHtml(m.module)}</span>
                    ${safeUrl(m.profile_url) ? link(m.profile_url, 'profile') : ''}</div>
                ${m.name ? `<div class="text-sm text-white truncate">${escapeHtml(m.name)}</div>` : ''}
                <div class="flex flex-wrap gap-1.5 mt-1">${m.username ? pivotChip('username', String(m.username)) : ''}${m.email ? pivotChip('email', String(m.email)) : ''}${m.phone ? pivotChip('phone', String(m.phone)) : ''}</div>
                ${m.created || m.last_seen || m.location ? `<div class="text-xs text-gray-500 mt-1">${escapeHtml([m.location, m.created && 'created ' + m.created, m.last_seen && 'seen ' + m.last_seen].filter(Boolean).join(' · '))}</div>` : ''}
            </div>`).join('')}</div>`;
    }
    return renderValue(data);
}

function renderCavalier(data) {
    if (!data || typeof data !== 'object') return renderValue(data);
    if (data.error) return `<p class="text-sm text-gray-400">No infostealer records for <span class="font-mono text-gray-200">${escapeHtml(data.query || '')}</span>.</p>`;
    const entries = data.stealers || data.data || [];
    if (!entries.length) return renderValue(data);
    return `
        <div class="space-y-3">
            <span class="text-sm font-semibold text-red-300">${entries.length} compromised machine${entries.length === 1 ? '' : 's'}</span>
            ${entries.map(e => `
                <div class="bg-gray-900 rounded-xl p-4 border border-red-900/40 space-y-3">
                    <div class="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
                        <div><div class="text-gray-500">Compromised</div><div class="text-gray-200">${escapeHtml((e.date_compromised || '').slice(0, 19).replace('T', ' '))}</div></div>
                        <div><div class="text-gray-500">Computer</div><div class="text-gray-200 break-all">${escapeHtml(e.computer_name)}</div></div>
                        <div><div class="text-gray-500">OS</div><div class="text-gray-200">${escapeHtml(e.operating_system)}</div></div>
                        <div><div class="text-gray-500">IP</div><div class="text-gray-200 font-mono">${escapeHtml(e.ip)}</div></div>
                    </div>
                    ${e.malware_path ? `<div class="text-xs"><span class="text-gray-500">Malware path:</span> <span class="font-mono text-gray-300 break-all">${escapeHtml(e.malware_path)}</span></div>` : ''}
                    ${(e.top_logins || []).length ? `<div><div class="text-xs text-gray-500 mb-1">Top logins</div>${chips(e.top_logins)}</div>` : ''}
                    ${(e.top_passwords || []).length ? `<div><div class="text-xs text-gray-500 mb-1">Top passwords</div>${chips(e.top_passwords)}</div>` : ''}
                    ${(e.credentials || []).length ? `<div><div class="text-xs text-gray-500 mb-1">Credentials</div>${renderTable(e.credentials, ['domain', 'username', 'url'])}</div>` : ''}
                </div>`).join('')}
        </div>`;
}

function renderGhuntProfile(data) {
    const profile = data && data.PROFILE_CONTAINER && data.PROFILE_CONTAINER.profile;
    if (!profile) return renderValue(data);
    const name = profile.names?.PROFILE?.fullname || profile.names?.PROFILE?.displayName || 'Google account';
    const email = profile.emails?.PROFILE?.value;
    const avatar = profile.profilePhotos?.PROFILE?.url;
    const gaiaId = profile.personId;
    const { profile: _ignored, ...rest } = data.PROFILE_CONTAINER;
    return `
        <div class="space-y-4">
            <div class="flex items-start gap-4 bg-gray-900 p-5 rounded-xl border border-gray-800">
                ${safeUrl(avatar) ? `<img src="${escapeAttr(safeUrl(avatar))}" alt="" loading="lazy" class="w-16 h-16 rounded-full object-cover border-2 border-purple-500/50 shrink-0">` : ''}
                <div class="space-y-1 min-w-0">
                    <h4 class="text-lg font-bold text-white">${escapeHtml(name)}</h4>
                    ${email ? `<div class="text-sm text-gray-300">${escapeHtml(email)}</div>` : ''}
                    ${gaiaId ? `<div class="text-xs text-gray-400 font-mono">Gaia ID ${escapeHtml(gaiaId)} · ${link(`https://www.google.com/maps/contrib/${encodeURIComponent(gaiaId)}/reviews`, 'Maps reviews')}</div>` : ''}
                </div>
            </div>
            ${Object.values(rest).some(Boolean) ? renderValue(rest, 1) : ''}
        </div>`;
}

function renderWebSearch(data) {
    const results = (data && data.results) || [];
    if (!results.length) return renderValue(data);
    return `
        <div class="space-y-3">
            <div class="grid grid-cols-3 gap-3">
                ${stat('Hits', data.total_results ?? results.length)}
                ${stat('Dorks', data.dorks_executed ?? '—', 'text-purple-400')}
                ${stat('Engines', (data.engines_used || []).length || '—', 'text-blue-400')}
            </div>
            <div class="space-y-2">
                ${results.slice(0, 200).map(r => `
                    <div class="bg-gray-900 p-3 rounded-lg border border-gray-800">
                        <div class="flex items-start justify-between gap-3">
                            <div class="text-sm font-semibold">${link(r.link || r.url, r.title || r.link || r.url)}</div>
                            ${r.engine ? `<span class="text-[10px] px-1.5 py-0.5 rounded bg-gray-800 text-gray-400 uppercase shrink-0">${escapeHtml(r.engine)}</span>` : ''}
                        </div>
                        ${r.snippet ? `<p class="text-xs text-gray-400 mt-1">${escapeHtml(r.snippet)}</p>` : ''}
                    </div>`).join('')}
            </div>
        </div>`;
}

function renderFaceSearch(data) {
    const list = Array.isArray(data) ? data : (data && data.results) || [];
    const query = !Array.isArray(data) && data && /^data:image\//.test(data.query_image || '') ? data.query_image : '';
    const queryHtml = query ? `<div class="flex items-center gap-3 text-xs text-gray-400 mb-3"><img src="${escapeAttr(query)}" alt="Searched face" class="w-14 h-14 rounded-lg object-cover border border-gray-700">Searched face</div>` : '';
    if (!list.length) return queryHtml + '<p class="text-sm text-gray-400">No matches.</p>';
    return queryHtml + `
        <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
            ${list.map(f => `
                <div class="bg-gray-900 rounded-lg border border-gray-800 overflow-hidden">
                    ${safeUrl(f.image_url) ? `<img src="${escapeAttr(safeUrl(f.image_url))}" alt="" loading="lazy" referrerpolicy="no-referrer" class="w-full h-32 object-cover bg-gray-800">` : ''}
                    <div class="p-2 text-xs space-y-0.5">
                        <div class="font-semibold text-white truncate">${escapeHtml(f.name || 'Match')}</div>
                        ${f.similarity_rate ? `<div class="text-emerald-400">${escapeHtml(f.similarity_rate)}% similar</div>` : ''}
                        ${f.city ? `<div class="text-gray-400 truncate">${escapeHtml(f.city)}</div>` : ''}
                        ${f.vk_id ? `<div>${pivotChip('vk', String(f.vk_id), 'vk.com/id' + f.vk_id)}</div>` : ''}
                    </div>
                </div>`).join('')}
        </div>`;
}

function renderFunstatUsers(data) {
    const users = Array.isArray(data) ? data : [data];
    return users.map(u => `
        <div class="bg-gray-900 rounded-xl p-4 border border-gray-800 flex items-center gap-4">
            <div class="w-12 h-12 rounded-full bg-purple-900/50 flex items-center justify-center text-xl shrink-0">${u.is_bot ? '🤖' : '👤'}</div>
            <div class="min-w-0">
                <div class="text-lg font-bold text-white">${escapeHtml([u.first_name, u.last_name].filter(Boolean).join(' ') || 'Unknown')}</div>
                <div class="text-sm text-gray-400">${u.username ? `${link(`https://t.me/${encodeURIComponent(u.username)}`, '@' + u.username)} · ` : ''}<span class="font-mono">ID ${escapeHtml(u.id)}</span></div>
            </div>
        </div>`).join('');
}

function renderFunstatGroups(data) {
    const groups = Array.isArray(data) ? data : [];
    return renderTable(groups.map(g => ({
        title: g.chat && g.chat.title,
        username: g.chat && g.chat.username,
        id: g.chat && g.chat.id,
        messages: g.messages_count,
        admin: g.is_admin,
        last_message: g.last_message,
    })));
}

function renderTmeProfile(p) {
    if (!p || !p.exists) return '<p class="text-gray-500 text-sm">No public t.me profile for this username.</p>';
    return `
        <div class="flex items-start gap-4">
            ${p.avatar_url ? `<a href="${escapeAttr(p.avatar_url)}" target="_blank"><img src="${escapeAttr(p.avatar_url)}" alt="Avatar" class="w-20 h-20 rounded-full object-cover border border-gray-700"></a>` : ''}
            <div class="min-w-0 text-sm space-y-1">
                <div class="text-lg font-semibold text-white">${escapeHtml(p.name || '')}</div>
                <div>${pivotChip('telegram_username', p.username, '@' + p.username)}</div>
                ${p.bio ? `<div class="text-gray-300 whitespace-pre-wrap break-words">${escapeHtml(p.bio)}</div>` : ''}
                <a href="${escapeAttr(p.link)}" target="_blank" rel="noopener noreferrer" class="text-xs text-purple-300 hover:text-white">${escapeHtml(p.link)}</a>
            </div>
        </div>`;
}

function renderFunstatMessages(messages) {
    messages = messages || [];
    if (!messages.length) return '<p class="text-sm text-gray-400">No messages.</p>';
    const limit = 300;
    return `
        <div class="space-y-2 max-h-[36rem] overflow-y-auto pr-1">
            <span class="text-sm font-semibold text-gray-300">${messages.length} message${messages.length === 1 ? '' : 's'}</span>
            ${messages.slice(0, limit).map(m => `
                <div class="bg-gray-900 p-3 rounded-lg border border-gray-800">
                    <div class="flex justify-between gap-3 text-xs text-gray-500 mb-1">
                        <span class="text-purple-300 truncate">${escapeHtml((m.group && m.group.title) || 'Unknown chat')}</span>
                        <span class="shrink-0">${escapeHtml(m.date ? new Date(m.date).toLocaleString() : '')}</span>
                    </div>
                    <div class="text-sm text-gray-200 whitespace-pre-wrap break-words">${m.text ? escapeHtml(m.text) : '<i class="text-gray-500">media / no text</i>'}</div>
                </div>`).join('')}
            ${messages.length > limit ? `<p class="text-xs text-gray-500">Showing ${limit} of ${messages.length} - open in module to browse all.</p>` : ''}
        </div>`;
}

function renderFunstatTextSearch(data) {
    const results = (data && (data.results || data.data)) || [];
    if (!results.length) return renderValue(data);
    return renderFunstatMessages(results.map(r => ({ ...r, group: r.group, text: r.text })));
}

// ----------------- ACTIONS -----------------

async function deleteResult(resultId) {
    if (!confirm('Delete this result (and any follow-ups grouped under it)? This cannot be undone.')) return;
    try {
        const response = await fetch(`/api/investigations/${investigationId}/results/${encodeURIComponent(resultId)}`, { method: 'DELETE' });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        allResults = allResults.filter(r => r.result_id !== resultId);
        openCards.delete(resultId);
        delete detailCache[resultId];
        currentInvestigation.results_count = allResults.length;
        renderHeader(currentInvestigation);
        populateModuleFilterOptions();
        renderResults();
        showTemporaryNotification('Result deleted', 'success');
    } catch (e) {
        showTemporaryNotification(`Failed to delete result: ${e.message}`, 'error');
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
    if (!confirm(`Delete "${name}" with all ${allResults.length} results and its notes? This cannot be undone.`)) return;
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
    if (e.key === 'Escape' && !document.getElementById('editInvestigationModal').classList.contains('hidden')) closeEditModal();
});
document.addEventListener('investigation:changed', () => {
    if (currentInvestigation) renderHeader(currentInvestigation);
});

// ----------------- IDENTIFIERS TAB -----------------

const entityState = { type: '', q: '', status: '', offset: 0, total: 0, loaded: false, pageSize: 200 };
const entityCache = new Map();  // key -> entity as last rendered

function setupEntitiesPanel() {
    document.getElementById('entitySearchInput').addEventListener('input', debounce(() => {
        entityState.q = document.getElementById('entitySearchInput').value.trim();
        loadEntities(true);
    }, 250));
    document.getElementById('entityStatusSelect').addEventListener('change', (e) => {
        entityState.status = e.target.value;
        loadEntities(true);
    });
    document.getElementById('entityTypeFacets').addEventListener('click', (e) => {
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
    fetch(`/api/investigations/${investigationId}/entities?limit=1`).then(r => r.json()).then(d => {
        document.getElementById('entitiesCountBadge').textContent = d.total ?? '';
    }).catch(() => {});
}

async function loadEntities(reset) {
    if (reset) entityState.offset = 0;
    const params = new URLSearchParams({ limit: entityState.pageSize, offset: entityState.offset });
    if (entityState.type) params.set('type', entityState.type);
    if (entityState.q) params.set('q', entityState.q);
    if (entityState.status) params.set('status', entityState.status);
    const list = document.getElementById('entitiesList');
    if (reset) list.innerHTML = '<p class="text-gray-400"><i class="fas fa-spinner fa-spin mr-2"></i>Loading…</p>';
    try {
        const response = await fetch(`/api/investigations/${investigationId}/entities?${params}`);
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
        entityState.loaded = true;
        entityState.total = data.total;
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
    box.innerHTML = [`<button type="button" data-facet="" class="facet ${entityState.type ? '' : 'active'}">All <span>${total.toLocaleString()}</span></button>`]
        .concat(types.map(t => `<button type="button" data-facet="${escapeAttr(t.type)}" class="facet ${entityState.type === t.type ? 'active' : ''}">${escapeHtml(t.label)} <span>${t.count.toLocaleString()}</span></button>`))
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
        ? `<span class="text-[10px] px-1.5 py-0.5 rounded bg-purple-900/50 text-purple-300" title="Looked up with ${escapeAttr(e.searched.join(', '))}">looked up</span>` : '';
    return `
        <div class="flex items-center gap-3 bg-[#14151f] border border-[#24283b] rounded-lg px-3 py-2 ${status === 'false_positive' ? 'opacity-50' : ''}" data-entity-key="${escapeAttr(e.key)}">
            <span class="text-[11px] text-gray-500 w-28 shrink-0 truncate">${escapeHtml(e.label || e.type)}</span>
            <div class="min-w-0 flex-1">
                <div class="flex items-center gap-2 flex-wrap">${pivotChip(e.type, e.value, e.display || e.value)} ${searched}</div>
                <div class="text-[11px] text-gray-500 mt-0.5 truncate">
                    ${e.found_count ? `in ${e.found_count} result${e.found_count === 1 ? '' : 's'} · ` : ''}${escapeHtml((e.services || []).join(', '))}
                </div>
            </div>
            <input type="text" data-entity-note value="${escapeAttr(e.note || '')}" placeholder="Note"
                class="hidden md:block w-56 bg-gray-900 border border-gray-800 rounded px-2 py-1 text-xs text-white focus:outline-none focus:border-purple-500">
            <div class="flex gap-1 shrink-0">${button('confirmed')}${button('important')}${button('false_positive')}</div>
        </div>`;
}

function onEntityClick(event) {
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
            method: 'PATCH', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ key, status: status === undefined ? (entity.status || null) : status, note })
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
