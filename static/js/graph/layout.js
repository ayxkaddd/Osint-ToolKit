// Tree layout: left to right, like osintframework.com. What was typed on the left,
// each lookup one column right, what it found beyond it. d3-hierarchy places the
// tree; Cytoscape only moves nodes to the positions.
//
// The graph isn't a tree (an identifier can be found by two lookups), so each node
// hangs under the first node that reaches it from the roots; its other links are
// "cross" links, drawn as curves. Links the analyst drew only place their own nodes.

import { OFF } from './style.js';

const COLUMN = 270;
const ROW = 66;

// order: the order nodes arrived in (server order is most relevant first)
const byOrder = (a, b) => (a.data('order') ?? 0) - (b.data('order') ?? 0);

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

    const lookupOf = (node) => {
        const d = node.data();
        if (d.kind === 'lookup') return node.id();
        if (d.kind === 'group') return d.lookup;
        if (d.kind === 'more') return node.cy().getElementById(d.of).data('lookup');
        return null;
    };
    const isHome = (parent, child) => !child.data('home') || lookupOf(parent) === child.data('home');
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

    const build = (id) => ({ id, children: (childrenOf.get(id) || []).map(build) });
    const root = window.d3.hierarchy({ id: null, children: topLevel.map((n) => build(n.id())) });
    window.d3
        .tree()
        .nodeSize([ROW, COLUMN])
        .separation((a, b) => (a.parent === b.parent ? 1 : 1.25))(root);

    const positions = new Map();
    root.descendants().forEach((d) => {
        if (d.data.id !== null) positions.set(d.data.id, { x: (d.depth - 1) * COLUMN, y: d.x });
    });

    cy.batch(() => {
        cy.edges().forEach((edge) => {
            edge.toggleClass('cross', parentOf.get(edge.target().id()) !== edge.source().id());
        });
    });
    const all = visible.length === cy.nodes().length ? parentOf : spanningTree(cy.nodes()).parentOf;
    return { positions, parentOf: all };
}
