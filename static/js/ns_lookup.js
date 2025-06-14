// Initialize Lucide icons
lucide.createIcons();

// Add input padding for icons
document.querySelectorAll('input[type="text"]').forEach(input => {
    input.style.paddingLeft = '2.5rem';
});

let sharedDomains = [];
let whoisData = {};

// Helper to chunk array for parallel processing
function chunkArray(array, size) {
    const chunks = [];
    for (let i = 0; i < array.length; i += size) {
        chunks.push(array.slice(i, i + size));
    }
    return chunks;
}

function extractRegistrantInfo(whoisResponse) {
    return {
        registrant: whoisResponse.registrant,
        email: whoisResponse.email,
        creationDate: whoisResponse.creation_date,
        registrar: whoisResponse.registrar
    };
}

async function fetchWhoisBatch(domains) {
    return Promise.all(domains.map(async domain => {
        try {
            const response = await fetch(`/api/domain/whois?domain=${encodeURIComponent(domain)}`);
            if (!response.ok) throw new Error(`Failed to fetch WHOIS for ${domain}`);
            const data = await response.json();

            // Store both raw text and parsed data
            whoisData[domain] = {
                data: data.domain_raw_text + '\n\n' + data.ip_raw_text,
                parsedData: {
                    registrant: data.registrant,
                    email: data.email,
                    creation_date: data.creation_date,
                    registrar: data.registrar
                }
            };

            return {
                domain,
                success: true
            };
        } catch (error) {
            console.error(`Error fetching WHOIS for ${domain}:`, error);
            whoisData[domain] = {
                data: `Error fetching WHOIS data: ${error.message}`,
                parsedData: null
            };
            return {
                domain,
                success: false
            };
        }
    }));
}



function findSimilarDomains(whoisData) {
    const groups = {
        sameRegistrant: {},
        sameEmail: {},
        sameRegistrar: {},
        sameYear: {}
    };

    // Process each domain's WHOIS data
    Object.entries(whoisData).forEach(([domain, info]) => {
        if (!info || !info.parsedData) return;
        const {
            parsedData
        } = info;

        if (parsedData.registrant) {
            if (!groups.sameRegistrant[parsedData.registrant]) {
                groups.sameRegistrant[parsedData.registrant] = new Set();
            }
            groups.sameRegistrant[parsedData.registrant].add(domain);
        }

        if (parsedData.email) {
            if (!groups.sameEmail[parsedData.email]) {
                groups.sameEmail[parsedData.email] = new Set();
            }
            groups.sameEmail[parsedData.email].add(domain);
        }

        if (parsedData.registrar) {
            if (!groups.sameRegistrar[parsedData.registrar]) {
                groups.sameRegistrar[parsedData.registrar] = new Set();
            }
            groups.sameRegistrar[parsedData.registrar].add(domain);
        }

        if (parsedData.creation_date) {
            const year = parsedData.creation_date.slice(0, 4);
            if (!groups.sameYear[year]) {
                groups.sameYear[year] = new Set();
            }
            groups.sameYear[year].add(domain);
        }
    });

    return groups;
}


function displaySimilarGroups(groups) {
    const similarGroups = document.getElementById('similarGroups');
    similarGroups.innerHTML = '';

    function createGroup(title, domains, type) {
        const groupDiv = document.createElement('div');
        groupDiv.className = 'bg-gray-800 rounded-lg p-4';
        const domainsArray = Array.from(domains);

        groupDiv.innerHTML = `
    <div class="flex justify-between items-center cursor-pointer hover:text-gray-300 transition-colors" 
            onclick="this.parentElement.querySelector('.content').classList.toggle('hidden')">
        <h3 class="font-semibold flex items-center gap-2">
            <i data-lucide="folder" class="w-4 h-4"></i>
            ${title} 
            <span class="text-sm text-gray-400 bg-gray-900 px-2 py-0.5 rounded-lg">
                ${domains.size} domains
            </span>
        </h3>
        <i data-lucide="chevron-down" class="w-5 h-5 transition-transform"></i>
    </div>
    <div class="content hidden mt-4 space-y-2">
        ${domainsArray.map(domain => `
            <div class="bg-gray-900 p-3 rounded-lg">
                <div class="flex justify-between items-center">
                    <span class="text-gray-300">${domain}</span>
                    <button onclick="toggleWhois('${domain}')" 
                        class="text-sm text-blue-400 hover:text-blue-300 transition-colors flex items-center gap-1">
                        <i data-lucide="info" class="w-4 h-4"></i>
                        WHOIS
                    </button>
                </div>
                <pre id="whois-${domain}" class="hidden mt-3 text-sm overflow-x-auto whitespace-pre-wrap bg-gray-950 p-3 rounded-lg text-gray-400">${whoisData[domain]?.data || 'No WHOIS data available'}</pre>
            </div>
        `).join('')}
    </div>
`;
        return groupDiv;
    }

    // Create sections for each type of similarity
    const sections = [{
            title: 'Same Registrant',
            data: groups.sameRegistrant
        },
        {
            title: 'Same Email',
            data: groups.sameEmail
        },
        {
            title: 'Same Registrar',
            data: groups.sameRegistrar
        },
        {
            title: 'Same Registration Year',
            data: groups.sameYear
        }
    ];

    sections.forEach(section => {
        const relevantGroups = Object.entries(section.data)
            .filter(([key, domains]) => domains.size > 1)
            .sort(([k1, a], [k2, b]) => b.size - a.size);

        if (relevantGroups.length > 0) {
            const sectionDiv = document.createElement('div');
            sectionDiv.className = 'mb-6';
            sectionDiv.innerHTML = `<h3 class="text-lg font-semibold mb-3">${section.title}</h3>`;

            relevantGroups.forEach(([key, domains]) => {
                const group = createGroup(key, domains, section.title);
                if (group) sectionDiv.appendChild(group);
            });

            similarGroups.appendChild(sectionDiv);
        }
    });
}
// Toggle WHOIS record visibility
window.toggleWhois = function(domain) {
    const whoisElement = document.getElementById(`whois-${domain}`);
    whoisElement.classList.toggle('hidden');
}

