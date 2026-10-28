// Initialize Lucide icons
lucide.createIcons();

let dashboardInvestigations = [];
let dashboardSelectedInvestigationId = null;
let currentActiveInvestigationId = null;

// Load investigations on page load
document.addEventListener('DOMContentLoaded', async function () {
    await fetchActiveInvestigationId();
    await loadDashboardInvestigations();

    // Setup search and filter
    const searchInput = document.getElementById('dashboardSearchInput');
    const statusFilter = document.getElementById('dashboardStatusFilter');

    if (searchInput) {
        searchInput.addEventListener('input', filterDashboardInvestigations);
    }
    if (statusFilter) {
        statusFilter.addEventListener('change', filterDashboardInvestigations);
    }
});

async function fetchActiveInvestigationId() {
    try {
        const response = await fetch('/api/investigations/current');
        const data = await response.json();
        if (data.status === 'success' && data.investigation_id) {
            currentActiveInvestigationId = data.investigation_id;
            localStorage.setItem('currentInvestigationId', currentActiveInvestigationId);
        } else {
            currentActiveInvestigationId = localStorage.getItem('currentInvestigationId');
        }
    } catch (e) {
        currentActiveInvestigationId = localStorage.getItem('currentInvestigationId');
    }
}

async function loadDashboardInvestigations() {
    try {
        const response = await fetch('/api/investigations/');
        const data = await response.json();

        if (data.status === 'success') {
            dashboardInvestigations = data.investigations;
            updateDashboardStatistics();
            displayDashboardInvestigations(dashboardInvestigations);
        }
    } catch (error) {
        console.error('Error loading investigations:', error);
        showDashboardNotification('Failed to load investigations', 'error');
    } finally {
        const loadingIndicator = document.getElementById('dashboardLoadingIndicator');
        const investigationsGrid = document.getElementById('dashboardInvestigationsGrid');

        if (loadingIndicator) loadingIndicator.classList.add('hidden');
        if (investigationsGrid) investigationsGrid.classList.remove('hidden');
    }
}

function updateDashboardStatistics() {
    const total = dashboardInvestigations.length;
    const active = dashboardInvestigations.filter(inv => inv.status === 'active').length;
    const totalResults = dashboardInvestigations.reduce((sum, inv) => sum + (inv.results_count || 0), 0);

    const totalEl = document.getElementById('dashboardTotalInvestigations');
    const activeEl = document.getElementById('dashboardActiveInvestigations');
    const resultsEl = document.getElementById('dashboardTotalResults');

    if (totalEl) totalEl.textContent = total;
    if (activeEl) activeEl.textContent = active;
    if (resultsEl) resultsEl.textContent = totalResults;
}

