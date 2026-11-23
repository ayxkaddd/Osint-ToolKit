// The header: update check, the Modules and More menus, names for screen readers.
import { openContextMenu } from './context_menu.js';
import { escapeAttr, escapeHtml, safeUrl, showTemporaryNotification } from './dom.js';
import { getModules } from './history.js';
import { logout } from './investigations.js';
import { getResources } from './pivots.js';

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

export function closeUpdateModal() {
    const modal = document.getElementById('updateModal');
    modal.classList.remove('modal-open');
    setTimeout(() => {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
    }, 150);
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

// "More" menu (header): the things not needed all the time
document.addEventListener('click', (event) => {
    const button = event.target.closest('#moreMenuButton');
    if (!button) return;
    openContextMenu(button, [
        { label: 'Plugins', icon: 'fa-puzzle-piece', href: '/plugins' },
        { label: 'Settings & API keys', icon: 'fa-cog', href: '/settings' },
        { label: 'Check for updates', icon: 'fa-sync-alt', onClick: checkForUpdates },
        { divider: true },
        { label: 'Log out', icon: 'fa-sign-out-alt', onClick: () => logout(), danger: true },
        { label: 'Log out everywhere', icon: 'fa-user-slash', onClick: () => logout(true), danger: true },
    ]);
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
