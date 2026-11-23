// HTML escaping, data-click actions, page data, dates, clipboard, notifications and the confirm window.

// ---------------------------------------------------------------------------
// HTML-escaping helpers. Use these before interpolating any externally-sourced
// value (OSINT results, user input, API data) into innerHTML / template
// literals to prevent stored/reflected XSS in the analyst's session.
// ---------------------------------------------------------------------------
export function escapeHtml(value) {
    if (value === null || value === undefined) return '';
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

// Escape for use inside a double-quoted HTML attribute.
export function escapeAttr(value) {
    return escapeHtml(value);
}

// Return url only if it uses a safe scheme (http/https/mailto/tel); else "".
// Prevents javascript:/data: URLs from external data landing in href.
export function safeUrl(url) {
    if (!url) return '';
    const s = String(url).trim();
    if (/^(https?:|mailto:|tel:)/i.test(s)) return s;
    if (/^\//.test(s)) return s; // site-relative
    if (/^[a-z][a-z0-9+.-]*:/i.test(s)) return ''; // some other scheme -> reject
    return 'https://' + s; // bare domain
}

// ---------------------------------------------------------------------------
// Event handlers in markup. The Content-Security-Policy (main.py) blocks inline
// on…="" handlers, so markup names a registered action instead:
//   data-click="name"      on click: name.call(element, ...args)
//   data-args="..."        the arguments as a JSON array: data-args="${clickArgs(a, b)}"
//   data-backdrop          only clicks on the element itself, not inside it (modal backdrops)
//   data-submit="name"     on form submit: name.call(form, event)
//   data-img-error="name"  when an image fails to load: name.call(img, img)
// Page scripts and plugin renderers add theirs with registerActions({ name: fn }).
// The innermost element with data-click handles a click, so a button inside a
// clickable card doesn't also open the card.
// ---------------------------------------------------------------------------
const ACTIONS = Object.create(null);

export function registerActions(actions) {
    Object.assign(ACTIONS, actions);
}

export function clickArgs(...values) {
    return escapeAttr(JSON.stringify(values));
}

function runAction(name, element, args) {
    const action = ACTIONS[name];
    if (typeof action !== 'function') {
        console.error(`No action named "${name}" (registerActions)`);
        return;
    }
    return action.apply(element, args);
}

registerActions({
    // clickable area that does nothing itself, so the card around it isn't opened
    none() {},
    removeParent() {
        this.parentElement.remove();
    },
    removeClosest(selector) {
        this.closest(selector)?.remove();
    },
    hideImage(img) {
        img.style.display = 'none';
    },
    removeImage(img) {
        img.remove();
    },
    // site icons: the next address to try (data-next), then the letters placed after the image
    siteIconFailed(img) {
        if (img.dataset.next) {
            img.src = img.dataset.next;
            img.removeAttribute('data-next');
            return;
        }
        img.style.display = 'none';
        if (img.nextElementSibling) img.nextElementSibling.style.display = 'flex';
    },
});

document.addEventListener('click', (event) => {
    const element = event.target.closest?.('[data-click]');
    if (!element || (element.hasAttribute('data-backdrop') && event.target !== element)) return;
    let args = [];
    try {
        args = element.dataset.args ? JSON.parse(element.dataset.args) : [];
    } catch (e) {
        console.error('Bad data-args', element.dataset.args);
    }
    runAction(element.dataset.click, element, args);
});

document.addEventListener('submit', (event) => {
    const form = event.target.closest?.('[data-submit]');
    if (form) runAction(form.dataset.submit, form, [event]);
});

// Image errors don't bubble, so this listens in the capture phase. Once per address: a
// fallback may set another src, which can fail again.
function handleImageError(img) {
    const src = img.getAttribute('src') || '';
    if (img.dataset.imgErrorFor === src) return;
    img.dataset.imgErrorFor = src;
    runAction(img.dataset.imgError, img, [img]);
}

document.addEventListener(
    'error',
    (event) => {
        if (event.target instanceof HTMLImageElement && event.target.dataset.imgError) handleImageError(event.target);
    },
    true
);

// ...and images in the page itself may have failed before this script ran
document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('img[data-img-error]').forEach((img) => {
        if (img.complete && img.naturalWidth === 0 && img.getAttribute('src')) handleImageError(img);
    });
});

// Data a template hands to its script, as <script type="application/json" id="...">:
// it isn't run, so the Content-Security-Policy allows it
export function pageData(id) {
    const element = document.getElementById(id);
    return element ? JSON.parse(element.textContent) : null;
}

// Pictures already on screen are carried over when a part of the page is rebuilt: an
// <img> in `fresh` with the same src as one in `old` is swapped for the old element,
// which keeps its loaded (or loading) image instead of blinking while it loads again.
export function keepLoadedImages(old, fresh) {
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

// container.innerHTML = html, without reloading the pictures it already shows
export function replaceKeepingImages(container, html) {
    const template = document.createElement('template');
    template.innerHTML = html;
    keepLoadedImages(container, template.content);
    container.replaceChildren(template.content);
}

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

export function refreshIcons() {
    if (window.lucide) window.lucide.createIcons();
}

// Dates look the same everywhere: "Nov 11, 2026, 11:47 AM" in the reader's own locale
// (month by name, so 11/12 can't be read two ways). `seconds` for message times.
export function fmtDateTime(value, seconds = false) {
    const date = value instanceof Date ? value : new Date(value);
    if (value === null || value === undefined || value === '' || isNaN(date)) return '';
    return date.toLocaleString([], { dateStyle: 'medium', timeStyle: seconds ? 'medium' : 'short' });
}

export function fmtDate(value) {
    const date = value instanceof Date ? value : new Date(value);
    if (value === null || value === undefined || value === '' || isNaN(date)) return '';
    return date.toLocaleDateString([], { dateStyle: 'medium' });
}

export function timeAgo(date) {
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

// ---------------------------------------------------------------------------
// Clipboard: renderers add data-copy="<escaped value>" to a clickable element
// instead of inlining the value into an onclick JS string.
// ---------------------------------------------------------------------------
export async function copyTextToClipboard(text) {
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
export function showTemporaryNotification(message, type = 'success') {
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

// ---------------------------------------------------------------------------
// Confirmation window in the app's style, instead of the browser's confirm().
//   if (!(await appConfirm('Delete this result?', { danger: true, confirmLabel: 'Delete' }))) return;
// options: title, confirmLabel, cancelLabel, danger (red button; Cancel has the focus, so
// Enter can't delete by accident). Resolves true/false; Escape or a click outside is Cancel.
// ---------------------------------------------------------------------------
export function appConfirm(message, options = {}) {
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
