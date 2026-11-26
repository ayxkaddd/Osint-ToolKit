// Snapping a node being moved, like on a whiteboard: it lines up with the nodes around
// it (purple guides show with which) or, away from them, with the grid. Ctrl pressed once
// the drag has started places it freely (Ctrl at the press starts a box selection instead,
// and Alt + drag moves the window on many Linux desktops); the magnet button turns
// snapping off. Methods of GraphView (view.js).
import { GRID } from './layout.js';
import { OFF } from './style.js';

const THRESHOLD = 8; // screen pixels
const PILLS = new Set(['lookup', 'pending', 'card']);
const STORE_KEY = 'graphSnap';

// The value in sorted ``values`` nearest to ``v``
function nearest(values, v) {
    let lo = 0;
    let hi = values.length - 1;
    if (hi < 0) return null;
    while (lo < hi) {
        const mid = (lo + hi) >> 1;
        if (values[mid] < v) lo = mid + 1;
        else hi = mid;
    }
    const after = values[lo];
    const before = lo > 0 ? values[lo - 1] : after;
    return Math.abs(before - v) <= Math.abs(after - v) ? before : after;
}

// Where a node goes when dropped at ``at``. ``anchors``: offsets from its centre that may
// line up (its centre, and a pill's two ends); ``lines``: {x: [...], y: [...]} sorted, the
// places other nodes offer. Within ``threshold`` of one it lines up (``guides`` says
// where), else it goes to the grid.
export function snapPoint(at, anchors, lines, { threshold, grid }) {
    const out = { x: at.x, y: at.y, guides: { x: null, y: null } };
    for (const axis of ['x', 'y']) {
        let best = null;
        for (const offset of anchors[axis]) {
            const target = nearest(lines[axis], at[axis] + offset);
            if (target === null) continue;
            const distance = Math.abs(target - (at[axis] + offset));
            if (distance <= threshold && (!best || distance < best.distance)) best = { target, offset, distance };
        }
        if (best) {
            out[axis] = best.target - best.offset;
            out.guides[axis] = best.target;
        } else if (grid) out[axis] = Math.round(at[axis] / grid) * grid;
    }
    return out;
}

const anchorsOf = (node) => {
    const half = PILLS.has(node.data('kind')) ? node.data('w') / 2 : 0;
    return { x: half ? [0, -half, half] : [0], y: [0] };
};

