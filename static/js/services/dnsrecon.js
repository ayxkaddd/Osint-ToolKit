window.currentService = 'dns_recon';

const recon = {
    form: document.getElementById('reconForm'),
    input: document.getElementById('domainInput'),
    button: document.getElementById('scanButton'),
    loading: document.getElementById('loadingIndicator'),
    results: document.getElementById('reconResults'),
    subdomains: [],
    showAll: false,
};
const SUBDOMAIN_PAGE = 150;

const reconField = (label, html) => html ? `<div><div class="text-xs text-gray-500 mb-1">${escapeHtml(label)}</div><div class="text-sm text-gray-100">${html}</div></div>` : '';
const reconStat = (label, value, color = 'text-white') =>
    `<div class="bg-gray-900 rounded-lg p-3 border border-gray-800"><div class="text-xs text-gray-500">${escapeHtml(label)}</div><div class="text-xl font-bold ${color}">${escapeHtml(value ?? '—')}</div></div>`;
const reconBadge = (text, cls = 'bg-gray-800 text-gray-300') => `<span class="text-[11px] px-1.5 py-0.5 rounded ${cls}">${escapeHtml(text)}</span>`;
const reconEmpty = (text) => `<p class="text-sm text-gray-500">${escapeHtml(text)}</p>`;

function renderStats(data) {
    const s = data.summary || {};
    const intel = data.intel || {};
    document.getElementById('reconStats').innerHTML = [
        reconStat('Names found', s.total_subdomains ?? (data.subdomains || []).length, 'text-purple-300'),
        reconStat('Resolve now', s.resolving_subdomains ?? '—', 'text-blue-300'),
        reconStat('Respond over HTTP', s.alive_subdomains ?? 0, 'text-emerald-300'),
        reconStat('IP addresses', s.unique_ips ?? (data.hosting || []).length),
        reconStat('First certificate', intel.first_certificate || '—'),
    ].join('');
}

function renderOwnerIntel(data) {
    const intel = data.intel || {};
    const whois = data.whois_info || {};
    const emails = [...new Set([
        ...(intel.emails || []), ...(intel.cert_emails || []),
        ...((intel.dmarc || {}).report_emails || []), ...[].concat(whois.emails || [])
    ].map(e => String(e).toLowerCase()))].filter(e => !/abuse/.test(e.split('@')[0]));  // registrar abuse desks
    const spf = intel.spf;
    const dmarc = intel.dmarc;
    const verifications = intel.verifications || [];

    const whoisHtml = whois.error
        ? `<p class="text-xs text-gray-500">WHOIS: ${escapeHtml(whois.error)}</p>`
        : `<div class="grid grid-cols-2 md:grid-cols-4 gap-4">
            ${reconField('Registrar', escapeHtml(whois.registrar || ''))}
            ${reconField('Registered', escapeHtml((whois.creation_date || '').slice(0, 10)))}
            ${reconField('Expires', escapeHtml((whois.expiration_date || '').slice(0, 10)))}
            ${reconField('Registrant', escapeHtml([whois.registrant, whois.org, whois.country].filter(Boolean).join(' · ')))}
        </div>`;

    document.getElementById('ownerIntel').innerHTML = `
        <div class="space-y-5">
            <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
                ${reconField('Mail provider', escapeHtml((intel.mail_providers || []).join(', ')) || '<span class="text-gray-500">unknown / none</span>')}
                ${reconField('DNS provider', escapeHtml((intel.dns_providers || []).join(', ')) || '<span class="text-gray-500">unknown</span>')}
                ${reconField('Sends email through', spf ? (escapeHtml(spf.services.join(', ')) || '<span class="text-gray-500">own servers</span>') : '<span class="text-gray-500">no SPF record</span>')}
                ${reconField('DMARC policy', dmarc ? escapeHtml(dmarc.policy || 'none') : '<span class="text-gray-500">no DMARC record</span>')}
            </div>
            ${whoisHtml}
            ${emails.length ? `<div>
                <div class="text-xs text-gray-500 mb-1">Email addresses <span class="text-gray-600">- from DNS, DMARC reports, old certificates and WHOIS</span></div>
                <div class="flex flex-wrap gap-1.5">${emails.map(e => pivotChip('email', e)).join('')}</div>
            </div>` : ''}
            ${verifications.length ? `<div>
                <div class="text-xs text-gray-500 mb-1">Verification tokens <span class="text-gray-600">- issued per account: another domain with the same token has the same owner</span></div>
                <div class="space-y-1.5">${verifications.map(v => `
                    <div class="flex items-center gap-2 flex-wrap bg-gray-900 rounded-lg px-3 py-2 border border-gray-800">
                        <span class="text-sm text-gray-300 w-56 shrink-0">${escapeHtml(v.service)}</span>
                        <code class="text-xs text-purple-200 break-all flex-1 min-w-0">${escapeHtml(v.token)}</code>
                        <button type="button" data-copy="${escapeAttr(v.record)}" class="text-xs px-2 py-1 rounded bg-gray-800 hover:bg-gray-700" title="Copy record"><i class="fas fa-copy"></i></button>
                        <a href="https://www.google.com/search?q=${encodeURIComponent('"' + v.token + '"')}" target="_blank" rel="noopener noreferrer"
                            class="text-xs px-2 py-1 rounded bg-gray-800 hover:bg-gray-700" title="Search the web for this token"><i class="fas fa-search mr-1"></i>Find other domains</a>
                    </div>`).join('')}</div>
            </div>` : ''}
            ${spf && (spf.includes.length || spf.ips.length) ? `<div>
                <div class="text-xs text-gray-500 mb-1">SPF - servers allowed to send as this domain (${escapeHtml(spf.policy || 'no policy')})</div>
                <div class="flex flex-wrap gap-1.5">${spf.includes.map(h => pivotChip('domain', h)).join('')}${spf.ips.map(ip => ip.includes('/') ? reconBadge(ip) : pivotChip('ip', ip)).join('')}</div>
            </div>` : ''}
            ${(intel.other_txt || []).length ? `<div>
                <div class="text-xs text-gray-500 mb-1">Other TXT records</div>
                <div class="space-y-1">${intel.other_txt.map(t => `<div class="font-mono text-xs bg-gray-900 rounded px-2 py-1 break-all text-gray-300">${pivotInText(t)}</div>`).join('')}</div>
            </div>` : ''}
        </div>`;
}

