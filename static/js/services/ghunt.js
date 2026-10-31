// GHunt page (templates/ghunt.html). Results are drawn by static/js/ghunt_cards.js,
// shared with saved results on the investigation page.
(function () {
    const TYPES = {
        email: {
            endpoint: '/api/ghunt/email', param: 'email', placeholder: 'someone@gmail.com',
            hint: 'The Google account behind an email: name, photo, Gaia ID, Maps activity and Google services in use.',
            test: (v) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v),
        },
        gaia: {
            endpoint: '/api/ghunt/gaia', param: 'gaia_id', placeholder: '113997182440839277998',
            hint: "Google's permanent account ID (15-25 digits) - found in other GHunt results and Google URLs.",
            test: (v) => /^\d{15,25}$/.test(v),
        },
        drive: {
            endpoint: '/api/ghunt/drive', param: 'drive_url', placeholder: 'https://docs.google.com/document/d/…',
            hint: 'A shared Google Drive / Docs link or file ID: owners, people with access, dates and comments.',
            test: (v) => /^https:\/\/(drive|docs)\.google\.com\//.test(v),
        },
        geolocate: {
            endpoint: '/api/ghunt/geolocate', param: 'bssid', placeholder: 'AA:BB:CC:DD:EE:FF',
            hint: "A Wi-Fi access point's MAC address (BSSID): where Google's location data puts it.",
            test: (v) => /^[0-9A-Fa-f]{2}([:-][0-9A-Fa-f]{2}){5}$/.test(v),
        },
        spiderdal: {
            endpoint: '/api/ghunt/spiderdal', param: 'domain', placeholder: 'example.com',
            hint: 'Websites and Android apps that declare the same owner as this domain (Digital Asset Links).',
            test: (v) => /^(https?:\/\/)?([a-z0-9-]+\.)+[a-z]{2,}(\/.*)?$/i.test(v) && !v.includes('@'),
        },
    };
    const METHOD_TYPES = {
        lookup_ghunt_email: 'email', lookup_ghunt_gaia: 'gaia', lookup_ghunt_drive: 'drive',
        lookup_ghunt_geolocate: 'geolocate', lookup_ghunt_spiderdal: 'spiderdal',
    };
    const $ = (id) => document.getElementById(id);
    const state = { type: 'email', chosenByHand: false, controller: null, timer: null };

    window.currentService = 'ghunt';

    function setType(type, byHand = false) {
        state.type = type;
        if (byHand) state.chosenByHand = true;
        document.querySelectorAll('#ghuntTypes [data-type]').forEach(b => b.classList.toggle('active', b.dataset.type === type));
        $('searchInput').placeholder = TYPES[type].placeholder;
        $('moduleHint').textContent = TYPES[type].hint;
    }

    // Pasting an email, Gaia ID, Drive link, BSSID or domain picks the matching lookup
    function detectType() {
        const value = $('searchInput').value.trim();
        if (!value || state.chosenByHand && TYPES[state.type].test(value)) return;
        const found = Object.keys(TYPES).find(t => TYPES[t].test(value));
        if (found && found !== state.type) setType(found);
    }

    // "Nothing found" is an answer, not an error
    function showNotFound(message) {
        $('ghuntError').innerHTML = `<div class="text-gray-300"><i class="fas fa-search mr-2 text-gray-500"></i>${escapeHtml(message)}</div>`;
        $('ghuntError').className = 'mt-6 px-4 py-3 rounded-lg bg-gray-800/60 border border-gray-700 text-sm';
    }

    function showError(message) {
        $('ghuntError').className = 'mt-6 px-4 py-3 rounded-lg bg-red-500/10 border border-red-500/30 text-sm text-red-200';
        let help = '';
        if (/not logged in|login|credential|cookies|oauth|master token/i.test(message)) {
            help = 'GHunt needs a Google login: run <code>ghunt login</code> (or <code>python main.py login</code> in the GHunt folder) as the user that runs the toolkit.';
        } else if (/not set up|not found \(GHUNT|GHUNT_/i.test(message)) {
            help = 'Set the GHunt folder in <a href="/settings" class="underline">Settings</a> (GHunt venv and main.py).';
        } else if (/did not finish|timed out/i.test(message)) {
            help = 'Google answered slowly - try again in a minute.';
        }
        $('ghuntError').innerHTML = `<div class="font-medium"><i class="fas fa-exclamation-triangle mr-2"></i>${escapeHtml(message)}</div>`
            + (help ? `<div class="text-red-200/80 mt-1">${help}</div>` : '');
        $('ghuntError').classList.remove('hidden');
    }

    function setBusy(busy) {
        $('searchButton').disabled = busy;
        $('ghuntStatus').classList.toggle('hidden', !busy);
        clearInterval(state.timer);
        if (busy) {
            const started = Date.now();
            const tick = () => {
                const s = Math.round((Date.now() - started) / 1000);
                $('ghuntStatusText').textContent = `Asking Google… ${s}s${s >= 8 ? ' - lookups usually take 10-30 seconds' : ''}`;
            };
            tick();
            state.timer = setInterval(tick, 1000);
        }
    }

    function render(data) {
        const box = $('resultsData');
        box.innerHTML = ghuntResultHtml(data);
        box.classList.remove('hidden');
        if (window.lucide) lucide.createIcons();
    }

    async function performSearch() {
        let value = $('searchInput').value.trim();
        if (!value) return;
        const type = TYPES[state.type];
        if (state.type === 'gaia' && !type.test(value)) {
            showError('A Gaia ID is a number of 15-25 digits.');
            return;
        }
        $('ghuntError').classList.add('hidden');
        $('resultsData').classList.add('hidden');
        setBusy(true);
        if (state.controller) state.controller.abort();
        state.controller = new AbortController();
        try {
            const response = await fetch(`${type.endpoint}?${type.param}=${encodeURIComponent(value)}`, { signal: state.controller.signal });
            const data = await response.json().catch(() => ({}));
            if (response.status === 404) {
                showNotFound(data.detail || 'Nothing found.');
                return;
            }
            if (!response.ok) {
                const detail = Array.isArray(data.detail) ? data.detail.map(d => d.msg).join(', ') : data.detail;
                throw new Error(detail || `GHunt request failed (HTTP ${response.status})`);
            }
            render(data);
        } catch (error) {
            if (error.name !== 'AbortError') showError(error.message);
        } finally {
            setBusy(false);
            state.controller = null;
        }
    }

    // Saved results (module history, investigation "open in module")
    window.loadResultIntoView = (data, record) => {
        const type = (record && METHOD_TYPES[record.method_name]) || null;
        if (type) setType(type);
        const params = (record && record.parameters && record.parameters.kwargs) || {};
        const value = params[TYPES[state.type].param] || params.email || params.gaia_id || params.bssid || params.domain || params.drive_url;
        $('searchInput').value = value || '';
        $('ghuntError').classList.add('hidden');
        render(data);
    };

    document.querySelectorAll('#ghuntTypes [data-type]').forEach(b => b.addEventListener('click', () => {
        setType(b.dataset.type, true);
        $('searchInput').focus();
    }));
    $('searchInput').addEventListener('input', detectType);
    $('searchInput').addEventListener('keydown', (e) => { if (e.key === 'Enter') performSearch(); });
    $('searchButton').addEventListener('click', performSearch);
    setType('email');
    if (window.lucide) lucide.createIcons();
})();
