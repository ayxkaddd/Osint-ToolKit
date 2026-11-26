// What we know: the case at a glance, beside the graph (GET .../graph/summary). Names,
// photos, places, contacts, accounts and breaches, counted over every record, however
// much of the graph is folded; clicking one shows it on the graph. Methods of GraphView.
import { CARD_KINDS, FACT_KINDS, cardColor } from './style.js';

const esc = (value) => window.escapeHtml(value);
const attr = (value) => window.escapeAttr(value);
const STORE_KEY = 'graphSummary';

export const summing = {
    buildSummary() {
        this.summary = this.root.querySelector('.graph-summary');
        this.summary.addEventListener('click', (e) => {
            if (e.target.closest('[data-summary-close]')) return this.toggleSummary(false);
            const reveal = e.target.closest('[data-reveal-node]');
            if (reveal) this.revealNode(reveal.dataset.revealNode);
        });
        let open = null;
        try {
            open = localStorage.getItem(STORE_KEY);
        } catch {
            /* the default */
        }
        // open at first where there is room for it beside the graph
        this.summaryWanted = open ? open === 'open' : this.root.clientWidth >= 1100;
    },

    summaryOpen() {
        return !this.summary.classList.contains('hidden');
    },

    // shown when ``open`` (or the other way round), remembered for the next case
    async toggleSummary(open = !this.summaryOpen()) {
        this.summaryWanted = open;
        try {
            localStorage.setItem(STORE_KEY, open ? 'open' : 'closed');
        } catch {
            /* this page only */
        }
        this.showSummary(open);
    },

    async showSummary(open) {
        this.summary.classList.toggle('hidden', !open);
        // it takes the left side: the legend and the counts are in it
        this.root.querySelector('.graph-legend').classList.toggle('hidden', open);
        this.stats.classList.toggle('hidden', open);
        this.root.querySelector('[data-summary-button]')?.classList.toggle('text-purple-300', open);
        if (open) {
            this.filterPanel.classList.add('hidden');
            this.tray.classList.add('hidden');
            await this.loadSummary();
        }
    },

    async loadSummary() {
        if (!this.summaryOpen()) return;
        if (!this.summary.innerHTML) this.summary.innerHTML = '<p class="p-4 text-gray-500">Loading…</p>';
        let data;
        try {
            data = await this.api('graph/summary');
        } catch (error) {
            this.summary.innerHTML = `<p class="p-4 text-red-400">Could not load it (${esc(error.message)}).</p>`;
            return;
        }
        this.summary.innerHTML = this.summaryHtml(data);
        window.refreshIcons?.();
    },

    summaryHtml(data) {
        const section = (title, inner, note = '') =>
            inner
                ? `<section class="px-4 py-3 border-b border-[#24283b]">
                    <h3 class="flex items-center justify-between text-[11px] uppercase tracking-wider text-gray-500 mb-2">${esc(title)}<span class="normal-case tracking-normal">${esc(note)}</span></h3>${inner}</section>`
                : '';
        const show = (id) =>
            `<button type="button" data-reveal-node="${attr(id)}" class="text-gray-500 hover:text-purple-300 shrink-0" title="Show it on the graph"><i data-lucide="crosshair" class="w-3.5 h-3.5"></i></button>`;
        const times = (n) => (n > 1 ? `<span class="text-xs text-gray-500 shrink-0">×${esc(n)}</span>` : '');
        // identifiers: the usual chip to look them up, and a way to them on the graph
        const identifiers = (rows) =>
            rows
                .map(
                    (r) => `
                <div class="flex items-center gap-2 py-0.5">
                    <span class="min-w-0 flex-1">${window.pivotChip(r.type, r.value, r.display)}</span>
                    ${r.searched ? '<span class="text-[10px] text-gray-500 shrink-0">looked up</span>' : ''}
                    ${times(r.sources)}${show(r.id)}
                </div>`
                )
                .join('');
        const c = data.counts || {};
        const kinds = Object.entries(c.kinds || {})
            .sort((a, b) => b[1] - a[1])
            .map(
                ([kind, n]) =>
                    `<span class="inline-flex items-center gap-1"><span class="w-2 h-2 rounded-sm" style="background:${attr(cardColor(kind))}"></span>${esc(n)} ${esc((CARD_KINDS[kind]?.plural || kind).toLowerCase())}</span>`
            )
            .join('');
        const dates =
            data.dates?.first && data.dates.first !== data.dates.last
                ? `${data.dates.first} – ${data.dates.last}`
                : data.dates?.first || '';
        const photos = (data.photos || [])
            .map(
                (p) =>
                    `<button type="button" data-reveal-node="${attr(p.id)}" title="${attr([p.title, p.subtitle].filter(Boolean).join(' · '))}" class="shrink-0"><img src="${attr(window.safeUrl(p.url))}" alt="" referrerpolicy="no-referrer" data-img-error="hideImage" class="w-12 h-12 rounded-lg object-cover border border-[#24283b] hover:border-purple-400"></button>`
            )
            .join('');
        const names = (data.names || [])
            .map(
                (n) => `
                <div class="flex items-center gap-2 py-0.5">
                    <span class="min-w-0 flex-1 truncate text-gray-200">${window.pivotChip('name', n.value, n.display)}</span>${times(n.sources)}${show(n.id)}
                </div>`
            )
            .join('');
        const places = (data.places || [])
            .map(
                (p) => `
                <div class="flex items-center gap-2 py-0.5">
                    <i data-lucide="map-pin" class="w-3.5 h-3.5 text-green-400 shrink-0"></i>
                    <span class="min-w-0 flex-1 truncate text-gray-200">${window.pivotInText(p.value)}</span>${times(p.count)}${show(p.id)}
                </div>`
            )
            .join('');
        const accounts = Object.entries(data.accounts || {})
            .map(
                ([category, n]) =>
                    `<span class="px-2 py-0.5 rounded-full bg-[#24283b] text-xs text-gray-300">${esc(category)} <span class="text-gray-500">${esc(n)}</span></span>`
            )
            .join('');
        const b = data.breaches || {};
        const breaches = (b.latest || [])
            .map(
                (x) => `
                <button type="button" data-reveal-node="${attr(x.id)}" class="w-full flex items-center gap-2 py-0.5 text-left hover:text-purple-300">
                    <i data-lucide="${x.flags?.includes('password') ? 'key-round' : 'shield-alert'}" class="w-3.5 h-3.5 shrink-0 ${x.flags?.includes('password') ? 'text-red-400' : 'text-orange-300'}"></i>
                    <span class="min-w-0 flex-1 truncate text-gray-200">${esc(x.title)}</span>
                    <span class="text-xs text-gray-500 shrink-0">${esc(x.date || '')}</span>
                </button>`
            )
            .join('');
        const shared = (data.shared_facts || [])
            .map(
                (f) => `
                <button type="button" data-reveal-node="${attr(f.id)}" class="w-full flex items-center gap-2 py-0.5 text-left hover:text-purple-300">
                    <i data-lucide="${attr(FACT_KINDS[f.fact]?.icon || 'link')}" class="w-3.5 h-3.5 shrink-0" style="color:${attr(FACT_KINDS[f.fact]?.color || '#fbbf24')}"></i>
                    <span class="min-w-0 flex-1 truncate text-gray-200">${esc(f.name)} · ${esc(f.label)}</span>
                    <span class="text-xs text-gray-500 shrink-0">${esc(f.cards)} records</span>
                </button>`
            )
            .join('');
        const s = this.statsData || {};
        return `
            <div class="sticky top-0 z-10 bg-[#1a1b26] flex items-start justify-between gap-2 px-4 py-3 border-b border-[#24283b]">
                <div class="min-w-0">
                    <div class="text-white font-semibold">What we know</div>
                    <div class="text-xs text-gray-500 mt-0.5">${esc(c.cards ?? 0)} records · ${esc(c.identifiers ?? 0)} identifiers · ${esc(c.lookups ?? 0)} lookups${dates ? ` · ${esc(dates)}` : ''}</div>
                </div>
                <button type="button" data-summary-close class="text-gray-400 hover:text-white" aria-label="Close"><i data-lucide="x" class="w-4 h-4"></i></button>
            </div>
            ${kinds ? `<div class="px-4 py-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-gray-300 border-b border-[#24283b]">${kinds}</div>` : ''}
            ${photos ? section('Photos', `<div class="flex flex-wrap gap-2">${photos}</div>`) : ''}
            ${section('Names', names)}
            ${section('Places', places)}
            ${section('Usernames', identifiers(data.usernames || []))}
            ${section('Emails', identifiers(data.emails || []))}
            ${section('Phones', identifiers(data.phones || []))}
            ${section('Accounts', accounts ? `<div class="flex flex-wrap gap-1.5">${accounts}</div>` : '', Object.values(data.accounts || {}).reduce((a, n) => a + n, 0) || '')}
            ${section('Breaches', breaches, b.count ? `${b.count}${b.passwords ? ` · ${b.passwords} with a password` : ''}` : '')}
            ${section('Shared by several records', shared)}
            ${section('Domains', identifiers(data.domains || []))}
            <p class="px-4 py-3 text-[11px] text-gray-500">Counted over every record in the case, folded or not${s.noise || s.false_positive ? `, without ${(s.noise || 0) + (s.false_positive || 0)} left out as noise or false positives` : ''}.</p>`;
    },
};
