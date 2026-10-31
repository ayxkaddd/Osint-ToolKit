// OSINT Industries results, shared by the OSINT Industries page (streamed, OiResultsView)
// and saved results (oiResultsHtml). Cards come from services/oi_service.py:normalize_oi
// and use the username search card styles (static/css/services/username.css) and its
// packed columns (static/js/masonry.js).
// Layout: counts, a summary of who the accounts point to (photos, names, usernames, places,
// a timeline), then breaches, accounts with profile data, and sites where an account just exists.

const OI_STAT_LABEL = /follower|following|friend|subscriber|post|repo|review|connection|like|karma|\bxp\b/i;
const OI_INFO_KEYS = ['name', 'username', 'email', 'phone', 'picture', 'bio', 'location', 'account_id', 'age', 'website', 'created', 'last_seen'];
const OI_SENSITIVE = /password|credit|ssn|security|bank/i;
const OI_ROWS_SHOWN = 8;

function oiCompact(value) {
    return new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 }).format(value);
}

function oiValue(value) {
    if (typeof value === 'boolean') return value ? 'Yes' : 'No';
    if (typeof value === 'number') return value.toLocaleString();
    return String(value);
}

function oiKind(card) {
    if (card.breach) return 'breach';
    return OI_INFO_KEYS.some(k => card[k] !== undefined && card[k] !== null && card[k] !== '') || (card.fields || []).length
        ? 'profile' : 'registered';
}

function oiWebsiteUrl(site) {
    return site ? (/^https?:/i.test(site) ? site : `https://${site}`) : '';
}

function oiIconUrl(card) {
    return card.domain ? `/api/oi/icon/${encodeURIComponent(card.domain)}` : '';
}

// OSINT Industries' own module icon; modules named after a domain get its favicon instead
function oiModuleIcons(card) {
    const slug = String(card.slug || card.module || '').trim().toLowerCase();
    if (slug.includes('.')) return [`/api/oi/icon/${encodeURIComponent(slug)}`, oiIconUrl(card)];
    return [slug ? `https://cdn.osint.industries/modules/${encodeURIComponent(slug)}.png` : '', oiIconUrl(card)];
}

// Site icon like the username cards: the first image that loads, else two letters
function oiSiteMark(urls, label) {
    const [src, next] = urls.map(u => safeUrl(u)).filter(Boolean);
    const letters = escapeHtml(String(label || '').replace(/[^\p{L}\p{N}]/gu, '').slice(0, 2).toUpperCase() || '?');
    const fallback = `<div class="platform-icon bg-gray-600${src ? ' username-site-mark-fallback' : ''}">${letters}</div>`;
    if (!src) return `<div class="username-site-mark">${fallback}</div>`;
    const giveUp = "this.style.display='none';this.nextElementSibling.style.display='flex'";
    const onerror = next ? `if(this.dataset.next){this.src=this.dataset.next;this.removeAttribute('data-next')}else{${giveUp}}` : giveUp;
    return `<div class="username-site-mark">
        <img src="${escapeAttr(src)}" ${next ? `data-next="${escapeAttr(next)}"` : ''} alt="" loading="lazy" referrerpolicy="no-referrer" onerror="${onerror}">
        ${fallback}</div>`;
}

function oiAvatar(url) {
    const encoded = encodeURIComponent(url);
    return `
        <div class="username-card-media">
            <button type="button" data-image-view="${escapeAttr(url)}" data-image-title="Profile picture" class="username-avatar-preview-btn" title="Preview profile picture">
                <img src="${escapeAttr(url)}" alt="" loading="lazy" referrerpolicy="no-referrer" class="username-card-avatar"
                    onerror="this.closest('.username-result-card').classList.remove('has-profile-image'); this.closest('.username-card-media').style.display='none';">
            </button>
            <div class="username-reverse-search" aria-label="Reverse image search">
                <a href="https://lens.google.com/uploadbyurl?url=${encoded}" target="_blank" rel="noopener noreferrer" title="Google reverse image search"><i class="fab fa-google"></i></a>
                <a href="https://yandex.com/images/search?rpt=imageview&url=${encoded}" target="_blank" rel="noopener noreferrer" title="Yandex reverse image search"><i class="fas fa-search"></i></a>
            </div>
        </div>`;
}

