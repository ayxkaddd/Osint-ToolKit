// Pivots from the graph: an identifier's menu (look up with another module, copy,
// assessment, note), the lookups running on it drawn as pending nodes, and the new
// branch growing out of it when the lookup finishes. Methods of GraphView (view.js).
import { clip, typeName } from './view.js';
import { decorate } from './style.js';

const REDUCED_MOTION = window.matchMedia('(prefers-reduced-motion: reduce)');
const motion = (ms) => (REDUCED_MOTION.matches ? 0 : ms);
export const TRIAGE = {
    confirmed: { label: 'Confirmed', icon: 'fa-check-circle' },
    important: { label: 'Important', icon: 'fa-star' },
    false_positive: { label: 'False positive', icon: 'fa-times-circle' },
};

export const pivoting = {
    // The result a lookup on this node is attached under: the latest result of the record
    // it is in (the card it hangs under in the tree, or the card itself). Nothing for what
    // was typed.
    parentResultFor(node) {
        let at = node.data('kind') === 'card' ? node : this.cy.getElementById(this.parentOf.get(node.id()) || '');
        for (let hops = 0; at.length && hops < 20; hops++) {
            const kind = at.data('kind');
            if (kind === 'card') return at.data('result_ids')?.slice(-1)[0] || null;
            if (kind === 'lookup') return at.data('result_id') || null;
            at = this.cy.getElementById((kind === 'group' ? at.data('owner') : this.parentOf.get(at.id())) || '');
        }
        return null;
    },

    // The app's pivot menu at the node (the menu is placed under an element: one where the node is)
    pivotFrom(node) {
        const box = this.canvas.getBoundingClientRect();
        const at = node.renderedPosition();
        let anchor = document.getElementById('graphPivotAnchor');
        if (!anchor) {
            anchor = document.createElement('span');
            anchor.id = 'graphPivotAnchor';
            anchor.setAttribute('aria-hidden', 'true');
            anchor.className = 'fixed w-px h-px pointer-events-none';
            document.body.appendChild(anchor);
        }
        anchor.style.left = `${box.left + at.x}px`;
        anchor.style.top = `${box.top + at.y + node.renderedHeight() / 2}px`;
        window.openPivotMenu(node.data('type'), node.data('value'), anchor, {
            parentResultId: this.parentResultFor(node),
        });
    },

    identifierItems(node) {
        const d = node.data();
        const triage = (status) => ({
            label: TRIAGE[status].label,
            icon: TRIAGE[status].icon,
            checked: d.status === status,
            onClick: () => this.setTriage(node.id(), d.status === status ? null : status),
        });
        return [
            {
                label: 'Look up with another module…',
                icon: 'fa-search',
                // after this click is done: the page closes the pivot menu on any click outside it
                onClick: () => setTimeout(() => this.pivotFrom(node)),
            },
            { label: 'Copy', icon: 'fa-copy', onClick: () => window.copyTextToClipboard?.(d.value) },
            { divider: true },
            triage('confirmed'),
            triage('important'),
            triage('false_positive'),
            {
                label: d.note ? 'Edit the note…' : 'Add a note…',
                icon: 'fa-sticky-note',
                onClick: () => this.noteDialog(node.id()),
            },
            { divider: true },
            { label: 'Focus on it', icon: 'fa-crosshairs', onClick: () => this.focusOn(node.id()) },
            {
                label: 'Where it was found',
                icon: 'fa-list',
                href: `/api/investigations/${encodeURIComponent(this.investigationId)}/view?identifier=${encodeURIComponent(d.value)}#identifiers`,
            },
        ];
    },

    // Assessment and note are the case's own (PATCH .../entities), not only the graph's
    async saveTriage(id, status, note) {
        const response = await fetch(`/api/investigations/${encodeURIComponent(this.investigationId)}/entities`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ key: id.slice(2), status, note }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
        const node = this.cy.getElementById(id);
        if (node.length) this.setData(node, { status: data.entity.status, note: data.entity.note });
        if (this.panelNode === id) this.openPanel(node);
    },

    async setTriage(id, status) {
        try {
            await this.saveTriage(id, status, this.cy.getElementById(id).data('note') || null);
            window.showTemporaryNotification?.(
                status ? `Marked ${TRIAGE[status].label.toLowerCase()}` : 'Assessment cleared'
            );
        } catch (error) {
            window.showTemporaryNotification?.(`Not saved: ${error.message}`, 'error');
        }
    },

    noteDialog(id) {
        const node = this.cy.getElementById(id);
        if (!node.length) return;
        this.dialog(
            'Note',
            `<p class="text-sm text-gray-400 break-all">${window.escapeHtml(typeName(node.data('type')))} · ${window.escapeHtml(node.data('display') || node.data('value'))}</p>
             <textarea name="note" rows="5" maxlength="5000" placeholder="What you know about it"
                class="w-full bg-gray-950 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-purple-500">${window.escapeHtml(node.data('note') || '')}</textarea>`,
            (form) => this.saveTriage(id, node.data('status') || null, form.elements.note.value.trim() || null)
        );
    },

    // -----------------------------------------------------------------------
    // Lookups running on identifiers of this case: pending nodes, then the branch
    // -----------------------------------------------------------------------
    watchJobs() {
        document.addEventListener('jobs:started', (e) => this.onJobStarted(e.detail));
        document.addEventListener('jobs:updated', (e) => this.onJobsUpdated(e.detail || []));
        document.addEventListener('investigation:updated', (e) => {
            if (!e.detail?.investigationId || e.detail.investigationId === this.investigationId) this.mergeFresh();
        });
        // lookups started anywhere else (another page or tab) are noticed too, while the
        // graph is on screen; refreshJobs then follows them every 2 s until they finish
        this.activeJobs = new Set();
        setInterval(() => {
            if (this.cy && document.visibilityState === 'visible' && !this.root.closest('.hidden'))
                window.refreshJobs?.();
        }, 8000);
    },

    onJobStarted(job) {
        if (!job || !this.cy) return;
        if (job.investigation_id !== this.investigationId) {
            // background lookups are saved to the investigation being recorded
            if (!this.root.closest('.hidden'))
                window.showTemporaryNotification?.(
                    'This lookup is saved to the investigation being recorded, not this one. Press "Record here" to save lookups to this case.',
                    'info'
                );
            return;
        }
        this.onJobsUpdated([job]);
    },

    onJobsUpdated(jobs) {
        if (!this.cy) return;
        let finished = false;
        // the first list after the page opened: what was already there is not news
        const first = !this.knownJobs;
        this.knownJobs = this.knownJobs || new Set();
        for (const job of jobs) {
            if (job.investigation_id !== this.investigationId) continue;
            const pending = this.cy.getElementById(`p:${job.id}`);
            const active = job.status === 'queued' || job.status === 'running';
            // started and done between two looks (a quick lookup started elsewhere)
            const wasActive = this.activeJobs.has(job.id) || (!first && !this.knownJobs.has(job.id));
            this.knownJobs.add(job.id);
            if (active) this.activeJobs.add(job.id);
            else this.activeJobs.delete(job.id);
            if (!pending.length) {
                if (active) this.addPending(job);
                // done without a pending node (its identifier wasn't drawn): the graph still grows
                else if (wasActive && job.status === 'done') finished = true;
            } else if (job.status === 'done') this.finishPending(pending, job);
            else if (pending.data('status') !== 'failed') this.setData(pending, this.pendingData(job));
        }
        if (finished) this.mergeFresh();
    },

    pendingData(job) {
        const p = job.progress || {};
        const status = job.status === 'queued' || job.status === 'running' ? 'running' : 'failed';
        const progress =
            job.status === 'queued'
                ? 'waiting…'
                : job.status === 'running'
                  ? `running${p.total ? ` ${p.done || 0}/${p.total}` : p.done ? ` ${p.done}` : '…'}${p.found ? ` · ${p.found} found` : ''}`
                  : job.status === 'cancelled'
                    ? 'cancelled · click to dismiss'
                    : 'failed · click to dismiss';
        const title = clip(job.module_name, 30);
        return {
            label: `${title}\n${progress}`,
            status,
            error: job.error || (job.status === 'cancelled' ? 'Cancelled' : null),
            module_name: job.module_name,
            value: job.value,
            w: 50 + 6.2 * Math.max(title.length, progress.length),
            h: 40,
        };
    },

    addPending(job) {
        const key = `${job.entity_type}:${job.value}`;
        let from = this.cy.getElementById(`e:${key}`);
        // an account's address or id is drawn as its card
        if (!from.length)
            from = this.cy
                .nodes('[kind = "card"]')
                .filter((n) => n.data('own')?.includes(key))
                .first();
        if (!from.length) return;
        const id = `p:${job.id}`;
        const data = {
            id,
            kind: 'pending',
            job: job.id,
            order: this.order++,
            color: '#a855f7',
            ...this.pendingData(job),
        };
        data.decor = decorate(data);
        const added = this.cy.add([
            { group: 'nodes', data },
            { group: 'edges', data: { id: `${from.id()}>${id}`, source: from.id(), target: id, kind: 'searched' } },
        ]);
        this.grow(added.nodes(), from);
        this.spin();
    },

    // The pending node goes; what the lookup found grows out of the identifier
    async finishPending(pending, job) {
        const from = pending.incomers('node').first();
        // its cards take the pending node's place
        if (from.length) this.placeHints.set(from.id(), { ...pending.position() });
        pending.remove();
        await this.mergeFresh({ around: from.length ? from : null });
        if (job.result_id && from.length) {
            const found = from
                .outgoers('node')
                .filter((n) => (n.data('result_ids') || []).includes(job.result_id) || n.data('kind') === 'group');
            this.pulse(found.union(found.outgoers('node')));
        }
    },

    dismissPending(node) {
        node.remove();
        this.relayout();
    },

    // A slowly turning purple arc on running lookups
    spin() {
        if (this.spinning || !motion(1)) return;
        this.spinning = true;
        let offset = 0;
        const tick = () => {
            const running = this.cy?.nodes('[kind = "pending"][status = "running"]');
            if (!running?.length) {
                this.spinning = false;
                return;
            }
            offset = (offset + 1.5) % 400;
            running.style('border-dash-offset', -offset);
            requestAnimationFrame(tick);
        };
        requestAnimationFrame(tick);
    },

    pulse(nodes) {
        if (!motion(1) || !nodes?.length) return;
        nodes.addClass('pulse');
        setTimeout(() => nodes.removeClass('pulse'), 1400);
    },

    // What the server has now that isn't drawn yet (a finished lookup, something added
    // elsewhere), added and grown; what is drawn gets its new counts. Nothing is added
    // under a lookup or group the analyst folded.
    async mergeFresh({ around = null } = {}) {
        if (!this.cy || this.merging) return;
        this.merging = true;
        try {
            const graph = await this.api('graph');
            this.statsData = graph.stats;
            // folded by the analyst, or closed by the server's budget: what is new waits in it
            const folded = (id) => {
                const node = this.cy.getElementById(id);
                if (!node.length || node.data('open')) return false;
                if (node.data('kind') === 'group') return true;
                return this.stash.has(id) || this.state.data.collapsed.includes(id) || node.data('hidden') > 0;
            };
            const fresh = [];
            for (const n of graph.nodes) {
                const node = this.cy.getElementById(n.id);
                if (node.length) {
                    const { order, open, foldable, pinned } = node.data();
                    this.setData(node, { ...this.nodeData(n), order, open, foldable, pinned });
                    continue;
                }
                const from = graph.edges.filter((e) => e.target === n.id).map((e) => e.source);
                if (from.length && from.every(folded)) continue;
                fresh.push(n);
            }
            const added = this.cy.add(this.elements(fresh, graph.edges));
            // and links between nodes that were already drawn
            this.cy.add(this.elements([], graph.edges));
            // what new children grew under is open now (a double-click folds it)
            added
                .nodes()
                .incomers('node')
                .not('[kind = "group"]')
                .forEach((n) => n.data('open') || this.setData(n, { open: true }));
            this.attachManualEdges();
            if (!added.nodes().length) {
                this.refreshFoldable(this.cy.nodes());
                this.updateStats();
                // a pending node may have gone: the rows close up
                await this.relayout();
                return;
            }
            this.show('');
            this.loadSummary();
            await this.grow(added.nodes(), around);
            this.pulse(added.nodes());
        } catch (error) {
            window.showTemporaryNotification?.(`The graph was not updated (${error.message})`, 'error');
        } finally {
            this.merging = false;
        }
    },
};
