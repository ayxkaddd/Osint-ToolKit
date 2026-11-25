// The investigation graph: what the server sends (/graph) drawn with Cytoscape,
// lookups and groups opening and folding on click, and the side panel.
// Editing (hide, remove, add, link, undo) is in edit.js; the saved view in state.js.
import { MANUAL_TYPES, OFF, decorate, stylesheet, typeColor } from './style.js';
import { box, overlaps, placeNew, treeLayout } from './layout.js';
import { History, SavedView } from './state.js';
import { editing } from './edit.js';
import { pivoting } from './pivot.js';
import { finding } from './find.js';
import { framing } from './chrome.js';

const REDUCED_MOTION = window.matchMedia('(prefers-reduced-motion: reduce)');
const motion = (ms) => (REDUCED_MOTION.matches ? 0 : ms);
// overshoots a little and settles: children spring out of their parent
const SPRING = 'cubic-bezier(0.34, 1.4, 0.64, 1)';
const LABEL_MAX = 28;

export const clip = (text, max = LABEL_MAX) => {
    const s = String(text ?? '').replace(/\s+/g, ' ');
    return s.length > max ? `${s.slice(0, max - 1)}…` : s;
};
// moduleInfo and methodLabel: result_renderers.js (a classic script on every page)
const moduleOf = (service) =>
    typeof moduleInfo === 'function' ? moduleInfo(service) : { name: service || 'Lookup', icon: 'terminal' };
