class OSINTSearch {
    constructor() {
        this.eventSource = null;
        this.searchActive = false;
        this.results = [];
        this.resultsByCategory = {};
        this.viewMode = 'flat';
        this.activeCategory = 'all';
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
            resultsMasonry: document.getElementById('resultsMasonry'),
            groupedResults: document.getElementById('groupedResults'),
            categoryStats: document.getElementById('categoryStats'),
            categoryStatsGrid: document.getElementById('categoryStatsGrid'),
            filterSection: document.getElementById('filterSection'),
            categoryFilter: document.getElementById('categoryFilter'),
            flatViewBtn: document.getElementById('flatViewBtn'),
            groupedViewBtn: document.getElementById('groupedViewBtn')
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

        if (this.elements.flatViewBtn) {
            this.elements.flatViewBtn.addEventListener('click', () => {
                this.switchView('flat');
            });
        }

        if (this.elements.groupedViewBtn) {
            this.elements.groupedViewBtn.addEventListener('click', () => {
                this.switchView('grouped');
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

        const username = document.getElementById('usernameSearchInput').value.trim();
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

            case 'profile_extracted':
                this.handleProfileExtracted(event.data);
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
        const card = this.createResultCard(result);

        if (this.viewMode === 'grouped') {
            const group = this.getGroupedCategory(result.category);
            group.querySelector('.username-category-results').appendChild(card);
            this.updateGroupedCategoryCount(result.category);
            this.filterByCategory(this.activeCategory);
        } else {
            this.elements.resultsMasonry.appendChild(card);
        }
    }

    replaceResultCard(result) {
        const existingCard = this.findResultCard(result);
        const newCard = this.createResultCard(result);
        newCard.classList.remove('fade-in');

        if (existingCard) {
            existingCard.replaceWith(newCard);
            return;
        }

        this.addResultCard(result);
    }

    findResultCard(result) {
        const cards = this.elements.resultsContainer.querySelectorAll('.username-result-card');
        return Array.from(cards).find(card =>
            card.dataset.resultUrl === result.url &&
            card.dataset.siteName === result.siteName
        );
    }

    createResultCard(result) {
        const platformInfo = this.getPlatformIcon(result.siteName, result.category);
        const responseTime = result.responseTime ? Math.round(result.responseTime * 1000) : 0;
        const timeAgo = this.getTimeAgo(result.checkedAt);
        const keyInfo = this.extractKeyInfo(result.profileData);
        const hasProfileData = result.profileData && Object.keys(result.profileData).length > 0;
        const metaRows = this.getCompactRows(keyInfo);
        const domain = this.getDomainFromUrl(result.url);
        const faviconUrl = domain ? this.getFaviconUrl(domain) : '';
        const profileImageUrl = keyInfo.profileImage ? this.getAbsoluteUrl(keyInfo.profileImage) : '';
        const reverseSearchLinks = profileImageUrl ? this.getReverseImageSearchLinks(profileImageUrl) : [];

        const card = document.createElement('div');
        card.className = `result-card username-result-card fade-in${profileImageUrl ? ' has-profile-image' : ''}`;
        card.dataset.resultUrl = result.url;
        card.dataset.siteName = result.siteName;
        card.dataset.category = result.category;

        card.innerHTML = `
            <div class="username-card-header">
                <div class="username-card-heading">
                    <div class="username-site-mark">
                        ${faviconUrl ? `
                            <img src="${this.escapeHtml(faviconUrl)}" alt="" onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';">
                            <div class="platform-icon ${platformInfo.class} username-site-mark-fallback">
                                ${this.escapeHtml(platformInfo.icon)}
                            </div>
                        ` : `
                            <div class="platform-icon ${platformInfo.class}">
                                ${this.escapeHtml(platformInfo.icon)}
                            </div>
                        `}
                    </div>
                    <div class="username-card-title">
                        <h3 title="${this.escapeHtml(result.siteName)}">${this.escapeHtml(result.siteName)}</h3>
                        <span>${this.escapeHtml(result.category || 'unknown')}</span>
                    </div>
                </div>
                ${profileImageUrl ? `
                    <div class="username-card-media">
                        <button type="button" class="username-avatar-preview-btn" data-image-url="${this.escapeHtml(profileImageUrl)}" data-site-name="${this.escapeHtml(result.siteName)}" title="Preview profile picture">
                            <img src="${this.escapeHtml(keyInfo.profileImage)}" alt="" class="username-card-avatar" onerror="this.closest('.username-result-card').classList.remove('has-profile-image'); this.closest('.username-card-media').style.display='none';">
                        </button>
                        <div class="username-reverse-search" aria-label="Reverse image search">
                            ${reverseSearchLinks.map(link => `
                                <a href="${this.escapeHtml(link.url)}" target="_blank" rel="noopener noreferrer" title="${this.escapeHtml(link.label)} reverse image search">
                                    <i class="${this.escapeHtml(link.icon)}"></i>
                                </a>
                            `).join('')}
                        </div>
                    </div>
                ` : ''}
            </div>

            ${keyInfo.username ? `
                <div class="username-handle-row">
                    <span title="@${this.escapeHtml(String(keyInfo.username))}">@${this.escapeHtml(String(keyInfo.username))}</span>
                    <button class="copy-username-btn" data-username="${this.escapeHtml(String(keyInfo.username))}" title="Copy username">
                        <i class="fas fa-copy"></i>
                    </button>
                </div>
            ` : ''}

            <div class="username-card-content">
                ${keyInfo.bio ? `
                    <p class="username-card-bio">${this.escapeHtml(String(keyInfo.bio))}</p>
                ` : ''}

                ${metaRows.map(row => `
                    <div class="username-data-row">
                        <strong>${this.escapeHtml(row.label)}</strong>
                        <span title="${this.escapeHtml(String(row.value))}">${this.escapeHtml(String(row.value))}</span>
                    </div>
                `).join('')}

                ${keyInfo.numericStats && keyInfo.numericStats.length > 0 ? `
                    <div class="username-mini-stats">
                        ${keyInfo.numericStats.slice(0, 6).map(stat => `
                            <div>
                                <span>${this.escapeHtml(stat.key)}</span>
                                <strong>${this.escapeHtml(this.formatFieldValue(stat.rawKey || stat.key, stat.value, { compactCounts: true }))}</strong>
                            </div>
                        `).join('')}
                    </div>
                ` : ''}

                ${keyInfo.socialLinks && keyInfo.socialLinks.length > 0 ? `
                    <div class="username-link-strip">
                        ${keyInfo.socialLinks.slice(0, 5).map(link => `
                            <a href="${this.escapeHtml(link)}" target="_blank" title="${this.escapeHtml(link)}">
                                <i class="fas fa-link"></i>
                            </a>
                        `).join('')}
                    </div>
                ` : ''}
            </div>

            <div class="username-card-actions">
                <a href="${this.escapeHtml(result.url)}" target="_blank" title="${this.escapeHtml(result.url)}">
                    <i class="fas fa-external-link-alt"></i>
                    <span>View</span>
                </a>
                ${hasProfileData ? `
                    <button class="expand-btn">
                        <i class="fas fa-code"></i>
                        <span>Data</span>
                    </button>
                ` : ''}
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

        const avatarPreviewBtn = card.querySelector('.username-avatar-preview-btn');
        if (avatarPreviewBtn) {
            avatarPreviewBtn.addEventListener('click', () => {
                this.openImagePreview(avatarPreviewBtn.dataset.imageUrl, avatarPreviewBtn.dataset.siteName);
            });
        }

        return card;
    }

    getDomainFromUrl(url) {
        try {
            return new URL(url, window.location.origin).hostname.replace(/^www\./, '');
        } catch (error) {
            return '';
        }
    }

    getFaviconUrl(domain) {
        return `https://www.google.com/s2/favicons?domain=${encodeURIComponent(domain)}&sz=128`;
    }

    getAbsoluteUrl(url) {
        try {
            return new URL(url, window.location.href).href;
        } catch (error) {
            return url;
        }
    }

    getReverseImageSearchLinks(imageUrl) {
        const encodedUrl = encodeURIComponent(imageUrl);
        return [
            {
                label: 'Google',
                icon: 'fab fa-google',
                url: `https://lens.google.com/uploadbyurl?url=${encodedUrl}`
            },
            {
                label: 'Yandex',
                icon: 'fas fa-search',
                url: `https://yandex.com/images/search?rpt=imageview&url=${encodedUrl}`
            }
        ];
    }

    openImagePreview(imageUrl, siteName) {
        if (!imageUrl) return;

        const modal = document.createElement('div');
        modal.className = 'modal-overlay username-image-preview-overlay';
        modal.innerHTML = `
            <div class="username-image-preview-card">
                <div class="username-image-preview-header">
                    <div>
                        <h2>${this.escapeHtml(siteName || 'Profile picture')}</h2>
                        <p>Profile picture preview</p>
                    </div>
                    <button type="button" class="close-modal" title="Close preview">
                        <i class="fas fa-times"></i>
                    </button>
                </div>
                <div class="username-image-preview-body">
                    <img src="${this.escapeHtml(imageUrl)}" alt="" onerror="this.closest('.username-image-preview-body').innerHTML='<span>Image could not be loaded.</span>';">
                </div>
            </div>
        `;

        const closeModal = () => {
            if (modal.parentNode) {
                document.body.removeChild(modal);
            }
            document.removeEventListener('keydown', escapeHandler);
        };

        const escapeHandler = (e) => {
            if (e.key === 'Escape') {
                closeModal();
            }
        };

        document.body.appendChild(modal);
        document.addEventListener('keydown', escapeHandler);

        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                closeModal();
            }
        });

        modal.querySelector('.close-modal').addEventListener('click', closeModal);
    }