// rows are [label, value] or [label, value, identifier type] (plugin cards know the type)
function oiRow(label, value, type = null) {
    const text = oiValue(value);
    // emails, phones, usernames... open the "look up with" menu (OI and plugin cards)
    const shown = type ? pivotText(type, value, text)
        : typeof value === 'string' ? pivotField(label, value, text) : escapeHtml(text);
    return `<div class="username-data-row"><strong>${escapeHtml(label)}</strong><span title="${escapeAttr(text)}">${shown}</span></div>`;
}

// The first rows, the rest behind the "more" button in the card footer
function oiRows(rows) {
    const shown = rows.length > OI_ROWS_SHOWN + 1 ? rows.slice(0, OI_ROWS_SHOWN) : rows;
    const hidden = rows.slice(shown.length);
    return {
        html: shown.map(([label, value, type]) => oiRow(label, value, type)).join('')
            + (hidden.length ? `<div data-oi-more class="hidden">${hidden.map(([label, value, type]) => oiRow(label, value, type)).join('')}</div>` : ''),
        hidden: hidden.length,
    };
}

function oiActions(url, label, hiddenRows) {
    const safe = safeUrl(url);
    if (!safe && !hiddenRows) return '';
    return `
        <div class="username-card-actions">
            ${safe ? `<a href="${escapeAttr(safe)}" target="_blank" rel="noopener noreferrer" title="${escapeAttr(url)}">
                <i class="fas fa-external-link-alt"></i><span>${label}</span></a>` : '<span></span>'}
            ${hiddenRows ? `<button type="button" data-oi-more-toggle data-count="${hiddenRows}"><i class="fas fa-chevron-down"></i><span>${hiddenRows} more</span></button>` : ''}
        </div>`;
}

function oiFilterText(card) {
    return [card.module, card.slug, card.name, card.username, card.email, card.phone, card.location, card.bio, card.website,
        ...(card.fields || []).map(f => f.value)].filter(v => v !== undefined && v !== null).join(' ').toLowerCase();
}

function oiShell(card, kind, picture, inner) {
    return `
        <div class="result-card username-result-card fade-in${picture ? ' has-profile-image' : ''}${kind === 'breach' ? ' !border-red-500/30' : ''}"
            data-oi-text="${escapeAttr(oiFilterText(card))}" data-oi-category="${escapeAttr(card.breach ? 'Data breaches' : (card.category || 'Other'))}">
            ${inner}
        </div>`;
}

function oiHeader(title, subtitle, iconUrls, picture, subtitleClass = '') {
    return `
        <div class="username-card-header">
            <div class="username-card-heading">
                ${oiSiteMark(iconUrls, title)}
                <div class="username-card-title">
                    <h3 title="${escapeAttr(title)}">${escapeHtml(title)}</h3>
                    ${subtitle ? `<span class="${subtitleClass}">${escapeHtml(subtitle)}</span>` : ''}
                </div>
            </div>
            ${picture ? oiAvatar(picture) : ''}
        </div>`;
}

function oiProfileCard(card) {
    const fields = card.fields || [];
    const stats = fields.filter(f => typeof f.value === 'number' && OI_STAT_LABEL.test(f.label));
    // false flags ("private: no") say nothing worth a row
    const rest = fields.filter(f => !stats.includes(f) && f.value !== false);
    const rows = [
        ['Name', card.name], ['Email', card.email], ['Phone', card.phone], ['Location', card.location],
        ['Age', card.age], ['Gender', card.gender],
        ['Joined', card.created && String(card.created).slice(0, 10)],
        ['Last seen', card.last_seen && String(card.last_seen).slice(0, 10)],
        ['Website', card.website], ['ID', card.account_id],
        ...rest.map(f => [f.label, f.value]),
    ].filter(([, value]) => value !== undefined && value !== null && value !== '');
    const { html, hidden } = oiRows(rows);
    const picture = safeUrl(card.picture);
    return oiShell(card, oiKind(card), picture, `
        ${oiHeader(card.module, card.category || 'account', oiModuleIcons(card), picture)}
        ${card.username ? `
            <div class="username-handle-row">
                <span title="@${escapeAttr(String(card.username))}">${pivotText('username', String(card.username), '@' + card.username)}</span>
                <button type="button" class="copy-username-btn" data-oi-copy="${escapeAttr(String(card.username))}" title="Copy username"><i class="fas fa-copy"></i></button>
            </div>` : ''}
        ${card.bio || html || stats.length ? `
            <div class="username-card-content">
                ${card.bio ? `<p class="username-card-bio" title="${escapeAttr(card.bio)}">${pivotInText(card.bio)}</p>` : ''}
                ${html}
                ${stats.length ? `<div class="username-mini-stats">${stats.slice(0, 6).map(f => `
                    <div title="${escapeAttr(oiValue(f.value))}"><span>${escapeHtml(f.label)}</span><strong>${escapeHtml(oiCompact(f.value))}</strong></div>`).join('')}
                </div>` : ''}
            </div>` : ''}
        ${oiActions(card.profile_url, 'View', hidden)}`);
}

