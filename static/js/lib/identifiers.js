// Identifiers seen elsewhere: other sites, earlier lookups, other investigations.
import { escapeAttr, escapeHtml, safeUrl } from './dom.js';
import { ENTITY_LABELS } from './history.js';
import { currentInvestigationId } from './investigations.js';
import { closePivotMenu, openPivotMenu, pivotMenuAnchor } from './pivots.js';

// "Check on another site": links that open those sites on this value (new tab)
export function externalSitesHtml(sites, type, value) {
    if (!sites.length) return '';
    const plain = type === 'telegram_username' ? String(value).replace(/^@/, '') : String(value);
    const links = sites
        .map((site) => {
            const href = safeUrl(site.template.replace('{value}', encodeURIComponent(plain)));
            if (!href) return '';
            let host = '';
            try {
                host = new URL(site.url).hostname;
            } catch (e) {
                // no icon then
            }
            return `<a href="${escapeAttr(href)}" target="_blank" rel="noopener noreferrer" title="${escapeAttr(`Open ${site.name} on this ${ENTITY_LABELS[type] || type}`)}"
                class="inline-flex items-center gap-1.5 px-2 py-1 rounded bg-gray-800 hover:bg-gray-700 text-xs text-gray-200">
                ${host ? `<img src="/api/oi/icon/${encodeURIComponent(host)}" alt="" class="w-3.5 h-3.5 rounded-sm" loading="lazy" data-img-error="removeImage">` : ''}${escapeHtml(site.name)}</a>`;
        })
        .join('');
    return `<div class="px-3 py-2 border-t border-gray-700">
        <div class="text-[11px] uppercase tracking-wider text-gray-500 mb-1.5">Check on another site</div>
        <div class="flex flex-wrap gap-1.5">${links}</div></div>`;
}

// Lookups of an identifier already saved in an investigation, newest first ([] if none or unknown)
export async function earlierLookups(investigationId, type, value) {
    if (!investigationId) return [];
    try {
        const params = new URLSearchParams({ type, value });
        const response = await fetch(
            `/api/investigations/${encodeURIComponent(investigationId)}/entities/lookups?${params}`
        );
        return response.ok ? (await response.json()).lookups || [] : [];
    } catch (e) {
        return [];
    }
}

document.addEventListener('click', (event) => {
    const trigger = event.target.closest('[data-pivot-type]');
    if (trigger) {
        event.preventDefault();
        event.stopPropagation();
        // a second click on the chip whose menu is open closes it
        if (trigger === pivotMenuAnchor) {
            closePivotMenu();
            return;
        }
        openPivotMenu(trigger.dataset.pivotType, trigger.dataset.pivotValue, trigger, {
            parentResultId: trigger.dataset.pivotParent || null,
        });
        return;
    }
    if (!event.target.closest('#pivotMenu')) closePivotMenu();
});

window.addEventListener('scroll', closePivotMenu, { passive: true });

// ---------------------------------------------------------------------------
// Identifiers other investigations have too: their pivot chips get a badge with the
// number of investigations, and the pivot menu links to them. Chips are checked in
// batches as they appear on the page.
// ---------------------------------------------------------------------------
export const sharedCache = new Map(); // "type:value" -> [{investigation_id, name, ...}] ([] = nowhere else)

const sharedPending = new Set();

let sharedTimer = null;

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// Results on this page belong to this investigation (the page's own, or the one recording)
export function sharedExclude() {
    const id = window.pageInvestigationId || currentInvestigationId;
    return id && UUID_RE.test(id) ? id : null;
}

function markSharedChip(chip, places) {
    if (!places || !places.length || chip.querySelector('.shared-badge')) return;
    const names = places.map((p) => p.name).join(', ');
    const badge = `<span class="shared-badge" title="${escapeAttr(`Also in: ${names}`)}"><i class="fas fa-folder-open"></i>${places.length}</span>`;
    const chevron = chip.querySelector('.fa-chevron-down');
    if (chevron) chevron.insertAdjacentHTML('beforebegin', badge);
    else chip.insertAdjacentHTML('beforeend', badge);
}

function queueSharedChips(root) {
    const chips =
        root.matches && root.matches('[data-pivot-type]') ? [root] : root.querySelectorAll('[data-pivot-type]');
    chips.forEach((chip) => {
        if (chip.dataset.sharedChecked) return;
        chip.dataset.sharedChecked = '1';
        const name = `${chip.dataset.pivotType}:${chip.dataset.pivotValue}`;
        if (sharedCache.has(name)) markSharedChip(chip, sharedCache.get(name));
        else sharedPending.add(name);
    });
    if (sharedPending.size && !sharedTimer) sharedTimer = setTimeout(flushSharedChips, 250);
}

async function flushSharedChips() {
    sharedTimer = null;
    const names = [...sharedPending].slice(0, 2000);
    names.forEach((name) => sharedPending.delete(name));
    if (sharedPending.size) sharedTimer = setTimeout(flushSharedChips, 250);
    const items = names.map((name) => {
        const split = name.indexOf(':');
        return { type: name.slice(0, split), value: name.slice(split + 1) };
    });
    try {
        const response = await fetch('/api/entities/elsewhere', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ items, exclude: sharedExclude() }),
        });
        if (!response.ok) return;
        const { matches } = await response.json();
        names.forEach((name) => sharedCache.set(name, matches[name] || []));
        if (!Object.keys(matches).length) return;
        document.querySelectorAll('[data-pivot-type]').forEach((chip) => {
            const found = matches[`${chip.dataset.pivotType}:${chip.dataset.pivotValue}`];
            if (found) markSharedChip(chip, found);
        });
    } catch (e) {
        // the badge is a hint; the page works without it
    }
}

function recheckSharedChips() {
    sharedCache.clear();
    document.querySelectorAll('.shared-badge').forEach((badge) => badge.remove());
    document.querySelectorAll('[data-shared-checked]').forEach((chip) => delete chip.dataset.sharedChecked);
    queueSharedChips(document.body);
}

document.addEventListener('investigation:changed', recheckSharedChips);

queueSharedChips(document.body);

new MutationObserver((mutations) => {
    mutations.forEach((m) =>
        m.addedNodes.forEach((node) => {
            if (node.nodeType === 1) queueSharedChips(node);
        })
    );
}).observe(document.body, { childList: true, subtree: true });
