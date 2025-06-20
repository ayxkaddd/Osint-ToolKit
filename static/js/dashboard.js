lucide.createIcons();

let modules = [];

async function loadResources() {
    try {
        const response = await fetch('/api/resources/')
        const resources = await response.json()
        modules = resources.modules;
        const { ext_res } = resources

        const modulesList = document.getElementById('modulesList')
        modulesList.innerHTML = modules.map(module => `
            <div class="bg-gray-900 rounded-xl shadow-sm hover:shadow-md transition-shadow duration-300 overflow-hidden opacity-0 transform translate-y-4 transition-all">
                <div class="relative">
                    ${module.settings ? `
                        <button
                            onclick="openSettings('${module.name}')"
                            type="button"
                            class="absolute top-4 right-4 p-2 text-gray-400 hover:text-white transition-colors z-10">
                            <i class="fas fa-cog"></i>
                        </button>
                    ` : ''}
                    <a href="${module.endpoint}" class="block p-6">
                        <div class="w-12 h-12 bg-gray-800 rounded-lg flex items-center justify-center mb-4">
                            <i class="${module.icon_type} fa-${module.icon} text-${module.icon_color}-500 text-2xl"></i>
                        </div>
                        <h3 class="text-xl font-semibold text-white mb-2">${module.name}</h3>
                        <p class="text-gray-400 mb-4">${module.description}</p>
                        <div class="flex flex-wrap gap-2">
                            ${module.tags.map(tag => `
                                <span class="px-3 py-1 bg-gray-800 text-gray-300 rounded-full text-sm">${tag}</span>
                            `).join('')}
                        </div>
                    </a>
                </div>
            </div>
        `).join('')

        const resourcesList = document.getElementById('resourcesList')
        resourcesList.innerHTML = ext_res.map(resource => `
            <div class="bg-gray-900 rounded-lg p-4 flex items-start gap-4 group hover:bg-gray-800 transition-colors opacity-0 transform translate-y-4 transition-all">
                <div class="flex-shrink-0">
                    <img src="${resource.favicon}" alt="${resource.name} favicon"
                        class="w-8 h-8 rounded"
                        onerror="this.src='data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' viewBox=\'0 0 24 24\' fill=\'none\' stroke=\'%236b7280\' stroke-width=\'2\'%3E%3Cpath d=\'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0z\'/%3E%3Cpath d=\'M9 10h.01\'/%3E%3Cpath d=\'M15 10h.01\'/%3E%3Cpath d=\'M9.5 15a3.5 3.5 0 0 0 5 0\'/%3E%3C/svg%3E'">
                </div>
                <div class="flex-grow">
                    <div class="flex items-center justify-between">
                        <h3 class="font-semibold">${resource.name}</h3>
                        <a href="${resource.url}"
                           target="_blank"
                           class="text-gray-400 hover:text-white transition-colors"
                           title="Open in new tab">
                            <i data-lucide="external-link" class="w-4 h-4"></i>
                        </a>
                    </div>
                    <p class="text-sm text-gray-400 mt-1">${resource.description}</p>
                </div>
            </div>
        `).join('')

        document.getElementById('loadingState').style.display = 'none'
        const contentContainer = document.getElementById('contentContainer')
        contentContainer.style.display = 'block'

        void contentContainer.offsetHeight

        contentContainer.classList.remove('opacity-0')

        const items = [...document.querySelectorAll('#modulesList > div, #resourcesList > div')]
        items.forEach((item, index) => {
            setTimeout(() => {
                item.classList.remove('opacity-0', 'translate-y-4')
            }, 50 * index)
        })

        lucide.createIcons()
    } catch (error) {
        console.error('Error loading resources:', error)
        document.getElementById('loadingState').innerHTML = `
            <div class="text-red-500">
                <i class="fas fa-exclamation-circle text-2xl mb-2"></i>
                <p>Error loading resources. Please try again later.</p>
            </div>
        `
    }
}

let currentModule = null;

function redactSensitiveValue(value) {
    if (!value) return '';
    if (value.length <= 4) return value;
    return value.substring(0, 3) + '*'.repeat(value.length - 4) + value.slice(-1);
}

function openSettings(moduleName) {
    const module = modules.find(m => m.name === moduleName);
    if (!module || !module.settings) {
        console.log('No settings found for module:', moduleName);
        return;
    }

    currentModule = module;
    const content = document.getElementById('settingsContent');
    content.innerHTML = Object.entries(module.settings).map(([key, config]) => {
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
                       data-module="${moduleName}"
                       class="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-white focus:outline-none focus:border-blue-500"
                       value="${displayValue}"
                       placeholder="${config.label}">
            </div>
        `;
    }).join('');

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
                body: JSON.stringify(settings)
            });

            if (!response.ok) {
                throw new Error('Failed to update settings');
            }

            const notification = document.createElement('div');
            notification.className = 'fixed bottom-4 right-4 bg-green-500 text-white px-6 py-3 rounded-lg shadow-lg transform transition-all duration-300 translate-y-full opacity-0';
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
            alert('Failed to save settings. Please try again.');
        }
    } else {
        closeSettings();
    }
}

loadResources();