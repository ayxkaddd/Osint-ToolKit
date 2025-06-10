lucide.createIcons();

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
            throw new Error('Search failed');
        }
        const data = await response.json();

        displayResults(data);
        results.classList.remove('hidden');
    } catch (error) {
        console.error('Error:', error);
        showTemporaryNotification('Search failed. Please try again.', 'error');
    } finally {
        loadingIndicator.classList.add('hidden');
    }
}

function displayResults(data) {
    const entriesContainer = document.getElementById('profile-entries');
    const photosContainer = document.getElementById('photos');

    entriesContainer.innerHTML = '';
    photosContainer.innerHTML = '';

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

    data.entries.forEach(entry => {
        const entryDiv = document.createElement('div');
        entryDiv.className = 'bg-gray-800 rounded-lg p-4 space-y-3';

        const headerHtml = `
            <div class="flex items-center justify-between border-b border-gray-700 pb-2 mb-3">
                <div class="flex items-center gap-4">
                    ${entry.avatar ? `
                        <img src="https://api.allorigins.win/raw?url=${encodeURIComponent(entry.avatar)}"
                             alt="Profile avatar"
                             class="w-12 h-12 rounded-full object-cover"
                             onerror="this.src='data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' viewBox=\'0 0 24 24\' fill=\'none\' stroke=\'%236b7280\' stroke-width=\'2\'%3E%3Cpath d=\'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0z\'/%3E%3Cpath d=\'M9 10h.01\'/%3E%3Cpath d=\'M15 10h.01\'/%3E%3Cpath d=\'M9.5 15a3.5 3.5 0 0 0 5 0\'/%3E%3C/svg%3E'">`
                        : '<div class="w-12 h-12 rounded-full bg-gray-700 flex items-center justify-center"><i data-lucide="user" class="w-6 h-6"></i></div>'
                    }
                    <div>
                        <span class="font-semibold">${entry.year_month || 'Unknown Date'}</span>
                        ${entry.full_name ? `<div class="text-sm text-gray-400">${entry.full_name}</div>` : ''}
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
                    <span class="text-gray-400 text-sm">${formatFieldName(key)}:</span>
                    ${key === 'url' ?
                        `<a href="${value}" target="_blank" class="text-sm text-blue-400 hover:text-blue-300 truncate">${value}</a>` :
                        `<span class="text-sm truncate">${value}</span>`
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

    data.photos.forEach(photoUrl => {
        const photoDiv = document.createElement('div');
        photoDiv.className = 'relative group';
        photoDiv.innerHTML = `
            <a href="${photoUrl}" target="_blank" class="block">
                <img src="https://api.allorigins.win/raw?url=${encodeURIComponent(photoUrl)}"
                     alt="Profile photo"
                     class="w-full h-48 object-cover rounded-lg transition-transform duration-200 group-hover:scale-105"
                     onerror="this.src='data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' viewBox=\'0 0 24 24\' fill=\'none\' stroke=\'%236b7280\' stroke-width=\'2\'%3E%3Cpath d=\'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0z\'/%3E%3Cpath d=\'M9 10h.01\'/%3E%3Cpath d=\'M15 10h.01\'/%3E%3Cpath d=\'M9.5 15a3.5 3.5 0 0 0 5 0\'/%3E%3C/svg%3E'">
            </a>
        `;
        photosContainer.appendChild(photoDiv);
    });

    lucide.createIcons();
}

function formatFieldName(key) {
    return key
        .split('_')
        .map(word => word.charAt(0).toUpperCase() + word.slice(1))
        .join(' ');
}

function showTemporaryNotification(message, type = 'error') {
    const notification = document.createElement('div');
    const bgColor = type === 'success' ? 'bg-green-500' : 'bg-red-500';
    notification.className = `fixed bottom-4 right-4 ${bgColor} text-white px-6 py-3 rounded-lg shadow-lg transform transition-all duration-300 translate-y-full opacity-0`;
    notification.innerHTML = `
        <div class="flex items-center space-x-2">
            <i class="fas ${type === 'success' ? 'fa-check-circle' : 'fa-exclamation-circle'}"></i>
            <span>${message}</span>
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
}

document.getElementById('user-id').addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
        searchProfile();
    }
});