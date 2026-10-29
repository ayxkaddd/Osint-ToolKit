// Initialize Lucide icons
lucide.createIcons();

// Enable result loading
window.currentService = 'hlr';
window.loadResultIntoView = function (data) {
    displayResults(data);
    document.getElementById('hlrResults').classList.remove('hidden');
};


const searchButton = document.getElementById('searchButton');
const phoneInput = document.getElementById('phoneInput');
const loadingIndicator = document.getElementById('loadingIndicator');
const hlrResults = document.getElementById('hlrResults');
const balanceAmount = document.getElementById('balanceAmount');
const resultsTimeline = document.getElementById('resultsTimeline');

async function performHLRLookup() {
    try {
        loadingIndicator.classList.remove('hidden');
        hlrResults.classList.add('hidden');

        const phones = phoneInput.value.trim();
        const response = await fetch('/api/hlr/lookup', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ phones })
        });

        const data = await response.json();

        // Check if response is an error
        if (!response.ok) {
            throw new Error(JSON.stringify(data.detail));
        }

        displayResults(data);
        hlrResults.classList.remove('hidden'); // Show results

    } catch (error) {
        console.error('Error:', error);
        // Show error in the results area
        hlrResults.classList.remove('hidden');
        balanceAmount.textContent = 'N/A';

        // Parse error message if it's JSON
        let errorData;
        try {
            errorData = JSON.parse(error.message);
        } catch {
            errorData = { message: error.message };
        }

        resultsTimeline.innerHTML = `
            <div class="bg-gray-900 rounded-lg overflow-hidden">
                <div class="p-4 border-b border-gray-800">
                    <div class="flex items-center gap-3">
                        <div class="bg-gray-800 p-2 rounded">
                            <i data-lucide="alert-triangle" class="w-5 h-5 text-yellow-500"></i>
                        </div>
                        <div>
                            <span class="text-lg font-semibold">Request Failed</span>
                            <div class="text-sm text-gray-400 mt-1">${escapeHtml(errorData.message || error.message)}</div>
                        </div>
                    </div>
                </div>
                ${errorData.raw_response ? `
                <div class="p-4 bg-gray-900/50">
                    <div class="flex items-center justify-between mb-2">
                        <span class="text-sm text-gray-400">Raw SMSC Response:</span>
                        <button data-copy="${escapeAttr(errorData.raw_response)}" class="text-xs px-2 py-1 bg-gray-800 rounded hover:bg-gray-700 transition-colors">
                            <i data-lucide="copy" class="w-3 h-3 inline-block mr-1"></i>Copy
                        </button>
                    </div>
                    <div class="font-mono text-sm bg-gray-800 p-3 rounded">${escapeHtml(errorData.raw_response)}</div>
                </div>
                ` : ''}
            </div>
        `;
        lucide.createIcons();
    } finally {
        loadingIndicator.classList.add('hidden');
    }
}

function displayResults(data) {
    balanceAmount.textContent = data.balance;

    resultsTimeline.innerHTML = data.results.map(result => `
        <div class="bg-gray-900 rounded-lg overflow-hidden">
            <!-- Header section -->
            <div class="p-4 border-b border-gray-800">
                <div class="flex items-center justify-between">
                    <div class="flex items-center gap-3">
                        <div class="bg-gray-800 p-2 rounded">
                            <i data-lucide="phone" class="w-5 h-5 text-blue-500"></i>
                        </div>
                        <div>
                            <span class="text-lg font-semibold">${pivotText('phone', /^\d/.test(String(result.phone || '')) ? '+' + result.phone : result.phone, result.phone)}</span>
                            <div class="text-sm text-gray-400 mt-1">${escapeHtml(result.operator || 'Unknown Operator')} • ${escapeHtml(result.region || 'Unknown Region')}</div>
                        </div>
                    </div>
                    <div class="flex items-center gap-2">
                        <button data-raw="${escapeAttr(result.raw_response)}" class="text-xs px-2 py-1 bg-gray-800 rounded hover:bg-gray-700 transition-colors mr-2">
                            <i data-lucide="code" class="w-3 h-3 inline-block mr-1"></i>Raw
                        </button>
                        <span class="text-sm px-3 py-1 rounded-full ${result.status === 'OK' ? 'bg-green-900/50 text-green-200' : 'bg-yellow-900/50 text-yellow-200'}">
                            ${escapeHtml(result.status)}
                        </span>
                    </div>
                </div>
            </div>

            <!-- Details section -->
            <div class="p-4 bg-gray-900/50">
                <div class="grid grid-cols-3 gap-4">
                    <div class="bg-gray-800 p-3 rounded-lg">
                        <div class="flex items-center gap-2 mb-2">
                            <i data-lucide="globe" class="w-4 h-4 text-gray-400"></i>
                            <span class="text-xs text-gray-400">MCC</span>
                        </div>
                        <span class="text-sm font-semibold">${escapeHtml(result.mcc || "N/A")}</span>
                    </div>
                    <div class="bg-gray-800 p-3 rounded-lg">
                        <div class="flex items-center gap-2 mb-2">
                            <i data-lucide="network" class="w-4 h-4 text-gray-400"></i>
                            <span class="text-xs text-gray-400">MNC</span>
                        </div>
                        <span class="text-sm font-semibold">${escapeHtml(result.mnc || "N/A")}</span>
                    </div>
                    <div class="bg-gray-800 p-3 rounded-lg">
                        <div class="flex items-center gap-2 mb-2">
                            <i data-lucide="fingerprint" class="w-4 h-4 text-gray-400"></i>
                            <span class="text-xs text-gray-400">IMSI</span>
                        </div>
                        <span class="text-sm font-semibold">${escapeHtml(result.imsi || "N/A")}</span>
                    </div>
                </div>
            </div>
        </div>
    `).join('');

    lucide.createIcons();
}

