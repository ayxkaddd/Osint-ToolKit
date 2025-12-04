// Step 2: Features Selection HTML
function getStep2HTML() {
    return `
    <div id="step-2" class="setup-step">
        <h2 class="text-2xl font-bold mb-2">Select Features</h2>
        <p class="text-gray-400 mb-6">Choose which OSINT modules to enable</p>

        <div class="bg-gray-800/50 border border-gray-700 rounded-lg p-4 mb-6">
            <div class="flex items-center justify-between mb-3">
                <h3 class="text-white font-semibold">System Status</h3>
                <button onclick="refreshSystemStatus()" class="text-gray-400 hover:text-white transition-colors">
                    <i data-lucide="refresh-cw" class="w-4 h-4"></i>
                </button>
            </div>
            <div class="grid grid-cols-2 gap-3 text-sm">
                <div class="flex justify-between">
                    <span class="text-gray-400">Python:</span>
                    <span class="text-green-400">${systemStatus.python_version}</span>
                </div>
                <div class="flex justify-between">
                    <span class="text-gray-400">Platform:</span>
                    <span class="text-gray-300">${systemStatus.platform}</span>
                </div>
                <div class="flex justify-between">
                    <span class="text-gray-400">Go Installed:</span>
                    <span class="${systemStatus.go_installed ? 'text-green-400' : 'text-red-400'}">
                        ${systemStatus.go_installed ? 'Yes' : 'No'}
                    </span>
                </div>
                <div class="flex justify-between">
                    <span class="text-gray-400">GitFive:</span>
                    <span class="${systemStatus.gitfive.installed ? 'text-green-400' : 'text-yellow-400'}">
                        ${systemStatus.gitfive.status}
                    </span>
                </div>
            </div>
        </div>

        <form id="features-form" class="space-y-4">
            <div class="feature-card">
                <label class="flex items-start cursor-pointer">
                    <input type="checkbox" name="enable_github" class="mt-1 mr-3 rounded bg-gray-700 border-gray-600">
                    <div class="flex-1">
                        <div class="flex items-center gap-2 mb-1">
                            <span class="text-white font-semibold">GitHub Analysis (GitFive)</span>
                            <span class="text-xs px-2 py-1 bg-blue-600 rounded">Advanced</span>
                        </div>
                        <span class="text-gray-400 text-sm block mb-2">Deep profile analysis, repositories, SSH keys</span>
                        <div class="text-xs space-y-1">
                            <div class="text-yellow-400">⚠ Requires: GitFive installation & GitHub auth</div>
                            <div class="text-gray-500">Features: Profile scraping, repo analysis, commit history</div>
                        </div>
                    </div>
                </label>
            </div>

            <div class="feature-card">
                <label class="flex items-start cursor-pointer">
                    <input type="checkbox" name="enable_dns_recon" class="mt-1 mr-3 rounded bg-gray-700 border-gray-600">
                    <div class="flex-1">
                        <div class="flex items-center gap-2 mb-1">
                            <span class="text-white font-semibold">DNS Reconnaissance</span>
                            <span class="text-xs px-2 py-1 bg-purple-600 rounded">Pro</span>
                        </div>
                        <span class="text-gray-400 text-sm block mb-2">Subdomain discovery and security analysis</span>
                        <div class="text-xs space-y-1">
                            <div class="text-yellow-400">⚠ Requires: Go tools (subfinder, httpx, nuclei)</div>
                            <div class="text-gray-500">Features: Subdomain enum, port scanning, tech detection</div>
                        </div>
                    </div>
                </label>
            </div>

            <div class="feature-card">
                <label class="flex items-start cursor-pointer">
                    <input type="checkbox" name="enable_ns_lookup" class="mt-1 mr-3 rounded bg-gray-700 border-gray-600">
                    <div class="flex-1">
                        <div class="flex items-center gap-2 mb-1">
                            <span class="text-white font-semibold">NS Lookup</span>
                            <span class="text-xs px-2 py-1 bg-green-600 rounded">Basic</span>
                        </div>
                        <span class="text-gray-400 text-sm block mb-2">Find domains sharing nameservers</span>
                        <div class="text-xs space-y-1">
                            <div class="text-yellow-400">⚠ Requires: HackerTarget API key</div>
                        </div>
                    </div>
                </label>
            </div>

            <div class="feature-card">
                <label class="flex items-start cursor-pointer">
                    <input type="checkbox" name="enable_osint_industries" class="mt-1 mr-3 rounded bg-gray-700 border-gray-600">
                    <div class="flex-1">
                        <div class="flex items-center gap-2 mb-1">
                            <span class="text-white font-semibold">OSINT Industries</span>
                            <span class="text-xs px-2 py-1 bg-purple-600 rounded">Premium</span>
                        </div>
                        <span class="text-gray-400 text-sm block mb-2">Search emails, phones, usernames</span>
                        <div class="text-xs space-y-1">
                            <div class="text-yellow-400">⚠ Requires: OSINT Industries API key (paid)</div>
                        </div>
                    </div>
                </label>
            </div>

            <div class="feature-card">
                <label class="flex items-start cursor-pointer">
                    <input type="checkbox" name="enable_whois" class="mt-1 mr-3 rounded bg-gray-700 border-gray-600">
                    <div class="flex-1">
                        <div class="flex items-center gap-2 mb-1">
                            <span class="text-white font-semibold">WHOIS History</span>
                            <span class="text-xs px-2 py-1 bg-blue-600 rounded">Basic</span>
                        </div>
                        <span class="text-gray-400 text-sm block mb-2">Historical domain registration data</span>
                        <div class="text-xs space-y-1">
                            <div class="text-yellow-400">⚠ Requires: WhoisXML API key (1000 free)</div>
                        </div>
                    </div>
                </label>
            </div>

            <div class="feature-card">
                <label class="flex items-start cursor-pointer">
                    <input type="checkbox" name="enable_cavalier" class="mt-1 mr-3 rounded bg-gray-700 border-gray-600">
                    <div class="flex-1">
                        <div class="flex items-center gap-2 mb-1">
                            <span class="text-white font-semibold">Cavalier API</span>
                            <span class="text-xs px-2 py-1 bg-red-600 rounded">Free</span>
                        </div>
                        <span class="text-gray-400 text-sm block mb-2">Search compromised accounts</span>
                        <div class="text-xs"><div class="text-green-400">✓ No API key required</div></div>
                    </div>
                </label>
            </div>

            <div class="feature-card">
                <label class="flex items-start cursor-pointer">
                    <input type="checkbox" name="enable_doxbin" class="mt-1 mr-3 rounded bg-gray-700 border-gray-600">
                    <div class="flex-1">
                        <div class="flex items-center gap-2 mb-1">
                            <span class="text-white font-semibold">DoxBin Search</span>
                            <span class="text-xs px-2 py-1 bg-red-600 rounded">Free</span>
                        </div>
                        <span class="text-gray-400 text-sm block mb-2">Search breached DoxBin database</span>
                        <div class="text-xs"><div class="text-green-400">✓ No API key required</div></div>
                    </div>
                </label>
            </div>

            <div class="flex gap-4 mt-6">
                <button type="button" onclick="previousStep()" class="flex-1 bg-gray-800 hover:bg-gray-700 border border-gray-700 text-white font-bold py-3 px-6 rounded-lg transition-colors flex items-center justify-center gap-2">
                    <i data-lucide="arrow-left" class="w-4 h-4"></i> Back
                </button>
                <button type="submit" class="flex-1 bg-gray-800 hover:bg-gray-700 border border-gray-700 text-white font-bold py-3 px-6 rounded-lg transition-colors flex items-center justify-center gap-2">
                    Continue <i data-lucide="arrow-right" class="w-4 h-4"></i>
                </button>
            </div>
        </form>
    </div>`;
}