function oiBreachCard(card) {
    const fields = card.fields || [];
    const count = fields.find(f => /count|records/i.test(f.label) && typeof f.value === 'number');
    const classes = fields.find(f => /data classes/i.test(f.label));
    const tags = classes ? String(classes.value).split(/,\s*/).filter(Boolean) : [];
    const name = card.name || card.module;
    const rows = [
        ['Breached', card.created && String(card.created).slice(0, 10)],
        ['Accounts leaked', count && oiCompact(count.value)],
        ['Website', card.website],
        ...fields.filter(f => f !== count && f !== classes).map(f => [f.label, f.value]),
    ].filter(([, value]) => value !== undefined && value !== null && value !== '');
    const { html, hidden } = oiRows(rows);
    return oiShell(card, 'breach', '', `
        ${oiHeader(name, 'data breach', [card.picture, oiIconUrl(card)], '', '!text-red-300')}
        <div class="username-card-content">
            ${tags.length ? `<div class="flex flex-wrap gap-1.5 mb-3">${tags.map(t =>
                `<span class="px-2 py-0.5 rounded-md text-xs ${OI_SENSITIVE.test(t) ? 'bg-red-500/15 text-red-300' : 'bg-gray-800/60 text-gray-300'}">${escapeHtml(t)}</span>`).join('')}</div>` : ''}
            ${html}
        </div>
        ${oiActions(oiWebsiteUrl(card.website), 'Website', hidden)}`);
}

function oiCardHtml(card) {
    return card.breach ? oiBreachCard(card) : oiProfileCard(card);
}

// Card buttons work the same on the live page and in saved results
document.addEventListener('click', (event) => {
    const copy = event.target.closest('[data-oi-copy]');
    if (copy) {
        navigator.clipboard.writeText(copy.dataset.oiCopy).then(() => {
            copy.innerHTML = '<i class="fas fa-check"></i>';
            setTimeout(() => { copy.innerHTML = '<i class="fas fa-copy"></i>'; }, 1500);
        }).catch(() => {});
        return;
    }
    const toggle = event.target.closest('[data-oi-more-toggle]');
    if (toggle) {
        const more = toggle.closest('.username-result-card').querySelector('[data-oi-more]');
        const open = !more.classList.toggle('hidden');
        toggle.innerHTML = open
            ? '<i class="fas fa-chevron-up"></i><span>Less</span>'
            : `<i class="fas fa-chevron-down"></i><span>${toggle.dataset.count} more</span>`;
    }
});

// ---------------------------------------------------------------------------
// Summary: what the accounts say about the person
// ---------------------------------------------------------------------------

function oiTally(cards, pick) {
    const tally = new Map();
    for (const card of cards) {
        const value = pick(card);
        if (!value) continue;
        const key = String(value).trim();
        const entry = tally.get(key.toLowerCase()) || { value: key, sources: [] };
        entry.sources.push(card.module);
        tally.set(key.toLowerCase(), entry);
    }
    return [...tally.values()].sort((a, b) => b.sources.length - a.sources.length);
}

function oiSummaryRow(icon, label, items, render, limit = 8) {
    if (!items.length) return '';
    const more = items.length - limit;
    return `
        <div class="flex gap-3 py-2 border-t border-[#24283b] first:border-t-0">
            <div class="w-28 shrink-0 flex items-center gap-2 text-xs text-gray-400 pt-1 self-start"><i data-lucide="${icon}" class="w-3.5 h-3.5"></i>${label}</div>
            <div class="flex flex-wrap gap-1.5 min-w-0">${items.slice(0, limit).map(render).join('')}
                ${more > 0 ? `<span class="text-xs text-gray-500 self-center">+${more} more</span>` : ''}</div>
        </div>`;
}

