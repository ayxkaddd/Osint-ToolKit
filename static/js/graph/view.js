// The investigation graph: what the server sends (/graph) drawn with Cytoscape,
// lookups and groups opening and folding on click, and the side panel.
import { decorate, stylesheet, typeColor } from './style.js';
import { treeLayout } from './layout.js';

const REDUCED_MOTION = window.matchMedia('(prefers-reduced-motion: reduce)');
const motion = (ms) => (REDUCED_MOTION.matches ? 0 : ms);
// overshoots a little and settles: children spring out of their parent
const SPRING = 'cubic-bezier(0.34, 1.4, 0.64, 1)';
const LABEL_MAX = 28;

const clip = (text, max = LABEL_MAX) => {
    const s = String(text ?? '').replace(/\s+/g, ' ');
    return s.length > max ? `${s.slice(0, max - 1)}…` : s;
};
// moduleInfo and methodLabel: result_renderers.js (a classic script on every page)
const moduleOf = (service) =>
    typeof moduleInfo === 'function' ? moduleInfo(service) : { name: service || 'Lookup', icon: 'terminal' };
const methodName = (method) => (typeof methodLabel === 'function' ? methodLabel(method) : method || '');
const typeName = (type) => (window.ENTITY_LABELS || {})[type] || type;
const esc = (value) => window.escapeHtml(value);

function lookupTitle(node) {
    const info = moduleOf(node.service);
    const method = methodName(node.method);
    const generic = !method || ['run', 'upload'].includes(node.method);
    if (generic || info.name.toLowerCase().includes(method.toLowerCase())) return info.name;
    // "WHOIS lookup" says it all; "WHOIS · WHOIS lookup" twice
    if (method.toLowerCase().includes(info.name.toLowerCase())) return method;
    return `${info.name} · ${method}`;
}

// A group of accounts (username search categories) or of one identifier type
const groupType = (key) => (key.startsWith('type:') ? key.slice(5) : 'username');

export class GraphView {
    constructor(root, investigationId, { fullscreen = false } = {}) {
        this.root = root;
        this.investigationId = investigationId;
        this.fullscreen = fullscreen;
        this.order = 0;
        this.stash = new Map(); // folded node id -> the elements it hid (restored without a request)
        this.parentOf = new Map();
        this.panelNode = null;
        this.build();
        this.load();
    }

    api(path, params = {}) {
        const query = new URLSearchParams(params).toString();
        return fetch(`/api/investigations/${this.investigationId}/${path}${query ? `?${query}` : ''}`).then((r) => {
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            return r.json();
        });
    }

    // -----------------------------------------------------------------------
    // Page parts: canvas, toolbar, tooltip, side panel
    // -----------------------------------------------------------------------
    build() {
        this.root.innerHTML = `
            <div class="graph-canvas absolute inset-0" role="application" aria-label="Investigation graph"></div>
            <div class="graph-toolbar absolute top-3 left-3 flex items-center gap-1 bg-[#1a1b26] border border-[#24283b] rounded-lg p-1 shadow-xl">
                <button type="button" data-graph="fit" title="Fit to screen (0)"><i data-lucide="scan" class="w-4 h-4"></i></button>
                <button type="button" data-graph="zoomIn" title="Zoom in (+)"><i data-lucide="zoom-in" class="w-4 h-4"></i></button>
                <button type="button" data-graph="zoomOut" title="Zoom out (-)"><i data-lucide="zoom-out" class="w-4 h-4"></i></button>
                <span class="w-px h-5 bg-[#24283b] mx-1"></span>
                <button type="button" data-graph="collapseAll" title="Fold every lookup"><i data-lucide="fold-horizontal" class="w-4 h-4"></i></button>
                <button type="button" data-graph="reload" title="Reload the graph"><i data-lucide="refresh-cw" class="w-4 h-4"></i></button>
                ${
                    this.fullscreen
                        ? `<a href="/api/investigations/${esc(this.investigationId)}/view#graph" title="Back to the investigation"><i data-lucide="minimize-2" class="w-4 h-4"></i></a>`
                        : `<a href="/investigations/${esc(this.investigationId)}/graph" title="Full screen"><i data-lucide="maximize-2" class="w-4 h-4"></i></a>`
                }
            </div>
            <div class="graph-stats absolute bottom-3 left-3 text-[11px] text-gray-500 bg-black/60 rounded px-2 py-1 pointer-events-none"></div>
            <div class="graph-tooltip hidden absolute z-20 max-w-sm pointer-events-none bg-[#0f1017] border border-[#24283b] rounded-lg px-3 py-2 text-xs text-gray-200 shadow-2xl"></div>
            <div class="graph-message hidden absolute inset-0 flex items-center justify-center text-sm text-gray-400"></div>
            <aside class="graph-panel hidden absolute top-0 right-0 h-full w-full sm:w-[400px] bg-[#1a1b26] border-l border-[#24283b] shadow-2xl z-30 flex flex-col" aria-label="Selected node"></aside>`;
        this.canvas = this.root.querySelector('.graph-canvas');
        this.tooltip = this.root.querySelector('.graph-tooltip');
        this.panel = this.root.querySelector('.graph-panel');
        this.stats = this.root.querySelector('.graph-stats');
        this.message = this.root.querySelector('.graph-message');
        this.root.querySelectorAll('.graph-toolbar button, .graph-toolbar a').forEach((el) => {
            el.className =
                'w-8 h-8 inline-flex items-center justify-center rounded-md text-gray-400 hover:text-white hover:bg-gray-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-purple-500';
            el.setAttribute('aria-label', el.title);
        });
        this.root.querySelector('.graph-toolbar').addEventListener('click', (e) => {
            const action = e.target.closest('[data-graph]')?.dataset.graph;
            if (action) this[action]();
        });
        this.panel.addEventListener('click', (e) => {
            if (e.target.closest('[data-panel-close]')) this.closePanel();
            const focus = e.target.closest('[data-focus-node]');
            if (focus) this.focusNode(focus.dataset.focusNode);
        });
        window.refreshIcons?.();
    }

