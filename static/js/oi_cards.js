// OSINT Industries results, shared by the OSINT Industries page (streamed, OiResultsView)
// and saved results (oiResultsHtml). Cards come from services/oi_service.py:normalize_oi.
// Layout: a summary of who the accounts point to (photos, names, usernames, places,
// a timeline), then breaches, accounts with profile data, and sites where an account just exists.

const OI_STAT_LABEL = /follower|following|friend|subscriber|post|repo|review|connection|like|karma|\bxp\b/i;
const OI_INFO_KEYS = ['name', 'username', 'email', 'phone', 'picture', 'bio', 'location', 'account_id', 'age', 'website', 'created', 'last_seen'];
// Letter placeholders until (or instead of) a site icon
const OI_TINTS = [
    'bg-purple-500/15 text-purple-300', 'bg-sky-500/15 text-sky-300', 'bg-emerald-500/15 text-emerald-300',
    'bg-amber-500/15 text-amber-300', 'bg-rose-500/15 text-rose-300', 'bg-indigo-500/15 text-indigo-300',
    'bg-teal-500/15 text-teal-300', 'bg-fuchsia-500/15 text-fuchsia-300',
];

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

function oiTint(text) {
    let hash = 0;
    for (const ch of String(text || '')) hash = (hash * 31 + ch.charCodeAt(0)) | 0;
    return OI_TINTS[Math.abs(hash) % OI_TINTS.length];
}

// First loadable image over a tinted letter; images that fail just disappear
function oiImage(urls, label, box) {
    const letter = escapeHtml((label || '?').trim().charAt(0).toUpperCase());
    const [src, next] = urls.map(u => safeUrl(u)).filter(Boolean);
    const onerror = next ? `this.onerror=()=>this.remove();this.src=this.dataset.next` : 'this.remove()';
    return `<span class="relative ${box} shrink-0 overflow-hidden inline-flex items-center justify-center font-semibold ${oiTint(label)}">${letter}
        ${src ? `<img src="${escapeAttr(src)}" ${next ? `data-next="${escapeAttr(next)}"` : ''} alt="" loading="lazy" referrerpolicy="no-referrer" class="absolute inset-0 w-full h-full object-cover bg-gray-900" onerror="${onerror}">` : ''}</span>`;
}

function oiIconUrl(card) {
    return card.domain ? `/api/oi/icon/${encodeURIComponent(card.domain)}` : '';
}

function oiSiteIcon(card, box = 'w-5 h-5 rounded text-[10px]') {
    return oiImage([oiIconUrl(card)], card.module, box);
}

function oiDetails(fields, openCount = 4) {
    if (!fields.length) return '';
    const row = f => `<div class="flex justify-between gap-4 py-1.5 border-t border-white/5 first:border-t-0">
        <dt class="text-gray-500 shrink-0">${escapeHtml(f.label)}</dt>
        <dd class="text-gray-200 text-right break-words min-w-0">${escapeHtml(oiValue(f.value))}</dd></div>`;
    const shown = fields.length > openCount + 1 ? fields.slice(0, openCount) : fields;
    const hidden = fields.slice(shown.length);
    return `<dl class="mt-3 text-sm">${shown.map(row).join('')}</dl>
        ${hidden.length ? `<details class="text-sm"><summary class="cursor-pointer text-gray-500 hover:text-gray-300 py-1 select-none">${hidden.length} more</summary>
            <dl>${hidden.map(row).join('')}</dl></details>` : ''}`;
}

function oiFact(icon, text) {
    return `<span class="inline-flex items-center gap-1.5"><i data-lucide="${icon}" class="w-3.5 h-3.5 text-gray-500"></i>${escapeHtml(text)}</span>`;
}

