lucide.createIcons();

let modules = [];

// Neutral icon when a favicon can't load (offline, blocked); onerror cleared so it can't loop
const FALLBACK_FAVICON =
    'data:image/svg+xml,' +
    encodeURIComponent(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#6b7280" stroke-width="2">' +
            '<path d="M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0z"/><path d="M9 10h.01"/><path d="M15 10h.01"/><path d="M9.5 15a3.5 3.5 0 0 0 5 0"/></svg>'
    );
function faviconFallback(img) {
    img.onerror = null;
    img.src = FALLBACK_FAVICON;
}

// The cards are drawn from the last answer right away, then corrected if the server's differs.
// It only holds names, icons and setting labels, never setting values.
const RESOURCES_CACHE_KEY = 'dashboard_resources';

function readResourcesCache() {
    try {
        return localStorage.getItem(RESOURCES_CACHE_KEY);
    } catch {
        return null;
    }
}

function writeResourcesCache(text) {
    try {
        localStorage.setItem(RESOURCES_CACHE_KEY, text);
    } catch {
        // Storage blocked or full: the page just loads from the server next time
    }
}

// Favicons come through the toolkit's own icon cache, so they only leave the network once
function resourceIcon(resource) {
    try {
        return `/api/oi/icon/${encodeURIComponent(new URL(resource.url).hostname)}`;
    } catch {
        return safeUrl(resource.favicon);
    }
}

// External resources, grouped by what they're for
const RESOURCE_CATEGORIES = [
    ['breaches', 'Breaches and leaks'],
    ['accounts', 'Accounts and usernames'],
    ['domains', 'Domains, DNS and websites'],
    ['infrastructure', 'IPs and infrastructure'],
    ['images', 'Images and faces'],
    ['telegram', 'Telegram'],
    ['companies', 'Companies, people and vehicles'],
    ['crypto', 'Crypto'],
    ['archives', 'Archives'],
    ['other', 'Other'],
];
const RESOURCE_COST = {
    free: ['free', 'bg-emerald-900/50 text-emerald-300'],
    freemium: ['free tier', 'bg-sky-900/50 text-sky-300'],
    paid: ['paid', 'bg-yellow-900/60 text-yellow-300'],
};
let externalResources = [];
const resourceFilter = { category: '', q: '' };

function resourceMatches(resource) {
    if (resourceFilter.category && (resource.category || 'other') !== resourceFilter.category) return false;
    const q = resourceFilter.q.toLowerCase();
    if (!q) return true;
    const types = (resource.types || []).map((t) => window.ENTITY_LABELS[t] || t);
    return [resource.name, resource.description, resource.url, ...types].join(' ').toLowerCase().includes(q);
}

function resourceCard(resource) {
    const cost = RESOURCE_COST[resource.cost];
    const opens = Object.keys(resource.search || {});
    return `
        <a href="${escapeAttr(safeUrl(resource.url))}" target="_blank" rel="noopener noreferrer"
           class="bg-[#14151f] border border-[#24283b] hover:border-gray-600 rounded-xl p-4 flex items-start gap-4 group transition-colors">
            <img src="${escapeAttr(resourceIcon(resource))}" alt="" loading="lazy" class="w-8 h-8 rounded shrink-0" onerror="faviconFallback(this)">
            <div class="min-w-0 flex-grow">
                <div class="flex items-center gap-2">
                    <h3 class="font-semibold text-white truncate">${escapeHtml(resource.name)}</h3>
                    ${cost ? `<span class="text-[10px] px-1.5 py-0.5 rounded ${cost[1]}">${cost[0]}</span>` : ''}
                    <i data-lucide="external-link" class="w-4 h-4 text-gray-500 group-hover:text-white ml-auto shrink-0"></i>
                </div>
                <p class="text-sm text-gray-400 mt-1">${escapeHtml(resource.description)}</p>
                ${
                    (resource.types || []).length
                        ? `<div class="flex flex-wrap gap-1 mt-2">${resource.types
                              .map(
                                  (t) =>
                                      `<span class="text-[10px] px-1.5 py-0.5 rounded border ${opens.includes(t) ? 'border-purple-700/60 text-purple-300' : 'border-gray-700 text-gray-400'}"
                                  title="${opens.includes(t) ? 'Offered in the menu of this kind of identifier' : ''}">${escapeHtml(window.ENTITY_LABELS[t] || t)}</span>`
                              )
                              .join('')}</div>`
                        : ''
                }
            </div>
        </a>`;
}