    show(text) {
        this.message.textContent = text || '';
        this.message.classList.toggle('hidden', !text);
    }

    // -----------------------------------------------------------------------
    // Data
    // -----------------------------------------------------------------------
    async load() {
        this.show('Loading the graph…');
        let graph;
        try {
            graph = await this.api('graph');
        } catch (error) {
            this.show(`The graph could not be loaded (${error.message}).`);
            return;
        }
        if (!this.cy) this.createCanvas();
        this.cy.elements().remove();
        this.stash.clear();
        this.closePanel();
        if (!graph.nodes.length) {
            this.show('Nothing to draw yet: run a lookup while this investigation is selected.');
            return;
        }
        this.show('');
        this.cy.add(this.elements(graph.nodes, graph.edges));
        this.refreshFoldable(this.cy.nodes());
        this.statsData = graph.stats;
        this.updateStats();
        this.relayout({ animate: false });
        this.moved = false;
        this.fitAll();
    }

    fitAll() {
        this.cy.fit(undefined, 40);
        if (this.cy.zoom() > 1.1) this.cy.zoom({ level: 1.1, renderedPosition: this.center() });
    }

    // Server nodes and edges as Cytoscape elements (new ones only)
    elements(nodes, edges) {
        const out = [];
        const known = new Set(this.cy.nodes().map((n) => n.id()));
        for (const node of nodes) {
            if (known.has(node.id)) continue;
            known.add(node.id);
            out.push({ group: 'nodes', data: this.nodeData(node) });
        }
        for (const edge of edges) {
            if (!known.has(edge.source) || !known.has(edge.target) || this.cy.getElementById(edge.id).length) continue;
            const { id, source, target, kind, service, method, timestamp } = edge;
            out.push({
                group: 'edges',
                data: { id, source, target, kind, service, method, timestamp, color: '#a78bfa' },
            });
        }
        return out;
    }

    nodeData(node) {
        const data = { ...node, order: this.order++ };
        // "parent" makes a compound node in Cytoscape: the "+N more" node's group is "of"
        if ('parent' in data) {
            data.of = data.parent;
            delete data.parent;
        }
        if (node.kind === 'identifier') {
            data.color = typeColor(node.type);
            // a link reads better without https://www. (the full value is in the tooltip)
            const shown = String(node.display || node.value);
            data.label = clip(node.type === 'url' ? shown.replace(/^https?:\/\/(www\.)?/i, '') : shown);
            data.w = data.h = node.root ? 42 : 34;
        } else if (node.kind === 'lookup') {
            data.icon = moduleOf(node.service).icon || 'terminal';
            const title = clip(lookupTitle(node), 30);
            const detail = [`${node.found} found`, node.rerun ? `re-run ×${node.runs.length}` : '']
                .filter(Boolean)
                .join(' · ');
            data.label = `${title}\n${detail}`;
            data.color = '#24283b';
            data.w = 50 + 6.2 * Math.max(title.length, detail.length);
            data.h = 40;
        } else if (node.kind === 'group') {
            data.color = typeColor(groupType(node.key));
            data.label = clip(node.label);
            data.open = false;
            data.w = data.h = 38;
        } else {
            data.color = '#4b5563';
            data.label = `+${node.count} more`;
            data.w = data.h = 26;
        }
        data.decor = decorate(data);
        return data;
    }