// Current NS pair plus every earlier one SecurityTrails knows
function dnsNsSets(data) {
    const sets = [{ servers: (data.dns_records || {}).NS || [], label: 'current' }];
    (((data.dns_history || {}).securitytrails || {}).NS || []).forEach(r =>
        sets.push({ servers: r.values || [], first_seen: r.first_seen, last_seen: r.last_seen || 'now' }));
    return sets;
}

function renderNsPairs(data) {
    const html = nsLookupSuggestion(dnsNsSets(data));
    document.getElementById('nsPairsSection').classList.toggle('hidden', !html);
    document.getElementById('nsPairs').innerHTML = html;
}

function renderHosting(data) {
    const hosting = data.hosting || [];
    document.getElementById('hostingCount').textContent = hosting.length ? `${hosting.length} IPs` : '';
    if (!hosting.length) {
        document.getElementById('hostingList').innerHTML = reconEmpty('No names resolved.');
        return;
    }
    // One card per network: the same provider usually hosts several IPs
    const networks = new Map();
    hosting.forEach(h => {
        const key = h.asn || 'unknown';
        if (!networks.has(key)) networks.set(key, { asn: h.asn, name: h.as_name, country: h.country, ips: [], hosts: new Set() });
        const n = networks.get(key);
        n.ips.push(h);
        h.hosts.forEach(x => n.hosts.add(x));
    });
    const sorted = [...networks.values()].sort((a, b) => b.hosts.size - a.hosts.size);
    document.getElementById('hostingList').innerHTML = `<div class="space-y-2">${sorted.map(n => {
        const hosts = [...n.hosts];
        return `<div class="bg-gray-900 rounded-lg p-3 border border-gray-800">
            <div class="flex items-center justify-between gap-2 flex-wrap mb-2">
                <div class="text-sm"><span class="text-white font-medium">${escapeHtml(n.name || 'Unknown network')}</span>
                    ${n.asn ? `<span class="text-xs text-gray-500 ml-2">AS${escapeHtml(n.asn)}</span>` : ''}
                    ${n.country ? `<span class="text-xs text-gray-500 ml-1">· ${escapeHtml(n.country)}</span>` : ''}</div>
                <span class="text-xs text-gray-500">${hosts.length} name${hosts.length === 1 ? '' : 's'}</span>
            </div>
            <div class="flex flex-wrap gap-1.5 mb-2">${n.ips.map(h => pivotChip('ip', h.ip)).join('')}</div>
            <div class="text-xs text-gray-400 break-words">${hosts.slice(0, 30).map(escapeHtml).join(', ')}${hosts.length > 30 ? ` <span class="text-gray-500">+${hosts.length - 30} more</span>` : ''}</div>
        </div>`;
    }).join('')}</div>`;
}

