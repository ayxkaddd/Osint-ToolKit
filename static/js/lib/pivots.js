// Pivot chips and the pivot menu: any identifier can be looked up with another module.
import { escapeAttr, escapeHtml, refreshIcons, timeAgo } from './dom.js';
import { ENTITY_LABELS, checkExistingResults, getModules, loadResult, moduleBadges } from './history.js';
import { earlierLookups, externalSitesHtml, sharedCache, sharedExclude } from './identifiers.js';
import { currentInvestigationId, loadInvestigations, syncCurrentInvestigation } from './investigations.js';
import { refreshJobs, startJob } from './jobs.js';
import { setupLinkHtml, setupQuickLookup } from './lookup_box.js';

// ---------------------------------------------------------------------------
// Pivot menu: any identifier -> look it up with another module.
// Elements with data-pivot-type / data-pivot-value open it on click.
// ---------------------------------------------------------------------------
export let pivotMenuAnchor = null;

export function closePivotMenu() {
    document.getElementById('pivotMenu')?.remove();
    pivotMenuAnchor = null;
}

export async function openPivotMenu(type, value, anchor, options = {}) {
    closePivotMenu();
    pivotMenuAnchor = anchor;
    // earlier lookups of this identifier in the investigation results are saved to
    const investigationId = sharedExclude();
    const [allModules, lookups, sites] = await Promise.all([
        getModules(),
        earlierLookups(investigationId, type, value),
        externalSearchesFor(type),
    ]);
    const modules = allModules.filter((m) => (m.accepts || []).includes(type));
    if (pivotMenuAnchor !== anchor) return; // closed or another chip clicked while loading
    const earlierLine = (m) => {
        const earlier = lookups.filter((p) => p.service === m.service);
        if (!earlier.length) return '';
        const last = earlier[0];
        // a follow-up is shown inside its parent on the investigation page
        const href =
            m.page && !last.child_id
                ? `${m.page}?load_result=${encodeURIComponent(last.result_id)}&investigation=${encodeURIComponent(investigationId)}`
                : `/api/investigations/${encodeURIComponent(investigationId)}/view#result-${encodeURIComponent(last.result_id)}`;
        // which lookup it was: modules can share where they save (WHOIS and WHOIS history)
        const what = typeof methodLabel === 'function' ? methodLabel(last.method) : last.method;
        return `<div class="text-[11px] text-emerald-300/90 mt-0.5 truncate" title="Already in this investigation">
            <i class="fas fa-check mr-1"></i>${escapeHtml(what)} · ${escapeHtml(timeAgo(last.timestamp))}${earlier.length > 1 ? ` (${earlier.length} times)` : ''}
            · <a href="${escapeAttr(href)}" data-earlier-open class="underline hover:text-white">open</a></div>`;
    };
    const menu = document.createElement('div');
    menu.id = 'pivotMenu';
    menu.className = 'fixed z-[70] w-80 bg-gray-900 border border-gray-700 rounded-xl shadow-2xl text-sm slide-in';
    const rows = modules.length
        ? modules
              .map(
                  (m) => `
        <div class="px-3 py-2 flex items-center justify-between gap-2 hover:bg-gray-800/70">
            <div class="min-w-0">
                <div class="text-white truncate">${escapeHtml(m.name)}</div>
                <div class="flex items-center gap-1.5 mt-0.5">${moduleBadges(m)}${m.ready ? '' : setupLinkHtml(m)}</div>
                ${earlierLine(m)}
            </div>
            <div class="flex gap-1.5 shrink-0">
                <button type="button" data-pivot-run="${escapeAttr(m.id)}" ${m.ready ? '' : 'disabled'}
                    class="px-2 py-1 rounded bg-purple-700 hover:bg-purple-600 disabled:opacity-40 disabled:cursor-not-allowed text-xs"
                    title="${m.ready ? 'Run in the background' : escapeAttr((m.problems || []).join('; '))}">Run</button>
                <a href="${escapeAttr(`${m.page}?q=${encodeURIComponent(value)}&t=${encodeURIComponent(type)}`)}"
                    class="px-2 py-1 rounded bg-gray-800 hover:bg-gray-700 text-xs" title="Open the module with this value">Open</a>
            </div>
        </div>`
              )
              .join('')
        : '<div class="px-3 py-3 text-gray-500">No module looks up this type yet.</div>';
    const shared = sharedCache.get(`${type}:${value}`) || [];
    const sharedRows = shared.length
        ? `<div class="px-3 py-2 border-b border-gray-700 text-xs">
            <div class="text-gray-500 mb-1"><i class="fas fa-folder-open mr-1 text-amber-300"></i>Also in other investigations</div>
            <div class="flex flex-wrap gap-1.5">${shared
                .slice(0, 8)
                .map(
                    (p) =>
                        `<a href="${escapeAttr(`/api/investigations/${encodeURIComponent(p.investigation_id)}/view?identifier=${encodeURIComponent(value)}#identifiers`)}"
                    class="px-2 py-0.5 rounded bg-amber-900/30 border border-amber-700/50 text-amber-200 hover:border-amber-400"
                    title="${escapeAttr(`${p.searched ? 'Looked up' : 'Found'} there${p.results ? ` · ${p.results} result${p.results === 1 ? '' : 's'}` : ''}`)}">${escapeHtml(p.name)}</a>`
                )
                .join(
                    ''
                )}${shared.length > 8 ? `<span class="text-gray-500">+${shared.length - 8} more</span>` : ''}</div>
        </div>`
        : '';
    menu.innerHTML = `
    <div class="px-3 py-2.5 border-b border-gray-700">
        <div class="text-[11px] uppercase tracking-wider text-gray-500">${escapeHtml(ENTITY_LABELS[type] || type)}</div>
        <div class="font-mono text-purple-200 break-all">${escapeHtml(value)}</div>
    </div>
    ${sharedRows}
    <div class="max-h-80 overflow-y-auto custom-scrollbar py-1">${rows}</div>
    ${externalSitesHtml(sites, type, value)}
    <div class="px-3 py-2 border-t border-gray-700 flex justify-between text-xs">
        <button type="button" data-copy="${escapeAttr(value)}" class="text-gray-400 hover:text-white"><i class="fas fa-copy mr-1"></i>Copy</button>
        <a href="/lookup?q=${encodeURIComponent(value)}" class="text-purple-300 hover:text-white">All lookups for this →</a>
    </div>`;
    document.body.appendChild(menu);

    const rect = anchor.getBoundingClientRect();
    const top = Math.min(rect.bottom + 6, window.innerHeight - menu.offsetHeight - 8);
    const left = Math.min(Math.max(8, rect.left), window.innerWidth - menu.offsetWidth - 8);
    menu.style.top = `${Math.max(8, top)}px`;
    menu.style.left = `${left}px`;

    menu.addEventListener('click', async (event) => {
        const run = event.target.closest('[data-pivot-run]');
        if (run) {
            run.disabled = true;
            await startJob(run.dataset.pivotRun, type, value, options.parentResultId || null);
            closePivotMenu();
        }
    });
}

