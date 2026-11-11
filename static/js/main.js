// main.js - shared layout behaviour (loaded on every page via base.html):
// active investigation selector, module history panel, update check,
// notifications and the HTML-escaping / clipboard helpers other scripts use.

// ---------------------------------------------------------------------------
// HTML-escaping helpers. Use these before interpolating any externally-sourced
// value (OSINT results, user input, API data) into innerHTML / template
// literals to prevent stored/reflected XSS in the analyst's session.
// ---------------------------------------------------------------------------
function escapeHtml(value) {
    if (value === null || value === undefined) return '';
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

// Escape for use inside a double-quoted HTML attribute.
function escapeAttr(value) {
    return escapeHtml(value);
}

// Return url only if it uses a safe scheme (http/https/mailto/tel); else "".
// Prevents javascript:/data: URLs from external data landing in href.
function safeUrl(url) {
    if (!url) return '';
    const s = String(url).trim();
    if (/^(https?:|mailto:|tel:)/i.test(s)) return s;
    if (/^\//.test(s)) return s; // site-relative
    if (/^[a-z][a-z0-9+.-]*:/i.test(s)) return ''; // some other scheme -> reject
    return 'https://' + s; // bare domain
}

window.escapeHtml = escapeHtml;
window.escapeAttr = escapeAttr;
window.safeUrl = safeUrl;

// A value passed to a function in an inline handler: onclick="fn(${jsArg(value)})".
// A JSON string literal, then attribute-escaped (the browser decodes the attribute first).
function jsArg(value) {
    return escapeAttr(JSON.stringify(String(value ?? '')));
}
window.jsArg = jsArg;

// Pictures already on screen are carried over when a part of the page is rebuilt: an
// <img> in `fresh` with the same src as one in `old` is swapped for the old element,
// which keeps its loaded (or loading) image instead of blinking while it loads again.
function keepLoadedImages(old, fresh) {
    // src -> the old <img>s showing it (a card can show the same site icon twice)
    const shown = new Map();
    old.querySelectorAll('img[src]').forEach((img) => {
        const src = img.getAttribute('src');
        const failed = img.complete && img.naturalWidth === 0;
        if (!failed) shown.set(src, [...(shown.get(src) || []), img]);
    });
    fresh.querySelectorAll('img[src]').forEach((img) => {
        const kept = (shown.get(img.getAttribute('src')) || []).shift();
        if (kept) img.replaceWith(kept);
    });
}
window.keepLoadedImages = keepLoadedImages;

// container.innerHTML = html, without reloading the pictures it already shows
function replaceKeepingImages(container, html) {
    const template = document.createElement('template');
    template.innerHTML = html;
    keepLoadedImages(container, template.content);
    container.replaceChildren(template.content);
}
window.replaceKeepingImages = replaceKeepingImages;

// lucide.createIcons() re-renders *every* icon on the page on each call (rendered
// SVGs keep their data-lucide attribute). Scripts call it after every render, so
// patch it to only convert icons that have not been rendered yet.
(function patchLucide() {
    const L = window.lucide;
    if (!L || typeof L.createIcons !== 'function' || L.__onlyPending) return;
    const original = L.createIcons;
    try {
        L.createIcons = function (options = {}) {
            const pending = document.querySelectorAll('[data-lucide]:not(svg)');
            if (!pending.length) return;
            pending.forEach((el) => el.setAttribute('data-lucide-pending', el.getAttribute('data-lucide')));
            original({ ...options, nameAttr: 'data-lucide-pending' });
            document
                .querySelectorAll('svg[data-lucide-pending]')
                .forEach((svg) => svg.removeAttribute('data-lucide-pending'));
        };
        L.__onlyPending = true;
    } catch (e) {
        /* read-only export: keep the original behaviour */
    }
})();

function refreshIcons() {
    if (window.lucide) window.lucide.createIcons();
}
window.refreshIcons = refreshIcons;

// Dates look the same everywhere: "Nov 11, 2026, 11:47 AM" in the reader's own locale
// (month by name, so 11/12 can't be read two ways). `seconds` for message times.
function fmtDateTime(value, seconds = false) {
    const date = value instanceof Date ? value : new Date(value);
    if (value === null || value === undefined || value === '' || isNaN(date)) return '';
    return date.toLocaleString([], { dateStyle: 'medium', timeStyle: seconds ? 'medium' : 'short' });
}
function fmtDate(value) {
    const date = value instanceof Date ? value : new Date(value);
    if (value === null || value === undefined || value === '' || isNaN(date)) return '';
    return date.toLocaleDateString([], { dateStyle: 'medium' });
}
window.fmtDateTime = fmtDateTime;
window.fmtDate = fmtDate;

function timeAgo(date) {
    const seconds = Math.floor((new Date() - new Date(date)) / 1000);
    const units = [
        [31536000, 'year'],
        [2592000, 'month'],
        [86400, 'day'],
        [3600, 'hour'],
        [60, 'minute'],
    ];
    for (const [size, name] of units) {
        const n = Math.floor(seconds / size);
        if (n >= 1) return `${n} ${name}${n > 1 ? 's' : ''} ago`;
    }
    return 'just now';
}
window.timeAgo = timeAgo;

// ---------------------------------------------------------------------------
// Clipboard: renderers add data-copy="<escaped value>" to a clickable element
// instead of inlining the value into an onclick JS string.
// ---------------------------------------------------------------------------
async function copyTextToClipboard(text) {
    try {
        if (navigator.clipboard && window.isSecureContext) {
            await navigator.clipboard.writeText(text);
            return true;
        }
    } catch (e) {
        /* fall through to legacy path */
    }
    try {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        return true;
    } catch (e) {
        return false;
    }
}
window.copyTextToClipboard = copyTextToClipboard;

document.addEventListener('click', (event) => {
    const el = event.target.closest('[data-copy]');
    if (!el) return;
    event.preventDefault();
    copyTextToClipboard(el.getAttribute('data-copy') || '').then((ok) => {
        showTemporaryNotification(ok ? 'Copied to clipboard' : 'Copy failed', ok ? 'success' : 'error');
    });
});

// ---------------------------------------------------------------------------
// Notifications
// ---------------------------------------------------------------------------
function showTemporaryNotification(message, type = 'success') {
    const notification = document.createElement('div');
    const bgColor = type === 'success' ? 'bg-green-600' : type === 'info' ? 'bg-gray-700' : 'bg-red-600';
    notification.className = `toast fixed bottom-4 right-4 ${bgColor} text-white px-5 py-3 rounded-lg shadow-lg z-[60] max-w-md`;
    notification.innerHTML = `
        <div class="flex items-center space-x-2 text-sm">
            <i class="fas ${type === 'success' ? 'fa-check-circle' : type === 'info' ? 'fa-info-circle' : 'fa-exclamation-circle'}"></i>
            <span>${escapeHtml(message)}</span>
        </div>
    `;
    document.body.appendChild(notification);
    requestAnimationFrame(() => notification.classList.add('toast-visible'));
    // Errors often carry instructions (e.g. "GHunt is not logged in") - keep them longer
    setTimeout(
        () => {
            notification.classList.remove('toast-visible');
            setTimeout(() => notification.remove(), 250);
        },
        type === 'error' || String(message).length > 80 ? 6000 : 2800
    );
}
window.showTemporaryNotification = showTemporaryNotification;

// ---------------------------------------------------------------------------
// Confirmation window in the app's style, instead of the browser's confirm().
//   if (!(await appConfirm('Delete this result?', { danger: true, confirmLabel: 'Delete' }))) return;
// options: title, confirmLabel, cancelLabel, danger (red button; Cancel has the focus, so
// Enter can't delete by accident). Resolves true/false; Escape or a click outside is Cancel.
// ---------------------------------------------------------------------------
function appConfirm(message, options = {}) {
    const { title = 'Are you sure?', confirmLabel = 'OK', cancelLabel = 'Cancel', danger = false } = options;
    document.getElementById('appConfirm')?.dispatchEvent(new Event('app-confirm-cancel'));
    const before = document.activeElement;
    const overlay = document.createElement('div');
    overlay.id = 'appConfirm';
    overlay.className = 'modal fixed inset-0 bg-black/70 flex items-center justify-center z-[90] p-4';
    overlay.setAttribute('role', 'alertdialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.innerHTML = `
        <div class="modal-panel bg-gray-900 rounded-xl p-6 max-w-md w-full border border-gray-800 shadow-2xl">
            <div class="flex items-start gap-4">
                <div class="w-10 h-10 rounded-full flex items-center justify-center shrink-0 ${danger ? 'bg-red-950/70 text-red-300' : 'bg-purple-950/70 text-purple-300'}">
                    <i class="fas ${danger ? 'fa-trash' : 'fa-question'}"></i>
                </div>
                <div class="min-w-0 flex-1">
                    <h2 id="appConfirmTitle" class="text-lg font-semibold text-white">${escapeHtml(title)}</h2>
                    <p class="mt-2 text-sm text-gray-300 whitespace-pre-line break-words">${escapeHtml(message)}</p>
                </div>
            </div>
            <div class="flex justify-end gap-3 mt-6">
                <button type="button" data-confirm-answer="no" class="px-4 py-2 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-gray-500">${escapeHtml(cancelLabel)}</button>
                <button type="button" data-confirm-answer="yes"
                    class="px-5 py-2 ${danger ? 'bg-red-600 hover:bg-red-500 focus:ring-red-400' : 'bg-purple-600 hover:bg-purple-500 focus:ring-purple-400'} text-white font-medium rounded-lg focus:outline-none focus:ring-2">${escapeHtml(confirmLabel)}</button>
            </div>
        </div>`;
    overlay.setAttribute('aria-labelledby', 'appConfirmTitle');
    document.body.appendChild(overlay);
    requestAnimationFrame(() => overlay.classList.add('modal-open'));
    const buttons = [...overlay.querySelectorAll('[data-confirm-answer]')];
    (danger ? buttons[0] : buttons[1]).focus();

    return new Promise((resolve) => {
        let answered = false;
        const finish = (answer) => {
            if (answered) return;
            answered = true;
            document.removeEventListener('keydown', onKey, true);
            overlay.classList.remove('modal-open');
            setTimeout(() => overlay.remove(), 150);
            if (before && typeof before.focus === 'function' && document.contains(before)) before.focus();
            resolve(answer);
        };
        // Escape and Tab stay in this window: other windows under it keep their own keys
        const onKey = (event) => {
            if (event.key === 'Escape') {
                event.preventDefault();
                event.stopImmediatePropagation();
                finish(false);
            } else if (event.key === 'Tab') {
                event.preventDefault();
                const next = buttons[(buttons.indexOf(document.activeElement) + 1) % buttons.length];
                next.focus();
            }
        };
        document.addEventListener('keydown', onKey, true);
        overlay.addEventListener('app-confirm-cancel', () => finish(false), { once: true });
        overlay.addEventListener('click', (event) => {
            const answer = event.target.closest('[data-confirm-answer]');
            if (answer) finish(answer.dataset.confirmAnswer === 'yes');
            else if (event.target === overlay) finish(false);
        });
    });
}
window.appConfirm = appConfirm;

// ---------------------------------------------------------------------------
// Active investigation. The server's "current investigation" decides where
// module results are saved, so it is the source of truth; localStorage only
// mirrors it for scripts that read it synchronously.
// ---------------------------------------------------------------------------
let currentInvestigationId = localStorage.getItem('currentInvestigationId') || null;
let investigations = [];

function setCurrentInvestigationLocal(id) {
    currentInvestigationId = id || null;
    if (currentInvestigationId) localStorage.setItem('currentInvestigationId', currentInvestigationId);
    else {
        localStorage.removeItem('currentInvestigationId');
        localStorage.removeItem('currentInvestigationName');
    }
}

async function syncCurrentInvestigation() {
    try {
        const response = await fetch('/api/investigations/current');
        if (!response.ok) return;
        const data = await response.json();
        setCurrentInvestigationLocal(data.investigation_id);
    } catch (e) {
        console.error('Could not read current investigation:', e);
    }
}

async function loadInvestigations() {
    try {
        const response = await fetch('/api/investigations/');
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        investigations = data.investigations || [];
        updateInvestigationsList();
        updateCurrentInvestigationDisplay();
    } catch (error) {
        console.error('Error loading investigations:', error);
        const list = document.getElementById('investigationsList');
        if (list) {
            list.innerHTML = `
                <div class="p-3 text-center text-red-400 text-sm">
                    <i class="fas fa-exclamation-triangle"></i>
                    <span class="ml-2">Error loading investigations</span>
                </div>
            `;
        }
    }
}

function updateInvestigationsList() {
    const listContainer = document.getElementById('investigationsList');
    if (!listContainer) return;

    // Completed and archived cases are done: only the active ones (and the one recording) are listed
    const shown = investigations.filter(
        (i) => (i.status || 'active') === 'active' || i.investigation_id === currentInvestigationId
    );
    const closed = investigations.length - shown.length;
    const closedLink = closed
        ? `<a href="/investigations#completed" class="block px-3 py-2 text-xs text-gray-500 hover:text-white hover:bg-gray-800 border-t border-gray-800">
              ${closed} completed or archived · see all investigations →</a>`
        : '';

    if (shown.length === 0) {
        listContainer.innerHTML = `
            <div class="p-4 text-center text-gray-500 text-sm">
                <i class="fas fa-folder-open"></i>
                <span class="ml-2">${investigations.length ? 'No active investigations' : 'No investigations yet'}</span>
            </div>${closedLink}
        `;
        return;
    }

    const stopItem = currentInvestigationId
        ? `<button type="button" data-investigation-clear
              class="w-full text-left px-3 py-2 text-sm text-gray-400 hover:bg-gray-800 hover:text-white border-b border-gray-800">
          <i class="fas fa-stop-circle mr-2"></i>Stop recording results
       </button>`
        : '';

    listContainer.innerHTML =
        stopItem +
        shown
            .map((investigation) => {
                const active = currentInvestigationId === investigation.investigation_id;
                const status = investigation.status || 'active';
                const id = escapeAttr(investigation.investigation_id);
                return `
        <div class="group flex items-stretch hover:bg-gray-800 ${active ? 'bg-gray-800/80' : ''}" data-investigation-row="${id}">
            <button type="button" data-investigation-id="${id}" title="Record lookups here (right-click for more)"
                    class="investigation-item flex-1 min-w-0 text-left px-3 py-2">
                <div class="flex items-center gap-3">
                    ${
                        investigation.picture_url
                            ? `<img src="${escapeAttr(investigation.picture_url)}" alt="" loading="lazy" class="w-8 h-8 rounded-md object-cover shrink-0">`
                            : `<div class="w-8 h-8 rounded-md bg-gray-800 flex items-center justify-center shrink-0 text-gray-500"><i class="fas fa-folder"></i></div>`
                    }
                    <div class="flex-1 min-w-0">
                        <div class="flex items-center gap-2">
                            <span class="font-medium text-white truncate text-sm">${escapeHtml(investigation.name)}</span>
                            ${active ? '<span class="rec-dot" title="Recording"></span>' : ''}
                            ${status !== 'active' ? `<span class="text-[10px] uppercase px-1.5 py-0.5 rounded bg-gray-800 text-gray-400 border border-gray-700">${escapeHtml(status)}</span>` : ''}
                        </div>
                        <div class="text-xs text-gray-500 truncate">
                            ${escapeHtml(investigation.results_count || 0)} results · ${escapeHtml(fmtDate(investigation.created_at))}
                        </div>
                    </div>
                </div>
            </button>
            <div class="flex items-center gap-0.5 pr-2 opacity-60 group-hover:opacity-100 focus-within:opacity-100">
                <a href="/api/investigations/${encodeURIComponent(investigation.investigation_id)}/view" title="Open its results"
                   class="w-7 h-7 rounded flex items-center justify-center text-gray-400 hover:text-white hover:bg-gray-700"><i class="fas fa-layer-group text-xs"></i></a>
                <button type="button" data-investigation-menu="${id}" title="More"
                   class="w-7 h-7 rounded flex items-center justify-center text-gray-400 hover:text-white hover:bg-gray-700"><i class="fas fa-ellipsis-h text-xs"></i></button>
            </div>
        </div>`;
            })
            .join('') +
        closedLink;
}

document.addEventListener('click', (event) => {
    const menu = event.target.closest('[data-investigation-menu]');
    if (menu && menu.closest('#investigationsList')) {
        const inv = investigations.find((i) => i.investigation_id === menu.dataset.investigationMenu);
        // the row owns it too: a right-click on the row closes it like a second click on ⋯
        if (inv) openContextMenu(menu, investigationMenuItems(inv), inv.name, menu.closest('[data-investigation-row]'));
        return;
    }
    const item = event.target.closest('[data-investigation-id]');
    if (item && item.closest('#investigationsList')) {
        const inv = investigations.find((i) => i.investigation_id === item.dataset.investigationId);
        selectInvestigation(item.dataset.investigationId, inv ? inv.name : '');
        return;
    }
    if (event.target.closest('[data-investigation-clear]')) {
        clearCurrentInvestigation();
    }
});

// Right-click on an investigation in the header menu
document.addEventListener('contextmenu', (event) => {
    const row = event.target.closest('#investigationsList [data-investigation-row]');
    if (!row) return;
    const inv = investigations.find((i) => i.investigation_id === row.dataset.investigationRow);
    if (!inv) return;
    event.preventDefault();
    openContextMenu(event, investigationMenuItems(inv), inv.name, row);
});

// After an investigation is marked completed or archived: if it is the one recording, ask
// whether to stop - lookups would keep going into a case that is done
async function offerToStopRecording(investigationId, status, name = '') {
    if (status === 'active' || investigationId !== currentInvestigationId) return;
    const label = name ? `"${name}"` : 'This investigation';
    const stop = await appConfirm(
        `${label} is ${status}, but lookups are still being recorded into it. Stop recording into it?`,
        { title: 'Stop recording?', confirmLabel: 'Stop recording', cancelLabel: 'Keep recording' }
    );
    if (stop) await clearCurrentInvestigation();
}
window.offerToStopRecording = offerToStopRecording;

// What can be done with an investigation from anywhere (header menu, investigations page)
function investigationMenuItems(inv) {
    const id = inv.investigation_id;
    const page = `/api/investigations/${encodeURIComponent(id)}`;
    const status = inv.status || 'active';
    const setStatus = (value) => async () => {
        const response = await fetch(page, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: value }),
        });
        if (!response.ok) return showTemporaryNotification('Could not change the status', 'error');
        showTemporaryNotification(`"${inv.name}" is now ${value}`, 'success');
        await offerToStopRecording(id, value, inv.name);
        await loadInvestigations();
        document.dispatchEvent(new CustomEvent('investigation:updated', { detail: { investigationId: id } }));
    };
    return [
        currentInvestigationId === id
            ? { label: 'Stop recording here', icon: 'fa-stop-circle', onClick: clearCurrentInvestigation }
            : { label: 'Record lookups here', icon: 'fa-dot-circle', onClick: () => selectInvestigation(id, inv.name) },
        { divider: true },
        { label: 'Open results', icon: 'fa-layer-group', href: `${page}/view` },
        { label: 'Timeline', icon: 'fa-stream', href: `${page}/view#events` },
        { label: 'Identifiers', icon: 'fa-fingerprint', href: `${page}/view#identifiers` },
        { label: 'Notes', icon: 'fa-sticky-note', href: `${page}/notes/view` },
        { label: 'Report', icon: 'fa-file-alt', href: `${page}/report`, newTab: true },
        { divider: true },
        status === 'active'
            ? { label: 'Mark as completed', icon: 'fa-check-circle', onClick: setStatus('completed') }
            : { label: 'Reopen (active)', icon: 'fa-undo', onClick: setStatus('active') },
        status !== 'archived' ? { label: 'Archive', icon: 'fa-box-archive', onClick: setStatus('archived') } : null,
    ].filter(Boolean);
}
window.investigationMenuItems = investigationMenuItems;

// ---------------------------------------------------------------------------
// Context menu: right-click (or a "⋯" button) on something gives its actions.
// openContextMenu(eventOrElement, [{label, icon, href, newTab, onClick, danger, checked} | {divider: true}], title, owner)
// owner: what the menu belongs to (a row, a card); a second click on it closes the menu
// instead of opening it again. A button passed as eventOrElement is its own owner.
// ---------------------------------------------------------------------------
let contextMenuOwner = null;
let contextMenuDismissed = { owner: null, at: 0 }; // what a press outside just closed the menu of

function closeContextMenu() {
    document.getElementById('contextMenu')?.remove();
    contextMenuOwner = null;
}
window.closeContextMenu = closeContextMenu;

function openContextMenu(at, items, title = '', owner = null) {
    owner = owner || (at instanceof Element ? at : null);
    // the press that started this click or right-click closed this same menu: leave it closed
    if (owner && contextMenuDismissed.owner === owner && Date.now() - contextMenuDismissed.at < 800) {
        contextMenuDismissed = { owner: null, at: 0 };
        return;
    }
    closeContextMenu();
    contextMenuOwner = owner;
    const menu = document.createElement('div');
    menu.id = 'contextMenu';
    menu.setAttribute('role', 'menu');
    menu.className =
        'fixed z-[80] min-w-[13rem] max-w-xs bg-gray-900 border border-gray-700 rounded-lg shadow-2xl py-1 text-sm';
    const actions = [];
    menu.innerHTML =
        (title
            ? `<div class="px-3 py-1.5 text-[11px] uppercase tracking-wider text-gray-500 truncate">${escapeHtml(title)}</div>`
            : '') +
        items
            .map((item) => {
                if (item.divider) return '<div class="my-1 border-t border-gray-800"></div>';
                const cls = `w-full flex items-center gap-2.5 px-3 py-1.5 text-left ${item.danger ? 'text-red-300 hover:bg-red-950/60' : 'text-gray-200 hover:bg-gray-800'} focus:bg-gray-800 focus:outline-none`;
                const inner = `<i class="fas ${escapeAttr(item.icon || 'fa-circle')} w-4 text-center text-gray-500"></i><span class="flex-1 truncate">${escapeHtml(item.label)}</span>${item.checked ? '<i class="fas fa-check text-xs text-emerald-400"></i>' : ''}`;
                if (item.href)
                    return `<a role="menuitem" href="${escapeAttr(item.href)}" ${item.newTab ? 'target="_blank" rel="noopener"' : ''} class="${cls}">${inner}</a>`;
                actions.push(item.onClick);
                return `<button type="button" role="menuitem" data-context-action="${actions.length - 1}" class="${cls}">${inner}</button>`;
            })
            .join('');
    document.body.appendChild(menu);

    // at the pointer, or under the button that opened it; kept on screen
    const rect = at instanceof Element ? at.getBoundingClientRect() : null;
    const x = rect ? rect.right - menu.offsetWidth : at.clientX;
    const y = rect ? rect.bottom + 4 : at.clientY;
    menu.style.left = `${Math.max(8, Math.min(x, window.innerWidth - menu.offsetWidth - 8))}px`;
    menu.style.top = `${Math.max(8, Math.min(y, window.innerHeight - menu.offsetHeight - 8))}px`;

    menu.addEventListener('click', (event) => {
        const action = event.target.closest('[data-context-action]');
        if (event.target.closest('a, [data-context-action]')) closeContextMenu();
        if (action) actions[Number(action.dataset.contextAction)]?.();
    });
    menu.addEventListener('keydown', (event) => {
        const entries = [...menu.querySelectorAll('[role="menuitem"]')];
        const index = entries.indexOf(document.activeElement);
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault();
            const next = (index + (event.key === 'ArrowDown' ? 1 : -1) + entries.length) % entries.length;
            entries[next]?.focus();
        }
    });
    menu.querySelector('[role="menuitem"]')?.focus({ preventScroll: true });
}
window.openContextMenu = openContextMenu;

document.addEventListener(
    'mousedown',
    (event) => {
        if (event.target.closest('#contextMenu') || !document.getElementById('contextMenu')) return;
        contextMenuDismissed = { owner: contextMenuOwner, at: Date.now() };
        closeContextMenu();
    },
    true
);
// Escape closes the menu only, not the dropdown or window it was opened from
document.addEventListener(
    'keydown',
    (event) => {
        if (event.key !== 'Escape' || !document.getElementById('contextMenu')) return;
        event.stopImmediatePropagation();
        closeContextMenu();
    },
    true
);
window.addEventListener('scroll', closeContextMenu, { passive: true });
window.addEventListener('resize', closeContextMenu);
window.addEventListener('blur', closeContextMenu);

function closeInvestigationsDropdown() {
    const dropdown = document.getElementById('investigationsDropdownMenu');
    const icon = document.getElementById('dropdownIcon');
    if (dropdown) dropdown.classList.add('hidden');
    if (icon) icon.style.transform = 'rotate(0deg)';
}

function toggleInvestigationsDropdown() {
    const dropdown = document.getElementById('investigationsDropdownMenu');
    const icon = document.getElementById('dropdownIcon');
    if (!dropdown) return;

    if (dropdown.classList.contains('hidden')) {
        dropdown.classList.remove('hidden');
        if (icon) icon.style.transform = 'rotate(180deg)';
        loadInvestigations();
    } else {
        closeInvestigationsDropdown();
    }
}

// Close dropdown when clicking outside
document.addEventListener('click', (event) => {
    const dropdown = document.getElementById('investigationsDropdownMenu');
    const button = document.getElementById('investigationsDropdown');
    if (dropdown && button && !dropdown.contains(event.target) && !button.contains(event.target)) {
        closeInvestigationsDropdown();
    }
});

async function selectInvestigation(investigationId, investigationName) {
    try {
        const response = await fetch(`/api/investigations/set`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: new URLSearchParams({ investigation_id: investigationId }),
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
    } catch (error) {
        console.error('Error selecting investigation:', error);
        showTemporaryNotification('Failed to select investigation', 'error');
        return false;
    }

    setCurrentInvestigationLocal(investigationId);
    updateCurrentInvestigationDisplay();
    updateInvestigationsList();
    closeInvestigationsDropdown();
    showTemporaryNotification(`Recording into: ${investigationName || 'investigation'}`, 'success');
    checkExistingResults();
    document.dispatchEvent(new CustomEvent('investigation:changed', { detail: { investigationId } }));
    return true;
}

async function clearCurrentInvestigation() {
    try {
        const response = await fetch('/api/investigations/clear', { method: 'DELETE' });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
    } catch (error) {
        showTemporaryNotification('Failed to stop recording', 'error');
        return;
    }
    setCurrentInvestigationLocal(null);
    updateCurrentInvestigationDisplay();
    updateInvestigationsList();
    closeInvestigationsDropdown();
    removeHistoryUi();
    showTemporaryNotification('Results are no longer recorded', 'info');
    document.dispatchEvent(new CustomEvent('investigation:changed', { detail: { investigationId: null } }));
}

function updateCurrentInvestigationDisplay() {
    const displayElement = document.getElementById('currentInvestigationName');
    const button = document.getElementById('investigationsDropdown');
    if (!displayElement) return;

    const current =
        currentInvestigationId && investigations.find((inv) => inv.investigation_id === currentInvestigationId);
    if (currentInvestigationId && !current && investigations.length) {
        // The active investigation was deleted
        setCurrentInvestigationLocal(null);
    }
    // A module page (it sets window.currentService) with nowhere to save its results
    document
        .getElementById('notSavedBanner')
        ?.classList.toggle('hidden', Boolean(currentInvestigationId) || !window.currentService);
    if (current) {
        displayElement.textContent = current.name;
        // Shown straight away on the next page load (inline script in base.html)
        localStorage.setItem('currentInvestigationName', current.name);
        displayElement.classList.add('text-purple-300');
        if (button) {
            button.classList.add('recording');
            button.title = 'Module results are being saved to this investigation';
        }
    } else {
        displayElement.textContent = 'No investigation';
        displayElement.classList.remove('text-purple-300');
        if (button) {
            button.classList.remove('recording');
            button.title = 'Select an investigation to save module results';
        }
    }
}

// ---------------------------------------------------------------------------
// Create investigation modal
// ---------------------------------------------------------------------------
function openCreateInvestigationModal() {
    const modal = document.getElementById('createInvestigationModal');
    if (!modal) return;
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    requestAnimationFrame(() => modal.classList.add('modal-open'));
    closeInvestigationsDropdown();
    setTimeout(() => document.getElementById('investigationName')?.focus(), 50);
}

function closeCreateInvestigationModal() {
    const modal = document.getElementById('createInvestigationModal');
    if (!modal) return;
    modal.classList.remove('modal-open');
    setTimeout(() => {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
        document.getElementById('createInvestigationForm')?.reset();
    }, 150);
}

const createInvestigationForm = document.getElementById('createInvestigationForm');
if (createInvestigationForm) {
    createInvestigationForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const submit = createInvestigationForm.querySelector('button[type="submit"]');
        const name = document.getElementById('investigationName').value.trim();

        const formData = new FormData();
        formData.append('name', name);
        formData.append('description', document.getElementById('investigationDescription').value);
        const pictureFile = document.getElementById('investigationPicture').files[0];
        if (pictureFile) formData.append('picture', pictureFile);

        if (submit) submit.disabled = true;
        try {
            const response = await fetch('/api/investigations/create', { method: 'POST', body: formData });
            const result = await response.json().catch(() => ({}));
            if (!response.ok) throw new Error(result.detail || 'Failed to create investigation');

            await loadInvestigations();
            await selectInvestigation(result.investigation_id, name);
            closeCreateInvestigationModal();
            document.dispatchEvent(new CustomEvent('investigation:created', { detail: result }));
        } catch (error) {
            console.error('Error creating investigation:', error);
            showTemporaryNotification(error.message || 'Failed to create investigation', 'error');
        } finally {
            if (submit) submit.disabled = false;
        }
    });
}