function subdomainRow(s) {
    const probe = s.httpx_data || {};
    const status = s.status_code || probe.status_code;
    const statusCls = !status ? '' : status < 300 ? 'bg-emerald-900/50 text-emerald-300' : status < 400 ? 'bg-yellow-900/50 text-yellow-300' : 'bg-red-900/40 text-red-300';
    const url = probe.url ? safeUrl(probe.url) : '';
    return `<div class="flex items-start gap-3 py-2 border-b border-gray-800/70 last:border-0">
        <div class="min-w-0 flex-1">
            <div class="flex items-center gap-1.5 flex-wrap">
                ${pivotChip('domain', s.name)}
                ${status ? reconBadge(String(status), statusCls) : (s.resolves === false ? reconBadge('does not resolve', 'bg-gray-800 text-gray-500') : '')}
                ${url ? `<a href="${escapeAttr(url)}" target="_blank" rel="noopener noreferrer" class="text-gray-500 hover:text-white text-xs" title="Open"><i class="fas fa-external-link-alt"></i></a>` : ''}
            </div>
            ${s.title || s.technologies?.length ? `<div class="text-xs text-gray-400 mt-1 truncate">${escapeHtml(s.title || '')}${s.technologies?.length ? ` <span class="text-gray-500">· ${escapeHtml(s.technologies.join(', '))}</span>` : ''}</div>` : ''}
        </div>
        <div class="text-right shrink-0 text-xs text-gray-500 space-y-0.5">
            <div class="font-mono">${(s.ips || []).slice(0, 2).map(ip => pivotText('ip', ip)).join(', ')}</div>
            <div>${(s.sources || []).filter(x => x !== 'target').map(x => escapeHtml(x)).join(' · ')}${s.first_cert ? ` · cert ${escapeHtml(s.first_cert)}` : ''}</div>
        </div>
    </div>`;
}

function renderSubdomains() {
    const q = document.getElementById('subdomainFilter').value.trim().toLowerCase();
    const state = document.getElementById('subdomainState').value;
    const list = recon.subdomains.filter(s => {
        if (state === 'resolves' && !s.resolves) return false;
        if (state === 'alive' && !s.is_alive) return false;
        if (state === 'gone' && s.resolves !== false) return false;
        if (!q) return true;
        return [s.name, s.title, ...(s.ips || []), ...(s.technologies || [])].some(v => v && String(v).toLowerCase().includes(q));
    });
    const shown = recon.showAll ? list : list.slice(0, SUBDOMAIN_PAGE);
    document.getElementById('subdomainCount').textContent = recon.subdomains.length ? String(recon.subdomains.length) : '';
    document.getElementById('subdomainsList').innerHTML = shown.length
        ? `<div class="bg-gray-900 rounded-lg px-3 border border-gray-800">${shown.map(subdomainRow).join('')}</div>`
        : reconEmpty(recon.subdomains.length ? 'Nothing matches the filter.' : 'No subdomains found.');
    const more = document.getElementById('subdomainsMore');
    more.classList.toggle('hidden', shown.length >= list.length);
    more.textContent = `Show all ${list.length}`;
}