// Step 3: Tools Installation HTML
function getStep3HTML() {
    return `
    <div id="step-3" class="setup-step">
        <h2 class="text-2xl font-bold mb-2">Install Required Tools</h2>
        <p class="text-gray-400 mb-6">Install Go tools and configure external dependencies</p>

        <div class="bg-gray-800/50 border border-gray-700 rounded-lg p-4 mb-6">
            <h3 class="text-white font-semibold mb-4 flex items-center gap-2">
                <i data-lucide="package" class="w-5 h-5"></i>
                Go Tools Installation
            </h3>
            <div id="go-tools-status" class="space-y-3 mb-4"></div>
            <button type="button" onclick="installGoTools()" id="install-go-btn" class="w-full bg-blue-600 hover:bg-blue-700 border border-blue-600 text-white font-bold py-3 px-6 rounded-lg transition-colors flex items-center justify-center gap-2">
                <i data-lucide="download" class="w-4 h-4"></i> Install Go Tools
            </button>
        </div>

        <div class="bg-gray-800/50 border border-gray-700 rounded-lg p-4 mb-6">
            <h3 class="text-white font-semibold mb-4 flex items-center gap-2">
                <i data-lucide="git-branch" class="w-5 h-5"></i>
                GitFive Setup Guide
            </h3>
            <div id="gitfive-guide" class="space-y-2 mb-4 text-sm text-gray-400"></div>
            <button type="button" onclick="showGitFiveGuide()" class="w-full bg-purple-600 hover:bg-purple-700 border border-purple-600 text-white font-bold py-3 px-6 rounded-lg transition-colors flex items-center justify-center gap-2">
                <i data-lucide="book-open" class="w-4 h-4"></i> View Detailed Guide
            </button>
        </div>

        <div class="flex gap-4">
            <button type="button" onclick="previousStep()" class="flex-1 bg-gray-800 hover:bg-gray-700 border border-gray-700 text-white font-bold py-3 px-6 rounded-lg transition-colors flex items-center justify-center gap-2">
                <i data-lucide="arrow-left" class="w-4 h-4"></i> Back
            </button>
            <button type="button" onclick="nextStep()" class="flex-1 bg-gray-800 hover:bg-gray-700 border border-gray-700 text-white font-bold py-3 px-6 rounded-lg transition-colors flex items-center justify-center gap-2">
                Continue <i data-lucide="arrow-right" class="w-4 h-4"></i>
            </button>
        </div>
    </div>`;
}

