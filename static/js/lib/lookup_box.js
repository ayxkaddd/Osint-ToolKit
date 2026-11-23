// The header lookup box and its dropdown.
import { escapeAttr, escapeHtml, timeAgo } from './dom.js';
import { moduleBadges } from './history.js';
import { startJob } from './jobs.js';

// ---------------------------------------------------------------------------
// Lookup box dropdown: run a module on what's typed, without leaving the page.
// Enter still opens the full /lookup page.
// ---------------------------------------------------------------------------
let quickLookupTimer = null;

let quickLookupRequest = 0; // answers to anything but the latest request are dropped

function closeQuickLookup() {
    clearTimeout(quickLookupTimer);
    quickLookupRequest += 1;
    document.getElementById('globalLookupMenu')?.classList.add('hidden');
}

function quickLookupRow(candidate, m, canRun) {
    const last = (m.previous || [])[(m.previous || []).length - 1];
    const problems = (m.problems || []).join('; ');
    const openUrl = `${m.page}?q=${encodeURIComponent(candidate.value)}&t=${encodeURIComponent(candidate.type)}`;
    return `
    <div class="px-3 py-2 flex items-center justify-between gap-2 hover:bg-gray-800/70">
        <div class="min-w-0">
            <div class="text-white truncate">${escapeHtml(m.name)}</div>
            <div class="flex items-center gap-1.5 mt-0.5">${moduleBadges(m)}${m.ready ? '' : setupLinkHtml(m)}</div>
            ${last ? `<div class="text-[11px] text-amber-300 mt-0.5"><i class="fas fa-history mr-1"></i>Already looked up ${escapeHtml(timeAgo(last.timestamp))}</div>` : ''}
        </div>
        <div class="flex gap-1.5 shrink-0">
            <button type="button" data-quick-run="${escapeAttr(m.id)}" data-quick-type="${escapeAttr(candidate.type)}" data-quick-value="${escapeAttr(candidate.value)}"
                ${m.ready && canRun ? '' : 'disabled'}
                class="px-2 py-1 rounded bg-purple-700 hover:bg-purple-600 disabled:opacity-40 disabled:cursor-not-allowed text-xs"
                title="${m.ready ? (canRun ? 'Run in the background' : 'Select an investigation first') : escapeAttr(problems)}">Run</button>
            <a href="${escapeAttr(openUrl)}" class="px-2 py-1 rounded bg-gray-800 hover:bg-gray-700 text-xs" title="Open the module with this value">Open</a>
        </div>
    </div>`;
}

// For a module that can't run yet: what to do, as a link to where it is done
// ("Add the SerpAPI Key" -> Settings). The full reason is the tooltip.
export function setupLinkHtml(m) {
    const fix = (m.setup || [])[0] || { action: 'Needs setup', href: '/settings' };
    return `<a href="${escapeAttr(fix.href)}" class="text-[10px] text-amber-300 hover:text-amber-200 underline truncate" title="${escapeAttr((m.problems || []).join('; '))}">${escapeHtml(fix.action)}</a>`;
}

// A phone number typed without its country code: the full numbers it could be, to pick from
// (data-lookup-suggest carries the full number; the lookup box and /lookup both use this)
export function phoneSuggestionsHtml(suggestions) {
    if (!suggestions || !suggestions.length) return '';
    return `<div class="text-xs text-gray-400 mb-2"><i class="fas fa-phone mr-1.5 text-purple-300"></i>A phone number? Without its country code it could be any of these - pick one:</div>
    <div class="flex flex-wrap gap-1.5">${suggestions
        .map(
            (s) => `<button type="button" data-lookup-suggest="${escapeAttr(s.value)}"
            class="inline-flex items-center gap-2 px-2.5 py-1.5 rounded bg-gray-800 hover:bg-purple-700/50 border border-gray-700 text-xs">
            <span class="font-mono text-purple-200">${escapeHtml(s.display)}</span><span class="text-gray-400">${escapeHtml(s.country)}</span></button>`
        )
        .join('')}</div>`;
}

export const LOOKUP_EXAMPLES_HINT =
    "Couldn't tell what this is. Try an email, a phone number with its country code (+1 415 555 2671), an @username, a domain or an IP address.";

function renderQuickLookup(data) {
    const menu = document.getElementById('globalLookupMenu');
    const canRun = Boolean(data.investigation_id);
    const suggestions = phoneSuggestionsHtml(data.suggestions);
    const sections = data.candidates
        .map(
            (c) => `
    <div class="px-3 pt-2.5 pb-1 text-[11px] uppercase tracking-wider text-gray-500">${escapeHtml(c.label)} · <span class="font-mono normal-case text-purple-200">${escapeHtml(c.display || c.value)}</span></div>
    ${
        c.modules.length
            ? c.modules.map((m) => quickLookupRow(c, m, canRun)).join('')
            : '<div class="px-3 py-2 text-gray-500">No module looks this up yet - "All lookups" lists sites that do.</div>'
    }`
        )
        .join('');
    menu.innerHTML = `
    ${canRun ? '' : '<div class="px-3 py-2 border-b border-gray-700 text-xs text-yellow-200">Select or create an investigation to run lookups. Results are saved there.</div>'}
    <div class="max-h-96 overflow-y-auto custom-scrollbar pb-1">
        ${suggestions ? `<div class="px-3 py-2.5 border-b border-gray-800">${suggestions}</div>` : ''}
        ${sections || (suggestions ? '' : `<div class="px-3 py-3 text-gray-500">${escapeHtml(LOOKUP_EXAMPLES_HINT)}</div>`)}
    </div>
    <div class="px-3 py-2 border-t border-gray-700 text-right text-xs">
        <a href="/lookup?q=${encodeURIComponent(data.query)}" class="text-purple-300 hover:text-white">All lookups for this →</a>
    </div>`;
    menu.classList.remove('hidden');
}

async function updateQuickLookup(query) {
    const request = ++quickLookupRequest;
    try {
        const response = await fetch(`/api/lookup/detect?q=${encodeURIComponent(query)}`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        if (request === quickLookupRequest) renderQuickLookup(data);
    } catch (error) {
        console.error('Lookup detection failed:', error);
    }
}

export function setupQuickLookup() {
    const input = document.getElementById('globalLookupInput');
    const menu = document.getElementById('globalLookupMenu');
    if (!input || !menu) return;
    const schedule = () => {
        clearTimeout(quickLookupTimer);
        const query = input.value.trim();
        if (query.length < 2) {
            closeQuickLookup();
            return;
        }
        quickLookupTimer = setTimeout(() => updateQuickLookup(query), 200);
    };
    input.addEventListener('input', schedule);
    input.addEventListener('focus', schedule);
    document.getElementById('globalLookupForm').addEventListener('keydown', (event) => {
        if (event.key === 'Escape') closeQuickLookup();
    });
    document.getElementById('globalLookupForm').addEventListener('submit', closeQuickLookup);
    document.addEventListener('click', (event) => {
        if (!event.target.closest('#globalLookupForm')) closeQuickLookup();
    });
    // Stays open after a run, so several modules can be started in a row
    menu.addEventListener('click', async (event) => {
        const suggestion = event.target.closest('[data-lookup-suggest]');
        if (suggestion) {
            input.value = suggestion.dataset.lookupSuggest;
            input.focus();
            updateQuickLookup(input.value);
            return;
        }
        const run = event.target.closest('[data-quick-run]');
        if (!run) return;
        run.disabled = true;
        const job = await startJob(run.dataset.quickRun, run.dataset.quickType, run.dataset.quickValue);
        if (job) run.textContent = 'Started';
        else run.disabled = false;
    });
}