function displayDashboardInvestigations(investigations) {
    const listContainer = document.getElementById('dashboardInvestigationsList');
    const emptyState = document.getElementById('dashboardEmptyState');

    if (!listContainer || !emptyState) return;

    if (investigations.length === 0) {
        listContainer.innerHTML = '';
        emptyState.classList.remove('hidden');
        emptyState.classList.add('flex');
        return;
    }

    emptyState.classList.add('hidden');
    emptyState.classList.remove('flex');

    listContainer.innerHTML = investigations.map(inv => {
        const createdDate = new Date(inv.created_at);
        const formattedDate = createdDate.toLocaleDateString('en-US', {
            year: 'numeric',
            month: 'short',
            day: 'numeric'
        });

        const statusColors = {
            'active': 'bg-green-900/50 text-green-200 border-green-700/50',
            'completed': 'bg-blue-900/50 text-blue-200 border-blue-700/50',
            'archived': 'bg-gray-800 text-gray-400 border-gray-700'
        };

        const statusColor = statusColors[inv.status] || statusColors['active'];
        const isCurrent = currentActiveInvestigationId && (inv.investigation_id === currentActiveInvestigationId);

        return `
            <div class="bg-[#14151f] border ${isCurrent ? 'border-emerald-500 shadow-lg shadow-emerald-950/30 ring-1 ring-emerald-500/50' : 'border-[#24283b]'} rounded-xl overflow-hidden hover:border-purple-500/50 transition-all duration-300 cursor-pointer group flex flex-col justify-between relative"
                 onclick="openDashboardInvestigationDetails('${inv.investigation_id}')">
                
                ${isCurrent ? `
                    <div class="absolute top-3 left-3 z-10">
                        <span class="text-xs font-semibold px-2.5 py-1 rounded-full bg-emerald-950/90 border border-emerald-500 text-emerald-300 flex items-center gap-1.5 shadow-md">
                            <span class="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span> Active Case
                        </span>
                    </div>
                ` : ''}

                <!-- Picture Header -->
                <div class="h-36 bg-gradient-to-br from-gray-800/80 to-gray-950 flex items-center justify-center relative overflow-hidden">
                    ${inv.picture_url ?
                        `<img src="${escapeAttr(inv.picture_url)}" alt="" loading="lazy" class="w-full h-full object-cover">` :
                        `<div class="w-14 h-14 rounded-2xl bg-gray-800/80 border border-gray-700 flex items-center justify-center text-gray-500 group-hover:text-purple-400 group-hover:scale-110 transition-all">
                            <i data-lucide="folder-open" class="w-7 h-7"></i>
                         </div>`
                    }
                    <div class="absolute top-3 right-3">
                        <span class="text-xs px-2.5 py-1 rounded-full border ${statusColor} font-medium">
                            ${inv.status}
                        </span>
                    </div>
                </div>

                <!-- Content -->
                <div class="p-5 flex-1 flex flex-col justify-between">
                    <div>
                        <h3 class="text-lg font-bold text-white mb-1.5 group-hover:text-purple-400 transition-colors truncate">
                            ${escapeHtml(inv.name)}
                        </h3>
                        <p class="text-sm text-gray-400 mb-4 line-clamp-2 leading-relaxed">
                            ${escapeHtml(inv.description || 'No description provided.')}
                        </p>
                    </div>

                    <div>
                        <!-- Stats -->
                        <div class="flex items-center justify-between text-xs text-gray-400 mb-4 pt-3 border-t border-gray-800/80">
                            <div class="flex items-center gap-1.5">
                                <i data-lucide="file-text" class="w-3.5 h-3.5 text-purple-400"></i>
                                <span class="font-medium text-gray-300">${inv.results_count || 0}</span> results
                            </div>
                            <div class="flex items-center gap-1.5">
                                <i data-lucide="calendar" class="w-3.5 h-3.5 text-gray-500"></i>
                                <span>${formattedDate}</span>
                            </div>
                        </div>

                        <!-- Action Buttons -->
                        <div class="grid grid-cols-2 gap-2">
                            <a href="/api/investigations/${inv.investigation_id}/view"
                               onclick="event.stopPropagation()"
                               class="bg-purple-600/80 hover:bg-purple-600 text-white py-2 rounded-lg transition-colors text-xs font-semibold flex items-center justify-center gap-1.5">
                                <i data-lucide="eye" class="w-3.5 h-3.5"></i> Results
                            </a>
                            ${!isCurrent ? `
                                <button onclick="event.stopPropagation(); setActiveInvestigationDirectly('${inv.investigation_id}')"
                                    class="bg-gray-800 hover:bg-emerald-600 hover:text-white text-gray-300 py-2 rounded-lg transition-colors text-xs font-medium flex items-center justify-center gap-1.5 border border-gray-700">
                                    <i data-lucide="check-circle" class="w-3.5 h-3.5"></i> Set Active
                                </button>
                            ` : `
                                <button onclick="event.stopPropagation(); openDashboardInvestigationDetails('${inv.investigation_id}')"
                                    class="bg-emerald-950/60 border border-emerald-700 text-emerald-300 py-2 rounded-lg text-xs font-medium flex items-center justify-center gap-1.5">
                                    <i data-lucide="info" class="w-3.5 h-3.5"></i> Details
                                </button>
                            `}
                        </div>
                    </div>
                </div>
            </div>
        `;
    }).join('');

    lucide.createIcons();
}

function filterDashboardInvestigations() {
    const searchInput = document.getElementById('dashboardSearchInput');
    const statusFilter = document.getElementById('dashboardStatusFilter');

    if (!searchInput || !statusFilter) return;

    const searchTerm = searchInput.value.toLowerCase();
    const statusValue = statusFilter.value;

    const filtered = dashboardInvestigations.filter(inv => {
        const matchesSearch = inv.name.toLowerCase().includes(searchTerm) ||
            (inv.description && inv.description.toLowerCase().includes(searchTerm));
        const matchesStatus = statusValue === 'all' || inv.status === statusValue;

        return matchesSearch && matchesStatus;
    });

    displayDashboardInvestigations(filtered);
}

