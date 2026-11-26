// What the tree layout draws besides nodes (layout.js ``decor``): under the graph, the
// lanes' headings ("Accounts · 12"), the frames of grids with the one link to each, and the
// frames of clusters with what links their trees; over it, zoomed far out, a summary of
// each tree ("jdoe · 34 accounts · 6 breaches"), when the nodes are too small to read.
// Methods of GraphView (view.js).
import { GRID } from './layout.js';
import { CARD_KINDS } from './style.js';

// Under this zoom the trees are summed up
const SUMMARY_ZOOM = 0.32;
const LANE_NAMES = {
    sections: 'Results by section',
    identifiers: 'Identifiers',
    facts: 'Shared facts',
    lookups: 'Lookups',
    nothing: 'Looked up, nothing found yet',
};
const FONT = 'JetBrains Mono, ui-monospace, monospace';

export const laning = {
    buildLanes() {
        this.under = this.root.querySelector('.graph-under');
        this.over = this.root.querySelector('.graph-over');
    },

    // once per frame, whatever asked for it
    scheduleLanes() {
        this.lanesDirty = true;
        if (this.lanesFrame) return;
        this.lanesFrame = requestAnimationFrame(() => {
            this.lanesFrame = null;
            this.drawLanes();
        });
    },

    // Drawn in the same frame as the graph (Cytoscape's "render"), so the frames and headings
    // never lag behind the nodes; only when the view or the nodes changed since the last time
    syncLanes() {
        const drawn = this.lanesView;
        const zoom = this.cy.zoom();
        const pan = this.cy.pan();
        if (drawn && !this.lanesDirty && drawn.zoom === zoom && drawn.pan.x === pan.x && drawn.pan.y === pan.y) return;
        this.drawLanes();
    },

    canvasFor(canvas) {
        const ratio = window.devicePixelRatio || 1;
        const w = canvas.clientWidth;
        const h = canvas.clientHeight;
        if (canvas.width !== Math.round(w * ratio) || canvas.height !== Math.round(h * ratio)) {
            canvas.width = Math.round(w * ratio);
            canvas.height = Math.round(h * ratio);
        }
        const ctx = canvas.getContext('2d');
        ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
        ctx.clearRect(0, 0, w, h);
        return ctx;
    },

    // The app's grid on three levels (every 1, 5 and 25 steps), moving and scaling with the
    // graph; zooming out, the finest fades just as the next takes its place, so nothing jumps
    drawGrid(ctx, zoom, pan) {
        const w = this.under.clientWidth;
        const h = this.under.clientHeight;
        let fine = GRID * zoom;
        while (fine < 12) fine *= 5;
        while (fine >= 60) fine /= 5;
        const t = Math.min(1, (fine - 12) / 48);
        const levels = [
            [fine, `rgba(100, 116, 139, ${(0.11 * t).toFixed(3)})`],
            [fine * 5, `rgba(139, 152, 179, ${(0.11 + 0.09 * t).toFixed(3)})`],
            [fine * 25, 'rgba(139, 152, 179, 0.2)'],
        ];
        ctx.lineWidth = 1;
        for (const [step, color] of levels) {
            ctx.beginPath();
            for (let x = ((pan.x % step) + step) % step; x < w; x += step) {
                ctx.moveTo(Math.round(x) + 0.5, 0);
                ctx.lineTo(Math.round(x) + 0.5, h);
            }
            for (let y = ((pan.y % step) + step) % step; y < h; y += step) {
                ctx.moveTo(0, Math.round(y) + 0.5);
                ctx.lineTo(w, Math.round(y) + 0.5);
            }
            ctx.strokeStyle = color;
            ctx.stroke();
        }
    },

    drawLanes() {
        if (!this.cy || !this.under) return;
        const under = this.canvasFor(this.under);
        const zoom = this.cy.zoom();
        const pan = this.cy.pan();
        this.lanesView = { zoom, pan: { ...pan } };
        this.lanesDirty = false;
        this.drawGrid(under, zoom, pan);
        // the canvas over the graph is cleared only when something was drawn on it
        const over = this.overDrawn || zoom < SUMMARY_ZOOM ? this.canvasFor(this.over) : null;
        this.overDrawn = false;
        const decor = this.decor;
        if (!decor) return;
        const sx = (x) => x * zoom + pan.x;
        const sy = (y) => y * zoom + pan.y;
        const far = zoom < SUMMARY_ZOOM;
        // only what is on screen is drawn
        const view = {
            x1: -pan.x / zoom,
            y1: -pan.y / zoom,
            x2: (this.under.clientWidth - pan.x) / zoom,
            y2: (this.under.clientHeight - pan.y) / zoom,
        };
        const seen = (b) => b.x2 >= view.x1 && b.x1 <= view.x2 && b.y2 >= view.y1 && b.y1 <= view.y2;
        const round = (ctx, x1, y1, x2, y2, r) => {
            ctx.beginPath();
            ctx.roundRect(sx(x1), sy(y1), (x2 - x1) * zoom, (y2 - y1) * zoom, r * zoom);
        };

        // clusters: a dashed frame, and what links the trees in it
        for (const c of decor.clusters) {
            if (!seen(c)) continue;
            round(under, c.x1, c.y1, c.x2, c.y2, 18);
            under.fillStyle = 'rgba(109, 40, 217, 0.06)';
            under.fill();
            under.setLineDash([8 * zoom, 6 * zoom]);
            under.strokeStyle = 'rgba(167, 139, 250, 0.45)';
            under.lineWidth = Math.max(1, 1.5 * zoom);
            under.stroke();
            under.setLineDash([]);
            if (!far && c.links.length) {
                under.font = `${Math.max(9, 11 * zoom)}px ${FONT}`;
                under.fillStyle = 'rgba(196, 181, 253, 0.9)';
                under.textBaseline = 'middle';
                under.fillText(`Linked by ${c.links.join(', ')}`, sx(c.x1 + 14), sy(c.y1 + 18));
            }
        }

        // grids: a soft frame, and one link from the parent to it
        for (const g of decor.grids) {
            if (!seen({ ...g, x1: g.x1 - 400 })) continue;
            round(under, g.x1, g.y1, g.x2, g.y2, 12);
            under.fillStyle = 'rgba(26, 27, 38, 0.45)';
            under.fill();
            under.strokeStyle = 'rgba(100, 116, 139, 0.35)';
            under.lineWidth = Math.max(1, zoom);
            under.stroke();
            if (!g.from) continue;
            const from = this.cy.getElementById(g.from);
            if (!from.length || from.is('.is-hidden, .filtered, .unfocused')) continue;
            const p = from.position();
            const start = { x: p.x + from.width() / 2, y: p.y };
            const row = Math.min(Math.max(p.y, g.y1 + 28), g.y2 - 28);
            const bend = g.x1 - 16;
            under.beginPath();
            under.moveTo(sx(start.x), sy(start.y));
            under.lineTo(sx(bend), sy(start.y));
            under.lineTo(sx(bend), sy(row));
            under.lineTo(sx(g.x1), sy(row));
            under.strokeStyle = 'rgba(100, 116, 139, 0.75)';
            under.lineWidth = Math.max(1, 1.8 * zoom);
            under.stroke();
            under.beginPath();
            under.moveTo(sx(g.x1), sy(row));
            under.lineTo(sx(g.x1 - 7), sy(row - 4));
            under.lineTo(sx(g.x1 - 7), sy(row + 4));
            under.closePath();
            under.fillStyle = 'rgba(100, 116, 139, 0.75)';
            under.fill();
        }

        // branches in columns: the parent's line, along their tops, down each column, into each
        const line = (points) => {
            under.beginPath();
            points.forEach(([x, y], i) => (i ? under.lineTo(sx(x), sy(y)) : under.moveTo(sx(x), sy(y))));
            under.stroke();
        };
        const arrow = (x, y) => {
            under.beginPath();
            under.moveTo(sx(x), sy(y));
            under.lineTo(sx(x - 7), sy(y - 4));
            under.lineTo(sx(x - 7), sy(y + 4));
            under.closePath();
            under.fill();
        };
        under.strokeStyle = 'rgba(100, 116, 139, 0.75)';
        under.fillStyle = 'rgba(100, 116, 139, 0.75)';
        under.lineWidth = Math.max(1, 1.8 * zoom);
        for (const bus of decor.buses || []) {
            const end = bus.columns[bus.columns.length - 1];
            const bottom = Math.max(...bus.columns.map((c) => c.ticks[c.ticks.length - 1]?.y ?? bus.y));
            if (!end || !seen({ x1: bus.columns[0].x - 400, x2: end.x + 400, y1: bus.y - 400, y2: bottom })) continue;
            const from = this.cy.getElementById(bus.from);
            if (!from.length || from.is('.is-hidden, .filtered, .unfocused') || !bus.columns.length) continue;
            const p = from.position();
            const first = bus.columns[0];
            const last = bus.columns[bus.columns.length - 1];
            line([
                [p.x + from.width() / 2, p.y],
                [first.x, p.y],
                [first.x, bus.y],
            ]);
            line([
                [first.x, bus.y],
                [last.x, bus.y],
            ]);
            for (const col of bus.columns) {
                if (!col.ticks.length) continue;
                line([
                    [col.x, bus.y],
                    [col.x, col.ticks[col.ticks.length - 1].y],
                ]);
                for (const t of col.ticks) {
                    // to the node's edge (a circle is narrower than its label)
                    const n = t.node ? this.cy.getElementById(t.node) : null;
                    const end = n?.length ? n.position('x') - n.width() / 2 - 3 : t.x;
                    line([
                        [col.x, t.y],
                        [end, t.y],
                    ]);
                    arrow(end, t.y);
                }
            }
        }

        // lanes: their headings
        if (!far) {
            const size = 11 * zoom;
            if (size >= 6) {
                under.font = `600 ${size}px ${FONT}`;
                under.textBaseline = 'middle';
                for (const l of decor.lanes) {
                    if (!seen({ x1: l.x, x2: l.x + 300, y1: l.y - 10, y2: l.y + 10 })) continue;
                    const kind = CARD_KINDS[l.lane];
                    under.fillStyle = kind?.color || '#94a3b8';
                    under.globalAlpha = 0.9;
                    under.fillText(
                        `${(kind?.plural || LANE_NAMES[l.lane] || l.lane).toUpperCase()} · ${l.count}`,
                        sx(l.x),
                        sy(l.y)
                    );
                    under.globalAlpha = 1;
                }
            }
        }

        // far out: each tree summed up over it
        if (far && over) {
            for (const u of decor.units) if (seen(u)) this.drawSummary(over, u, { sx, sy, zoom });
            this.overDrawn = true;
        }
    },

    // "jdoe@mail.com and 2 more · 34 accounts · 6 breaches (2 passwords) · 12 identifiers"
    drawSummary(ctx, unit, { sx, sy, zoom }) {
        const kinds = new Map();
        let identifiers = 0;
        let passwords = 0;
        for (const id of unit.nodes) {
            const n = this.cy.getElementById(id);
            if (!n.length || n.is('.is-hidden, .filtered, .unfocused')) continue;
            const d = n.data();
            if (d.kind === 'card') {
                kinds.set(d.card, (kinds.get(d.card) || 0) + 1);
                if (d.card === 'breach' && d.flags?.includes('password')) passwords += 1;
            } else if (d.kind === 'group' && d.card) kinds.set(d.card, (kinds.get(d.card) || 0) + d.count);
            else if (d.kind === 'group') identifiers += d.count;
            else if (d.kind === 'identifier' && !unit.roots.includes(id)) identifiers += 1;
        }
        const name = (id) => {
            const d = this.cy.getElementById(id).data() || {};
            return String(d.display || d.value || d.title || (d.label || '').split('\n')[0] || id);
        };
        const title = unit.loose
            ? `${unit.loose} looked up, nothing found yet`
            : `${name(unit.roots[0])}${unit.roots.length > 1 ? ` and ${unit.roots.length - 1} more` : ''}`;
        const parts = [...kinds.entries()]
            .sort((a, b) => b[1] - a[1])
            .map(([kind, n]) => {
                const word = (CARD_KINDS[kind]?.plural || kind).toLowerCase();
                return `${n} ${n === 1 ? (CARD_KINDS[kind]?.label || kind).toLowerCase() : word}${kind === 'breach' && passwords ? ` (${passwords} with a password)` : ''}`;
            });
        if (identifiers && !unit.loose) parts.push(`${identifiers} identifier${identifiers === 1 ? '' : 's'}`);

        const x = sx(unit.x1);
        const y = sy(unit.y1);
        const w = (unit.x2 - unit.x1) * zoom;
        const h = (unit.y2 - unit.y1) * zoom;
        if (w < 40 || h < 16) return;
        ctx.beginPath();
        ctx.roundRect(x, y, w, h, 10);
        ctx.fillStyle = 'rgba(15, 16, 23, 0.78)';
        ctx.fill();
        ctx.strokeStyle = 'rgba(167, 139, 250, 0.35)';
        ctx.lineWidth = 1;
        ctx.stroke();
        ctx.save();
        ctx.beginPath();
        ctx.rect(x + 8, y, w - 16, h);
        ctx.clip();
        ctx.textBaseline = 'top';
        ctx.fillStyle = '#ffffff';
        ctx.font = `600 13px ${FONT}`;
        ctx.fillText(title, x + 10, y + 8);
        ctx.font = `11px ${FONT}`;
        ctx.fillStyle = '#c4b5fd';
        // as many lines as the box has room for
        let line = '';
        let at = y + 28;
        for (const part of parts) {
            const next = line ? `${line} · ${part}` : part;
            if (ctx.measureText(next).width > w - 20 && line) {
                if (at + 14 > y + h) break;
                ctx.fillText(line, x + 10, at);
                at += 15;
                line = part;
            } else line = next;
        }
        if (line && at + 12 <= y + h) ctx.fillText(line, x + 10, at);
        ctx.restore();
    },
};