const methodName = (method) => (typeof methodLabel === 'function' ? methodLabel(method) : method || '');
export const typeName = (type) => MANUAL_TYPES[type]?.label || (window.ENTITY_LABELS || {})[type] || type;
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
        this.state = new SavedView(investigationId);
        this.placeHints = new Map(); // parent id -> where its next new children start (pivot.js, loadMore)
        this.history = new History(() => this.updateToolbar());
        this.build();
        this.watchJobs();
        this.load();
    }

    api(path, params = {}) {
        // noise and false positives only when the filter asks for them (find.js)
        if (path.startsWith('graph') && this.state?.data.filters?.noise) params = { ...params, noise: 1 };
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
                <button type="button" data-graph="toggleLayout" data-layout-button title="Web layout: shared identifiers pull branches together"><i data-lucide="share-2" class="w-4 h-4"></i></button>
                <span class="w-px h-5 bg-[#24283b] mx-1"></span>
                <button type="button" data-graph="openSearch" title="Search (/ or Ctrl+F)"><i data-lucide="search" class="w-4 h-4"></i></button>
                <button type="button" data-graph="toggleFilters" data-filter-button title="Filters"><i data-lucide="sliders-horizontal" class="w-4 h-4"></i><span data-filter-dot class="hidden ml-0.5 w-1.5 h-1.5 rounded-full bg-purple-400"></span></button>
                <span class="w-px h-5 bg-[#24283b] mx-1"></span>
                <button type="button" data-graph="tidy" title="Tidy up: put the nodes you moved back in their places (Ctrl+Z puts them back)"><i data-lucide="wand-sparkles" class="w-4 h-4"></i></button>
                <button type="button" data-graph="collapseAll" title="Fold every lookup"><i data-lucide="fold-horizontal" class="w-4 h-4"></i></button>
                <span class="w-px h-5 bg-[#24283b] mx-1"></span>
                <button type="button" data-graph="addNodeDialog" title="Add a node (N)"><i data-lucide="plus" class="w-4 h-4"></i></button>
                <button type="button" data-graph="startLink" title="Link two nodes (L)"><i data-lucide="spline" class="w-4 h-4"></i></button>
                <button type="button" data-graph="undo" title="Undo (Ctrl+Z)"><i data-lucide="undo-2" class="w-4 h-4"></i></button>
                <button type="button" data-graph="redo" title="Redo (Ctrl+Shift+Z)"><i data-lucide="redo-2" class="w-4 h-4"></i></button>
                <button type="button" data-graph="toggleTray" data-tray-button title="Hidden and removed nodes"><i data-lucide="eye-off" class="w-4 h-4"></i><span data-tray-count class="ml-1 text-[11px]"></span></button>
                <span class="w-px h-5 bg-[#24283b] mx-1"></span>
                <button type="button" data-graph="exportMenu" title="Export"><i data-lucide="download" class="w-4 h-4"></i></button>
                <button type="button" data-graph="reload" title="Reload the graph"><i data-lucide="refresh-cw" class="w-4 h-4"></i></button>
                <button type="button" data-graph="showKeys" title="Keys (?)"><i data-lucide="keyboard" class="w-4 h-4"></i></button>
                ${
                    this.fullscreen
                        ? `<a href="/api/investigations/${esc(this.investigationId)}/view#graph" title="Back to the investigation"><i data-lucide="minimize-2" class="w-4 h-4"></i></a>`
                        : `<a href="/investigations/${esc(this.investigationId)}/graph" title="Full screen"><i data-lucide="maximize-2" class="w-4 h-4"></i></a>`
                }
            </div>
            <div class="graph-tray hidden absolute top-14 left-3 z-20 w-80 max-h-[60%] overflow-y-auto custom-scrollbar bg-[#1a1b26] border border-[#24283b] rounded-lg shadow-2xl text-sm"></div>
            <div class="graph-mode hidden absolute bottom-3 left-1/2 -translate-x-1/2 z-20 bg-purple-950/90 border border-purple-700 text-purple-100 text-xs rounded-lg px-3 py-2"></div>
            <div class="graph-search hidden absolute top-14 left-1/2 -translate-x-1/2 z-20 w-96 max-w-[90%] bg-[#1a1b26] border border-[#24283b] rounded-lg shadow-2xl text-sm">
                <div class="flex items-center gap-2 px-3 py-2">
                    <i data-lucide="search" class="w-4 h-4 text-gray-500 shrink-0"></i>
                    <input type="search" aria-label="Search the graph" placeholder="Find an identifier… (Enter: next)" class="flex-1 min-w-0 bg-transparent text-white placeholder-gray-500 focus:outline-none">
                    <span data-search-count class="text-[11px] text-gray-500 shrink-0"></span>
                    <button type="button" data-search-close class="text-gray-500 hover:text-white" aria-label="Close the search"><i data-lucide="x" class="w-4 h-4"></i></button>
                </div>
                <div data-search-more class="max-h-64 overflow-y-auto custom-scrollbar border-t border-[#24283b] empty:border-0"></div>
            </div>
            <div class="graph-filters hidden absolute top-14 left-3 z-20 w-80 max-h-[70%] overflow-y-auto custom-scrollbar bg-[#1a1b26] border border-[#24283b] rounded-lg shadow-2xl text-sm"></div>
            <div class="graph-legend absolute bottom-10 left-3 z-10 w-52 bg-[#1a1b26]/95 border border-[#24283b] rounded-lg text-[11px] text-gray-300">
                <button type="button" data-legend-toggle class="w-full flex items-center justify-between px-3 py-1.5 text-gray-400 hover:text-white">Legend<i data-lucide="chevrons-up-down" class="w-3.5 h-3.5"></i></button>
                <div data-legend-body class="px-3 pb-2 space-y-1 max-h-64 overflow-y-auto custom-scrollbar"></div>
            </div>
            <canvas class="graph-minimap absolute bottom-3 right-3 z-10 w-48 h-32 bg-[#0f1017]/90 border border-[#24283b] rounded-lg cursor-pointer" aria-label="Minimap: click to move there"></canvas>
            <div class="graph-stats absolute bottom-3 left-3 text-[11px] text-gray-500 bg-black/60 rounded px-2 py-1 pointer-events-none"></div>
            <div class="graph-tooltip hidden absolute z-20 max-w-sm pointer-events-none bg-[#0f1017] border border-[#24283b] rounded-lg px-3 py-2 text-xs text-gray-200 shadow-2xl"></div>
            <div class="graph-message hidden absolute inset-0 flex items-center justify-center text-sm text-gray-400"></div>
            <aside class="graph-panel hidden absolute top-0 right-0 h-full w-full sm:w-[400px] bg-[#1a1b26] border-l border-[#24283b] shadow-2xl z-30 flex flex-col" aria-label="Selected node"></aside>`;
        this.canvas = this.root.querySelector('.graph-canvas');
        this.tooltip = this.root.querySelector('.graph-tooltip');
        this.panel = this.root.querySelector('.graph-panel');
        this.stats = this.root.querySelector('.graph-stats');
        this.message = this.root.querySelector('.graph-message');
        this.tray = this.root.querySelector('.graph-tray');
        this.modeBar = this.root.querySelector('.graph-mode');
        this.root.querySelectorAll('.graph-toolbar button, .graph-toolbar a').forEach((el) => {
            el.className =
                'h-8 min-w-8 px-1.5 inline-flex items-center justify-center rounded-md text-gray-400 hover:text-white hover:bg-gray-800 disabled:opacity-40 disabled:hover:bg-transparent focus:outline-none focus-visible:ring-2 focus-visible:ring-purple-500';
            el.setAttribute('aria-label', el.title);
        });
        // keys work while the graph has focus (clicking it gives it focus)
        this.root.tabIndex = 0;
        this.root.addEventListener('keydown', (e) => this.onKey(e));
        this.tray.addEventListener('click', (e) => this.onTrayClick(e));
        this.buildSearch();
        this.filterPanel = this.root.querySelector('.graph-filters');
        this.filterPanel.addEventListener('change', (e) => this.onFilterChange(e));
        this.filterPanel.addEventListener(
            'click',
            (e) => e.target.closest('[data-filter-clear]') && this.setFilters({})
        );
        this.legendBody = this.root.querySelector('[data-legend-body]');
        this.root.querySelector('[data-legend-toggle]').addEventListener('click', () => this.toggleLegend());
        try {
            if (localStorage.getItem('graphLegend') === 'closed') this.legendBody.classList.add('hidden');
        } catch {
            /* shown */
        }
        this.minimap = this.root.querySelector('.graph-minimap');
        let dragging = false;
        this.minimap.addEventListener('pointerdown', (e) => {
            dragging = true;
            this.minimap.setPointerCapture(e.pointerId);
            this.minimapPan(e);
        });
        this.minimap.addEventListener('pointermove', (e) => dragging && this.minimapPan(e));
        this.minimap.addEventListener('pointerup', () => (dragging = false));
        this.root.querySelector('.graph-toolbar').addEventListener('click', (e) => {
            const button = e.target.closest('[data-graph]');
            if (button) this[button.dataset.graph](button);
        });
        this.panel.addEventListener('click', (e) => {
            if (e.target.closest('[data-panel-close]')) this.closePanel();
            const menu = e.target.closest('[data-panel-menu]');
            const shown = this.panelNode && this.cy.getElementById(this.panelNode);
            if (menu && shown?.length) window.openContextMenu(menu, this.identifierItems(shown), shown.data('label'));
            if (e.target.closest('[data-panel-edit]')) this.nodeDialog({ editing: this.panelNode });
            if (e.target.closest('[data-panel-add-to-case]'))
                this.nodeDialog({ editing: this.panelNode, addToCase: true });
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
            // the saved view wants noise shown: ask again with it
            if (graph.state?.filters?.noise && !this.state.data.filters?.noise) {
                this.state.load(graph.state);
                graph = await this.api('graph');
            }
        } catch (error) {
            this.show(`The graph could not be loaded (${error.message}).`);
            return;
        }
        if (!this.cy) this.createCanvas();
        this.cy.elements().remove();
        this.stash.clear();
        this.closePanel();
        this.state.load(graph.state);
        if (!graph.nodes.length && !this.state.data.manual_nodes.length) {
            this.show('Nothing to draw yet: run a lookup while this investigation is selected, or add a node (N).');
            this.updateToolbar();
            return;
        }
        this.show('');
        this.cy.add(this.elements(graph.nodes, graph.edges));
        this.statsData = graph.stats;
        // the view as the analyst left it (edit.js)
        await this.state.whileRestoring(() => this.restoreView());
        // a view saved for an older layout: kept in the new form from now on
        if (this.state.outdated) {
            this.state.outdated = false;
            this.state.change(() => {});
        }
        this.refreshFoldable(this.cy.nodes());
        this.updateStats();
        this.updateToolbar();
        this.relayout({ animate: false, initial: true });
        const viewport = this.state.data.viewport;
        if (viewport) {
            this.cy.viewport({ zoom: viewport.zoom, pan: { x: viewport.x, y: viewport.y } });
            this.moved = true;
        } else {
            this.moved = false;
            this.fitAll();
        }
        // lookups already running on this case's identifiers come in as pending nodes (pivot.js)
        window.refreshJobs?.();
    }

    lookupName(node) {
        return lookupTitle(node);
    }

    fitAll() {
        this.cy.fit(undefined, 64);
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
            data.picture = node.image || null;
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
        } else if (node.kind === 'manual') {
            data.color = node.color || typeColor(node.type);
            data.label = clip(node.label);
            data.w = data.h = 36;
            if (node.image)
                data.picture = `/api/investigations/${encodeURIComponent(this.investigationId)}/note-images/${encodeURIComponent(node.image)}`;
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
        this.renderLegend();
        this.drawMinimap();
        const s = this.statsData || {};
        const shown = this.cy.nodes('[kind = "identifier"]').not(OFF).length;
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
        // the web layout (static/vendor/cytoscape-fcose), once per page
        if (window.cytoscapeFcose && !window.cytoscape.fcoseAdded) {
            window.cytoscape.use(window.cytoscapeFcose);
            window.cytoscape.fcoseAdded = true;
        }
        this.cy = window.cytoscape({
            container: this.canvas,
            style: stylesheet(),
            minZoom: 0.08,
            maxZoom: 3,
            // Shift + drag selects several nodes (to hide or remove them at once)
            boxSelectionEnabled: true,
            selectionType: 'single',
            pixelRatio: 'auto',
        });
        const cy = this.cy;

        // the app's grid, moving with the graph
        const grid = () => {
            // fine lines every 40 units, coarse every 200; zoomed far out, the coarse become the fine
            let fine = 40 * cy.zoom();
            while (fine < 12) fine *= 5;
            const coarse = fine * 5;
            const pan = cy.pan();
            const at = `${pan.x}px ${pan.y}px`;
            this.root.style.backgroundSize = [fine, fine, coarse, coarse].map((s) => `${s}px ${s}px`).join(', ');
            this.root.style.backgroundPosition = [at, at, at, at].join(', ');
            this.hideTooltip();
        };
        cy.on('viewport', grid);
        cy.on('viewport', () => this.drawMinimap(false));
        cy.on('position add remove', () => this.drawMinimap());
        grid();

        cy.on('tap', 'node', (e) => this.onTap(e.target));
        cy.on('tap', () => this.root.focus({ preventScroll: true }));
        // the order nodes were selected in (a link goes from the first to the second)
        cy.on(
            'select',
            'node',
            (e) =>
                (this.selectedAt = [
                    ...(this.selectedAt || []).filter((id) => id !== e.target.id()),
                    e.target.id(),
                ].slice(-10))
        );
        // right click, or a long press on a touch screen
        cy.on('cxttap taphold', 'node, edge', (e) => this.elementMenu(e.target, e));
        cy.on('cxttap taphold', (e) => e.target === cy && this.canvasMenu(e));
        cy.on('grab', 'node', (e) => this.dragStart(e.target));
        cy.on('dbltap', 'node[kind = "identifier"]', (e) => this.openAllUnder(e.target));
        cy.on('tap', (e) => {
            if (e.target === cy) this.closePanel();
        });
        cy.on('mouseover', 'node', (e) => this.hover(e.target, e.renderedPosition));
        cy.on('mouseout', 'node', () => this.unhover());
        cy.on('mouseover', 'edge', (e) => this.edgeTooltip(e.target, e.renderedPosition));
        cy.on('mouseout', 'edge', () => this.hideTooltip());
        // a node the analyst moved stays where they put it
        cy.on('dragfree', 'node', (e) => this.dragEnd(e.target));
        let viewportTimer;
        cy.on('viewport', () => {
            clearTimeout(viewportTimer);
            viewportTimer = setTimeout(() => {
                if (!this.moved) return;
                const pan = cy.pan();
                const now = { zoom: +cy.zoom().toFixed(4), x: Math.round(pan.x), y: Math.round(pan.y) };
                const before = this.state.data.viewport;
                if (before && before.zoom === now.zoom && before.x === now.x && before.y === now.y) return;
                this.state.change((s) => {
                    s.viewport = now;
                });
            }, 400);
        });
        // until the analyst pans or zooms, a new size fits the graph again
        cy.on('dragpan scrollzoom pinchzoom', () => (this.moved = true));
        // the browser's own menu would cover the graph's (right click)
        this.canvas.addEventListener('contextmenu', (e) => e.preventDefault());
        new ResizeObserver(() => {
            cy.resize();
            if (!this.moved && cy.nodes().length) this.fitAll();
        }).observe(this.canvas);
    }

    center() {
        return { x: this.canvas.clientWidth / 2, y: this.canvas.clientHeight / 2 };
    }

    fit() {
        this.moved = true;
        this.cy.animate({ fit: { eles: this.cy.elements().not(OFF), padding: 64 } }, { duration: motion(300) });
    }

    zoomIn() {
        this.moved = true;
        this.cy.animate(
            { zoom: { level: this.cy.zoom() * 1.3, renderedPosition: this.center() } },
            { duration: motion(150) }
        );
    }

    zoomOut() {
        this.moved = true;
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
        this.moved = true;
        this.cy.$(':selected').unselect();
        node.select();
        this.cy.animate({ center: { eles: node }, zoom: Math.max(this.cy.zoom(), 0.9) }, { duration: motion(300) });
        this.openPanel(node);
    }

    // Where nodes go. The tree (layout.js) gives every node its own row, the same way each
    // time: growing pushes only the rows below down, smoothly, and nodes the analyst moved
    // stay where they were put. The web keeps every place and puts new nodes in free
    // space beside their parent (placeNew); ``full`` lays the web out again.
    relayout({ animate = true, grown = null, full = false, initial = false } = {}) {
        const { positions: tree, parentOf } = treeLayout(this.cy);
        this.parentOf = parentOf;
        this.scheduleSnapshot();
        const web = this.layoutName() === 'web';
        this.cy.edges().toggleClass('web', web);
        const saved = this.state.data.positions;
        const pinned = new Set(this.pinnedIds());
        const drawn = this.cy.nodes().not(OFF);
        const xy = (p) => ({ x: p[0], y: p[1] });
        if (initial) drawn.forEach((n) => n.data('pinned', pinned.has(n.id())));
        const targets = new Map();
        if (web) {
            if (initial && drawn.filter((n) => saved[n.id()]).length < drawn.length / 2) full = true;
            if (full) return this.runWeb({ animate, fresh: !initial }).then(() => this.keepPlaces(drawn, true));
            const fresh = [];
            drawn.forEach((n) => {
                if (n.data('placed')) return;
                const back = n.scratch('_to') || (saved[n.id()] && xy(saved[n.id()]));
                if (back) targets.set(n.id(), back);
                else fresh.push(n);
            });
            const settled = new Map();
            drawn.forEach((n) => {
                if (targets.has(n.id())) settled.set(n.id(), { node: n, at: targets.get(n.id()) });
                else if (n.data('placed')) settled.set(n.id(), { node: n, at: { ...n.position() } });
            });
            placeNew(this.cy.collection(fresh), parentOf, settled, { web, hints: this.placeHints }).forEach((to, id) =>
                targets.set(id, to)
            );
        } else {
            drawn.forEach((n) => {
                if (!(pinned.has(n.id()) && saved[n.id()]) && tree.get(n.id())) targets.set(n.id(), tree.get(n.id()));
            });
            // a moved node stays where it was put, unless the tree has grown under it there:
            // then it goes back to its row (nothing is ever drawn over something else)
            const taken = [...targets].map(([id, to]) => box(this.cy.getElementById(id), to));
            const unpin = [];
            drawn.forEach((n) => {
                if (targets.has(n.id()) || !saved[n.id()]) return;
                const at = xy(saved[n.id()]);
                const b = box(n, at);
                if (taken.some((t) => overlaps(t, b))) {
                    unpin.push(n.id());
                    n.data('pinned', false);
                    if (tree.get(n.id())) targets.set(n.id(), tree.get(n.id()));
                    taken.push(box(n, tree.get(n.id()) || at));
                } else {
                    targets.set(n.id(), at);
                    taken.push(b);
                }
            });
            if (unpin.length)
                this.state.change((s) => {
                    s.pinned = (s.pinned ?? Object.keys(s.positions)).filter((id) => !unpin.includes(id));
                    unpin.forEach((id) => delete s.positions[id]);
                });
            // the tree needs no saved places but the moved ones
            if (initial && Object.keys(saved).some((id) => !pinned.has(id)))
                this.state.change((s) => {
                    s.pinned = s.pinned ?? Object.keys(s.positions);
                    s.positions = Object.fromEntries(
                        Object.entries(s.positions).filter(([id]) => s.pinned.includes(id))
                    );
                });
        }
        this.placeHints.clear();
        const duration = animate ? motion(380) : 0;
        const moves = [];
        targets.forEach((to, id) => {
            const node = this.cy.getElementById(id);
            const isNew = grown?.has(id);
            node.removeScratch('_to');
            node.data('placed', true);
            const from = node.position();
            if (!duration) {
                node.position(to);
                return;
            }
            if (!isNew && Math.abs(from.x - to.x) < 0.5 && Math.abs(from.y - to.y) < 0.5) return;
            const style = isNew ? { opacity: 1, width: node.data('w'), height: node.data('h') } : undefined;
            moves.push(
                node
                    .animation({ position: to, style }, { duration, easing: isNew ? SPRING : 'ease-in-out-cubic' })
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
        if (web && targets.size) this.keepPlaces(targets);
        if (grown?.size && !initial) this.bringIntoView([...grown].map((id) => targets.get(id)).filter(Boolean));
        return Promise.all(moves);
    }

    pinnedIds() {
        const s = this.state.data;
        // before "pinned" was saved, every saved position was a node the analyst moved
        return s.pinned ?? Object.keys(s.positions);
    }

    // Remember where nodes are (so the case opens as it was left). ``places``: a Map of
    // id -> {x, y}, or nodes (their positions now)
    keepPlaces(places, all = false) {
        const now = {};
        if (places instanceof Map) places.forEach((p, id) => (now[id] = [Math.round(p.x), Math.round(p.y)]));
        else places.forEach((n) => (now[n.id()] = [Math.round(n.position('x')), Math.round(n.position('y'))]));
        Object.keys(now)
            .filter((id) => id.startsWith('p:'))
            .forEach((id) => delete now[id]);
        this.state.change((s) => {
            s.pinned = s.pinned ?? Object.keys(s.positions);
            let positions = all ? { ...now } : { ...s.positions, ...now };
            if (all) s.pinned.forEach((id) => s.positions[id] && !now[id] && (positions[id] = s.positions[id]));
            // the cap of the saved view: what is pinned or drawn first
            const ids = Object.keys(positions);
            if (ids.length > 5000) {
                const keep = new Set([...s.pinned, ...this.cy.nodes().map((n) => n.id())]);
                positions = Object.fromEntries(
                    ids
                        .filter((id) => keep.has(id))
                        .slice(0, 5000)
                        .map((id) => [id, positions[id]])
                );
            }
            s.positions = positions;
        });
    }

    // New nodes off the screen (or under the toolbar): the view moves just enough to show
    // them; the nodes stay where they are
    bringIntoView(points) {
        if (!points.length) return;
        const zoom = this.cy.zoom();
        const pan = this.cy.pan();
        const width = this.canvas.clientWidth;
        const height = this.canvas.clientHeight;
        // on screen, in pixels; the toolbar covers the top, the legend and minimap the bottom
        const xs = points.map((p) => p.x * zoom + pan.x);
        const ys = points.map((p) => p.y * zoom + pan.y);
        const box = { x1: 60, x2: width - 60, y1: 90, y2: height - 60 };
        let dx = 0;
        let dy = 0;
        if (Math.min(...xs) < box.x1) dx = box.x1 - Math.min(...xs);
        else if (Math.max(...xs) > box.x2) dx = Math.max(box.x2 - Math.max(...xs), box.x1 - Math.min(...xs));
        if (Math.min(...ys) < box.y1) dy = box.y1 - Math.min(...ys);
        else if (Math.max(...ys) > box.y2) dy = Math.max(box.y2 - Math.max(...ys), box.y1 - Math.min(...ys));
        if (!dx && !dy) return;
        this.moved = true;
        this.cy.animate(
            { pan: { x: pan.x + dx, y: pan.y + dy } },
            { duration: motion(450), easing: 'ease-in-out-cubic' }
        );
    }

    // Tidy up. The tree: the nodes the analyst moved go back into it. The web: laid out
    // again. Ctrl+Z puts things back as they were.
    async tidy() {
        const before = { positions: { ...this.state.data.positions }, pinned: [...this.pinnedIds()] };
        const places = new Map(this.cy.nodes().map((n) => [n.id(), { ...n.position() }]));
        const restore = async (view) => {
            this.state.change((s) => {
                s.positions = { ...view.positions };
                s.pinned = [...view.pinned];
            });
            this.cy.nodes().forEach((n) => n.data('pinned', view.pinned.includes(n.id())));
            if (this.layoutName() === 'web') {
                await Promise.all(
                    [...places].map(([id, to]) => {
                        const node = this.cy.getElementById(id);
                        return node.length
                            ? node
                                  .animation({ position: to }, { duration: motion(380) })
                                  .play()
                                  .promise()
                            : null;
                    })
                );
            } else await this.relayout();
        };
        const tidied = async () => {
            if (this.layoutName() === 'web') return this.relayout({ full: true });
            this.state.change((s) => {
                s.positions = {};
                s.pinned = [];
            });
            this.cy.nodes().data('pinned', false);
            return this.relayout();
        };
        await tidied();
        this.history.push({ undo: () => restore(before), redo: tidied });
        this.fit();
    }

    // -----------------------------------------------------------------------
    // Opening and folding
    // -----------------------------------------------------------------------
    onTap(node) {
        if (this.linking) return this.finishLink(node);
        const kind = node.data('kind');
        if (kind === 'pending') return node.data('status') === 'failed' ? this.dismissPending(node) : undefined;
        if (kind === 'more') return this.loadMore(node, { record: true });
        if (kind === 'lookup' || kind === 'group') {
            this.toggle(node, { record: true });
            if (!this.panel.classList.contains('hidden')) this.openPanel(node);
            return;
        }
        this.openPanel(node);
    }

    toggle(node, options = {}) {
        if (node.data('busy')) return;
        if (node.data('open') && node.outgoers('node').length) return this.fold(node, options);
        return this.open(node, options);
    }

    // record: remember it in the saved view and in undo; quiet: no animation or layout
    // (several at once while the saved view is put back)
    async open(node, { record = false, quiet = false } = {}) {
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
        this.attachManualEdges();
        if (record) {
            this.state.change((s) => {
                s.collapsed = s.collapsed.filter((x) => x !== id);
                if (!s.expanded.includes(id)) s.expanded.push(id);
            });
            this.history.push({ undo: () => this.foldById(id), redo: () => this.openById(id) });
        }
        if (quiet) return;
        await this.grow(added.nodes(), node);
    }

    async loadMore(more, { record = false, quiet = false } = {}) {
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
        if (more.data('of')) this.placeHints.set(more.data('of'), { ...from });
        more.remove();
        const added = this.cy.add(this.elements(page.nodes, page.edges));
        this.attachManualEdges();
        if (record) this.state.add('expanded', more.id());
        if (quiet) return;
        this.applyVisibility();
        await this.grow(added.nodes(), null, from);
    }

    // New nodes start small and clear at their parent and spring out to their places
    async grow(nodes, parent, from = null) {
        nodes.forEach((n) => {
            // opened again: it goes back to where it was
            if (n.data('placed')) {
                n.scratch('_to', { ...n.position() });
                n.data('placed', false);
            }
            // from the parent given, else from what links to it, else the middle of the screen
            const origin = n.incomers('node').not(nodes).first();
            const start = from || parent?.position() || (origin.length ? origin.position() : this.modelCenter());
            n.position({ x: start.x, y: start.y });
            if (motion(1)) n.style({ opacity: 0, width: 4, height: 4 });
        });
        this.applyVisibility();
        this.refreshFoldable(this.cy.nodes());
        this.updateStats();
        await this.relayout({ grown: new Set(nodes.map((n) => n.id())) });
    }

    // What hangs only under this node, in the tree: what folds into it. A node another
    // branch also links to stays (with what hangs under it).
    branch(node, parentOf = this.parentOf) {
        const children = new Map();
        parentOf.forEach((parent, child) => {
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

    async fold(node, { record = false, quiet = false } = {}) {
        const id = node.id();
        if (record) {
            this.state.change((s) => {
                s.expanded = s.expanded.filter((x) => x !== id);
                if (!s.collapsed.includes(id)) s.collapsed.push(id);
            });
            this.history.push({ undo: () => this.openById(id), redo: () => this.foldById(id) });
        }
        const folding = this.branch(node);
        if (!folding.length) {
            this.setData(node, { open: false });
            return;
        }
        const edges = folding.connectedEdges();
        this.stash.set(node.id(), [...folding.jsons(), ...edges.jsons()]);
        node.data('busy', true);
        const duration = quiet ? 0 : motion(320);
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
        if (quiet) return;
        this.refreshFoldable(this.cy.nodes());
        this.updateStats();
        await this.relayout();
    }

    async openById(id) {
        const node = this.cy.getElementById(id);
        if (node.length && !(node.data('open') && node.outgoers('node').length)) await this.open(node);
        this.state.change((s) => {
            s.collapsed = s.collapsed.filter((x) => x !== id);
            if (!s.expanded.includes(id)) s.expanded.push(id);
        });
    }

    async foldById(id) {
        const node = this.cy.getElementById(id);
        if (node.length && node.data('open')) await this.fold(node);
        this.state.change((s) => {
            s.expanded = s.expanded.filter((x) => x !== id);
            if (!s.collapsed.includes(id)) s.collapsed.push(id);
        });
    }

    // Double-click an identifier: open every lookup under it, one level
    async openAllUnder(node) {
        const closed = node.outgoers('node[kind = "lookup"]').filter((n) => !n.data('open'));
        await Promise.all(closed.map((n) => this.open(n, { record: true })));
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
            if (node.inside()) await this.fold(node, { record: true });
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
        } else if (d.kind === 'pending') {
            lines.push([d.module_name, 'text-white'], [d.value, 'text-gray-300 break-all']);
            lines.push(
                d.status === 'failed'
                    ? [d.error || 'Failed', 'text-red-300']
                    : [d.label.split('\n')[1] || 'running…', 'text-purple-300']
            );
        } else if (d.kind === 'manual') {
            lines.push([`${typeName(d.type)} · added by you`, 'text-gray-500'], [d.label, 'text-white break-all']);
            if (d.note) lines.push([d.note.length > 200 ? `${d.note.slice(0, 199)}…` : d.note, 'text-gray-300']);
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
        if (node.data('kind') === 'manual') details = { node: node.data() };
        else
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
        } else if (d.kind === 'manual') {
            kind = `${typeName(d.type)} · yours`;
            title = d.label;
        }
        const color = d.kind === 'identifier' ? typeColor(d.type) : d.kind === 'manual' ? d.color : '#a78bfa';
        return `
            <div class="flex items-start justify-between gap-3 px-5 py-4 border-b border-[#24283b]">
                <div class="min-w-0">
                    <div class="text-[11px] uppercase tracking-wider" style="color:${esc(color)}">${esc(kind)}</div>
                    <div class="text-white font-semibold break-all mt-0.5">${esc(title)}</div>
                </div>
                <div class="flex items-center gap-2 shrink-0">
                    ${d.kind === 'identifier' ? '<button type="button" data-panel-menu class="text-gray-400 hover:text-white" aria-label="More" title="Look up, assess, note"><i data-lucide="ellipsis" class="w-5 h-5"></i></button>' : ''}
                    <button type="button" data-panel-close class="text-gray-400 hover:text-white" aria-label="Close"><i data-lucide="x" class="w-5 h-5"></i></button>
                </div>
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
                // the chip's lookups are attached under the result that found it, as from the node's menu
                `<div>${window.pivotChip(d.type, d.value, d.display || d.value).replace('<button ', `<button data-pivot-parent="${window.escapeAttr(this.parentResultFor(this.cy.getElementById(d.id)) || '')}" `)}</div>`,
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
        if (d.kind === 'manual') {
            const picture = d.picture
                ? `<img src="${window.escapeAttr(d.picture)}" alt="" data-img-error="hideImage" class="w-24 h-24 rounded-full object-cover border-2" style="border-color:${esc(d.color)}">`
                : '';
            const link = d.url && window.safeUrl(d.url);
            return [
                picture,
                d.note ? `<div class="text-gray-300 whitespace-pre-line break-words">${esc(d.note)}</div>` : '',
                link
                    ? `<a href="${window.escapeAttr(link)}" target="_blank" rel="noopener noreferrer" class="block text-purple-300 hover:text-white break-all">${esc(d.url)}</a>`
                    : '',
                `<div class="flex flex-wrap gap-2">
                    <button type="button" data-panel-edit class="px-3 py-1.5 bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-lg text-xs text-gray-200"><i class="fas fa-pencil-alt mr-1.5"></i>Edit</button>
                    ${d.type in (window.ENTITY_LABELS || {}) ? '<button type="button" data-panel-add-to-case class="px-3 py-1.5 bg-purple-700 hover:bg-purple-600 rounded-lg text-xs text-white"><i class="fas fa-plus-circle mr-1.5"></i>Add to the investigation</button>' : ''}
                </div>`,
                '<p class="text-xs text-gray-500">Added by you in the graph. It is only in this graph until you add it to the investigation.</p>',
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

Object.assign(GraphView.prototype, editing);
Object.assign(GraphView.prototype, pivoting);
Object.assign(GraphView.prototype, finding);
Object.assign(GraphView.prototype, framing);
