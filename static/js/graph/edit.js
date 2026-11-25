// Editing the graph: putting the saved view back, hiding and removing nodes (and
// the tray that brings them back), moving, adding nodes and links, the context
// menus, keys, and undo / redo. Methods of GraphView (view.js), kept here.
import { spanningTree } from './layout.js';
import { MANUAL_TYPES, typeColor } from './style.js';
import { clip, typeName } from './view.js';

const esc = (value) => window.escapeHtml(value);
const attr = (value) => window.escapeAttr(value);
const REDUCED_MOTION = window.matchMedia('(prefers-reduced-motion: reduce)');
const motion = (ms) => (REDUCED_MOTION.matches ? 0 : ms);

// 32 hex characters (crypto.randomUUID needs https; the app is often opened over plain http)
function newId(prefix) {
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    return prefix + [...bytes].map((b) => b.toString(16).padStart(2, '0')).join('');
}

const isIdentifierType = (type) => type in (window.ENTITY_LABELS || {});

// What a node id says about the node, for nodes that aren't drawn (folded or hidden)
function describeId(id, manualNodes) {
    if (id.startsWith('e:')) {
        const [type, ...rest] = id.slice(2).split(':');
        return { label: clip(rest.join(':')), color: typeColor(type), kind: typeName(type) };
    }
    if (id.startsWith('m:')) {
        const node = manualNodes.find((n) => n.id === id);
        return { label: clip(node?.label || 'Added node'), color: node?.color || typeColor(node?.type), kind: 'Yours' };
    }
    if (id.startsWith('g:')) return { label: clip(id.split(':').pop()), color: '#a78bfa', kind: 'Group' };
    return { label: 'Lookup', color: '#a78bfa', kind: 'Lookup' };
}

function nodeLabel(node) {
    return node.data('kind') === 'lookup' ? node.data('label').split('\n')[0] : node.data('label');
}

