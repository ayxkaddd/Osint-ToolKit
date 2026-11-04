// Initialize Lucide icons
lucide.createIcons();

// Enable result loading
window.currentService = 'vk_profile';
window.loadResultIntoView = function (data, record) {
    // running: a lookup still streaming in the background (main.js refreshes it)
    displayResults(data, record ? (record.running ? 'running' : record.partial ? 'partial' : '') : '');
};

(async function checkAuthStatus() {
    try {
        const response = await fetch('/auth/tg/status');
        if (!response.ok) throw new Error('Failed to check auth status');

        const data = await response.json();
        if (!data.authorized) {
            window.location.href = '/telegram_auth';
        }
    } catch (error) {
        console.error('Authorization check failed:', error);
        showTemporaryNotification('Error checking authorization status', 'error');
    }
})();

const els = {
    input: document.getElementById('user-id'),
    searchBtn: document.getElementById('vkSearchBtn'),
    stopBtn: document.getElementById('vkStopBtn'),
    results: document.getElementById('results'),
    status: document.getElementById('vkStatus'),
    statusIcon: document.getElementById('vkStatusIcon'),
    statusText: document.getElementById('vkStatusText'),
    error: document.getElementById('vkError'),
    notices: document.getElementById('vkNotices'),
    entries: document.getElementById('profile-entries'),
    photosCard: document.getElementById('photosCard'),
    photos: document.getElementById('photos'),
    emptyPeriods: document.getElementById('vkEmptyPeriods'),
};
const view = { entries: 0, photos: 0, emptyPeriods: [] };
let controller = null; // set while a search is running

function setStatus(kind, text) {
    els.status.classList.remove('hidden');
    els.statusIcon.innerHTML =
        kind === 'running'
            ? '<span class="block w-2.5 h-2.5 rounded-full bg-purple-400 animate-pulse"></span>'
            : `<i data-lucide="${kind === 'done' ? 'check-circle-2' : 'circle-alert'}" class="w-4 h-4 ${kind === 'done' ? 'text-emerald-400' : 'text-amber-400'}"></i>`;
    els.statusText.textContent = text;
    lucide.createIcons();
}

function showError(message) {
    els.error.textContent = message;
    els.error.classList.remove('hidden');
}

function resetView() {
    view.entries = 0;
    view.photos = 0;
    view.emptyPeriods = [];
    els.emptyPeriods.classList.add('hidden');
    els.entries.innerHTML = '';
    els.photos.innerHTML = '';
    els.notices.innerHTML = '';
    els.notices.classList.add('hidden');
    els.photosCard.classList.add('hidden');
    els.error.classList.add('hidden');
    els.status.classList.add('hidden');
    els.results.classList.remove('hidden');
}

function countsText() {
    const photos = view.photos ? `, ${view.photos} photo${view.photos === 1 ? '' : 's'}` : '';
    return `${view.entries} snapshot${view.entries === 1 ? '' : 's'}${photos}`;
}

async function searchProfile() {
    const userId = els.input.value.trim();
    if (!userId || controller) return;

    resetView();
    controller = new AbortController();
    els.searchBtn.disabled = true;
    els.stopBtn.classList.remove('hidden');
    const started = Date.now();
    let done = null;
    let failed = false;
    const progress = () => setStatus('running', `Asking the bot… ${countsText()} so far`);
    setStatus('running', 'Asking the bot…');

    const handle = (event) => {
        if (event.event === 'waiting') setStatus('running', 'Waiting for another VK lookup to finish…');
        else if (event.event === 'started') progress();
        else if (event.event === 'entry') {
            addEntry(event.entry);
            progress();
        } else if (event.event === 'photos') {
            addPhotos(event.photos || []);
            progress();
        } else if (event.event === 'notice') addNotice(event.text);
        else if (event.event === 'nothing_for') addEmptyPeriod(event.period);
        else if (event.event === 'error') {
            failed = true;
            showError(event.detail || 'The lookup failed');
        } else if (event.event === 'done') done = event;
    };

    try {
        const response = await fetch(`/api/telegram/search/stream?user_id=${encodeURIComponent(userId)}`, {
            signal: controller.signal,
        });
        if (!response.ok) {
            const data = await response.json().catch(() => ({}));
            const detail = Array.isArray(data.detail) ? data.detail.map((d) => d.msg).join(', ') : data.detail;
            throw new Error(detail || `Search failed (HTTP ${response.status})`);
        }
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        for (;;) {
            const { done: finished, value } = await reader.read();
            if (finished) break;
            buffer += decoder.decode(value, { stream: true });
            const blocks = buffer.split('\n\n');
            buffer = blocks.pop();
            for (const block of blocks) {
                const data = block
                    .split('\n')
                    .filter((l) => l.startsWith('data:'))
                    .map((l) => l.slice(5).trimStart())
                    .join('\n');
                if (!data) continue;
                try {
                    handle(JSON.parse(data));
                } catch (e) {
                    console.error('Bad VK history event', e);
                }
            }
        }
    } catch (error) {
        if (error.name !== 'AbortError') {
            failed = true;
            showError(error.message);
        }
    } finally {
        controller = null;
        els.searchBtn.disabled = false;
        els.stopBtn.classList.add('hidden');
    }

    const seconds = Math.round((Date.now() - started) / 1000);
    if (done && done.complete) setStatus('done', `${countsText()} in ${seconds}s`);
    else if (done) setStatus('stopped', `The bot did not finish within 60 seconds - ${countsText()}, maybe incomplete`);
    else if (failed) els.status.classList.add('hidden');
    else setStatus('stopped', `Stopped after ${seconds}s · ${countsText()}`);
    showEmpty();
}