    getCompactRows(keyInfo) {
        const rows = [];
        const add = (label, value) => {
            if (value !== null && value !== undefined && value !== '') {
                rows.push({ label, value });
            }
        };

        add('Name', keyInfo.fullName);
        add('Followers', keyInfo.followers ? this.formatNumber(keyInfo.followers) : null);
        add('Following', keyInfo.following ? this.formatNumber(keyInfo.following) : null);
        add('Posts', keyInfo.posts ? this.formatNumber(keyInfo.posts) : null);
        add('Reputation', keyInfo.reputation ? this.formatNumber(keyInfo.reputation) : null);
        add('Country', keyInfo.country);
        add('Gender', keyInfo.gender);
        add('Website', keyInfo.website);
        add('Joined', keyInfo.createdAt);
        add('Active', keyInfo.lastActive);

        if (keyInfo.verified) add('Verified', 'Yes');
        if (keyInfo.otherFields) {
            keyInfo.otherFields.slice(0, Math.max(0, 6 - rows.length)).forEach(field => {
                add(field.key, this.formatFieldValue(field.rawKey || field.key, field.value));
            });
        }

        return rows.slice(0, 8);
    }

    handleProfileExtracted(data) {
        const result = this.results.find(item =>
            item.url === data.url && item.siteName === data.site_name
        );

        if (!result) return;

        result.profileData = data.profile_data;
        this.replaceResultCard(result);
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
        const section = Array.from(this.elements.groupedResults.querySelectorAll('[data-category]'))
            .find(item => item.dataset.category === category);
        if (section) {
            const count = this.resultsByCategory[category].length;
            const countElement = section.querySelector('.category-count');
            if (countElement) {
                countElement.textContent = count;
            }
        }
    }

