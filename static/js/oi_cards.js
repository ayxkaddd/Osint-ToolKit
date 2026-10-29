// OSINT Industries results, shared by the OSINT Industries page (streamed, OiResultsView)
// and saved results (oiResultsHtml). Cards come from services/oi_service.py:normalize_oi.
// Three sections: breaches, accounts with profile data, sites where an account just exists.

const OI_STAT_LABEL = /follower|following|friend|subscriber|post|repo|review|connection|like|karma|\bxp\b/i;
const OI_INFO_KEYS = ['name', 'username', 'email', 'phone', 'picture', 'bio', 'location', 'account_id', 'age', 'website', 'created', 'last_seen'];

function oiCompact(value) {
    return new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 }).format(value);
}

function oiValue(value) {
    if (typeof value === 'boolean') return value ? 'yes' : 'no';
    if (typeof value === 'number') return value.toLocaleString();
    return String(value);
}

function oiKind(card) {
    if (card.breach) return 'breach';
    return OI_INFO_KEYS.some(k => card[k] !== undefined && card[k] !== null && card[k] !== '') || (card.fields || []).length
        ? 'profile' : 'registered';
}

function oiLink(url, label, cls = 'text-blue-400 hover:underline') {
    const safe = safeUrl(url);
    return safe ? `<a href="${escapeAttr(safe)}" target="_blank" rel="noopener noreferrer" class="${cls}">${label}</a>` : '';
}

function oiWebsiteUrl(site) {
    return site ? (/^https?:/i.test(site) ? site : `https://${site}`) : '';
}

function oiDetails(fields, openCount = 4) {
    if (!fields.length) return '';
    const row = f => `<div class="flex justify-between gap-4 py-1 border-t border-gray-800/70 first:border-t-0">
        <dt class="text-gray-500 shrink-0">${escapeHtml(f.label)}</dt>
        <dd class="text-gray-200 text-right break-words min-w-0">${escapeHtml(oiValue(f.value))}</dd></div>`;
    const shown = fields.length > openCount + 1 ? fields.slice(0, openCount) : fields;
    const hidden = fields.slice(shown.length);
    return `<dl class="mt-3 text-sm">${shown.map(row).join('')}</dl>
        ${hidden.length ? `<details class="text-sm"><summary class="cursor-pointer text-gray-500 hover:text-gray-300 py-1 select-none">${hidden.length} more</summary>
            <dl>${hidden.map(row).join('')}</dl></details>` : ''}`;
}

function oiAvatar(url, label) {
    const safe = safeUrl(url);
    const letter = escapeHtml((label || '?').trim().charAt(0).toUpperCase());
    return `<div class="relative w-11 h-11 rounded-lg bg-gray-800 shrink-0 overflow-hidden flex items-center justify-center text-gray-400 font-semibold">${letter}
        ${safe ? `<img src="${escapeAttr(safe)}" alt="" loading="lazy" referrerpolicy="no-referrer" class="absolute inset-0 w-full h-full object-cover" onerror="this.remove()">` : ''}</div>`;
}

function oiProfileCard(card) {
    const fields = card.fields || [];
    const stats = fields.filter(f => typeof f.value === 'number' && OI_STAT_LABEL.test(f.label));
    const badges = fields.filter(f => f.value === true);
    // false flags ("private: no") say nothing worth a row
    const rest = fields.filter(f => !stats.includes(f) && !badges.includes(f) && f.value !== false);
    const title = card.name || '';
    const facts = [
        card.location,
        card.age && `${card.age} y/o`,
        card.gender,
        card.created && `joined ${String(card.created).slice(0, 10)}`,
        card.last_seen && `seen ${String(card.last_seen).slice(0, 10)}`,
    ].filter(Boolean);
    const chips = [
        card.username ? pivotChip('username', String(card.username)) : '',
        card.email ? pivotChip('email', String(card.email)) : '',
        card.phone ? pivotChip('phone', String(card.phone)) : '',
    ].join('');
    if (card.account_id) rest.unshift({ label: 'ID', value: card.account_id });
    return `
        <article class="bg-gray-950/60 rounded-xl p-4 border border-gray-800 hover:border-gray-700 min-w-0">
            <header class="flex items-start gap-3">
                ${oiAvatar(card.picture, card.module)}
                <div class="min-w-0 flex-1">
                    <div class="flex items-baseline justify-between gap-2">
                        <h4 class="text-white font-semibold truncate">${escapeHtml(card.module)}</h4>
                        <span class="flex items-center gap-3 text-xs shrink-0">
                            ${oiLink(oiWebsiteUrl(card.website), 'site')}
                            ${oiLink(card.profile_url, 'open profile')}
                        </span>
                    </div>
                    ${card.category ? `<div class="text-xs text-gray-500">${escapeHtml(card.category)}</div>` : ''}
                </div>
            </header>
            ${title ? `<div class="mt-3 text-base text-gray-100 font-medium break-words">${escapeHtml(title)}</div>` : ''}
            ${chips ? `<div class="flex flex-wrap gap-1.5 mt-2">${chips}</div>` : ''}
            ${facts.length ? `<div class="mt-2 text-sm text-gray-400">${facts.map(f => escapeHtml(f)).join('<span class="text-gray-600 mx-1.5">·</span>')}</div>` : ''}
            ${stats.length ? `<div class="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm">${stats.map(f =>
                `<span title="${escapeAttr(oiValue(f.value))}"><span class="text-white font-semibold">${escapeHtml(oiCompact(f.value))}</span> <span class="text-gray-500">${escapeHtml(f.label.toLowerCase())}</span></span>`).join('')}</div>` : ''}
            ${badges.length ? `<div class="mt-2 flex flex-wrap gap-1.5">${badges.map(f =>
                `<span class="px-2 py-0.5 rounded-full text-xs bg-purple-500/10 text-purple-300 border border-purple-500/20">${escapeHtml(f.label.toLowerCase())}</span>`).join('')}</div>` : ''}
            ${card.bio ? `<p class="mt-3 text-sm text-gray-300 leading-relaxed break-words line-clamp-3" title="${escapeAttr(card.bio)}">${escapeHtml(card.bio)}</p>` : ''}
            ${oiDetails(rest)}
        </article>`;
}

