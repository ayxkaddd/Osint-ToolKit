window.currentService = 'whois';

const whoisEls = {
    form: document.getElementById('whoisForm'),
    input: document.getElementById('domainInput'),
    button: document.getElementById('searchButton'),
    preview: document.getElementById('previewBox'),
    loading: document.getElementById('loadingIndicator'),
    loadingText: document.getElementById('loadingText'),
    data: document.getElementById('whoisData'),
};
const ROLE_LABELS = { registrant: 'Registrant', admin: 'Admin', tech: 'Tech', billing: 'Billing', zone: 'Zone' };
const FIELD_LABELS = { registrar: 'Registrar', nameservers: 'Name servers', registrant: 'Registrant', admin: 'Admin contact', tech: 'Tech contact', status: 'Status' };

function cleanDomain(value) {
    return value.trim().toLowerCase().replace(/^https?:\/\//, '').split('/')[0].replace(/^www\./, '');
}

function setLoading(text) {
    whoisEls.loading.classList.toggle('hidden', !text);
    whoisEls.loadingText.textContent = text || '';
    whoisEls.button.disabled = !!text;
}

async function fetchJson(url) {
    const response = await fetch(url);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `HTTP ${response.status}`);
    return data;
}

async function checkHistory() {
    const domain = cleanDomain(whoisEls.input.value);
    if (!domain) return;
    whoisEls.input.value = domain;
    whoisEls.data.classList.add('hidden');
    whoisEls.preview.classList.add('hidden');
    setLoading('Checking how many records exist…');
    try {
        const preview = await fetchJson(`/api/domain/history/preview?domain=${encodeURIComponent(domain)}`);
        const count = preview.records_count || 0;
        whoisEls.preview.innerHTML = `
            <div class="bg-[#14151f] border border-[#24283b] rounded-xl p-5 flex items-center justify-between gap-4 flex-wrap">
                <div>
                    <div class="text-lg">${pivotChip('domain', domain)} <span class="ml-2 ${count ? 'text-white' : 'text-gray-400'}">${count} archived record${count === 1 ? '' : 's'}</span></div>
                    <div class="text-xs text-gray-500 mt-1">${count ? 'Loading them uses WhoisXML credits.' : 'Nothing to load - no credits were used.'}</div>
                </div>
                ${count ? `<button type="button" id="loadHistoryButton" class="bg-purple-600 hover:bg-purple-500 px-4 py-2 rounded-lg text-sm font-medium">Load ${count} record${count === 1 ? '' : 's'}</button>` : ''}
            </div>`;
        whoisEls.preview.classList.remove('hidden');
        const load = document.getElementById('loadHistoryButton');
        if (load) load.addEventListener('click', () => loadHistory(domain));
    } catch (error) {
        showTemporaryNotification(error.message, 'error');
    } finally {
        setLoading('');
    }
}

async function loadHistory(domain) {
    whoisEls.preview.classList.add('hidden');
    setLoading('Loading WHOIS history…');
    try {
        displayResults(await fetchJson(`/api/domain/history?domain=${encodeURIComponent(domain)}`));
    } catch (error) {
        whoisEls.preview.classList.remove('hidden');
        showTemporaryNotification(error.message, 'error');
    } finally {
        setLoading('');
    }
}

function contactCard(c) {
    const location = [c.street, c.city, c.state, c.postalCode, c.country].filter(Boolean).join(', ');
    return `
        <div class="bg-gray-900 rounded-lg p-4 border ${c.privacy ? 'border-gray-800 opacity-70' : 'border-emerald-800/60'}">
            <div class="flex items-start justify-between gap-3 flex-wrap mb-2">
                <div class="min-w-0">
                    <div class="text-white font-medium break-words">${escapeHtml(c.name || c.organization || 'Unnamed contact')}</div>
                    ${c.name && c.organization ? `<div class="text-sm text-gray-400 break-words">${escapeHtml(c.organization)}</div>` : ''}
                </div>
                <div class="flex items-center gap-1.5 flex-wrap">
                    ${c.privacy ? '<span class="text-[11px] px-1.5 py-0.5 rounded bg-gray-800 text-gray-400">privacy service</span>'
                        : '<span class="text-[11px] px-1.5 py-0.5 rounded bg-emerald-900/50 text-emerald-300">real contact</span>'}
                    ${(c.roles || []).map(r => `<span class="text-[11px] px-1.5 py-0.5 rounded bg-gray-800 text-gray-300">${escapeHtml(ROLE_LABELS[r] || r)}</span>`).join('')}
                </div>
            </div>
            <div class="flex flex-wrap gap-1.5 mb-2">
                ${c.email ? pivotChip('email', c.email) : ''}
                ${c.telephone ? pivotChip('phone', c.telephone) : ''}
            </div>
            ${location ? `<div class="text-xs text-gray-400 break-words"><i class="fas fa-map-marker-alt mr-1 text-gray-500"></i>${escapeHtml(location)}</div>` : ''}
            <div class="text-xs text-gray-500 mt-1">Listed ${escapeHtml(c.first_seen || '?')}${c.last_seen && c.last_seen !== c.first_seen ? ` → ${escapeHtml(c.last_seen)}` : ''}</div>
        </div>`;
}

function periods(rows, pivotType) {
    return `<div class="space-y-1">${rows.map(r => `
        <div class="flex items-center gap-3 text-sm">
            <span class="text-xs text-gray-500 font-mono w-48 shrink-0">${escapeHtml(r.first_seen || '?')} → ${escapeHtml(r.last_seen || '?')}</span>
            ${pivotType ? pivotChip(pivotType, r.name) : `<span class="text-gray-200">${escapeHtml(r.name)}</span>`}
        </div>`).join('')}</div>`;
}

