// The current investigation: the header dropdown, its menu, creating and switching cases.
import { closeInvestigationsDropdown, openContextMenu, toggleInvestigationsDropdown } from './context_menu.js';
import { appConfirm, escapeAttr, escapeHtml, fmtDate, registerActions, showTemporaryNotification } from './dom.js';
import { closeUpdateModal } from './header.js';
import { checkExistingResults, removeHistoryUi } from './history.js';

// ---------------------------------------------------------------------------
// Active investigation. The server's "current investigation" decides where
// module results are saved, so it is the source of truth; localStorage only
// mirrors it for scripts that read it synchronously.
// ---------------------------------------------------------------------------
export let currentInvestigationId = localStorage.getItem('currentInvestigationId') || null;

let investigations = [];

function setCurrentInvestigationLocal(id) {
    currentInvestigationId = id || null;
    if (currentInvestigationId) localStorage.setItem('currentInvestigationId', currentInvestigationId);
    else {
        localStorage.removeItem('currentInvestigationId');
        localStorage.removeItem('currentInvestigationName');
    }
}

export async function syncCurrentInvestigation() {
    try {
        const response = await fetch('/api/investigations/current');
        if (!response.ok) return;
        const data = await response.json();
        setCurrentInvestigationLocal(data.investigation_id);
    } catch (e) {
        console.error('Could not read current investigation:', e);
    }
}

export async function loadInvestigations() {
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
export async function offerToStopRecording(investigationId, status, name = '') {
    if (status === 'active' || investigationId !== currentInvestigationId) return;
    const label = name ? `"${name}"` : 'This investigation';
    const stop = await appConfirm(
        `${label} is ${status}, but lookups are still being recorded into it. Stop recording into it?`,
        { title: 'Stop recording?', confirmLabel: 'Stop recording', cancelLabel: 'Keep recording' }
    );
    if (stop) await clearCurrentInvestigation();
}

// What can be done with an investigation from anywhere (header menu, investigations page)
export function investigationMenuItems(inv) {
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

// Close dropdown when clicking outside
document.addEventListener('click', (event) => {
    const dropdown = document.getElementById('investigationsDropdownMenu');
    const button = document.getElementById('investigationsDropdown');
    if (dropdown && button && !dropdown.contains(event.target) && !button.contains(event.target)) {
        closeInvestigationsDropdown();
    }
});

export async function selectInvestigation(investigationId, investigationName) {
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

export async function clearCurrentInvestigation() {
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
export function openCreateInvestigationModal() {
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

export async function logout(everywhere = false) {
    try {
        await fetch(everywhere ? '/logout?everywhere=true' : '/logout', { method: 'POST' });
    } finally {
        window.location.href = '/';
    }
}

registerActions({
    toggleInvestigationsDropdown,
    openCreateInvestigationModal,
    closeCreateInvestigationModal,
    closeUpdateModal,
});