    setData(node, values) {
        node.data(values);
        node.data('decor', decorate(node.data()));
    }

    // A lookup or group can fold when something hangs under it
    refreshFoldable(nodes) {
        nodes.filter('[kind = "lookup"], [kind = "group"]').forEach((node) => {
            const foldable = node.outgoers('node').length > 0;
            if (node.data('foldable') !== foldable || (node.data('kind') === 'group' && node.data('open') !== foldable))
                this.setData(node, { foldable, ...(node.data('kind') === 'group' ? { open: foldable } : {}) });
        });
    }

    updateStats() {
        const s = this.statsData || {};
        const shown = this.cy.nodes('[kind = "identifier"]').length;
        this.stats.textContent = `${shown} of ${s.identifiers ?? '?'} identifiers shown · ${s.lookups ?? 0} lookups${
            s.noise || s.false_positive
                ? ` · ${(s.noise || 0) + (s.false_positive || 0)} left out (noise, false positives)`
                : ''
        }`;
    }

    // -----------------------------------------------------------------------
    // Canvas
    // -----------------------------------------------------------------------
    createCanvas() {
        this.cy = window.cytoscape({
            container: this.canvas,
            style: stylesheet(),
            minZoom: 0.08,
            maxZoom: 3,
            boxSelectionEnabled: false,
            selectionType: 'single',
            pixelRatio: 'auto',
        });
        const cy = this.cy;

        // the app's grid, moving with the graph
        const grid = () => {
            const size = 40 * cy.zoom();
            const pan = cy.pan();
            this.root.style.backgroundSize = `${size}px ${size}px`;
            this.root.style.backgroundPosition = `${pan.x}px ${pan.y}px`;
            this.hideTooltip();
        };
        cy.on('viewport', grid);
        grid();

        cy.on('tap', 'node', (e) => this.onTap(e.target));
        cy.on('dbltap', 'node[kind = "identifier"]', (e) => this.openAllUnder(e.target));
        cy.on('tap', (e) => {
            if (e.target === cy) this.closePanel();
        });
        cy.on('mouseover', 'node', (e) => this.hover(e.target, e.renderedPosition));
        cy.on('mouseout', 'node', () => this.unhover());
        cy.on('mouseover', 'edge', (e) => this.edgeTooltip(e.target, e.renderedPosition));
        cy.on('mouseout', 'edge', () => this.hideTooltip());
        // a node the analyst moved stays where they put it
        cy.on('dragfree', 'node', (e) => e.target.data('pinned', true));
        // until the analyst pans or zooms, a new size fits the graph again
        cy.on('dragpan scrollzoom pinchzoom', () => (this.moved = true));
        new ResizeObserver(() => {
            cy.resize();
            if (!this.moved && cy.nodes().length) this.fitAll();
        }).observe(this.canvas);
    }

    center() {
        return { x: this.canvas.clientWidth / 2, y: this.canvas.clientHeight / 2 };
    }

    fit() {
        this.cy.animate({ fit: { eles: this.cy.elements(), padding: 40 } }, { duration: motion(300) });
    }

    zoomIn() {
        this.cy.animate(
            { zoom: { level: this.cy.zoom() * 1.3, renderedPosition: this.center() } },
            { duration: motion(150) }
        );
    }

    zoomOut() {
        this.cy.animate(
            { zoom: { level: this.cy.zoom() / 1.3, renderedPosition: this.center() } },
            { duration: motion(150) }
        );
    }

    reload() {
        this.load();
    }