function renderHistory(data) {
    const history = data.dns_history || {};
    const st = history.securitytrails || {};
    const vt = history.virustotal_resolutions || [];
    const section = document.getElementById('historySection');
    const hasSt = Object.values(st).some(v => v && v.length);
    if (!hasSt && !vt.length) {
        const configured = (data.summary || {}).external_apis_used;
        document.getElementById('dnsHistory').innerHTML = reconEmpty(configured
            ? 'No history returned. SecurityTrails and VirusTotal keys add earlier IPs, mail and name servers - often the real host before a CDN was added.'
            : 'External APIs were off for this scan.');
        return;
    }
    section.open = true;
    const pivotType = { A: 'ip', MX: 'domain', NS: 'domain' };
    document.getElementById('dnsHistory').innerHTML = `
        <div class="space-y-4">
            ${Object.entries(st).filter(([, rows]) => rows && rows.length).map(([type, rows]) => `
                <div>
                    <div class="text-xs font-bold text-blue-300 mb-1">${escapeHtml(type)} records over time <span class="text-gray-500 font-normal">(SecurityTrails)</span></div>
                    <div class="bg-gray-900 rounded-lg px-3 border border-gray-800">
                        ${rows.map(r => `<div class="flex items-start gap-3 py-2 border-b border-gray-800/70 last:border-0">
                            <div class="text-xs text-gray-400 w-48 shrink-0 font-mono">${escapeHtml(r.first_seen || '?')} → ${escapeHtml(r.last_seen || 'now')}</div>
                            <div class="flex-1 min-w-0">
                                <div class="flex flex-wrap gap-1.5">${(r.values || []).map(v => pivotChip(pivotType[type] || 'domain', v)).join('')}</div>
                                ${(r.organizations || []).length ? `<div class="text-xs text-gray-500 mt-1">${escapeHtml(r.organizations.join(', '))}</div>` : ''}
                            </div>
                        </div>`).join('')}
                    </div>
                </div>`).join('')}
            ${vt.length ? `<div>
                <div class="text-xs font-bold text-blue-300 mb-1">Passive DNS <span class="text-gray-500 font-normal">(VirusTotal - IPs this domain pointed to)</span></div>
                <div class="flex flex-wrap gap-1.5">${vt.map(r => `<span class="inline-flex items-center gap-1">${pivotChip('ip', r.ip)}<span class="text-[11px] text-gray-500">${escapeHtml(r.last_resolved)}</span></span>`).join('')}</div>
            </div>` : ''}
        </div>`;
}

function renderRecords(data) {
    const records = Object.entries(data.dns_records || {}).filter(([, v]) => v && v.length);
    const chipFor = (type, value) => {
        if (type === 'A' || type === 'AAAA') return pivotChip('ip', value);
        if (type === 'MX') return pivotChip('domain', value.split(' ').pop().replace(/\.$/, ''), value);
        if (type === 'NS' || type === 'CNAME') return pivotChip('domain', value.replace(/\.$/, ''));
        return `<div class="font-mono text-xs bg-gray-950 rounded px-2 py-1 break-all text-gray-300 w-full">${pivotInText(value)}</div>`;
    };
    document.getElementById('dnsRecords').innerHTML = records.length ? records.map(([type, list]) => `
        <div class="bg-gray-900 rounded-lg p-3 border border-gray-800">
            <div class="text-xs font-bold text-blue-300 mb-2">${escapeHtml(type)}</div>
            <div class="flex flex-wrap gap-1.5">${list.map(v => chipFor(type, String(v))).join('')}</div>
        </div>`).join('') : reconEmpty('No DNS records found.');
}

function renderPorts(data) {
    const ports = (data.port_scan_results || []).filter(p => !p.error);
    const section = document.getElementById('portScanSection');
    section.classList.toggle('hidden', !ports.length);
    if (!ports.length) return;
    section.open = true;
    document.getElementById('portScanResults').innerHTML = `<div class="grid grid-cols-1 md:grid-cols-2 gap-2">${ports.map(p => `
        <div class="bg-gray-900 rounded-lg px-3 py-2 border border-gray-800 flex items-center justify-between gap-2 text-sm">
            <span><span class="font-mono text-cyan-300">${escapeHtml(p.port)}/${escapeHtml(p.protocol || 'tcp')}</span>
                <span class="text-gray-300 ml-2">${escapeHtml(p.service || '')}</span>
                <span class="text-gray-500 ml-1 text-xs">${escapeHtml([p.product, p.version].filter(Boolean).join(' '))}</span></span>
            ${reconBadge(p.state || '', p.state === 'open' ? 'bg-emerald-900/50 text-emerald-300' : 'bg-gray-800 text-gray-400')}
        </div>`).join('')}</div>`;
}

function renderTechnologies(data) {
    const counts = {};
    (data.subdomains || []).forEach(s => (s.technologies || []).forEach(t => { counts[t] = (counts[t] || 0) + 1; }));
    const entries = Object.entries(counts).sort((a, b) => b[1] - a[1]);
    document.getElementById('technologyStack').innerHTML = entries.length
        ? entries.map(([t, n]) => `<span class="text-xs px-2 py-1 rounded bg-gray-900 border border-gray-800">${escapeHtml(t)} <span class="text-gray-500">${n}</span></span>`).join('')
        : reconEmpty('Nothing detected (needs httpx-toolkit).');
}