// The dashboard's lists (resources.json plus plugins): {modules, ext_res}, fetched once per page
let resourcesPromise = null;

export function getResources() {
    resourcesPromise =
        resourcesPromise ||
        fetch('/api/resources/')
            .then((r) => (r.ok ? r.json() : {}))
            .catch(() => ({}));
    return resourcesPromise;
}

// External resources that open on a kind of identifier: {name, url, template}
export function externalSearchesFor(type) {
    return getResources().then((resources) =>
        (resources.ext_res || [])
            .filter((r) => r.search && r.search[type])
            .map((r) => ({ name: r.name, url: r.url, template: r.search[type] }))
    );
}

// Chip for an identifier that opens the pivot menu
export function pivotChip(type, value, label = null) {
    return `<button type="button" data-pivot-type="${escapeAttr(type)}" data-pivot-value="${escapeAttr(value)}"
      class="pivot-chip" title="Look up with another module">${escapeHtml(label || value)}<i class="fas fa-chevron-down"></i></button>`;
}

// An identifier in a result (an email in a list, a username in a heading): a pivot chip
// when the value has that type's shape, plain text otherwise (masked or partial values).
// pivotText("email", "a@b.c") / pivotText("username", handle, "@" + handle)
// Shapes a value must have to be offered as that type (masked or partial values stay plain text)
const PIVOT_SHAPES = {
    email: /^[^\s@*]+@[^\s@*]+\.[^\s@*]+$/,
    ip: /^(\d{1,3}\.){3}\d{1,3}$|^[0-9a-f]*:[0-9a-f:]+$/i,
    domain: /^(?!-)(?:[a-z0-9-]+\.)+[a-z]{2,}$/i,
    url: /^https?:\/\/[^\s*]+$/i,
    phone: /^\+?[\d][\d\s().-]{5,}\d$/,
    username: /^@?[\w.-]{2,64}$/,
    telegram_username: /^@?[\w]{3,64}$/,
    telegram_id: /^\d{5,15}$/,
    gaia_id: /^\d{15,25}$/,
    // 2-4 words of letters (any alphabet), initials allowed: "John Smith", "Петренко Олександр Іванович"
    name: /^(?=.*\p{L}{2}.*\s.*\p{L}{2})[\p{L}][\p{L}'’ʼ.-]*(?:\s+[\p{L}][\p{L}'’ʼ.-]*){1,3}$/u,
};