// Step 4: API Configuration HTML
function getStep4HTML() {
    const apis = [
        { name: 'hacker_target', label: 'HackerTarget API', url: 'https://hackertarget.com/api/' },
        { name: 'osint_industries', label: 'OSINT Industries API', url: 'https://osint.industries' },
        { name: 'whois_history', label: 'WhoisXML API', url: 'https://whoisxmlapi.com' },
        { name: 'securitytrails', label: 'SecurityTrails API', url: 'https://securitytrails.com' },
        { name: 'virustotal', label: 'VirusTotal API', url: 'https://www.virustotal.com/gui/join-us' }
    ];

    let apiHTML = apis.map(api => `
        <div class="api-config-card">
            <div class="flex items-center justify-between mb-3">
                <label class="text-white font-semibold">${api.label}</label>
                <a href="${api.url}" target="_blank" class="text-blue-400 hover:text-blue-300 text-sm flex items-center gap-1">
                    <i data-lucide="external-link" class="w-3 h-3"></i> Get Key
                </a>
            </div>
            <div class="flex gap-2">
                <input type="text" name="${api.name}" id="${api.name}_input" class="flex-1 px-4 py-3 bg-gray-800 border border-gray-700 text-white rounded-lg focus:outline-none focus:border-gray-500 transition-colors placeholder-gray-500" placeholder="Enter API key (optional)">
                <button type="button" onclick="validateKey('${api.name}')" class="px-4 py-2 bg-gray-800 hover:bg-gray-700 border border-gray-700 text-white rounded-lg transition-colors">
                    <i data-lucide="check" class="w-4 h-4"></i>
                </button>
            </div>
            <div id="${api.name}_status" class="mt-2 text-sm"></div>
        </div>
    `).join('');

    return `
    <div id="step-4" class="setup-step">
        <h2 class="text-2xl font-bold mb-2">API Configuration</h2>
        <p class="text-gray-400 mb-6">Configure API keys with real-time validation</p>

        <form id="api-form" class="space-y-4">
            ${apiHTML}

            <div class="bg-gray-800/50 border border-gray-700 rounded-lg p-4 mt-6">
                <h3 class="text-white font-semibold mb-3">GitFive Paths (If Enabled)</h3>
                <div class="space-y-3">
                    <div>
                        <label class="block text-gray-400 mb-2 text-sm">Virtual Environment Python Path</label>
                        <input type="text" name="gitfive_venv" class="w-full px-3 py-2 bg-gray-700 border border-gray-600 text-white rounded focus:outline-none focus:border-gray-500 transition-colors placeholder-gray-500" placeholder="/path/to/GitFive/venv/bin/python">
                    </div>
                    <div>
                        <label class="block text-gray-400 mb-2 text-sm">Main Script Path</label>
                        <input type="text" name="gitfive_script" class="w-full px-3 py-2 bg-gray-700 border border-gray-600 text-white rounded focus:outline-none focus:border-gray-500 transition-colors placeholder-gray-500" placeholder="/path/to/GitFive/main.py">
                    </div>
                </div>
            </div>

            <div class="flex gap-4 mt-6">
                <button type="button" onclick="previousStep()" class="flex-1 bg-gray-800 hover:bg-gray-700 border border-gray-700 text-white font-bold py-3 px-6 rounded-lg transition-colors flex items-center justify-center gap-2">
                    <i data-lucide="arrow-left" class="w-4 h-4"></i> Back
                </button>
                <button type="submit" class="flex-1 bg-gray-800 hover:bg-gray-700 border border-gray-700 text-white font-bold py-3 px-6 rounded-lg transition-colors flex items-center justify-center gap-2">
                    Continue <i data-lucide="arrow-right" class="w-4 h-4"></i>
                </button>
            </div>
        </form>
    </div>`;
}

