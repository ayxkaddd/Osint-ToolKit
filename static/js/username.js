class OSINTSearch {
    constructor() {
        this.eventSource = null;
        this.searchActive = false;
        this.results = [];
        this.resultsByCategory = {};
        this.stats = {
            scanned: 0,
            total: 0,
            found: 0
        };

        this.initializeElements();
        this.bindEvents();
    }

    initializeElements() {
        this.elements = {
            form: document.getElementById('searchForm'),
            searchBtn: document.getElementById('searchBtn'),
            stopBtn: document.getElementById('stopBtn'),
            progressSection: document.getElementById('progressSection'),
            progressBar: document.getElementById('progressBar'),
            progressText: document.getElementById('progressText'),
            progressPercent: document.getElementById('progressPercent'),
            sourcesScanned: document.getElementById('sourcesScanned'),
            usernamesFound: document.getElementById('usernamesFound'),
            totalAccounts: document.getElementById('totalAccounts'),
            currentlyChecking: document.getElementById('currentlyChecking'),
            currentSite: document.getElementById('currentSite'),
            resultsContainer: document.getElementById('resultsContainer'),
            categoryStats: document.getElementById('categoryStats'),
            categoryStatsGrid: document.getElementById('categoryStatsGrid'),
            filterSection: document.getElementById('filterSection'),
            categoryFilter: document.getElementById('categoryFilter')
        };
    }

    bindEvents() {
        if (this.elements.form) {
            this.elements.form.addEventListener('submit', (e) => {
                e.preventDefault();
                this.startSearch();
            });
        }

        if (this.elements.stopBtn) {
            this.elements.stopBtn.addEventListener('click', () => {
                this.stopSearch();
            });
        }

        if (this.elements.categoryFilter) {
            this.elements.categoryFilter.addEventListener('change', (e) => {
                this.filterByCategory(e.target.value);
            });
        }
    }

    getPlatformIcon(siteName, category) {
        const name = siteName.toLowerCase();

        // Social platforms
        if (name.includes('github')) return { class: 'github-green', icon: 'GH' };
        if (name.includes('twitter') || name.includes('x.com')) return { class: 'twitter-blue', icon: '𝕏' };
        if (name.includes('instagram')) return { class: 'instagram-gradient', icon: 'IG' };
        if (name.includes('linkedin')) return { class: 'linkedin-blue', icon: 'in' };
        if (name.includes('reddit')) return { class: 'reddit-orange', icon: 'R' };
        if (name.includes('discord')) return { class: 'discord-purple', icon: 'D' };
        if (name.includes('telegram')) return { class: 'telegram-blue', icon: 'TG' };
        if (name.includes('snapchat')) return { class: 'snapchat-yellow', icon: 'SC' };
        if (name.includes('mastodon')) return { class: 'mastodon-purple', icon: 'M' };

        // Gaming platforms
        if (name.includes('steam')) return { class: 'steam-blue', icon: 'ST' };
        if (name.includes('epic')) return { class: 'epic-black', icon: 'EG' };
        if (name.includes('twitch')) return { class: 'twitch-purple', icon: 'TW' };

        // Media platforms
        if (name.includes('spotify')) return { class: 'spotify-green', icon: '♪' };
        if (name.includes('youtube')) return { class: 'youtube-red', icon: 'YT' };
        if (name.includes('tiktok')) return { class: 'tiktok-black', icon: 'TT' };
        if (name.includes('pinterest')) return { class: 'pinterest-red', icon: 'P' };
        if (name.includes('vimeo')) return { class: 'vimeo-blue', icon: 'V' };

        // Developer platforms
        if (name.includes('gitlab')) return { class: 'gitlab-orange', icon: 'GL' };
        if (name.includes('stackoverflow') || name.includes('stack overflow')) return { class: 'stackoverflow-orange', icon: 'SO' };

        // Other platforms
        if (name.includes('cashapp')) return { class: 'cashapp-green', icon: '$' };
        if (name.includes('patreon')) return { class: 'patreon-orange', icon: 'PT' };

        const firstLetter = siteName.charAt(0).toUpperCase();
        const secondLetter = siteName.length > 1 ? siteName.charAt(1).toUpperCase() : '';

        return {
            class: 'bg-gray-600',
            icon: firstLetter + secondLetter
        };
    }

    startSearch() {
        if (this.searchActive) return;

        const username = document.getElementById('username').value.trim();
        if (!username) return;

        this.resetResults();
        this.showProgress();
        this.searchActive = true;
        this.elements.searchBtn.innerHTML = '<i class="fas fa-spinner fa-spin mr-2"></i>Searching...';
        this.elements.searchBtn.disabled = true;
        this.elements.stopBtn.classList.remove('hidden');

        const url = `/api/username/search/stream?username=${encodeURIComponent(username)}&include_duckduckgo=false&extract_profile=true`;

        this.eventSource = new EventSource(url);

        this.eventSource.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                this.handleEvent(data);
            } catch (error) {
                console.error('Error parsing event data:', error);
            }
        };

        this.eventSource.onerror = (error) => {
            console.error('EventSource error:', error);
            this.stopSearch();
        };
    }

    handleEvent(event) {
        switch (event.event_type) {
            case 'search_started':
                this.stats.total = event.data.total_sites;
                this.updateStats();
                break;

            case 'site_checking':
                this.showCurrentlyChecking(event.data.site_name);
                break;

            case 'site_result':
                if (event.data.status === 'found') {
                    this.handleFoundResult(event.data);
                }
                if (event.data.progress) {
                    this.updateProgress(event.data.progress);
                }
                break;

            case 'search_completed':
                this.handleSearchCompleted(event.data);
                break;
        }
    }

    showCurrentlyChecking(siteName) {
        this.elements.currentSite.textContent = siteName;
        this.elements.currentlyChecking.classList.remove('hidden');
    }

    handleFoundResult(data) {
        const result = {
            siteName: data.site_name,
            category: data.category,
            url: data.url,
            statusCode: data.status_code,
            profileData: data.profile_data,
            responseTime: data.response_time,
            checkedAt: data.checked_at
        };

        this.results.push(result);

        if (!this.resultsByCategory[result.category]) {
            this.resultsByCategory[result.category] = [];
        }
        this.resultsByCategory[result.category].push(result);

        this.addResultCard(result);
        this.stats.found++;
        this.updateStats();
        this.updateCategoryStats();
    }

    getCategorySection(category) {
        let section = document.getElementById(`category-${category}`);

        if (!section) {
            section = this.createCategorySection(category);
            this.elements.resultsContainer.appendChild(section);

            // Update filter dropdown
            this.updateCategoryFilter();
        }

        return section.querySelector('.category-grid');
    }

    createCategorySection(category) {
        const section = document.createElement('div');
        section.id = `category-${category}`;
        section.className = 'mb-8 fade-in';
        section.dataset.category = category;

        const categoryColor = this.getCategoryColor(category);

        section.innerHTML = `
            <div class="bg-[#1a1b26]/50 backdrop-blur-sm border border-[#24283b] rounded-xl overflow-hidden">
                <button class="category-header w-full p-4 flex items-center justify-between hover:bg-[#24283b]/30 transition-colors" data-category="${category}">
                    <div class="flex items-center space-x-3">
                        <div class="w-3 h-3 rounded-full ${categoryColor}"></div>
                        <h2 class="text-xl font-bold text-white capitalize">${category}</h2>
                        <span class="category-count px-2 py-1 bg-gray-700 rounded-full text-xs text-gray-300">0</span>
                    </div>
                    <i class="fas fa-chevron-down text-gray-400 transition-transform"></i>
                </button>
                <div class="category-content p-4">
                    <div class="category-grid grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                        <!-- Results will be inserted here -->
                    </div>
                </div>
            </div>
        `;

        // Add toggle functionality
        const header = section.querySelector('.category-header');
        const content = section.querySelector('.category-content');
        const icon = header.querySelector('i');

        header.addEventListener('click', () => {
            content.classList.toggle('collapsed');
            icon.classList.toggle('fa-chevron-down');
            icon.classList.toggle('fa-chevron-up');
        });

        return section;
    }

    getCategoryColor(category) {
        const colors = {
            'social': 'bg-blue-500',
            'gaming': 'bg-purple-500',
            'forums': 'bg-green-500',
            'developer': 'bg-orange-500',
            'marketplace': 'bg-yellow-500',
            'streaming': 'bg-pink-500',
            'adult': 'bg-red-500',
            'miscellaneous': 'bg-gray-500',
            'default': 'bg-gray-500'
        };

        return colors[category.toLowerCase()] || colors['default'];
    }

    addResultCard(result) {
        const categoryGrid = this.getCategorySection(result.category);
        const platformInfo = this.getPlatformIcon(result.siteName, result.category);
        const responseTime = result.responseTime ? Math.round(result.responseTime * 1000) : 0;
        const timeAgo = this.getTimeAgo(result.checkedAt);

        const keyInfo = this.extractKeyInfo(result.profileData);
        const hasProfileData = result.profileData && Object.keys(result.profileData).length > 0;

        const card = document.createElement('div');
        card.className = 'result-card bg-[#1a1b26]/50 backdrop-blur-sm border border-[#24283b] rounded-xl p-6 hover:border-purple-500/50 transition-all fade-in';

        card.innerHTML = `
            <div class="flex items-start justify-between mb-4">
                <div class="flex items-center space-x-3">
                    ${keyInfo.profileImage ? `
                        <img src="${keyInfo.profileImage}" alt="Profile" class="w-12 h-12 rounded-lg object-cover border border-gray-700">
                    ` : `
                        <div class="platform-icon ${platformInfo.class}">
                            ${platformInfo.icon}
                        </div>
                    `}
                    <div>
                        <h3 class="font-semibold text-white">${result.siteName}</h3>
                        ${keyInfo.username ? `
                            <div class="flex items-center space-x-2">
                                <div class="text-sm text-gray-400 font-mono">@${keyInfo.username}</div>
                                <button class="copy-username-btn text-gray-500 hover:text-purple-400 transition-colors" data-username="${keyInfo.username}" title="Copy username">
                                    <i class="fas fa-copy text-xs"></i>
                                </button>
                            </div>
                        ` : ''}
                    </div>
                </div>
                <div class="text-right">
                    <div class="text-xs text-gray-400">${timeAgo}</div>
                    <div class="text-xs text-gray-500">${responseTime}ms</div>
                </div>
            </div>

            <div class="space-y-3">
                ${keyInfo.fullName ? `
                    <div class="flex justify-between">
                        <span class="text-gray-400 text-sm">Full Name</span>
                        <span class="text-white text-sm">${this.escapeHtml(keyInfo.fullName)}</span>
                    </div>
                ` : ''}

                ${keyInfo.bio ? `
                    <div>
                        <span class="text-gray-400 text-sm block mb-1">Bio</span>
                        <p class="text-white text-sm line-clamp-2">${this.escapeHtml(keyInfo.bio)}</p>
                    </div>
                ` : ''}

                ${(keyInfo.followers !== null && keyInfo.followers > 0) || (keyInfo.following !== null && keyInfo.following > 0) ? `
                    <div class="flex justify-between">
                        ${keyInfo.followers !== null && keyInfo.followers > 0 ? `
                            <div>
                                <span class="text-gray-400 text-xs">Followers</span>
                                <div class="text-white text-sm font-semibold">${this.formatNumber(keyInfo.followers)}</div>
                            </div>
                        ` : ''}
                        ${keyInfo.following !== null && keyInfo.following > 0 ? `
                            <div>
                                <span class="text-gray-400 text-xs">Following</span>
                                <div class="text-white text-sm font-semibold">${this.formatNumber(keyInfo.following)}</div>
                            </div>
                        ` : ''}
                    </div>
                ` : ''}

                ${keyInfo.posts !== null && keyInfo.posts > 0 ? `
                    <div class="flex justify-between">
                        <span class="text-gray-400 text-sm">Posts</span>
                        <span class="text-white text-sm font-semibold">${this.formatNumber(keyInfo.posts)}</span>
                    </div>
                ` : ''}

                ${keyInfo.reputation !== null && keyInfo.reputation > 0 ? `
                    <div class="flex justify-between">
                        <span class="text-gray-400 text-sm">Reputation</span>
                        <span class="text-white text-sm font-semibold">${this.formatNumber(keyInfo.reputation)}</span>
                    </div>
                ` : ''}

                <!-- Display ALL numeric stats found in the profile data -->
                ${keyInfo.numericStats && keyInfo.numericStats.length > 0 ? `
                    <div class="grid grid-cols-2 gap-2">
                        ${keyInfo.numericStats.slice(0, 8).map(stat => `
                            <div class="bg-gray-800/30 rounded p-2">
                                <span class="text-gray-400 text-xs block">${stat.key}</span>
                                <span class="text-white text-sm font-semibold">${this.formatNumber(stat.value)}</span>
                            </div>
                        `).join('')}
                    </div>
                ` : ''}

                ${keyInfo.country || keyInfo.gender ? `
                    <div class="flex justify-between flex-wrap gap-2">
                        ${keyInfo.country ? `
                            <div class="flex items-center space-x-1">
                                <i class="fas fa-map-marker-alt text-gray-400 text-xs"></i>
                                <span class="text-white text-sm">${this.escapeHtml(keyInfo.country)}</span>
                            </div>
                        ` : ''}
                        ${keyInfo.gender ? `
                            <div class="flex items-center space-x-1">
                                <i class="fas fa-user text-gray-400 text-xs"></i>
                                <span class="text-white text-sm capitalize">${this.escapeHtml(keyInfo.gender)}</span>
                            </div>
                        ` : ''}
                    </div>
                ` : ''}

                <!-- Display social media profile links -->
                ${keyInfo.socialProfiles && Object.keys(keyInfo.socialProfiles).length > 0 ? `
                    <div>
                        <span class="text-gray-400 text-sm block mb-2">Social Profiles</span>
                        <div class="flex flex-wrap gap-2">
                            ${Object.entries(keyInfo.socialProfiles).map(([platform, handle]) => {
            const icons = {
                youtube: 'fab fa-youtube',
                twitter: 'fab fa-twitter',
                twitch: 'fab fa-twitch',
                instagram: 'fab fa-instagram',
                facebook: 'fab fa-facebook',
                tiktok: 'fab fa-tiktok',
                snapchat: 'fab fa-snapchat',
                linkedin: 'fab fa-linkedin',
                github: 'fab fa-github',
                gitlab: 'fab fa-gitlab'
            };
            const icon = icons[platform] || 'fas fa-link';
            return `
                                    <a href="https://${platform}.com/${handle}" target="_blank"
                                       class="flex items-center space-x-1 px-2 py-1 bg-gray-800/50 hover:bg-gray-700/50 rounded text-xs text-purple-400 hover:text-purple-300 transition-colors">
                                        <i class="${icon}"></i>
                                        <span>${this.escapeHtml(String(handle))}</span>
                                    </a>
                                `;
        }).join('')}
                        </div>
                    </div>
                ` : ''}

                ${keyInfo.website ? `
                    <div class="flex justify-between">
                        <span class="text-gray-400 text-sm">Website</span>
                        <a href="${keyInfo.website}" target="_blank" class="text-purple-400 hover:text-purple-300 text-sm truncate max-w-[200px]">${this.escapeHtml(keyInfo.website)}</a>
                    </div>
                ` : ''}

                ${keyInfo.createdAt ? `
                    <div class="flex justify-between">
                        <span class="text-gray-400 text-sm">Joined</span>
                        <span class="text-white text-sm">${keyInfo.createdAt}</span>
                    </div>
                ` : ''}

                ${keyInfo.lastActive ? `
                    <div class="flex justify-between">
                        <span class="text-gray-400 text-sm">Last Active</span>
                        <span class="text-white text-sm">${keyInfo.lastActive}</span>
                    </div>
                ` : ''}

                ${keyInfo.verified ? `
                    <div class="flex items-center space-x-2">
                        <i class="fas fa-check-circle text-blue-400"></i>
                        <span class="text-blue-400 text-sm">Verified Account</span>
                    </div>
                ` : ''}

                ${keyInfo.genres && keyInfo.genres.length > 0 ? `
                    <div>
                        <span class="text-gray-400 text-sm block mb-1">Genres</span>
                        <div class="flex flex-wrap gap-1">
                            ${keyInfo.genres.map(g => `<span class="px-2 py-0.5 bg-purple-900/30 text-purple-300 text-xs rounded">${this.escapeHtml(g)}</span>`).join('')}
                        </div>
                    </div>
                ` : ''}

                ${keyInfo.skills && keyInfo.skills.length > 0 ? `
                    <div>
                        <span class="text-gray-400 text-sm block mb-1">Skills</span>
                        <div class="flex flex-wrap gap-1">
                            ${keyInfo.skills.map(s => `<span class="px-2 py-0.5 bg-blue-900/30 text-blue-300 text-xs rounded">${this.escapeHtml(s)}</span>`).join('')}
                        </div>
                    </div>
                ` : ''}

                ${keyInfo.socialLinks && keyInfo.socialLinks.length > 0 ? `
                    <div>
                        <span class="text-gray-400 text-sm block mb-1">Social Links</span>
                        <div class="flex flex-wrap gap-2">
                            ${keyInfo.socialLinks.map(link => `
                                <a href="${link}" target="_blank" class="text-purple-400 hover:text-purple-300 text-xs">
                                    <i class="fas fa-external-link-alt"></i>
                                </a>
                            `).join('')}
                        </div>
                    </div>
                ` : ''}

                <!-- Display other simple fields (strings, booleans) -->
                ${keyInfo.otherFields && keyInfo.otherFields.length > 0 ? `
                    ${keyInfo.otherFields.slice(0, 5).map(field => `
                        <div class="flex justify-between">
                            <span class="text-gray-400 text-sm">${field.key}</span>
                            <span class="text-white text-sm">${typeof field.value === 'boolean' ? (field.value ? 'Yes' : 'No') : this.escapeHtml(String(field.value))}</span>
                        </div>
                    `).join('')}
                ` : ''}
            </div>

            ${hasProfileData ? `
                <div class="mt-4 pt-4 border-t border-gray-700">
                    <button class="expand-btn w-full text-purple-400 hover:text-purple-300 text-sm font-medium transition-colors flex items-center justify-center space-x-2">
                        <span>Expand Result</span>
                        <i class="fas fa-external-link-alt"></i>
                    </button>
                </div>
            ` : ''}

            <div class="flex justify-between items-center mt-4 pt-4 border-t border-gray-700">
                <a href="${result.url}" target="_blank"
                   class="text-purple-400 hover:text-purple-300 text-sm font-medium transition-colors flex items-center space-x-1">
                    <i class="fas fa-external-link-alt"></i>
                    <span>View Account</span>
                </a>
            </div>
        `;

        const copyUsernameBtn = card.querySelector('.copy-username-btn');
        if (copyUsernameBtn) {
            copyUsernameBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                const username = copyUsernameBtn.dataset.username;
                this.copyToClipboard(username, copyUsernameBtn);
            });
        }

        const expandBtn = card.querySelector('.expand-btn');
        if (expandBtn) {
            expandBtn.addEventListener('click', () => {
                this.openModal(result);
            });
        }

        categoryGrid.appendChild(card);

        // Update category count
        this.updateCategoryCount(result.category);
    }

    copyToClipboard(text, button) {
        navigator.clipboard.writeText(text).then(() => {
            const originalHTML = button.innerHTML;
            button.innerHTML = '<i class="fas fa-check text-xs"></i>';
            button.classList.add('text-green-400');

            setTimeout(() => {
                button.innerHTML = originalHTML;
                button.classList.remove('text-green-400');
            }, 1500);
        }).catch(err => {
            console.error('Failed to copy:', err);
        });
    }

    updateCategoryCount(category) {
        const section = document.getElementById(`category-${category}`);
        if (section) {
            const count = this.resultsByCategory[category].length;
            const countElement = section.querySelector('.category-count');
            if (countElement) {
                countElement.textContent = count;
            }
        }
    }

    updateCategoryStats() {
        const categories = Object.keys(this.resultsByCategory);

        if (categories.length > 0) {
            this.elements.categoryStats.classList.remove('hidden');
            this.elements.filterSection.classList.remove('hidden');

            this.elements.categoryStatsGrid.innerHTML = categories.map(category => {
                const count = this.resultsByCategory[category].length;
                const color = this.getCategoryColor(category);

                return `
                    <div class="flex items-center justify-between p-2 bg-gray-800/30 rounded">
                        <div class="flex items-center space-x-2">
                            <div class="w-2 h-2 rounded-full ${color}"></div>
                            <span class="text-xs text-gray-400 capitalize">${category}</span>
                        </div>
                        <span class="text-sm font-semibold text-white">${count}</span>
                    </div>
                `;
            }).join('');
        }
    }

    updateCategoryFilter() {
        const categories = Object.keys(this.resultsByCategory).sort();
        const currentValue = this.elements.categoryFilter.value;

        this.elements.categoryFilter.innerHTML = '<option value="all">All Categories</option>' +
            categories.map(category =>
                `<option value="${category}" ${currentValue === category ? 'selected' : ''}>${category.charAt(0).toUpperCase() + category.slice(1)}</option>`
            ).join('');
    }

    filterByCategory(category) {
        const sections = this.elements.resultsContainer.querySelectorAll('[data-category]');

        sections.forEach(section => {
            if (category === 'all' || section.dataset.category === category) {
                section.style.display = 'block';
            } else {
                section.style.display = 'none';
            }
        });
    }

    openModal(result) {
        const modal = document.createElement('div');
        modal.className = 'modal-overlay';
        modal.innerHTML = `
            <div class="modal-content">
                <div class="modal-header">
                    <div>
                        <h2 class="text-xl font-bold text-white">${result.siteName}</h2>
                        <p class="text-sm text-gray-400 mt-1">Full Profile Data</p>
                    </div>
                    <button class="close-modal text-gray-400 hover:text-white transition-colors">
                        <i class="fas fa-times text-xl"></i>
                    </button>
                </div>
                <div class="modal-body">
                    <pre class="text-sm text-gray-300 whitespace-pre-wrap break-words" id="modalContent">${this.renderFullProfileData(result.profileData)}</pre>
                </div>
                <div class="modal-footer">
                    <button class="copy-btn bg-purple-600 hover:bg-purple-700 text-white" data-format="json">
                        <i class="fas fa-copy mr-2"></i>Copy as JSON
                    </button>
                    <button class="copy-btn bg-blue-600 hover:bg-blue-700 text-white" data-format="text">
                        <i class="fas fa-copy mr-2"></i>Copy as Text
                    </button>
                </div>
            </div>
        `;

        document.body.appendChild(modal);

        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                document.body.removeChild(modal);
            }
        });

        modal.querySelector('.close-modal').addEventListener('click', () => {
            document.body.removeChild(modal);
        });

        modal.querySelectorAll('.copy-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const format = btn.dataset.format;
                let textToCopy = '';

                if (format === 'json') {
                    textToCopy = JSON.stringify(result.profileData, null, 2);
                } else {
                    textToCopy = this.convertToPlainText(result.profileData);
                }

                navigator.clipboard.writeText(textToCopy).then(() => {
                    const originalHTML = btn.innerHTML;
                    btn.innerHTML = '<i class="fas fa-check mr-2"></i>Copied!';
                    btn.classList.add('success');

                    setTimeout(() => {
                        btn.innerHTML = originalHTML;
                        btn.classList.remove('success');
                    }, 2000);
                });
            });
        });

        const escapeHandler = (e) => {
            if (e.key === 'Escape') {
                document.body.removeChild(modal);
                document.removeEventListener('keydown', escapeHandler);
            }
        };
        document.addEventListener('keydown', escapeHandler);
    }

    convertToPlainText(data, indent = 0) {
        let text = '';
        const spaces = '  '.repeat(indent);

        for (const [key, value] of Object.entries(data)) {
            if (value === null || value === undefined || value === '') continue;

            const formattedKey = key
                .replace(/_/g, ' ')
                .split(' ')
                .map(word => word.charAt(0).toUpperCase() + word.slice(1))
                .join(' ');

            text += this.renderValue(formattedKey, value, indent);
        }

        return text;
    }

    extractKeyInfo(profileData) {
        if (!profileData) return {};

        const info = {
            username: null,
            fullName: null,
            bio: null,
            profileImage: null,
            followers: null,
            following: null,
            posts: null,
            reputation: null,
            createdAt: null,
            lastActive: null,
            verified: null,
            genres: [],
            skills: [],
            country: null,
            gender: null,
            website: null,
            socialLinks: [],
            numericStats: [],
            otherFields: [],
            socialProfiles: {}
        };

        const usernameFields = ['username', 'user_name', 'userName', 'disqus_username',
            'imgur_username', 'name', 'handle', 'login', 'screen_name',
            'screenName', 'display', 'nickname', 'nick', 'account_name'];
        for (const field of usernameFields) {
            if (profileData[field]) {
                info.username = profileData[field];
                break;
            }
        }

        const nameFields = ['fullname', 'full_name', 'fullName', 'displayName',
            'display_name', 'realName', 'real_name', 'name'];
        for (const field of nameFields) {
            if (profileData[field] && profileData[field] !== info.username) {
                info.fullName = profileData[field];
                break;
            }
        }

        const bioFields = ['bio', 'description', 'about', 'aboutMe', 'about_me',
            'motto', 'statusMessage', 'status_message', 'blurb', 'note',
            'summary', 'headline', 'tagline'];
        for (const field of bioFields) {
            if (profileData[field]) {
                info.bio = profileData[field];
                break;
            }
        }

        const imageFields = ['profileImageUrl', 'profile_image_url', 'profilePic',
            'profile_pic', 'image', 'avatar', 'avatar_static',
            'avatar_url', 'icon_img', 'logo', 'logoUrl', 'pic_url',
            'photo', 'photo_url', 'picture'];
        for (const field of imageFields) {
            if (profileData[field]) {
                if (typeof profileData[field] === 'object' && profileData[field].url) {
                    info.profileImage = profileData[field].url;
                } else if (typeof profileData[field] === 'string') {
                    info.profileImage = profileData[field];
                }
                if (info.profileImage) break;
            }
        }

        const countryFields = ['country', 'location', 'city', 'place', 'nationality',
            'region', 'area', 'locale'];
        for (const field of countryFields) {
            if (profileData[field]) {
                if (typeof profileData[field] === 'object') {
                    info.country = profileData[field].name || profileData[field].code || null;
                } else {
                    info.country = profileData[field];
                }
                if (info.country) break;
            }
        }

        const genderFields = ['gender', 'genderVerbal', 'gender_verbal', 'sex'];
        for (const field of genderFields) {
            if (profileData[field]) {
                info.gender = profileData[field];
                break;
            }
        }

        const followerFields = ['follower_count', 'followers_count', 'followersCount',
            'followerCount', 'followers', 'subscriber_count',
            'subscribers', 'fans'];
        for (const field of followerFields) {
            if (profileData[field] !== undefined && profileData[field] !== null) {
                info.followers = parseInt(profileData[field]);
                break;
            }
        }
        if (profileData.counters && profileData.counters.followers !== undefined) {
            info.followers = parseInt(profileData.counters.followers);
        }
        if (profileData.stats && profileData.stats.followers) {
            if (typeof profileData.stats.followers === 'object' && profileData.stats.followers.value !== undefined) {
                info.followers = parseInt(profileData.stats.followers.value);
            } else {
                info.followers = parseInt(profileData.stats.followers);
            }
        }

        const followingFields = ['following_count', 'follows_count', 'followsCount',
            'followingCount', 'following', 'followeeCount',
            'followees', 'subscriptions'];
        for (const field of followingFields) {
            if (profileData[field] !== undefined && profileData[field] !== null) {
                info.following = parseInt(profileData[field]);
                break;
            }
        }
        if (profileData.counters && profileData.counters.following !== undefined) {
            info.following = parseInt(profileData.counters.following);
        }
        if (profileData.stats && profileData.stats.following) {
            if (typeof profileData.stats.following === 'object' && profileData.stats.following.value !== undefined) {
                info.following = parseInt(profileData.stats.following.value);
            } else {
                info.following = parseInt(profileData.stats.following);
            }
        }

        const postsFields = ['posts', 'post_count', 'postCount', 'statuses_count',
            'statusesCount', 'tweets', 'updates', 'contributions',
            'cloudcast_count', 'videos', 'photos'];
        for (const field of postsFields) {
            if (profileData[field] !== undefined && profileData[field] !== null) {
                info.posts = parseInt(profileData[field]);
                break;
            }
        }
        if (profileData.counters && profileData.counters.posts !== undefined) {
            info.posts = parseInt(profileData.counters.posts);
        }

        const reputationFields = ['reputation', 'karma', 'total_karma', 'points',
            'score', 'rating'];
        for (const field of reputationFields) {
            if (profileData[field] !== undefined && profileData[field] !== null) {
                info.reputation = parseInt(profileData[field]);
                break;
            }
        }
        if (profileData.data && profileData.data.total_karma !== undefined) {
            info.reputation = parseInt(profileData.data.total_karma);
        }

        const dateFields = ['created_at', 'createdAt', 'createdOn', 'created',
            'memberSince', 'member_since', 'createdDate', 'created_date',
            'joinedAt', 'joined_at', 'registered', 'signup_date'];
        for (const field of dateFields) {
            if (profileData[field]) {
                const date = this.parseDate(profileData[field]);
                if (date) {
                    info.createdAt = date;
                    break;
                }
            }
        }
        if (profileData.data && profileData.data.created_utc) {
            const date = new Date(profileData.data.created_utc * 1000);
            info.createdAt = date.toLocaleDateString();
        }

        const lastActiveFields = ['last_active', 'lastActive', 'last_seen', 'lastSeen',
            'updated_at', 'updatedAt', 'last_login', 'lastLogin'];
        for (const field of lastActiveFields) {
            if (profileData[field]) {
                const date = this.parseDate(profileData[field]);
                if (date) {
                    info.lastActive = date;
                    break;
                }
            }
        }

        const verifiedFields = ['verified', 'isVerified', 'is_verified',
            'is_twitter_verified', 'verified_account', 'badge'];
        for (const field of verifiedFields) {
            if (profileData[field] === true || profileData[field] === 'True' ||
                profileData[field] === 'true' || profileData[field] === 1) {
                info.verified = true;
                break;
            }
        }

        const websiteFields = ['website', 'url', 'homepage', 'blog', 'site', 'web'];
        for (const field of websiteFields) {
            if (profileData[field] && typeof profileData[field] === 'string' &&
                profileData[field].startsWith('http')) {
                info.website = profileData[field];
                break;
            }
        }

        const socialFields = ['social_links', 'socialLinks', 'links', 'urls'];
        for (const field of socialFields) {
            if (profileData[field]) {
                if (Array.isArray(profileData[field])) {
                    info.socialLinks = profileData[field].filter(link =>
                        typeof link === 'string' && link.startsWith('http')
                    );
                } else if (typeof profileData[field] === 'object') {
                    info.socialLinks = Object.values(profileData[field]).filter(link =>
                        typeof link === 'string' && link.startsWith('http')
                    );
                }
                if (info.socialLinks.length > 0) break;
            }
        }

        const socialPlatforms = ['youtube', 'twitter', 'twitch', 'instagram', 'facebook',
            'tiktok', 'snapchat', 'linkedin', 'github', 'gitlab'];
        for (const platform of socialPlatforms) {
            if (profileData[platform] && profileData[platform] !== null) {
                info.socialProfiles[platform] = profileData[platform];
            }
        }

        const alreadyCaptured = ['followers', 'following', 'posts', 'reputation'];
        const skipFields = [...usernameFields, ...nameFields, ...bioFields, ...imageFields,
        ...countryFields, ...genderFields, ...followerFields, ...followingFields,
        ...postsFields, ...reputationFields, ...dateFields, ...lastActiveFields,
        ...verifiedFields, ...websiteFields, ...socialFields, ...socialPlatforms,
            'data', 'counters', 'stats', 'picture', 'backgroundPicture', 'links'];

        for (const [key, value] of Object.entries(profileData)) {
            if (skipFields.includes(key) || typeof value === 'object') continue;

            if (typeof value === 'number' && !alreadyCaptured.includes(key)) {
                const formattedKey = key
                    .replace(/([A-Z])/g, ' $1')
                    .replace(/_/g, ' ')
                    .trim()
                    .split(' ')
                    .map(word => word.charAt(0).toUpperCase() + word.slice(1))
                    .join(' ');

                info.numericStats.push({ key: formattedKey, value: value });
            } else if ((typeof value === 'string' || typeof value === 'boolean') &&
                !key.toLowerCase().includes('id') &&
                !key.toLowerCase().includes('color') &&
                !key.toLowerCase().includes('col') &&
                value !== '' && value !== null) {
                const formattedKey = key
                    .replace(/([A-Z])/g, ' $1')
                    .replace(/_/g, ' ')
                    .trim()
                    .split(' ')
                    .map(word => word.charAt(0).toUpperCase() + word.slice(1))
                    .join(' ');

                info.otherFields.push({ key: formattedKey, value: value });
            }
        }

        return info;
    }

    parseDate(value) {
        if (!value) return null;

        if (typeof value === 'number') {
            const date = value > 10000000000 ? new Date(value) : new Date(value * 1000);
            if (!isNaN(date.getTime())) {
                return date.toLocaleDateString();
            }
        }

        if (typeof value === 'string') {
            const date = new Date(value);
            if (!isNaN(date.getTime())) {
                return date.toLocaleDateString();
            }
        }

        return null;
    }

    formatNumber(num) {
        if (num === null || num === undefined) return '0';
        if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
        if (num >= 1000) return (num / 1000).toFixed(1) + 'K';
        return num.toString();
    }

    renderFullProfileData(profileData) {
        if (!profileData || Object.keys(profileData).length === 0) return '';

        let html = '<div class="text-xs text-gray-400 mb-2 font-semibold">Full Profile Data:</div>';

        for (const [key, value] of Object.entries(profileData)) {
            if (value === null || value === undefined || value === '') continue;

            const formattedKey = key
                .replace(/_/g, ' ')
                .split(' ')
                .map(word => word.charAt(0).toUpperCase() + word.slice(1))
                .join(' ');

            html += this.renderValue(formattedKey, value);
        }

        return html;
    }

    renderValue(key, value, indent = 0) {
        const indentClass = indent > 0 ? `ml-${indent * 4}` : '';
        let html = '';

        if (value === null || value === undefined || value === '') {
            return '';
        }

        if (Array.isArray(value)) {
            if (value.length === 0) return '';

            html += `
                <div class="${indentClass} mb-2">
                    <span class="text-gray-400 text-sm font-medium">${key}:</span>
            `;

            value.forEach((item, index) => {
                if (typeof item === 'object' && item !== null) {
                    html += `<div class="ml-4 mt-1 p-2 bg-gray-800/50 rounded border border-gray-700">`;
                    for (const [subKey, subValue] of Object.entries(item)) {
                        html += this.renderValue(subKey, subValue, indent + 1);
                    }
                    html += `</div>`;
                } else {
                    html += `<div class="ml-4 text-white text-sm">${this.escapeHtml(String(item))}</div>`;
                }
            });

            html += `</div>`;
            return html;
        }

        if (typeof value === 'object' && value !== null) {
            const entries = Object.entries(value);
            if (entries.length === 0) return '';

            html += `
                <div class="${indentClass} mb-2">
                    <span class="text-gray-400 text-sm font-medium">${key}:</span>
                    <div class="ml-4 mt-1 p-2 bg-gray-800/50 rounded border border-gray-700">
            `;

            for (const [subKey, subValue] of entries) {
                html += this.renderValue(subKey, subValue, indent + 1);
            }

            html += `</div></div>`;
            return html;
        }

        if (typeof value === 'string' && (value.startsWith('http://') || value.startsWith('https://'))) {
            return `
                <div class="${indentClass} flex justify-between items-start gap-4 mb-2">
                    <span class="text-gray-400 text-sm whitespace-nowrap">${key}</span>
                    <a href="${value}" target="_blank" class="text-purple-400 hover:text-purple-300 hover:underline text-sm text-right break-all">${this.truncateUrl(value)}</a>
                </div>
            `;
        }

        if (typeof value === 'boolean' || value === 'True' || value === 'False') {
            const boolValue = value === true || value === 'True';
            return `
                <div class="${indentClass} flex justify-between items-start gap-4 mb-2">
                    <span class="text-gray-400 text-sm whitespace-nowrap">${key}</span>
                    <span class="px-2 py-0.5 rounded ${boolValue ? 'bg-green-900 text-green-300' : 'bg-red-900 text-red-300'} text-xs">${boolValue ? 'Yes' : 'No'}</span>
                </div>
            `;
        }

        if (typeof value === 'string' && (value.match(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/) || value.match(/^\d{4}-\d{2}-\d{2}/))) {
            const date = new Date(value);
            if (!isNaN(date.getTime())) {
                const formattedValue = date.toLocaleDateString() + (value.includes('T') ? ' ' + date.toLocaleTimeString() : '');
                return `
                    <div class="${indentClass} flex justify-between items-start gap-4 mb-2">
                        <span class="text-gray-400 text-sm whitespace-nowrap">${key}</span>
                        <span class="text-white text-sm text-right">${formattedValue}</span>
                    </div>
                `;
            }
        }

        return `
            <div class="${indentClass} flex justify-between items-start gap-4 mb-2">
                <span class="text-gray-400 text-sm whitespace-nowrap">${key}</span>
                <span class="text-white text-sm text-right break-words">${this.escapeHtml(String(value))}</span>
            </div>
        `;
    }

    truncateUrl(url) {
        if (url.length <= 40) return url;
        return url.substring(0, 37) + '...';
    }

    escapeHtml(text) {
        const map = {
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#039;'
        };
        return text.replace(/[&<>"']/g, m => map[m]);
    }

    getTimeAgo(timestamp) {
        const now = new Date();
        const time = new Date(timestamp);
        const diffInSeconds = Math.floor((now - time) / 1000);

        if (diffInSeconds < 60) return 'Just now';
        if (diffInSeconds < 3600) return `${Math.floor(diffInSeconds / 60)}m ago`;
        if (diffInSeconds < 86400) return `${Math.floor(diffInSeconds / 3600)}h ago`;
        return time.toLocaleDateString();
    }

    updateProgress(progress) {
        this.stats.scanned = progress.checked;
        const percentage = progress.percentage;

        this.elements.progressBar.style.width = `${percentage}%`;
        this.elements.progressText.textContent = `${progress.checked} / ${progress.total}`;
        this.elements.progressPercent.textContent = `${Math.round(percentage)}%`;

        this.updateStats();
        this.elements.currentlyChecking.classList.add('hidden');
    }

    updateStats() {
        this.elements.sourcesScanned.textContent = this.stats.scanned;
        this.elements.usernamesFound.textContent = this.stats.found;
        this.elements.totalAccounts.textContent = this.stats.found;
    }

    showProgress() {
        this.elements.progressSection.classList.remove('hidden');
    }

    resetResults() {
        this.results = [];
        this.resultsByCategory = {};
        this.stats = { scanned: 0, total: 0, found: 0 };
        this.elements.resultsContainer.innerHTML = '';
        this.elements.currentlyChecking.classList.add('hidden');
        this.elements.categoryStats.classList.add('hidden');
        this.elements.filterSection.classList.add('hidden');
        this.updateStats();

        this.elements.progressBar.style.width = '0%';
        this.elements.progressText.textContent = '0 / 0';
        this.elements.progressPercent.textContent = '0%';
    }

    handleSearchCompleted(data) {
        console.log('Search completed:', data);
        this.stopSearch();
    }

    stopSearch() {
        if (this.eventSource) {
            this.eventSource.close();
            this.eventSource = null;
        }

        this.searchActive = false;
        this.elements.searchBtn.disabled = false;
        this.elements.searchBtn.innerHTML = '<i class="fas fa-search mr-2"></i>Search Username';
        this.elements.stopBtn.classList.add('hidden');
        this.elements.currentlyChecking.classList.add('hidden');
    }
}

document.addEventListener('DOMContentLoaded', () => {
    window.osintSearch = new OSINTSearch();

    window.loadResultIntoView = function (data) {
        if (!window.osintSearch) return;

        const search = window.osintSearch;
        search.resetResults();

        // Update stats
        if (data.stats) {
            search.stats.total = data.stats.total || 0;
            search.stats.scanned = data.stats.scanned || 0;
            search.updateStats();
        }

        // Load results
        if (data.results && Array.isArray(data.results)) {
            data.results.forEach(result => {
                if (result.status === 'found') {
                    search.handleFoundResult(result);
                }
            });
        }

        // Show results section
        search.elements.resultsContainer.classList.remove('hidden');
        search.elements.categoryStats.classList.remove('hidden');
        search.elements.filterSection.classList.remove('hidden');
    };
});
