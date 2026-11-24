// The graph on the investigation page (Graph tab) and on its full-screen page.
// Drawn the first time it is shown; the tab says when with a "graph:show" event.
import { GraphView } from './view.js';

const root = document.getElementById('graphRoot');
let view = null;

// On the investigation page the graph takes the height left under the tabs, so the
// whole of it is on screen (the page can't always scroll the tabs to the top)
function fitHeight() {
    if (!root || root.dataset.fullscreen === 'true' || root.closest('.hidden')) return;
    root.style.height = `${Math.max(420, window.innerHeight - root.getBoundingClientRect().top - 16)}px`;
}

function show() {
    if (!root) return;
    fitHeight();
    if (!view)
        view = new GraphView(root, window.pageData('investigationId'), {
            fullscreen: root.dataset.fullscreen === 'true',
        });
    else view.cy?.resize();
    root.graphView = view; // for the browser console and browser tests
}

document.addEventListener('graph:show', show);
window.addEventListener('resize', fitHeight);
// the case's header is drawn after the page loads and moves the graph down
const above = document.querySelector('.page');
if (root && above && root.dataset.fullscreen !== 'true') new ResizeObserver(fitHeight).observe(above);
if (root && (root.dataset.fullscreen === 'true' || !root.closest('.hidden'))) show();
