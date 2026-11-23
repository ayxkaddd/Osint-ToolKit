// Module pages: their saved results, the module registry and module badges.
import { escapeAttr, escapeHtml, fmtDateTime, refreshIcons, showTemporaryNotification, timeAgo } from './dom.js';
import { currentInvestigationId } from './investigations.js';

// ---------------------------------------------------------------------------
// Module history: each tool page sets window.currentService and (optionally)
// window.loadResultIntoView(result, record). Saved results of the current
// investigation for that module can then be re-opened without re-running.
// ---------------------------------------------------------------------------
let moduleHistory = [];

function formatParameters(params) {
    if (!params) return '';
    const kwargs = params.kwargs || params;
    return Object.entries(kwargs)
        .filter(([, value]) => value !== null && value !== undefined && value !== '' && value !== false)
        .map(([key, value]) => {
            const text = typeof value === 'object' ? JSON.stringify(value) : String(value);
            const short = text.length > 80 ? text.slice(0, 80) + '…' : text;
            return `<span class="text-xs text-gray-500 mr-2">${escapeHtml(key)}: <span class="text-gray-300">${escapeHtml(short)}</span></span>`;
        })
        .join('');
}

export function removeHistoryUi() {
    document.getElementById('resultLoadNotification')?.remove();
    document.getElementById('persistentHistoryBtn')?.remove();
    moduleHistory = [];
}

export async function checkExistingResults() {
    removeHistoryUi();
    if (!currentInvestigationId || !window.currentService) return;

    try {
        const response = await fetch(
            `/api/investigations/results/legacy?service_name=${encodeURIComponent(window.currentService)}`
        );
        if (!response.ok) return;
        const data = await response.json();
        moduleHistory = data.results || [];
        if (typeof window.updateHistoryList === 'function') window.updateHistoryList(moduleHistory);
        if (moduleHistory.length === 0) return;

        showPersistentHistoryButton();
        if (typeof window.loadResultIntoView === 'function') showResultLoadNotification();
    } catch (error) {
        console.error('Error checking existing results:', error);
    }
}

function showResultLoadNotification() {
    const latest = moduleHistory[0];
    const notification = document.createElement('div');
    notification.id = 'resultLoadNotification';
    notification.className =
        'fixed bottom-20 left-6 bg-[#1a1b26] border border-purple-500/40 text-white rounded-xl shadow-2xl z-40 max-w-sm w-full slide-in';
    notification.innerHTML = `
        <div class="p-4">
            <div class="flex items-start gap-3">
                <div class="bg-purple-500/20 p-2.5 rounded-lg shrink-0"><i class="fas fa-history text-purple-400"></i></div>
                <div class="flex-1 min-w-0">
                    <h4 class="font-semibold text-sm text-white">${moduleHistory.length} saved result${moduleHistory.length > 1 ? 's' : ''} in this investigation</h4>
                    <p class="text-xs text-gray-400 mt-1 truncate">Latest: <span class="text-gray-200">${escapeHtml(latest.target || latest.method_name)}</span> · ${escapeHtml(timeAgo(latest.timestamp))}</p>
                </div>
                <button type="button" data-history-dismiss class="text-gray-500 hover:text-white p-1"><i class="fas fa-times"></i></button>
            </div>
            <div class="flex gap-2 mt-3">
                <button type="button" data-history-load="${escapeAttr(latest.result_id)}" class="flex-1 bg-purple-600 hover:bg-purple-500 px-3 py-1.5 rounded-lg text-sm font-medium">Load latest</button>
                <button type="button" data-history-open class="flex-1 bg-gray-800 hover:bg-gray-700 px-3 py-1.5 rounded-lg text-sm border border-gray-700">View all</button>
            </div>
        </div>
    `;
    document.body.appendChild(notification);
    setTimeout(() => notification.remove(), 12000);
}

function showPersistentHistoryButton() {
    if (document.getElementById('persistentHistoryBtn')) return;
    const btn = document.createElement('button');
    btn.id = 'persistentHistoryBtn';
    btn.type = 'button';
    btn.dataset.historyOpen = '';
    btn.className =
        'fixed bottom-6 left-6 bg-gray-900 hover:bg-purple-600 text-purple-300 hover:text-white border border-purple-500/40 h-12 w-12 rounded-full shadow-lg z-30 flex items-center justify-center';
    btn.title = 'Saved results for this module';
    btn.innerHTML = `<i class="fas fa-history text-lg"></i><span class="history-count">${moduleHistory.length}</span>`;
    document.body.appendChild(btn);
}