document.getElementById('submitQuery').addEventListener('click', async () => {
    const ns1 = document.getElementById('ns1Input').value.trim();
    const ns2 = document.getElementById('ns2Input').value.trim();

    if (!ns1 || !ns2) {
        alert('Please enter both nameservers');
        return;
    }

    const loading = document.getElementById('loading');
    const result = document.getElementById('result');
    const domainList = document.getElementById('domainList');
    const domainCount = document.getElementById('domainCount');
    const analyzeSection = document.getElementById('analyzeSection');
    const whoisAnalysis = document.getElementById('whoisAnalysis');

    loading.classList.remove('hidden');
    result.classList.add('hidden');
    whoisAnalysis.classList.add('hidden');
    domainList.innerHTML = '';

    try {
        const response = await fetch(`/api/ns/search?ns1=${encodeURIComponent(ns1)}&ns2=${encodeURIComponent(ns2)}`);
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        sharedDomains = await response.json();

        sharedDomains.forEach(domain => {
            const domainElement = document.createElement('div');
            domainElement.className = 'bg-gray-800 p-3 rounded-lg flex justify-between items-center group';
            domainElement.innerHTML = `
                <div class="flex items-center gap-2">
                    <i data-lucide="globe" class="w-4 h-4 text-gray-500"></i>
                    <span class="break-all">${domain}</span>
                </div>
                <button onclick="copyToClipboard('${domain}')" 
                    class="ml-2 text-gray-400 hover:text-white flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    <i data-lucide="copy" class="w-4 h-4"></i>
                </button>
            `;
            domainList.appendChild(domainElement);
            lucide.createIcons(); // Refresh icons for new elements
        });

        domainCount.textContent = `${sharedDomains.length} domains found`;
        analyzeSection.classList.remove('hidden');
        result.classList.remove('hidden');
    } catch (error) {
        domainList.innerHTML = `<div class="text-red-500">Error: ${error.message}</div>`;
        result.classList.remove('hidden');
    } finally {
        loading.classList.add('hidden');
    }
});

document.getElementById('analyzeWhois').addEventListener('click', async () => {
    const analysisProgress = document.getElementById('analysisProgress');
    const whoisAnalysis = document.getElementById('whoisAnalysis');
    const analyzeButton = document.getElementById('analyzeWhois');

    analyzeButton.disabled = true;
    analyzeButton.classList.add('opacity-50');
    whoisData = {};
    analysisProgress.classList.remove('hidden');
    analysisProgress.querySelector('span').textContent = 'Starting WHOIS analysis...';
    whoisAnalysis.classList.add('hidden');

    try {
        // Process domains in parallel batches
        const BATCH_SIZE = 5;
        const domainBatches = chunkArray(sharedDomains, BATCH_SIZE);
        let processedCount = 0;

        for (const batch of domainBatches) {
            const results = await fetchWhoisBatch(batch);
            results.forEach(({
                domain,
                data
            }) => {
                if (data) whoisData[domain] = data;
            });
            processedCount += batch.length;
            analysisProgress.querySelector('span').textContent = `Analyzed ${processedCount}/${sharedDomains.length} domains`;
        }

        // Find and display similar domains
        const groups = findSimilarDomains(whoisData);
        displaySimilarGroups(groups);
        whoisAnalysis.classList.remove('hidden');
    } catch (error) {
        analysisProgress.querySelector('span').textContent = `Error: ${error.message}`;
    } finally {
        analyzeButton.disabled = false;
        analyzeButton.classList.remove('opacity-50');
        analysisProgress.classList.add('hidden');
    }
});

function copyToClipboard(text) {
    navigator.clipboard.writeText(text)
        .catch(err => console.error('Failed to copy text: ', err));
}