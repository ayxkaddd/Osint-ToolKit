window.currentService = 'ip';

const ipEls = {
    form: document.getElementById('ipForm'),
    input: document.getElementById('ipInput'),
    submit: document.getElementById('ipSubmit'),
    loading: document.getElementById('ipLoading'),
    result: document.getElementById('ipResult'),
};

function ipField(label, value) {
    if (value === null || value === undefined || value === '') return '';
    return `<div><div class="text-xs text-gray-500">${escapeHtml(label)}</div><div class="text-gray-100 break-words">${value}</div></div>`;
}

function renderIp(data) {
    showIdentifiers(data);
    const basic = data.basic_info || {};
    const abuse = data.abuse_info;
    const shodan = data.shodan_info;
    const [lat, lon] = (basic.loc || '').split(',');
    const warnings = data.warnings || [];

    const abuseHtml = abuse && !abuse.error ? `
        <section class="bg-gray-900 rounded-xl p-5 border border-gray-800">
            <h2 class="font-bold mb-3"><i class="fas fa-flag text-red-400 mr-2"></i>Abuse reports (AbuseIPDB)</h2>
            <div class="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                ${ipField('Abuse confidence', `<span class="${abuse.abuseConfidenceScore > 50 ? 'text-red-300' : 'text-emerald-300'} font-bold">${escapeHtml(abuse.abuseConfidenceScore)}%</span>`)}
                ${ipField('Reports (1 year)', escapeHtml(abuse.totalReports))}
                ${ipField('Usage type', escapeHtml(abuse.usageType))}
                ${ipField('Last reported', escapeHtml((abuse.lastReportedAt || '').slice(0, 10)))}
                ${ipField('Tor exit node', abuse.isTor ? '<span class="text-yellow-300">yes</span>' : 'no')}
            </div>
            ${(abuse.reports || []).length ? `<div class="mt-3 space-y-1 text-xs text-gray-400 max-h-48 overflow-y-auto">${abuse.reports.map(r => `<div><span class="text-gray-500">${escapeHtml((r.reportedAt || '').slice(0, 10))}</span> ${escapeHtml(r.comment || '')}</div>`).join('')}</div>` : ''}
        </section>` : '';

    const shodanHtml = shodan && !shodan.error ? `
        <section class="bg-gray-900 rounded-xl p-5 border border-gray-800">
            <h2 class="font-bold mb-3"><i class="fas fa-server text-blue-400 mr-2"></i>Exposed services (Shodan)</h2>
            ${shodan.note ? `<p class="text-sm text-gray-400">${escapeHtml(shodan.note)}</p>` : `
            <div class="grid grid-cols-2 md:grid-cols-3 gap-4 text-sm">
                ${ipField('Open ports', escapeHtml((shodan.ports || []).join(', ')))}
                ${ipField('OS', escapeHtml(shodan.os))}
                ${ipField('Last scanned', escapeHtml(shodan.last_update))}
                ${ipField('Known CVEs', (shodan.vulns || []).length ? `<span class="text-red-300">${escapeHtml(shodan.vulns.join(', '))}</span>` : '')}
                ${ipField('Tags', escapeHtml((shodan.tags || []).join(', ')))}
            </div>
            ${(shodan.hostnames || []).length || (shodan.domains || []).length ? `<div class="mt-3 flex flex-wrap gap-1.5">${[...(shodan.hostnames || []), ...(shodan.domains || [])].map(h => pivotChip('domain', h)).join('')}</div>` : ''}`}
        </section>` : '';

    ipEls.result.innerHTML = `
        ${warnings.length ? `<div class="bg-yellow-900/30 border border-yellow-700/60 rounded-lg p-4 text-sm text-yellow-100">${warnings.map(w => `<p>${escapeHtml(w)}</p>`).join('')}</div>` : ''}
        <section class="bg-gray-900 rounded-xl p-5 border border-gray-800">
            <div class="flex items-center justify-between gap-3 mb-4">
                <div class="font-mono text-xl text-purple-200">${escapeHtml(data.ip)}</div>
                ${data.reverse_dns ? pivotChip('domain', data.reverse_dns) : '<span class="text-xs text-gray-500">no reverse DNS</span>'}
            </div>
            <div class="grid grid-cols-2 md:grid-cols-3 gap-4 text-sm">
                ${ipField('Location', escapeHtml([basic.city, basic.region, basic.country].filter(Boolean).join(', ')))}
                ${ipField('Network (ASN / owner)', escapeHtml(basic.org))}
                ${ipField('Hostname', escapeHtml(basic.hostname))}
                ${ipField('Postal code', escapeHtml(basic.postal))}
                ${ipField('Timezone', escapeHtml(basic.timezone))}
                ${ipField('Anycast', basic.anycast ? 'yes' : '')}
                ${lat && lon ? ipField('Map', `<a class="text-blue-400 hover:underline" target="_blank" rel="noopener noreferrer" href="https://www.openstreetmap.org/?mlat=${encodeURIComponent(lat)}&mlon=${encodeURIComponent(lon)}#map=11/${encodeURIComponent(lat)}/${encodeURIComponent(lon)}">${escapeHtml(basic.loc)}</a> <span class="text-xs text-gray-500">(approximate)</span>`) : ''}
            </div>
        </section>
        ${abuseHtml}
        ${shodanHtml}`;
}

async function lookupIp() {
    const ip = ipEls.input.value.trim();
    if (!ip) return;
    ipEls.loading.classList.remove('hidden');
    ipEls.result.innerHTML = '';
    ipEls.submit.disabled = true;
    try {
        const response = await fetch(`/api/ip/lookup?ip=${encodeURIComponent(ip)}`);
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
        renderIp(data);
    } catch (error) {
        ipEls.result.innerHTML = `<p class="text-red-400">${escapeHtml(error.message)}</p>`;
    } finally {
        ipEls.loading.classList.add('hidden');
        ipEls.submit.disabled = false;
    }
}

window.loadResultIntoView = (data) => {
    if (data && data.ip) ipEls.input.value = data.ip;
    renderIp(data || {});
};

ipEls.form.addEventListener('submit', (e) => {
    e.preventDefault();
    lookupIp();
});
