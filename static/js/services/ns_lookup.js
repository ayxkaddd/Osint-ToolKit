window.currentService = 'ns';

const DOMAIN_PAGE = 100;

// State for the lookup currently on screen
const ns = {
    domains: [],
    whois: {},         // domain -> parsed WHOIS (or {error})
    web: {},           // domain -> web fingerprint
    noResponse: new Set(),
    resultId: null,    // saved NS lookup the analyses attach to
    clusterOf: {},     // domain -> cluster number
    showAll: false,
    open: new Set(),   // expanded domain rows
};

const els = {
    form: document.getElementById('nsForm'),
    ns1: document.getElementById('ns1Input'),
    ns2: document.getElementById('ns2Input'),
    submit: document.getElementById('submitQuery'),
    loading: document.getElementById('loading'),
    result: document.getElementById('result'),
    domainList: document.getElementById('domainList'),
    domainCount: document.getElementById('domainCount'),
    domainFilter: document.getElementById('domainFilter'),
    domainsMore: document.getElementById('domainsMore'),
    analyzeButton: document.getElementById('analyzeWhois'),
    fingerprintButton: document.getElementById('runFingerprint'),
    progress: document.getElementById('analysisProgress'),
};

// ---------------- WHOIS ----------------

// One saved/streamed WHOIS answer -> parsed record (RDAP JSON when available)
function parseWhois(whois) {
    if (!whois || whois.error) return { error: (whois && whois.error) || 'no data' };
    const rdap = NsAttribution.parseRdap(whois.domain_raw_text);
    if (rdap) return { ...rdap, raw: whois.domain_raw_text };
    // Not RDAP: the fields the server already parsed
    const contact = whois.registrant || whois.email
        ? [{ roles: ['registrant'], org: whois.registrant, email: whois.email, redacted: NsAttribution.REDACTED.test(whois.registrant || '') }] : [];
    return {
        registrar: whois.registrar, created: whois.creation_date, expires: whois.expiration_date,
        statuses: whois.statuses || [], nameservers: whois.nameservers || [], contacts: contact,
        raw: whois.domain_raw_text,
    };
}

const fmtDate = (v) => v ? String(v).slice(0, 10) : '—';
const ROLE_NAMES = { registrant: 'Registrant', administrative: 'Admin', technical: 'Tech', billing: 'Billing' };

function prettyJson(text) {
    try { return JSON.stringify(JSON.parse(text), null, 2); } catch (e) { return String(text); }
}

// Only the parts of a contact that weren't redacted ("DATA REDACTED, NY" -> "NY")
const unredacted = (v) => v && !NsAttribution.REDACTED.test(v);
const who = (c) => [c.name, c.org].filter(unredacted).filter((v, i, a) => a.indexOf(v) === i).join(' · ');
const place = (c) => [...String(c.address || '').split(/,\s*/), c.country].filter(unredacted)
    .filter((v, i, a) => a.indexOf(v) === i).join(', ');