function oiProfileCard(card) {
    const fields = card.fields || [];
    const stats = fields.filter(f => typeof f.value === 'number' && OI_STAT_LABEL.test(f.label));
    const badges = fields.filter(f => f.value === true);
    // false flags ("private: no") say nothing worth a row
    const rest = fields.filter(f => !stats.includes(f) && !badges.includes(f) && f.value !== false);
    if (card.account_id) rest.unshift({ label: 'ID', value: card.account_id });
    const facts = [
        card.location && oiFact('map-pin', card.location),
        (card.age || card.gender) && oiFact('user-round', [card.age && `${card.age} y/o`, card.gender].filter(Boolean).join(', ')),
        card.created && oiFact('calendar-plus', `joined ${String(card.created).slice(0, 10)}`),
        card.last_seen && oiFact('eye', `seen ${String(card.last_seen).slice(0, 10)}`),
    ].filter(Boolean);
    const chips = [
        card.username ? pivotChip('username', String(card.username)) : '',
        card.email ? pivotChip('email', String(card.email)) : '',
        card.phone ? pivotChip('phone', String(card.phone)) : '',
    ].join('');
    const person = card.picture || card.name || chips;
    return `
        <article class="break-inside-avoid mb-3 rounded-xl border border-white/[0.07] bg-[#101119] hover:border-white/15 transition-colors min-w-0 overflow-hidden">
            <header class="flex items-center gap-2.5 px-4 py-2.5 bg-white/[0.025] border-b border-white/[0.06]">
                ${oiSiteIcon(card)}
                <h4 class="text-sm font-semibold text-white truncate">${escapeHtml(card.module)}</h4>
                ${card.category ? `<span class="text-[11px] px-1.5 py-0.5 rounded bg-white/5 text-gray-400 truncate">${escapeHtml(card.category)}</span>` : ''}
                <span class="ml-auto flex items-center gap-1 shrink-0">
                    ${oiLink(oiWebsiteUrl(card.website), '<i data-lucide="globe" class="w-4 h-4"></i>', 'p-1 rounded text-gray-500 hover:text-white hover:bg-white/5')}
                    ${oiLink(card.profile_url, '<i data-lucide="external-link" class="w-4 h-4"></i>', 'p-1 rounded text-gray-500 hover:text-white hover:bg-white/5')}
                </span>
            </header>
            <div class="p-4">
                ${person ? `<div class="flex items-center gap-3">
                    ${card.picture ? oiImage([card.picture], card.name || card.module, 'w-12 h-12 rounded-full text-base') : ''}
                    <div class="min-w-0">
                        ${card.name ? `<div class="text-base text-gray-50 font-medium break-words">${escapeHtml(card.name)}</div>` : ''}
                        ${chips ? `<div class="flex flex-wrap gap-1.5 mt-1">${chips}</div>` : ''}
                    </div>
                </div>` : ''}
                ${facts.length ? `<div class="${person ? 'mt-3' : ''} flex flex-wrap gap-x-4 gap-y-1 text-sm text-gray-400">${facts.join('')}</div>` : ''}
                ${stats.length || badges.length ? `<div class="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-sm">
                    ${stats.map(f => `<span title="${escapeAttr(oiValue(f.value))}"><span class="text-white font-semibold">${escapeHtml(oiCompact(f.value))}</span> <span class="text-gray-500">${escapeHtml(f.label.toLowerCase())}</span></span>`).join('')}
                    ${badges.map(f => `<span class="px-2 py-0.5 rounded-full text-xs bg-purple-500/10 text-purple-300 border border-purple-500/20">${escapeHtml(f.label.toLowerCase())}</span>`).join('')}
                </div>` : ''}
                ${card.bio ? `<p class="mt-3 text-sm text-gray-300 leading-relaxed break-words line-clamp-3" title="${escapeAttr(card.bio)}">${escapeHtml(card.bio)}</p>` : ''}
                ${oiDetails(rest)}
            </div>
        </article>`;
}

function oiBreachRow(card) {
    const fields = card.fields || [];
    const count = fields.find(f => /count|records/i.test(f.label) && typeof f.value === 'number');
    const classes = fields.find(f => /data classes/i.test(f.label));
    const rest = fields.filter(f => f !== count && f !== classes);
    const tags = classes ? String(classes.value).split(/,\s*/).filter(Boolean) : [];
    const name = card.name || card.module;
    return `
        <article class="flex gap-3.5 py-3.5 border-t border-white/[0.06] first:border-t-0 min-w-0">
            ${oiImage([card.picture, oiIconUrl(card)], name, 'w-10 h-10 rounded-lg text-sm')}
            <div class="min-w-0 flex-1">
                <div class="flex items-baseline justify-between gap-3">
                    <h4 class="text-white font-semibold truncate">${escapeHtml(name)}</h4>
                    ${card.created ? `<span class="text-sm text-gray-400 shrink-0 tabular-nums">${escapeHtml(String(card.created).slice(0, 10))}</span>` : ''}
                </div>
                <div class="text-sm text-gray-500">
                    ${[card.website && oiLink(oiWebsiteUrl(card.website), escapeHtml(card.website)),
                       count && `${escapeHtml(oiCompact(count.value))} accounts leaked`].filter(Boolean).join('<span class="mx-1.5">·</span>')}
                </div>
                ${tags.length ? `<div class="mt-2 flex flex-wrap gap-1.5">${tags.map(t =>
                    `<span class="px-2 py-0.5 rounded-md text-xs ${/password|credit|ssn|security|bank/i.test(t) ? 'bg-red-500/15 text-red-300' : 'bg-white/5 text-gray-300'}">${escapeHtml(t)}</span>`).join('')}</div>` : ''}
                ${rest.length ? `<details class="text-sm mt-1"><summary class="cursor-pointer text-gray-500 hover:text-gray-300 py-1 select-none">Details</summary>${oiDetails(rest, rest.length)}</details>` : ''}
            </div>
        </article>`;
}

