// Tree layout: left to right, like osintframework.com. What was looked up on the left,
// the cards found for it (accounts, breaches...) one column right, what each card holds
// beyond it, one row per node. d3-hierarchy walks the tree; Cytoscape only moves nodes.
//
// The graph isn't a tree (an identifier can be in two records), so each node hangs under
// its home (the server's ``home``), or else the first node that reaches it from the roots;
// its other links are "cross" links, drawn as curves. Links the analyst drew only place
// their own nodes.

import { OFF } from './style.js';

// One grid for the layout, the background and snapping (snap.js): rows two cells
// apart, columns nine, so every node of the tree sits on grid lines
export const GRID = 32;
const COLUMN = GRID * 9;
const ROW = GRID * 2;
const PILLS = new Set(['lookup', 'pending', 'card']);

// The order of a node's children (and of the trees), the same however and whenever
// they were drawn, so a reload or a new branch never reorders rows: the server's order
// (``rank``: the records that say most first, then what they hold), then groups, "+N
// more", what the analyst added, and lookups still running last
const KIND_RANK = { identifier: 0, card: 0, fact: 0, lookup: 0, manual: 1, group: 2, more: 3, pending: 5 };
const sortKey = (node) => {
    const d = node.data();
    const when =
        d.kind === 'lookup'
            ? (d.runs?.[d.runs.length - 1]?.timestamp ?? d.timestamp ?? '')
            : d.kind === 'pending'
              ? '9999'
              : (d.first_seen ?? '');
    const rank = d.rank ?? (KIND_RANK[d.kind] ?? 9) * 1_000_000;
    return [rank, String(when), String(d.value ?? d.key ?? d.offset ?? node.id())];
};
const byOrder = (a, b) => {
    const x = sortKey(a);
    const y = sortKey(b);
    if (x[0] !== y[0]) return x[0] - y[0];
    if (x[1] !== y[1]) return x[1] < y[1] ? -1 : 1;
    return x[2] < y[2] ? -1 : x[2] > y[2] ? 1 : 0;
};

// A link the tree follows: found, searched, follow-ups; a drawn link only to a drawn node
const treeEdge = (edge) => edge.data('kind') !== 'manual' || edge.target().data('kind') === 'manual';

// Which node each of ``nodes`` hangs under, taking only links between them. An identifier
// found by several lookups hangs under its home (the lookup that found it first, or a
// group of it) whenever that is drawn, so lookups run later don't move it.
export function spanningTree(nodes) {
    const inside = new Set(nodes.map((n) => n.id()));
    const parentOf = new Map();
    const childrenOf = new Map();
    const seen = new Set();
    const waiting = new Map(); // child id -> the first node that reached it, if its home never does

    // the node a group (or a group's "+N more") stands in for
    const ownerOf = (node) => {
        const d = node.data();
        if (d.kind === 'group') return d.owner;
        if (d.kind === 'more') {
            const of = node.cy().getElementById(d.of);
            return of.data('kind') === 'group' ? of.data('owner') : d.of;
        }
        return node.id();
    };
    const isHome = (parent, child) => !child.data('home') || ownerOf(parent) === child.data('home');
    const homeDrawn = (child) =>
        !!child.data('home') &&
        child
            .incomers('edge')
            .filter(treeEdge)
            .sources()
            .some((src) => inside.has(src.id()) && isHome(src, child));
    const attach = (child, parent) => {
        seen.add(child.id());
        waiting.delete(child.id());
        parentOf.set(child.id(), parent.id());
        if (!childrenOf.has(parent.id())) childrenOf.set(parent.id(), []);
        childrenOf.get(parent.id()).push(child.id());
    };

    const walk = (starts) => {
        let frontier = starts.filter((n) => !seen.has(n.id()));
        frontier.forEach((n) => seen.add(n.id()));
        while (frontier.length) {
            const next = [];
            for (const node of frontier) {
                node.outgoers('edge')
                    .filter(treeEdge)
                    .targets()
                    .filter((child) => inside.has(child.id()) && !seen.has(child.id()))
                    .sort(byOrder)
                    .forEach((child) => {
                        if (!isHome(node, child) && homeDrawn(child)) {
                            if (!waiting.has(child.id())) waiting.set(child.id(), node);
                            return;
                        }
                        attach(child, node);
                        next.push(child);
                    });
            }
            frontier = next;
        }
        // a home that is never reached (a loop of lookups): the first node that reached it
        for (const [id, parent] of [...waiting]) {
            if (seen.has(id)) continue;
            const child = parent.cy().getElementById(id);
            attach(child, parent);
            walk([child]);
        }
    };

    const hasParent = (n) =>
        n
            .incomers('edge')
            .filter(treeEdge)
            .sources()
            .some((src) => inside.has(src.id()));
    const roots = nodes.filter((n) => n.data('root') || !hasParent(n)).sort(byOrder);
    walk(roots.toArray());
    const topLevel = roots.toArray().filter((n) => !parentOf.has(n.id()));
    // whatever is left (loops with no way in) starts its own tree
    for (const node of nodes.sort(byOrder).toArray()) {
        if (!seen.has(node.id())) {
            topLevel.push(node);
            walk([node]);
        }
    }
    return { parentOf, childrenOf, topLevel };
}