function oiTag(entry) {
    const n = entry.sources.length;
    return `<span class="inline-flex items-center gap-1.5 px-2 py-1 rounded-md bg-gray-800/40 text-sm text-gray-200" title="${escapeAttr(entry.sources.join(', '))}">${escapeHtml(entry.value)}${n > 1 ? `<span class="text-[11px] text-gray-500">×${n}</span>` : ''}</span>`;
}

function oiTimeline(cards) {
    const years = new Map();
    for (const card of cards) {
        const year = Number(String(card.created || '').slice(0, 4));
        if (!year || year < 1990 || year > 2100) continue;
        const entry = years.get(year) || { accounts: [], breaches: [] };
        (card.breach ? entry.breaches : entry.accounts).push(card.breach ? (card.name || card.module) : card.module);
        years.set(year, entry);
    }
    if (years.size < 2) return '';
    const last = Math.max(...years.keys());
    const first = Math.max(Math.min(...years.keys()), last - 19);
    const peak = Math.max(...[...years.values()].map(e => e.accounts.length + e.breaches.length));
    const pct = n => (n ? Math.max(6, Math.round((n / peak) * 100)) : 0);
    const columns = [];
    for (let year = first; year <= last; year++) {
        const e = years.get(year) || { accounts: [], breaches: [] };
        const title = [
            e.accounts.length && `${e.accounts.length} account${e.accounts.length === 1 ? '' : 's'} created: ${e.accounts.slice(0, 12).join(', ')}`,
            e.breaches.length && `${e.breaches.length} breach${e.breaches.length === 1 ? '' : 'es'}: ${e.breaches.slice(0, 12).join(', ')}`,
        ].filter(Boolean).join('\n');
        columns.push(`
            <div class="flex-1 min-w-0 flex flex-col items-center gap-1" title="${escapeAttr(`${year}${title ? '\n' + title : ''}`)}">
                <div class="w-full h-16 flex flex-col justify-end items-center">
                    ${e.breaches.length ? `<div class="w-full max-w-[18px] rounded-t-sm bg-red-400/70" style="height:${pct(e.breaches.length)}%"></div>` : ''}
                    ${e.accounts.length ? `<div class="w-full max-w-[18px] ${e.breaches.length ? '' : 'rounded-t-sm'} bg-purple-400/80" style="height:${pct(e.accounts.length)}%"></div>` : ''}
                </div>
                <div class="text-[10px] text-gray-500 tabular-nums">${(year === first || year === last || year % 5 === 0) ? year : '&nbsp;'}</div>
            </div>`);
    }
    return `
        <div class="pt-3 mt-1 border-t border-[#24283b]">
            <div class="flex items-center justify-between text-xs text-gray-400 mb-2">
                <span class="flex items-center gap-2"><i data-lucide="chart-column" class="w-3.5 h-3.5"></i>Timeline</span>
                <span class="flex gap-3 text-gray-500"><span class="flex items-center gap-1"><span class="w-2 h-2 rounded-sm bg-purple-400/80"></span>account created</span><span class="flex items-center gap-1"><span class="w-2 h-2 rounded-sm bg-red-400/70"></span>breach</span></span>
            </div>
            <div class="flex items-end gap-1">${columns.join('')}</div>
        </div>`;
}