function oiBreachRow(card) {
    const fields = card.fields || [];
    const count = fields.find(f => /count|records/i.test(f.label) && typeof f.value === 'number');
    const classes = fields.find(f => /data classes/i.test(f.label));
    const rest = fields.filter(f => f !== count && f !== classes);
    const tags = classes ? String(classes.value).split(/,\s*/).filter(Boolean) : [];
    return `
        <article class="flex gap-3 py-3 border-t border-gray-800 first:border-t-0 min-w-0">
            ${oiAvatar(card.picture, card.name || card.module)}
            <div class="min-w-0 flex-1">
                <div class="flex items-baseline justify-between gap-3">
                    <h4 class="text-white font-semibold truncate">${escapeHtml(card.name || card.module)}</h4>
                    ${card.created ? `<span class="text-sm text-gray-400 shrink-0">${escapeHtml(String(card.created).slice(0, 10))}</span>` : ''}
                </div>
                <div class="text-sm text-gray-500">
                    ${[card.website && oiLink(oiWebsiteUrl(card.website), escapeHtml(card.website)),
                       count && `${escapeHtml(oiCompact(count.value))} accounts leaked`].filter(Boolean).join('<span class="mx-1.5">·</span>')}
                </div>
                ${tags.length ? `<div class="mt-2 flex flex-wrap gap-1.5">${tags.map(t =>
                    `<span class="px-2 py-0.5 rounded-md text-xs ${/password|credit|ssn|security/i.test(t) ? 'bg-red-500/15 text-red-300' : 'bg-gray-800 text-gray-300'}">${escapeHtml(t)}</span>`).join('')}</div>` : ''}
                ${rest.length ? `<details class="text-sm mt-1"><summary class="cursor-pointer text-gray-500 hover:text-gray-300 py-1 select-none">Details</summary>${oiDetails(rest, rest.length)}</details>` : ''}
            </div>
        </article>`;
}

function oiRegisteredChip(card) {
    const label = escapeHtml(card.module);
    const cls = 'inline-flex items-center px-2.5 py-1 rounded-md bg-gray-800/80 border border-gray-700/60 text-sm text-gray-200';
    return safeUrl(card.profile_url)
        ? oiLink(card.profile_url, label, `${cls} hover:border-blue-500/60 hover:text-white`)
        : `<span class="${cls}" ${card.category ? `title="${escapeAttr(card.category)}"` : ''}>${label}</span>`;
}

const OI_SECTIONS = [
    { kind: 'breach', title: 'Data breaches', icon: 'shield-alert', tone: 'text-red-300', body: 'rounded-xl border border-red-900/40 bg-red-950/10 px-4 py-1', render: oiBreachRow },
    { kind: 'profile', title: 'Accounts with profile data', icon: 'user-round', tone: 'text-gray-200', body: 'grid grid-cols-1 md:grid-cols-2 gap-3 items-start', render: oiProfileCard },
    { kind: 'registered', title: 'Registered, no public details', icon: 'check', tone: 'text-gray-400', body: 'flex flex-wrap gap-2', render: oiRegisteredChip },
];

