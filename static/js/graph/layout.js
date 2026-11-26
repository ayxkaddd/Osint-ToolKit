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

// Positions for the nodes on screen; ``parentOf`` is over every node, shown or hidden
// (what folds or hides with a node)
export function treeLayout(cy) {
    // not ':visible': Cytoscape counts a clear node as not visible, and new nodes start clear
    const visible = cy.nodes().not(OFF);
    const { parentOf, childrenOf, topLevel } = spanningTree(visible);

    // Rows: every node has a row of its own and sits level with its first child, so
    // nothing can overlap, and what grows under a node only pushes the rows below it
    // down (a lookup's first finding, or a pivot's lookup, takes the row it starts from)
    const build = (id) => ({ id, children: (childrenOf.get(id) || []).map(build) });
    const root = window.d3.hierarchy({ id: null, children: topLevel.map((n) => build(n.id())) });
    let row = 0;
    const rowOf = new Map();
    root.eachBefore((d) => {
        if (d.data.id === null) return;
        // the first node of each tree after the first: a blank row between trees
        if (d.depth === 1 && row > 0) row += 1;
        // a node shares its row with its first child; a leaf takes the next one
        rowOf.set(d.data.id, d.parent?.children?.[0] === d && d.depth > 1 ? rowOf.get(d.parent.data.id) : row);
        if (!d.children) row = rowOf.get(d.data.id) + 1;
    });
    const positions = new Map();
    root.descendants().forEach((d) => {
        if (d.data.id !== null) positions.set(d.data.id, { x: (d.depth - 1) * COLUMN, y: rowOf.get(d.data.id) * ROW });
    });

    cy.batch(() => {
        cy.edges().forEach((edge) => {
            edge.toggleClass('cross', parentOf.get(edge.target().id()) !== edge.source().id());
        });
    });
    const all = visible.length === cy.nodes().length ? parentOf : spanningTree(cy.nodes()).parentOf;
    return { positions, parentOf: all };
}

// ---------------------------------------------------------------------------
// New nodes, placed without moving anything already on screen. In the tree, the
// children of a node go in the column to its right, as one block starting level with
// it (or where ``hints`` says: a finished lookup where its pending node was), moved up
// or down to the nearest place where they overlap nothing. In the web, around it.
// ---------------------------------------------------------------------------
const PILLS = new Set(['lookup', 'pending', 'card']);

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
