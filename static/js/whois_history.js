// Initialize Lucide icons
lucide.createIcons()

// Get DOM elements
const searchButton = document.getElementById('searchButton')
const domainInput = document.getElementById('domainInput')
const loadingIndicator = document.getElementById('loadingIndicator')
const whoisData = document.getElementById('whoisData')
const domainNameEl = document.getElementById('domainName')
const recordsCountEl = document.getElementById('recordsCount')
const recordsTimeline = document.getElementById('recordsTimeline')

// Handle search
searchButton.addEventListener('click', async () => {
    const domain = domainInput.value.trim()
    if (!domain) return

    // Show loading state
    loadingIndicator.classList.remove('hidden')
    whoisData.classList.add('hidden')

    try {
        const response = await fetch(`/api/domain/history?domain=${domain}`)
        const data = await response.json()
        displayResults(data)
    } catch (error) {
        console.error('Error:', error)
        // TODO: Show error message to user
    } finally {
        loadingIndicator.classList.add('hidden')
    }
})

function formatDate(dateString) {
    return new Date(dateString).toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    })
}

function displayResults(data) {
    // Update domain info
    domainNameEl.textContent = data.records[0].domainName
    recordsCountEl.textContent = `${data.recordsCount} historical records`

    // Clear previous records
    recordsTimeline.innerHTML = ''

    // Add records to timeline
    data.records.forEach((record, index) => {
        const recordElement = document.createElement('div')
        recordElement.className = 'bg-gray-900 rounded-lg p-6'
        recordElement.innerHTML = `
            <div class="flex justify-between items-start">
                <div class="flex items-center space-x-4">
                    <div class="text-gray-400">
                        <div class="text-sm">Updated: ${formatDate(record.updatedDateISO8601)}</div>
                        <div class="text-sm mt-1">Expires: ${formatDate(record.expiresDateISO8601)}</div>
                    </div>
                </div>
                <button class="section-toggle bg-gray-800 hover:bg-gray-700 px-3 py-1 rounded-md transition-colors">
                    <i data-lucide="chevron-down" class="w-5 h-5"></i>
                </button>
            </div>
            <div class="recordDetails mt-4 space-y-4">
                <div class="grid grid-cols-2 gap-4">
                    <div>
                        <h4 class="text-sm font-bold mb-2">Registrar</h4>
                        <p class="text-gray-400 text-sm">${record.registrarName || 'N/A'}</p>
                    </div>
                    <div>
                        <h4 class="text-sm font-bold mb-2">WHOIS Server</h4>
                        <p class="text-gray-400 text-sm">${record.whoisServer || 'N/A'}</p>
                    </div>
                </div>

                <div>
                    <h4 class="text-sm font-bold mb-2">Dates</h4>
                    <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
                        <div class="bg-gray-800 p-3 rounded">
                            <p class="text-xs text-gray-500 mb-1">Created</p>
                            <p class="text-sm">${formatDate(record.createdDateISO8601)}</p>
                        </div>
                        <div class="bg-gray-800 p-3 rounded">
                            <p class="text-xs text-gray-500 mb-1">Updated</p>
                            <p class="text-sm">${formatDate(record.updatedDateISO8601)}</p>
                        </div>
                        <div class="bg-gray-800 p-3 rounded">
                            <p class="text-xs text-gray-500 mb-1">Expires</p>
                            <p class="text-sm">${formatDate(record.expiresDateISO8601)}</p>
                        </div>
                    </div>
                </div>

                <div>
                    <h4 class="text-sm font-bold mb-2">Name Servers</h4>
                    <div class="space-y-1">
                        ${record.nameServers.map(ns => `
                            <div class="bg-gray-800 p-2 rounded text-sm">${ns}</div>
                        `).join('')}
                    </div>
                </div>

                <div>
                    <h4 class="text-sm font-bold mb-2">Status</h4>
                    <div class="flex flex-wrap gap-2">
                        ${record.status.map(status => `
                            <span class="bg-gray-800 px-2 py-1 rounded text-xs">${status}</span>
                        `).join('')}
                    </div>
                </div>

                ${record.registrantContact ? `
                <div>
                    <h4 class="text-sm font-bold mb-2">Registrant Contact</h4>
                    <div class="bg-gray-800 p-3 rounded space-y-2">
                        ${renderContactInfo(record.registrantContact)}
                    </div>
                </div>
                ` : ''}

                ${record.administrativeContact ? `
                <div>
                    <h4 class="text-sm font-bold mb-2">Administrative Contact</h4>
                    <div class="bg-gray-800 p-3 rounded space-y-2">
                        ${renderContactInfo(record.administrativeContact)}
                    </div>
                </div>
                ` : ''}

                ${record.technicalContact ? `
                <div>
                    <h4 class="text-sm font-bold mb-2">Technical Contact</h4>
                    <div class="bg-gray-800 p-3 rounded space-y-2">
                        ${renderContactInfo(record.technicalContact)}
                    </div>
                </div>
                ` : ''}

                ${record.billingContact ? `
                <div>
                    <h4 class="text-sm font-bold mb-2">Billing Contact</h4>
                    <div class="bg-gray-800 p-3 rounded space-y-2">
                        ${renderContactInfo(record.billingContact)}
                    </div>
                </div>
                ` : ''}

                ${record.zoneContact && Object.values(record.zoneContact).some(val => val) ? `
                <div>
                    <h4 class="text-sm font-bold mb-2">Zone Contact</h4>
                    <div class="bg-gray-800 p-3 rounded space-y-2">
                        ${renderContactInfo(record.zoneContact)}
                    </div>
                </div>
                ` : ''}

            </div>
        `
        recordsTimeline.appendChild(recordElement)
    })

    // Show results
    whoisData.classList.remove('hidden')

    // Reinitialize Lucide icons for new content
    lucide.createIcons()

    // Add event listeners for record toggles
    document.querySelectorAll('.section-toggle').forEach(button => {
        button.addEventListener('click', (e) => {
            const recordDetails = e.target.closest('.bg-gray-900').querySelector('.recordDetails')
            recordDetails.classList.toggle('expanded')
            button.classList.toggle('active')
        })
    })
}

function renderContactInfo(contact) {
    const fields = [{
            key: 'name',
            icon: 'user',
            label: 'Name'
        },
        {
            key: 'organization',
            icon: 'building',
            label: 'Organization'
        },
        {
            key: 'street',
            icon: 'map',
            label: 'Street'
        },
        {
            key: 'city',
            icon: 'home',
            label: 'City'
        },
        {
            key: 'state',
            icon: 'map-pin',
            label: 'State'
        },
        {
            key: 'postalCode',
            icon: 'mail',
            label: 'Postal Code'
        },
        {
            key: 'country',
            icon: 'globe',
            label: 'Country'
        },
        {
            key: 'email',
            icon: 'mail',
            label: 'Email'
        },
        {
            key: 'telephone',
            icon: 'phone',
            label: 'Phone'
        },
        {
            key: 'fax',
            icon: 'printer',
            label: 'Fax'
        }
    ];

    return fields
        .filter(field => contact[field.key])
        .map(field => `
            <div class="flex items-center gap-2">
                <i data-lucide="${field.icon}" class="w-4 h-4 text-gray-500"></i>
                <span class="text-xs text-gray-500">${field.label}:</span>
                <span class="text-sm">${contact[field.key]}</span>
            </div>
        `).join('');
}

// Handle Enter key in search input
domainInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
        searchButton.click()
    }
})