function whoisCard(w) {
    if (!w) return '<p class="text-sm text-gray-500">Run WHOIS to see the registration.</p>';
    if (w.error) return `<p class="text-sm text-red-300">WHOIS failed: ${escapeHtml(w.error)}</p>`;
    const field = (label, value) => `<div><div class="text-[11px] text-gray-500">${label}</div><div class="text-sm text-gray-200 break-words">${value || '<span class="text-gray-600">—</span>'}</div></div>`;
    const contacts = (w.contacts || []).map(c => `
        <div class="bg-gray-950/60 rounded-lg p-3 border ${c.redacted ? 'border-gray-800' : 'border-emerald-800/60'}">
            <div class="flex items-center gap-1.5 mb-1 flex-wrap">
                ${c.roles.map(r => `<span class="text-[11px] px-1.5 py-0.5 rounded bg-gray-800 text-gray-300">${escapeHtml(ROLE_NAMES[r] || r)}</span>`).join('')}
                ${c.redacted ? '<span class="text-[11px] text-gray-500">redacted / privacy</span>' : '<span class="text-[11px] text-emerald-300">real contact</span>'}
            </div>
            ${who(c) ? `<div class="text-sm text-white">${escapeHtml(who(c))}</div>` : ''}
            <div class="flex flex-wrap gap-1.5 mt-1">
                ${c.email && !c.redacted ? pivotChip('email', c.email) : (c.email ? `<span class="text-xs text-gray-500">${escapeHtml(c.email)}</span>` : '')}
                ${c.phone && !c.redacted ? pivotChip('phone', c.phone) : ''}
            </div>
            ${place(c) ? `<div class="text-xs text-gray-400 mt-1">${escapeHtml(place(c))}</div>` : ''}
        </div>`).join('');
    return `
        <div class="space-y-3">
            <div class="grid grid-cols-2 gap-3">
                ${field('Registrar', escapeHtml(w.registrar || '') + (w.registrar_iana ? ` <span class="text-xs text-gray-500">IANA ${escapeHtml(w.registrar_iana)}</span>` : ''))}
                ${field('Registered', fmtDate(w.created))}
                ${field('Last changed', fmtDate(w.updated))}
                ${field('Expires', fmtDate(w.expires))}
                ${field('Name servers', (w.nameservers || []).map(escapeHtml).join('<br>'))}
                ${field('DNSSEC', w.dnssec === null || w.dnssec === undefined ? '' : (w.dnssec ? 'signed' : 'unsigned'))}
            </div>
            ${(w.statuses || []).length ? `<div class="flex flex-wrap gap-1">${w.statuses.map(s => `<span class="text-[11px] px-1.5 py-0.5 rounded bg-gray-800 text-gray-400">${escapeHtml(s)}</span>`).join('')}</div>` : ''}
            ${contacts || '<p class="text-xs text-gray-500">No contacts published.</p>'}
            ${w.abuse_email ? `<div class="text-xs text-gray-500">Registrar abuse desk: ${escapeHtml(w.abuse_email)}</div>` : ''}
            ${w.raw ? `<details><summary class="text-xs text-gray-500 cursor-pointer">Raw response</summary>
                <pre class="mt-2 bg-gray-950 rounded-lg p-3 text-xs text-gray-400 whitespace-pre-wrap break-all max-h-72 overflow-y-auto">${escapeHtml(prettyJson(w.raw))}</pre></details>` : ''}
        </div>`;
}

// ---------------- web fingerprint ----------------

const TRACKER_NAMES = {
    google_analytics: 'Google Analytics', google_analytics_ua: 'Google Analytics (UA)', google_tag_manager: 'Tag Manager',
    adsense: 'AdSense', yandex_metrika: 'Yandex Metrika', facebook_pixel: 'Facebook pixel', hotjar: 'Hotjar',
    email: 'Emails', telegram: 'Telegram',
};

function webCard(domain) {
    const f = ns.web[domain];
    if (!f) {
        return ns.noResponse.has(domain)
            ? '<p class="text-sm text-gray-500">No HTTP response.</p>'
            : '<p class="text-sm text-gray-500">Run the fingerprint to see the website.</p>';
    }
    const field = (label, value) => value ? `<div><div class="text-[11px] text-gray-500">${label}</div><div class="text-sm text-gray-200 break-words">${value}</div></div>` : '';
    const final = safeUrl(f.final_url);
    const trackers = Object.entries(f.trackers || {}).map(([kind, ids]) => `
        <div class="text-xs"><span class="text-gray-500">${escapeHtml(TRACKER_NAMES[kind] || kind)}:</span>
            ${ids.map(id => kind === 'email' ? pivotChip('email', id)
                : kind === 'telegram' ? pivotChip('telegram_username', id.split('/')[1], id)
                : `<code class="text-purple-200">${escapeHtml(id)}</code>`).join(' ')}</div>`).join('');
    return `
        <div class="space-y-3">
            <div class="grid grid-cols-2 gap-3">
                ${field('Opens', final ? `<a href="${escapeAttr(final)}" target="_blank" rel="noopener noreferrer" class="text-blue-400 hover:underline break-all">${escapeHtml(f.final_url)}</a> <span class="text-xs text-gray-500">${escapeHtml(f.status || '')}</span>` : '')}
                ${field('Title', escapeHtml(f.title || ''))}
                ${field('Server', escapeHtml([f.server, f.cdn && `CDN ${f.cdn}`].filter(Boolean).join(' · ')))}
                ${field('Network', escapeHtml(f.asn || ''))}
                ${field('IPs', (f.ips || []).map(ip => pivotChip('ip', ip)).join(' '))}
                ${field('Technologies', escapeHtml((f.tech || []).join(', ')))}
                ${field('Certificate', f.cert ? escapeHtml(`${f.cert.subject || '?'} · ${f.cert.issuer || ''} · from ${fmtDate(f.cert.not_before)}`) : '')}
                ${field('Favicon / JARM', escapeHtml([f.favicon && `mmh3 ${f.favicon}`, f.jarm && `JARM ${f.jarm.slice(0, 16)}…`].filter(Boolean).join(' · ')))}
            </div>
            ${trackers ? `<div class="space-y-1">${trackers}</div>` : ''}
        </div>`;
}

