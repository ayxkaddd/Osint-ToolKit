window.toggleSensitiveInfo = function(index) {
    const infoDiv = document.getElementById(`sensitive-info-${index}`);
    const chevron = document.getElementById(`chevron-${index}`);

    if (infoDiv.classList.contains('hidden')) {
        infoDiv.classList.remove('hidden');
        chevron.style.transform = 'rotate(180deg)';
    } else {
        infoDiv.classList.add('hidden');
        chevron.style.transform = 'rotate(0deg)';
    }
}

// Add copy to clipboard functionality
window.copyToClipboard = function(text, button) {
    navigator.clipboard.writeText(text).then(() => {
        const copyText = button.querySelector('.copy-text');
        const originalText = copyText.textContent;
        const originalBg = button.className;

        // Change button appearance
        button.className = button.className.replace('bg-gray-800 hover:bg-gray-700', 'bg-green-800');
        copyText.textContent = 'Copied!';

        // Add success animation
        button.style.transform = 'scale(0.95)';
        setTimeout(() => button.style.transform = 'scale(1)', 100);

        // Reset button after 2 seconds
        setTimeout(() => {
            button.className = originalBg;
            copyText.textContent = originalText;
        }, 2000);
    }).catch(err => {
        console.error('Failed to copy text: ', err);
    });
}

document.addEventListener("DOMContentLoaded", () => {
    const searchInput = document.getElementById("searchInput");
    const resultsContainer = document.getElementById("resultsContainer");
    const loadingIndicator = document.getElementById("loadingIndicator");
    let debounceTimeout;

    // Initialize Lucide icons
    lucide.createIcons();

    searchInput.addEventListener("input", (e) => {
        const query = e.target.value.trim();

        // Clear previous timeout
        clearTimeout(debounceTimeout);

        if (query.length < 2) {
            resultsContainer.innerHTML = "";
            return;
        }

        // Show loading indicator
        loadingIndicator.classList.remove("hidden");

        // Debounce the API call
        debounceTimeout = setTimeout(() => {
            fetchResults(query);
        }, 300);
    });

    async function fetchResults(query) {
        try {
            const response = await fetch(`/api/doxbin/query?query=${encodeURIComponent(query)}`);
            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.detail || "Failed to fetch results");
            }

            displayResults(data);
        } catch (error) {
            console.error("Error fetching results:", error);
            resultsContainer.innerHTML = `
                <div class="bg-red-900/50 border border-red-700 rounded-lg p-4 text-center max-w-md mx-auto">
                    ${atob(error.message)}
                </div>
            `;
        } finally {
            loadingIndicator.classList.add("hidden");
        }
    }

    function displayResults(results) {
        if (!results.length) {
            resultsContainer.innerHTML = `
                <div class="bg-gray-900 border border-gray-700 rounded-lg p-4 text-center text-gray-400 max-w-md mx-auto">
                    No results found
                </div>
            `;
            return;
        }

        resultsContainer.innerHTML = results.map((user, index) => `
            <div class="bg-gray-900 rounded-lg p-4 hover:bg-gray-800 transition-colors max-w-md mx-auto">
                <div class="flex items-center justify-between">
                    <div class="flex-1">
                        <div class="flex items-center gap-3">
                            <div class="flex flex-wrap gap-2">
                                ${user.username.map(name => `
                                    <h3 class="text-lg font-bold">${name}</h3>
                                `).join(' | ')}
                            </div>
                            <span class="text-xs bg-gray-700 px-2 py-0.5 rounded">ID: ${user.uid}</span>
                            <a href="${user.profile_url}" target="_blank"
                               class="text-gray-400 hover:text-white transition-colors"
                               title="View Profile">
                                <i data-lucide="external-link" class="w-4 h-4"></i>
                            </a>
                        </div>
                        <div class="mt-2 space-y-1">
                            ${user.email.map(email => `
                                <div class="flex items-center text-gray-400">
                                    <i data-lucide="mail" class="w-4 h-4 mr-2"></i>
                                    <span class="text-sm">${email}</span>
                                </div>
                            `).join('')}
                        </div>
                        <div class="mt-3">
                            <button
                                onclick="toggleSensitiveInfo(${index})"
                                class="text-sm text-gray-400 hover:text-white flex items-center gap-2 transition-colors"
                            >
                                <i data-lucide="chevron-down" class="w-4 h-4 transition-transform" id="chevron-${index}"></i>
                                Show password and session
                            </button>
                            <div id="sensitive-info-${index}" class="hidden mt-2 space-y-2 pl-2 border-l border-gray-700">
                                <div class="flex items-center justify-between text-gray-400 group">
                                    <div class="flex items-center">
                                        <i data-lucide="key" class="w-4 h-4 mr-2"></i>
                                        <span class="text-sm font-mono">${user.password.slice(0, 32)}${user.password.length > 38 ? '...' : ''}</span>
                                    </div>
                                    <button
                                        onclick="copyToClipboard('${user.password}', this)"
                                        class="flex items-center gap-1 px-2 py-1 text-xs rounded-md
                                               bg-gray-800 hover:bg-gray-700
                                               transition-all duration-200 ease-in-out
                                               focus:outline-none focus:ring-2 focus:ring-gray-600"
                                    >
                                        <i data-lucide="copy" class="w-3 h-3"></i>
                                        <span class="copy-text"></span>
                                    </button>
                                </div>
                                <div class="flex items-center justify-between text-gray-400 group">
                                    <div class="flex items-center">
                                        <i data-lucide="cookie" class="w-4 h-4 mr-2"></i>
                                        <span class="text-sm font-mono">${user.session}</span>
                                    </div>
                                <button
                                        onclick="copyToClipboard('${user.session}', this)"
                                        class="flex items-center gap-1 px-2 py-1 text-xs rounded-md
                                               bg-gray-800 hover:bg-gray-700
                                               transition-all duration-200 ease-in-out
                                               focus:outline-none focus:ring-2 focus:ring-gray-600"
                                    >
                                        <i data-lucide="copy" class="w-3 h-3"></i>
                                        <span class="copy-text"></span>
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `).join("");

        // Reinitialize Lucide icons for new content
        lucide.createIcons();
    }
});