function renderExternalResources() {
    const counts = {};
    externalResources.forEach((r) => (counts[r.category || 'other'] = (counts[r.category || 'other'] || 0) + 1));
    document.getElementById('resourcesFacets').innerHTML = [
        `<button type="button" data-resource-category="" class="facet ${resourceFilter.category ? '' : 'active'}">All <span>${externalResources.length}</span></button>`,
        ...RESOURCE_CATEGORIES.filter(([id]) => counts[id]).map(
            ([id, label]) =>
                `<button type="button" data-resource-category="${id}" class="facet ${resourceFilter.category === id ? 'active' : ''}">${escapeHtml(label)} <span>${counts[id]}</span></button>`
        ),
    ].join('');

    const shown = externalResources.filter(resourceMatches);
    document.getElementById('resourcesCount').textContent =
        shown.length === externalResources.length
            ? `(${shown.length})`
            : `(${shown.length} of ${externalResources.length})`;
    const sections = RESOURCE_CATEGORIES.map(([id, label]) => {
        const items = shown.filter((r) => (r.category || 'other') === id);
        if (!items.length) return '';
        return `
            <section>
                <h3 class="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-2">${escapeHtml(label)}</h3>
                <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">${items.map(resourceCard).join('')}</div>
            </section>`;
    }).join('');
    document.getElementById('resourcesList').innerHTML =
        sections || '<p class="text-sm text-gray-500">Nothing matches the filter.</p>';
    lucide.createIcons();
}

document.getElementById('resourcesFacets')?.addEventListener('click', (event) => {
    const facet = event.target.closest('[data-resource-category]');
    if (!facet) return;
    resourceFilter.category = facet.dataset.resourceCategory;
    renderExternalResources();
});
document.getElementById('resourcesSearch')?.addEventListener('input', (event) => {
    resourceFilter.q = event.target.value.trim();
    renderExternalResources();
});

function renderResources(resources) {
    modules = resources.modules;
    const { ext_res } = resources;

    const modulesList = document.getElementById('modulesList');
    modulesList.innerHTML =
        modules
            .map(
                (module) => `
                <div class="bg-[#14151f] border border-[#24283b] hover:border-purple-700/60 rounded-xl overflow-hidden flex flex-col transition-colors">
                    <div class="relative">
                        ${
                            module.settings
                                ? `
                            <button
                                onclick="openSettings(${jsArg(module.name)})"
                                type="button"
                                title="${escapeAttr(module.name)} settings"
                                aria-label="${escapeAttr(module.name)} settings"
                                class="absolute top-4 right-4 p-2 text-gray-400 hover:text-white transition-colors z-10">
                                <i class="fas fa-cog"></i>
                            </button>
                        `
                                : ''
                        }
                        <a href="${escapeAttr(module.endpoint)}" class="block p-6">
                            <div class="w-12 h-12 bg-gray-800 rounded-lg flex items-center justify-center mb-4">
                                <i class="${module.icon_type} fa-${module.icon} text-${module.icon_color}-500 text-2xl"></i>
                            </div>
                            <h3 class="text-xl font-semibold text-white mb-2">${escapeHtml(module.name)}</h3>
                            <p class="text-gray-400 mb-4">${escapeHtml(module.description)}</p>
                            <div class="flex flex-wrap gap-2">
                                ${module.tags
                                    .map(
                                        (tag) => `
                                    <span class="px-3 py-1 bg-gray-800 text-gray-300 rounded-full text-sm">${tag}</span>
                                `
                                    )
                                    .join('')}
                            </div>
                        </a>
                    </div>
                </div>
            `
            )
            .join('') +
        `
                <a href="/plugins/builder" class="bg-[#14151f] border border-dashed border-[#24283b] hover:border-purple-700/60 rounded-xl p-6 flex flex-col items-center justify-center text-center gap-3 transition-colors">
                    <div class="w-12 h-12 bg-gray-800 rounded-lg flex items-center justify-center"><i class="fas fa-plus text-purple-400 text-2xl"></i></div>
                    <h3 class="text-xl font-semibold text-white">Build a plugin</h3>
                    <p class="text-gray-400">Connect another website or service and search it from here - no coding needed.</p>
                </a>`;

    externalResources = ext_res || [];
    renderExternalResources();

    document.getElementById('loadingState').style.display = 'none';
    document.getElementById('contentContainer').style.display = 'block';
    lucide.createIcons();
}

