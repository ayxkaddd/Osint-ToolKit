// Context menus: right-click (or a "⋯" button) on something gives its actions.
import { escapeAttr, escapeHtml } from './dom.js';
import { loadInvestigations } from './investigations.js';

// ---------------------------------------------------------------------------
// Context menu: right-click (or a "⋯" button) on something gives its actions.
// openContextMenu(eventOrElement, [{label, icon, href, newTab, onClick, danger, checked} | {divider: true}], title, owner)
// owner: what the menu belongs to (a row, a card); a second click on it closes the menu
// instead of opening it again. A button passed as eventOrElement is its own owner.
// ---------------------------------------------------------------------------
let contextMenuOwner = null;

let contextMenuDismissed = { owner: null, at: 0 }; // what a press outside just closed the menu of

export function closeContextMenu() {
    document.getElementById('contextMenu')?.remove();
    contextMenuOwner = null;
}

export function openContextMenu(at, items, title = '', owner = null) {
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
        const owner = contextMenuOwner;
        closeContextMenu();
        owner?.focus?.({ preventScroll: true }); // keyboard users land back on the button that opened it
    },
    true
);

window.addEventListener('scroll', closeContextMenu, { passive: true });

window.addEventListener('resize', closeContextMenu);

window.addEventListener('blur', closeContextMenu);

export function closeInvestigationsDropdown() {
    const dropdown = document.getElementById('investigationsDropdownMenu');
    const icon = document.getElementById('dropdownIcon');
    if (dropdown) dropdown.classList.add('hidden');
    if (icon) icon.style.transform = 'rotate(0deg)';
}

export function toggleInvestigationsDropdown() {
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