document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    closeInvestigationsDropdown();
    const createModal = document.getElementById('createInvestigationModal');
    if (createModal && !createModal.classList.contains('hidden')) closeCreateInvestigationModal();
    document.getElementById('historyModal')?.remove();
});

async function logout() {
    try {
        await fetch('/logout', { method: 'POST' });
    } finally {
        window.location.href = '/';
    }
}
window.logout = logout;

window.getCurrentInvestigationId = () => currentInvestigationId;
window.openCreateModal = openCreateInvestigationModal;
window.loadInvestigationsDropdown = loadInvestigations;
window.selectInvestigation = selectInvestigation;
window.clearCurrentInvestigation = clearCurrentInvestigation;

// ---------------------------------------------------------------------------
// Update check
// ---------------------------------------------------------------------------
async function checkForUpdates() {
    try {
        const response = await fetch('/api/updates/check');
        const update = await response.json().catch(() => null);
        if (!response.ok) {
            showTemporaryNotification(`Update check failed: ${update?.detail || `HTTP ${response.status}`}`, 'error');
            return;
        }

        if (update && update.configured === false) {
            showTemporaryNotification('Update checks are not configured (set UPDATE_REPO in .env)', 'info');
            return;
        }
        if (!update || !update.sha) {
            showTemporaryNotification('You are up to date!', 'success');
            return;
        }

        const date = new Date(update.date);
        document.getElementById('updateAuthorAvatar').src =
            safeUrl(update.author_avatar) || '/static/avatar_placeholder.png';
        document.getElementById('updateAuthorName').textContent = update.committer;
        document.getElementById('updateDate').textContent = isNaN(date)
            ? ''
            : date.toLocaleDateString('en-US', {
                  year: 'numeric',
                  month: 'long',
                  day: 'numeric',
                  hour: '2-digit',
                  minute: '2-digit',
              });

        const [message, description] = (update.message || '').split('\n\n');
        document.getElementById('updateMessage').textContent = message;
        const descContainer = document.getElementById('descriptionContainer');
        const descElement = document.getElementById('updateDescription');
        const toggleBtn = document.getElementById('toggleDescription');
        if (description) {
            descElement.textContent = description;
            descContainer.classList.remove('hidden');
            toggleBtn.onclick = () => {
                const icon = toggleBtn.querySelector('i');
                const hidden = descElement.classList.toggle('hidden');
                icon.style.transform = hidden ? 'rotate(0deg)' : 'rotate(180deg)';
            };
        } else {
            descContainer.classList.add('hidden');
        }

        const stats = update.stats || { additions: 0, deletions: 0, total: 0 };
        document.getElementById('updateTotalChanges').textContent = `${stats.total} changes`;
        document.getElementById('updateAdditions').textContent = `+${stats.additions}`;
        document.getElementById('updateDeletions').textContent = `-${stats.deletions}`;
        document.getElementById('updateCommitHash').textContent = (update.sha || '').slice(0, 7);
        document.getElementById('updateCommitUrl').href = safeUrl(update.commit_url) || '#';

        const maxChanges = Math.max(stats.additions, stats.deletions) || 1;
        setTimeout(() => {
            document.getElementById('updateAdditionsBar').style.width = `${(stats.additions / maxChanges) * 100}%`;
            document.getElementById('updateDeletionsBar').style.width = `${(stats.deletions / maxChanges) * 100}%`;
        }, 100);

        openUpdateModal();
    } catch (error) {
        console.error('Error checking for updates:', error);
        showTemporaryNotification('Failed to check for updates', 'error');
    }
}