    focusNode(id) {
        const node = this.cy.getElementById(id);
        if (!node.length) return;
        this.cy.$(':selected').unselect();
        node.select();
        this.cy.animate({ center: { eles: node }, zoom: Math.max(this.cy.zoom(), 0.9) }, { duration: motion(300) });
        this.openPanel(node);
    }

    // Move every node to its place in the tree. New nodes grow out of where they start.
    relayout({ animate = true, grown = null } = {}) {
        const { positions, parentOf } = treeLayout(this.cy);
        this.parentOf = parentOf;
        const duration = animate ? motion(420) : 0;
        const moves = [];
        this.cy.nodes().forEach((node) => {
            const to = positions.get(node.id());
            const isNew = grown?.has(node.id());
            if (!to || (node.data('pinned') && !isNew)) return;
            if (!duration) {
                node.position(to);
                return;
            }
            const style = isNew ? { opacity: 1, width: node.data('w'), height: node.data('h') } : undefined;
            moves.push(
                node
                    .animation({ position: to, style }, { duration, easing: isNew ? SPRING : 'ease-out-cubic' })
                    .play()
                    .promise()
                    .then(() => isNew && node.removeStyle('opacity width height'))
            );
        });
        if (!duration && grown)
            this.cy
                .nodes()
                .filter((n) => grown.has(n.id()))
                .removeStyle('opacity width height');
        return Promise.all(moves);
    }

    // -----------------------------------------------------------------------
    // Opening and folding
    // -----------------------------------------------------------------------
    onTap(node) {
        const kind = node.data('kind');
        if (kind === 'more') return this.loadMore(node);
        if (kind === 'lookup' || kind === 'group') {
            this.toggle(node);
            if (!this.panel.classList.contains('hidden')) this.openPanel(node);
            return;
        }
        this.openPanel(node);
    }

    toggle(node) {
        if (node.data('busy')) return;
        if (node.data('open') && node.outgoers('node').length) return this.fold(node);
        return this.open(node);
    }

    async open(node) {
        const id = node.id();
        let added;
        if (this.stash.has(id)) {
            const saved = this.stash.get(id);
            this.stash.delete(id);
            const ids = new Set(this.cy.nodes().map((n) => n.id()));
            const nodes = saved.filter((e) => e.group === 'nodes' && !ids.has(e.data.id));
            nodes.forEach((e) => ids.add(e.data.id));
            const edges = saved.filter(
                (e) =>
                    e.group === 'edges' &&
                    ids.has(e.data.source) &&
                    ids.has(e.data.target) &&
                    !this.cy.getElementById(e.data.id).length
            );
            added = this.cy.add([...nodes, ...edges]);
        } else {
            if (node.data('kind') === 'lookup' && !node.data('hidden')) return;
            node.data('busy', true);
            try {
                const page = await this.api('graph/expand', { node: id });
                added = this.cy.add(this.elements(page.nodes, page.edges));
            } catch (error) {
                window.showTemporaryNotification?.(`Could not open it: ${error.message}`, 'error');
                return;
            } finally {
                node.data('busy', false);
            }
        }
        this.setData(node, { open: true });
        await this.grow(added.nodes(), node);
    }

    async loadMore(more) {
        if (more.data('busy')) return;
        more.data('busy', true);
        let page;
        try {
            page = await this.api('graph/expand', { node: more.id() });
        } catch (error) {
            more.data('busy', false);
            window.showTemporaryNotification?.(`Could not load more: ${error.message}`, 'error');
            return;
        }
        const from = more.position();
        more.remove();
        const added = this.cy.add(this.elements(page.nodes, page.edges));
        await this.grow(added.nodes(), null, from);
    }

    // New nodes start small and clear at their parent and spring out to their places
    async grow(nodes, parent, from = null) {
        const start = from || parent.position();
        nodes.forEach((n) => {
            n.position({ x: start.x, y: start.y });
            if (motion(1)) n.style({ opacity: 0, width: 4, height: 4 });
        });
        this.refreshFoldable(this.cy.nodes());
        this.updateStats();
        await this.relayout({ grown: new Set(nodes.map((n) => n.id())) });
    }