// Step 5: Review & Complete HTML
function getStep5HTML() {
    return `
    <div id="step-5" class="setup-step">
        <h2 class="text-2xl font-bold mb-2">Review & Complete</h2>
        <p class="text-gray-400 mb-6">Review your configuration and complete setup</p>

        <div class="space-y-4 mb-6">
            <div class="bg-gray-800/50 border border-gray-700 rounded-lg p-4">
                <h3 class="text-white font-semibold mb-3">Configuration Summary</h3>
                <ul class="text-gray-400 space-y-2 text-sm" id="config-summary">
                    <li class="flex items-center gap-2"><i data-lucide="check-circle" class="w-4 h-4 text-green-400"></i> Admin account configured</li>
                    <li class="flex items-center gap-2"><i data-lucide="check-circle" class="w-4 h-4 text-green-400"></i> Features selected</li>
                    <li class="flex items-center gap-2"><i data-lucide="check-circle" class="w-4 h-4 text-green-400"></i> Tools configured</li>
                    <li class="flex items-center gap-2"><i data-lucide="check-circle" class="w-4 h-4 text-green-400"></i> API keys configured</li>
                </ul>
            </div>

            <div class="bg-gray-800/50 border border-gray-600 rounded-lg p-4">
                <h3 class="text-white font-semibold mb-3 flex items-center gap-2">
                    <i data-lucide="info" class="w-4 h-4"></i> Next Steps
                </h3>
                <ul class="text-gray-400 space-y-2 text-sm">
                    <li>• Review your .env configuration file</li>
                    <li>• Restart the application to apply changes</li>
                    <li>• Install Go tools if DNS recon is enabled</li>
                    <li>• Configure GitFive if GitHub analysis is enabled</li>
                    <li>• You can modify settings later in the web interface</li>
                </ul>
            </div>
        </div>

        <div class="flex gap-4">
            <button type="button" onclick="previousStep()" class="flex-1 bg-gray-800 hover:bg-gray-700 border border-gray-700 text-white font-bold py-3 px-6 rounded-lg transition-colors flex items-center justify-center gap-2">
                <i data-lucide="arrow-left" class="w-4 h-4"></i> Back
            </button>
            <button type="button" onclick="completeSetup()" class="flex-1 bg-green-600 hover:bg-green-700 border border-green-600 text-white font-bold py-3 px-6 rounded-lg transition-colors flex items-center justify-center gap-2">
                Complete Setup <i data-lucide="check" class="w-4 h-4"></i>
            </button>
        </div>
    </div>`;
}