function openUpdateModal() {
    const modal = document.getElementById('updateModal');
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    requestAnimationFrame(() => modal.classList.add('modal-open'));
}

function closeUpdateModal() {
    const modal = document.getElementById('updateModal');
    modal.classList.remove('modal-open');
    setTimeout(() => {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
    }, 150);
}

// ---------------------------------------------------------------------------
// Module history: each tool page sets window.currentService and (optionally)
// window.loadResultIntoView(result, record). Saved results of the current
// investigation for that module can then be re-opened without re-running.
// ---------------------------------------------------------------------------
let moduleHistory = [];

function formatParameters(params) {
    if (!params) return '';
    const kwargs = params.kwargs || params;
    return Object.entries(kwargs)
        .filter(([, value]) => value !== null && value !== undefined && value !== '' && value !== false)
        .map(([key, value]) => {
            const text = typeof value === 'object' ? JSON.stringify(value) : String(value);
            const short = text.length > 80 ? text.slice(0, 80) + '…' : text;
            return `<span class="text-xs text-gray-500 mr-2">${escapeHtml(key)}: <span class="text-gray-300">${escapeHtml(short)}</span></span>`;
        })
        .join('');
}

function removeHistoryUi() {
    document.getElementById('resultLoadNotification')?.remove();
    document.getElementById('persistentHistoryBtn')?.remove();
    moduleHistory = [];
}