async function loadResources() {
    let shown = readResourcesCache();
    if (shown) {
        try {
            renderResources(JSON.parse(shown));
        } catch {
            shown = null;
        }
    }
    loadActiveInvestigation();

    try {
        const response = await fetch('/api/resources/');
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const text = await response.text();
        if (text !== shown) {
            renderResources(JSON.parse(text));
            writeResourcesCache(text);
            shown = text;
        }
    } catch (error) {
        console.error('Error loading resources:', error);
        if (!shown) {
            document.getElementById('loadingState').innerHTML = `
                <div class="text-red-500">
                    <i class="fas fa-exclamation-circle text-2xl mb-2"></i>
                    <p>Error loading resources. Please try again later.</p>
                </div>
            `;
            return;
        }
    }
    annotateReadiness();
}

async function loadActiveInvestigation() {
    const banner = document.getElementById('activeInvestigationBanner');
    if (!banner) return;

    try {
        const response = await fetch('/api/investigations/current');
        const data = await response.json();
        const inv = data.investigation;

        if (inv) {
            const dateStr = new Date(inv.created_at || Date.now()).toLocaleDateString('en-US', {
                month: 'short',
                day: 'numeric',
                year: 'numeric',
            });

            banner.innerHTML = `
                <div class="bg-gradient-to-r from-purple-950/40 via-gray-900 to-indigo-950/40 border border-purple-800/40 rounded-2xl p-6 shadow-xl relative overflow-hidden">
                    <div class="absolute -right-10 -bottom-10 w-48 h-48 bg-purple-600/10 rounded-full blur-3xl pointer-events-none"></div>
                    <div class="flex flex-col md:flex-row items-start md:items-center justify-between gap-6 relative z-10">
                        <div class="flex items-center gap-5">
                            <div class="w-16 h-16 rounded-2xl bg-purple-900/40 border border-purple-700/50 flex items-center justify-center text-purple-300 text-2xl overflow-hidden shrink-0 shadow-inner">
                                ${inv.picture_url ? `<img src="${escapeAttr(inv.picture_url)}" alt="" class="w-full h-full object-cover">` : `<i class="fas fa-shield-alt"></i>`}
                            </div>
                            <div>
                                <div class="flex items-center gap-3 mb-1.5 flex-wrap">
                                    <span class="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-950 border border-emerald-700 text-emerald-300 flex items-center gap-1.5">
                                        <span class="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span> Active Investigation
                                    </span>
                                    <span class="text-xs text-gray-400">Created ${dateStr}</span>
                                </div>
                                <h2 class="text-2xl font-bold text-white tracking-tight">${escapeHtml(inv.name || 'Untitled Case')}</h2>
                                <p class="text-gray-400 text-sm mt-0.5 line-clamp-1 max-w-xl">${escapeHtml(inv.description || 'Module lookups are automatically recorded into this investigation.')}</p>
                            </div>
                        </div>

                        <div class="flex flex-wrap items-center gap-3 shrink-0 w-full md:w-auto">
                            <a href="/api/investigations/${inv.investigation_id}/view" 
                               class="flex-1 md:flex-initial px-4 py-2.5 bg-purple-600 hover:bg-purple-500 text-white font-medium rounded-xl transition-all duration-200 flex items-center justify-center gap-2 text-sm shadow-lg shadow-purple-950/50 hover:shadow-purple-900/50 hover:-translate-y-0.5">
                                <i class="fas fa-chart-line"></i> View Results (${inv.results_count || 0})
                            </a>
                            <a href="/investigations" 
                               class="flex-1 md:flex-initial px-4 py-2.5 bg-gray-800/80 hover:bg-gray-700 border border-gray-700 text-gray-300 rounded-xl transition-colors flex items-center justify-center gap-2 text-sm">
                                <i class="fas fa-folder-open"></i> Switch Case
                            </a>
                        </div>
                    </div>
                </div>
            `;
        } else {
            banner.innerHTML = `
                <div class="card flex flex-col md:flex-row items-center justify-between gap-6">
                    <div class="flex items-center gap-4 text-center md:text-left">
                        <div class="w-12 h-12 rounded-xl bg-gray-800 border border-gray-700 flex items-center justify-center text-gray-400 text-xl shrink-0">
                            <i class="fas fa-folder-plus"></i>
                        </div>
                        <div>
                            <h3 class="text-lg font-bold text-white">No Active Investigation Selected</h3>
                            <p class="text-gray-400 text-sm mt-0.5">Select an existing investigation or create a new case to start saving all OSINT module results automatically.</p>
                        </div>
                    </div>
                    <div class="flex items-center gap-3 w-full md:w-auto justify-end">
                        <button onclick="if(window.openCreateModal) window.openCreateModal(); else window.location.href='/investigations';" 
                                class="flex-1 md:flex-initial px-4 py-2.5 bg-blue-600 hover:bg-blue-500 text-white font-medium rounded-xl transition-colors flex items-center justify-center gap-2 text-sm">
                            <i class="fas fa-plus"></i> Create Investigation
                        </button>
                        <a href="/investigations" 
                           class="flex-1 md:flex-initial px-4 py-2.5 bg-gray-800 hover:bg-gray-700 border border-gray-700 text-gray-300 rounded-xl transition-colors flex items-center justify-center gap-2 text-sm">
                            <i class="fas fa-folder-open"></i> Browse Cases
                        </a>
                    </div>
                </div>
            `;
        }
    } catch (e) {
        console.error('Error loading active investigation banner:', e);
    }
}