// ---------------------------------------------------------------------------
// The tree, laid out to fill the screen, not one tall column:
// - a node's children go in the column to its right, the first level with it; many
//   children with nothing under them (accounts, breach records) fill a grid, row by row,
//   so a new one takes the next free cell and nothing else moves;
// - the children are in lanes by kind (accounts, breaches, identifiers...), each with a
//   heading when there are several;
// - separate trees that something links (a password, an identifier in both) are one
//   cluster, framed and labelled with what links them;
// - the trees and clusters are packed side by side into columns, as wide as the graph is
//   tall, each into the shortest column so far.
// Headings, frames, the grids' links and the summaries shown zoomed out are drawn under
// the graph (lanes.js) from ``decor``.
// ---------------------------------------------------------------------------
const CELL = GRID * 8; // a grid cell's width (a card is 236)
const GRID_MIN = 5; // this many children with nothing under them, in a row: a grid
const GRID_COLS = 4;
const HEAD = GRID; // a lane's or a cluster's heading
const GAP = GRID * 2; // between trees, and between the packed columns
const BUS = GRID; // above branches in columns: the line joining them
const WRAP = ROW * 14; // branches taller than this together go in columns

const moveBus = (bus, at) => ({
    ...bus,
    y: bus.y + at.y,
    columns: bus.columns.map((c) => ({
        x: c.x + at.x,
        ticks: c.ticks.map((t) => ({ ...t, x: t.x + at.x, y: t.y + at.y })),
    })),
});

// The lane a child goes in, in this order
const LANES = ['account', 'person', 'breach', 'registration', 'network', 'place', 'document', 'record', 'mention'];
const laneOf = (node) => {
    const d = node.data();
    if (d.kind === 'card') return d.card;
    if (d.kind === 'group') return d.card || 'identifiers';
    if (d.kind === 'more') return laneOf(node.cy().getElementById(d.of));
    if (d.kind === 'fact') return 'facts';
    if (d.kind === 'lookup' || d.kind === 'pending') return 'lookups';
    return 'identifiers';
};
const laneRank = (lane) => {
    const i = LANES.indexOf(lane);
    return i >= 0 ? i : ({ identifiers: 20, facts: 21, lookups: 22 }[lane] ?? 30);
};

// How wide a node is, with its label (a circle's label is wider than the circle)
const widthOf = (node) => (PILLS.has(node.data('kind')) ? node.data('w') : CELL - GRID);