async function checkExistingResults() {
    removeHistoryUi();
    if (!currentInvestigationId || !window.currentService) return;

    try {
        const response = await fetch(
            `/api/investigations/results/legacy?service_name=${encodeURIComponent(window.currentService)}`
        );
        if (!response.ok) return;
        const data = await response.json();
        moduleHistory = data.results || [];
        if (typeof window.updateHistoryList === 'function') window.updateHistoryList(moduleHistory);
        if (moduleHistory.length === 0) return;

        showPersistentHistoryButton();
        if (typeof window.loadResultIntoView === 'function') showResultLoadNotification();
    } catch (error) {
        console.error('Error checking existing results:', error);
    }
}

function showResultLoadNotification() {
    const latest = moduleHistory[0];
    const notification = document.createElement('div');
    notification.id = 'resultLoadNotification';
    notification.className =
        'fixed bottom-20 left-6 bg-[#1a1b26] border border-purple-500/40 text-white rounded-xl shadow-2xl z-40 max-w-sm w-full slide-in';
    notification.innerHTML = `
        <div class="p-4">
            <div class="flex items-start gap-3">
                <div class="bg-purple-500/20 p-2.5 rounded-lg shrink-0"><i class="fas fa-history text-purple-400"></i></div>
                <div class="flex-1 min-w-0">
                    <h4 class="font-semibold text-sm text-white">${moduleHistory.length} saved result${moduleHistory.length > 1 ? 's' : ''} in this investigation</h4>
                    <p class="text-xs text-gray-400 mt-1 truncate">Latest: <span class="text-gray-200">${escapeHtml(latest.target || latest.method_name)}</span> · ${escapeHtml(timeAgo(latest.timestamp))}</p>
                </div>
                <button type="button" data-history-dismiss class="text-gray-500 hover:text-white p-1"><i class="fas fa-times"></i></button>
            </div>
            <div class="flex gap-2 mt-3">
                <button type="button" data-history-load="${escapeAttr(latest.result_id)}" class="flex-1 bg-purple-600 hover:bg-purple-500 px-3 py-1.5 rounded-lg text-sm font-medium">Load latest</button>
                <button type="button" data-history-open class="flex-1 bg-gray-800 hover:bg-gray-700 px-3 py-1.5 rounded-lg text-sm border border-gray-700">View all</button>
            </div>
        </div>
    `;
    document.body.appendChild(notification);
    setTimeout(() => notification.remove(), 12000);
}

function showPersistentHistoryButton() {
    if (document.getElementById('persistentHistoryBtn')) return;
    const btn = document.createElement('button');
    btn.id = 'persistentHistoryBtn';
    btn.type = 'button';
    btn.dataset.historyOpen = '';
    btn.className =
        'fixed bottom-6 left-6 bg-gray-900 hover:bg-purple-600 text-purple-300 hover:text-white border border-purple-500/40 h-12 w-12 rounded-full shadow-lg z-30 flex items-center justify-center';
    btn.title = 'Saved results for this module';
    btn.innerHTML = `<i class="fas fa-history text-lg"></i><span class="history-count">${moduleHistory.length}</span>`;
    document.body.appendChild(btn);
}

// A saved result the page's own view can't draw (an older format, a saved error):
// shown with the investigation page's renderer, which handles anything
function showSavedResultFallback(record) {
    document.getElementById('savedResultFallback')?.remove();
    const page = document.querySelector('.page') || document.querySelector('main') || document.body;
    const card = document.createElement('div');
    card.id = 'savedResultFallback';
    card.className = 'card mb-6';
    card.innerHTML = `
    <h2 class="text-lg font-semibold text-white mb-1">Saved result</h2>
    <p class="muted-note mb-4">This result doesn't fit this page's usual layout, so it is shown as saved.</p>
    ${safeRender(record.service_name, record.method_name, record.result, record)}`;
    const lead = page.querySelector(':scope > .page-lead');
    if (lead) lead.after(card);
    else page.prepend(card);
    refreshIcons();
}
window.showSavedResultFallback = showSavedResultFallback;

// A lookup still streaming in the background (opened from the jobs tray) comes back
// with running: true and what it has found so far; the page follows it until it's saved.
const LIVE_REFRESH_MS = 2000;
const live = { timer: null, resultId: null, signature: null, sawRunning: false };

function stopFollowingResult() {
    clearTimeout(live.timer);
    Object.assign(live, { timer: null, resultId: null, signature: null, sawRunning: false });
    document.getElementById('liveResultBanner')?.remove();
}