    // What hangs only under this node, in the tree: what folds into it. A node another
    // branch also links to stays (with what hangs under it).
    branch(node) {
        const children = new Map();
        this.parentOf.forEach((parent, child) => {
            if (!children.has(parent)) children.set(parent, []);
            children.get(parent).push(child);
        });
        const under = new Set();
        const collect = (id) =>
            (children.get(id) || []).forEach((child) => {
                under.add(child);
                collect(child);
            });
        collect(node.id());
        let changed = true;
        while (changed) {
            changed = false;
            for (const id of [...under]) {
                const elsewhere = this.cy
                    .getElementById(id)
                    .incomers('node')
                    .some((src) => src.id() !== node.id() && !under.has(src.id()));
                if (elsewhere) {
                    const keep = new Set([id]);
                    const gather = (k) => (children.get(k) || []).forEach((c) => (keep.add(c), gather(c)));
                    gather(id);
                    keep.forEach((k) => under.delete(k));
                    changed = true;
                }
            }
        }
        return this.cy.nodes().filter((n) => under.has(n.id()));
    }

    async fold(node) {
        const folding = this.branch(node);
        if (!folding.length) {
            this.setData(node, { open: false });
            return;
        }
        const edges = folding.connectedEdges();
        this.stash.set(node.id(), [...folding.jsons(), ...edges.jsons()]);
        node.data('busy', true);
        const duration = motion(320);
        if (duration) {
            await Promise.all(
                folding.map((n) =>
                    n
                        .animation(
                            { position: node.position(), style: { opacity: 0, width: 4, height: 4 } },
                            { duration, easing: 'ease-in-cubic' }
                        )
                        .play()
                        .promise()
                )
            );
        }
        if (folding.some((n) => n.id() === this.panelNode)) this.closePanel();
        this.cy.remove(folding);
        node.data('busy', false);
        this.setData(node, { open: false });
        this.refreshFoldable(this.cy.nodes());
        this.updateStats();
        await this.relayout();
    }

    // Double-click an identifier: open every lookup under it, one level
    async openAllUnder(node) {
        const closed = node.outgoers('node[kind = "lookup"]').filter((n) => !n.data('open'));
        await Promise.all(closed.map((n) => this.open(n)));
    }

    async collapseAll() {
        const open = this.cy
            .nodes('[kind = "lookup"], [kind = "group"]')
            .filter((n) => n.data('open') && n.outgoers('node').length);
        // deepest first, so each fold keeps what is under it
        const depth = (n) => {
            let d = 0;
            for (let id = n.id(); this.parentOf.has(id); id = this.parentOf.get(id)) d++;
            return d;
        };
        for (const node of open.sort((a, b) => depth(b) - depth(a)).toArray()) {
            if (node.inside()) await this.fold(node);
        }
        this.fit();
    }

    // -----------------------------------------------------------------------
    // Hover: the node, its links and its neighbours stay bright
    // -----------------------------------------------------------------------
    hover(node, at) {
        node.addClass('hover');
        const color = node.data('kind') === 'lookup' ? '#a78bfa' : node.data('color');
        this.cy.batch(() => {
            this.cy.elements().not(node.closedNeighborhood()).addClass('faded');
            node.connectedEdges().data('color', color).addClass('lit');
        });
        this.showTooltip(this.nodeTooltip(node.data()), at);
    }

    unhover() {
        this.cy.batch(() => {
            this.cy.elements('.hover').removeClass('hover');
            this.cy.elements('.faded').removeClass('faded');
            this.cy.edges('.lit').not(':selected').removeClass('lit');
        });
        this.hideTooltip();
    }

    nodeTooltip(d) {
        const lines = [];
        if (d.kind === 'identifier') {
            lines.push([typeName(d.type), 'text-gray-500'], [d.display || d.value, 'text-white break-all']);
            if (d.status)
                lines.push([
                    { confirmed: 'Confirmed', important: 'Important', false_positive: 'False positive' }[d.status],
                    'text-purple-300',
                ]);
            if (d.found_by > 1) lines.push([`Found by ${d.found_by} lookups`, 'text-gray-400']);
            if (d.shared) lines.push([`Also in ${d.shared} other case${d.shared > 1 ? 's' : ''}`, 'text-indigo-300']);
        } else if (d.kind === 'lookup') {
            lines.push([lookupTitle(d), 'text-white']);
            if (d.target) lines.push([String(d.target), 'text-gray-300 break-all']);
            if (d.summary) lines.push([String(d.summary), 'text-gray-400']);
            lines.push([`${d.found} found${d.hidden && !d.open ? `, ${d.hidden} folded` : ''}`, 'text-gray-400']);
            if (d.rerun)
                lines.push([
                    `Re-run ${d.runs.length} times; latest ${window.fmtDateTime?.(d.timestamp) || d.timestamp}`,
                    'text-amber-300',
                ]);
            else if (d.timestamp) lines.push([window.fmtDateTime?.(d.timestamp) || d.timestamp, 'text-gray-500']);
        } else if (d.kind === 'group') {
            lines.push(
                [d.label, 'text-white'],
                [`${d.count} identifiers · click to ${d.open ? 'fold' : 'open'}`, 'text-gray-400']
            );
        } else {
            lines.push([`${d.count} more · click to load the next ones`, 'text-gray-300']);
        }
        return lines;
    }