// A saved result the page's own view can't draw (an older format, a saved error):
// shown with the investigation page's renderer, which handles anything
export function showSavedResultFallback(record) {
    document.getElementById('savedResultFallback')?.remove();
    const page = document.querySelector('.page') || document.querySelector('main') || document.body;
    const card = document.createElement('div');
    card.id = 'savedResultFallback';
    card.className = 'card mb-6';
    card.innerHTML = `
    <h2 class="text-lg font-semibold text-white mb-1">Saved result</h2>
    <p class="muted-note mb-4">This result doesn't fit this page's usual layout, so it is shown as saved.</p>
    ${safeRender(record.service_name, record.method_name, record.result, record)}`;
    const lead = page.querySelector(':scope > .page-lead');
    if (lead) lead.after(card);
    else page.prepend(card);
    refreshIcons();
}

// A lookup still streaming in the background (opened from the jobs tray) comes back
// with running: true and what it has found so far; the page follows it until it's saved.
const LIVE_REFRESH_MS = 2000;

const live = { timer: null, resultId: null, signature: null, sawRunning: false };

function stopFollowingResult() {
    clearTimeout(live.timer);
    Object.assign(live, { timer: null, resultId: null, signature: null, sawRunning: false });
    document.getElementById('liveResultBanner')?.remove();
}

function showLiveResultBanner() {
    if (document.getElementById('liveResultBanner')) return;
    const banner = document.createElement('div');
    banner.id = 'liveResultBanner';
    banner.className =
        'mb-5 bg-[#1a1b26] border border-purple-500/40 rounded-xl px-4 py-2.5 flex items-center gap-3 text-sm';
    banner.innerHTML = `
        <span class="block w-2.5 h-2.5 rounded-full bg-purple-400 animate-pulse shrink-0"></span>
        <span class="flex-1 text-gray-200">This lookup is still running in the background - the page updates as results arrive.</span>
        <button type="button" data-live-stop class="shrink-0 whitespace-nowrap text-xs text-gray-400 hover:text-white border border-gray-700 rounded-lg px-2 py-1">Stop following</button>`;
    placeUnderPageTitle(banner, document.getElementById('savedResultBar'));
}

// In the page, under its title (where a saved result that doesn't fit is shown too), after `after` if given
function placeUnderPageTitle(element, after = null) {
    const page = document.querySelector('.page') || document.querySelector('main') || document.body;
    const lead = after || page.querySelector(':scope > .page-lead');
    if (lead) lead.after(element);
    else page.prepend(element);
}

// Which saved result the page shows: what was looked up, with which module and when
function showSavedResultBar(record, investigationId) {
    document.getElementById('savedResultBar')?.remove();
    const bar = document.createElement('div');
    bar.id = 'savedResultBar';
    bar.className =
        'mb-5 bg-[#1a1b26] border border-gray-700 rounded-xl px-4 py-2.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm';
    const method = typeof methodLabel === 'function' ? methodLabel(record.method_name) : record.method_name;
    const when = record.timestamp ? `${timeAgo(record.timestamp)} · ${fmtDateTime(record.timestamp)}` : '';
    const link = `/api/investigations/${encodeURIComponent(investigationId)}/view#result-${encodeURIComponent(record.result_id)}`;
    bar.innerHTML = `
        <i class="fas fa-history text-purple-400 shrink-0"></i>
        <span class="text-gray-400 shrink-0">Saved result</span>
        ${record.target ? `<span class="font-mono text-purple-200 break-all">${escapeHtml(record.target)}</span>` : ''}
        <span class="text-gray-500">${escapeHtml([method, when].filter(Boolean).join(' · '))}</span>
        ${record.partial && !record.running ? '<span class="text-[10px] uppercase px-1.5 py-0.5 rounded bg-yellow-900/60 text-yellow-300" title="The lookup was stopped before it finished">partial</span>' : ''}
        <a href="${escapeAttr(link)}" class="ml-auto text-xs text-purple-300 hover:text-white shrink-0">Open in investigation →</a>`;
    placeUnderPageTitle(bar);
}