// ---------------- attribution ----------------

function renderAttribution() {
    const signals = NsAttribution.buildSignals(ns.whois, ns.web);
    const groups = NsAttribution.clusters(signals);
    ns.clusterOf = {};
    groups.forEach((g, i) => g.domains.forEach(d => { ns.clusterOf[d] = i + 1; }));
    const hasData = Object.keys(ns.whois).length || Object.keys(ns.web).length;

    const strengthCls = { strong: 'text-emerald-300', medium: 'text-yellow-300', weak: 'text-gray-400' };
    const confCls = { high: 'bg-emerald-900/50 text-emerald-300', likely: 'bg-yellow-900/40 text-yellow-300', possible: 'bg-gray-800 text-gray-300' };
    const reason = (s) => `<div class="text-xs"><span class="${strengthCls[s.strength]}">${escapeHtml(s.label)}</span>
        <span class="text-gray-300 break-all">${escapeHtml(s.value)}</span> <span class="text-gray-600">(${s.domains.length})</span></div>`;

    document.getElementById('clustersSection').classList.toggle('hidden', !hasData);
    document.getElementById('clustersCount').textContent = groups.length ? String(groups.length) : '';
    document.getElementById('clusters').innerHTML = groups.length ? `<div class="space-y-3">${groups.map((g, i) => `
        <div class="bg-gray-900 rounded-lg p-4 border border-gray-800">
            <div class="flex items-center justify-between gap-2 mb-2">
                <span class="text-sm font-semibold text-white">Group ${i + 1} · ${g.domains.length} domains</span>
                <span class="text-[11px] px-2 py-0.5 rounded-full ${confCls[g.confidence]}">${g.confidence} same owner</span>
            </div>
            <div class="flex flex-wrap gap-1.5 mb-3">${g.domains.map(d => pivotChip('domain', d)).join('')}</div>
            <div class="space-y-0.5">${g.reasons.slice(0, 12).map(reason).join('')}</div>
        </div>`).join('')}</div>`
        : '<p class="text-sm text-gray-500">No domains share an owner signal yet. Run both WHOIS and the website fingerprint for the full picture.</p>';

    document.getElementById('signalsSection').classList.toggle('hidden', !signals.length);
    document.getElementById('signalsCount').textContent = signals.length ? String(signals.length) : '';
    document.getElementById('signals').innerHTML = `
        <p class="text-xs text-gray-500 mb-3"><span class="text-emerald-300">Strong</span> signals are set per account (analytics IDs, contacts, a certificate naming several of the domains).
            <span class="text-yellow-300">Medium</span> ones link domains unless most of the set shares them (parking pages, templates).
            <span class="text-gray-400">Weak</span> ones (IP, server config, stack, registrar) never link on their own.</p>
        <div class="space-y-1.5">${signals.map(s => `
            <details class="bg-gray-900 rounded-lg px-3 py-2 border border-gray-800">
                <summary class="cursor-pointer flex items-center gap-2 text-sm">
                    <span class="${strengthCls[s.strength]} shrink-0">${escapeHtml(s.label)}</span>
                    <span class="text-gray-300 truncate">${escapeHtml(s.value)}</span>
                    ${s.common ? '<span class="text-[11px] text-gray-500 shrink-0">common - not used</span>' : ''}
                    <span class="ml-auto text-xs text-gray-500 shrink-0">${s.domains.length} domains</span>
                </summary>
                <div class="flex flex-wrap gap-1.5 mt-2">${s.domains.map(d => pivotChip('domain', d)).join('')}</div>
            </details>`).join('')}</div>`;
    renderDomains();
}

// ---------------- domain list ----------------

function domainSearchText(domain) {
    const w = ns.whois[domain] || {};
    const f = ns.web[domain] || {};
    return [domain, w.registrar, f.title, f.server, ...(f.tech || []), ...(f.ips || []),
        ...(w.contacts || []).flatMap(c => [c.name, c.org, c.email])].filter(Boolean).join(' ').toLowerCase();
}