function oiRegisteredChip(card) {
    const inner = `${oiSiteIcon(card, 'w-4 h-4 rounded-sm text-[9px]')}<span>${escapeHtml(card.module)}</span>`;
    const cls = 'inline-flex items-center gap-2 pl-2 pr-3 py-1.5 rounded-lg bg-white/[0.04] border border-white/[0.07] text-sm text-gray-200';
    return safeUrl(card.profile_url)
        ? oiLink(card.profile_url, inner, `${cls} hover:border-blue-500/50 hover:text-white`)
        : `<span class="${cls}" ${card.category ? `title="${escapeAttr(card.category)}"` : ''}>${inner}</span>`;
}

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
        <div class="flex gap-3 py-2 border-t border-white/[0.06] first:border-t-0">
            <div class="w-28 shrink-0 flex items-center gap-2 text-xs uppercase tracking-wide text-gray-500 pt-1 self-start"><i data-lucide="${icon}" class="w-3.5 h-3.5"></i>${label}</div>
            <div class="flex flex-wrap gap-1.5 min-w-0">${items.slice(0, limit).map(render).join('')}
                ${more > 0 ? `<span class="text-xs text-gray-500 self-center">+${more} more</span>` : ''}</div>
        </div>`;
}

function oiTag(entry) {
    const n = entry.sources.length;
    return `<span class="inline-flex items-center gap-1.5 px-2 py-1 rounded-md bg-white/[0.04] text-sm text-gray-200" title="${escapeAttr(entry.sources.join(', '))}">${escapeHtml(entry.value)}${n > 1 ? `<span class="text-[11px] text-gray-500">×${n}</span>` : ''}</span>`;
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
        <div class="pt-3 mt-1 border-t border-white/[0.06]">
            <div class="flex items-center justify-between text-xs uppercase tracking-wide text-gray-500 mb-2">
                <span class="flex items-center gap-2"><i data-lucide="chart-column" class="w-3.5 h-3.5"></i>Timeline</span>
                <span class="normal-case tracking-normal flex gap-3"><span class="flex items-center gap-1"><span class="w-2 h-2 rounded-sm bg-purple-400/80"></span>account created</span><span class="flex items-center gap-1"><span class="w-2 h-2 rounded-sm bg-red-400/70"></span>breach</span></span>
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
        <section class="rounded-xl border border-white/[0.07] bg-gradient-to-br from-purple-500/[0.07] via-transparent to-transparent p-4 mb-6">
            ${photos.length ? `<div class="flex items-center gap-2 mb-3 overflow-x-auto pb-1">${photos.map(p => `
                <a href="${escapeAttr(safeUrl(p.value))}" target="_blank" rel="noopener noreferrer" title="${escapeAttr(p.sources.join(', '))}" class="shrink-0">
                    ${oiImage([p.value], p.sources[0], 'w-14 h-14 rounded-xl text-lg ring-1 ring-white/10 hover:ring-purple-400/60')}</a>`).join('')}
            </div>` : ''}
            ${rows}
            ${timeline}
        </section>`;
}

// ---------------------------------------------------------------------------
// Sections
// ---------------------------------------------------------------------------

const OI_SECTIONS = [
    { kind: 'breach', title: 'Data breaches', icon: 'shield-alert', tone: 'text-red-300', body: 'rounded-xl border border-red-500/20 bg-red-500/[0.03] px-4 py-0.5', render: oiBreachRow },
    { kind: 'profile', title: 'Accounts with profile data', icon: 'id-card', tone: 'text-gray-200', body: 'columns-1 md:columns-2 gap-3', render: oiProfileCard },
    { kind: 'registered', title: 'Registered, no public details', icon: 'circle-check', tone: 'text-gray-300', body: 'flex flex-wrap gap-2', render: oiRegisteredChip },
];

