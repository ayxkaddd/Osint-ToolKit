// Finding your way: search (also inside folded groups), focus on a node, filters,
// the path between two nodes, moving between nodes with the keyboard and the list of
// keys. Methods of GraphView (view.js).
import { spanningTree } from './layout.js';
import { MANUAL_TYPES, OFF, typeColor } from './style.js';
import { clip, typeName } from './view.js';

const esc = (value) => window.escapeHtml(value);
const attr = (value) => window.escapeAttr(value);
const REDUCED_MOTION = window.matchMedia('(prefers-reduced-motion: reduce)');
const motion = (ms) => (REDUCED_MOTION.matches ? 0 : ms);
const TRIAGE_FILTERS = {
    confirmed: 'Confirmed',
    important: 'Important',
    none: 'Not assessed',
    false_positive: 'False positive',
};

const KEYS = [
    ['Click', 'Open or fold a lookup or group; an identifier: its panel'],
    ['Double-click', 'Open every lookup under an identifier'],
    ['Right click / long press', 'The node’s menu'],
    ['Shift + drag', 'Select several nodes'],
    ['← ↑ → ↓', 'Move to a connected node'],
    ['Space', 'Open or fold the selected node'],
    ['/  or  Ctrl+F', 'Search'],
    ['F', 'Focus on the selected node (again: two steps)'],
    ['P', 'The path between two selected nodes'],
    ['H', 'Hide the selected nodes'],
    ['Delete', 'Take the selected nodes off the graph'],
    ['N', 'Add a node'],
    ['L', 'Link two nodes'],
    ['Ctrl+Z  /  Ctrl+Shift+Z', 'Undo / redo'],
    ['+  /  -  /  0', 'Zoom in / out / fit'],
    ['Esc', 'Close, clear the search, leave the focus or the path'],
    ['?', 'This list'],
];

