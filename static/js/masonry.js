// Packed "masonry" columns, laid out in JS. CSS columns re-flow every card
// whenever one is added or grows (streamed results, late-loading images), so
// cards jumped between columns while scrolling. Here each card is placed once,
// in the currently shortest column, and keeps it; only a breakpoint change
// (window resize) re-flows, preserving the original card order. The column
// count follows the container's width, so cards also fit narrow places
// (result snapshots in the notes sidebar).
const masonryState = new WeakMap();
let masonryOrder = 0;

function masonryColumnCount(container) {
    const width = container && container.clientWidth;
    if (!width) return window.innerWidth >= 1100 ? 3 : window.innerWidth >= 640 ? 2 : 1;
    return width >= 900 ? 3 : width >= 520 ? 2 : 1;
}

function masonryLayout(container, cards = []) {
    const count = masonryColumnCount(container);
    container.innerHTML = '';
    const columns = Array.from({ length: count }, () => {
        const column = document.createElement('div');
        column.className = 'username-masonry-col';
        container.appendChild(column);
        return column;
    });
    const state = { count, columns };
    masonryState.set(container, state);
    cards.forEach(card => masonryAppend(container, card));
    return state;
}

function masonryAppend(container, card) {
    let state = masonryState.get(container);
    if (!state || state.columns[0].parentNode !== container) {
        state = masonryLayout(container);
    }
    if (!card.dataset.order) card.dataset.order = String(masonryOrder++);
    const heights = state.columns.map(column => column.offsetHeight);
    // Hidden containers report 0 height everywhere: fall back to card counts
    const measure = heights.some(h => h > 0) ? heights : state.columns.map(column => column.childElementCount);
    const target = measure.indexOf(Math.min(...measure));
    state.columns[target].appendChild(card);
}

function masonryReflowAll() {
    document.querySelectorAll('.username-masonry, .username-category-results').forEach(container => {
        const state = masonryState.get(container);
        if (!state || state.count === masonryColumnCount(container)) return;
        const cards = Array.from(container.querySelectorAll('.username-result-card'))
            .sort((a, b) => Number(a.dataset.order) - Number(b.dataset.order));
        masonryLayout(container, cards);
    });
}

let masonryResizeTimer = null;
window.addEventListener('resize', () => {
    clearTimeout(masonryResizeTimer);
    masonryResizeTimer = setTimeout(masonryReflowAll, 150);
});

// Lays out cards that were rendered as plain HTML into [data-masonry-pack] containers
function masonryPackAll(root = document) {
    root.querySelectorAll('[data-masonry-pack]').forEach(container => {
        masonryLayout(container, Array.from(container.querySelectorAll('.username-result-card')));
    });
}