// The type a value can be offered as, or null (a "username" that is an email is an email)
export function pivotTypeFor(type, value) {
    const text = String(value ?? '').trim();
    if (!type || !text) return null;
    if ((type === 'username' || type === 'telegram_username') && text.includes('@') && !text.startsWith('@'))
        type = 'email';
    const shape = PIVOT_SHAPES[type];
    return shape && !shape.test(text) ? null : type;
}

export function pivotText(type, value, label = null) {
    if (value === undefined || value === null || value === '') return escapeHtml(label ?? '');
    const text = String(value).trim();
    type = pivotTypeFor(type, text);
    if (!type) return escapeHtml(label ?? value);
    return pivotChip(
        type,
        type === 'username' || type === 'telegram_username' ? text.replace(/^@/, '') : text,
        label ?? text
    );
}

// A Telegram account's "first last" name: a pivot chip when it reads as a person's name
// (emoji and decorated names stay plain text)
export function telegramName(user) {
    return pivotText('name', [user && user.first_name, user && user.last_name].filter(Boolean).join(' ').trim());
}

// A login that is an email or a username
export function pivotLogin(value, label = null) {
    return pivotText(String(value ?? '').includes('@') ? 'email' : 'username', value, label);
}

// Identifier type a field name implies (same idea as services/entities.py _key_hint)
export function pivotKeyType(key) {
    const k = String(key ?? '')
        .toLowerCase()
        .replace(/[\s-]+/g, '_');
    if (k.includes('email') || k === 'mail' || k === 'e_mail') return 'email';
    if (/phone|msisdn|mobile|^tel$|telephone/.test(k)) return 'phone';
    if (
        /^(username|user_name|login|screen_name|nickname|handle|usernames|twitter|twitter_username|github|instagram|tiktok)$/.test(
            k
        )
    )
        return 'username';
    if (/^(telegram|telegram_username|tg_username)$/.test(k)) return 'telegram_username';
    if (/^(telegram_id|tg_id|user_id_telegram)$/.test(k)) return 'telegram_id';
    if (/^(domain|domains|hostname|hostnames|host|hosts|subdomain|subdomains)$/.test(k) || k.endsWith('_domain'))
        return 'domain';
    if (/^(ip|ip_address|ipaddress|ip_addr|ips)$/.test(k)) return 'ip';
    if (/gaia/.test(k) || k === 'personid') return 'gaia_id';
    // a person's whole name ("name" alone is as often a site or a file: callers pass the type)
    if (
        /^(full_?name|display_?name|real_?name|person_name|owner_name|registrant_name|contact_name|sender_name|author_name|normalized_name|fio|фио|піб|ф\.и\.(_\(нормал\.\))?)$/.test(
            k
        )
    )
        return 'name';
    return null;
}