function openDashboardInvestigationDetails(investigationId) {
    const investigation = dashboardInvestigations.find(inv => inv.investigation_id === investigationId);
    if (!investigation) return;

    dashboardSelectedInvestigationId = investigationId;

    // Populate modal
    const nameEl = document.getElementById('dashboardModalInvestigationName');
    const descEl = document.getElementById('dashboardModalInvestigationDescription');
    const resultsCountEl = document.getElementById('dashboardModalResultsCount');

    if (nameEl) nameEl.textContent = investigation.name;
    if (descEl) descEl.textContent = investigation.description || 'No description provided.';
    if (resultsCountEl) resultsCountEl.textContent = investigation.results_count || 0;

    const statusColors = {
        'active': 'bg-green-900/50 text-green-200 border border-green-700',
        'completed': 'bg-blue-900/50 text-blue-200 border border-blue-700',
        'archived': 'bg-gray-700 text-gray-300'
    };
    const statusElement = document.getElementById('dashboardModalInvestigationStatus');
    if (statusElement) {
        statusElement.textContent = investigation.status;
        statusElement.className = `text-xs px-2.5 py-1 rounded-full ${statusColors[investigation.status] || statusColors['active']}`;
    }

    const createdDate = new Date(investigation.created_at);
    const updatedDate = new Date(investigation.updated_at);

    const dateEl = document.getElementById('dashboardModalInvestigationDate');
    const createdEl = document.getElementById('dashboardModalCreatedDate');
    const updatedEl = document.getElementById('dashboardModalUpdatedDate');

    if (dateEl) dateEl.textContent = createdDate.toLocaleDateString();
    if (createdEl) createdEl.textContent = createdDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
    if (updatedEl) updatedEl.textContent = updatedDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });

    // Handle picture
    const pictureContainer = document.getElementById('dashboardModalInvestigationPicture');
    if (pictureContainer) {
        if (investigation.picture_url) {
            pictureContainer.innerHTML = `<img src="${escapeAttr(investigation.picture_url)}" alt="" class="w-full h-full object-cover">`;
        } else {
            pictureContainer.innerHTML = `<i data-lucide="folder-open" class="w-8 h-8 text-purple-400"></i>`;
        }
    }

    // Toggle Set Active button appearance
    const setActiveBtn = document.getElementById('dashboardModalSetActiveBtn');
    if (setActiveBtn) {
        const isCurrent = currentActiveInvestigationId && (investigation.investigation_id === currentActiveInvestigationId);
        if (isCurrent) {
            setActiveBtn.innerHTML = '<i data-lucide="check" class="w-5 h-5"></i> Currently Active';
            setActiveBtn.className = 'flex items-center justify-center gap-2 bg-emerald-950 border border-emerald-600 text-emerald-300 px-4 py-3 rounded-lg cursor-default font-medium';
            setActiveBtn.disabled = true;
        } else {
            setActiveBtn.innerHTML = '<i data-lucide="check-circle" class="w-5 h-5"></i> Set as Active';
            setActiveBtn.className = 'flex items-center justify-center gap-2 bg-emerald-600 hover:bg-emerald-500 text-white px-4 py-3 rounded-lg transition-colors font-medium';
            setActiveBtn.disabled = false;
        }
    }

    // Open modal
    const modal = document.getElementById('dashboardInvestigationDetailsModal');
    if (modal) {
        modal.classList.remove('hidden');
        modal.classList.add('flex');
    }

    lucide.createIcons();
}

function closeDashboardInvestigationDetailsModal() {
    const modal = document.getElementById('dashboardInvestigationDetailsModal');
    if (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
    }
}

async function setActiveInvestigationDirectly(investigationId) {
    const inv = dashboardInvestigations.find(i => i.investigation_id === investigationId);
    // Shared selector in main.js keeps the header, localStorage and server in sync
    const ok = await window.selectInvestigation(investigationId, inv ? inv.name : '');
    if (!ok) return;
    currentActiveInvestigationId = investigationId;
    await loadDashboardInvestigations();
}

async function setDashboardInvestigationAsActive() {
    if (!dashboardSelectedInvestigationId) return;
    await setActiveInvestigationDirectly(dashboardSelectedInvestigationId);
    openDashboardInvestigationDetails(dashboardSelectedInvestigationId);
}

function viewDashboardInvestigationResults() {
    if (dashboardSelectedInvestigationId) {
        window.location.href = `/api/investigations/${dashboardSelectedInvestigationId}/view`;
    }
}