// The page's search box shows what the loaded result looked up (when it's one value and the box is empty)
async function prefillSavedQuery(record) {
    const target = String(record.target || '').trim();
    if (!target || / \+ |, |…/.test(target)) return;
    const module = (await getModules()).find(
        (m) => m.page === window.location.pathname && m.prefill && m.service === record.service_name
    );
    const input = module && document.querySelector(module.prefill.input);
    if (input && !input.value.trim()) input.value = target;
}

export async function loadResult(resultId, investigationId = currentInvestigationId, following = false) {
    if (!investigationId || typeof window.loadResultIntoView !== 'function') return;
    if (!following) stopFollowingResult();
    else if (live.resultId !== resultId) return; // stopped, or another result was opened meanwhile
    try {
        const response = await fetch(
            `/api/investigations/${encodeURIComponent(investigationId)}/results/${encodeURIComponent(resultId)}`
        );
        if (following && live.resultId !== resultId) return;
        if (response.status === 404 && following) {
            // finished with nothing worth saving (a failed or empty lookup)
            stopFollowingResult();
            showTemporaryNotification('The lookup finished without a result to keep', 'info');
            return;
        }
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const { result: record } = await response.json();
        const signature = JSON.stringify(record.result ?? null);
        if (!following || signature !== live.signature) {
            document.getElementById('savedResultFallback')?.remove();
            try {
                window.loadResultIntoView(record.result, record);
            } catch (renderError) {
                console.error("This page can't draw the saved result:", renderError);
                showSavedResultFallback(record);
            }
            showSavedResultBar(record, investigationId);
            if (!following) prefillSavedQuery(record);
        }
        document.getElementById('resultLoadNotification')?.remove();
        document.getElementById('historyModal')?.remove();
        if (record.running) {
            Object.assign(live, { resultId, signature, sawRunning: true });
            showLiveResultBanner();
            live.timer = setTimeout(() => loadResult(resultId, investigationId, true), LIVE_REFRESH_MS);
        } else {
            const finished = following && live.sawRunning;
            stopFollowingResult();
            showTemporaryNotification(finished ? 'Lookup finished - result saved' : 'Saved result loaded', 'success');
        }
    } catch (error) {
        console.error('Error loading result:', error);
        if (following) {
            // a hiccup while following: try again rather than give up
            live.timer = setTimeout(() => loadResult(resultId, investigationId, true), LIVE_REFRESH_MS * 2);
            return;
        }
        showTemporaryNotification('Failed to load saved result', 'error');
    }
}

// Starting a search of your own on the page stops following the background one
// (and the "Saved result" bar goes: the page no longer shows that result)
function ownSearchStarted() {
    if (live.resultId) stopFollowingResult();
    document.getElementById('savedResultBar')?.remove();
}

document.addEventListener(
    'click',
    (event) => {
        if (live.resultId && event.target.closest('[data-live-stop]')) return stopFollowingResult();
        if (event.target.closest('#liveResultBanner, #savedResultBar, #historyModal, #resultLoadNotification')) return;
        if (
            event.target.closest(
                'button.btn-primary, button[id*="search" i], button[onclick*="search" i], button[type="submit"]'
            )
        )
            ownSearchStarted();
    },
    true
);

document.addEventListener(
    'keydown',
    (event) => {
        if (event.key === 'Enter' && event.target.matches('.page input, .page textarea')) ownSearchStarted();
    },
    true
);