    edgeTooltip(edge, at) {
        const d = edge.data();
        if (!d.service) return;
        const when = d.timestamp ? window.fmtDateTime?.(d.timestamp) || d.timestamp : '';
        const verb =
            { searched: 'Looked up with', found: 'Found by', member: 'Found by', followup: 'Follow-up of' }[d.kind] ||
            '';
        this.showTooltip(
            [
                [`${verb} ${lookupTitle(d)}`.trim(), 'text-white'],
                [when, 'text-gray-500'],
            ],
            at
        );
    }

    // lines: [[text, classes]] - set as text, never as HTML
    showTooltip(lines, at) {
        this.tooltip.replaceChildren(
            ...lines
                .filter(([text]) => text)
                .map(([text, cls]) => {
                    const div = document.createElement('div');
                    div.className = cls;
                    div.textContent = text;
                    return div;
                })
        );
        const x = Math.min(at.x + 14, this.root.clientWidth - 300);
        this.tooltip.style.left = `${Math.max(4, x)}px`;
        this.tooltip.style.top = `${at.y + 14}px`;
        this.tooltip.classList.remove('hidden');
    }

    hideTooltip() {
        this.tooltip.classList.add('hidden');
    }

    // -----------------------------------------------------------------------
    // Side panel
    // -----------------------------------------------------------------------
    closePanel() {
        this.panel.classList.add('hidden');
        this.panelNode = null;
    }

    async openPanel(node) {
        const id = node.id();
        this.panelNode = id;
        this.panel.classList.remove('hidden');
        this.panel.innerHTML = this.panelFrame(node.data(), '<p class="text-sm text-gray-500">Loading…</p>');
        let details;
        try {
            details = await this.api('graph/node', { node: id });
        } catch (error) {
            details = { node: node.data(), error: error.message };
        }
        if (this.panelNode !== id) return;
        this.panel.innerHTML = this.panelFrame(details.node, this.panelBody(details));
        window.refreshIcons?.();
    }

    panelFrame(d, body) {
        let kind = '';
        let title = '';
        if (d.kind === 'identifier') {
            kind = typeName(d.type);
            title = d.display || d.value;
        } else if (d.kind === 'lookup') {
            kind = 'Lookup';
            title = lookupTitle(d);
        } else if (d.kind === 'group') {
            kind = 'Group';
            title = d.label;
        }
        const color = d.kind === 'identifier' ? typeColor(d.type) : '#a78bfa';
        return `
            <div class="flex items-start justify-between gap-3 px-5 py-4 border-b border-[#24283b]">
                <div class="min-w-0">
                    <div class="text-[11px] uppercase tracking-wider" style="color:${esc(color)}">${esc(kind)}</div>
                    <div class="text-white font-semibold break-all mt-0.5">${esc(title)}</div>
                </div>
                <button type="button" data-panel-close class="text-gray-400 hover:text-white shrink-0" aria-label="Close"><i data-lucide="x" class="w-5 h-5"></i></button>
            </div>
            <div class="flex-1 overflow-y-auto custom-scrollbar px-5 py-4 space-y-5 text-sm">${body}</div>`;
    }