// A result field's value: clickable when the field or the value is an identifier
// (emails and +phones are recognised by shape whatever the field is called)
export function pivotField(key, value, label = null) {
    if (value === undefined || value === null || typeof value === 'object') return escapeHtml(label ?? value ?? '');
    const text = String(value).trim();
    let type = pivotKeyType(key);
    if (!type && PIVOT_SHAPES.email.test(text)) type = 'email';
    else if (!type && text.startsWith('+') && PIVOT_SHAPES.phone.test(text)) type = 'phone';
    return type ? pivotText(type, text, label) : escapeHtml(label ?? value);
}

// Free text (a snippet, bio or message): escaped, with the emails and +phone numbers in it clickable.
// known: identifiers the server found in this text [{type, value, display}] (things added by hand:
// names, numbers written without "+"), made clickable where they are written.
export const TEXT_IDENTIFIER_RE = /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}|\+\d[\d\s().-]{7,18}\d/g;

export function pivotInText(text, known = []) {
    const source = String(text ?? '');
    const spans = [];
    for (const match of source.matchAll(TEXT_IDENTIFIER_RE)) {
        const found = match[0];
        spans.push({
            start: match.index,
            end: match.index + found.length,
            html: found.includes('@')
                ? pivotText('email', found)
                : pivotText('phone', found.replace(/[\s().-]/g, ''), found),
        });
    }
    // names are matched whatever their case (ПЕТРЕНКО Олександр is shown as written)
    const lower = source.toLowerCase();
    const haystack = lower.length === source.length ? lower : source;
    (known || []).forEach((k) => {
        if (k.type === 'text') return;
        // every way it is written there ("067 123 45 67" and "+380671234567")
        new Set([...(k.written || []), k.display || k.value].map(String)).forEach((shown) => {
            if (shown.length < 3) return;
            const needle = haystack === lower ? shown.toLowerCase() : shown;
            for (let at = haystack.indexOf(needle); at !== -1; at = haystack.indexOf(needle, at + needle.length)) {
                const written = source.slice(at, at + needle.length);
                spans.push({ start: at, end: at + needle.length, html: pivotChip(k.type, k.value, written) });
            }
        });
    });
    // the longest wins where two overlap (an email over the domain inside it)
    spans.sort((a, b) => a.start - b.start || b.end - b.start - (a.end - a.start));
    let out = '';
    let last = 0;
    for (const span of spans) {
        if (span.start < last) continue;
        out += escapeHtml(source.slice(last, span.start)) + span.html;
        last = span.end;
    }
    return out + escapeHtml(source.slice(last));
}

// Analytics / ads IDs BuiltWith lists the other websites of (Google Analytics, Tag Manager, AdSense)
const BUILTWITH_TAG_RE = /^(UA-\d{4,10}|G-[A-Z0-9]{8,12}|GTM-[A-Z0-9]{5,8}|pub-\d{14,20})$/;

export function builtwithTagUrl(id) {
    const tag = String(id ?? '').trim();
    return BUILTWITH_TAG_RE.test(tag) ? `https://builtwith.com/relationships/tag/${encodeURIComponent(tag)}` : null;
}

// A tracking ID in a result, with a link to the other websites that carry it when BuiltWith knows the kind
export function trackerTag(id) {
    const url = builtwithTagUrl(id);
    return `<span class="inline-flex items-center gap-1"><code class="text-purple-200">${escapeHtml(id)}</code>${
        url
            ? `<a href="${escapeAttr(url)}" target="_blank" rel="noopener noreferrer" class="text-gray-400 hover:text-white" title="Other websites with this tag (BuiltWith)"><i class="fas fa-external-link-alt text-[10px]"></i></a>`
            : ''
    }</span>`;
}