export const snapping = {
    snapEnabled() {
        if (this.snapOn === undefined) {
            try {
                this.snapOn = localStorage.getItem(STORE_KEY) !== 'off';
            } catch {
                this.snapOn = true;
            }
        }
        return this.snapOn;
    },

    toggleSnap() {
        this.snapOn = !this.snapEnabled();
        try {
            localStorage.setItem(STORE_KEY, this.snapOn ? 'on' : 'off');
        } catch {
            /* kept for this page only */
        }
        this.updateSnapButton();
        window.showTemporaryNotification?.(
            this.snapOn ? 'Snapping on' : 'Snapping off: nodes go where you drop them',
            'info'
        );
    },

    updateSnapButton() {
        const button = this.root.querySelector('[data-snap-button]');
        if (!button) return;
        const on = this.snapEnabled();
        button.classList.toggle('text-purple-300', on);
        button.title = on
            ? 'Snapping on: nodes line up with others and the grid (press Ctrl while dragging: freely)'
            : 'Snapping off';
        button.setAttribute('aria-label', button.title);
    },

    // A point on the grid (a node added by hand)
    snapToGrid(at) {
        if (!this.snapEnabled()) return at;
        return { x: Math.round(at.x / GRID) * GRID, y: Math.round(at.y / GRID) * GRID };
    },

    // Grab: the lines the nodes around offer, once for the whole drag
    snapStart(node) {
        if (!this.watchingCtrl) {
            this.watchingCtrl = true;
            const watch = (e) => (this.ctrlHeld = e.ctrlKey || e.metaKey);
            window.addEventListener('pointermove', watch, { capture: true, passive: true });
            window.addEventListener('pointerdown', watch, { capture: true, passive: true });
            window.addEventListener('keydown', watch, { capture: true });
            window.addEventListener('keyup', watch, { capture: true });
        }
        const moving = this.cy.$('node:selected').contains(node) ? this.cy.$('node:selected') : node;
        const extent = this.cy.extent();
        const marginX = extent.w / 2;
        const marginY = extent.h / 2;
        const xs = [];
        const ys = [];
        this.cy
            .nodes()
            .not(OFF)
            .not(moving)
            .forEach((n) => {
                const p = n.position();
                if (
                    p.x < extent.x1 - marginX ||
                    p.x > extent.x2 + marginX ||
                    p.y < extent.y1 - marginY ||
                    p.y > extent.y2 + marginY
                )
                    return;
                anchorsOf(n).x.forEach((offset) => xs.push(p.x + offset));
                ys.push(p.y);
            });
        xs.sort((a, b) => a - b);
        ys.sort((a, b) => a - b);
        // box selection is for drags that start on the canvas; while a node is moved it would
        // take over as soon as Ctrl is pressed
        this.cy.boxSelectionEnabled(false);
        // ``free``: where the node would be without snapping (it follows the pointer)
        this.snapDrag = {
            id: node.id(),
            moving,
            lines: { x: xs, y: ys },
            free: { ...node.position() },
            last: { ...node.position() },
        };
    },

    snapMove(node, event) {
        const drag = this.snapDrag;
        if (!drag || node.id() !== drag.id) return;
        const now = node.position();
        drag.free = { x: drag.free.x + now.x - drag.last.x, y: drag.free.y + now.y - drag.last.y };
        // Ctrl from the pointer itself: Cytoscape's drag event doesn't always say
        const free = !this.snapEnabled() || this.ctrlHeld || event?.originalEvent?.ctrlKey;
        const to = free
            ? { ...drag.free, guides: { x: null, y: null } }
            : snapPoint(drag.free, anchorsOf(node), drag.lines, { threshold: THRESHOLD / this.cy.zoom(), grid: GRID });
        const dx = to.x - now.x;
        const dy = to.y - now.y;
        if (dx || dy)
            this.cy.batch(() =>
                drag.moving.forEach((n) => {
                    n.position({ x: n.position('x') + dx, y: n.position('y') + dy });
                })
            );
        drag.last = { x: to.x, y: to.y };
        this.drawGuides(to.guides);
    },

    snapEnd() {
        this.snapDrag = null;
        this.cy.boxSelectionEnabled(true);
        this.drawGuides({ x: null, y: null });
    },

    // Purple lines across the screen through what the node lines up with
    drawGuides(guides) {
        const canvas = this.guides;
        if (!canvas) return;
        const ratio = window.devicePixelRatio || 1;
        const width = canvas.clientWidth;
        const height = canvas.clientHeight;
        if (canvas.width !== width * ratio || canvas.height !== height * ratio) {
            canvas.width = width * ratio;
            canvas.height = height * ratio;
        }
        const ctx = canvas.getContext('2d');
        ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
        ctx.clearRect(0, 0, width, height);
        if (guides.x === null && guides.y === null) return;
        const zoom = this.cy.zoom();
        const pan = this.cy.pan();
        ctx.strokeStyle = '#a855f7';
        ctx.lineWidth = 1;
        ctx.setLineDash([5, 4]);
        ctx.beginPath();
        if (guides.x !== null) {
            const x = Math.round(guides.x * zoom + pan.x) + 0.5;
            ctx.moveTo(x, 0);
            ctx.lineTo(x, height);
        }
        if (guides.y !== null) {
            const y = Math.round(guides.y * zoom + pan.y) + 0.5;
            ctx.moveTo(0, y);
            ctx.lineTo(width, y);
        }
        ctx.stroke();
    },
};