// Check Go tools installation status
async function checkGoTools() {
    const statusDiv = document.getElementById('go-tools-status');
    statusDiv.innerHTML = '<div class="flex items-center justify-between text-sm"><span class="text-gray-400">Checking tools...</span><div class="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div></div>';

    try {
        const response = await fetch('/setup/system-check');
        const data = await response.json();
        const tools = data.go.tools;

        let html = '';
        for (const [name, info] of Object.entries(tools)) {
            const statusColor = info.installed ? 'text-green-400' : 'text-red-400';
            const statusIcon = info.installed ? 'check-circle' : 'x-circle';
            html += `
                <div class="flex items-center justify-between text-sm">
                    <div class="flex items-center gap-2">
                        <i data-lucide="${statusIcon}" class="w-4 h-4 ${statusColor}"></i>
                        <span class="text-white">${name}</span>
                        ${info.version ? `<span class="text-gray-500 text-xs">${info.version}</span>` : ''}
                    </div>
                    <span class="${statusColor}">${info.installed ? 'Installed' : 'Not Installed'}</span>
                </div>`;
        }

        statusDiv.innerHTML = html;
        if (typeof lucide !== 'undefined') lucide.createIcons();

        // Show GitFive status
        const gitfiveDiv = document.getElementById('gitfive-guide');
        if (data.gitfive.installed) {
            gitfiveDiv.innerHTML = `<div class="text-green-400">✓ GitFive found at: ${data.gitfive.path}</div>`;
        } else {
            gitfiveDiv.innerHTML = `<div class="text-yellow-400">⚠ GitFive not detected. Click below for setup instructions.</div>`;
        }
    } catch (error) {
        statusDiv.innerHTML = `<div class="text-red-400">Error checking tools: ${error.message}</div>`;
    }
}

// Install Go tools
async function installGoTools() {
    showLoading(true, 'Installing Go tools... This may take a few minutes.');
    const btn = document.getElementById('install-go-btn');
    btn.disabled = true;
    btn.innerHTML = '<i data-lucide="loader" class="w-4 h-4 animate-spin"></i> Installing...';

    try {
        const response = await fetch('/setup/install-tools', { method: 'POST' });
        const data = await response.json();

        if (data.success) {
            showNotification('Go tools installed successfully!', 'success');
            checkGoTools();
        } else {
            showNotification('Installation failed. Check console for details.', 'error');
            console.error(data);
        }
    } catch (error) {
        showNotification('Installation error: ' + error.message, 'error');
    } finally {
        showLoading(false);
        btn.disabled = false;
        btn.innerHTML = '<i data-lucide="download" class="w-4 h-4"></i> Install Go Tools';
        if (typeof lucide !== 'undefined') lucide.createIcons();
    }
}