function showLiveResultBanner() {
    if (document.getElementById('liveResultBanner')) return;
    const banner = document.createElement('div');
    banner.id = 'liveResultBanner';
    banner.className =
        'mb-5 bg-[#1a1b26] border border-purple-500/40 rounded-xl px-4 py-2.5 flex items-center gap-3 text-sm';
    banner.innerHTML = `
        <span class="block w-2.5 h-2.5 rounded-full bg-purple-400 animate-pulse shrink-0"></span>
        <span class="flex-1 text-gray-200">This lookup is still running in the background - the page updates as results arrive.</span>
        <button type="button" data-live-stop class="shrink-0 whitespace-nowrap text-xs text-gray-400 hover:text-white border border-gray-700 rounded-lg px-2 py-1">Stop following</button>`;
    placeUnderPageTitle(banner, document.getElementById('savedResultBar'));
}

// In the page, under its title (where a saved result that doesn't fit is shown too), after `after` if given
function placeUnderPageTitle(element, after = null) {
    const page = document.querySelector('.page') || document.querySelector('main') || document.body;
    const lead = after || page.querySelector(':scope > .page-lead');
    if (lead) lead.after(element);
    else page.prepend(element);
}

// Which saved result the page shows: what was looked up, with which module and when
function showSavedResultBar(record, investigationId) {
    document.getElementById('savedResultBar')?.remove();
    const bar = document.createElement('div');
    bar.id = 'savedResultBar';
    bar.className =
        'mb-5 bg-[#1a1b26] border border-gray-700 rounded-xl px-4 py-2.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm';
    const method = typeof methodLabel === 'function' ? methodLabel(record.method_name) : record.method_name;
    const when = record.timestamp ? `${timeAgo(record.timestamp)} · ${fmtDateTime(record.timestamp)}` : '';
    const link = `/api/investigations/${encodeURIComponent(investigationId)}/view#result-${encodeURIComponent(record.result_id)}`;
    bar.innerHTML = `
        <i class="fas fa-history text-purple-400 shrink-0"></i>
        <span class="text-gray-400 shrink-0">Saved result</span>
        ${record.target ? `<span class="font-mono text-purple-200 break-all">${escapeHtml(record.target)}</span>` : ''}
        <span class="text-gray-500">${escapeHtml([method, when].filter(Boolean).join(' · '))}</span>
        ${record.partial && !record.running ? '<span class="text-[10px] uppercase px-1.5 py-0.5 rounded bg-yellow-900/60 text-yellow-300" title="The lookup was stopped before it finished">partial</span>' : ''}
        <a href="${escapeAttr(link)}" class="ml-auto text-xs text-purple-300 hover:text-white shrink-0">Open in investigation →</a>`;
    placeUnderPageTitle(bar);
}

// The page's search box shows what the loaded result looked up (when it's one value and the box is empty)
async function prefillSavedQuery(record) {
    const target = String(record.target || '').trim();
    if (!target || / \+ |, |…/.test(target)) return;
    const module = (await getModules()).find(
        (m) => m.page === window.location.pathname && m.prefill && m.service === record.service_name
    );
    const input = module && document.querySelector(module.prefill.input);
    if (input && !input.value.trim()) input.value = target;
}

async function loadResult(resultId, investigationId = currentInvestigationId, following = false) {
    if (!investigationId || typeof window.loadResultIntoView !== 'function') return;
    if (!following) stopFollowingResult();
    else if (live.resultId !== resultId) return; // stopped, or another result was opened meanwhile
    try {
        const response = await fetch(
            `/api/investigations/${encodeURIComponent(investigationId)}/results/${encodeURIComponent(resultId)}`
        );
        if (following && live.resultId !== resultId) return;
        if (response.status === 404 && following) {
            // finished with nothing worth saving (a failed or empty lookup)
            stopFollowingResult();
            showTemporaryNotification('The lookup finished without a result to keep', 'info');
            return;
        }
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const { result: record } = await response.json();
        const signature = JSON.stringify(record.result ?? null);
        if (!following || signature !== live.signature) {
            document.getElementById('savedResultFallback')?.remove();
            try {
                window.loadResultIntoView(record.result, record);
            } catch (renderError) {
                console.error("This page can't draw the saved result:", renderError);
                showSavedResultFallback(record);
            }
            showSavedResultBar(record, investigationId);
            if (!following) prefillSavedQuery(record);
        }
        document.getElementById('resultLoadNotification')?.remove();
        document.getElementById('historyModal')?.remove();
        if (record.running) {
            Object.assign(live, { resultId, signature, sawRunning: true });
            showLiveResultBanner();
            live.timer = setTimeout(() => loadResult(resultId, investigationId, true), LIVE_REFRESH_MS);
        } else {
            const finished = following && live.sawRunning;
            stopFollowingResult();
            showTemporaryNotification(finished ? 'Lookup finished - result saved' : 'Saved result loaded', 'success');
        }
    } catch (error) {
        console.error('Error loading result:', error);
        if (following) {
            // a hiccup while following: try again rather than give up
            live.timer = setTimeout(() => loadResult(resultId, investigationId, true), LIVE_REFRESH_MS * 2);
            return;
        }
        showTemporaryNotification('Failed to load saved result', 'error');
    }
}

// Starting a search of your own on the page stops following the background one
// (and the "Saved result" bar goes: the page no longer shows that result)
function ownSearchStarted() {
    if (live.resultId) stopFollowingResult();
    document.getElementById('savedResultBar')?.remove();
}
document.addEventListener(
    'click',
    (event) => {
        if (live.resultId && event.target.closest('[data-live-stop]')) return stopFollowingResult();
        if (event.target.closest('#liveResultBanner, #savedResultBar, #historyModal, #resultLoadNotification')) return;
        if (
            event.target.closest(
                'button.btn-primary, button[id*="search" i], button[onclick*="search" i], button[type="submit"]'
            )
        )
            ownSearchStarted();
    },
    true
);
document.addEventListener(
    'keydown',
    (event) => {
        if (event.key === 'Enter' && event.target.matches('.page input, .page textarea')) ownSearchStarted();
    },
    true
);

function showResultSelector() {
    document.getElementById('resultLoadNotification')?.remove();
    if (!moduleHistory.length) {
        showTemporaryNotification('No saved results for this module', 'info');
        return;
    }
    const canLoad = typeof window.loadResultIntoView === 'function';

    const rows = moduleHistory
        .map(
            (r) => `
        <div class="group bg-gray-800/50 hover:bg-gray-800 border border-gray-700 hover:border-purple-500/50 rounded-xl p-4 ${canLoad ? 'cursor-pointer' : ''}"
             ${canLoad ? `data-history-load="${escapeAttr(r.result_id)}"` : ''}>
            <div class="flex justify-between items-start gap-3">
                <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2 mb-1 flex-wrap">
                        <span class="font-semibold text-white truncate">${escapeHtml(r.target || r.method_name)}</span>
                        ${r.partial ? '<span class="text-[10px] uppercase px-1.5 py-0.5 rounded bg-yellow-900/60 text-yellow-300">partial</span>' : ''}
                        ${r.children && r.children.length ? `<span class="text-[10px] px-1.5 py-0.5 rounded bg-purple-900/60 text-purple-300">+${r.children.length} follow-up</span>` : ''}
                    </div>
                    <div class="text-xs text-gray-400">${escapeHtml(r.summary || '')} · ${escapeHtml(timeAgo(r.timestamp))}</div>
                    <div class="mt-1 break-all">${formatParameters(r.parameters)}</div>
                </div>
                ${canLoad ? '<i class="fas fa-chevron-right text-gray-500 group-hover:text-white mt-1"></i>' : ''}
            </div>
        </div>`
        )
        .join('');

    const modal = document.createElement('div');
    modal.id = 'historyModal';
    modal.className = 'fixed inset-0 bg-black/80 flex items-center justify-center z-50 p-4';
    modal.innerHTML = `
        <div class="bg-[#1a1b26] rounded-2xl border border-gray-700 w-full max-w-2xl shadow-2xl flex flex-col max-h-[85vh] slide-in">
            <div class="p-5 border-b border-gray-800 flex justify-between items-center">
                <div>
                    <h3 class="text-lg font-bold text-white">Saved results</h3>
                    <p class="text-sm text-gray-400 mt-0.5">${canLoad ? 'Click one to load it into this page' : 'Open the investigation page to view them'}</p>
                </div>
                <div class="flex items-center gap-2">
                    <a href="/api/investigations/${escapeAttr(currentInvestigationId)}/view" class="text-sm text-purple-300 hover:text-white px-3 py-2">Open investigation</a>
                    <button type="button" data-history-close class="bg-gray-800 hover:bg-gray-700 text-gray-400 hover:text-white h-9 w-9 rounded-lg"><i class="fas fa-times"></i></button>
                </div>
            </div>
            <div class="p-5 overflow-y-auto custom-scrollbar space-y-3">${rows}</div>
        </div>
    `;
    modal.addEventListener('click', (e) => {
        if (e.target === modal) modal.remove();
    });
    document.body.appendChild(modal);
}

document.addEventListener('click', (event) => {
    const load = event.target.closest('[data-history-load]');
    if (load) return loadResult(load.dataset.historyLoad);
    if (event.target.closest('[data-history-open]')) return showResultSelector();
    if (event.target.closest('[data-history-close]')) return document.getElementById('historyModal')?.remove();
    if (event.target.closest('[data-history-dismiss]'))
        return document.getElementById('resultLoadNotification')?.remove();
});

window.loadResult = loadResult;
window.showResultSelector = showResultSelector;
window.checkExistingResults = checkExistingResults;

// Global function to fetch history for a service (can be used by templates)
async function fetchServiceHistory(serviceName) {
    if (!currentInvestigationId) return [];
    try {
        const response = await fetch(
            `/api/investigations/results/legacy?service_name=${encodeURIComponent(serviceName)}`
        );
        const data = await response.json();
        return data.status === 'success' && data.results ? data.results : [];
    } catch (error) {
        console.error('Error fetching history:', error);
        return [];
    }
}
window.fetchServiceHistory = fetchServiceHistory;