function domainRow(domain) {
    const w = ns.whois[domain];
    const f = ns.web[domain];
    const cluster = ns.clusterOf[domain];
    const status = f ? f.status : null;
    const statusCls = !status ? '' : status < 300 ? 'bg-emerald-900/50 text-emerald-300' : status < 400 ? 'bg-yellow-900/50 text-yellow-300' : 'bg-red-900/40 text-red-300';
    const realContact = w && (w.contacts || []).some(c => !c.redacted);
    const open = ns.open.has(domain);
    return `
        <div class="bg-gray-900 rounded-lg border border-gray-800" data-domain-row="${escapeAttr(domain)}">
            <button type="button" class="w-full text-left px-3 py-2 flex items-center gap-2 flex-wrap" data-toggle-domain="${escapeAttr(domain)}">
                <i class="fas fa-chevron-${open ? 'down' : 'right'} text-[10px] text-gray-500 w-3"></i>
                <span class="text-sm text-white break-all">${escapeHtml(domain)}</span>
                ${cluster ? `<span class="text-[11px] px-1.5 py-0.5 rounded bg-purple-900/50 text-purple-200">group ${cluster}</span>` : ''}
                ${realContact ? '<span class="text-[11px] px-1.5 py-0.5 rounded bg-emerald-900/50 text-emerald-300">real WHOIS contact</span>' : ''}
                ${status ? `<span class="text-[11px] px-1.5 py-0.5 rounded ${statusCls}">${escapeHtml(status)}</span>` : ''}
                <span class="text-xs text-gray-400 truncate flex-1 min-w-0">${escapeHtml((f && f.title) || '')}</span>
                <span class="text-xs text-gray-500 shrink-0">${escapeHtml([w && w.registrar, w && w.created && fmtDate(w.created)].filter(Boolean).join(' · '))}</span>
            </button>
            ${open ? `<div class="px-4 pb-4 pt-3 border-t border-gray-800">
                <div class="mb-3">${pivotChip('domain', domain)}</div>
                <div class="grid grid-cols-1 lg:grid-cols-2 gap-5">
                    <div><div class="text-xs font-semibold text-gray-400 uppercase mb-2">WHOIS</div>${whoisCard(w)}</div>
                    <div><div class="text-xs font-semibold text-gray-400 uppercase mb-2">Website</div>${webCard(domain)}</div>
                </div>
            </div>` : ''}
        </div>`;
}

function renderDomains() {
    const q = els.domainFilter.value.trim().toLowerCase();
    // Grouped domains first, so related ones sit together
    const list = ns.domains
        .filter(d => !q || domainSearchText(d).includes(q))
        .sort((a, b) => (ns.clusterOf[a] || 1e9) - (ns.clusterOf[b] || 1e9) || a.localeCompare(b));
    const shown = ns.showAll ? list : list.slice(0, DOMAIN_PAGE);
    els.domainList.innerHTML = shown.map(domainRow).join('')
        || `<p class="text-sm text-gray-500">${ns.domains.length ? 'Nothing matches the filter.' : 'No shared domains found.'}</p>`;
    els.domainsMore.classList.toggle('hidden', shown.length >= list.length);
    els.domainsMore.textContent = `Show all ${list.length}`;
}

function showDomains(domains) {
    ns.domains = domains;
    ns.whois = {};
    ns.web = {};
    ns.noResponse = new Set();
    ns.open = new Set();
    ns.showAll = false;
    els.domainCount.textContent = String(domains.length);
    els.analyzeButton.disabled = els.fingerprintButton.disabled = domains.length === 0;
    els.result.classList.remove('hidden');
    renderAttribution();
}

// ---------------- requests ----------------

async function runLookup() {
    const ns1 = els.ns1.value.trim();
    const ns2 = els.ns2.value.trim();
    if (!ns1 || !ns2) {
        showTemporaryNotification('Enter both name servers', 'error');
        return;
    }
    els.loading.classList.remove('hidden');
    els.result.classList.add('hidden');
    els.submit.disabled = true;
    ns.resultId = null;
    try {
        const response = await fetch(`/api/ns/search?ns1=${encodeURIComponent(ns1)}&ns2=${encodeURIComponent(ns2)}`);
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
        ns.resultId = window.savedResultId(response);
        showDomains(Array.isArray(data) ? data : []);
    } catch (error) {
        showTemporaryNotification(`NS lookup failed: ${error.message}`, 'error');
    } finally {
        els.loading.classList.add('hidden');
        els.submit.disabled = false;
    }
}