    panelBody(details) {
        if (details.error) return `<p class="text-red-400">Could not load the details (${esc(details.error)}).</p>`;
        const d = details.node;
        const section = (heading, inner) =>
            inner
                ? `<section><h3 class="text-[11px] uppercase tracking-wider text-gray-500 mb-2">${esc(heading)}</h3>${inner}</section>`
                : '';
        const resultHref = (lookup) =>
            `/api/investigations/${encodeURIComponent(this.investigationId)}/view#result-${encodeURIComponent(lookup.result_id)}`;
        const lookupRow = (lookup) => `
            <div class="flex items-center gap-2 py-1">
                <button type="button" data-focus-node="${window.escapeAttr(lookup.id)}" class="min-w-0 flex-1 text-left hover:text-purple-300">
                    <span class="block truncate text-gray-200">${esc(lookupTitle(lookup))}${lookup.rerun ? ` <span class="text-amber-300 text-xs">×${lookup.runs.length}</span>` : ''}</span>
                    <span class="block truncate text-xs text-gray-500">${esc(lookup.target || '')} · ${esc(window.fmtDateTime?.(lookup.timestamp) || lookup.timestamp || '')}</span>
                </button>
                <a href="${window.escapeAttr(resultHref(lookup))}" class="text-gray-500 hover:text-purple-300 shrink-0" title="Open the result"><i data-lucide="external-link" class="w-4 h-4"></i></a>
            </div>`;

        if (d.kind === 'identifier') {
            const status = { confirmed: 'Confirmed', important: 'Important', false_positive: 'False positive' }[
                d.status
            ];
            const picture = d.image
                ? `<img src="${window.escapeAttr(window.safeUrl(d.image))}" alt="" referrerpolicy="no-referrer" data-img-error="hideImage" class="w-20 h-20 rounded-full object-cover border-2" style="border-color:${esc(typeColor(d.type))}">`
                : '';
            const elsewhere = (details.elsewhere || [])
                .map(
                    (place) =>
                        `<a class="block py-1 text-purple-300 hover:text-white truncate" href="/api/investigations/${encodeURIComponent(place.investigation_id)}/view?identifier=${encodeURIComponent(d.value)}#identifiers">${esc(place.name)}</a>`
                )
                .join('');
            return [
                picture,
                `<div>${window.pivotChip(d.type, d.value, d.display || d.value)}</div>`,
                status || d.note
                    ? `<div class="space-y-1">${status ? `<div class="text-purple-300">${esc(status)}</div>` : ''}${d.note ? `<div class="text-gray-300 whitespace-pre-line">${esc(d.note)}</div>` : ''}</div>`
                    : '',
                section('Looked up with', (details.searched_in || []).map(lookupRow).join('')),
                section('Found by', (details.found_in || []).map(lookupRow).join('')),
                section('Also in other cases', elsewhere),
                d.first_seen
                    ? `<p class="text-xs text-gray-500">First seen ${esc(window.fmtDateTime?.(d.first_seen) || d.first_seen)}${d.last_seen && d.last_seen !== d.first_seen ? `, last seen ${esc(window.fmtDateTime?.(d.last_seen) || d.last_seen)}` : ''}</p>`
                    : '',
            ].join('');
        }
        if (d.kind === 'lookup') {
            const runs = (d.runs || [])
                .map(
                    (run, i) => `
                <div class="flex items-center justify-between gap-2 py-1">
                    <span class="text-gray-300">${esc(window.fmtDateTime?.(run.timestamp) || run.timestamp || '')}${i === 0 ? ' <span class="text-xs text-gray-500">latest</span>' : ''}${run.partial ? ' <span class="text-xs text-amber-300">incomplete</span>' : ''}</span>
                    <a href="${window.escapeAttr(resultHref(run))}" class="text-gray-500 hover:text-purple-300" title="Open this run"><i data-lucide="external-link" class="w-4 h-4"></i></a>
                </div>`
                )
                .join('');
            return [
                d.target ? `<div class="text-gray-300 break-all">${esc(d.target)}</div>` : '',
                d.summary ? `<div class="text-gray-400">${esc(d.summary)}</div>` : '',
                `<div class="text-gray-400">${esc(d.found)} identifiers found</div>`,
                d.rerun
                    ? `<p class="text-xs text-amber-300/90">Run ${esc(d.runs.length)} times on the same ${d.runs.length > 1 ? 'identifiers' : 'identifier'}: one node, with what every run found.</p>`
                    : '',
                section(d.rerun ? 'Runs' : 'Run', runs),
                details.parent ? section('Follow-up of', lookupRow(details.parent)) : '',
            ].join('');
        }
        if (d.kind === 'group') {
            return [
                `<div class="text-gray-300">${esc(d.count)} identifiers, folded. Click the group to open it.</div>`,
                details.lookup ? section('Found by', lookupRow(details.lookup)) : '',
            ].join('');
        }
        return '';
    }
}