export const editing = {
    // -----------------------------------------------------------------------
    // The saved view, put back after the graph loads
    // -----------------------------------------------------------------------
    async restoreView() {
        const s = this.state.data;
        this.cy.add(s.manual_nodes.map((n) => ({ group: 'nodes', data: this.nodeData({ ...n, kind: 'manual' }) })));
        this.attachManualEdges();

        // folded: the deepest first, so each keeps what is folded inside it
        this.relayout({ animate: false });
        const depth = (id) => {
            let d = 0;
            for (let at = id; this.parentOf.has(at); at = this.parentOf.get(at)) d++;
            return d;
        };
        for (const id of [...s.collapsed].sort((a, b) => depth(b) - depth(a))) {
            const node = this.cy.getElementById(id);
            if (node.length && node.data('open')) await this.fold(node, { quiet: true });
        }
        // opened: in waves, as what they are inside of opens
        let pending = [...s.expanded];
        for (let wave = 0; wave < 10 && pending.length; wave++) {
            const later = [];
            for (const id of pending) {
                const node = this.cy.getElementById(id);
                if (!node.length) later.push(id);
                else if (node.data('kind') === 'more') await this.loadMore(node, { quiet: true });
                else if (!(node.data('open') && node.outgoers('node').length)) await this.open(node, { quiet: true });
            }
            if (later.length === pending.length) break;
            pending = later;
        }
        this.applyVisibility();
    },

    attachManualEdges() {
        const add = this.state.data.manual_edges
            .filter(
                (e) =>
                    !this.cy.getElementById(e.id).length &&
                    this.cy.getElementById(e.source).length &&
                    this.cy.getElementById(e.target).length
            )
            .map((e) => ({ group: 'edges', data: { ...e, kind: 'manual' } }));
        if (add.length) this.cy.add(add);
    },

    // -----------------------------------------------------------------------
    // Hidden and removed nodes (with what hangs only under them)
    // -----------------------------------------------------------------------
    applyVisibility() {
        if (!this.cy) return;
        const gone = [...this.state.data.hidden, ...this.state.data.removed];
        const { parentOf } = spanningTree(this.cy.nodes());
        this.cy.batch(() => {
            this.cy.elements('.is-hidden').removeClass('is-hidden');
            for (const id of gone) {
                const node = this.cy.getElementById(id);
                if (!node.length) continue;
                node.addClass('is-hidden');
                this.branch(node, parentOf).addClass('is-hidden');
            }
            this.cy.elements('.is-hidden:selected').unselect();
        });
        if (this.panelNode && this.cy.getElementById(this.panelNode).hasClass('is-hidden')) this.closePanel();
    },

    async hideNodes(ids, list = 'hidden', { record = true } = {}) {
        const s = this.state.data;
        ids = ids.filter((id) => !s.hidden.includes(id) && !s.removed.includes(id));
        if (!ids.length) return;
        const { parentOf } = spanningTree(this.cy.nodes());
        let going = this.cy.collection();
        ids.forEach((id) => {
            const node = this.cy.getElementById(id);
            if (node.length) going = going.union(node).union(this.branch(node, parentOf));
        });
        const duration = motion(180);
        if (duration && going.length)
            await Promise.all(
                going.map((n) =>
                    n
                        .animation({ style: { opacity: 0 } }, { duration })
                        .play()
                        .promise()
                )
            );
        going.removeStyle('opacity');
        this.state.change((state) => state[list].push(...ids));
        if (record)
            this.history.push({
                undo: () => this.showNodes(ids, { record: false }),
                redo: () => this.hideNodes(ids, list, { record: false }),
            });
        this.applyVisibility();
        this.afterVisibilityChange();
        if (record && list === 'removed')
            window.showTemporaryNotification?.(
                ids.length > 1
                    ? `${ids.length} nodes taken off the graph (Ctrl+Z puts them back)`
                    : 'Taken off the graph (Ctrl+Z puts it back)'
            );
    },

    async showNodes(ids, { record = true } = {}) {
        const before = { hidden: [...this.state.data.hidden], removed: [...this.state.data.removed] };
        this.state.change((s) => {
            s.hidden = s.hidden.filter((x) => !ids.includes(x));
            s.removed = s.removed.filter((x) => !ids.includes(x));
        });
        if (record)
            this.history.push({
                undo: () => {
                    this.state.change((s) => Object.assign(s, before));
                    this.applyVisibility();
                    this.afterVisibilityChange();
                },
                redo: () => this.showNodes(ids, { record: false }),
            });
        const wasHidden = this.cy.elements('.is-hidden');
        this.applyVisibility();
        const back = wasHidden.filter((n) => n.isNode() && !n.hasClass('is-hidden'));
        if (motion(1) && back.length) back.style({ opacity: 0 });
        await this.afterVisibilityChange();
        if (back.length)
            await Promise.all(
                back.map((n) =>
                    n
                        .animation({ style: { opacity: 1 } }, { duration: motion(220) })
                        .play()
                        .promise()
                )
            );
        back.removeStyle('opacity');
    },

    async afterVisibilityChange() {
        this.updateToolbar();
        this.updateStats();
        if (!this.tray.classList.contains('hidden')) this.renderTray();
        await this.relayout();
    },

    selectedOr(node) {
        const selected = this.cy.$('node:selected');
        return node && !selected.contains(node) ? node : selected.length ? selected : node || this.cy.collection();
    },

    // -----------------------------------------------------------------------
    // Toolbar and tray
    // -----------------------------------------------------------------------
    updateToolbar() {
        const s = this.state.data;
        const count = s.hidden.length + s.removed.length;
        const counter = this.root.querySelector('[data-tray-count]');
        counter.textContent = count ? String(count) : '';
        this.root.querySelector('[data-tray-button]').title = count
            ? `Hidden and removed nodes (${count})`
            : 'Hidden and removed nodes (none)';
        this.root.querySelector('[data-graph="undo"]').disabled = !this.history.done.length;
        this.root.querySelector('[data-graph="redo"]').disabled = !this.history.undone.length;
    },

    toggleTray() {
        if (!this.tray.classList.contains('hidden')) {
            this.tray.classList.add('hidden');
            return;
        }
        this.renderTray();
        this.tray.classList.remove('hidden');
    },

    renderTray() {
        const s = this.state.data;
        const row = (id) => {
            const node = this.cy.getElementById(id);
            const d = node.length
                ? {
                      label: nodeLabel(node),
                      color: node.data('color'),
                      kind: typeName(node.data('type')) || node.data('kind'),
                  }
                : describeId(id, s.manual_nodes);
            return `
                <div class="flex items-center gap-2 px-3 py-1.5 hover:bg-gray-800/60">
                    <span class="w-2.5 h-2.5 rounded-full shrink-0" style="background:${attr(d.color)}"></span>
                    <button type="button" data-tray-show="${attr(id)}" class="flex-1 min-w-0 text-left truncate text-gray-200 hover:text-white" title="Show it again">${esc(d.label)}</button>
                    <span class="text-[10px] text-gray-500 shrink-0">${esc(d.kind)}</span>
                </div>`;
        };
        const section = (title, ids, hint) =>
            ids.length
                ? `<div class="px-3 pt-3 pb-1 text-[11px] uppercase tracking-wider text-gray-500" title="${attr(hint)}">${esc(title)} · ${ids.length}</div>${ids.map(row).join('')}`
                : '';
        const empty = !s.hidden.length && !s.removed.length;
        this.tray.innerHTML = empty
            ? '<p class="px-4 py-3 text-gray-500">Nothing hidden. Select a node and press H to hide it, Delete to take it off the graph.</p>'
            : `${section('Hidden', s.hidden, 'Hidden from view (H)')}${section('Taken off the graph', s.removed, 'Removed from this graph only; the results stay in the case')}
               <div class="flex justify-end gap-2 px-3 py-2 mt-1 border-t border-[#24283b]">
                   <button type="button" data-tray-all class="text-xs text-purple-300 hover:text-white">Show all</button>
               </div>`;
    },

    onTrayClick(e) {
        const one = e.target.closest('[data-tray-show]');
        if (one) this.showNodes([one.dataset.trayShow]);
        else if (e.target.closest('[data-tray-all]'))
            this.showNodes([...this.state.data.hidden, ...this.state.data.removed]);
    },

    // -----------------------------------------------------------------------
    // Moving nodes
    // -----------------------------------------------------------------------
    dragStart(node) {
        const moving = this.cy.$('node:selected').contains(node) ? this.cy.$('node:selected') : node;
        this.dragging = moving.map((n) => ({
            id: n.id(),
            from: { ...n.position() },
            pinned: !!n.data('pinned'),
            saved: this.state.data.positions[n.id()] || null,
        }));
    },

    dragEnd() {
        const moved = (this.dragging || [])
            .map((d) => ({ ...d, to: { ...this.cy.getElementById(d.id).position() } }))
            .filter((d) => Math.abs(d.to.x - d.from.x) + Math.abs(d.to.y - d.from.y) > 1);
        this.dragging = null;
        if (!moved.length) return;
        const place = (items, which) => {
            this.state.change((s) => {
                items.forEach((d) => {
                    const node = this.cy.getElementById(d.id);
                    const at = which === 'to' ? d.to : d.from;
                    if (node.length) {
                        node.position(at);
                        node.data('pinned', which === 'to' || d.pinned);
                    }
                    if (which === 'to') s.positions[d.id] = [Math.round(at.x), Math.round(at.y)];
                    else if (d.saved) s.positions[d.id] = d.saved;
                    else delete s.positions[d.id];
                });
            });
        };
        place(moved, 'to');
        this.history.push({ undo: () => place(moved, 'from'), redo: () => place(moved, 'to') });
    },

    // -----------------------------------------------------------------------
    // Menus and keys
    // -----------------------------------------------------------------------
    pointAt(e) {
        const box = this.canvas.getBoundingClientRect();
        return { clientX: box.left + e.renderedPosition.x, clientY: box.top + e.renderedPosition.y };
    },

    elementMenu(ele, e) {
        this.hideTooltip();
        if (ele.isEdge()) {
            if (ele.data('kind') !== 'manual') return;
            const id = ele.id();
            window.openContextMenu(
                this.pointAt(e),
                [
                    { label: 'Edit the label…', icon: 'fa-pencil-alt', onClick: () => this.linkDialog(null, null, id) },
                    { label: 'Delete the link', icon: 'fa-trash', danger: true, onClick: () => this.deleteLink(id) },
                ],
                ele.data('label') || 'Your link'
            );
            return;
        }
        const node = ele;
        const kind = node.data('kind');
        if (kind === 'more') return;
        if (kind === 'pending') {
            if (node.data('status') === 'failed')
                window.openContextMenu(this.pointAt(e), [
                    { label: 'Dismiss', icon: 'fa-times', onClick: () => this.dismissPending(node) },
                ]);
            return;
        }
        const targets = this.selectedOr(node);
        const many = targets.length > 1;
        const ids = targets.map((n) => n.id());
        const items = [];
        if (many) {
            items.push(
                ...(ids.length === 2
                    ? [
                          {
                              label: 'Link these two…',
                              icon: 'fa-link',
                              onClick: () => this.linkDialog(...this.selectionOrder(targets)),
                          },
                      ]
                    : []),
                { label: `Hide ${ids.length} nodes`, icon: 'fa-eye-slash', onClick: () => this.hideNodes(ids) },
                {
                    label: `Take ${ids.length} nodes off the graph`,
                    icon: 'fa-minus-circle',
                    onClick: () => this.hideNodes(ids, 'removed'),
                }
            );
            window.openContextMenu(this.pointAt(e), items, `${ids.length} selected`);
            return;
        }
        if (kind === 'identifier') items.push(...this.identifierItems(node), { divider: true });
        if (kind === 'lookup' || kind === 'group')
            items.push({
                label: node.data('open') && node.outgoers('node').length ? 'Fold' : 'Open',
                icon: 'fa-sitemap',
                onClick: () => this.toggle(node, { record: true }),
            });
        if (kind === 'manual') {
            items.push({
                label: 'Edit…',
                icon: 'fa-pencil-alt',
                onClick: () => this.nodeDialog({ editing: node.id() }),
            });
            if (isIdentifierType(node.data('type')))
                items.push({
                    label: 'Add to the investigation…',
                    icon: 'fa-plus-circle',
                    onClick: () => this.nodeDialog({ editing: node.id(), addToCase: true }),
                });
        }
        items.push(
            { label: 'Link to…', icon: 'fa-link', onClick: () => this.startLink(node) },
            { divider: true },
            {
                label: many ? `Hide ${ids.length} nodes` : 'Hide',
                icon: 'fa-eye-slash',
                onClick: () => this.hideNodes(ids),
            },
            {
                label: many ? `Take ${ids.length} nodes off the graph` : 'Take off the graph',
                icon: 'fa-minus-circle',
                onClick: () => this.hideNodes(ids, 'removed'),
            }
        );
        if (kind === 'manual')
            items.push({
                label: 'Delete',
                icon: 'fa-trash',
                danger: true,
                onClick: () => this.deleteManualNode(node.id()),
            });
        if (kind === 'lookup' && !many) {
            const runs = node.data('runs') || [];
            // only whole results can be deleted (a follow-up goes with the result it is in)
            if (runs.length && runs.every((r) => !r.child_id))
                items.push(
                    { divider: true },
                    {
                        label: runs.length > 1 ? `Delete the ${runs.length} results too…` : 'Delete the result too…',
                        icon: 'fa-trash',
                        danger: true,
                        onClick: () => this.deleteResults(node),
                    }
                );
        }
        window.openContextMenu(this.pointAt(e), items, many ? `${ids.length} selected` : nodeLabel(node));
    },

    canvasMenu(e) {
        this.hideTooltip();
        const at = { ...e.position };
        const s = this.state.data;
        const gone = s.hidden.length + s.removed.length;
        window.openContextMenu(this.pointAt(e), [
            { label: 'Add a node here…', icon: 'fa-plus', onClick: () => this.nodeDialog({ at }) },
            ...(gone
                ? [{ label: `Hidden and removed (${gone})`, icon: 'fa-eye', onClick: () => this.toggleTray() }]
                : []),
            { label: 'Fit to screen', icon: 'fa-expand', onClick: () => this.fit() },
        ]);
    },

    onKey(e) {
        if (e.target.closest('input, textarea, select, [contenteditable]') || document.getElementById('graphDialog'))
            return;
        const mod = e.ctrlKey || e.metaKey;
        const key = e.key.toLowerCase();
        const selected = this.cy?.$('node:selected') || [];
        let handled = true;
        if (mod && key === 'z' && !e.shiftKey) this.undo();
        else if (mod && ((key === 'z' && e.shiftKey) || key === 'y')) this.redo();
        else if (mod || e.altKey) handled = false;
        else if (key === 'h' && selected.length) this.hideNodes(selected.map((n) => n.id()));
        else if ((key === 'delete' || key === 'backspace') && selected.length)
            this.hideNodes(
                selected.map((n) => n.id()),
                'removed'
            );
        else if (key === 'n') this.nodeDialog({});
        else if (key === 'l') {
            if (selected.length === 2) this.linkDialog(...this.selectionOrder(selected));
            else this.startLink(selected.length === 1 ? selected : null);
        } else if (key === 'escape') {
            if (!this.cancelLink()) {
                if (!this.tray.classList.contains('hidden')) this.tray.classList.add('hidden');
                else if (this.panelNode) this.closePanel();
                else this.cy?.$(':selected').unselect();
            }
        } else if (key === '0') this.fit();
        else if (key === '+' || key === '=') this.zoomIn();
        else if (key === '-') this.zoomOut();
        else handled = false;
        if (handled) e.preventDefault();
    },

    async undo() {
        if (!(await this.history.undo())) return;
        this.applyVisibility();
        await this.afterVisibilityChange();
    },

    async redo() {
        if (!(await this.history.redo())) return;
        this.applyVisibility();
        await this.afterVisibilityChange();
    },

    // -----------------------------------------------------------------------
    // Links drawn by the analyst
    // -----------------------------------------------------------------------
    startLink(from = null) {
        this.cancelLink();
        this.linking = { from: from?.length ? from.id() : null };
        if (from?.length) from.addClass('link-from');
        this.modeBar.textContent = from?.length
            ? 'Click the node to link it to · Esc to cancel'
            : 'Click the first node of the link · Esc to cancel';
        this.modeBar.classList.remove('hidden');
        this.root.focus({ preventScroll: true });
    },

    finishLink(node) {
        if (node.data('kind') === 'more') return;
        if (!this.linking.from) return this.startLink(node);
        const from = this.linking.from;
        this.cancelLink();
        if (from !== node.id()) this.linkDialog(from, node.id());
    },

    cancelLink() {
        if (!this.linking) return false;
        this.cy.$('.link-from').removeClass('link-from');
        this.modeBar.classList.add('hidden');
        this.linking = null;
        return true;
    },

    addLink(edge, { record = true } = {}) {
        this.state.change((s) => s.manual_edges.push(edge));
        this.attachManualEdges();
        if (record)
            this.history.push({
                undo: () => this.deleteLink(edge.id, { record: false }),
                redo: () => this.addLink(edge, { record: false }),
            });
    },

    deleteLink(id, { record = true } = {}) {
        const edge = this.state.data.manual_edges.find((e) => e.id === id);
        if (!edge) return;
        this.state.change((s) => {
            s.manual_edges = s.manual_edges.filter((e) => e.id !== id);
        });
        this.cy.getElementById(id).remove();
        if (record)
            this.history.push({
                undo: () => this.addLink(edge, { record: false }),
                redo: () => this.deleteLink(id, { record: false }),
            });
    },

    setLinkLabel(id, label, { record = true } = {}) {
        const edge = this.state.data.manual_edges.find((e) => e.id === id);
        if (!edge) return;
        const before = edge.label || '';
        this.state.change(() => {
            edge.label = label;
        });
        this.cy.getElementById(id).data('label', label);
        if (record)
            this.history.push({
                undo: () => this.setLinkLabel(id, before, { record: false }),
                redo: () => this.setLinkLabel(id, label, { record: false }),
            });
    },

    // -----------------------------------------------------------------------
    // Nodes added by the analyst
    // -----------------------------------------------------------------------
    addManualNode(node, at, { record = true } = {}) {
        this.state.change((s) => {
            s.manual_nodes.push(node);
            s.positions[node.id] = [Math.round(at.x), Math.round(at.y)];
        });
        const added = this.cy.add({
            group: 'nodes',
            data: this.nodeData({ ...node, kind: 'manual' }),
            position: { ...at },
        });
        added.data('pinned', true);
        this.attachManualEdges();
        this.show('');
        if (record)
            this.history.push({
                undo: () => this.deleteManualNode(node.id, { record: false }),
                redo: () => this.addManualNode(node, at, { record: false }),
            });
        if (motion(1)) {
            added.style({ opacity: 0, width: 4, height: 4 });
            added
                .animation(
                    { style: { opacity: 1, width: added.data('w'), height: added.data('h') } },
                    { duration: motion(380), easing: 'cubic-bezier(0.34, 1.4, 0.64, 1)' }
                )
                .play()
                .promise()
                .then(() => added.removeStyle('opacity width height'));
        }
        this.updateStats();
    },

    updateManualNode(id, values, { record = true } = {}) {
        const index = this.state.data.manual_nodes.findIndex((n) => n.id === id);
        if (index < 0) return;
        const before = this.state.data.manual_nodes[index];
        const after = { ...before, ...values, id };
        this.state.change((s) => {
            s.manual_nodes[index] = after;
        });
        const node = this.cy.getElementById(id);
        if (node.length) {
            const { order } = node.data();
            node.data({ ...this.nodeData({ ...after, kind: 'manual' }), order, pinned: true });
        }
        if (this.panelNode === id) this.openPanel(node);
        if (record)
            this.history.push({
                undo: () => this.updateManualNode(id, before, { record: false }),
                redo: () => this.updateManualNode(id, after, { record: false }),
            });
    },

    deleteManualNode(id, { record = true } = {}) {
        const s = this.state.data;
        const node = s.manual_nodes.find((n) => n.id === id);
        if (!node) return;
        const edges = s.manual_edges.filter((e) => e.source === id || e.target === id);
        const at = s.positions[id] || [0, 0];
        this.state.change((state) => {
            state.manual_nodes = state.manual_nodes.filter((n) => n.id !== id);
            state.manual_edges = state.manual_edges.filter((e) => !edges.includes(e));
            state.hidden = state.hidden.filter((x) => x !== id);
            state.removed = state.removed.filter((x) => x !== id);
            delete state.positions[id];
        });
        this.cy.getElementById(id).remove();
        if (this.panelNode === id) this.closePanel();
        this.updateStats();
        if (record)
            this.history.push({
                undo: () => {
                    this.addManualNode(node, { x: at[0], y: at[1] }, { record: false });
                    edges.forEach((e) => this.addLink(e, { record: false }));
                },
                redo: () => this.deleteManualNode(id, { record: false }),
            });
    },

    // The lookup's results go too (they can't be brought back): the app's own delete
    async deleteResults(node) {
        const runs = node.data('runs') || [];
        const ok = await window.appConfirm(
            `${runs.length > 1 ? `All ${runs.length} runs of this lookup are` : 'This result is'} deleted from the investigation, with what only ${runs.length > 1 ? 'they' : 'it'} found. This can't be undone.`,
            { title: 'Delete the result?', confirmLabel: 'Delete', danger: true }
        );
        if (!ok) return;
        for (const run of runs) {
            const response = await fetch(
                `/api/investigations/${encodeURIComponent(this.investigationId)}/results/${encodeURIComponent(run.result_id)}`,
                { method: 'DELETE' }
            );
            if (!response.ok && response.status !== 404) {
                window.showTemporaryNotification?.(`Could not delete it (HTTP ${response.status})`, 'error');
                break;
            }
        }
        document.dispatchEvent(
            new CustomEvent('investigation:updated', { detail: { investigationId: this.investigationId } })
        );
        await this.state.flush();
        await this.load();
    },

    // -----------------------------------------------------------------------
    // Dialogs: a node (new or the analyst's own), a link's label
    // -----------------------------------------------------------------------
    dialog(title, body, onSubmit) {
        document.getElementById('graphDialog')?.remove();
        const before = document.activeElement;
        const overlay = document.createElement('div');
        overlay.id = 'graphDialog';
        overlay.className = 'modal fixed inset-0 bg-black/70 flex items-center justify-center z-[85] p-4';
        overlay.setAttribute('role', 'dialog');
        overlay.setAttribute('aria-modal', 'true');
        overlay.innerHTML = `
            <form class="modal-panel bg-gray-900 rounded-xl p-6 max-w-lg w-full border border-gray-800 shadow-2xl max-h-[92vh] overflow-y-auto custom-scrollbar space-y-4">
                <div class="flex justify-between items-center">
                    <h2 class="text-lg font-bold text-white">${esc(title)}</h2>
                    <button type="button" data-dialog-close class="text-gray-400 hover:text-white" aria-label="Close"><i class="fas fa-times"></i></button>
                </div>
                ${body}
                <p data-dialog-error class="hidden text-sm text-red-400"></p>
                <div class="flex justify-end gap-3 pt-3 border-t border-gray-800">
                    <button type="button" data-dialog-close class="px-4 py-2 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded-lg">Cancel</button>
                    <button type="submit" class="px-5 py-2 bg-purple-600 hover:bg-purple-500 disabled:opacity-50 text-white font-medium rounded-lg">Save</button>
                </div>
            </form>`;
        const close = () => {
            overlay.remove();
            (before || this.root).focus?.({ preventScroll: true });
        };
        const form = overlay.querySelector('form');
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay || e.target.closest('[data-dialog-close]')) close();
        });
        overlay.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                e.stopPropagation();
                close();
            }
        });
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const error = form.querySelector('[data-dialog-error]');
            const submit = form.querySelector('[type="submit"]');
            submit.disabled = true;
            error.classList.add('hidden');
            try {
                await onSubmit(form);
                close();
            } catch (problem) {
                error.textContent = problem.message;
                error.classList.remove('hidden');
            } finally {
                submit.disabled = false;
            }
        });
        document.body.appendChild(overlay);
        requestAnimationFrame(() => overlay.classList.add('modal-open'));
        form.querySelector('input:not([type="hidden"]), select, textarea')?.focus();
        return form;
    },

    linkDialog(source, target, editing = null) {
        const edge = editing ? this.state.data.manual_edges.find((e) => e.id === editing) : null;
        const name = (id) => {
            const node = this.cy.getElementById(id);
            return node.length ? nodeLabel(node) : id;
        };
        const field =
            'w-full bg-gray-950 border border-gray-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-purple-500';
        this.dialog(
            edge ? 'Edit the link' : 'Link two nodes',
            `${edge ? '' : `<p class="text-sm text-gray-400 break-all">${esc(name(source))} → ${esc(name(target))}</p>`}
             <div>
                <label for="graphLinkLabel" class="block text-sm text-gray-300 mb-1">Label <span class="text-gray-500">(optional)</span></label>
                <input id="graphLinkLabel" name="label" maxlength="200" value="${attr(edge?.label || '')}" placeholder="same person, owns, logged in from…" class="${field}">
             </div>`,
            async (form) => {
                const label = form.elements.label.value.trim();
                if (edge) this.setLinkLabel(edge.id, label);
                else this.addLink({ id: newId('l:'), source, target, label });
            }
        );
    },

    // nodeDialog({}) adds a node at the middle of the screen; {at} adds it there;
    // {editing: id} edits the analyst's node; addToCase: ticked from the start
    nodeDialog({ at = null, editing = null, addToCase = false } = {}) {
        const current = editing ? this.state.data.manual_nodes.find((n) => n.id === editing) : null;
        const field =
            'w-full bg-gray-950 border border-gray-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-purple-500';
        const option = (value, label) =>
            `<option value="${attr(value)}" ${(current?.type || 'person') === value ? 'selected' : ''}>${esc(label)}</option>`;
        const ownTypes = Object.entries(MANUAL_TYPES)
            .map(([value, t]) => option(value, t.label))
            .join('');
        const identifierTypes = Object.entries(window.ENTITY_LABELS || {})
            .map(([value, label]) => option(value, label))
            .join('');
        const form = this.dialog(
            current ? 'Edit your node' : 'Add a node',
            `<div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                    <label for="graphNodeType" class="block text-sm text-gray-300 mb-1">Type</label>
                    <select id="graphNodeType" name="type" class="${field}">
                        <optgroup label="Your own">${ownTypes}</optgroup>
                        <optgroup label="Identifier">${identifierTypes}</optgroup>
                    </select>
                </div>
                <div>
                    <label for="graphNodeColor" class="block text-sm text-gray-300 mb-1">Colour</label>
                    <input id="graphNodeColor" name="color" type="color" value="${attr(current?.color || typeColor(current?.type || 'person'))}" class="h-[42px] w-full bg-gray-950 border border-gray-700 rounded-lg px-1">
                </div>
                <div class="sm:col-span-2">
                    <label for="graphNodeLabel" class="block text-sm text-gray-300 mb-1">Label</label>
                    <input id="graphNodeLabel" name="label" required maxlength="200" value="${attr(current?.label || '')}" placeholder="A name, an address, the value of an identifier" class="${field}">
                </div>
                <div class="sm:col-span-2">
                    <label for="graphNodeNote" class="block text-sm text-gray-300 mb-1">Note <span class="text-gray-500">(optional)</span></label>
                    <textarea id="graphNodeNote" name="note" rows="3" maxlength="5000" class="${field} text-sm">${esc(current?.note || '')}</textarea>
                </div>
                <div class="sm:col-span-2">
                    <label for="graphNodeUrl" class="block text-sm text-gray-300 mb-1">Link <span class="text-gray-500">(optional)</span></label>
                    <input id="graphNodeUrl" name="url" type="url" maxlength="2000" value="${attr(current?.url || '')}" placeholder="https://…" class="${field}">
                </div>
                <div class="sm:col-span-2">
                    <label for="graphNodeImage" class="block text-sm text-gray-300 mb-1">Picture <span class="text-gray-500">(optional)</span></label>
                    <input id="graphNodeImage" name="image" type="file" accept="image/*" class="w-full text-sm text-gray-400 file:mr-2 file:py-2 file:px-3 file:rounded-lg file:border-0 file:bg-gray-700 file:text-white">
                    ${current?.image ? '<label class="flex items-center gap-2 text-xs text-gray-400 mt-2"><input type="checkbox" name="dropImage" class="pick-box"> Remove the current picture</label>' : ''}
                </div>
                <label data-add-to-case class="sm:col-span-2 hidden items-start gap-2 text-sm text-gray-300">
                    <input type="checkbox" name="addToCase" class="pick-box mt-0.5" ${addToCase ? 'checked' : ''}>
                    <span>Add to the investigation<span class="block text-xs text-gray-500">It becomes a real identifier, saved as something added by hand: the pivot menu and the rest of the app know it.</span></span>
                </label>
            </div>`,
            async (f) => {
                const type = f.elements.type.value;
                const label = f.elements.label.value.trim();
                const url = f.elements.url.value.trim();
                if (!label) throw new Error('Give it a label');
                if (url && !/^https?:\/\/\S+$/i.test(url))
                    throw new Error('The link must start with http:// or https://');
                const values = {
                    type,
                    label,
                    note: f.elements.note.value.trim(),
                    url: url || null,
                    color: f.elements.color.value || null,
                    image: f.elements.dropImage?.checked ? null : current?.image || null,
                };
                const file = f.elements.image.files[0];
                if (file) values.image = await this.uploadPicture(file);
                const place = current
                    ? this.cy.getElementById(current.id).position()
                    : at || this.freeSpot(this.modelCenter());
                if (isIdentifierType(type) && f.elements.addToCase.checked)
                    return this.addToInvestigation(values, place, current?.id);
                if (current) this.updateManualNode(current.id, values);
                else this.addManualNode({ id: newId('m:'), ...values }, place);
            }
        );
        // the colour follows the type until the analyst picks one
        let colorTouched = !!current?.color;
        const caseBox = form.querySelector('[data-add-to-case]');
        const syncType = () => {
            const type = form.elements.type.value;
            caseBox.classList.toggle('hidden', !isIdentifierType(type));
            caseBox.classList.toggle('flex', isIdentifierType(type));
            if (!colorTouched) form.elements.color.value = typeColor(type);
        };
        form.elements.color.addEventListener('input', () => (colorTouched = true));
        form.elements.type.addEventListener('change', syncType);
        syncType();
        if (current && addToCase) form.elements.label.focus();
    },

    modelCenter() {
        const pan = this.cy.pan();
        const zoom = this.cy.zoom();
        return { x: (this.canvas.clientWidth / 2 - pan.x) / zoom, y: (this.canvas.clientHeight / 2 - pan.y) / zoom };
    },

    // The nearest place around ``at`` with no node on it (a new node never lands on another)
    freeSpot(at) {
        const taken = this.cy
            .nodes()
            .not('.is-hidden')
            .map((n) => n.position());
        const clear = (p) => taken.every((q) => Math.abs(p.x - q.x) > 150 || Math.abs(p.y - q.y) > 64);
        for (let ring = 0; ring < 12; ring++)
            for (let step = 0; step < Math.max(1, ring * 8); step++) {
                const angle = (2 * Math.PI * step) / Math.max(1, ring * 8);
                const p = { x: at.x + ring * 80 * Math.cos(angle), y: at.y + ring * 60 * Math.sin(angle) };
                if (clear(p)) return p;
            }
        return at;
    },

    // Two selected nodes in the order they were clicked (the link goes from the first)
    selectionOrder(nodes) {
        const ids = nodes.map((n) => n.id());
        const clicked = (this.selectedAt || []).filter((id) => ids.includes(id));
        return [...clicked, ...ids.filter((id) => !clicked.includes(id))].slice(0, 2);
    },

    async uploadPicture(file) {
        const body = new FormData();
        body.append('image', file);
        const response = await fetch(`/api/investigations/${encodeURIComponent(this.investigationId)}/note-images`, {
            method: 'POST',
            body,
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.detail || `The picture was not saved (HTTP ${response.status})`);
        return data.url.split('/').pop();
    },

    // A node that is an identifier, added to the case for real: saved as something added
    // by hand (the app's own "Add manually"), then drawn as that identifier where the
    // node was, with its links. Not undone with Ctrl+Z: it is a result now.
    async addToInvestigation(values, place, replacing = null) {
        const base = `/api/investigations/${encodeURIComponent(this.investigationId)}`;
        const body = new FormData();
        body.append('title', `${typeName(values.type)} added in the graph`);
        body.append('identifiers', values.label);
        if (values.note) body.append('text', values.note);
        if (values.url) body.append('url', values.url);
        const response = await fetch(`${base}/manual`, { method: 'POST', body });
        const saved = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(saved.detail || `It was not added (HTTP ${response.status})`);
        const found = await fetch(`${base}/results/${encodeURIComponent(saved.result_id)}/entities`).then((r) =>
            r.ok ? r.json() : { entities: [] }
        );
        const entities = found.entities || [];
        const entity = entities.find((e) => e.type === values.type) || entities[0];
        if (!entity) {
            // saved as text only: keep the node as it was, say why
            throw new Error(
                `"${values.label}" was saved, but not recognised as ${typeName(values.type).toLowerCase()}.`
            );
        }
        const id = `e:${entity.key}`;
        this.state.change((s) => {
            s.positions[id] = [Math.round(place.x), Math.round(place.y)];
            if (replacing) {
                s.manual_nodes = s.manual_nodes.filter((n) => n.id !== replacing);
                s.manual_edges = s.manual_edges.map((e) => ({
                    ...e,
                    source: e.source === replacing ? id : e.source,
                    target: e.target === replacing ? id : e.target,
                }));
                s.hidden = s.hidden.filter((x) => x !== replacing);
                s.removed = s.removed.filter((x) => x !== replacing);
                delete s.positions[replacing];
            }
        });
        document.dispatchEvent(
            new CustomEvent('investigation:updated', { detail: { investigationId: this.investigationId } })
        );
        await this.state.flush();
        await this.load();
        this.focusNode(id);
        window.showTemporaryNotification?.(`${typeName(entity.type)} added to the investigation`);
    },
};