function stopSearch() {
    if (controller) controller.abort();
}

// A saved result (from an investigation)
// state: '' for a finished result, 'partial' when it was stopped, 'running' while it still streams
function displayResults(data, state = '') {
    resetView();
    (data.notices || []).forEach(addNotice);
    (data.empty_periods || []).forEach(addEmptyPeriod);
    if (data.status === 'error' && data.message) showError(data.message);
    if (data.error) showError(data.error);
    (data.entries || []).forEach(addEntry);
    addPhotos(data.photos || []);
    if (state === 'running') {
        setStatus('running', `Asking the bot… ${countsText()} so far`);
        return;
    }
    if (data.stopped || state === 'partial') setStatus('stopped', `Stopped before the bot finished · ${countsText()}`);
    else if (data.complete === false)
        setStatus('stopped', `The bot did not finish within 60 seconds - ${countsText()}, maybe incomplete`);
    showEmpty();
}

function showEmpty() {
    if (!view.entries && els.notices.classList.contains('hidden') && els.error.classList.contains('hidden'))
        els.entries.innerHTML = '<p class="text-gray-400">No profile history found.</p>';
}

// Bot replies that aren't profile data: limits, nothing found...
function addNotice(text) {
    if (!text) return;
    els.notices.classList.remove('hidden');
    els.notices.insertAdjacentHTML('beforeend', `<p class="whitespace-pre-wrap">${escapeHtml(text)}</p>`);
}

// Periods the bot has no snapshot for, on one line
function addEmptyPeriod(period) {
    if (!period) return;
    view.emptyPeriods.push(period);
    els.emptyPeriods.textContent = `No snapshot for ${view.emptyPeriods.join(', ')}`;
    els.emptyPeriods.classList.remove('hidden');
}

// Values the bot lists with ';'
const LIST_FIELDS = ['career', 'education', 'family'];

const FIELD_LABELS = {
    url: 'Profile link',
    vk_id: 'VK id',
    aka: 'Also known as',
    mobile_phone: 'Mobile phone',
    home_phone: 'Home phone',
    icq: 'ICQ',
    contacts: 'Contacts',
    homepage: 'Home page',
    tv: 'TV',
};

const FIELD_ICONS = {
    url: 'link',
    vk_id: 'fingerprint',
    full_name: 'user',
    first_name: 'user',
    last_name: 'user',
    gender: 'user',
    country: 'globe',
    hometown: 'home',
    city: 'map-pin',
    last_login: 'clock',
    device: 'smartphone',
    followers: 'users',
    university: 'graduation-cap',
    faculty: 'book-open',
    username: 'at-sign',
    marital_status: 'heart',
    normalized_name: 'user-check',
    education: 'book',
    avatar: 'image',
    birth_date: 'calendar',
    last_visit: 'clock',
    aka: 'user',
    region: 'map',
    email: 'mail',
    mobile_phone: 'smartphone',
    home_phone: 'phone',
    icq: 'message-circle',
    contacts: 'contact',
    website: 'globe',
    homepage: 'home',
    career: 'briefcase',
    family: 'users',
    interests: 'sparkles',
    music: 'music',
    movies: 'film',
    tv: 'tv',
    books: 'book',
    games: 'gamepad-2',
};

