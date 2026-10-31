// Initialize Lucide icons
lucide.createIcons();

// Enable result loading
window.currentService = 'vk_profile';
window.loadResultIntoView = function (data) {
    displayResults(data);
    document.getElementById('results').classList.remove('hidden');
};

(async function checkAuthStatus() {
    try {
        const response = await fetch('/auth/tg/status');
        if (!response.ok) throw new Error('Failed to check auth status');

        const data = await response.json();
        if (!data.authorized) {
            window.location.href = '/telegram_auth';
        }
    } catch (error) {
        console.error('Authorization check failed:', error);
        showTemporaryNotification('Error checking authorization status', 'error');
    }
})();

async function searchProfile() {
    const userId = document.getElementById('user-id').value;
    if (!userId) return;

    const loadingIndicator = document.getElementById('loadingIndicator');
    const results = document.getElementById('results');

    try {
        loadingIndicator.classList.remove('hidden');
        results.classList.add('hidden');

        const response = await fetch(`/api/telegram/search?user_id=${encodeURIComponent(userId)}`);
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.message || err.detail || `Search failed (HTTP ${response.status})`);
        }
        const data = await response.json();

        displayResults(data);
        results.classList.remove('hidden');
    } catch (error) {
        console.error('Error:', error);
        showTemporaryNotification(error.message || 'Search failed', 'error');
    } finally {
        loadingIndicator.classList.add('hidden');
    }
}

function displayResults(data) {
    const entriesContainer = document.getElementById('profile-entries');
    const photosContainer = document.getElementById('photos');

    entriesContainer.innerHTML = '';
    photosContainer.innerHTML = '';

    // Bot replies that weren't profile data (limits, nothing found...) and timeouts
    const notices = [];
    if (data.complete === false) notices.push('The bot did not finish within 60 seconds - results may be incomplete.');
    (data.notices || []).forEach(n => notices.push(n));
    if (notices.length) {
        entriesContainer.insertAdjacentHTML('beforeend', `
            <div class="bg-yellow-900/30 border border-yellow-700/60 rounded-lg p-4 text-sm text-yellow-100 space-y-2">
                ${notices.map(n => `<p class="whitespace-pre-wrap">${escapeHtml(n)}</p>`).join('')}
            </div>`);
    }
    if (!(data.entries || []).length && !notices.length) {
        entriesContainer.insertAdjacentHTML('beforeend', '<p class="text-gray-400">No profile history found.</p>');
    }

    // Field icons mapping
    const fieldIcons = {
        url: 'link',
        vk_id: 'fingerprint',
        full_name: 'user',
        first_name: 'user',
        last_name: 'user',
        gender: 'user',
        country: 'globe',
        hometown: 'home',
        city: 'map-pin',
        last_login: 'clock',
        device: 'smartphone',
        followers: 'users',
        university: 'graduation-cap',
        faculty: 'book-open',
        username: 'at-sign',
        marital_status: 'heart',
        normalized_name: 'user-check',
        education: 'book',
        avatar: 'image',
        birth_date: 'calendar',
        last_visit: 'clock'
    };

    // Display profile entries
    data.entries.forEach(entry => {
        const entryDiv = document.createElement('div');
        entryDiv.className = 'bg-gray-800 rounded-lg p-4 space-y-3';

        const headerHtml = `
            <div class="flex items-center justify-between border-b border-gray-700 pb-2 mb-3">
                <div class="flex items-center gap-4">
                    ${entry.avatar ? `
                        <img src="https://api.allorigins.win/raw?url=${encodeURIComponent(entry.avatar)}"
                             alt="Profile avatar" data-image-view="" data-image-title="Profile avatar"
                             class="w-12 h-12 rounded-full object-cover"
                             data-placeholder-size="w-12 h-12 rounded-full shrink-0" data-placeholder-icon-only onerror="imageLoadFailed(this)">`
                : '<div class="w-12 h-12 rounded-full bg-gray-700 flex items-center justify-center"><i data-lucide="user" class="w-6 h-6"></i></div>'
            }
                    <div>
                        <span class="font-semibold">${escapeHtml(entry.year_month || 'Unknown Date')}</span>
                        ${entry.full_name ? `<div class="text-sm text-gray-400">${escapeHtml(entry.full_name)}</div>` : ''}
                    </div>
                </div>
            </div>
        `;

        const fields = Object.entries(entry)
            .filter(([key, value]) => value && !['year_month', 'avatar', 'full_name'].includes(key))
            .map(([key, value]) => `
                <div class="flex items-center gap-3">
                    <div class="w-5 h-5 text-gray-400">
                        <i data-lucide="${fieldIcons[key] || 'circle'}"></i>
                    </div>
                    <span class="text-gray-400 text-sm">${escapeHtml(formatFieldName(key))}:</span>
                    ${key === 'url' ?
                    `<a href="${escapeAttr(safeUrl(value))}" target="_blank" rel="noopener noreferrer" class="text-sm text-blue-400 hover:text-blue-300 truncate">${escapeHtml(value)}</a>` :
                    `<span class="text-sm truncate">${key === 'vk_id' || key === 'username' ? pivotText('vk', value) : pivotField(key, value)}</span>`
                }
                </div>
            `).join('');

        entryDiv.innerHTML = `
            ${headerHtml}
            <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
                ${fields}
            </div>
        `;
        entriesContainer.appendChild(entryDiv);
    });

    // Display photos with proxy
    data.photos.forEach(photoUrl => {
        const photoDiv = document.createElement('div');
        photoDiv.className = 'relative group';
        photoDiv.innerHTML = `
            <button type="button" data-image-view="https://api.allorigins.win/raw?url=${encodeURIComponent(photoUrl)}" data-image-title="Profile photo" class="block w-full">
                <img src="https://api.allorigins.win/raw?url=${encodeURIComponent(photoUrl)}"
                     alt="Profile photo"
                     class="w-full h-48 object-cover rounded-lg transition-transform duration-200 group-hover:scale-105"
                     data-placeholder-size="w-full h-48 rounded-lg" onerror="imageLoadFailed(this)">
            </button>
        `;
        photosContainer.appendChild(photoDiv);
    });

    // Reinitialize Lucide icons for the new content
    lucide.createIcons();
}

function formatFieldName(key) {
    return key
        .split('_')
        .map(word => word.charAt(0).toUpperCase() + word.slice(1))
        .join(' ');
}

// Handle Enter key in search input
const userIdInput = document.getElementById('user-id');
if (userIdInput) {
    userIdInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            searchProfile();
        }
    });
}