// Show GitFive setup guide
async function showGitFiveGuide() {
    try {
        const response = await fetch('/setup/gitfive-guide');
        const data = await response.json();

        let html = '<div class="bg-gray-900 border border-gray-700 rounded-lg p-6"><h3 class="text-xl font-bold mb-4">GitFive Setup Instructions</h3><div class="space-y-4">';

        data.guide.steps.forEach(step => {
            html += `
                <div class="border-l-2 border-purple-600 pl-4">
                    <div class="text-white font-semibold mb-1">Step ${step.number}: ${step.title}</div>
                    <code class="block bg-gray-800 p-2 rounded text-sm text-green-400 mb-2">${step.command}</code>
                    <div class="text-gray-400 text-sm">${step.description}</div>
                </div>`;
        });

        html += '</div><div class="mt-4 bg-yellow-900/30 border border-yellow-700 rounded p-3"><div class="text-yellow-400 font-semibold mb-2">⚠ Important Warnings:</div><ul class="text-yellow-300 text-sm space-y-1">';
        data.guide.warnings.forEach(warn => {
            html += `<li>• ${warn}</li>`;
        });
        html += '</ul></div></div>';

        const modal = document.createElement('div');
        modal.className = 'fixed inset-0 bg-black bg-opacity-75 backdrop-blur-sm flex items-center justify-center z-50 p-4';
        modal.innerHTML = html + '<button onclick="this.parentElement.remove()" class="absolute top-4 right-4 text-white hover:text-gray-400"><i data-lucide="x" class="w-6 h-6"></i></button>';
        modal.onclick = (e) => { if (e.target === modal) modal.remove(); };
        document.body.appendChild(modal);
        if (typeof lucide !== 'undefined') lucide.createIcons();
    } catch (error) {
        showNotification('Error loading guide: ' + error.message, 'error');
    }
}

// Validate API key
async function validateKey(service) {
    const input = document.getElementById(`${service}_input`);
    const statusDiv = document.getElementById(`${service}_status`);
    const apiKey = input.value.trim();

    if (!apiKey) {
        statusDiv.innerHTML = '<span class="text-red-400">Please enter an API key</span>';
        return;
    }

    statusDiv.innerHTML = '<span class="text-gray-400">Validating...</span>';

    try {
        const formData = new FormData();
        formData.append('service', service);
        formData.append('api_key', apiKey);

        const response = await fetch('/setup/validate-api', { method: 'POST', body: formData });
        const data = await response.json();

        if (data.valid) {
            statusDiv.innerHTML = `<span class="text-green-400">✓ Valid${data.credits ? ` (${data.credits} credits)` : ''}</span>`;
        } else {
            statusDiv.innerHTML = `<span class="text-red-400">✗ ${data.message}</span>`;
        }
    } catch (error) {
        statusDiv.innerHTML = `<span class="text-red-400">Validation failed: ${error.message}</span>`;
    }
}

// Complete setup
async function completeSetup() {
    showLoading(true, 'Finalizing setup...');
    try {
        const response = await fetch('/setup/complete', { method: 'POST' });
        const data = await response.json();

        if (data.success) {
            showNotification('Setup completed successfully!', 'success');
            setTimeout(() => {
                window.location.href = data.redirect;
            }, 1500);
        } else {
            showNotification('Setup completion failed', 'error');
        }
    } catch (error) {
        showNotification('Error: ' + error.message, 'error');
    } finally {
        showLoading(false);
    }
}

// Refresh system status
async function refreshSystemStatus() {
    try {
        const response = await fetch('/setup/system-check');
        const data = await response.json();
        showNotification('System status refreshed', 'success');
        // Update UI with new data
        console.log(data);
    } catch (error) {
        showNotification('Failed to refresh status', 'error');
    }
}

// Form handlers for steps 2-4
document.addEventListener('DOMContentLoaded', () => {
    // Features form handler
    document.addEventListener('submit', async (e) => {
        if (e.target.id === 'features-form') {
            e.preventDefault();
            const formData = new FormData(e.target);
            showLoading(true, 'Saving features...');

            try {
                const response = await fetch('/setup/features', { method: 'POST', body: formData });
                const data = await response.json();

                if (data.success) {
                    showNotification(`${data.selected_count} features configured`, 'success');
                    nextStep();
                }
            } catch (error) {
                showNotification('Error: ' + error.message, 'error');
            } finally {
                showLoading(false);
            }
        }

        // API form handler
        if (e.target.id === 'api-form') {
            e.preventDefault();
            const formData = new FormData(e.target);
            showLoading(true, 'Saving API keys...');

            try {
                const response = await fetch('/setup/apis', { method: 'POST', body: formData });
                const data = await response.json();

                if (data.success) {
                    showNotification(`${data.configured_count} API keys configured`, 'success');
                    nextStep();
                }
            } catch (error) {
                showNotification('Error: ' + error.message, 'error');
            } finally {
                showLoading(false);
            }
        }
    });
});