// Positions for the nodes on screen; ``parentOf`` is over every node, shown or hidden
// (what folds or hides with a node); ``decor``: lanes, grids and clusters (lanes.js)
export function treeLayout(cy) {
    // not ':visible': Cytoscape counts a clear node as not visible, and new nodes start clear
    const visible = cy.nodes().not(OFF);
    const { parentOf, childrenOf, topLevel } = spanningTree(visible);
    const node = (id) => cy.getElementById(id);
    const inGrid = new Set();

    // A subtree, relative to its root at (0, 0): where each node goes, how far it reaches
    // up and down (a node's centre to the block's edges) and right, and its decor
    const block = (id) => {
        const self = node(id);
        const pos = new Map([[id, { x: 0, y: 0 }]]);
        const decor = { lanes: [], grids: [], buses: [] };
        const kids = (childrenOf.get(id) || []).map(node);
        let up = ROW / 2;
        let down = ROW / 2;
        let right = widthOf(self) / 2;
        if (!kids.length) return { pos, up, down, right, decor };

        const x0 = Math.max(COLUMN, widthOf(self) / 2 + CELL / 2 + GRID);
        const lanes = new Map();
        kids.forEach((k) => {
            const lane = laneOf(k);
            if (!lanes.has(lane)) lanes.set(lane, []);
            lanes.get(lane).push(k);
        });
        const ordered = [...lanes.entries()].sort((a, b) => laneRank(a[0]) - laneRank(b[0]));
        const headed = ordered.length > 1 && kids.length > GRID_MIN;
        let cursor = null; // the bottom of what is placed so far (null: nothing yet)
        const put = (sub, at) => sub.pos.forEach((p, k) => pos.set(k, { x: p.x + at.x, y: p.y + at.y }));
        const shift = (d, at) => {
            d.lanes.forEach((l) => decor.lanes.push({ ...l, x: l.x + at.x, y: l.y + at.y }));
            d.grids.forEach((g) =>
                decor.grids.push({ ...g, x1: g.x1 + at.x, x2: g.x2 + at.x, y1: g.y1 + at.y, y2: g.y2 + at.y })
            );
            d.buses.forEach((b) => decor.buses.push(moveBus(b, at)));
        };
        for (const [lane, members] of ordered) {
            if (headed) {
                // the heading over the lane; the first lane's is above the parent's row
                const top = cursor === null ? -ROW / 2 - HEAD : cursor;
                decor.lanes.push({ x: x0 - CELL / 2 + 4, y: top + HEAD / 2 + 4, lane, count: members.length });
                if (cursor === null) up = Math.max(up, ROW / 2 + HEAD);
                cursor = top + HEAD;
            }
            // runs of children with nothing under them make grids; the others, their subtrees
            const items = [];
            let i = 0;
            while (i < members.length) {
                let j = i;
                while (j < members.length && !(childrenOf.get(members[j].id()) || []).length) j++;
                if (j - i >= GRID_MIN) {
                    const run = members.slice(i, j);
                    const cols = Math.min(GRID_COLS, Math.ceil(run.length / 3));
                    const rows = Math.ceil(run.length / cols);
                    items.push({ run, cols, up: ROW / 2, down: (rows - 1) * ROW + ROW / 2, w: cols * CELL });
                    i = j;
                } else {
                    const sub = block(members[i].id());
                    const w = sub.right + CELL / 2;
                    items.push({ node: members[i], sub, up: sub.up, down: sub.down, w });
                    i += 1;
                }
            }
            // an item with its root (or a grid's first row) at (x, y)
            const place = (item, x, y, bused) => {
                if (item.run) {
                    item.run.forEach((k, n) => {
                        pos.set(k.id(), { x: x + (n % item.cols) * CELL, y: y + Math.floor(n / item.cols) * ROW });
                        inGrid.add(k.id());
                    });
                    decor.grids.push({
                        from: bused ? null : id,
                        x1: x - CELL / 2 + 6,
                        x2: x + (item.cols - 1) * CELL + CELL / 2 - 6,
                        y1: y - ROW / 2 + 4,
                        y2: y + item.down - 4,
                    });
                } else {
                    put(item.sub, { x, y });
                    shift(item.sub.decor, { x, y });
                    if (bused) inGrid.add(item.node.id());
                }
                right = Math.max(right, x + item.w - CELL / 2);
            };
            const tall = items.reduce((sum, it) => sum + it.up + it.down, 0);
            if (items.length >= 3 && tall > WRAP) {
                // many branches: in columns side by side, joined by a bus (lanes.js), each
                // column filled in order up to a height that makes the lane about 16:10
                const top = cursor === null ? -ROW / 2 : cursor;
                const area = items.reduce((sum, it) => sum + (it.w + GAP) * (it.up + it.down), 0);
                const target = Math.max(...items.map((it) => it.up + it.down), Math.sqrt(area / 1.6));
                const columns = [];
                items.forEach((it) => {
                    let col = columns[columns.length - 1];
                    if (!col || (col.h && col.h + it.up + it.down > target)) {
                        col = { h: 0, w: 0, items: [] };
                        columns.push(col);
                    }
                    col.items.push(it);
                    col.h += it.up + it.down;
                    col.w = Math.max(col.w, it.w);
                });
                const bus = { from: id, y: top + BUS / 2, columns: [] };
                let cx = x0;
                columns.forEach((col) => {
                    let at = top + BUS;
                    const ticks = [];
                    col.items.forEach((it) => {
                        const y = at + it.up;
                        place(it, cx, y, true);
                        ticks.push({
                            y,
                            x: it.run ? cx - CELL / 2 + 6 : cx - widthOf(it.node) / 2,
                            node: it.node?.id(),
                        });
                        at = y + it.down;
                    });
                    bus.columns.push({ x: cx - CELL / 2 - 10, ticks });
                    cx += col.w + GAP;
                });
                decor.buses.push(bus);
                cursor = top + BUS + Math.max(...columns.map((c) => c.h));
            } else {
                for (const it of items) {
                    // the first child is level with its parent; what is above it is above the parent too
                    if (cursor === null) up = Math.max(up, it.up);
                    const y = cursor === null ? 0 : cursor + it.up;
                    place(it, x0, y, false);
                    cursor = y + it.down;
                }
            }
        }
        down = Math.max(down, cursor);
        return { pos, up, down, right, decor };
    };

    // -- separate trees: clusters of the ones something links, then packed in columns --
    const treeOf = new Map();
    const blocks = topLevel.map((root, t) => {
        const b = block(root.id());
        b.pos.forEach((_, id) => treeOf.set(id, t));
        return { ...b, root, t };
    });
    const unionOf = blocks.map((_, t) => t);
    const find = (t) => (unionOf[t] === t ? t : (unionOf[t] = find(unionOf[t])));
    const links = new Map(); // cluster -> what links its trees
    const linkers = []; // [tree, the node that links it to another tree]
    cy.edges()
        .not(OFF)
        .forEach((e) => {
            const a = treeOf.get(e.source().id());
            const b = treeOf.get(e.target().id());
            if (a === undefined || b === undefined || a === b) return;
            unionOf[find(a)] = find(b);
            const linker = [e.target(), e.source()].find((n) => ['fact', 'identifier'].includes(n.data('kind')));
            if (linker) linkers.push([a, linker]);
        });
    linkers.forEach(([a, n]) => {
        {
            const root = find(a);
            if (!links.has(root)) links.set(root, new Map());
            const label =
                n.data('kind') === 'fact'
                    ? `${n.data('name')} ${n.data('label')}`
                    : String(n.data('display') || n.data('value'));
            links.get(root).set(n.id(), label.length > 30 ? `${label.slice(0, 29)}…` : label);
        }
    });
    // units: a cluster's trees one under another, or a tree on its own; in the trees' order
    const units = [];
    const unitOf = new Map();
    blocks.forEach((b) => {
        const root = find(b.t);
        if (!unitOf.has(root)) {
            unitOf.set(root, { trees: [], cluster: false, root });
            units.push(unitOf.get(root));
        }
        unitOf.get(root).trees.push(b);
    });
    // what was looked up and found nothing (yet): one grid, after the rest
    const lone = units.filter((u) => u.trees.length === 1 && u.trees[0].pos.size === 1);
    const loose = lone.length >= GRID_MIN ? { trees: lone.map((u) => u.trees[0]), loose: true } : null;
    if (loose) units.splice(0, units.length, ...units.filter((u) => !lone.includes(u)));
    units.forEach((u) => {
        u.ox = widthOf(u.trees[0].root) / 2;
        u.cluster = u.trees.length > 1;
        // a cluster's trees side by side too, in columns filled in order (about 16:10)
        const size = (b) => ({ w: widthOf(b.root) / 2 + b.right + GAP, h: b.up + b.down + GAP });
        const area = u.trees.reduce((sum, b) => sum + size(b).w * size(b).h, 0);
        const target = Math.max(...u.trees.map((b) => size(b).h), Math.sqrt(area / 1.6));
        const top = u.cluster ? HEAD : 0;
        let colX = 0;
        let colW = 0;
        let y = 0;
        let h = 0;
        u.trees.forEach((b) => {
            const { w, h: th } = size(b);
            if (y && y + th > target) {
                colX += colW;
                colW = 0;
                y = 0;
            }
            b.at = { x: colX + widthOf(b.root) / 2 - u.ox, y: top + y + b.up };
            y += th;
            colW = Math.max(colW, w);
            h = Math.max(h, y);
        });
        u.w = colX + colW;
        u.h = top + h - GAP;
    });
    if (loose) {
        const cols = Math.min(GRID_COLS, Math.ceil(loose.trees.length / 4));
        loose.trees.forEach((b, i) => {
            b.at = { x: (i % cols) * CELL, y: HEAD + Math.floor(i / cols) * ROW + ROW / 2 };
        });
        Object.assign(loose, {
            ox: CELL / 2,
            w: cols * CELL + GAP,
            h: HEAD + Math.ceil(loose.trees.length / cols) * ROW,
            cols,
        });
        units.push(loose);
    }

    // columns, filled in order up to a height that makes the whole about 16:10 (a tree
    // taller than that has a column of its own); the columns as wide as their widest tree
    const area = units.reduce((sum, u) => sum + u.w * (u.h + GAP), 0);
    const target = Math.max(...units.map((u) => u.h), Math.sqrt(area / 1.6));
    const cols = [];
    units.forEach((u) => {
        let col = cols[cols.length - 1];
        if (!col || (col.h && col.h + u.h > target)) {
            col = { h: 0, w: 0, units: [] };
            cols.push(col);
        }
        u.col = col;
        u.y = col.h;
        col.h += u.h + GAP;
        col.w = Math.max(col.w, u.w);
        col.units.push(u);
    });
    let x = 0;
    cols.forEach((c) => {
        c.x = x;
        x += c.w + GAP;
    });

    const positions = new Map();
    const decor = { lanes: [], grids: [], buses: [], clusters: [], units: [] };
    units.forEach((u) => {
        const ux = u.col.x + u.ox;
        u.trees.forEach((b) => {
            const at = { x: ux + b.at.x, y: u.y + b.at.y };
            b.pos.forEach((p, id) => positions.set(id, { x: p.x + at.x, y: p.y + at.y }));
            b.decor.lanes.forEach((l) => decor.lanes.push({ ...l, x: l.x + at.x, y: l.y + at.y }));
            b.decor.grids.forEach((g) =>
                decor.grids.push({ ...g, x1: g.x1 + at.x, x2: g.x2 + at.x, y1: g.y1 + at.y, y2: g.y2 + at.y })
            );
            b.decor.buses.forEach((bus) => decor.buses.push(moveBus(bus, at)));
        });
        const box = {
            x1: u.col.x - GRID / 2,
            x2: u.col.x + u.w - GAP + GRID / 2,
            y1: u.y - GRID / 2,
            y2: u.y + u.h + GRID / 2,
        };
        if (u.cluster) decor.clusters.push({ ...box, links: [...(links.get(u.root)?.values() || [])].slice(0, 3) });
        if (u.loose) {
            decor.lanes.push({
                x: box.x1 + GRID / 2 + 4,
                y: box.y1 + HEAD / 2 + 8,
                lane: 'nothing',
                count: u.trees.length,
            });
            decor.grids.push({ ...box, y1: box.y1 + HEAD });
        }
        // far out, a tree's summary takes its column's width (a short tree's name still fits)
        decor.units.push({
            ...box,
            x2: Math.max(box.x2, u.col.x + u.col.w - GAP + GRID / 2),
            loose: u.loose ? u.trees.length : 0,
            roots: u.trees.map((b) => b.root.id()),
            nodes: u.trees.flatMap((b) => [...b.pos.keys()]),
        });
    });

    cy.batch(() => {
        cy.edges().forEach((edge) => {
            const tree = parentOf.get(edge.target().id()) === edge.source().id();
            edge.toggleClass('cross', !tree);
            // a grid's links are drawn as one, to its frame (lanes.js)
            edge.toggleClass('in-grid', tree && inGrid.has(edge.target().id()));
        });
    });
    const all = visible.length === cy.nodes().length ? parentOf : spanningTree(cy.nodes()).parentOf;
    return { positions, parentOf: all, decor };
}

