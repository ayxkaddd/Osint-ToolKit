window.currentService = 'username';

// Stand-in pictures sites show when there is none (SoundCloud's default_avatar_large.png...)
const DEFAULT_PICTURE =
    /default[_-]?(avatar|profile|user|photo|image|pic)|(avatar|profile|user)[_-]?default|\/defaults?\/|no[_-]?(avatar|photo|image)|placeholder|blank[_-]?(avatar|profile)/i;

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
            found: 0,
            unchecked: 0,
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
            groupedViewBtn: document.getElementById('groupedViewBtn'),
            overview: document.getElementById('usernameOverview'),
            mailboxes: document.getElementById('usernameMailboxes'),
            checkMailboxes: document.getElementById('checkMailboxes'),
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
        this.bindMailboxEvents();
    }

    // ---------------------------------------------------------------------------
    // Email providers: is the username also a mailbox (someuser@gmail.com, @outlook.com...)?
    // Opt-in with the checkbox under the search box; the results stream in with the sites.
    // ---------------------------------------------------------------------------

    bindMailboxEvents() {
        const box = this.elements.checkMailboxes;
        if (box) {
            try {
                box.checked = localStorage.getItem('username.checkMailboxes') === '1';
            } catch (error) {
                // no storage (private window): the box just starts unticked
            }
            box.addEventListener('change', () => {
                try {
                    localStorage.setItem('username.checkMailboxes', box.checked ? '1' : '0');
                } catch (error) {
                    // not remembered, still used for this search
                }
            });
        }
        this.elements.mailboxes?.addEventListener('click', (event) => {
            if (event.target.closest('[data-mailbox-gmail-allow]')) this.openGmailPermission();
            if (event.target.closest('[data-mailbox-gmail-off]')) this.setGmailPermission(false);
        });
    }

    resetMailboxes(active = false) {
        this.mailboxes = { active, running: active, results: [] };
        this.mailboxHtml = '';
        if (this.elements.mailboxes) this.elements.mailboxes.innerHTML = '';
        if (active) this.queueMailboxes();
    }

    addMailboxResult(result) {
        if (!this.mailboxes?.active) return;
        // A re-check (Gmail once allowed) replaces the earlier answer for that address
        this.mailboxes.results = this.mailboxes.results.filter((r) => r.email !== result.email);
        this.mailboxes.results.push(result);
        this.queueMailboxes();
        if (result.status === 'found') this.queueOverview();
    }

    finishMailboxes() {
        if (!this.mailboxes?.active || !this.mailboxes.running) return;
        this.mailboxes.running = false;
        this.queueMailboxes();
    }

    foundMailboxes() {
        return (this.mailboxes?.results || []).filter((r) => r.status === 'found');
    }

    queueMailboxes() {
        if (this.mailboxesQueued) return;
        this.mailboxesQueued = true;
        requestAnimationFrame(() => {
            this.mailboxesQueued = false;
            this.renderMailboxes();
        });
    }

    async loadMailboxStatus() {
        if (this.mailboxStatus) return this.mailboxStatus;
        try {
            const response = await fetch('/api/username/mailboxes/status');
            if (response.ok) this.mailboxStatus = await response.json();
        } catch (error) {
            // the panel works without it; only the Gmail lines need it
        }
        return this.mailboxStatus || {};
    }

    renderMailboxes() {
        const container = this.elements.mailboxes;
        if (!container || !this.mailboxes?.active) return;
        const results = this.mailboxes.results;
        const by = (status) => results.filter((r) => r.status === status);
        const found = by('found');
        const missing = by('not_found');
        const failed = by('error');
        const gmailWaiting = results.find((r) => r.details && r.details.needs_permission);
        const skipped = by('skipped').filter((r) => r !== gmailWaiting);
        const running = this.mailboxes.running;
        const status = running
            ? `<span class="flex items-center gap-2"><i class="fas fa-spinner fa-spin"></i>Checking email providers…</span>`
            : [
                  `${found.length} found`,
                  missing.length && `${missing.length} not registered`,
                  failed.length && `${failed.length} couldn't check`,
              ]
                  .filter(Boolean)
                  .join(' · ');
        const list = (title, items, withReason) =>
            items.length
                ? `<details class="mt-2 text-xs text-gray-400">
                    <summary class="cursor-pointer w-fit hover:text-gray-200">${escapeHtml(title)} (${items.length})</summary>
                    <div class="mt-1.5 space-y-0.5">${items
                        .map(
                            (r) =>
                                `<div class="flex items-center gap-1.5 flex-wrap">${mailboxIcon(r.provider, r.email, 'w-3.5 h-3.5')}<span class="text-gray-300">${escapeHtml(r.email)}</span>${
                                    withReason && r.reason
                                        ? ` <span class="text-gray-500">- ${escapeHtml(r.reason)}</span>`
                                        : ''
                                }</div>`
                        )
                        .join('')}</div>
                </details>`
                : '';
        const permitted = this.mailboxStatus && this.mailboxStatus.gmail_permission;
        const html = `
            <section class="username-category-section p-4 mb-4">
                <div class="flex items-center justify-between gap-3 flex-wrap">
                    <h2 class="flex items-center gap-2 text-sm font-semibold text-white"><i data-lucide="mail" class="w-4 h-4 text-purple-300"></i>Email addresses</h2>
                    <span class="text-xs text-gray-400">${status}</span>
                </div>
                ${
                    found.length
                        ? `<div class="flex flex-wrap gap-2 mt-3">${found.map((r) => this.mailboxChip(r)).join('')}</div>`
                        : !running
                          ? '<p class="mt-2 text-sm text-gray-500">No mailbox with this name at the providers that answered.</p>'
                          : ''
                }
                ${
                    gmailWaiting
                        ? `<div class="mt-3 flex items-center justify-between gap-3 flex-wrap bg-yellow-900/20 border border-yellow-700/50 rounded-lg px-4 py-2 text-sm text-yellow-100">
                    <span>Gmail wasn't checked: it needs your permission to use your Google session.</span>
                    <button type="button" data-mailbox-gmail-allow class="px-3 py-1.5 rounded-lg bg-yellow-700/60 hover:bg-yellow-600/70 text-white shrink-0">Allow…</button>
                </div>`
                        : ''
                }
                ${list("Couldn't check", failed, true)}
                ${list('Not registered', missing, false)}
                ${list('Not checked', skipped, true)}
                ${
                    permitted
                        ? `<button type="button" data-mailbox-gmail-off class="mt-3 text-xs text-gray-500 hover:text-gray-300 underline">Gmail is checked with your Google session · turn off</button>`
                        : ''
                }
            </section>`;
        if (html === this.mailboxHtml) return;
        this.mailboxHtml = html;
        replaceKeepingImages(container, html);
        if (window.lucide) lucide.createIcons();
    }

    // A found address: provider, the address as a pivot chip, and what Gravatar or Google add
    mailboxChip(result) {
        const details = result.details || {};
        const picture = safeUrl(details.picture);
        const aliases = result.aliases || [];
        return `
            <div class="inline-flex items-center gap-2 max-w-full px-2.5 py-1.5 rounded-lg bg-gray-800/40 border border-[#293142]"${
                details.note ? ` title="${escapeAttr(details.note)}"` : ''
            }>
                ${
                    picture
                        ? `<button type="button" data-image-view="${escapeAttr(picture)}" data-image-title="${escapeAttr(result.email)}" class="shrink-0">
                    <img src="${escapeAttr(picture)}" alt="" loading="lazy" referrerpolicy="no-referrer" class="w-6 h-6 rounded-md object-cover"></button>`
                        : ''
                }
                ${mailboxIcon(result.provider, result.email)}
                ${pivotText('email', result.email)}
                ${details.name ? `<span class="text-xs text-gray-300 truncate">${escapeHtml(details.name)}</span>` : ''}
                ${details.gaia_id ? pivotText('gaia_id', details.gaia_id, 'Gaia ID') : ''}
                ${
                    aliases.length
                        ? `<span class="text-xs text-gray-500 shrink-0" title="${escapeAttr(aliases.join(', '))}">+${aliases.length} alias${aliases.length === 1 ? '' : 'es'}</span>`
                        : ''
                }
            </div>`;
    }

    async openGmailPermission() {
        const status = await this.loadMailboxStatus();
        const waiting = (this.mailboxes?.results || []).find((r) => r.details && r.details.needs_permission);
        const email = waiting ? waiting.email : 'an address';
        const modal = document.createElement('div');
        modal.className = 'modal-overlay';
        modal.innerHTML = `
            <div class="modal-content max-w-lg">
                <div class="modal-header">
                    <h2 class="text-lg font-bold text-white">Check Gmail with your Google session?</h2>
                    <button type="button" class="close-modal text-gray-400 hover:text-white" title="Close"><i class="fas fa-times"></i></button>
                </div>
                <div class="modal-body space-y-3 text-sm text-gray-300">
                    <p>To see whether <b class="text-white">${escapeHtml(email)}</b> is a Google account, the toolkit asks Google the way GHunt does: signed in with the Google session GHunt saved on this computer.</p>
                    <ul class="list-disc pl-5 space-y-1">
                        <li>Google sees these lookups on your account. Many of them in a short time can get the session limited or signed out.</li>
                        <li>Your cookies are only sent to Google, directly - never through proxies.</li>
                        <li>Only "does this account exist" is asked; nothing is sent to the address.</li>
                        <li>You can turn it off again below the email addresses.</li>
                    </ul>
                    ${
                        status.ghunt_session === false
                            ? '<p class="text-yellow-200">No GHunt session was found on this computer yet: log in with <code>ghunt login</code>, otherwise Gmail stays unchecked.</p>'
                            : ''
                    }
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn-secondary" data-cancel>Not now</button>
                    <button type="button" class="btn-primary" data-allow>Allow</button>
                </div>
            </div>`;
        const close = () => modal.remove();
        modal.addEventListener('click', (event) => {
            if (event.target === modal || event.target.closest('.close-modal, [data-cancel]')) close();
        });
        modal.querySelector('[data-allow]').addEventListener('click', async () => {
            close();
            await this.setGmailPermission(true);
        });
        document.body.appendChild(modal);
    }

    async setGmailPermission(allow) {
        try {
            const response = await fetch('/api/username/mailboxes/google-permission', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ allow }),
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();
            this.mailboxStatus = { ...(this.mailboxStatus || {}), gmail_permission: data.gmail_permission };
        } catch (error) {
            showTemporaryNotification("Couldn't save the Gmail setting", 'error');
            return;
        }
        if (!allow) {
            showTemporaryNotification('Gmail is no longer checked with your Google session', 'info');
            this.queueMailboxes();
            return;
        }
        // Allowed: check Gmail now, without running the whole search again
        if (!this.lastUsername || !this.mailboxes?.active) return this.queueMailboxes();
        try {
            const response = await fetch(
                `/api/username/mailboxes/check?username=${encodeURIComponent(this.lastUsername)}&provider=gmail`
            );
            const data = await response.json();
            (data.results || []).forEach((result) => this.addMailboxResult(result));
        } catch (error) {
            showTemporaryNotification("Couldn't check Gmail", 'error');
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
        if (name.includes('stackoverflow') || name.includes('stack overflow'))
            return { class: 'stackoverflow-orange', icon: 'SO' };

        // Other platforms
        if (name.includes('cashapp')) return { class: 'cashapp-green', icon: '$' };
        if (name.includes('patreon')) return { class: 'patreon-orange', icon: 'PT' };

        const firstLetter = siteName.charAt(0).toUpperCase();
        const secondLetter = siteName.length > 1 ? siteName.charAt(1).toUpperCase() : '';

        return {
            class: 'bg-gray-600',
            icon: firstLetter + secondLetter,
        };
    }

    // retrySites: re-check only these (they errored last time) and keep current results
    startSearch(retrySites = null) {
        if (this.searchActive) return;

        const username = retrySites ? this.lastUsername : document.getElementById('usernameSearchInput').value.trim();
        if (!username) return;

        this.retrying = Boolean(retrySites);
        document.getElementById('usernameRetryBox')?.remove();
        if (this.retrying) {
            this.stats.unchecked = Math.max(0, this.stats.unchecked - retrySites.length);
            this.updateStats();
        } else {
            this.resetResults();
        }
        this.lastUsername = username;
        this.erroredSites = [];
        this.errorReasons = {}; // site -> why it couldn't be checked
        this.showProgress();
        this.searchActive = true;
        this.elements.searchBtn.innerHTML = '<i class="fas fa-spinner fa-spin mr-2"></i>Searching...';
        this.elements.searchBtn.disabled = true;
        this.elements.stopBtn.classList.remove('hidden');

        const only = (retrySites || []).map((name) => `&only_sites=${encodeURIComponent(name)}`).join('');
        // Email providers: opt-in, and not on a re-check of the sites that errored
        const mailboxes = !retrySites && this.elements.checkMailboxes && this.elements.checkMailboxes.checked;
        if (!retrySites) this.resetMailboxes(mailboxes);
        if (mailboxes) this.loadMailboxStatus().then(() => this.queueMailboxes());
        const url = `/api/username/search/stream?username=${encodeURIComponent(username)}&include_duckduckgo=false&extract_profile=true${mailboxes ? '&check_mailboxes=true' : ''}${only}`;

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
                if (!this.retrying) this.stats.total = event.data.total_sites;
                this.updateStats();
                break;

            case 'site_checking':
                this.showCurrentlyChecking(event.data.site_name);
                break;

            case 'site_result':
                if (event.data.status === 'found') {
                    this.handleFoundResult(event.data);
                } else if (event.data.status === 'error' || event.data.status === 'rate_limited') {
                    // The site couldn't be checked: "not found" would be wrong
                    this.stats.unchecked++;
                    if (event.data.site_name) {
                        this.erroredSites.push(event.data.site_name);
                        this.errorReasons[event.data.site_name] = event.data.error_message || event.data.status;
                    }
                    this.updateStats();
                }
                if (event.data.progress && !this.retrying) {
                    this.updateProgress(event.data.progress);
                }
                break;

            case 'mailbox_result':
                this.addMailboxResult(event.data);
                break;

            case 'mailbox_completed':
                this.finishMailboxes();
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
            checkedAt: data.checked_at,
            // The account is under this name, also when the profile doesn't repeat it
            searched: this.lastUsername,
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
        this.queueOverview();
    }

    // Who the accounts point to (photos, names, handles, places, when it was active), in the
    // same summary as the OSINT Industries results. Rebuilt at most once per frame.
    queueOverview() {
        if (this.overviewQueued) return;
        this.overviewQueued = true;
        requestAnimationFrame(() => {
            this.overviewQueued = false;
            this.renderOverview();
        });
    }

    renderOverview() {
        const container = this.elements.overview;
        if (!container || typeof oiSummaryHtml !== 'function') return;
        const accounts = this.results.map((result) => {
            const info = this.extractKeyInfo(result.profileData);
            return {
                module: result.siteName,
                name: info.fullName ? String(info.fullName) : null,
                username: info.username,
                picture: info.profileImage ? this.getAbsoluteUrl(info.profileImage) : null,
                location: info.country,
                created: info.createdDate ? info.createdDate.toISOString() : null,
                last_seen: info.lastActiveDate ? info.lastActiveDate.toISOString() : null,
            };
        });
        // Mailboxes found at email providers: their addresses, and Gravatar's name and picture
        this.foundMailboxes().forEach((mailbox) => {
            const details = mailbox.details || {};
            accounts.push({
                module: mailbox.provider,
                email: mailbox.email,
                name: details.name || null,
                picture: details.picture || null,
                location: details.location || null,
            });
        });
        const html = oiSummaryHtml(accounts, { timeline: false });
        // Most results add nothing to the summary: leave it alone then
        if (html === this.overviewHtml) return;
        this.overviewHtml = html;
        // The photos already shown stay as they are (rebuilding them made them blink)
        replaceKeepingImages(container, html);
        if (window.lucide) lucide.createIcons();
    }

    getCategoryColor(category) {
        const colors = {
            social: 'bg-blue-500',
            gaming: 'bg-purple-500',
            forums: 'bg-green-500',
            developer: 'bg-orange-500',
            marketplace: 'bg-yellow-500',
            streaming: 'bg-pink-500',
            adult: 'bg-red-500',
            miscellaneous: 'bg-gray-500',
            default: 'bg-gray-500',
        };

        return colors[category.toLowerCase()] || colors['default'];
    }

    addResultCard(result) {
        const card = this.createResultCard(result);

        if (this.viewMode === 'grouped') {
            const group = this.getGroupedCategory(result.category);
            masonryAppend(group.querySelector('.username-category-results'), card);
            this.updateGroupedCategoryCount(result.category);
            this.filterByCategory(this.activeCategory);
        } else {
            masonryAppend(this.elements.resultsMasonry, card);
        }
    }

    replaceResultCard(result) {
        const existingCard = this.findResultCard(result);
        const newCard = this.createResultCard(result);
        newCard.classList.remove('fade-in');

        if (existingCard) {
            newCard.dataset.order = existingCard.dataset.order;
            // The site icon and anything else already loaded carry over without reloading
            keepLoadedImages(existingCard, newCard);
            existingCard.replaceWith(newCard);
            return;
        }

        this.addResultCard(result);
    }

    findResultCard(result) {
        const cards = this.elements.resultsContainer.querySelectorAll('.username-result-card');
        return Array.from(cards).find(
            (card) => card.dataset.resultUrl === result.url && card.dataset.siteName === result.siteName
        );
    }

    // A found account, led by who it is: picture, name, @handle, then what the profile
    // says (bio, counts, dates, place). The rest of the data is behind the footer button.
    createResultCard(result) {
        const info = this.extractKeyInfo(result.profileData);
        const handle = info.username || result.searched || '';
        const domain = this.getDomainFromUrl(result.url);
        const faviconUrl = domain ? this.getFaviconUrl(domain) : '';
        const avatar = info.profileImage ? safeUrl(this.getAbsoluteUrl(info.profileImage)) : '';
        const banner = info.banner ? safeUrl(this.getAbsoluteUrl(info.banner)) : '';
        const profileUrl = safeUrl(result.url);
        const stats = this.getStatChips(info);
        const shownStats = stats.slice(0, 5);
        const facts = this.getFactRows(info);
        const moreFields = stats.length - shownStats.length + facts.hidden;
        const hasProfileData = result.profileData && Object.keys(result.profileData).length > 0;
        const site = escapeAttr(result.siteName);
        const verified = info.verified
            ? '<i class="fas fa-check-circle username-profile-verified" title="Verified"></i>'
            : '';

        const card = document.createElement('div');
        card.className = `result-card username-result-card username-profile-card fade-in${banner ? ' has-banner' : ''}`;
        card.dataset.resultUrl = result.url;
        card.dataset.siteName = result.siteName;
        card.dataset.category = result.category;

        card.innerHTML = `
            ${
                banner
                    ? `<button type="button" class="username-card-banner" data-image-view="${escapeAttr(banner)}" data-image-title="${site}" data-image-note="Profile banner" title="Preview banner">
                <img src="${escapeAttr(banner)}" alt="" loading="lazy" referrerpolicy="no-referrer"
                    onerror="this.closest('.username-profile-card').classList.remove('has-banner'); this.parentElement.remove();">
            </button>`
                    : ''
            }
            <div class="username-profile-head">
                <div class="username-profile-pic${avatar ? '' : ' no-avatar'}">
                    ${
                        avatar
                            ? `<button type="button" class="username-avatar-preview-btn" data-image-view="${escapeAttr(avatar)}" data-image-title="${site}" data-image-note="Profile picture" title="Preview profile picture">
                        <img src="${escapeAttr(avatar)}" alt="" loading="lazy" referrerpolicy="no-referrer" class="username-profile-avatar"
                            onerror="this.closest('.username-profile-pic').classList.add('no-avatar')">
                    </button>
                    <div class="username-reverse-search" aria-label="Reverse image search">
                        ${this.getReverseImageSearchLinks(avatar)
                            .map(
                                (link) => `
                            <a href="${escapeAttr(link.url)}" target="_blank" rel="noopener noreferrer" title="${escapeAttr(link.label)} reverse image search"><i class="${escapeAttr(link.icon)}"></i></a>`
                            )
                            .join('')}
                    </div>`
                            : ''
                    }
                    ${this.siteMarkHtml(result, faviconUrl)}
                </div>
                <div class="username-profile-ident">
                    <div class="username-profile-site">
                        ${faviconUrl ? `<img src="${escapeAttr(faviconUrl)}" alt="" loading="lazy" class="username-profile-favicon" onerror="this.remove()">` : ''}
                        <span>${escapeHtml(result.siteName)}</span>
                        ${result.category ? `<span class="username-profile-cat">${escapeHtml(result.category)}</span>` : ''}
                    </div>
                    ${
                        info.fullName
                            ? `<h3 class="username-profile-name" title="${escapeAttr(String(info.fullName))}">${escapeHtml(String(info.fullName))}${verified}</h3>`
                            : ''
                    }
                    ${
                        handle
                            ? `<div class="username-profile-handle">
                        ${pivotText('username', handle, '@' + handle)}${info.fullName ? '' : verified}
                        <button type="button" class="copy-username-btn" data-username="${escapeAttr(handle)}" title="Copy username"><i class="fas fa-copy"></i></button>
                    </div>`
                            : ''
                    }
                </div>
            </div>

            ${info.bio ? `<p class="username-card-bio" title="${escapeAttr(String(info.bio))}">${pivotInText(String(info.bio))}</p>` : ''}

            ${
                shownStats.length
                    ? `<div class="username-profile-stats">${shownStats
                          .map(
                              (stat) =>
                                  `<span title="${escapeAttr(stat.full)}"><strong>${escapeHtml(stat.value)}</strong>${escapeHtml(stat.label)}</span>`
                          )
                          .join('')}</div>`
                    : ''
            }

            ${facts.html ? `<div class="username-card-content">${facts.html}</div>` : ''}

            ${
                info.socialLinks && info.socialLinks.length > 0
                    ? `<div class="username-link-strip">${info.socialLinks
                          .map((link) => safeUrl(link))
                          .filter(Boolean)
                          .slice(0, 5)
                          .map(
                              (link) =>
                                  `<a href="${escapeAttr(link)}" target="_blank" rel="noopener noreferrer" title="${escapeAttr(link)}"><i class="fas fa-link"></i></a>`
                          )
                          .join('')}</div>`
                    : ''
            }

            <div class="username-card-actions">
                ${
                    profileUrl
                        ? `<a href="${escapeAttr(profileUrl)}" target="_blank" rel="noopener noreferrer" title="${escapeAttr(result.url)}">
                    <i class="fas fa-external-link-alt"></i><span>View</span></a>`
                        : '<span></span>'
                }
                ${
                    hasProfileData
                        ? `<button type="button" class="expand-btn" title="All profile data">
                    <i class="fas fa-code"></i><span>${moreFields > 0 ? `+${moreFields} field${moreFields === 1 ? '' : 's'}` : 'Data'}</span>
                </button>`
                        : ''
                }
            </div>
        `;

        const copyUsernameBtn = card.querySelector('.copy-username-btn');
        if (copyUsernameBtn) {
            copyUsernameBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.copyToClipboard(copyUsernameBtn.dataset.username, copyUsernameBtn);
            });
        }

        const expandBtn = card.querySelector('.expand-btn');
        if (expandBtn) {
            expandBtn.addEventListener('click', () => {
                this.openModal(result);
            });
        }

        return card;
    }

    // The site's icon (or two letters when it doesn't load): stands in for a missing picture
    siteMarkHtml(result, faviconUrl) {
        const platform = this.getPlatformIcon(result.siteName, result.category);
        const fallback = `<div class="platform-icon ${platform.class}${faviconUrl ? ' username-site-mark-fallback' : ''}">${escapeHtml(platform.icon)}</div>`;
        return `<div class="username-site-mark">${
            faviconUrl
                ? `<img src="${escapeAttr(faviconUrl)}" alt="" loading="lazy" onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';">`
                : ''
        }${fallback}</div>`;
    }

    // Counts as "8 followers", "4 likes": followers/following/posts first, then the rest
    getStatChips(info) {
        const chips = [];
        const add = (label, value) => {
            if (!Number.isFinite(value)) return;
            chips.push({ label, value: this.formatNumber(value), full: `${value.toLocaleString()} ${label}` });
        };
        add('followers', info.followers);
        add('following', info.following);
        add('posts', info.posts);
        add('reputation', info.reputation);
        (info.numericStats || []).forEach((stat) => add(this.statLabel(stat.key), Number(stat.value)));
        return chips;
    }

    statLabel(key) {
        const label = String(key)
            .replace(/\b(count|total|number of|num)\b/gi, '')
            .replace(/\s+/g, ' ')
            .trim()
            .toLowerCase();
        return label || String(key).toLowerCase();
    }

    // Dates, place and a few other fields as label/value rows; how many more are in "Data"
    getFactRows(info) {
        const rows = [];
        const add = (label, value) => {
            if (value !== null && value !== undefined && value !== '') rows.push([label, value]);
        };
        add('Joined', info.createdAt);
        add('Last active', info.lastActive);
        add('Location', info.country);
        add('Gender', info.gender);
        add('Website', info.website);
        const other = (info.otherFields || []).map((field) => [
            field.key,
            this.formatFieldValue(field.rawKey || field.key, field.value),
        ]);
        const shownOther = other.slice(0, Math.min(3, Math.max(0, 6 - rows.length)));
        return {
            html: [...rows, ...shownOther]
                .map(
                    ([label, value]) => `
                <div class="username-data-row">
                    <strong>${escapeHtml(label)}</strong>
                    <span title="${escapeAttr(String(value))}">${pivotField(label, value)}</span>
                </div>`
                )
                .join(''),
            hidden: other.length - shownOther.length,
        };
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
                url: `https://lens.google.com/uploadbyurl?url=${encodedUrl}`,
            },
            {
                label: 'Yandex',
                icon: 'fas fa-search',
                url: `https://yandex.com/images/search?rpt=imageview&url=${encodedUrl}`,
            },
        ];
    }

    handleProfileExtracted(data) {
        const result = this.results.find((item) => item.url === data.url && item.siteName === data.site_name);

        if (!result) return;

        result.profileData = data.profile_data;
        this.replaceResultCard(result);
        this.queueOverview();
    }

    copyToClipboard(text, button) {
        navigator.clipboard
            .writeText(text)
            .then(() => {
                const originalHTML = button.innerHTML;
                button.innerHTML = '<i class="fas fa-check text-xs"></i>';
                button.classList.add('text-green-400');

                setTimeout(() => {
                    button.innerHTML = originalHTML;
                    button.classList.remove('text-green-400');
                }, 1500);
            })
            .catch((err) => {
                console.error('Failed to copy:', err);
            });
    }

    updateCategoryCount(category) {
        const section = Array.from(this.elements.groupedResults.querySelectorAll('[data-category]')).find(
            (item) => item.dataset.category === category
        );
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

            this.elements.categoryStatsGrid.innerHTML = categories
                .map((category) => {
                    const count = this.resultsByCategory[category].length;
                    return `
                    <button type="button" class="username-category-pill" data-category="${escapeHtml(category)}">
                        <span>${escapeHtml(category)}</span>
                        <strong>${count}</strong>
                    </button>
                `;
                })
                .join('');

            this.elements.categoryStatsGrid.querySelectorAll('.username-category-pill').forEach((button) => {
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

        this.elements.categoryFilter.innerHTML =
            '<option value="all">All Categories</option>' +
            categories
                .map(
                    (category) =>
                        `<option value="${category}" ${currentValue === category ? 'selected' : ''}>${category.charAt(0).toUpperCase() + category.slice(1)}</option>`
                )
                .join('');
    }

    filterByCategory(category) {
        this.activeCategory = category;
        const sections = this.elements.groupedResults.querySelectorAll('[data-category]');

        sections.forEach((section) => {
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

        // Cards are rebuilt for the other layout: their loaded pictures move with them
        const previous = new Map();
        this.elements.resultsContainer.querySelectorAll('.username-result-card').forEach((card) => {
            previous.set(`${card.dataset.siteName}\n${card.dataset.resultUrl}`, card);
        });
        const createCard = (result) => {
            const card = this.createResultCard(result);
            const old = previous.get(`${result.siteName}\n${result.url}`);
            if (old) keepLoadedImages(old, card);
            return card;
        };

        masonryLayout(this.elements.resultsMasonry);
        this.elements.groupedResults.innerHTML = '';

        if (this.viewMode === 'grouped') {
            Object.keys(this.resultsByCategory)
                .sort()
                .forEach((category) => {
                    const section = this.createGroupedCategory(category);
                    const grid = section.querySelector('.username-category-results');
                    this.resultsByCategory[category].forEach((result) => {
                        masonryAppend(grid, createCard(result));
                    });
                    this.elements.groupedResults.appendChild(section);
                });
            this.filterByCategory(this.activeCategory);
        } else {
            this.results.forEach((result) => {
                masonryAppend(this.elements.resultsMasonry, createCard(result));
            });
        }
    }

    getGroupedCategory(category) {
        let section = Array.from(this.elements.groupedResults.querySelectorAll('[data-category]')).find(
            (item) => item.dataset.category === category
        );
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
                <h2>${escapeHtml(category)}</h2>
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

        modal.querySelectorAll('.copy-btn').forEach((btn) => {
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
                .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
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
            socialProfiles: {},
        };

        const usernameFields = [
            'username',
            'user_name',
            'userName',
            'disqus_username',
            'imgur_username',
            'name',
            'handle',
            'login',
            'screen_name',
            'screenName',
            'display',
            'nickname',
            'nick',
            'account_name',
        ];
        for (const field of usernameFields) {
            if (profileData[field]) {
                info.username = profileData[field];
                break;
            }
        }
        // A handle has no spaces ("This username already exists" is a site's message;
        // "Drain God" in a name field is a display name, picked up below)
        const handle = String(info.username ?? '')
            .trim()
            .replace(/^@/, '');
        info.username = /^[\w.-]{1,64}$/u.test(handle) ? handle : null;

        const nameFields = [
            'fullname',
            'full_name',
            'fullName',
            'displayName',
            'display_name',
            'realName',
            'real_name',
            'name',
        ];
        for (const field of nameFields) {
            if (profileData[field] && profileData[field] !== info.username) {
                info.fullName = profileData[field];
                break;
            }
        }

        const bioFields = [
            'bio',
            'description',
            'about',
            'aboutMe',
            'about_me',
            'motto',
            'statusMessage',
            'status_message',
            'blurb',
            'note',
            'summary',
            'headline',
            'tagline',
        ];
        for (const field of bioFields) {
            if (profileData[field]) {
                info.bio = profileData[field];
                break;
            }
        }

        const imageFields = [
            'profileImageUrl',
            'profile_image_url',
            'profilePic',
            'profile_pic',
            'image',
            'avatar',
            'avatar_static',
            'avatar_url',
            'icon_img',
            'logo',
            'logoUrl',
            'pic_url',
            'photo',
            'photo_url',
            'picture',
        ];
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
        // A site's stand-in picture says nothing about the person
        if (info.profileImage && DEFAULT_PICTURE.test(String(info.profileImage))) info.profileImage = null;

        const bannerFields = [
            'image_bg',
            'banner',
            'banner_url',
            'bannerUrl',
            'banner_image',
            'profile_banner_url',
            'cover',
            'cover_url',
            'coverPhoto',
            'cover_photo',
            'header_image',
            'backgroundPicture',
        ];
        for (const field of bannerFields) {
            const value = profileData[field];
            const url = value && typeof value === 'object' ? value.url : value;
            if (typeof url === 'string' && /^(https?:)?\/\//.test(url) && !DEFAULT_PICTURE.test(url)) {
                info.banner = url;
                break;
            }
        }

        const countryFields = [
            'country',
            'country_code',
            'countryCode',
            'location',
            'city',
            'place',
            'nationality',
            'region',
            'area',
            'locale',
        ];
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
        info.country = this.countryName(info.country);

        const genderFields = ['gender', 'genderVerbal', 'gender_verbal', 'sex'];
        for (const field of genderFields) {
            if (profileData[field]) {
                info.gender = profileData[field];
                break;
            }
        }

        const followerFields = [
            'follower_count',
            'followers_count',
            'followersCount',
            'followerCount',
            'followers',
            'subscriber_count',
            'subscribers',
            'fans',
        ];
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

        const followingFields = [
            'following_count',
            'follows_count',
            'followsCount',
            'followingCount',
            'following',
            'followeeCount',
            'followees',
            'subscriptions',
        ];
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

        const postsFields = [
            'posts',
            'post_count',
            'postCount',
            'statuses_count',
            'statusesCount',
            'tweets',
            'updates',
            'contributions',
            'cloudcast_count',
            'videos',
            'photos',
        ];
        for (const field of postsFields) {
            if (profileData[field] !== undefined && profileData[field] !== null) {
                info.posts = parseInt(profileData[field]);
                break;
            }
        }
        if (profileData.counters && profileData.counters.posts !== undefined) {
            info.posts = parseInt(profileData.counters.posts);
        }

        const reputationFields = ['reputation', 'karma', 'total_karma', 'points', 'score', 'rating'];
        for (const field of reputationFields) {
            if (profileData[field] !== undefined && profileData[field] !== null) {
                info.reputation = parseInt(profileData[field]);
                break;
            }
        }
        if (profileData.data && profileData.data.total_karma !== undefined) {
            info.reputation = parseInt(profileData.data.total_karma);
        }

        const dateFields = [
            'created_at',
            'createdAt',
            'createdOn',
            'created',
            'memberSince',
            'member_since',
            'createdDate',
            'created_date',
            'joined',
            'joinedAt',
            'joined_at',
            'registered',
            'signup_date',
        ];
        for (const field of dateFields) {
            if (profileData[field]) {
                const date = this.toDate(profileData[field]);
                if (date) {
                    info.createdDate = date;
                    break;
                }
            }
        }
        if (profileData.data && profileData.data.created_utc) {
            info.createdDate = this.toDate(Number(profileData.data.created_utc)) || info.createdDate;
        }
        info.createdAt = info.createdDate ? this.formatDay(info.createdDate) : null;

        const lastActiveFields = [
            'latest_activity_at',
            'last_activity_at',
            'lastActivityAt',
            'last_active',
            'lastActive',
            'last_seen',
            'lastSeen',
            'updated_at',
            'updatedAt',
            'last_login',
            'lastLogin',
            'last_online',
            'lastOnline',
            'lastOnlineAt',
            'online_at',
        ];
        for (const field of lastActiveFields) {
            if (profileData[field]) {
                const date = this.toDate(profileData[field]);
                if (date) {
                    info.lastActiveDate = date;
                    break;
                }
            }
        }
        info.lastActive = info.lastActiveDate ? this.formatDay(info.lastActiveDate) : null;

        const verifiedFields = [
            'verified',
            'isVerified',
            'is_verified',
            'is_twitter_verified',
            'verified_account',
            'badge',
        ];
        for (const field of verifiedFields) {
            if (
                profileData[field] === true ||
                profileData[field] === 'True' ||
                profileData[field] === 'true' ||
                profileData[field] === 1
            ) {
                info.verified = true;
                break;
            }
        }

        const websiteFields = ['website', 'url', 'homepage', 'blog', 'site', 'web'];
        for (const field of websiteFields) {
            if (profileData[field] && typeof profileData[field] === 'string' && profileData[field].startsWith('http')) {
                info.website = profileData[field];
                break;
            }
        }

        const socialFields = ['social_links', 'socialLinks', 'links', 'urls'];
        for (const field of socialFields) {
            if (profileData[field]) {
                if (Array.isArray(profileData[field])) {
                    info.socialLinks = profileData[field].filter(
                        (link) => typeof link === 'string' && link.startsWith('http')
                    );
                } else if (typeof profileData[field] === 'object') {
                    info.socialLinks = Object.values(profileData[field]).filter(
                        (link) => typeof link === 'string' && link.startsWith('http')
                    );
                }
                if (info.socialLinks.length > 0) break;
            }
        }

        const socialPlatforms = [
            'youtube',
            'twitter',
            'twitch',
            'instagram',
            'facebook',
            'tiktok',
            'snapchat',
            'linkedin',
            'github',
            'gitlab',
        ];
        for (const platform of socialPlatforms) {
            if (profileData[platform] && profileData[platform] !== null) {
                info.socialProfiles[platform] = profileData[platform];
            }
        }

        const alreadyCaptured = ['followers', 'following', 'posts', 'reputation'];
        const skipFields = [
            ...usernameFields,
            ...nameFields,
            ...bioFields,
            ...imageFields,
            ...countryFields,
            ...genderFields,
            ...followerFields,
            ...followingFields,
            ...postsFields,
            ...reputationFields,
            ...dateFields,
            ...lastActiveFields,
            ...verifiedFields,
            ...websiteFields,
            ...socialFields,
            ...socialPlatforms,
            ...bannerFields,
            'data',
            'counters',
            'stats',
            'picture',
            'backgroundPicture',
            'links',
            // How the data was read, not what it says
            '_extractor',
            'extracted_from',
        ];
        // A page's own title next to OpenGraph data repeats the site's name, not the person's
        if (profileData.extracted_from) skipFields.push('title');

        for (const [key, value] of Object.entries(profileData)) {
            if (skipFields.includes(key) || typeof value === 'object') continue;
            if (/is_?default/i.test(key)) continue; // "default picture: yes" and the like

            // Counts often come as text ("4"): still counts
            const count = typeof value === 'string' && /^\d+$/.test(value.trim()) && this.shouldCompactNumber(key);
            if ((typeof value === 'number' || count) && !alreadyCaptured.includes(key)) {
                const formattedKey = this.formatFieldLabel(key);

                if (this.shouldCompactNumber(key)) {
                    info.numericStats.push({ key: formattedKey, rawKey: key, value: Number(value) });
                } else {
                    info.otherFields.push({ key: formattedKey, rawKey: key, value: value });
                }
            } else if (
                (typeof value === 'string' || typeof value === 'boolean') &&
                !key.toLowerCase().includes('id') &&
                !key.toLowerCase().includes('color') &&
                !key.toLowerCase().includes('col') &&
                value !== '' &&
                value !== null
            ) {
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
            .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
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
        return /(date|time|timestamp|created|joined|registered|updated|active|seen|online|login|last_online|member_since)/.test(
            normalized
        );
    }

    isIdentifierField(key) {
        const normalized = this.normalizeFieldKey(key);
        return (
            /(^|_)(id|uid|uuid|guid|sid)$/.test(normalized) ||
            /(user_id|userid|player_id|playerid|account_id|accountid|profile_id|profileid|steam_id|steamid|member_id|memberid)/.test(
                normalized
            )
        );
    }

    shouldCompactNumber(key) {
        const normalized = this.normalizeFieldKey(key);

        if (this.isIdentifierField(normalized) || this.isDateLikeField(normalized)) return false;
        if (/(rank|level|tier|xp|experience|year|age|percent|percentage|ratio)/.test(normalized)) return false;

        return /(count|total|followers?|following|followees?|subscribers?|subscriptions?|fans?|posts?|statuses?|tweets?|updates?|contributions?|videos?|photos?|views?|likes?|comments?|reputation|karma|points|score|rating)/.test(
            normalized
        );
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

    // A Date from what sites send: ISO, "2020-12-23 01:50:14 UTC", "...49.477000+00:00",
    // RFC 2822, or unix seconds / milliseconds. Null for anything else, and for 0 or
    // placeholder dates (before 1990).
    toDate(value) {
        if (value === null || value === undefined || value === '' || typeof value === 'boolean') return null;
        let date;
        const text = String(value).trim();
        if (typeof value === 'number' || /^\d{9,13}$/.test(text)) {
            const n = Number(value);
            date = new Date(n > 1e11 ? n : n * 1000);
        } else {
            const iso = text
                .replace(/^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})/, '$1T$2')
                .replace(/(\.\d{3})\d+/, '$1')
                .replace(/\s*UTC$/i, 'Z')
                .replace(/\s+([+-]\d{2}:?\d{2})$/, '$1');
            date = new Date(iso);
            if (isNaN(date.getTime())) date = new Date(text);
        }
        if (isNaN(date.getTime())) return null;
        const year = date.getFullYear();
        return year >= 1990 && year <= new Date().getFullYear() + 1 ? date : null;
    }

    formatDay(date) {
        return date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
    }

    parseDate(value) {
        const date = this.toDate(value);
        return date ? this.formatDay(date) : null;
    }

    // "US" -> "United States"; anything else as it is
    countryName(value) {
        if (!value) return null;
        const text = String(value).trim();
        if (/^[A-Za-z]{2}$/.test(text)) {
            try {
                return new Intl.DisplayNames(undefined, { type: 'region' }).of(text.toUpperCase()) || text;
            } catch (error) {
                return text;
            }
        }
        return text;
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
            maximumFractionDigits: Number.isInteger(num) ? 0 : 2,
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
                .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
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
                    <span class="text-gray-400 text-sm font-medium">${escapeHtml(key)}:</span>
            `;

            value.forEach((item, index) => {
                if (typeof item === 'object' && item !== null) {
                    html += `<div class="ml-4 mt-1 p-2 bg-gray-800/50 rounded border border-gray-700">`;
                    for (const [subKey, subValue] of Object.entries(item)) {
                        html += this.renderValue(subKey, subValue, indent + 1);
                    }
                    html += `</div>`;
                } else {
                    html += `<div class="ml-4 text-white text-sm">${pivotField(key, item)}</div>`;
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
                    <span class="text-gray-400 text-sm font-medium">${escapeHtml(key)}:</span>
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
                    <span class="text-gray-400 text-sm whitespace-nowrap">${escapeHtml(key)}</span>
                    <a href="${escapeHtml(safeUrl(value))}" target="_blank" rel="noopener noreferrer" class="text-purple-400 hover:text-purple-300 hover:underline text-sm text-right break-all">${escapeHtml(this.truncateUrl(value))}</a>
                </div>
            `;
        }

        if (typeof value === 'boolean' || value === 'True' || value === 'False') {
            const boolValue = value === true || value === 'True';
            return `
                <div class="${indentClass} flex justify-between items-start gap-4 mb-2">
                    <span class="text-gray-400 text-sm whitespace-nowrap">${escapeHtml(key)}</span>
                    <span class="px-2 py-0.5 rounded ${boolValue ? 'bg-green-900 text-green-300' : 'bg-red-900 text-red-300'} text-xs">${boolValue ? 'Yes' : 'No'}</span>
                </div>
            `;
        }

        if (
            typeof value === 'string' &&
            (value.match(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/) || value.match(/^\d{4}-\d{2}-\d{2}/))
        ) {
            const date = new Date(value);
            if (!isNaN(date.getTime())) {
                const formattedValue =
                    fmtDate(date) +
                    (value.includes('T') ? ' ' + date.toLocaleTimeString([], { timeStyle: 'short' }) : '');
                return `
                    <div class="${indentClass} flex justify-between items-start gap-4 mb-2">
                        <span class="text-gray-400 text-sm whitespace-nowrap">${escapeHtml(key)}</span>
                        <span class="text-white text-sm text-right">${escapeHtml(formattedValue)}</span>
                    </div>
                `;
            }
        }

        return `
            <div class="${indentClass} flex justify-between items-start gap-4 mb-2">
                <span class="text-gray-400 text-sm whitespace-nowrap">${escapeHtml(key)}</span>
                <span class="text-white text-sm text-right break-words">${pivotField(key, value)}</span>
            </div>
        `;
    }

    truncateUrl(url) {
        if (url.length <= 40) return url;
        return url.substring(0, 37) + '...';
    }

    getTimeAgo(timestamp) {
        const now = new Date();
        const time = new Date(timestamp);
        const diffInSeconds = Math.floor((now - time) / 1000);

        if (diffInSeconds < 60) return 'Just now';
        if (diffInSeconds < 3600) return `${Math.floor(diffInSeconds / 60)}m ago`;
        if (diffInSeconds < 86400) return `${Math.floor(diffInSeconds / 3600)}h ago`;
        return fmtDate(time);
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
        this.elements.totalAccounts.textContent = this.stats.unchecked || 0;
    }

    showProgress() {
        this.elements.progressSection.classList.remove('hidden');
    }

    resetResults() {
        this.results = [];
        this.resultsByCategory = {};
        this.stats = { scanned: 0, total: 0, found: 0, unchecked: 0 };
        this.viewMode = 'flat';
        this.activeCategory = 'all';
        masonryLayout(this.elements.resultsMasonry);
        this.elements.groupedResults.innerHTML = '';
        this.elements.resultsMasonry.classList.remove('hidden');
        this.elements.groupedResults.classList.add('hidden');
        this.elements.flatViewBtn.classList.add('active');
        this.elements.groupedViewBtn.classList.remove('active');
        this.elements.currentlyChecking.classList.add('hidden');
        this.elements.categoryStats.classList.add('hidden');
        this.elements.filterSection.classList.add('hidden');
        this.elements.categoryFilter.classList.add('hidden');
        if (this.elements.overview) this.elements.overview.innerHTML = '';
        this.overviewHtml = '';
        document.getElementById('usernameRetryBox')?.remove(); // belongs to the previous search
        this.resetMailboxes(false);
        this.updateStats();

        this.elements.progressBar.style.width = '0%';
        this.elements.progressText.textContent = '0 / 0';
        this.elements.progressPercent.textContent = '0%';
    }

    handleSearchCompleted(data) {
        const wasRetry = this.retrying;
        this.stopSearch();
        const errored = [...new Set(this.erroredSites || [])];
        if (wasRetry) {
            showTemporaryNotification(
                errored.length
                    ? `Retried - ${errored.length} site${errored.length === 1 ? '' : 's'} still couldn't be checked`
                    : 'Retried - every site was checked this time',
                errored.length ? 'info' : 'success'
            );
        }
        if (!errored.length) return;
        // Absence on a site that errored isn't proof the account doesn't exist: offer a re-check
        const box = document.createElement('div');
        box.id = 'usernameRetryBox';
        box.className =
            'mb-4 flex items-center justify-between gap-3 flex-wrap bg-yellow-900/20 border border-yellow-700/50 rounded-lg px-4 py-2 text-sm text-yellow-100';
        box.innerHTML = `
            <span>${errored.length} site${errored.length === 1 ? '' : 's'} couldn't be checked (errors, blocks or rate limits) - no result there isn't proof the account doesn't exist.
                <details class="inline"><summary class="inline cursor-pointer text-yellow-300/80 underline">which</summary>
                <span class="block text-xs text-yellow-200/70 mt-1 space-y-0.5">${errored
                    .map(
                        (name) =>
                            `<span class="block"><b class="text-yellow-100">${escapeHtml(name)}</b>${
                                this.errorReasons[name] ? ` - ${escapeHtml(this.errorReasons[name])}` : ''
                            }</span>`
                    )
                    .join('')}</span></details></span>
            <button type="button" class="px-3 py-1.5 rounded-lg bg-yellow-700/60 hover:bg-yellow-600/70 text-white shrink-0">Retry ${errored.length} site${errored.length === 1 ? '' : 's'}</button>`;
        box.querySelector('button').addEventListener('click', () => this.startSearch(errored));
        // Below the search box and its options, above the counts
        const anchor = document.getElementById('mailboxOption') || this.elements.stopBtn.parentElement;
        anchor.insertAdjacentElement('afterend', box);
    }

    stopSearch() {
        if (this.eventSource) {
            this.eventSource.close();
            this.eventSource = null;
        }

        this.searchActive = false;
        this.retrying = false;
        this.finishMailboxes();
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
        search.lastUsername = data.username || '';
        // Email providers checked with this search: found addresses, and the others by domain
        if (data.mailboxes || data.mailbox_checks) {
            search.resetMailboxes(true);
            (data.mailboxes || []).forEach((mailbox) => search.addMailboxResult(mailbox));
            Object.entries(data.mailbox_checks || {}).forEach(([status, entries]) =>
                (entries || []).forEach((entry) =>
                    search.addMailboxResult({
                        provider: entry.provider,
                        email: `${data.username}@${entry.domain}`,
                        status,
                        reason: entry.reason,
                        details: /permission/i.test(entry.reason || '') ? { needs_permission: true } : {},
                    })
                )
            );
            search.finishMailboxes();
            search.loadMailboxStatus().then(() => search.queueMailboxes());
        }

        // Update stats
        if (data.stats) {
            search.stats.total = data.stats.total || 0;
            search.stats.scanned = data.stats.checked || data.stats.scanned || data.stats.total || 0;
            search.stats.unchecked = data.stats.errors || 0;
            search.updateStats();
        }
        const input = document.getElementById('usernameSearchInput');
        if (data.username && input) input.value = data.username;

        // Load results
        if (data.results && Array.isArray(data.results)) {
            data.results.forEach((result) => {
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