function oiSectionHtml(section, inner, count) {
    return `
        <section data-oi-section="${section.kind}" class="mt-7 first:mt-0 ${count ? '' : 'hidden'}">
            <h3 class="flex items-center gap-2 text-sm font-semibold ${section.tone} mb-3">
                <i data-lucide="${section.icon}" class="w-4 h-4"></i>${section.title}
                <span data-oi-count class="px-1.5 rounded-md bg-white/5 text-xs text-gray-400 font-normal tabular-nums">${count}</span>
            </h3>
            <div data-oi-body class="${section.body}">${inner}</div>
        </section>`;
}

// Saved results: all cards at once
function oiResultsHtml(cards) {
    const found = (cards || []).filter(c => c.registered !== false);
    if (!found.length) return '<p class="text-sm text-gray-400">No accounts found.</p>';
    return oiSummaryHtml(found) + OI_SECTIONS.map(section => {
        const items = found.filter(c => oiKind(c) === section.kind);
        return items.length ? oiSectionHtml(section, items.map(section.render).join(''), items.length) : '';
    }).join('');
}

// Live results: cards are appended as modules finish; text and category filters apply to all
class OiResultsView {
    constructor(root) {
        this.root = root;
        this.cards = [];
        this.category = '';
        this.summaryQueued = false;
        root.innerHTML = `
            <div data-oi-summary></div>
            <div data-oi-filters class="hidden mb-6 space-y-3">
                <div class="relative">
                    <i data-lucide="search" class="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-gray-500 pointer-events-none"></i>
                    <input type="search" data-oi-filter placeholder="Filter by site, name, username, location…" class="field field-sm w-full !pl-9">
                </div>
                <div data-oi-categories class="flex flex-wrap gap-1.5"></div>
            </div>
            <p data-oi-empty class="hidden text-sm text-gray-400">No accounts match the filter.</p>
            ${OI_SECTIONS.map(s => oiSectionHtml(s, '', 0)).join('')}`;
        this.filterInput = root.querySelector('[data-oi-filter]');
        this.filterInput.addEventListener('input', () => this.applyFilter());
        root.querySelector('[data-oi-categories]').addEventListener('click', (event) => {
            const button = event.target.closest('[data-oi-cat]');
            if (!button) return;
            this.category = button.dataset.oiCat === this.category ? '' : button.dataset.oiCat;
            this.applyFilter();
            this.updateCategories();
        });
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
            el.dataset.oiCategory = card.breach ? 'Data breaches' : (card.category || 'Other');
            el.classList.toggle('hidden', !this.matches(el));
            this.cards.push(card);
        }
        this.updateCounts();
        this.updateCategories();
        this.root.querySelector('[data-oi-filters]').classList.toggle('hidden', this.cards.length < 6);
        this.queueSummary();
        if (window.lucide) lucide.createIcons();
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
        this.root.querySelector('[data-oi-empty]').classList.toggle('hidden', !this.cards.length || visible > 0);
    }

    updateCategories() {
        const counts = new Map();
        this.root.querySelectorAll('[data-oi-category]').forEach(el => counts.set(el.dataset.oiCategory, (counts.get(el.dataset.oiCategory) || 0) + 1));
        const chip = (value, label, n) => {
            const active = this.category === value;
            return `<button type="button" data-oi-cat="${escapeAttr(value)}" class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs border transition-colors ${active
                ? 'bg-purple-500/20 border-purple-400/50 text-white' : 'bg-white/[0.03] border-white/[0.08] text-gray-300 hover:border-white/20'}">${escapeHtml(label)}<span class="${active ? 'text-purple-200' : 'text-gray-500'} tabular-nums">${n}</span></button>`;
        };
        const sorted = [...counts.entries()].sort((a, b) => (b[0] === 'Data breaches') - (a[0] === 'Data breaches') || b[1] - a[1]);
        this.root.querySelector('[data-oi-categories]').innerHTML =
            chip('', 'All', this.cards.length) + sorted.map(([name, n]) => chip(name, name, n)).join('');
    }

    counts() {
        const count = kind => this.section(kind).querySelectorAll('[data-oi-text]').length;
        return { breaches: count('breach'), accounts: count('profile') + count('registered') };
    }
}