function openEditDashboardInvestigationModal() {
    if (!dashboardSelectedInvestigationId) return;
    const inv = dashboardInvestigations.find(i => i.investigation_id === dashboardSelectedInvestigationId);
    if (!inv) return;

    document.getElementById('editInvName').value = inv.name || '';
    document.getElementById('editInvDescription').value = inv.description || '';
    document.getElementById('editInvStatus').value = inv.status || 'active';

    const editModal = document.getElementById('dashboardEditInvestigationModal');
    if (editModal) {
        editModal.classList.remove('hidden');
        editModal.classList.add('flex');
    }
}

function closeEditDashboardInvestigationModal() {
    const editModal = document.getElementById('dashboardEditInvestigationModal');
    if (editModal) {
        editModal.classList.add('hidden');
        editModal.classList.remove('flex');
    }
}

async function submitEditInvestigation(e) {
    e.preventDefault();
    if (!dashboardSelectedInvestigationId) return;

    const name = document.getElementById('editInvName').value.trim();
    const description = document.getElementById('editInvDescription').value.trim();
    const status = document.getElementById('editInvStatus').value;

    try {
        const response = await fetch(`/api/investigations/${dashboardSelectedInvestigationId}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                name,
                description,
                status
            })
        });

        const data = await response.json();
        if (response.ok && data.status === 'success') {
            showDashboardNotification('Investigation updated successfully!', 'success');
            closeEditDashboardInvestigationModal();
            await loadDashboardInvestigations();
            openDashboardInvestigationDetails(dashboardSelectedInvestigationId);

            if (window.loadInvestigationsDropdown) {
                window.loadInvestigationsDropdown();
            }
        } else {
            throw new Error(data.detail || 'Failed to update investigation');
        }
    } catch (error) {
        console.error('Error updating investigation:', error);
        showDashboardNotification('Failed to update investigation', 'error');
    }
}

async function deleteDashboardInvestigation() {
    if (!dashboardSelectedInvestigationId) return;

    if (!confirm('Are you sure you want to delete this investigation? All saved results and notes will be permanently removed.')) {
        return;
    }

    try {
        const response = await fetch(`/api/investigations/${dashboardSelectedInvestigationId}`, {
            method: 'DELETE'
        });

        if (response.ok) {
            showDashboardNotification('Investigation deleted successfully', 'success');
            if (currentActiveInvestigationId === dashboardSelectedInvestigationId) {
                currentActiveInvestigationId = null;
            }
            closeDashboardInvestigationDetailsModal();
            await loadDashboardInvestigations();

            if (window.loadInvestigationsDropdown) {
                window.loadInvestigationsDropdown();
            }
        } else {
            throw new Error('Failed to delete investigation');
        }
    } catch (error) {
        console.error('Error deleting investigation:', error);
        showDashboardNotification('Failed to delete investigation', 'error');
    }
}

function openCreateInvestigationModal() {
    if (window.openCreateModal) {
        window.openCreateModal();
    } else {
        const modal = document.getElementById('createInvestigationModal');
        if (modal) {
            modal.classList.remove('hidden');
            modal.classList.add('flex');
        }
    }
}

function showDashboardNotification(message, type = 'success') {
    const notification = document.createElement('div');
    const bgColor = type === 'success' ? 'bg-emerald-600' : type === 'error' ? 'bg-red-600' : 'bg-blue-600';
    const icon = type === 'success' ? 'check-circle' : type === 'error' ? 'alert-circle' : 'info';

    notification.className = `fixed bottom-4 right-4 ${bgColor} text-white px-5 py-3 rounded-xl shadow-2xl transform transition-all duration-300 translate-y-full opacity-0 z-50 flex items-center gap-3`;
    notification.innerHTML = `
        <i data-lucide="${icon}" class="w-5 h-5"></i>
        <span class="font-medium text-sm">${escapeHtml(message)}</span>
    `;
    document.body.appendChild(notification);

    lucide.createIcons();

    setTimeout(() => {
        notification.classList.remove('translate-y-full', 'opacity-0');
    }, 100);

    setTimeout(() => {
        notification.classList.add('translate-y-full', 'opacity-0');
        setTimeout(() => {
            notification.remove();
        }, 300);
    }, 3000);
}

// Keep the grid in sync with changes made through the header selector / create modal
document.addEventListener('investigation:created', loadDashboardInvestigations);
document.addEventListener('investigation:changed', (e) => {
    currentActiveInvestigationId = e.detail ? e.detail.investigationId : null;
    loadDashboardInvestigations();
});
