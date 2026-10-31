// Renders a saved result's payload the way the investigation page shows it.
// Shared by the investigation page and the notes editor (result snapshots in notes).

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
    run: 'Lookup',  // plugins
};

const moduleInfo = (service) => MODULES[service] || {
    name: (service || 'unknown').replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase()),
    icon: 'terminal',
    page: null,
};
const methodLabel = (method) => METHOD_LABELS[method] || (method || '').replace(/_/g, ' ');

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
        if (typeof isPluginResult === 'function' && isPluginResult(data)) return renderPluginResult(data, record);
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
    ghunt: (data) => ghuntResultHtml(data),   // static/js/ghunt_cards.js
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

// type: the identifier type of the values (e.g. 'domain'); emails are recognised anyway
function chips(values, limit = 200, cls = 'font-mono', type = null) {
    const chip = (v) => {
        const t = pivotTypeFor(type, v) || pivotTypeFor('email', v);
        return t ? pivotChip(t, String(v).trim().replace(/^@/, ''), v)
            : `<span class="bg-gray-900 px-2 py-1 rounded-md text-xs ${cls} text-gray-200 border border-gray-800 break-all">${escapeHtml(v)}</span>`;
    };
    const shown = values.slice(0, limit).map(chip).join('');
    const more = values.length > limit ? `<span class="text-xs text-gray-500 px-2 py-1">+${values.length - limit} more (see Raw JSON)</span>` : '';
    return `<div class="flex flex-wrap gap-1.5">${shown}${more}</div>`;
}

// Generic, readable rendering for any JSON value.
// key: the field name the value came from (decides whether it is an identifier)
function renderValue(value, depth = 0, key = null) {
    if (value === null || value === undefined || value === '') return '<span class="text-gray-500">—</span>';
    if (typeof value !== 'object') {
        const text = String(value);
        if (/^https?:\/\//i.test(text)) return link(text);
        if (text.length > 300) return `<div class="whitespace-pre-wrap break-words text-sm text-gray-200 max-h-64 overflow-y-auto">${pivotInText(text)}</div>`;
        return `<span class="text-gray-200 break-words">${pivotField(key, text)}</span>`;
    }
    if (depth >= 3) {
        return `<pre class="text-xs text-gray-400 whitespace-pre-wrap break-all max-h-48 overflow-y-auto">${escapeHtml(JSON.stringify(value, null, 2))}</pre>`;
    }
    if (Array.isArray(value)) {
        if (!value.length) return '<span class="text-gray-500">none</span>';
        if (value.every(v => v === null || typeof v !== 'object')) return chips(value.map(String), 200, 'font-mono', pivotKeyType(key));
        if (value.every(v => v && typeof v === 'object' && !Array.isArray(v))) return renderTable(value);
        return `<div class="space-y-2">${value.slice(0, 50).map(v => `<div class="bg-gray-900/60 rounded-lg p-2">${renderValue(v, depth + 1)}</div>`).join('')}</div>`;
    }
    const entries = Object.entries(value);
    if (!entries.length) return '<span class="text-gray-500">empty</span>';
    return `
        <dl class="grid grid-cols-1 md:grid-cols-[minmax(8rem,auto)_1fr] gap-x-4 gap-y-1.5 text-sm">
            ${entries.map(([k, v]) => `
                <dt class="text-gray-500 text-xs pt-0.5 break-all">${escapeHtml(k.replace(/_/g, ' '))}</dt>
                <dd class="min-w-0">${renderValue(v, depth + 1, k)}</dd>
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
    const cell = (v, column) => {
        if (v === null || v === undefined || v === '') return '<span class="text-gray-600">—</span>';
        if (typeof v === 'object') return `<span class="text-gray-400 font-mono text-[11px]">${escapeHtml(JSON.stringify(v).slice(0, 80))}</span>`;
        const text = String(v);
        return /^https?:\/\//i.test(text) ? link(text, text.length > 60 ? text.slice(0, 60) + '…' : text) : pivotField(column, text);
    };
    return `
        <div class="overflow-x-auto border border-gray-800 rounded-lg max-h-[32rem] overflow-y-auto">
            <table class="w-full text-xs">
                <thead class="bg-gray-900 sticky top-0"><tr>${columns.map(c => `<th class="text-left px-3 py-2 text-gray-400 font-semibold whitespace-nowrap">${escapeHtml(c.replace(/_/g, ' '))}</th>`).join('')}</tr></thead>
                <tbody>${rows.slice(0, limit).map(r => `<tr class="border-t border-gray-800/80 hover:bg-gray-900/60">${columns.map(c => `<td class="px-3 py-1.5 text-gray-200 align-top break-words max-w-xs">${cell(r[c], c)}</td>`).join('')}</tr>`).join('')}</tbody>
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
                ${safeUrl(data.avatar_url) ? `<img src="${escapeAttr(safeUrl(data.avatar_url))}" alt="" loading="lazy" data-image-view="" data-image-title="Profile picture" class="w-16 h-16 rounded-xl border border-gray-700 shrink-0">` : ''}
                <div class="min-w-0">
                    <div class="flex items-center gap-2 flex-wrap">
                        <h4 class="text-xl font-bold text-white">${escapeHtml(data.name || data.username)}</h4>
                        <span class="text-sm text-gray-400 font-mono">${pivotText('username', data.username, '@' + data.username)}</span>
                        ${data.is_site_admin ? '<span class="px-2 py-0.5 text-xs bg-yellow-500 text-black rounded font-bold">Admin</span>' : ''}
                    </div>
                    ${data.bio ? `<p class="text-gray-300 text-sm mt-1">${pivotInText(data.bio)}</p>` : ''}
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
            ${(data.usernames || []).length ? `<div><h5 class="text-xs font-semibold text-gray-400 uppercase mb-2">Usernames</h5>${chips(data.usernames, 200, 'font-mono', 'username')}</div>` : ''}
            ${(data.domains || []).length ? `<div><h5 class="text-xs font-semibold text-gray-400 uppercase mb-2">Domains</h5>${chips(data.domains, 200, 'font-mono', 'domain')}</div>` : ''}
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
        return (data.error ? `<p class="text-sm text-red-300 mb-4">${escapeHtml(data.error)}</p>` : '') + oiResultsHtml(data.modules, data.modules_checked);
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
                        <div><div class="text-gray-500">IP</div><div class="text-gray-200 font-mono">${pivotText('ip', e.ip)}</div></div>
                    </div>
                    ${e.malware_path ? `<div class="text-xs"><span class="text-gray-500">Malware path:</span> <span class="font-mono text-gray-300 break-all">${escapeHtml(e.malware_path)}</span></div>` : ''}
                    ${(e.top_logins || []).length ? `<div><div class="text-xs text-gray-500 mb-1">Top logins</div>${chips(e.top_logins, 200, 'font-mono', 'username')}</div>` : ''}
                    ${(e.top_passwords || []).length ? `<div><div class="text-xs text-gray-500 mb-1">Top passwords</div>${chips(e.top_passwords)}</div>` : ''}
                    ${(e.credentials || []).length ? `<div><div class="text-xs text-gray-500 mb-1">Credentials</div>${renderTable(e.credentials, ['domain', 'username', 'url'])}</div>` : ''}
                </div>`).join('')}
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
                        ${r.snippet ? `<p class="text-xs text-gray-400 mt-1">${pivotInText(r.snippet)}</p>` : ''}
                    </div>`).join('')}
            </div>
        </div>`;
}