function renderReputation(data) {
    const vt = (data.external_api_data || {}).virustotal || {};
    const section = document.getElementById('reputationSection');
    const urls = vt.detected_urls || [];
    const show = !vt.error && ((vt.categories || []).length || urls.length);
    section.classList.toggle('hidden', !show);
    if (!show) return;
    document.getElementById('reputation').innerHTML = `
        ${(vt.categories || []).length ? `<div class="mb-3">${reconField('Categories', escapeHtml(vt.categories.join(', ')))}</div>` : ''}
        ${urls.length ? `<div class="text-xs text-gray-500 mb-1">URLs flagged by antivirus engines</div>
            <div class="space-y-1">${urls.map(u => `<div class="text-xs flex gap-2"><span class="text-red-300 w-12 shrink-0">${escapeHtml(u.positives)}/${escapeHtml(u.total)}</span>
                <span class="break-all text-gray-300">${escapeHtml(u.url)}</span></div>`).join('')}</div>` : reconEmpty('No flagged URLs.')}`;
}

function displayResults(data) {
    data = data || {};
    const warnings = data.warnings || [];
    const warningsBox = document.getElementById('reconWarnings');
    warningsBox.innerHTML = warnings.map(w => `<p><i class="fas fa-exclamation-triangle mr-2"></i>${escapeHtml(w)}</p>`).join('');
    warningsBox.classList.toggle('hidden', !warnings.length);

    document.getElementById('domainTitle').innerHTML = data.domain ? pivotChip('domain', data.domain) : '';
    document.getElementById('scanTimestamp').textContent = data.timestamp ? new Date(data.timestamp).toLocaleString() : '';

    recon.subdomains = (data.subdomains || []).map(s => typeof s === 'string' ? { name: s } : s);
    recon.showAll = false;

    renderStats(data);
    renderOwnerIntel(data);
    renderNsPairs(data);
    renderHosting(data);
    renderSubdomains();
    renderHistory(data);
    renderRecords(data);
    renderPorts(data);
    renderTechnologies(data);
    renderReputation(data);
    recon.results.classList.remove('hidden');
}

window.loadResultIntoView = function (data) {
    if (data && data.domain) recon.input.value = data.domain;
    displayResults(data);
};

async function performRecon() {
    const domain = recon.input.value.trim().toLowerCase().replace(/^https?:\/\//, '').split('/')[0];
    if (!domain) return;
    recon.input.value = domain;
    recon.loading.classList.remove('hidden');
    recon.results.classList.add('hidden');
    recon.button.disabled = true;
    try {
        const response = await fetch('/api/recon/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                domain,
                deep_scan: document.getElementById('deepScan').checked,
                include_ports: document.getElementById('includePorts').checked,
                use_external_apis: document.getElementById('useExternalApis').checked,
            })
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            const detail = Array.isArray(data.detail) ? data.detail.map(d => d.msg).join('; ') : data.detail;
            throw new Error(detail || `HTTP ${response.status}`);
        }
        displayResults(data);
    } catch (error) {
        showTemporaryNotification(`Scan failed: ${error.message}`, 'error');
    } finally {
        recon.loading.classList.add('hidden');
        recon.button.disabled = false;
    }
}

recon.form.addEventListener('submit', (e) => {
    e.preventDefault();
    performRecon();
});
document.getElementById('subdomainFilter').addEventListener('input', () => { recon.showAll = false; renderSubdomains(); });
document.getElementById('subdomainState').addEventListener('change', () => { recon.showAll = false; renderSubdomains(); });
document.getElementById('subdomainsMore').addEventListener('click', () => { recon.showAll = true; renderSubdomains(); });

// Say which history sources are configured (their calls count against small monthly quotas)
getModules().then(modules => {
    const module = modules.find(m => m.id === 'dns_recon');
    if (!module) return;
    const missing = module.optional_missing || [];
    const notes = [];
    if (missing.includes('SECURITYTRAILS_API_KEY')) notes.push('SecurityTrails key not set');
    else notes.push('4 SecurityTrails calls');
    if (missing.includes('VIRUSTOTAL_API_KEY')) notes.push('VirusTotal key not set');
    document.getElementById('externalApiNote').innerHTML = `(${escapeHtml(notes.join(', '))} - <a href="/settings" class="underline">settings</a>)`;
}).catch(() => {});