export function showResultSelector() {
    document.getElementById('resultLoadNotification')?.remove();
    if (!moduleHistory.length) {
        showTemporaryNotification('No saved results for this module', 'info');
        return;
    }
    const canLoad = typeof window.loadResultIntoView === 'function';

    const rows = moduleHistory
        .map(
            (r) => `
        <div class="group bg-gray-800/50 hover:bg-gray-800 border border-gray-700 hover:border-purple-500/50 rounded-xl p-4 ${canLoad ? 'cursor-pointer' : ''}"
             ${canLoad ? `data-history-load="${escapeAttr(r.result_id)}"` : ''}>
            <div class="flex justify-between items-start gap-3">
                <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2 mb-1 flex-wrap">
                        <span class="font-semibold text-white truncate">${escapeHtml(r.target || r.method_name)}</span>
                        ${r.partial ? '<span class="text-[10px] uppercase px-1.5 py-0.5 rounded bg-yellow-900/60 text-yellow-300">partial</span>' : ''}
                        ${r.children && r.children.length ? `<span class="text-[10px] px-1.5 py-0.5 rounded bg-purple-900/60 text-purple-300">+${r.children.length} follow-up</span>` : ''}
                    </div>
                    <div class="text-xs text-gray-400">${escapeHtml(r.summary || '')} · ${escapeHtml(timeAgo(r.timestamp))}</div>
                    <div class="mt-1 break-all">${formatParameters(r.parameters)}</div>
                </div>
                ${canLoad ? '<i class="fas fa-chevron-right text-gray-500 group-hover:text-white mt-1"></i>' : ''}
            </div>
        </div>`
        )
        .join('');

    const modal = document.createElement('div');
    modal.id = 'historyModal';
    modal.className = 'fixed inset-0 bg-black/80 flex items-center justify-center z-50 p-4';
    modal.innerHTML = `
        <div class="bg-[#1a1b26] rounded-2xl border border-gray-700 w-full max-w-2xl shadow-2xl flex flex-col max-h-[85vh] slide-in">
            <div class="p-5 border-b border-gray-800 flex justify-between items-center">
                <div>
                    <h3 class="text-lg font-bold text-white">Saved results</h3>
                    <p class="text-sm text-gray-400 mt-0.5">${canLoad ? 'Click one to load it into this page' : 'Open the investigation page to view them'}</p>
                </div>
                <div class="flex items-center gap-2">
                    <a href="/api/investigations/${escapeAttr(currentInvestigationId)}/view" class="text-sm text-purple-300 hover:text-white px-3 py-2">Open investigation</a>
                    <button type="button" data-history-close class="bg-gray-800 hover:bg-gray-700 text-gray-400 hover:text-white h-9 w-9 rounded-lg"><i class="fas fa-times"></i></button>
                </div>
            </div>
            <div class="p-5 overflow-y-auto custom-scrollbar space-y-3">${rows}</div>
        </div>
    `;
    modal.addEventListener('click', (e) => {
        if (e.target === modal) modal.remove();
    });
    document.body.appendChild(modal);
}

document.addEventListener('click', (event) => {
    const load = event.target.closest('[data-history-load]');
    if (load) return loadResult(load.dataset.historyLoad);
    if (event.target.closest('[data-history-open]')) return showResultSelector();
    if (event.target.closest('[data-history-close]')) return document.getElementById('historyModal')?.remove();
    if (event.target.closest('[data-history-dismiss]'))
        return document.getElementById('resultLoadNotification')?.remove();
});

// Global function to fetch history for a service (can be used by templates)
export async function fetchServiceHistory(serviceName) {
    if (!currentInvestigationId) return [];
    try {
        const response = await fetch(
            `/api/investigations/results/legacy?service_name=${encodeURIComponent(serviceName)}`
        );
        const data = await response.json();
        return data.status === 'success' && data.results ? data.results : [];
    } catch (error) {
        console.error('Error fetching history:', error);
        return [];
    }
}

// ---------------------------------------------------------------------------
// Module registry (what each module accepts, cost, readiness) - cached per page
// ---------------------------------------------------------------------------
export const ENTITY_LABELS = {
    email: 'Email',
    phone: 'Phone',
    username: 'Username',
    domain: 'Domain',
    ip: 'IP address',
    url: 'URL',
    telegram_id: 'Telegram ID',
    telegram_username: 'Telegram @username',
    vk: 'VK profile',
    gaia_id: 'Gaia ID',
    bssid: 'Wi-Fi BSSID',
    crypto_btc: 'Bitcoin address',
    crypto_eth: 'Ethereum address',
    text: 'Free text',
};

let modulesPromise = null;

export function getModules(refresh = false) {
    if (!modulesPromise || refresh) {
        modulesPromise = fetch('/api/modules')
            .then((r) => (r.ok ? r.json() : { modules: [] }))
            .then((d) => d.modules || [])
            .catch(() => []);
    }
    return modulesPromise;
}

export function moduleBadges(m) {
    const cost =
        m.cost === 'paid'
            ? `<span class="text-[10px] px-1.5 py-0.5 rounded bg-yellow-900/60 text-yellow-300" title="${escapeAttr(m.cost_note || 'Uses paid credits')}">paid</span>`
            : `<span class="text-[10px] px-1.5 py-0.5 rounded bg-emerald-900/50 text-emerald-300">free</span>`;
    const speed =
        m.speed === 'slow'
            ? '<span class="text-[10px] text-gray-500">minutes</span>'
            : m.speed === 'medium'
              ? '<span class="text-[10px] text-gray-500">~1 min</span>'
              : '';
    return `${cost} ${speed}`;
}