function oiSectionHtml(section, inner, count) {
    return `
        <section data-oi-section="${section.kind}" class="mt-6 first:mt-0 ${count ? '' : 'hidden'}">
            <h3 class="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide ${section.tone} mb-3">
                <i data-lucide="${section.icon}" class="w-4 h-4"></i>${section.title}
                <span data-oi-count class="text-gray-500 font-normal normal-case tracking-normal">${count}</span>
            </h3>
            <div data-oi-body class="${section.body}">${inner}</div>
        </section>`;
}

// Saved results: all cards at once
function oiResultsHtml(cards) {
    const found = (cards || []).filter(c => c.registered !== false);
    if (!found.length) return '<p class="text-sm text-gray-400">No accounts found.</p>';
    return OI_SECTIONS.map(section => {
        const items = found.filter(c => oiKind(c) === section.kind);
        return items.length ? oiSectionHtml(section, items.map(section.render).join(''), items.length) : '';
    }).join('');
}

// Live results: cards are appended as modules finish; a text filter and a category filter apply to all
class OiResultsView {
    constructor(root) {
        this.root = root;
        this.total = 0;
        this.categories = new Map();
        root.innerHTML = `
            <div data-oi-filters class="hidden flex flex-col sm:flex-row gap-2 mb-5">
                <input type="search" data-oi-filter placeholder="Filter by site, name, username, location…" class="field field-sm flex-1">
                <select data-oi-category class="field field-sm sm:w-56"><option value="">All categories</option></select>
            </div>
            <p data-oi-empty class="hidden text-sm text-gray-400">No accounts match the filter.</p>
            ${OI_SECTIONS.map(s => oiSectionHtml(s, '', 0)).join('')}`;
        this.filterInput = root.querySelector('[data-oi-filter]');
        this.categorySelect = root.querySelector('[data-oi-category]');
        this.filterInput.addEventListener('input', () => this.applyFilter());
        this.categorySelect.addEventListener('change', () => this.applyFilter());
    }

    section(kind) {
        return this.root.querySelector(`[data-oi-section="${kind}"]`);
    }

    add(cards) {
        for (const card of cards || []) {
            if (card.registered === false) continue;
            const kind = oiKind(card);
            const spec = OI_SECTIONS.find(s => s.kind === kind);
            const section = this.section(kind);
            const body = section.querySelector('[data-oi-body]');
            body.insertAdjacentHTML('beforeend', spec.render(card));
            const el = body.lastElementChild;
            el.dataset.oiText = [card.module, card.slug, card.name, card.username, card.email, card.phone, card.location, card.bio, card.website,
                ...(card.fields || []).map(f => f.value)].filter(v => v !== undefined && v !== null).join(' ').toLowerCase();
            el.dataset.oiCategory = card.breach ? 'Data breaches' : (card.category || '');
            el.classList.toggle('hidden', !this.matches(el));
            section.classList.remove('hidden');
            this.total += 1;
            const category = el.dataset.oiCategory;
            if (category) this.categories.set(category, (this.categories.get(category) || 0) + 1);
        }
        this.updateCounts();
        this.updateCategories();
        this.root.querySelector('[data-oi-filters]').classList.toggle('hidden', this.total < 6);
        if (window.lucide) lucide.createIcons();
    }

    matches(el) {
        const text = this.filterInput.value.trim().toLowerCase();
        const category = this.categorySelect.value;
        return (!text || el.dataset.oiText.includes(text)) && (!category || el.dataset.oiCategory === category);
    }

    applyFilter() {
        this.root.querySelectorAll('[data-oi-text]').forEach(el => el.classList.toggle('hidden', !this.matches(el)));
        this.updateCounts();
    }

    updateCounts() {
        let visible = 0;
        for (const { kind } of OI_SECTIONS) {
            const section = this.section(kind);
            const items = section.querySelectorAll('[data-oi-text]');
            const shown = [...items].filter(el => !el.classList.contains('hidden')).length;
            visible += shown;
            section.querySelector('[data-oi-count]').textContent = shown === items.length ? items.length : `${shown} of ${items.length}`;
            section.classList.toggle('hidden', !shown);
        }
        this.root.querySelector('[data-oi-empty]').classList.toggle('hidden', !this.total || visible > 0);
    }

    updateCategories() {
        const current = this.categorySelect.value;
        const options = [...this.categories.entries()].sort((a, b) => b[1] - a[1]);
        this.categorySelect.innerHTML = `<option value="">All categories</option>` + options.map(([name, n]) =>
            `<option value="${escapeAttr(name)}" ${name === current ? 'selected' : ''}>${escapeHtml(name)} (${n})</option>`).join('');
    }

    counts() {
        const count = kind => this.section(kind).querySelectorAll('[data-oi-text]').length;
        return { breaches: count('breach'), accounts: count('profile') + count('registered') };
    }
}