// Id of the saved result a module response was recorded as (null when not recording).
window.savedResultId = (response) =>
    response && response.headers ? response.headers.get('X-Investigation-Result-ID') : null;

// ---------------------------------------------------------------------------
// Module registry (what each module accepts, cost, readiness) - cached per page
// ---------------------------------------------------------------------------
const ENTITY_LABELS = {
    email: 'Email',
    phone: 'Phone',
    username: 'Username',
    domain: 'Domain',
    ip: 'IP address',
    url: 'URL',
    telegram_id: 'Telegram ID',
    telegram_username: 'Telegram @username',
    vk: 'VK profile',
    gaia_id: 'Gaia ID',
    bssid: 'Wi-Fi BSSID',
    crypto_btc: 'Bitcoin address',
    crypto_eth: 'Ethereum address',
    text: 'Free text',
};
window.ENTITY_LABELS = ENTITY_LABELS;

let modulesPromise = null;
function getModules(refresh = false) {
    if (!modulesPromise || refresh) {
        modulesPromise = fetch('/api/modules')
            .then((r) => (r.ok ? r.json() : { modules: [] }))
            .then((d) => d.modules || [])
            .catch(() => []);
    }
    return modulesPromise;
}
window.getModules = getModules;

function moduleBadges(m) {
    const cost =
        m.cost === 'paid'
            ? `<span class="text-[10px] px-1.5 py-0.5 rounded bg-yellow-900/60 text-yellow-300" title="${escapeAttr(m.cost_note || 'Uses paid credits')}">paid</span>`
            : `<span class="text-[10px] px-1.5 py-0.5 rounded bg-emerald-900/50 text-emerald-300">free</span>`;
    const speed =
        m.speed === 'slow'
            ? '<span class="text-[10px] text-gray-500">minutes</span>'
            : m.speed === 'medium'
              ? '<span class="text-[10px] text-gray-500">~1 min</span>'
              : '';
    return `${cost} ${speed}`;
}
window.moduleBadges = moduleBadges;

// ---------------------------------------------------------------------------
// Background jobs
// ---------------------------------------------------------------------------
let jobPollTimer = null;
let jobStatusSeen = null; // job id -> status (null until the first fetch)

async function startJob(moduleId, type, value, parentResultId = null) {
    try {
        const response = await fetch('/api/jobs', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ module: moduleId, type, value, parent_result_id: parentResultId }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
        showTemporaryNotification(`Started ${data.job.module_name} on ${value}`, 'info');
        refreshJobs();
        document.dispatchEvent(new CustomEvent('jobs:started', { detail: data.job }));
        return data.job;
    } catch (error) {
        showTemporaryNotification(error.message, 'error');
        return null;
    }
}
window.startJob = startJob;

function jobResultLink(job) {
    if (!job.result_id || !job.module_page) return null;
    return `${job.module_page}?load_result=${encodeURIComponent(job.result_id)}&investigation=${encodeURIComponent(job.investigation_id)}`;
}
window.jobResultLink = jobResultLink;

function jobStatusHtml(job) {
    const p = job.progress || {};
    if (job.status === 'running') {
        const count = p.total ? `${p.done || 0}/${p.total}` : p.done ? `${p.done}` : '';
        return `<span class="text-blue-300"><i class="fas fa-spinner fa-spin mr-1"></i>running ${escapeHtml(count)}${p.found ? ` · ${escapeHtml(p.found)} found` : ''}</span>`;
    }
    if (job.status === 'queued') return '<span class="text-gray-400"><i class="fas fa-clock mr-1"></i>queued</span>';
    if (job.status === 'done')
        return `<span class="text-emerald-300"><i class="fas fa-check mr-1"></i>${escapeHtml(job.summary || 'done')}</span>`;
    if (job.status === 'cancelled')
        return '<span class="text-gray-400"><i class="fas fa-ban mr-1"></i>cancelled</span>';
    return `<span class="text-red-300" title="${escapeAttr(job.error || '')}"><i class="fas fa-exclamation-triangle mr-1"></i>${escapeHtml((job.error || 'failed').slice(0, 90))}</span>`;
}
window.jobStatusHtml = jobStatusHtml;

function renderJobsTray(jobs) {
    const list = document.getElementById('jobsTrayList');
    const count = document.getElementById('jobsTrayCount');
    if (!list || !count) return;
    const active = jobs.filter((j) => j.status === 'running' || j.status === 'queued').length;
    count.textContent = active;
    count.classList.toggle('hidden', active === 0);
    if (!jobs.length) {
        list.innerHTML = '<div class="p-4 text-center text-gray-500">No lookups yet</div>';
        return;
    }
    list.innerHTML = jobs
        .slice(0, 25)
        .map((job) => {
            const link = jobResultLink(job);
            return `
        <div class="px-4 py-2.5 border-b border-gray-800 last:border-0">
            <div class="flex justify-between gap-2">
                <span class="font-medium text-white truncate">${escapeHtml(job.module_name)}</span>
                <span class="text-xs text-gray-500 shrink-0">${escapeHtml(timeAgo(job.created_at))}</span>
            </div>
            <div class="font-mono text-xs text-purple-200 truncate">${escapeHtml(job.value)}</div>
            <div class="flex justify-between items-center gap-2 mt-1 text-xs">
                <div class="min-w-0 truncate">${jobStatusHtml(job)}</div>
                <div class="shrink-0 flex gap-3">
                    ${job.status === 'running' || job.status === 'queued' ? `<button type="button" data-job-cancel="${escapeAttr(job.id)}" class="text-gray-400 hover:text-red-300">Cancel</button>` : ''}
                    ${link ? `<a href="${escapeAttr(link)}" class="text-purple-300 hover:text-white">Open</a>` : ''}
                </div>
            </div>
        </div>`;
        })
        .join('');
}

async function refreshJobs() {
    let jobs = [];
    try {
        const response = await fetch('/api/jobs?limit=30');
        if (!response.ok) return;
        jobs = (await response.json()).jobs || [];
    } catch (e) {
        return;
    }
    // Notify about lookups that finished while this page was open
    if (jobStatusSeen) {
        jobs.forEach((job) => {
            const before = jobStatusSeen[job.id];
            if ((before === 'running' || before === 'queued') && job.status !== before) {
                if (job.status === 'done')
                    showTemporaryNotification(`${job.module_name} finished: ${job.summary || 'done'}`, 'success');
                if (job.status === 'failed')
                    showTemporaryNotification(`${job.module_name} failed: ${job.error || ''}`, 'error');
            }
        });
    }
    jobStatusSeen = Object.fromEntries(jobs.map((j) => [j.id, j.status]));
    renderJobsTray(jobs);
    document.dispatchEvent(new CustomEvent('jobs:updated', { detail: jobs }));

    const active = jobs.some((j) => j.status === 'running' || j.status === 'queued');
    clearTimeout(jobPollTimer);
    if (active) jobPollTimer = setTimeout(refreshJobs, 2000);
}
window.refreshJobs = refreshJobs;

document.addEventListener('click', async (event) => {
    if (event.target.closest('#jobsTrayButton')) {
        document.getElementById('jobsTrayMenu')?.classList.toggle('hidden');
        refreshJobs();
        return;
    }
    const cancel = event.target.closest('[data-job-cancel]');
    if (cancel) {
        await fetch(`/api/jobs/${encodeURIComponent(cancel.dataset.jobCancel)}`, { method: 'DELETE' });
        refreshJobs();
        return;
    }
    const menu = document.getElementById('jobsTrayMenu');
    if (menu && !menu.classList.contains('hidden') && !event.target.closest('#jobsTrayMenu'))
        menu.classList.add('hidden');
});
document.addEventListener('jobs:started', () => refreshJobs());

// ---------------------------------------------------------------------------
// Pivot menu: any identifier -> look it up with another module.
// Elements with data-pivot-type / data-pivot-value open it on click.
// ---------------------------------------------------------------------------
let pivotMenuAnchor = null;

function closePivotMenu() {
    document.getElementById('pivotMenu')?.remove();
    pivotMenuAnchor = null;
}

async function openPivotMenu(type, value, anchor, options = {}) {
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
window.openPivotMenu = openPivotMenu;

// The dashboard's lists (resources.json plus plugins): {modules, ext_res}, fetched once per page
let resourcesPromise = null;
function getResources() {
    resourcesPromise =
        resourcesPromise ||
        fetch('/api/resources/')
            .then((r) => (r.ok ? r.json() : {}))
            .catch(() => ({}));
    return resourcesPromise;
}
window.getResources = getResources;

// External resources that open on a kind of identifier: {name, url, template}
function externalSearchesFor(type) {
    return getResources().then((resources) =>
        (resources.ext_res || [])
            .filter((r) => r.search && r.search[type])
            .map((r) => ({ name: r.name, url: r.url, template: r.search[type] }))
    );
}

// ---------------------------------------------------------------------------
// Modules menu (header): every module from every page, ones that need setup marked
// ---------------------------------------------------------------------------
async function renderModulesMenu() {
    const menu = document.getElementById('modulesMenu');
    const [resources, statuses] = await Promise.all([getResources(), getModules().catch(() => [])]);
    const here = window.location.pathname;
    const row = (href, icon, name, note = '') => `
        <a href="${escapeAttr(href)}" role="menuitem" ${href === here ? 'aria-current="page"' : ''}
            class="flex items-center gap-3 px-3 py-2 hover:bg-gray-800 ${href === here ? 'text-purple-300 bg-gray-800/60' : 'text-gray-200'}">
            <span class="w-5 text-center text-gray-400" aria-hidden="true">${icon}</span>
            <span class="truncate">${escapeHtml(name)}</span>${note}</a>`;
    const modules = (resources.modules || []).map((m) => {
        const related = statuses.filter((s) => s.page === m.endpoint);
        const blocked = related.length && related.every((s) => !s.ready);
        return row(
            m.endpoint,
            `<i class="${escapeAttr(m.icon_type || 'fas')} fa-${escapeAttr(m.icon || 'cube')}"></i>`,
            m.name,
            blocked ? '<span class="ml-auto shrink-0 text-[10px] text-amber-300/80">needs setup</span>' : ''
        );
    });
    menu.innerHTML =
        row('/dashboard', '<i class="fas fa-home"></i>', 'Dashboard') +
        row('/lookup', '<i class="fas fa-search"></i>', 'Lookup') +
        row('/investigations', '<i class="fas fa-folder-open"></i>', 'Investigations') +
        `<div class="border-t border-gray-800 my-1"></div>${modules.join('') || '<div class="px-3 py-2 text-gray-500">Could not load the modules</div>'}`;
}

function setModulesMenu(open) {
    const menu = document.getElementById('modulesMenu');
    const button = document.getElementById('modulesMenuButton');
    if (!menu || !button) return;
    menu.classList.toggle('hidden', !open);
    button.setAttribute('aria-expanded', String(open));
    if (open) renderModulesMenu();
}

document.addEventListener('click', (event) => {
    const menu = document.getElementById('modulesMenu');
    if (!menu) return;
    if (event.target.closest('#modulesMenuButton')) setModulesMenu(menu.classList.contains('hidden'));
    else if (!event.target.closest('#modulesMenu')) setModulesMenu(false);
});
document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') setModulesMenu(false);
});