function showRawResponse(rawResponse) {
    // Create modal or dialog to show raw response
    const modal = document.createElement('div');
    modal.className = 'fixed inset-0 bg-black/50 flex items-center justify-center z-50';
    modal.innerHTML = `
        <div class="bg-gray-900 rounded-lg p-6 max-w-2xl w-full mx-4">
            <div class="flex justify-between items-center mb-4">
                <h3 class="text-lg font-semibold">Raw SMSC Response</h3>
                <button onclick="this.closest('.fixed').remove()" class="text-gray-400 hover:text-white">
                    <i data-lucide="x" class="w-5 h-5"></i>
                </button>
            </div>
            <div class="bg-gray-800 p-4 rounded font-mono text-sm mb-4">${escapeHtml(rawResponse)}</div>
            <div class="flex justify-end">
                <button data-copy="${escapeAttr(rawResponse)}" class="text-sm px-3 py-1 bg-gray-800 rounded hover:bg-gray-700 transition-colors">
                    <i data-lucide="copy" class="w-4 h-4 inline-block mr-1"></i>Copy
                </button>
            </div>
        </div>
    `;
    document.body.appendChild(modal);
    lucide.createIcons();
}

// Open the raw-response modal (delegated from data-raw buttons)
document.addEventListener('click', (event) => {
    const btn = event.target.closest('[data-raw]');
    if (!btn) return;
    showRawResponse(btn.getAttribute('data-raw') || '');
});

// ---- Free offline analysis (libphonenumber) ----
const phoneInfoResults = document.getElementById('phoneInfoResults');

function phoneInfoCard(info) {
    const link = (href, label, icon) => `<a href="${escapeAttr(safeUrl(href) || href)}" target="_blank" rel="noopener noreferrer" class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded bg-gray-800 hover:bg-gray-700 text-xs"><i class="${icon}"></i>${label}</a>`;
    const field = (label, value) => value ? `<div><div class="text-xs text-gray-500">${label}</div><div class="text-gray-100">${escapeHtml(value)}</div></div>` : '';
    return `
        <div class="bg-gray-900 rounded-lg p-5 border ${info.valid ? 'border-gray-800' : 'border-yellow-700/60'}">
            <div class="flex items-center justify-between gap-3 flex-wrap mb-4">
                <div>${pivotChip('phone', info.e164, info.international)}</div>
                <span class="text-xs px-2 py-0.5 rounded-full ${info.valid ? 'bg-emerald-900/50 text-emerald-300' : 'bg-yellow-900/50 text-yellow-300'}">${info.valid ? 'valid number' : 'not a valid number'}</span>
            </div>
            <div class="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                ${field('Country / region', [info.location, info.region].filter(Boolean).join(' · '))}
                ${field('Original carrier', info.carrier)}
                ${field('Line type', info.line_type)}
                ${field('Timezone', (info.timezones || []).join(', '))}
            </div>
            <div class="mt-4">
                <div class="text-xs text-gray-500 mb-1">Formats to search for</div>
                <div class="flex flex-wrap gap-1.5">${(info.search_formats || []).map(f => `<button type="button" data-copy="${escapeAttr(f)}" class="font-mono text-xs px-2 py-0.5 rounded bg-gray-800 hover:bg-gray-700" title="Copy">${escapeHtml(f)}</button>`).join('')}</div>
            </div>
            <div class="mt-4 flex flex-wrap gap-2">
                ${link(info.links.whatsapp, 'WhatsApp', 'fab fa-whatsapp')}
                ${link(info.links.telegram, 'Telegram', 'fab fa-telegram')}
                ${`<a href="${escapeAttr(info.links.viber)}" class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded bg-gray-800 hover:bg-gray-700 text-xs"><i class="fab fa-viber"></i>Viber</a>`}
                ${link(info.links.google, 'Google all formats', 'fab fa-google')}
            </div>
            <p class="text-xs text-gray-500 mt-3">${escapeHtml(info.note)}</p>
        </div>`;
}

async function analyzePhones() {
    const numbers = phoneInput.value.split(/[,;\n]+/).map(n => n.trim()).filter(Boolean);
    if (!numbers.length) return;
    phoneInfoResults.innerHTML = '<p class="text-gray-400"><i class="fas fa-spinner fa-spin mr-2"></i>Analyzing…</p>';
    const cards = await Promise.all(numbers.map(async (number) => {
        const response = await fetch(`/api/phone/info?phone=${encodeURIComponent(number)}`);
        const data = await response.json().catch(() => ({}));
        if (!response.ok) return `<div class="bg-gray-900 rounded-lg p-4 text-red-300 text-sm">${escapeHtml(number)}: ${escapeHtml(data.detail || 'could not analyze')}</div>`;
        return phoneInfoCard(data);
    }));
    phoneInfoResults.innerHTML = cards.join('');
}

document.getElementById('analyzeButton').addEventListener('click', analyzePhones);
searchButton.addEventListener('click', performHLRLookup);
// Enter runs the free analysis; the paid HLR request needs an explicit click
phoneInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') analyzePhones();
});