function addEntry(entry) {
    if (!entry) return;
    view.entries += 1;
    const entryDiv = document.createElement('div');
    entryDiv.className = 'bg-gray-800 rounded-lg p-4 space-y-3';

    const headerHtml = `
        <div class="flex items-center justify-between border-b border-gray-700 pb-2 mb-3">
            <div class="flex items-center gap-4">
                ${
                    entry.avatar
                        ? `
                    <img src="${escapeAttr(safeUrl(entry.avatar))}" referrerpolicy="no-referrer"
                         alt="Profile avatar" data-image-view="" data-image-title="Profile avatar"
                         class="w-12 h-12 rounded-full object-cover"
                         data-placeholder-size="w-12 h-12 rounded-full shrink-0" data-placeholder-icon-only onerror="imageLoadFailed(this)">`
                        : '<div class="w-12 h-12 rounded-full bg-gray-700 flex items-center justify-center"><i data-lucide="user" class="w-6 h-6"></i></div>'
                }
                <div>
                    <span class="font-semibold">${escapeHtml(entry.year_month || 'Unknown Date')}</span>
                    ${entry.full_name ? `<div class="text-sm text-gray-400">${escapeHtml(entry.full_name)}</div>` : ''}
                </div>
            </div>
        </div>
    `;

    const field = (key, value, label = formatFieldName(key)) => {
        const text = String(value);
        // "A;B;C" lists (jobs, schools, family) one per line
        const items = LIST_FIELDS.includes(key)
            ? text
                  .split(';')
                  .map((t) => t.trim())
                  .filter(Boolean)
            : [text];
        const wide = text.length > 40 || items.length > 1;
        const shown =
            key === 'url' || key === 'website'
                ? safeUrl(text)
                    ? `<a href="${escapeAttr(safeUrl(text))}" target="_blank" rel="noopener noreferrer" class="text-sm text-blue-400 hover:text-blue-300 break-all">${escapeHtml(text)}</a>`
                    : escapeHtml(text)
                : key === 'vk_id' || key === 'username'
                  ? pivotText('vk', text)
                  : items.length > 1
                    ? items.map((item) => `<div>${pivotInText(item)}</div>`).join('')
                    : wide
                      ? pivotInText(items[0] ?? text)
                      : pivotField(key, items[0] ?? text);
        return `
            <div class="flex items-start gap-3 min-w-0 ${wide ? 'md:col-span-2' : ''}">
                <div class="w-5 h-5 text-gray-400 shrink-0"><i data-lucide="${FIELD_ICONS[key] || 'circle'}"></i></div>
                <span class="text-gray-400 text-sm shrink-0">${escapeHtml(label)}:</span>
                <span class="text-sm min-w-0 break-words">${shown}</span>
            </div>`;
    };
    const fields =
        Object.entries(entry)
            .filter(
                ([key, value]) =>
                    value !== null &&
                    value !== '' &&
                    typeof value !== 'object' &&
                    !['year_month', 'avatar', 'full_name'].includes(key)
            )
            .map(([key, value]) => field(key, value))
            .join('') +
        // lines the parser doesn't know yet, under the bot's own label
        Object.entries(entry.other || {})
            .map(([label, value]) => field('', value, label))
            .join('');
    const photos =
        (entry.photos || []).length > 1
            ? `
        <div class="flex flex-wrap gap-2 pt-1">${entry.photos
            .map(
                (url) => `
            <button type="button" data-image-view="${escapeAttr(safeUrl(url))}" data-image-title="${escapeAttr(`Photo · ${entry.year_month || ''}`)}">
                <img src="${escapeAttr(safeUrl(url))}" referrerpolicy="no-referrer" alt="" loading="lazy"
                     class="w-16 h-16 rounded-lg object-cover" data-placeholder-size="w-16 h-16 rounded-lg" onerror="imageLoadFailed(this)">
            </button>`
            )
            .join('')}</div>`
            : '';

    entryDiv.innerHTML = `
        ${headerHtml}
        <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
            ${fields}
        </div>
        ${photos}
    `;
    els.entries.querySelector('p.text-gray-400')?.remove();
    els.entries.appendChild(entryDiv);
    lucide.createIcons();
}

function addPhotos(urls) {
    urls.forEach((photoUrl) => {
        view.photos += 1;
        const photoDiv = document.createElement('div');
        photoDiv.className = 'relative group';
        photoDiv.innerHTML = `
            <button type="button" data-image-view="${escapeAttr(safeUrl(photoUrl))}" data-image-title="Profile photo" class="block w-full">
                <img src="${escapeAttr(safeUrl(photoUrl))}" referrerpolicy="no-referrer"
                     alt="Profile photo"
                     class="w-full h-48 object-cover rounded-lg transition-transform duration-200 group-hover:scale-105"
                     data-placeholder-size="w-full h-48 rounded-lg" onerror="imageLoadFailed(this)">
            </button>
        `;
        els.photos.appendChild(photoDiv);
    });
    if (view.photos) els.photosCard.classList.remove('hidden');
}

function formatFieldName(key) {
    if (FIELD_LABELS[key]) return FIELD_LABELS[key];
    const text = key.replace(/_/g, ' ');
    return text.charAt(0).toUpperCase() + text.slice(1);
}

// Handle Enter key in search input
if (els.input) {
    els.input.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            searchProfile();
        }
    });
}