// ---------------------------------------------------------------------------
// Names for screen readers. Icon-only buttons and links are described by their
// tooltip, and fields without a <label> by their placeholder; this copies those
// into aria-label wherever a page (or a later render) didn't set one.
// ---------------------------------------------------------------------------
function nameUnlabelledControls(root = document) {
    root.querySelectorAll('button:not([aria-label]), a[href]:not([aria-label])').forEach((el) => {
        if (el.textContent.trim() || el.getAttribute('aria-labelledby')) return;
        const name = el.getAttribute('title') || el.querySelector('img[alt]')?.getAttribute('alt');
        if (name) el.setAttribute('aria-label', name.replace(/\s*\([^)]*\)\s*$/, ''));
    });
    root.querySelectorAll(
        'input:not([type=hidden]):not([aria-label]), textarea:not([aria-label]), select:not([aria-label])'
    ).forEach((el) => {
        if (el.getAttribute('aria-labelledby') || el.closest('label')) return;
        if (el.id && document.querySelector(`label[for="${CSS.escape(el.id)}"]`)) return;
        const name =
            el.getAttribute('placeholder') ||
            el.getAttribute('title') ||
            (el.tagName === 'SELECT' ? el.options[0]?.textContent : '');
        if (name) el.setAttribute('aria-label', name.trim());
    });
    // decorative icons are skipped by screen readers
    root.querySelectorAll('i[class*="fa-"]:not([aria-hidden]), i[data-lucide]:not([aria-hidden])').forEach((icon) =>
        icon.setAttribute('aria-hidden', 'true')
    );
}
let namingTimer = null;
document.addEventListener('DOMContentLoaded', () => {
    nameUnlabelledControls();
    new MutationObserver(() => {
        clearTimeout(namingTimer);
        namingTimer = setTimeout(nameUnlabelledControls, 300);
    }).observe(document.body, { childList: true, subtree: true });
});