let currentModule = null;

function redactSensitiveValue(value) {
    if (!value) return '';
    if (value.length <= 4) return value;
    return value.substring(0, 3) + '*'.repeat(value.length - 4) + value.slice(-1);
}

function openSettings(moduleName) {
    const module = modules.find((m) => m.name === moduleName);
    if (!module || !module.settings) {
        return;
    }

    currentModule = module;
    const content = document.getElementById('settingsContent');
    content.innerHTML = Object.entries(module.settings)
        .map(([key, config]) => {
            const savedValue = localStorage.getItem(`${moduleName}_${key}`);
            let displayValue = '';

            if (config.type === 'password' || key.toLowerCase().includes('api_key')) {
                displayValue = savedValue ? '•'.repeat(8) : '';
            } else {
                displayValue = savedValue || '';
            }

            return `
                <div>
                    <label class="block text-sm font-medium text-gray-400 mb-2">${config.label}</label>
                    <input type="${config.type}"
                           name="${key}"
                           autocomplete="${config.type === 'password' ? 'new-password' : 'off'}"
                           data-lpignore="true" data-1p-ignore data-bwignore data-form-type="other"
                           data-module="${moduleName}"
                           class="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-white focus:outline-none focus:border-blue-500"
                           value="${displayValue}"
                           placeholder="${config.label}">
                </div>
            `;
        })
        .join('');

    document.getElementById('settingsTitle').textContent = `${moduleName} Settings`;
    const modal = document.getElementById('settingsModal');
    const modalContent = modal.querySelector('div');

    modal.classList.remove('hidden');
    modal.classList.add('flex');

    setTimeout(() => {
        modal.classList.remove('opacity-0');
        modalContent.classList.remove('scale-95', 'opacity-0');
    }, 10);
}

function closeSettings() {
    const modal = document.getElementById('settingsModal');
    const modalContent = modal.querySelector('div');

    modal.classList.add('opacity-0');
    modalContent.classList.add('scale-95', 'opacity-0');

    setTimeout(() => {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
    }, 300);
}