    updateGroupedCategoryCount(category) {
        this.updateCategoryCount(category);
    }

    updateCategoryStats() {
        const categories = Object.keys(this.resultsByCategory);

        if (categories.length > 0) {
            this.elements.categoryStats.classList.remove('hidden');
            this.elements.filterSection.classList.remove('hidden');

            this.elements.categoryStatsGrid.innerHTML = categories.map(category => {
                const count = this.resultsByCategory[category].length;
                return `
                    <button type="button" class="username-category-pill" data-category="${this.escapeHtml(category)}">
                        <span>${this.escapeHtml(category)}</span>
                        <strong>${count}</strong>
                    </button>
                `;
            }).join('');

            this.elements.categoryStatsGrid.querySelectorAll('.username-category-pill').forEach(button => {
                button.addEventListener('click', () => {
                    this.switchView('grouped');
                    this.filterByCategory(button.dataset.category);
                });
            });

            this.updateCategoryFilter();
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
        this.activeCategory = category;
        const sections = this.elements.groupedResults.querySelectorAll('[data-category]');

        sections.forEach(section => {
            if (category === 'all' || section.dataset.category === category) {
                section.style.display = 'block';
            } else {
                section.style.display = 'none';
            }
        });
    }

    switchView(viewMode) {
        this.viewMode = viewMode;
        this.elements.flatViewBtn.classList.toggle('active', viewMode === 'flat');
        this.elements.groupedViewBtn.classList.toggle('active', viewMode === 'grouped');
        this.elements.categoryFilter.classList.toggle('hidden', viewMode !== 'grouped');
        this.elements.resultsMasonry.classList.toggle('hidden', viewMode !== 'flat');
        this.elements.groupedResults.classList.toggle('hidden', viewMode !== 'grouped');
        this.renderResults();
    }

    renderResults() {
        if (!this.elements.resultsMasonry || !this.elements.groupedResults) return;

        this.elements.resultsMasonry.innerHTML = '';
        this.elements.groupedResults.innerHTML = '';

        if (this.viewMode === 'grouped') {
            Object.keys(this.resultsByCategory).sort().forEach(category => {
                const section = this.createGroupedCategory(category);
                const grid = section.querySelector('.username-category-results');
                this.resultsByCategory[category].forEach(result => {
                    grid.appendChild(this.createResultCard(result));
                });
                this.elements.groupedResults.appendChild(section);
            });
            this.filterByCategory(this.activeCategory);
        } else {
            this.results.forEach(result => {
                this.elements.resultsMasonry.appendChild(this.createResultCard(result));
            });
        }
    }

    getGroupedCategory(category) {
        let section = Array.from(this.elements.groupedResults.querySelectorAll('[data-category]'))
            .find(item => item.dataset.category === category);
        if (!section) {
            section = this.createGroupedCategory(category);
            this.elements.groupedResults.appendChild(section);
        }
        return section;
    }

    createGroupedCategory(category) {
        const section = document.createElement('section');
        section.className = 'username-category-section fade-in';
        section.dataset.category = category;
        section.innerHTML = `
            <div class="username-category-heading">
                <h2>${this.escapeHtml(category)}</h2>
                <span class="category-count">${this.resultsByCategory[category]?.length || 0}</span>
            </div>
            <div class="username-category-results"></div>
        `;
        return section;
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
            'memberSince', 'member_since', 'createdDate', 'created_date', 'joined',
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
            'updated_at', 'updatedAt', 'last_login', 'lastLogin', 'last_online',
            'lastOnline', 'lastOnlineAt', 'online_at'];
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
                const formattedKey = this.formatFieldLabel(key);

                if (this.shouldCompactNumber(key)) {
                    info.numericStats.push({ key: formattedKey, rawKey: key, value: value });
                } else {
                    info.otherFields.push({ key: formattedKey, rawKey: key, value: value });
                }
            } else if ((typeof value === 'string' || typeof value === 'boolean') &&
                !key.toLowerCase().includes('id') &&
                !key.toLowerCase().includes('color') &&
                !key.toLowerCase().includes('col') &&
                value !== '' && value !== null) {
                info.otherFields.push({ key: this.formatFieldLabel(key), rawKey: key, value: value });
            }
        }

        return info;
    }

    formatFieldLabel(key) {
        return String(key)
            .replace(/([A-Z])/g, ' $1')
            .replace(/_/g, ' ')
            .trim()
            .split(' ')
            .map(word => word.charAt(0).toUpperCase() + word.slice(1))
            .join(' ');
    }

    normalizeFieldKey(key) {
        return String(key)
            .replace(/([a-z])([A-Z])/g, '$1_$2')
            .replace(/[\s-]+/g, '_')
            .toLowerCase();
    }

    isDateLikeField(key) {
        const normalized = this.normalizeFieldKey(key);
        return /(date|time|timestamp|created|joined|registered|updated|active|seen|online|login|last_online|member_since)/.test(normalized);
    }

    isIdentifierField(key) {
        const normalized = this.normalizeFieldKey(key);
        return /(^|_)(id|uid|uuid|guid|sid)$/.test(normalized) ||
            /(user_id|userid|player_id|playerid|account_id|accountid|profile_id|profileid|steam_id|steamid|member_id|memberid)/.test(normalized);
    }

    shouldCompactNumber(key) {
        const normalized = this.normalizeFieldKey(key);

        if (this.isIdentifierField(normalized) || this.isDateLikeField(normalized)) return false;
        if (/(rank|level|tier|xp|experience|year|age|percent|percentage|ratio)/.test(normalized)) return false;

        return /(count|total|followers?|following|followees?|subscribers?|subscriptions?|fans?|posts?|statuses?|tweets?|updates?|contributions?|videos?|photos?|views?|likes?|comments?|reputation|karma|points|score|rating)/.test(normalized);
    }

    formatFieldValue(key, value, options = {}) {
        if (value === null || value === undefined) return '';

        if (typeof value === 'boolean') {
            return value ? 'Yes' : 'No';
        }

        if (typeof value === 'number') {
            if (this.isDateLikeField(key)) {
                const date = this.parseDate(value);
                if (date) return date;
            }

            if (options.compactCounts && this.shouldCompactNumber(key)) {
                return this.formatNumber(value);
            }

            return this.formatPlainNumber(value);
        }

        if (typeof value === 'string') {
            const trimmed = value.trim();
            const numericValue = Number(trimmed);
            const isNumericString = trimmed !== '' && Number.isFinite(numericValue);

            if (isNumericString && this.isDateLikeField(key)) {
                const date = this.parseDate(numericValue);
                if (date) return date;
            }

            if (isNumericString && !this.isIdentifierField(key)) {
                return this.formatPlainNumber(numericValue);
            }
        }

        return String(value);
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

    formatPlainNumber(num) {
        if (num === null || num === undefined) return '';
        return new Intl.NumberFormat(undefined, {
            maximumFractionDigits: Number.isInteger(num) ? 0 : 2
        }).format(num);
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
        text = String(text);
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
        this.viewMode = 'flat';
        this.activeCategory = 'all';
        this.elements.resultsMasonry.innerHTML = '';
        this.elements.groupedResults.innerHTML = '';
        this.elements.resultsMasonry.classList.remove('hidden');
        this.elements.groupedResults.classList.add('hidden');
        this.elements.flatViewBtn.classList.add('active');
        this.elements.groupedViewBtn.classList.remove('active');
        this.elements.currentlyChecking.classList.add('hidden');
        this.elements.categoryStats.classList.add('hidden');
        this.elements.filterSection.classList.add('hidden');
        this.elements.categoryFilter.classList.add('hidden');
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