// "Check on another site": links that open those sites on this value (new tab)
function externalSitesHtml(sites, type, value) {
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
                ${host ? `<img src="/api/oi/icon/${encodeURIComponent(host)}" alt="" class="w-3.5 h-3.5 rounded-sm" loading="lazy" onerror="this.remove()">` : ''}${escapeHtml(site.name)}</a>`;
        })
        .join('');
    return `<div class="px-3 py-2 border-t border-gray-700">
        <div class="text-[11px] uppercase tracking-wider text-gray-500 mb-1.5">Check on another site</div>
        <div class="flex flex-wrap gap-1.5">${links}</div></div>`;
}

// Lookups of an identifier already saved in an investigation, newest first ([] if none or unknown)
async function earlierLookups(investigationId, type, value) {
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
const sharedCache = new Map(); // "type:value" -> [{investigation_id, name, ...}] ([] = nowhere else)
const sharedPending = new Set();
let sharedTimer = null;
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// Results on this page belong to this investigation (the page's own, or the one recording)
function sharedExclude() {
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

// Answers the page already has (the Identifiers tab lists them with each identifier)
window.primeSharedIdentifiers = (entries) => {
    entries.forEach(([name, places]) => sharedCache.set(name, places || []));
};

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

// ---------------------------------------------------------------------------
// Image viewer, on every page. Elements with data-image-view open it on click: the
// attribute holds the full image's URL, or stays empty to show the <img> itself.
// Optional: data-image-title, data-image-note.
// ---------------------------------------------------------------------------
function openImageViewer(url, title = 'Image', note = 'Image preview') {
    if (!url) return;
    const modal = document.createElement('div');
    modal.className = 'modal-overlay username-image-preview-overlay';
    const original = safeUrl(url);
    modal.innerHTML = `
    <div class="username-image-preview-card">
        <div class="username-image-preview-header">
            <div class="min-w-0">
                <h2 class="truncate">${escapeHtml(title)}</h2>
                <p>${escapeHtml(note)}</p>
            </div>
            <div class="flex gap-2 shrink-0">
                ${original ? `<a href="${escapeAttr(original)}" target="_blank" rel="noopener noreferrer" title="Open the original in a new tab"><i class="fas fa-external-link-alt"></i></a>` : ''}
                <button type="button" class="close-modal" title="Close preview"><i class="fas fa-times"></i></button>
            </div>
        </div>
        <div class="username-image-preview-body">
            <img alt="" referrerpolicy="no-referrer">
        </div>
    </div>`;
    const image = modal.querySelector('img');
    image.onerror = () => {
        image.parentElement.innerHTML = '<span>Image could not be loaded.</span>';
    };
    image.src = url;

    const close = () => {
        modal.remove();
        document.removeEventListener('keydown', onKey, true);
    };
    // Capture: Esc closes only the viewer, not a window underneath it
    const onKey = (event) => {
        if (event.key !== 'Escape') return;
        event.stopPropagation();
        close();
    };
    document.addEventListener('keydown', onKey, true);
    modal.addEventListener('click', (event) => {
        if (event.target === modal) close();
    });
    modal.querySelector('.close-modal').addEventListener('click', close);
    document.body.appendChild(modal);
}
window.openImageViewer = openImageViewer;

// Capture: opening an image must not also open or toggle the card it sits in.
// Images in notes come from the editor bundle, so they are matched by class.
document.addEventListener(
    'click',
    (event) => {
        const trigger = event.target.closest('[data-image-view], img.cm-md-image');
        if (!trigger) return;
        event.preventDefault();
        event.stopPropagation();
        const url = trigger.dataset.imageView || trigger.currentSrc || trigger.src;
        openImageViewer(url, trigger.dataset.imageTitle || trigger.alt || 'Image', trigger.dataset.imageNote);
    },
    true
);

// ---------------------------------------------------------------------------
// Lookup box dropdown: run a module on what's typed, without leaving the page.
// Enter still opens the full /lookup page.
// ---------------------------------------------------------------------------
let quickLookupTimer = null;
let quickLookupRequest = 0; // answers to anything but the latest request are dropped

function closeQuickLookup() {
    clearTimeout(quickLookupTimer);
    quickLookupRequest += 1;
    document.getElementById('globalLookupMenu')?.classList.add('hidden');
}

function quickLookupRow(candidate, m, canRun) {
    const last = (m.previous || [])[(m.previous || []).length - 1];
    const problems = (m.problems || []).join('; ');
    const openUrl = `${m.page}?q=${encodeURIComponent(candidate.value)}&t=${encodeURIComponent(candidate.type)}`;
    return `
    <div class="px-3 py-2 flex items-center justify-between gap-2 hover:bg-gray-800/70">
        <div class="min-w-0">
            <div class="text-white truncate">${escapeHtml(m.name)}</div>
            <div class="flex items-center gap-1.5 mt-0.5">${moduleBadges(m)}${m.ready ? '' : setupLinkHtml(m)}</div>
            ${last ? `<div class="text-[11px] text-amber-300 mt-0.5"><i class="fas fa-history mr-1"></i>Already looked up ${escapeHtml(timeAgo(last.timestamp))}</div>` : ''}
        </div>
        <div class="flex gap-1.5 shrink-0">
            <button type="button" data-quick-run="${escapeAttr(m.id)}" data-quick-type="${escapeAttr(candidate.type)}" data-quick-value="${escapeAttr(candidate.value)}"
                ${m.ready && canRun ? '' : 'disabled'}
                class="px-2 py-1 rounded bg-purple-700 hover:bg-purple-600 disabled:opacity-40 disabled:cursor-not-allowed text-xs"
                title="${m.ready ? (canRun ? 'Run in the background' : 'Select an investigation first') : escapeAttr(problems)}">Run</button>
            <a href="${escapeAttr(openUrl)}" class="px-2 py-1 rounded bg-gray-800 hover:bg-gray-700 text-xs" title="Open the module with this value">Open</a>
        </div>
    </div>`;
}

// For a module that can't run yet: what to do, as a link to where it is done
// ("Add the SerpAPI Key" -> Settings). The full reason is the tooltip.
function setupLinkHtml(m) {
    const fix = (m.setup || [])[0] || { action: 'Needs setup', href: '/settings' };
    return `<a href="${escapeAttr(fix.href)}" class="text-[10px] text-amber-300 hover:text-amber-200 underline truncate" title="${escapeAttr((m.problems || []).join('; '))}">${escapeHtml(fix.action)}</a>`;
}
window.setupLinkHtml = setupLinkHtml;

// A phone number typed without its country code: the full numbers it could be, to pick from
// (data-lookup-suggest carries the full number; the lookup box and /lookup both use this)
function phoneSuggestionsHtml(suggestions) {
    if (!suggestions || !suggestions.length) return '';
    return `<div class="text-xs text-gray-400 mb-2"><i class="fas fa-phone mr-1.5 text-purple-300"></i>A phone number? Without its country code it could be any of these - pick one:</div>
    <div class="flex flex-wrap gap-1.5">${suggestions
        .map(
            (s) => `<button type="button" data-lookup-suggest="${escapeAttr(s.value)}"
            class="inline-flex items-center gap-2 px-2.5 py-1.5 rounded bg-gray-800 hover:bg-purple-700/50 border border-gray-700 text-xs">
            <span class="font-mono text-purple-200">${escapeHtml(s.display)}</span><span class="text-gray-400">${escapeHtml(s.country)}</span></button>`
        )
        .join('')}</div>`;
}
window.phoneSuggestionsHtml = phoneSuggestionsHtml;

const LOOKUP_EXAMPLES_HINT =
    "Couldn't tell what this is. Try an email, a phone number with its country code (+1 415 555 2671), an @username, a domain or an IP address.";
window.LOOKUP_EXAMPLES_HINT = LOOKUP_EXAMPLES_HINT;

function renderQuickLookup(data) {
    const menu = document.getElementById('globalLookupMenu');
    const canRun = Boolean(data.investigation_id);
    const suggestions = phoneSuggestionsHtml(data.suggestions);
    const sections = data.candidates
        .map(
            (c) => `
    <div class="px-3 pt-2.5 pb-1 text-[11px] uppercase tracking-wider text-gray-500">${escapeHtml(c.label)} · <span class="font-mono normal-case text-purple-200">${escapeHtml(c.display || c.value)}</span></div>
    ${
        c.modules.length
            ? c.modules.map((m) => quickLookupRow(c, m, canRun)).join('')
            : '<div class="px-3 py-2 text-gray-500">No module looks this up yet - "All lookups" lists sites that do.</div>'
    }`
        )
        .join('');
    menu.innerHTML = `
    ${canRun ? '' : '<div class="px-3 py-2 border-b border-gray-700 text-xs text-yellow-200">Select or create an investigation to run lookups. Results are saved there.</div>'}
    <div class="max-h-96 overflow-y-auto custom-scrollbar pb-1">
        ${suggestions ? `<div class="px-3 py-2.5 border-b border-gray-800">${suggestions}</div>` : ''}
        ${sections || (suggestions ? '' : `<div class="px-3 py-3 text-gray-500">${escapeHtml(LOOKUP_EXAMPLES_HINT)}</div>`)}
    </div>
    <div class="px-3 py-2 border-t border-gray-700 text-right text-xs">
        <a href="/lookup?q=${encodeURIComponent(data.query)}" class="text-purple-300 hover:text-white">All lookups for this →</a>
    </div>`;
    menu.classList.remove('hidden');
}

async function updateQuickLookup(query) {
    const request = ++quickLookupRequest;
    try {
        const response = await fetch(`/api/lookup/detect?q=${encodeURIComponent(query)}`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        if (request === quickLookupRequest) renderQuickLookup(data);
    } catch (error) {
        console.error('Lookup detection failed:', error);
    }
}

function setupQuickLookup() {
    const input = document.getElementById('globalLookupInput');
    const menu = document.getElementById('globalLookupMenu');
    if (!input || !menu) return;
    const schedule = () => {
        clearTimeout(quickLookupTimer);
        const query = input.value.trim();
        if (query.length < 2) {
            closeQuickLookup();
            return;
        }
        quickLookupTimer = setTimeout(() => updateQuickLookup(query), 200);
    };
    input.addEventListener('input', schedule);
    input.addEventListener('focus', schedule);
    document.getElementById('globalLookupForm').addEventListener('keydown', (event) => {
        if (event.key === 'Escape') closeQuickLookup();
    });
    document.getElementById('globalLookupForm').addEventListener('submit', closeQuickLookup);
    document.addEventListener('click', (event) => {
        if (!event.target.closest('#globalLookupForm')) closeQuickLookup();
    });
    // Stays open after a run, so several modules can be started in a row
    menu.addEventListener('click', async (event) => {
        const suggestion = event.target.closest('[data-lookup-suggest]');
        if (suggestion) {
            input.value = suggestion.dataset.lookupSuggest;
            input.focus();
            updateQuickLookup(input.value);
            return;
        }
        const run = event.target.closest('[data-quick-run]');
        if (!run) return;
        run.disabled = true;
        const job = await startJob(run.dataset.quickRun, run.dataset.quickType, run.dataset.quickValue);
        if (job) run.textContent = 'Started';
        else run.disabled = false;
    });
}

// Chip for an identifier that opens the pivot menu
function pivotChip(type, value, label = null) {
    return `<button type="button" data-pivot-type="${escapeAttr(type)}" data-pivot-value="${escapeAttr(value)}"
      class="pivot-chip" title="Look up with another module">${escapeHtml(label || value)}<i class="fas fa-chevron-down"></i></button>`;
}
window.pivotChip = pivotChip;

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
};

// The type a value can be offered as, or null (a "username" that is an email is an email)
function pivotTypeFor(type, value) {
    const text = String(value ?? '').trim();
    if (!type || !text) return null;
    if ((type === 'username' || type === 'telegram_username') && text.includes('@') && !text.startsWith('@'))
        type = 'email';
    const shape = PIVOT_SHAPES[type];
    return shape && !shape.test(text) ? null : type;
}
window.pivotTypeFor = pivotTypeFor;

function pivotText(type, value, label = null) {
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
window.pivotText = pivotText;

// A login that is an email or a username
function pivotLogin(value, label = null) {
    return pivotText(String(value ?? '').includes('@') ? 'email' : 'username', value, label);
}
window.pivotLogin = pivotLogin;

// Identifier type a field name implies (same idea as services/entities.py _key_hint)
function pivotKeyType(key) {
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
    return null;
}

// A result field's value: clickable when the field or the value is an identifier
// (emails and +phones are recognised by shape whatever the field is called)
function pivotField(key, value, label = null) {
    if (value === undefined || value === null || typeof value === 'object') return escapeHtml(label ?? value ?? '');
    const text = String(value).trim();
    let type = pivotKeyType(key);
    if (!type && PIVOT_SHAPES.email.test(text)) type = 'email';
    else if (!type && text.startsWith('+') && PIVOT_SHAPES.phone.test(text)) type = 'phone';
    return type ? pivotText(type, text, label) : escapeHtml(label ?? value);
}
window.pivotField = pivotField;

// Free text (a snippet, bio or message): escaped, with the emails and +phone numbers in it clickable
const TEXT_IDENTIFIER_RE = /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}|\+\d[\d\s().-]{7,18}\d/g;
function pivotInText(text) {
    const source = String(text ?? '');
    let out = '';
    let last = 0;
    for (const match of source.matchAll(TEXT_IDENTIFIER_RE)) {
        const found = match[0];
        out += escapeHtml(source.slice(last, match.index));
        out += found.includes('@')
            ? pivotText('email', found)
            : pivotText('phone', found.replace(/[\s().-]/g, ''), found);
        last = match.index + found.length;
    }
    return out + escapeHtml(source.slice(last));
}
window.pivotInText = pivotInText;

// Analytics / ads IDs BuiltWith lists the other websites of (Google Analytics, Tag Manager, AdSense)
const BUILTWITH_TAG_RE = /^(UA-\d{4,10}|G-[A-Z0-9]{8,12}|GTM-[A-Z0-9]{5,8}|pub-\d{14,20})$/;
function builtwithTagUrl(id) {
    const tag = String(id ?? '').trim();
    return BUILTWITH_TAG_RE.test(tag) ? `https://builtwith.com/relationships/tag/${encodeURIComponent(tag)}` : null;
}
window.builtwithTagUrl = builtwithTagUrl;

// A tracking ID in a result, with a link to the other websites that carry it when BuiltWith knows the kind
function trackerTag(id) {
    const url = builtwithTagUrl(id);
    return `<span class="inline-flex items-center gap-1"><code class="text-purple-200">${escapeHtml(id)}</code>${
        url
            ? `<a href="${escapeAttr(url)}" target="_blank" rel="noopener noreferrer" class="text-gray-400 hover:text-white" title="Other websites with this tag (BuiltWith)"><i class="fas fa-external-link-alt text-[10px]"></i></a>`
            : ''
    }</span>`;
}
window.trackerTag = trackerTag;

// A favicon's mmh3 hash (httpx -favicon; the number Shodan and FOFA index). FOFA lists the
// websites serving the same icon - often the same owner's other sites, or the real server
// behind a CDN. Its query, icon_hash="<hash>", goes base64-encoded in the address.
const FAVICON_HASH_RE = /^-?\d{1,11}$/;
function fofaIconHashUrl(hash) {
    const value = String(hash ?? '').trim();
    if (!FAVICON_HASH_RE.test(value)) return null;
    return `https://en.fofa.info/result?qbase64=${encodeURIComponent(btoa(`icon_hash="${value}"`))}`;
}
window.fofaIconHashUrl = fofaIconHashUrl;

// A favicon hash in a result, with a link to the other websites that show the same icon
function faviconHashTag(hash) {
    const url = fofaIconHashUrl(hash);
    return `<span class="inline-flex items-center gap-1"><code class="text-purple-200">mmh3 ${escapeHtml(hash)}</code>${
        url
            ? `<a href="${escapeAttr(url)}" target="_blank" rel="noopener noreferrer" class="text-gray-400 hover:text-white" title="Other websites with this favicon (FOFA)"><i class="fas fa-external-link-alt text-[10px]"></i></a>`
            : ''
    }</span>`;
}
window.faviconHashTag = faviconHashTag;

// Identifiers grouped by type, as pivot chips (investigation results and module pages)
function identifierGroupsHtml(entities, limit = 150) {
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
window.identifierGroupsHtml = identifierGroupsHtml;

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
function nsLookupSuggestion(sets, { compact = false } = {}) {
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
window.nsLookupSuggestion = nsLookupSuggestion;

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