async function saveSettings() {
    if (!currentModule || !currentModule.settings) return;

    const settings = {};
    let hasChanges = false;

    Object.entries(currentModule.settings).forEach(([key, config]) => {
        const input = document.querySelector(`input[name="${key}"][data-module="${currentModule.name}"]`);
        const value = input.value;

        if (config.type === 'password' && value === '•'.repeat(8)) {
            return;
        }

        hasChanges = true;

        if (config.type === 'password' || key.toLowerCase().includes('api_key')) {
            localStorage.setItem(`${currentModule.name}_${key}`, redactSensitiveValue(value));
        } else {
            localStorage.setItem(`${currentModule.name}_${key}`, value);
        }

        settings[key.toUpperCase()] = value;
    });

    if (hasChanges) {
        try {
            const response = await fetch('/api/settings/update', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(settings),
            });

            if (!response.ok) {
                throw new Error('Failed to update settings');
            }

            const notification = document.createElement('div');
            notification.className =
                'fixed bottom-4 right-4 bg-green-500 text-white px-6 py-3 rounded-lg shadow-lg transform transition-all duration-300 translate-y-full opacity-0';
            notification.innerHTML = `
                    <div class="flex items-center space-x-2">
                        <i class="fas fa-check-circle"></i>
                        <span>Settings saved successfully!</span>
                    </div>
                `;
            document.body.appendChild(notification);

            setTimeout(() => {
                notification.classList.remove('translate-y-full', 'opacity-0');
            }, 100);

            setTimeout(() => {
                notification.classList.add('translate-y-full', 'opacity-0');
                setTimeout(() => {
                    notification.remove();
                }, 300);
            }, 3000);

            closeSettings();
        } catch (error) {
            console.error('Error saving settings:', error);
            showTemporaryNotification('Failed to save settings. Please try again.', 'error');
        }
    } else {
        closeSettings();
    }
}

loadResources();

// Refresh the active-investigation banner when the header selector changes it
document.addEventListener('investigation:changed', loadActiveInvestigation);
document.addEventListener('investigation:created', loadActiveInvestigation);

// Readiness badge on each module card (missing keys, tools, Telegram login)
// Ready is the normal state and gets no marker. A module that can't run says
// what is missing, in words, with a link to fix it.
// The first thing to do for a module that can't run yet: {text, href}. The server says it
// in words (module_registry: "Add the OSINT Industries API Key").
function setupProblem(module) {
    const fix = (module.setup || [])[0];
    if (fix) return { text: fix.action, href: fix.href };
    return { text: module.problems[0] || 'Needs setup', href: '/settings' };
}

async function annotateReadiness() {
    const modules = await getModules();
    document.querySelectorAll('#modulesList a[href]').forEach((link) => {
        const related = modules.filter((m) => m.page === link.getAttribute('href'));
        const blocked = related.filter((m) => !m.ready);
        if (!blocked.length) return;
        const partial = blocked.length < related.length;
        const first = setupProblem(blocked[0]);
        const line = document.createElement('a');
        line.href = first.href;
        line.className =
            'flex items-center gap-2 px-6 py-2.5 border-t border-gray-800 text-xs text-amber-300/80 hover:text-amber-200 hover:bg-gray-800/50 transition-colors';
        line.title = blocked.map((m) => `${m.name}: ${m.problems.join('; ')}`).join('\n');
        line.innerHTML = `<i class="fas fa-wrench text-[10px]"></i><span class="truncate">${partial ? `${escapeHtml(blocked.map((m) => m.name).join(', '))}: ` : ''}${escapeHtml(first.text)}</span><span class="ml-auto shrink-0 text-gray-500">Set up →</span>`;
        link.parentElement.appendChild(line);
        if (!partial) {
            link.querySelector('i')?.classList.add('opacity-50');
            link.closest('#modulesList > div')?.setAttribute('data-needs-setup', '');
        }
    });
    sortModulesByReadiness();
}

// Modules that work now come first; the ones that still need a key, a tool or a login
// follow under their own heading, so a new install doesn't open on a wall of "set up".
function sortModulesByReadiness() {
    const list = document.getElementById('modulesList');
    const blocked = [...list.querySelectorAll(':scope > [data-needs-setup]')];
    list.querySelector('[data-setup-heading]')?.remove();
    if (!blocked.length || blocked.length === list.querySelectorAll(':scope > div[class*="bg-"]').length) return;
    const heading = document.createElement('h3');
    heading.dataset.setupHeading = '';
    heading.className = 'col-span-full mt-4 text-sm font-semibold text-gray-400 flex items-center gap-2';
    heading.innerHTML = `<i class="fas fa-wrench text-xs" aria-hidden="true"></i>Needs setup <span class="font-normal text-gray-500">${blocked.length}</span>`;
    list.append(heading, ...blocked);
}