function timelineEntry(entry) {
    return `
        <div class="flex gap-3 py-3 border-b border-gray-800/70 last:border-0">
            <div class="text-xs text-gray-400 font-mono w-24 shrink-0 pt-0.5">${escapeHtml(entry.date || '?')}</div>
            <div class="flex-1 min-w-0 text-sm">
                ${entry.first ? `<div class="text-gray-300">First archived record${entry.registrant ? ` - registrant <span class="text-white">${escapeHtml(entry.registrant)}</span>` : ''}${entry.registrar ? `, registrar ${escapeHtml(entry.registrar)}` : ''}</div>` : ''}
                ${(entry.changes || []).map(c => `
                    <div class="mb-1 break-words"><span class="text-gray-400">${escapeHtml(FIELD_LABELS[c.field] || c.field)}:</span>
                        <span class="text-red-300/80 line-through decoration-red-400/40">${escapeHtml(c.from)}</span>
                        <i class="fas fa-arrow-right text-gray-600 text-xs mx-1"></i>
                        <span class="text-emerald-200">${escapeHtml(c.to)}</span></div>`).join('')}
            </div>
        </div>`;
}

function rawRecord(record) {
    const date = (record.audit && record.audit.updatedDate) || record.updatedDateISO8601 || record.createdDateISO8601 || '';
    return `<details class="bg-gray-900 rounded-lg border border-gray-800">
        <summary class="cursor-pointer px-3 py-2 text-sm text-gray-300">${escapeHtml(String(date).slice(0, 10) || 'undated')} · ${escapeHtml(record.registrarName || 'unknown registrar')}</summary>
        <pre class="px-3 pb-3 text-xs text-gray-400 whitespace-pre-wrap break-words max-h-96 overflow-y-auto">${escapeHtml(record.cleanText || JSON.stringify(record, null, 2))}</pre>
    </details>`;
}

// One entry per distinct name server set across the archived records
function whoisNsSets(records) {
    return records.map(r => {
        const date = String((r.audit && r.audit.updatedDate) || r.updatedDateISO8601 || r.createdDateISO8601 || '').slice(0, 10);
        return { servers: r.nameServers || [], first_seen: date, last_seen: date };
    });
}

function displayResults(data) {
    showIdentifiers(data);
    data = data || {};
    const records = data.records || [];
    const a = data.analysis;
    const domain = data.domain || (records[0] && records[0].domainName) || '';
    if (domain) whoisEls.input.value = domain;
    const contacts = (a && a.contacts) || [];
    const nsHtml = nsLookupSuggestion(whoisNsSets(records));
    const stat = (label, value) => `<div class="bg-gray-900 rounded-lg p-3 border border-gray-800"><div class="text-xs text-gray-500">${escapeHtml(label)}</div><div class="text-lg font-bold text-white">${escapeHtml(value ?? '—')}</div></div>`;

    whoisEls.data.innerHTML = `
        <section class="bg-[#14151f] border border-[#24283b] rounded-xl p-5">
            <div class="mb-4">${domain ? pivotChip('domain', domain) : ''}</div>
            <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
                ${stat('Archived records', data.recordsCount ?? records.length)}
                ${stat('First registered', a && a.first_registered)}
                ${stat('Archive covers', a && a.first_snapshot ? `${a.first_snapshot.slice(0, 4)}–${(a.last_snapshot || '').slice(0, 4)}` : null)}
                ${stat('Real contacts', a ? a.real_contacts : null)}
            </div>
        </section>
        ${a ? `
        <details open class="recon-section"><summary><i class="fas fa-users"></i>Everyone ever listed <span class="count">${contacts.length}</span></summary>
            <div class="recon-body">${contacts.length ? `<div class="grid grid-cols-1 md:grid-cols-2 gap-3">${contacts.map(contactCard).join('')}</div>`
                : '<p class="text-sm text-gray-500">No contact details in any record.</p>'}</div></details>
        <details open class="recon-section"><summary><i class="fas fa-stream"></i>What changed <span class="count">${a.timeline.length}</span></summary>
            <div class="recon-body"><div class="bg-gray-900 rounded-lg px-3 border border-gray-800">${a.timeline.map(timelineEntry).join('')}</div></div></details>
        <details class="recon-section"><summary><i class="fas fa-server"></i>Registrars and name servers</summary>
            <div class="recon-body grid grid-cols-1 md:grid-cols-2 gap-5">
                <div><div class="text-xs text-gray-500 mb-2">Registrars</div>${periods(a.registrars)}</div>
                <div><div class="text-xs text-gray-500 mb-2">Name servers</div>${periods(a.nameservers, 'domain')}</div>
            </div></details>` : ''}
        ${nsHtml ? `
        <details open class="recon-section"><summary><i class="fas fa-server"></i>Same name servers</summary>
            <div class="recon-body">${nsHtml}</div></details>` : ''}
        <details class="recon-section"><summary><i class="fas fa-file-alt"></i>Full records <span class="count">${records.length}</span></summary>
            <div class="recon-body space-y-2">${records.map(rawRecord).join('') || '<p class="text-sm text-gray-500">No records.</p>'}</div></details>`;
    whoisEls.data.classList.remove('hidden');
}

window.loadResultIntoView = (data) => displayResults(data);

whoisEls.form.addEventListener('submit', (e) => {
    e.preventDefault();
    checkHistory();
});