export const finding = {
    // -----------------------------------------------------------------------
    // Search: what is drawn glows, what is folded is listed (from the server)
    // -----------------------------------------------------------------------
    openSearch() {
        this.searchBox.classList.remove('hidden');
        const input = this.searchBox.querySelector('input');
        input.focus();
        input.select();
    },

    closeSearch() {
        if (this.searchBox.classList.contains('hidden')) return false;
        this.searchBox.classList.add('hidden');
        this.searchBox.querySelector('input').value = '';
        this.searchBox.querySelector('[data-search-more]').innerHTML = '';
        this.cy.elements('.match, .search-dim').removeClass('match search-dim');
        this.matches = [];
        this.root.focus({ preventScroll: true });
        return true;
    },

    buildSearch() {
        this.searchBox = this.root.querySelector('.graph-search');
        const input = this.searchBox.querySelector('input');
        let timer;
        input.addEventListener('input', () => {
            this.searchHere(input.value);
            clearTimeout(timer);
            timer = setTimeout(() => this.searchFolded(input.value), 300);
        });
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                this.nextMatch(e.shiftKey ? -1 : 1);
            } else if (e.key === 'Escape') {
                e.preventDefault();
                e.stopPropagation();
                this.closeSearch();
            }
        });
        this.searchBox.addEventListener('click', (e) => {
            const reveal = e.target.closest('[data-reveal]');
            if (reveal) this.reveal(JSON.parse(reveal.dataset.reveal));
            if (e.target.closest('[data-search-close]')) this.closeSearch();
        });
    },

    searchHere(query) {
        const needle = query.trim().toLowerCase();
        this.cy.batch(() => {
            this.cy.elements('.match, .search-dim').removeClass('match search-dim');
            if (needle.length < 2) {
                this.matches = [];
                return;
            }
            const drawn = this.cy.nodes().not(OFF);
            const hits = drawn.filter((n) =>
                [n.data('value'), n.data('display'), n.data('label'), n.data('target')].some((v) =>
                    String(v ?? '')
                        .toLowerCase()
                        .includes(needle)
                )
            );
            hits.addClass('match');
            this.cy.elements().not(hits).addClass('search-dim');
            this.matches = hits.sort((a, b) => a.position('y') - b.position('y')).map((n) => n.id());
        });
        this.matchAt = -1;
        this.searchBox.querySelector('[data-search-count]').textContent =
            needle.length < 2 ? '' : `${this.matches.length} here`;
    },

    nextMatch(step) {
        if (!this.matches?.length) return;
        this.matchAt = (this.matchAt + step + this.matches.length) % this.matches.length;
        const node = this.cy.getElementById(this.matches[this.matchAt]);
        this.cy.$(':selected').unselect();
        node.select();
        this.moved = true;
        this.cy.animate({ center: { eles: node }, zoom: Math.max(this.cy.zoom(), 0.8) }, { duration: motion(250) });
        this.searchBox.querySelector('[data-search-count]').textContent =
            `${this.matchAt + 1} of ${this.matches.length}`;
    },

    // Matches that aren't drawn (in a folded group, under a closed lookup, hidden)
    async searchFolded(query) {
        const list = this.searchBox.querySelector('[data-search-more]');
        if (query.trim().length < 2) {
            list.innerHTML = '';
            return;
        }
        let found;
        try {
            found = await this.api('graph/search', { q: query.trim() });
        } catch {
            return;
        }
        if (this.searchBox.querySelector('input').value !== query) return;
        const away = found.matches.filter((m) => {
            const node = this.cy.getElementById(m.id);
            return !node.length || node.is(OFF);
        });
        list.innerHTML = away.length
            ? `<div class="px-3 pt-2 pb-1 text-[11px] uppercase tracking-wider text-gray-500">Not on screen${found.total > found.matches.length ? ` · first ${found.matches.length} of ${found.total}` : ''}</div>
               ${away
                   .map(
                       (
                           m
                       ) => `<button type="button" data-reveal="${attr(JSON.stringify(m))}" class="w-full flex items-center gap-2 px-3 py-1.5 text-left hover:bg-gray-800/70">
                        <span class="w-2 h-2 rounded-full shrink-0" style="background:${attr(typeColor(m.type))}"></span>
                        <span class="flex-1 min-w-0 truncate text-gray-200">${esc(m.display)}</span>
                        <span class="text-[10px] text-purple-300 shrink-0">${this.cy.getElementById(m.id).length ? 'show' : 'open'}</span></button>`
                   )
                   .join('')}`
            : '';
    },

    // Open what a match is folded in (its lookup, its group, the group's pages) and go to it
    async reveal(match) {
        const { lookup, group, offset } = match.reveal || {};
        const has = () => this.cy.getElementById(match.id).length > 0;
        if (!has() && lookup) {
            const node = this.cy.getElementById(lookup);
            if (node.length && !node.data('open')) await this.open(node, { record: true });
        }
        if (!has() && group) {
            const node = this.cy.getElementById(group);
            if (node.length && !node.data('open')) await this.open(node, { record: true });
            // the group opens 40 at a time: the pages up to it
            for (let page = 40; !has() && page <= (offset || 0); page += 40) {
                const more = this.cy.getElementById(`more:${group}:${page}`);
                if (!more.length) break;
                await this.loadMore(more, { record: true });
            }
        }
        const node = this.cy.getElementById(match.id);
        if (!node.length) {
            window.showTemporaryNotification?.('It could not be opened here (its lookup may be hidden)', 'error');
            return;
        }
        if (node.is(OFF)) {
            const s = this.state.data;
            const gone = [...s.hidden, ...s.removed];
            const { parentOf } = spanningTree(this.cy.nodes());
            // what hides it: itself or a node it hangs under
            const hiders = [];
            for (let id = node.id(); id; id = parentOf.get(id)) if (gone.includes(id)) hiders.push(id);
            if (hiders.length) await this.showNodes(hiders);
        }
        this.searchHere(this.searchBox.querySelector('input').value);
        this.searchFolded(this.searchBox.querySelector('input').value);
        this.focusNode(match.id);
        // the list was drawn again: the search keeps the keys (Esc, Enter)
        this.searchBox.querySelector('input').focus({ preventScroll: true });
    },

    // -----------------------------------------------------------------------
    // Focus: only a node and what is one (or two) steps from it
    // -----------------------------------------------------------------------
    focusOn(id) {
        this.cy.$(':selected').unselect();
        this.cy.getElementById(id).select();
        this.focus = null;
        this.toggleFocus();
    },

    toggleFocus() {
        const selected = this.cy.$('node:selected');
        const id = selected.length === 1 ? selected.id() : this.focus?.id;
        if (!id) {
            window.showTemporaryNotification?.('Select a node to focus on', 'info');
            return;
        }
        const depth = this.focus?.id === id && this.focus.depth === 1 ? 2 : 1;
        this.focus = { id, depth };
        this.refreshView();
        this.setMode(
            `Focus: ${clip(this.cy.getElementById(id).data('label')?.split('\n')[0] || id, 40)} · ${depth} step${depth > 1 ? 's' : ''} · F for ${depth === 1 ? 2 : 1} · Esc to leave`
        );
        this.fit();
    },

    leaveFocus() {
        if (!this.focus) return false;
        this.focus = null;
        this.refreshView();
        this.setMode('');
        this.fit();
        return true;
    },

    applyFocus() {
        this.cy.elements('.unfocused').removeClass('unfocused');
        if (!this.focus) return;
        const center = this.cy.getElementById(this.focus.id);
        if (!center.length) {
            this.focus = null;
            this.setMode('');
            return;
        }
        let near = center;
        for (let step = 0; step < this.focus.depth; step++) near = near.union(near.neighborhood('node'));
        this.cy.nodes().not(near).addClass('unfocused');
    },

    // -----------------------------------------------------------------------
    // Filters: by type, module, assessment, dates, other cases; noise from the server
    // -----------------------------------------------------------------------
    filters() {
        return {
            types: [],
            modules: [],
            triage: [],
            date_from: null,
            date_to: null,
            shared_only: false,
            noise: false,
            ...(this.state.data.filters || {}),
        };
    },

    filtersActive() {
        const f = this.filters();
        return !!(
            f.types.length ||
            f.modules.length ||
            f.triage.length ||
            f.date_from ||
            f.date_to ||
            f.shared_only ||
            f.noise
        );
    },

    // Shown: what matches, and the nodes on the way from a root to it (dimmed when they
    // don't match themselves). A lookup left out by module or date goes with its branch.
    applyFilters() {
        this.cy.elements('.filtered, .filter-dim').removeClass('filtered filter-dim');
        const f = this.filters();
        if (!this.filtersActive()) return;
        const day = (value) => (value ? String(value).slice(0, 10) : null);
        const lookupOut = (d) =>
            (f.modules.length && !f.modules.includes(d.service)) ||
            (f.date_from && day(d.timestamp) < f.date_from) ||
            (f.date_to && day(d.timestamp) > f.date_to);
        const identifierOut = (d) => {
            if (f.types.length && !f.types.includes(d.type)) return true;
            if (d.kind === 'manual') return false;
            if (f.triage.length && !f.triage.includes(d.status || 'none')) return true;
            if (f.shared_only && !d.shared) return true;
            if (f.date_from && day(d.last_seen) && day(d.last_seen) < f.date_from) return true;
            return !!(f.date_to && day(d.first_seen) && day(d.first_seen) > f.date_to);
        };
        // a group of accounts holds links; others, one identifier type
        const groupOut = (d) =>
            f.types.length > 0 && !f.types.includes(d.key.startsWith('type:') ? d.key.slice(5) : 'url');
        const { parentOf } = spanningTree(this.cy.nodes());
        let out = this.cy.collection();
        this.cy.nodes('[kind = "lookup"]').forEach((n) => {
            if (lookupOut(n.data())) out = out.union(n).union(this.branch(n, parentOf));
        });
        const dim = [];
        if (f.types.length || f.triage.length || f.shared_only || f.date_from || f.date_to) {
            const keep = new Set();
            const rest = this.cy.nodes().not(out);
            rest.forEach((n) => {
                const d = n.data();
                const passes =
                    d.kind === 'identifier' || d.kind === 'manual'
                        ? !identifierOut(d)
                        : d.kind === 'group'
                          ? !groupOut(d)
                          : d.kind === 'more'
                            ? !groupOut(this.cy.getElementById(d.of).data() || { key: '' })
                            : d.kind === 'pending';
                if (passes) for (let id = n.id(); id && !keep.has(id); id = parentOf.get(id)) keep.add(id);
            });
            rest.forEach((n) => {
                if (!keep.has(n.id())) out = out.union(n);
                else if (['identifier', 'manual'].includes(n.data('kind')) && identifierOut(n.data())) dim.push(n);
            });
        }
        this.cy.batch(() => {
            out.addClass('filtered');
            dim.forEach((n) => n.addClass('filter-dim'));
        });
    },

    toggleFilters() {
        if (!this.filterPanel.classList.contains('hidden')) {
            this.filterPanel.classList.add('hidden');
            return;
        }
        this.tray.classList.add('hidden');
        this.renderFilters();
        this.filterPanel.classList.remove('hidden');
    },

    renderFilters() {
        const f = this.filters();
        const types = new Map();
        const modules = new Map();
        this.cy.nodes().forEach((n) => {
            const d = n.data();
            if (d.kind === 'identifier' || d.kind === 'manual') types.set(d.type, (types.get(d.type) || 0) + 1);
            if (d.kind === 'lookup') modules.set(d.service, this.lookupName(d));
        });
        f.types.forEach((t) => types.has(t) || types.set(t, 0));
        f.modules.forEach((m) => modules.has(m) || modules.set(m, m));
        const box = (group, value, label, checked, extra = '') =>
            `<label class="flex items-center gap-2 py-0.5 text-gray-300 cursor-pointer"><input type="checkbox" class="pick-box" data-filter="${group}" value="${attr(value)}" ${checked ? 'checked' : ''}>${extra}<span class="truncate">${esc(label)}</span></label>`;
        const section = (title, inner) =>
            `<div class="px-3 py-2 border-b border-[#24283b]"><div class="text-[11px] uppercase tracking-wider text-gray-500 mb-1">${esc(title)}</div>${inner}</div>`;
        const dot = (type) =>
            `<span class="w-2 h-2 rounded-full shrink-0" style="background:${attr(typeColor(type))}"></span>`;
        this.filterPanel.innerHTML = `
            <div class="flex items-center justify-between px-3 py-2 border-b border-[#24283b]">
                <span class="text-white font-semibold">Show only</span>
                <button type="button" data-filter-clear class="text-xs text-purple-300 hover:text-white">Show everything</button>
            </div>
            ${section(
                'Identifiers',
                [...types.entries()]
                    .sort((a, b) => b[1] - a[1])
                    .map(([t, count]) => box('types', t, `${typeName(t)} · ${count}`, f.types.includes(t), dot(t)))
                    .join('') || '<p class="text-gray-500 text-xs">None drawn</p>'
            )}
            ${section('Modules', [...modules.entries()].map(([service, name]) => box('modules', service, name, f.modules.includes(service))).join('') || '<p class="text-gray-500 text-xs">None drawn</p>')}
            ${section(
                'Assessment',
                Object.entries(TRIAGE_FILTERS)
                    .filter(([v]) => v !== 'false_positive' || f.noise)
                    .map(([v, label]) => box('triage', v, label, f.triage.includes(v)))
                    .join('')
            )}
            ${section(
                'Seen',
                `<div class="flex items-center gap-2"><input type="date" data-filter-date="date_from" value="${attr(f.date_from || '')}" class="flex-1 bg-gray-950 border border-gray-700 rounded px-2 py-1 text-xs text-white"><span class="text-gray-500 text-xs">to</span><input type="date" data-filter-date="date_to" value="${attr(f.date_to || '')}" class="flex-1 bg-gray-950 border border-gray-700 rounded px-2 py-1 text-xs text-white"></div>`
            )}
            <div class="px-3 py-2 space-y-1">
                ${box('flag', 'shared_only', 'Only what other cases have too', f.shared_only)}
                ${box('flag', 'noise', 'Show noise and false positives', f.noise)}
            </div>`;
    },

    onFilterChange(e) {
        const f = this.filters();
        const input = e.target;
        if (input.matches('[data-filter-clear]')) {
            this.setFilters({});
            return;
        }
        if (input.dataset.filterDate) f[input.dataset.filterDate] = input.value || null;
        else if (input.dataset.filter === 'flag') f[input.value] = input.checked;
        else if (input.dataset.filter) {
            const list = new Set(f[input.dataset.filter]);
            if (input.checked) list.add(input.value);
            else list.delete(input.value);
            f[input.dataset.filter] = [...list];
        } else return;
        this.setFilters(f);
    },

    async setFilters(filters) {
        const noiseBefore = this.filters().noise;
        this.state.change((s) => {
            s.filters = Object.keys(filters).length ? filters : null;
        });
        this.updateToolbar();
        if (!!this.filters().noise !== !!noiseBefore) {
            // noise and false positives come from the server
            await this.state.flush();
            await this.load();
        } else await this.refreshView();
        if (!this.filterPanel.classList.contains('hidden')) this.renderFilters();
    },

    async refreshView() {
        this.applyVisibility();
        this.updateStats();
        await this.relayout();
    },

    // -----------------------------------------------------------------------
    // The path between two nodes
    // -----------------------------------------------------------------------
    showPath() {
        const selected = this.cy.$('node:selected');
        if (selected.length !== 2) {
            window.showTemporaryNotification?.(
                'Select two nodes (Shift + drag, or click one and Shift + click the other)',
                'info'
            );
            return;
        }
        const drawn = this.cy.elements().not(OFF);
        const [from, to] = this.selectionOrder(selected);
        const found = drawn.aStar({
            root: this.cy.getElementById(from),
            goal: this.cy.getElementById(to),
            directed: false,
        });
        if (!found.found) {
            window.showTemporaryNotification?.('These two are not connected on the graph', 'info');
            return;
        }
        this.clearPath();
        this.cy.batch(() => {
            found.path.addClass('on-path');
            this.cy.elements().not(found.path).addClass('path-dim');
        });
        this.onPath = true;
        const steps = found.path.nodes().length - 1;
        this.setMode(`Path: ${steps} step${steps === 1 ? '' : 's'} · Esc to clear`);
        this.moved = true;
        this.cy.animate({ fit: { eles: found.path, padding: 80 } }, { duration: motion(300) });
    },

    clearPath() {
        if (!this.onPath) return false;
        this.cy.elements('.on-path, .path-dim').removeClass('on-path path-dim');
        this.onPath = false;
        this.setMode('');
        return true;
    },

    setMode(text) {
        if (!text && this.linking) return;
        this.modeBar.textContent = text;
        this.modeBar.classList.toggle('hidden', !text);
    },

    // -----------------------------------------------------------------------
    // Keys: moving between nodes, opening, the list of keys
    // -----------------------------------------------------------------------
    onFindKey(e) {
        const key = e.key;
        const mod = e.ctrlKey || e.metaKey;
        if ((mod && key.toLowerCase() === 'f') || (!mod && key === '/')) return this.openSearch(), true;
        if (mod || e.altKey) return false;
        if (key.startsWith('Arrow')) return this.step(key.slice(5).toLowerCase()), true;
        if (key === ' ') {
            const node = this.cy.$('node:selected');
            if (node.length === 1 && ['lookup', 'group'].includes(node.data('kind')))
                this.toggle(node, { record: true });
            else if (node.length === 1 && node.data('kind') === 'more') this.loadMore(node, { record: true });
            return true;
        }
        if (key === 'f' || key === 'F') return this.toggleFocus(), true;
        if (key === 'p' || key === 'P') return this.showPath(), true;
        if (key === '?') return this.showKeys(), true;
        return false;
    },

    // Escape, most recent thing first
    leaveSomething() {
        return this.closeSearch() || this.clearPath() || this.leaveFocus();
    },

    // To the connected node in that direction (nearest to the line), or the first root
    step(direction) {
        const drawn = this.cy.nodes().not(OFF);
        const current = this.cy.$('node:selected').first();
        let next;
        if (!current.length) next = drawn.filter((n) => !n.incomers('node').not(OFF).length).first();
        else {
            const v = { left: [-1, 0], right: [1, 0], up: [0, -1], down: [0, 1] }[direction];
            const from = current.position();
            let best = Infinity;
            current
                .neighborhood('node')
                .not(OFF)
                .forEach((n) => {
                    const dx = n.position('x') - from.x;
                    const dy = n.position('y') - from.y;
                    const along = dx * v[0] + dy * v[1];
                    if (along <= 0) return;
                    const across = Math.abs(dx * v[1] - dy * v[0]);
                    const score = along + across * 2;
                    if (score < best) {
                        best = score;
                        next = n;
                    }
                });
            // nothing linked that way: the nearest drawn node that way
            if (!next)
                drawn.forEach((n) => {
                    const dx = n.position('x') - from.x;
                    const dy = n.position('y') - from.y;
                    const along = dx * v[0] + dy * v[1];
                    if (along <= 0 || n === current) return;
                    const score = along + Math.abs(dx * v[1] - dy * v[0]) * 3;
                    if (score < best) {
                        best = score;
                        next = n;
                    }
                });
        }
        if (!next?.length) return;
        this.cy.$(':selected').unselect();
        next.select();
        const box = this.cy.extent();
        const p = next.position();
        if (p.x < box.x1 || p.x > box.x2 || p.y < box.y1 || p.y > box.y2) {
            this.moved = true;
            this.cy.animate({ center: { eles: next } }, { duration: motion(200) });
        }
        if (!this.panel.classList.contains('hidden')) this.openPanel(next);
    },

    showKeys() {
        this.dialog(
            'Keys',
            `<table class="w-full text-sm">${KEYS.map(
                ([k, what]) =>
                    `<tr class="border-b border-gray-800 last:border-0"><td class="py-1.5 pr-4 whitespace-nowrap text-purple-200 font-mono text-xs">${esc(k)}</td><td class="py-1.5 text-gray-300">${esc(what)}</td></tr>`
            ).join('')}</table>`,
            async () => {}
        );
        const form = document.querySelector('#graphDialog form');
        form.querySelector('[type="submit"]').textContent = 'OK';
        form.querySelector('[data-dialog-close].px-4')?.remove();
    },

    // A manual node type's or an identifier type's label (for lists and the legend)
    kindLabel(type) {
        return MANUAL_TYPES[type]?.label || typeName(type);
    },
};