// A match's photo. Links to these photos often expire, so a placeholder takes its place.
function facePlaceholderHtml(sizeClass) {
    return `<div class="${sizeClass} flex flex-col items-center justify-center gap-2 bg-gray-800 text-gray-500 text-xs"><i class="fas fa-user text-3xl"></i>Image unavailable</div>`;
}

function faceImageFailed(img) {
    img.onerror = null;
    img.insertAdjacentHTML('afterend', facePlaceholderHtml(img.dataset.faceSize));
    img.remove();
}

function faceImageHtml(url, name, sizeClass, imageClass) {
    if (!url) return facePlaceholderHtml(sizeClass);
    return `<img src="${escapeAttr(url)}" alt="" loading="lazy" referrerpolicy="no-referrer" data-image-view="" data-image-title="${escapeAttr(name || 'Match')}"
        data-face-size="${sizeClass}" onerror="faceImageFailed(this)" class="${sizeClass} ${imageClass}">`;
}

function renderFaceSearch(data) {
    const list = Array.isArray(data) ? data : (data && data.results) || [];
    const query = !Array.isArray(data) && data && /^data:image\//.test(data.query_image || '') ? data.query_image : '';
    const queryHtml = query ? `<div class="flex items-center gap-3 text-xs text-gray-400 mb-3"><img src="${escapeAttr(query)}" alt="Searched face" data-image-view="" class="w-14 h-14 rounded-lg object-cover border border-gray-700">Searched face</div>` : '';
    if (!list.length) return queryHtml + '<p class="text-sm text-gray-400">No matches.</p>';
    return queryHtml + `
        <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
            ${list.map(f => `
                <div class="bg-gray-900 rounded-lg border border-gray-800 overflow-hidden">
                    ${faceImageHtml(safeUrl(f.image_url), f.name, 'w-full h-32', 'object-cover bg-gray-800')}
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
                <div class="text-sm text-gray-400">${u.username ? `${pivotText('telegram_username', u.username, '@' + u.username)} ${link(`https://t.me/${encodeURIComponent(u.username)}`, '↗')} · ` : ''}<span class="font-mono">ID ${pivotText('telegram_id', u.id)}</span></div>
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
            ${p.avatar_url ? `<img src="${escapeAttr(p.avatar_url)}" alt="Avatar" data-image-view="" data-image-title="${escapeAttr(p.name || 'Avatar')}" class="w-20 h-20 rounded-full object-cover border border-gray-700">` : ''}
            <div class="min-w-0 text-sm space-y-1">
                <div class="text-lg font-semibold text-white">${escapeHtml(p.name || '')}</div>
                <div>${pivotChip('telegram_username', p.username, '@' + p.username)}</div>
                ${p.bio ? `<div class="text-gray-300 whitespace-pre-wrap break-words">${pivotInText(p.bio)}</div>` : ''}
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
                    <div class="text-sm text-gray-200 whitespace-pre-wrap break-words">${m.text ? pivotInText(m.text) : '<i class="text-gray-500">media / no text</i>'}</div>
                </div>`).join('')}
            ${messages.length > limit ? `<p class="text-xs text-gray-500">Showing ${limit} of ${messages.length} - open in module to browse all.</p>` : ''}
        </div>`;
}

function renderFunstatTextSearch(data) {
    const results = (data && (data.results || data.data)) || [];
    if (!results.length) return renderValue(data);
    return renderFunstatMessages(results.map(r => ({ ...r, group: r.group, text: r.text })));
}