// A favicon's mmh3 hash (httpx -favicon; the number Shodan and FOFA index). FOFA lists the
// websites serving the same icon - often the same owner's other sites, or the real server
// behind a CDN. Its query, icon_hash="<hash>", goes base64-encoded in the address.
const FAVICON_HASH_RE = /^-?\d{1,11}$/;

export function fofaIconHashUrl(hash) {
    const value = String(hash ?? '').trim();
    if (!FAVICON_HASH_RE.test(value)) return null;
    return `https://en.fofa.info/result?qbase64=${encodeURIComponent(btoa(`icon_hash="${value}"`))}`;
}

// A favicon hash in a result, with a link to the other websites that show the same icon
export function faviconHashTag(hash) {
    const url = fofaIconHashUrl(hash);
    return `<span class="inline-flex items-center gap-1"><code class="text-purple-200">mmh3 ${escapeHtml(hash)}</code>${
        url
            ? `<a href="${escapeAttr(url)}" target="_blank" rel="noopener noreferrer" class="text-gray-400 hover:text-white" title="Other websites with this favicon (FOFA)"><i class="fas fa-external-link-alt text-[10px]"></i></a>`
            : ''
    }</span>`;
}

// Identifiers grouped by type, as pivot chips (investigation results and module pages)
export function identifierGroupsHtml(entities, limit = 150) {
    const byType = {};
    entities.forEach((e) => (byType[e.type] = byType[e.type] || []).push(e));
    return Object.entries(byType)
        .map(
            ([type, list]) => `
      <div class="mb-2">
        <div class="text-xs text-gray-500 mb-1">${escapeHtml(ENTITY_LABELS[type] || type)} (${list.length})</div>
        <div class="flex flex-wrap gap-1.5">
          ${list
              .slice(0, limit)
              .map((e) => pivotChip(e.type, e.value, e.display || e.value))
              .join('')}
          ${list.length > limit ? `<span class="text-xs text-gray-500">+${list.length - limit} more in the investigation's Identifiers tab</span>` : ''}
        </div>
      </div>`
        )
        .join('');
}

// ---------------------------------------------------------------------------
// Name server pairs -> "find other domains on the same name servers" (NS lookup)
// ---------------------------------------------------------------------------
// Registrar/host defaults: millions of unrelated domains share these pairs
const SHARED_NS_PROVIDERS =
    /domaincontrol\.com|registrar-servers\.com|dns-parking\.com|hostinger|bluehost|hostgator|wixdns\.net|squarespacedns|googledomains\.com|name\.com$|porkbun\.com|namebrightdns|ultradns|nic\.ru$|reg\.ru$|dnsmadeeasy|parkingcrew|sedoparking|above\.com|ztomy\.com|afternic|dan\.com|bodis\.com/i;

function normalizeNs(name) {
    return String(name || '')
        .trim()
        .toLowerCase()
        .replace(/\.$/, '');
}

// sets: [{ servers: [...], first_seen?, last_seen?, label? }] -> distinct sets, same order
function distinctNsSets(sets) {
    const seen = new Map();
    for (const set of sets) {
        const servers = [...new Set((set.servers || []).map(normalizeNs).filter(Boolean))].sort();
        if (servers.length < 2) continue;
        const key = servers.join(',');
        const prev = seen.get(key);
        if (!prev) {
            seen.set(key, { ...set, servers });
            continue;
        }
        if (set.first_seen && (!prev.first_seen || set.first_seen < prev.first_seen)) prev.first_seen = set.first_seen;
        if (set.last_seen && (!prev.last_seen || set.last_seen > prev.last_seen)) prev.last_seen = set.last_seen;
        if (set.label && !prev.label) prev.label = set.label;
    }
    return [...seen.values()];
}

function nsLookupUrl(ns1, ns2) {
    return `/ns?ns1=${encodeURIComponent(ns1)}&ns2=${encodeURIComponent(ns2)}&run=1`;
}

// Card offering an NS lookup for every distinct pair (empty string when there is none)
export function nsLookupSuggestion(sets, { compact = false } = {}) {
    const distinct = distinctNsSets(sets);
    if (!distinct.length) return '';
    const rows = distinct
        .map((set) => {
            const [ns1, ns2] = set.servers;
            const shared = set.servers.every((ns) => SHARED_NS_PROVIDERS.test(ns));
            const when = set.label || [set.first_seen, set.last_seen].filter(Boolean).join(' → ');
            return `
      <div class="flex items-center gap-3 flex-wrap py-2 border-b border-gray-800/70 last:border-0">
        <div class="min-w-0 flex-1">
          <div class="font-mono text-sm text-gray-200 break-all">${set.servers.map(escapeHtml).join(' · ')}</div>
          <div class="text-xs text-gray-500">${escapeHtml(when)}${set.servers.length > 2 ? `${when ? ' · ' : ''}searching the first two` : ''}${
              shared
                  ? `${when || set.servers.length > 2 ? ' · ' : ''}<span class="text-yellow-400/80">registrar/hosting default - shared by many unrelated domains</span>`
                  : ''
          }</div>
        </div>
        <a href="${escapeAttr(nsLookupUrl(ns1, ns2))}" target="_blank" rel="noopener"
          class="shrink-0 text-xs px-3 py-1.5 rounded-lg bg-purple-700/70 hover:bg-purple-600 text-white"><i class="fas fa-server mr-1"></i>Find domains on these name servers</a>
      </div>`;
        })
        .join('');
    return `
    <div class="${compact ? '' : 'bg-gray-900 rounded-lg border border-gray-800'} px-3">
      ${compact ? '' : `<div class="text-xs text-gray-500 pt-3">Domains on the same name server pair often share an owner (most useful for custom or per-account pairs, like Cloudflare's). Uses 2 HackerTarget queries.</div>`}
      ${rows}
    </div>`;
}

// ---------------------------------------------------------------------------
// Module page prefill: /git?q=someone fills the module's input
// ---------------------------------------------------------------------------
async function prefillFromQuery() {
    const params = new URLSearchParams(window.location.search);
    const value = params.get('q');
    if (!value || window.location.pathname === '/lookup') return;
    const modules = await getModules();
    const type = params.get('t');
    const module =
        modules.find(
            (m) => m.page === window.location.pathname && m.prefill && (!type || (m.accepts || []).includes(type))
        ) || modules.find((m) => m.page === window.location.pathname && m.prefill);
    if (!module) return;
    const input = document.querySelector(module.prefill.input);
    if (!input) return;
    input.value = value;
    input.dispatchEvent(new Event('input', { bubbles: true }));
    if (module.prefill.type_select && type) {
        const button = document.querySelector(`[data-type="${CSS.escape(type)}"]`);
        if (button) button.click();
    }
    input.focus();
}

// "/" focuses the lookup box (unless typing somewhere)
document.addEventListener('keydown', (event) => {
    if (event.key !== '/' || event.ctrlKey || event.metaKey || event.altKey) return;
    const tag = (document.activeElement && document.activeElement.tagName) || '';
    if (['INPUT', 'TEXTAREA', 'SELECT'].includes(tag) || document.activeElement?.isContentEditable) return;
    const input = document.getElementById('globalLookupInput');
    if (input) {
        event.preventDefault();
        input.focus();
    }
});

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', async () => {
    // Static data-lucide icons in templates: render them on every page, so a
    // page whose script never calls createIcons() still shows its icons
    refreshIcons();
    await syncCurrentInvestigation();
    await loadInvestigations();

    // Deep link from the investigation page: /<module>?load_result=<id>&investigation=<id>
    const params = new URLSearchParams(window.location.search);
    const deepLink = params.get('load_result');
    if (deepLink) {
        await loadResult(deepLink, params.get('investigation') || currentInvestigationId);
        history.replaceState(null, '', window.location.pathname);
    }
    checkExistingResults();
    prefillFromQuery();
    refreshJobs();
    setupQuickLookup();
    const lookupInput = document.getElementById('globalLookupInput');
    if (lookupInput && window.location.pathname === '/lookup') lookupInput.value = params.get('q') || '';
});
