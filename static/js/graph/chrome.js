// Around the graph: the web layout and the switch between layouts, the legend, the
// minimap, exports (PNG, SVG, JSON, GEXF) and the picture kept for the case report.
// Methods of GraphView (view.js).
import { MANUAL_TYPES, OFF, TYPE_ICONS, decorate, iconUri, typeColor } from './style.js';
import { typeName } from './view.js';

const esc = (value) => window.escapeHtml(value);
const attr = (value) => window.escapeAttr(value);
const REDUCED_MOTION = window.matchMedia('(prefers-reduced-motion: reduce)');
const motion = (ms) => (REDUCED_MOTION.matches ? 0 : ms);
const SNAPSHOT_DELAY = 4000;

// A picture from another site can't go into an exported image (the browser forbids
// reading a canvas that drew it), and a report says nothing about other cases
const sameSite = (url) => !url || url.startsWith('/') || url.startsWith('data:');

export const framing = {
    // -----------------------------------------------------------------------
    // Layouts: the tree (layout.js) or a web where shared identifiers pull branches together
    // -----------------------------------------------------------------------
    layoutName() {
        return this.state.data.layout === 'web' && window.cytoscapeFcose ? 'web' : 'tree';
    },

    async toggleLayout() {
        const web = this.layoutName() !== 'web';
        this.state.change((s) => {
            s.layout = web ? 'web' : 'tree';
        });
        this.updateToolbar();
        await this.relayout({ full: true });
        this.fit();
    },

    // fcose with the nodes the analyst placed held where they are
    runWeb({ animate = true, grown = null, fresh = false } = {}) {
        const drawn = this.cy.elements().not(OFF);
        const nodes = drawn.nodes();
        const fixed = nodes
            .filter((n) => n.data('pinned'))
            .map((n) => ({ nodeId: n.id(), position: { ...n.position() } }));
        const duration = animate ? motion(500) : 0;
        const layout = drawn.layout({
            name: 'fcose',
            quality: 'default',
            randomize: fresh && !fixed.length,
            animate: duration > 0 ? 'end' : false,
            animationDuration: duration,
            animationEasing: 'ease-out-cubic',
            fit: false,
            nodeDimensionsIncludeLabels: true,
            packComponents: true,
            nodeRepulsion: () => 9000,
            idealEdgeLength: (edge) => (edge.data('kind') === 'member' ? 70 : 110),
            edgeElasticity: () => 0.4,
            fixedNodeConstraint: fixed.length ? fixed : undefined,
        });
        const done = layout.promiseOn('layoutstop');
        layout.run();
        return done.then(() => {
            if (!grown?.size) return null;
            const fresh = nodes.filter((n) => grown.has(n.id()));
            return Promise.all(
                fresh.map((n) =>
                    n
                        .animation(
                            { style: { opacity: 1, width: n.data('w'), height: n.data('h') } },
                            { duration: motion(250) }
                        )
                        .play()
                        .promise()
                        .then(() => n.removeStyle('opacity width height'))
                )
            );
        });
    },

    // -----------------------------------------------------------------------
    // Legend: the kinds of node drawn now
    // -----------------------------------------------------------------------
    renderLegend() {
        const counts = new Map();
        this.cy
            .nodes()
            .not(OFF)
            .forEach((n) => {
                const d = n.data();
                if (d.kind === 'identifier' || d.kind === 'manual') counts.set(d.type, (counts.get(d.type) || 0) + 1);
            });
        const rows = [...counts.entries()]
            .sort((a, b) => b[1] - a[1])
            .map(
                ([type, count]) => `
                <div class="flex items-center gap-2">
                    <span class="w-4 h-4 rounded-full border-2 bg-[#1a1b26] flex items-center justify-center shrink-0" style="border-color:${attr(typeColor(type))}">
                        <img src="${attr(iconUri(MANUAL_TYPES[type]?.icon || TYPE_ICONS[type] || 'circle', '#ffffff', 0.8))}" alt="" class="w-2.5 h-2.5"></span>
                    <span class="flex-1 truncate">${esc(typeName(type))}</span><span class="text-gray-500">${count}</span>
                </div>`
            )
            .join('');
        const shapes = `
            <div class="flex items-center gap-2"><span class="w-5 h-3 rounded border border-[#3b3f57] bg-[#0f1017] shrink-0"></span>Lookup</div>
            <div class="flex items-center gap-2"><span class="w-4 h-4 rounded-full border border-gray-500 outline outline-1 outline-offset-1 outline-gray-600 shrink-0"></span>Group, folded</div>
            <div class="flex items-center gap-2"><span class="w-4 h-0 border-t border-dashed border-purple-300 shrink-0"></span>Your link</div>`;
        this.legendBody.innerHTML =
            rows + `<div class="mt-1.5 pt-1.5 border-t border-[#24283b] space-y-1 text-gray-400">${shapes}</div>`;
    },

    toggleLegend() {
        const open = this.legendBody.classList.toggle('hidden');
        try {
            localStorage.setItem('graphLegend', open ? 'closed' : 'open');
        } catch {
            /* not kept: private window */
        }
    },

    // -----------------------------------------------------------------------
    // Minimap: the whole graph small, and where the screen is on it
    // -----------------------------------------------------------------------
    // The nodes and links are drawn once per change (``nodesMoved``); panning and
    // zooming only draw the frame of the screen over them
    drawMinimap(nodesMoved = true) {
        this.minimapDirty = this.minimapDirty || nodesMoved;
        if (this.minimapQueued) return;
        this.minimapQueued = true;
        requestAnimationFrame(() => {
            this.minimapQueued = false;
            const canvas = this.minimap;
            if (!this.cy || canvas.closest('.hidden')) return;
            const ratio = window.devicePixelRatio || 1;
            const width = canvas.clientWidth;
            const height = canvas.clientHeight;
            if (this.minimapDirty || !this.minimapBase || this.minimapBase.width !== width * ratio) {
                this.minimapDirty = false;
                this.minimapBase = this.drawMinimapBase(width, height, ratio);
            }
            canvas.width = width * ratio;
            canvas.height = height * ratio;
            const ctx = canvas.getContext('2d');
            ctx.drawImage(this.minimapBase, 0, 0);
            const frame = this.minimapFrame;
            if (!frame) return;
            ctx.scale(ratio, ratio);
            const view = this.cy.extent();
            ctx.strokeStyle = '#a855f7';
            ctx.lineWidth = 1.2;
            ctx.strokeRect(
                view.x1 * frame.scale + frame.ox,
                view.y1 * frame.scale + frame.oy,
                view.w * frame.scale,
                view.h * frame.scale
            );
        });
    },

    drawMinimapBase(width, height, ratio) {
        const base = document.createElement('canvas');
        base.width = width * ratio;
        base.height = height * ratio;
        const ctx = base.getContext('2d');
        ctx.scale(ratio, ratio);
        const nodes = this.cy.nodes().not(OFF);
        this.minimapFrame = null;
        if (!nodes.length) return base;
        const box = nodes.boundingBox();
        const scale = Math.min((width - 12) / Math.max(box.w, 1), (height - 12) / Math.max(box.h, 1));
        const ox = (width - box.w * scale) / 2 - box.x1 * scale;
        const oy = (height - box.h * scale) / 2 - box.y1 * scale;
        this.minimapFrame = { scale, ox, oy };
        ctx.strokeStyle = 'rgba(75,85,99,.5)';
        ctx.lineWidth = 0.5;
        ctx.beginPath();
        this.cy
            .edges()
            .not(OFF)
            .forEach((e) => {
                const a = e.source().position();
                const b = e.target().position();
                ctx.moveTo(a.x * scale + ox, a.y * scale + oy);
                ctx.lineTo(b.x * scale + ox, b.y * scale + oy);
            });
        ctx.stroke();
        nodes.forEach((n) => {
            const p = n.position();
            ctx.fillStyle = n.data('kind') === 'lookup' ? '#4b5563' : n.data('color') || '#9ca3af';
            ctx.beginPath();
            ctx.arc(p.x * scale + ox, p.y * scale + oy, n.data('kind') === 'lookup' ? 1.6 : 2.2, 0, Math.PI * 2);
            ctx.fill();
        });
        return base;
    },

    // Click or drag on the minimap: that place in the middle of the screen
    minimapPan(e) {
        const frame = this.minimapFrame;
        if (!frame) return;
        const box = this.minimap.getBoundingClientRect();
        const x = (e.clientX - box.left - frame.ox) / frame.scale;
        const y = (e.clientY - box.top - frame.oy) / frame.scale;
        const zoom = this.cy.zoom();
        this.moved = true;
        this.cy.pan({ x: this.canvas.clientWidth / 2 - x * zoom, y: this.canvas.clientHeight / 2 - y * zoom });
    },

    // -----------------------------------------------------------------------
    // Exports
    // -----------------------------------------------------------------------
    exportMenu(button) {
        const base = `/api/investigations/${encodeURIComponent(this.investigationId)}/graph/export`;
        window.openContextMenu(
            button,
            [
                { label: 'Picture (PNG)', icon: 'fa-image', onClick: () => this.exportPng() },
                { label: 'Drawing (SVG)', icon: 'fa-bezier-curve', onClick: () => this.exportSvg() },
                { divider: true },
                { label: 'Whole graph (JSON)', icon: 'fa-file-code', href: `${base}?format=json` },
                { label: 'Whole graph for Gephi (GEXF)', icon: 'fa-project-diagram', href: `${base}?format=gexf` },
            ],
            'Export'
        );
    },

    // <case name>-graph.<ext>
    async fileName(ext) {
        if (this.caseName === undefined) {
            const info = await fetch(`/api/investigations/${encodeURIComponent(this.investigationId)}/info`)
                .then((r) => (r.ok ? r.json() : {}))
                .catch(() => ({}));
            this.caseName = info.investigation?.name || '';
        }
        const name = this.caseName
            .replace(/[^\p{L}\p{N}_-]+/gu, '-')
            .replace(/^-+|-+$/g, '')
            .slice(0, 60);
        return `${name || 'investigation'}-graph.${ext}`;
    },

    download(blob, name) {
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = name;
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 2000);
    },

    // The graph drawn for a picture: no hover or search dimming, no pictures from other
    // sites; for the report also nothing about other cases. Put back after.
    async asPicture(work, { forReport = false } = {}) {
        const marks = '.hover, .faded, .lit, .match, .search-dim, .pulse';
        const marked = this.cy.elements(marks).map((e) => [e, e.classes().filter((c) => marks.includes(`.${c}`))]);
        const changed = [];
        this.cy.batch(() => {
            this.cy.elements(marks).removeClass(marks.replace(/[.,]/g, ' '));
            this.cy.nodes().forEach((n) => {
                const d = n.data();
                const external = d.picture && !sameSite(d.picture);
                if (external || (forReport && d.shared)) {
                    changed.push([n, d.decor]);
                    n.data(
                        'decor',
                        decorate({ ...d, picture: external ? null : d.picture, shared: forReport ? 0 : d.shared })
                    );
                }
            });
        });
        try {
            return await work();
        } finally {
            this.cy.batch(() => {
                changed.forEach(([n, decor]) => n.data('decor', decor));
                marked.forEach(([e, classes]) => e.addClass(classes.join(' ')));
            });
        }
    },

    async exportPng() {
        try {
            const blob = await this.asPicture(() =>
                this.cy.png({
                    output: 'blob-promise',
                    full: true,
                    scale: 2,
                    bg: '#000000',
                    maxWidth: 12000,
                    maxHeight: 12000,
                })
            );
            this.download(blob, await this.fileName('png'));
        } catch (error) {
            window.showTemporaryNotification?.(`The picture could not be made (${error.message})`, 'error');
        }
    },

    // A drawing of what is on screen: links, nodes with their ring and icon, labels
    exportSvg() {
        const drawn = this.cy.elements().not(OFF);
        const box = drawn.boundingBox({ includeLabels: true });
        const pad = 40;
        const x0 = box.x1 - pad;
        const y0 = box.y1 - pad;
        const xml = (value) =>
            String(value ?? '')
                .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, '')
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;');
        const pt = (p) => `${(p.x - x0).toFixed(1)},${(p.y - y0).toFixed(1)}`;
        const out = [];
        drawn.edges().forEach((e) => {
            const manual = e.data('kind') === 'manual';
            const points = [e.sourceEndpoint(), ...(e.segmentPoints() || e.controlPoints() || []), e.targetEndpoint()];
            out.push(
                `<polyline points="${points.map(pt).join(' ')}" fill="none" stroke="${manual ? '#c4b5fd' : '#4b5563'}" stroke-opacity="${manual ? 0.8 : 0.6}" stroke-width="${manual ? 1.5 : 1}"${manual ? ' stroke-dasharray="6 4"' : ''}/>`
            );
            if (manual && e.data('label')) {
                const mid = e.midpoint();
                out.push(
                    `<text x="${(mid.x - x0).toFixed(1)}" y="${(mid.y - y0).toFixed(1)}" fill="#ddd6fe" font-size="9" text-anchor="middle">${xml(e.data('label'))}</text>`
                );
            }
        });
        drawn.nodes().forEach((n) => {
            const d = n.data();
            const p = n.position();
            const w = n.width();
            const h = n.height();
            const cx = p.x - x0;
            const cy = p.y - y0;
            const pill = ['lookup', 'pending'].includes(d.kind);
            const stroke =
                d.kind === 'lookup' ? '#24283b' : d.status === 'confirmed' ? '#a855f7' : d.color || '#9ca3af';
            out.push(
                pill
                    ? `<rect x="${(cx - w / 2).toFixed(1)}" y="${(cy - h / 2).toFixed(1)}" width="${w.toFixed(1)}" height="${h.toFixed(1)}" rx="12" fill="#0f1017" stroke="${xml(stroke)}" stroke-width="1.5"/>`
                    : `<circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="${(w / 2).toFixed(1)}" fill="${d.kind === 'group' || d.kind === 'more' ? '#0f1017' : '#1a1b26'}" stroke="${xml(stroke)}" stroke-width="2"${d.status === 'false_positive' ? ' stroke-dasharray="4 3" opacity="0.4"' : ''}/>`
            );
            const icon = (d.decor || [])[0];
            if (icon?.uri?.startsWith('data:')) {
                const size = pill ? 16 : w * 0.55;
                const ix = pill ? cx - w / 2 + 12 - size / 2 + 8 : cx - size / 2;
                out.push(
                    `<image href="${xml(icon.uri)}" x="${ix.toFixed(1)}" y="${(cy - size / 2).toFixed(1)}" width="${size.toFixed(1)}" height="${size.toFixed(1)}"/>`
                );
            }
            const lines = String(d.label || '').split('\n');
            if (pill)
                lines.forEach((line, i) =>
                    out.push(
                        `<text x="${(cx - w / 2 + 34).toFixed(1)}" y="${(cy - (lines.length - 1) * 6.5 + i * 13 + 3.5).toFixed(1)}" fill="#d1d5db" font-size="10">${xml(line)}</text>`
                    )
                );
            else
                out.push(
                    `<text x="${cx.toFixed(1)}" y="${(cy + h / 2 + 15).toFixed(1)}" fill="#e5e7eb" font-size="11" text-anchor="middle">${xml(lines[0])}</text>`
                );
        });
        const width = box.w + pad * 2;
        const height = box.h + pad * 2;
        const svg = `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="${width.toFixed(0)}" height="${height.toFixed(0)}" viewBox="0 0 ${width.toFixed(1)} ${height.toFixed(1)}" font-family="JetBrains Mono, ui-monospace, monospace">
<rect width="100%" height="100%" fill="#000"/>
${out.join('\n')}
</svg>`;
        this.fileName('svg').then((name) => this.download(new Blob([svg], { type: 'image/svg+xml' }), name));
    },

    // -----------------------------------------------------------------------
    // The picture in the case report: made a few seconds after the view changes
    // -----------------------------------------------------------------------
    scheduleSnapshot() {
        clearTimeout(this.snapshotTimer);
        this.snapshotTimer = setTimeout(() => this.saveSnapshot(), SNAPSHOT_DELAY);
    },

    async saveSnapshot() {
        if (!this.cy?.nodes().not(OFF).length || this.root.closest('.hidden')) return;
        const look = JSON.stringify([
            this.cy
                .nodes()
                .not(OFF)
                .map((n) => [n.id(), Math.round(n.position('x')), Math.round(n.position('y')), n.data('status')]),
            this.state.data.manual_edges.length,
        ]);
        if (look === this.snapshotLook) return;
        try {
            const blob = await this.asPicture(
                () =>
                    this.cy.png({
                        output: 'blob-promise',
                        full: true,
                        scale: 1.5,
                        bg: '#000000',
                        maxWidth: 4000,
                        maxHeight: 4000,
                    }),
                { forReport: true }
            );
            const response = await fetch(
                `/api/investigations/${encodeURIComponent(this.investigationId)}/graph/image`,
                {
                    method: 'PUT',
                    headers: { 'Content-Type': 'image/png' },
                    body: blob,
                }
            );
            if (response.ok) this.snapshotLook = look;
        } catch {
            /* the report keeps the last picture */
        }
    },
};