function oiSummaryHtml(cards) {
    const accounts = cards.filter(c => !c.breach && c.registered !== false);
    const photos = oiTally(accounts, c => (safeUrl(c.picture) ? c.picture : null)).slice(0, 10);
    const rows = [
        oiSummaryRow('user-round', 'Names', oiTally(accounts, c => c.name), oiTag),
        oiSummaryRow('at-sign', 'Usernames', oiTally(accounts, c => c.username), e => pivotChip('username', e.value)),
        oiSummaryRow('mail', 'Emails', oiTally(accounts, c => c.email), e => pivotChip('email', e.value)),
        oiSummaryRow('phone', 'Phones', oiTally(accounts, c => c.phone || (c.fields || []).find(f => /phone hint/i.test(f.label))?.value), oiTag),
        oiSummaryRow('map-pin', 'Places', oiTally(accounts, c => c.location), oiTag, 6),
    ].join('');
    const timeline = oiTimeline(cards);
    if (!photos.length && !rows && !timeline) return '';
    return `
        <section class="username-category-section p-4 mb-4">
            ${photos.length ? `<div class="flex items-center gap-2 mb-3 overflow-x-auto pb-1">${photos.map(p => `
                <button type="button" data-image-view="${escapeAttr(safeUrl(p.value))}" data-image-title="${escapeAttr(p.sources.join(', ') || 'Photo')}" title="${escapeAttr(p.sources.join(', '))}" class="shrink-0">
                    <img src="${escapeAttr(safeUrl(p.value))}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.closest('button').remove()"
                        class="w-14 h-14 rounded-lg object-cover border border-[#293142] hover:border-purple-400/70"></button>`).join('')}
            </div>` : ''}
            ${rows}
            ${timeline}
        </section>`;
}

// ---------------------------------------------------------------------------
// Groups and counts
// ---------------------------------------------------------------------------

const OI_GROUPS = [
    { kind: 'breach', title: 'Data breaches', tone: 'text-red-300' },
    { kind: 'profile', title: 'Accounts with profile data', tone: 'text-white' },
    { kind: 'registered', title: 'Registered, no public details', tone: 'text-white' },
];

function oiStatsHtml({ accounts = 0, profile = 0, breach = 0, sites = '—' } = {}) {
    const stat = (key, label, value) => `<div class="username-stat"><span>${label}</span><strong data-oi-stat="${key}">${escapeHtml(String(value))}</strong></div>`;
    return `<div class="username-status-row">
        ${stat('accounts', 'Accounts', accounts)}${stat('profile', 'With profile data', profile)}${stat('breach', 'Breaches', breach)}${stat('sites', 'Sites answered', sites)}
    </div>`;
}

function oiGroupHtml(group, inner, count, attrs = '') {
    return `
        <section data-oi-group="${group.kind}" class="mt-6 first:mt-0 ${count ? '' : 'hidden'}">
            <h2 class="flex items-center gap-2 text-sm font-semibold ${group.tone} mb-3">${group.title}
                <span data-oi-count class="text-xs font-normal text-purple-300 tabular-nums">${count}</span></h2>
            <div class="username-masonry" ${attrs}>${inner}</div>
        </section>`;
}

// Saved results: all cards at once; masonryPackAll() lays out the columns after insertion
function oiResultsHtml(cards, sitesAnswered) {
    const found = (cards || []).filter(c => c.registered !== false);
    if (!found.length) return '<p class="text-sm text-gray-400">No accounts found.</p>';
    const byKind = kind => found.filter(c => oiKind(c) === kind);
    const profile = byKind('profile').length;
    const breach = byKind('breach').length;
    return oiStatsHtml({ accounts: found.length - breach, profile, breach, sites: sitesAnswered ?? '—' })
        + oiSummaryHtml(found)
        + OI_GROUPS.map(group => {
            const items = byKind(group.kind);
            return items.length ? oiGroupHtml(group, items.map(oiCardHtml).join(''), items.length, 'data-masonry-pack') : '';
        }).join('');
}

// Live results: cards are added as modules finish; text and category filters apply to all.
// Filtered-out cards are kept aside and the columns re-packed, so no gaps are left behind.
class OiResultsView {
    constructor(root) {
        this.root = root;
        this.cards = [];
        this.items = [];
        this.category = '';
        this.sites = '—';
        this.summaryQueued = false;
        root.innerHTML = `
            ${oiStatsHtml()}
            <div data-oi-summary></div>
            <div data-oi-filters class="hidden mb-5 space-y-3">
                <div class="relative">
                    <i data-lucide="search" class="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-gray-500 pointer-events-none"></i>
                    <input type="search" data-oi-filter placeholder="Filter by site, name, username, location…" class="field field-sm w-full !pl-9">
                </div>
                <div data-oi-categories class="flex flex-wrap gap-2"></div>
            </div>
            <p data-oi-empty class="hidden text-sm text-gray-400">No accounts match the filter.</p>
            ${OI_GROUPS.map(g => oiGroupHtml(g, '', 0)).join('')}`;
        this.filterInput = root.querySelector('[data-oi-filter]');
        this.filterInput.addEventListener('input', () => this.applyFilter());
        root.querySelector('[data-oi-categories]').addEventListener('click', (event) => {
            const button = event.target.closest('[data-oi-cat]');
            if (!button) return;
            this.category = button.dataset.oiCat === this.category ? '' : button.dataset.oiCat;
            this.applyFilter();
            this.updateCategories();
        });
        if (window.lucide) lucide.createIcons();
    }