// ---------------------------------------------------------------------------
// New nodes, placed without moving anything already on screen. In the tree, the
// children of a node go in the column to its right, as one block starting level with
// it (or where ``hints`` says: a finished lookup where its pending node was), moved up
// or down to the nearest place where they overlap nothing. In the web, around it.
// ---------------------------------------------------------------------------
export function box(node, at) {
    const half = PILLS.has(node.data('kind')) ? node.data('w') / 2 + 10 : 100;
    return { x1: at.x - half, x2: at.x + half, y1: at.y - ROW / 2 + 4, y2: at.y + ROW / 2 - 4 };
}

export const overlaps = (a, b) => a.x1 < b.x2 && b.x1 < a.x2 && a.y1 < b.y2 && b.y1 < a.y2;

// fresh: nodes needing a place, in the order they came; parentOf: the tree over every node;
// settled: Map id -> {node, at} of the nodes that keep (or go back to) their place.
// Returns a Map id -> {x, y} for the fresh ones.
export function placeNew(fresh, parentOf, settled, { web = false, hints = new Map() } = {}) {
    const at = new Map();
    const taken = [...settled.values()].map((s) => box(s.node, s.at));
    const where = (node) => at.get(node.id()) || settled.get(node.id())?.at || null;
    const freshIds = new Set(fresh.map((n) => n.id()));
    // parents first: a fresh child of a fresh node waits until its parent has a place
    const byParent = new Map();
    fresh.sort(byOrder).forEach((node) => {
        const parent = parentOf.get(node.id()) || null;
        if (!byParent.has(parent)) byParent.set(parent, []);
        byParent.get(parent).push(node);
    });
    const cy = fresh.length ? fresh[0].cy() : null;
    const bottomLeft = () => {
        const all = [...taken];
        if (!all.length) return { x: 0, y: 0 };
        return { x: Math.min(...all.map((b) => b.x1)) + 100, y: Math.max(...all.map((b) => b.y2)) + ROW * 1.5 };
    };
    const fits = (nodes, x, y0) =>
        nodes.every((node, i) => {
            const b = box(node, { x, y: y0 + i * ROW });
            return !taken.some((t) => overlaps(t, b));
        });

    let pending = [...byParent.keys()];
    for (let round = 0; pending.length && round < 50; round++) {
        const later = [];
        for (const parentId of pending) {
            const kids = byParent.get(parentId);
            const parent = parentId ? cy.getElementById(parentId) : null;
            const origin = parent && where(parent);
            if (parent && !origin && freshIds.has(parentId)) {
                later.push(parentId);
                continue;
            }
            if (!origin) {
                // a new root: under everything, on the left
                const start = bottomLeft();
                kids.forEach((node, i) => {
                    const p = { x: start.x, y: start.y + i * ROW };
                    at.set(node.id(), p);
                    taken.push(box(node, p));
                });
                continue;
            }
            if (web) {
                kids.forEach((node, i) => {
                    let p = null;
                    for (let ring = 1; ring < 30 && !p; ring++)
                        for (let step = 0; step < ring * 6 && !p; step++) {
                            const angle = (2 * Math.PI * (step + i * 0.37)) / (ring * 6);
                            const q = {
                                x: origin.x + ring * 120 * Math.cos(angle),
                                y: origin.y + ring * 70 * Math.sin(angle),
                            };
                            const b = box(node, q);
                            if (!taken.some((t) => overlaps(t, b))) p = q;
                        }
                    p = p || { x: origin.x + 140, y: origin.y };
                    at.set(node.id(), p);
                    taken.push(box(node, p));
                });
                continue;
            }
            const x = origin.x + COLUMN;
            const hint = hints.get(parentId);
            const start = hint ? hint.y : origin.y - ((kids.length - 1) * ROW) / 2;
            let y0 = null;
            for (let step = 0; step < 600 && y0 === null; step++) {
                // 0, +½ row, -½ row, +1, -1, ...: the nearest free place
                const offset = Math.ceil(step / 2) * (ROW / 2) * (step % 2 ? 1 : -1);
                if (fits(kids, x, start + offset)) y0 = start + offset;
            }
            if (y0 === null) y0 = bottomLeft().y;
            kids.forEach((node, i) => {
                const p = { x, y: y0 + i * ROW };
                at.set(node.id(), p);
                taken.push(box(node, p));
            });
        }
        pending = later;
    }
    return at;
}