// POST the domain list and read the NDJSON answer line by line
async function streamAnalysis(url, label, onEvent) {
    const progressText = els.progress.querySelector('span');
    els.analyzeButton.disabled = els.fingerprintButton.disabled = true;
    els.progress.classList.remove('hidden');
    progressText.textContent = `${label}: starting…`;
    try {
        const headers = { 'Content-Type': 'application/json' };
        if (ns.resultId) headers['X-Parent-Result-ID'] = ns.resultId;
        const response = await fetch(url, { method: 'POST', headers, body: JSON.stringify({ domains: ns.domains }) });
        if (!response.ok || !response.body) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${response.status}`);
        }
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let lastPaint = 0;
        for (;;) {
            const { value, done } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop();
            for (const line of lines) {
                if (!line.trim()) continue;
                const event = JSON.parse(line);
                if (event.type === 'error') throw new Error(event.error);
                onEvent(event);
                const now = performance.now();
                if (event.done && now - lastPaint > 400) {
                    progressText.textContent = `${label}: ${event.done}/${event.total}`;
                    renderAttribution();
                    lastPaint = now;
                }
            }
        }
        renderAttribution();
    } catch (error) {
        showTemporaryNotification(`${label} failed: ${error.message}`, 'error');
    } finally {
        els.analyzeButton.disabled = els.fingerprintButton.disabled = false;
        els.progress.classList.add('hidden');
    }
}

function runWhoisAnalysis() {
    ns.whois = {};
    return streamAnalysis('/api/ns/whois-analysis', 'WHOIS', (event) => {
        if (event.type === 'domain') ns.whois[event.domain] = parseWhois(event.ok ? event.whois : { error: event.error });
    });
}

function runFingerprint() {
    ns.web = {};
    ns.noResponse = new Set();
    return streamAnalysis('/api/ns/fingerprint', 'Fingerprint', (event) => {
        if (event.type === 'domain') ns.web[event.domain] = event.fingerprint;
        else if (event.type === 'complete') ns.noResponse = new Set(event.no_response || []);
    });
}

// Saved result (from the history panel). `record` carries the grouped analyses.
window.loadResultIntoView = function (data, record) {
    const domains = Array.isArray(data) ? data : (data && data.domains ? Object.keys(data.domains) : []);
    const params = (record && record.parameters && record.parameters.kwargs) || {};
    if (params.ns1) els.ns1.value = params.ns1;
    if (params.ns2) els.ns2.value = params.ns2;
    ns.resultId = record ? record.result_id : null;
    showDomains(domains);

    const children = (record && record.children) || [];
    const latest = (method) => children.filter(c => c.method_name === method).pop();
    const whoisChild = latest('whois_analysis');
    const whoisDomains = whoisChild ? whoisChild.result.domains : (data && data.domains && !Array.isArray(data) ? data.domains : null);
    Object.entries(whoisDomains || {}).forEach(([d, w]) => { ns.whois[d] = parseWhois(w); });
    const fpChild = latest('fingerprint');
    if (fpChild && fpChild.result) {
        ns.web = { ...(fpChild.result.domains || {}) };
        ns.noResponse = new Set(fpChild.result.no_response || []);
    }
    renderAttribution();
};

els.form.addEventListener('submit', (e) => {
    e.preventDefault();
    runLookup();
});
els.analyzeButton.addEventListener('click', runWhoisAnalysis);
els.fingerprintButton.addEventListener('click', runFingerprint);
els.domainFilter.addEventListener('input', () => { ns.showAll = false; renderDomains(); });
els.domainsMore.addEventListener('click', () => { ns.showAll = true; renderDomains(); });
els.domainList.addEventListener('click', (e) => {
    const toggle = e.target.closest('[data-toggle-domain]');
    if (!toggle) return;
    const domain = toggle.dataset.toggleDomain;
    if (ns.open.has(domain)) ns.open.delete(domain);
    else ns.open.add(domain);
    const row = els.domainList.querySelector(`[data-domain-row="${CSS.escape(domain)}"]`);
    if (row) row.outerHTML = domainRow(domain);
});

// Opened from a "find domains on these name servers" suggestion
(function prefillPair() {
    const params = new URLSearchParams(window.location.search);
    if (!params.get('ns1') || !params.get('ns2') || params.get('load_result')) return;
    els.ns1.value = params.get('ns1');
    els.ns2.value = params.get('ns2');
    if (params.get('run') === '1') runLookup();
})();