    group(kind) {
        return this.root.querySelector(`[data-oi-group="${kind}"]`);
    }

    grid(kind) {
        return this.group(kind).querySelector('.username-masonry');
    }

    add(cards) {
        const template = document.createElement('template');
        for (const card of cards || []) {
            if (card.registered === false) continue;
            const kind = oiKind(card);
            template.innerHTML = oiCardHtml(card).trim();
            const el = template.content.firstElementChild;
            this.items.push({ kind, el });
            this.cards.push(card);
            if (this.matches(el)) {
                // Columns are measured, so the group must be visible before the card goes in
                this.group(kind).classList.remove('hidden');
                masonryAppend(this.grid(kind), el);
            }
        }
        this.updateCounts();
        this.updateCategories();
        this.root.querySelector('[data-oi-filters]').classList.toggle('hidden', this.cards.length < 6);
        this.queueSummary();
    }

    setSites(count) {
        this.sites = count;
        this.updateCounts();
    }

    // The summary is rebuilt from all cards, at most once per frame while results pour in
    queueSummary() {
        if (this.summaryQueued) return;
        this.summaryQueued = true;
        requestAnimationFrame(() => {
            this.summaryQueued = false;
            this.root.querySelector('[data-oi-summary]').innerHTML = oiSummaryHtml(this.cards);
            if (window.lucide) lucide.createIcons();
        });
    }

    matches(el) {
        const text = this.filterInput.value.trim().toLowerCase();
        return (!text || el.dataset.oiText.includes(text)) && (!this.category || el.dataset.oiCategory === this.category);
    }

    applyFilter() {
        for (const { kind } of OI_GROUPS) {
            const shown = this.items.filter(item => item.kind === kind && this.matches(item.el)).map(item => item.el);
            this.group(kind).classList.toggle('hidden', !shown.length);
            masonryLayout(this.grid(kind), shown);
        }
        this.updateCounts();
    }

    updateCounts() {
        let visible = 0;
        for (const { kind } of OI_GROUPS) {
            const total = this.items.filter(item => item.kind === kind).length;
            const shown = this.grid(kind).querySelectorAll('.username-result-card').length;
            visible += shown;
            this.group(kind).querySelector('[data-oi-count]').textContent = shown === total ? total : `${shown} of ${total}`;
            this.group(kind).classList.toggle('hidden', !shown);
        }
        this.root.querySelector('[data-oi-empty]').classList.toggle('hidden', !this.cards.length || visible > 0);
        const { accounts, breaches } = this.counts();
        const set = (key, value) => { this.root.querySelector(`[data-oi-stat="${key}"]`).textContent = value; };
        set('accounts', accounts);
        set('profile', this.items.filter(item => item.kind === 'profile').length);
        set('breach', breaches);
        set('sites', this.sites);
    }

    updateCategories() {
        const counts = new Map();
        this.items.forEach(({ el }) => counts.set(el.dataset.oiCategory, (counts.get(el.dataset.oiCategory) || 0) + 1));
        const pill = (value, label, n) => {
            const active = this.category === value;
            return `<button type="button" data-oi-cat="${escapeAttr(value)}" class="username-category-pill${active ? ' !border-purple-400/60 !bg-purple-500/15' : ''}">
                <span>${escapeHtml(label)}</span><strong>${n}</strong></button>`;
        };
        const sorted = [...counts.entries()].sort((a, b) => (b[0] === 'Data breaches') - (a[0] === 'Data breaches') || b[1] - a[1]);
        this.root.querySelector('[data-oi-categories]').innerHTML =
            pill('', 'All', this.items.length) + sorted.map(([name, n]) => pill(name, name, n)).join('');
    }

    counts() {
        const breaches = this.items.filter(item => item.kind === 'breach').length;
        return { breaches, accounts: this.items.length - breaches };
    }
}
