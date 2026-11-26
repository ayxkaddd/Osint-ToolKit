// The saved view (graph.json on the server) and undo / redo.
// Every change is sent whole a moment after the last one (PUT .../graph/state).

const SAVE_DELAY = 800;
const HISTORY_MAX = 200;

// The layout positions are made for (view.js); a view saved for an older one starts afresh
export const LAYOUT_VERSION = 4;

const emptyState = () => ({
    version: LAYOUT_VERSION,
    positions: {},
    expanded: [],
    collapsed: [],
    hidden: [],
    removed: [],
    manual_nodes: [],
    manual_edges: [],
    viewport: null,
    filters: null,
    layout: 'tree',
});

export class SavedView {
    constructor(investigationId) {
        this.url = `/api/investigations/${encodeURIComponent(investigationId)}/graph/state`;
        this.data = emptyState();
        this.timer = null;
        this.quiet = 0; // > 0 while the saved view is being put back: nothing to save
        this.failed = false;
        // leaving the page doesn't lose the last change
        const leave = () => this.timer && this.flush({ keepalive: true });
        window.addEventListener('pagehide', leave);
        document.addEventListener('visibilitychange', () => document.visibilityState === 'hidden' && leave());
    }

    load(saved) {
        const data = { ...emptyState(), ...(saved || {}) };
        delete data.updated_at;
        // positions from an older layout mean nothing in this one (what is open, hidden,
        // added and linked stays)
        if ((saved || {}).version !== LAYOUT_VERSION) {
            this.outdated = Object.keys(data.positions).length > 0;
            data.positions = {};
            data.pinned = [];
            // and where the view was: the graph fits the screen again
            delete data.viewport;
            data.version = LAYOUT_VERSION;
        }
        this.data = data;
    }

    // change((state) => ...) then save
    change(edit) {
        edit(this.data);
        if (this.quiet) return;
        clearTimeout(this.timer);
        this.timer = setTimeout(() => this.flush(), SAVE_DELAY);
    }

    async whileRestoring(work) {
        this.quiet++;
        try {
            return await work();
        } finally {
            this.quiet--;
        }
    }

    async flush({ keepalive = false } = {}) {
        clearTimeout(this.timer);
        this.timer = null;
        try {
            const response = await fetch(this.url, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(this.data),
                keepalive,
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            this.failed = false;
        } catch (error) {
            // one message, not one per change
            if (!this.failed)
                window.showTemporaryNotification?.(`The graph view was not saved (${error.message})`, 'error');
            this.failed = true;
        }
    }

    has(list, id) {
        return this.data[list].includes(id);
    }

    add(list, id) {
        this.change((s) => {
            if (!s[list].includes(id)) s[list].push(id);
        });
    }

    drop(list, id) {
        this.change((s) => {
            s[list] = s[list].filter((x) => x !== id);
        });
    }
}

// Undo / redo of what the analyst did in this session: each entry knows how to undo
// and redo itself (by node ids, so it still works after nodes were redrawn)
export class History {
    constructor(onChange) {
        this.done = [];
        this.undone = [];
        this.busy = false;
        this.onChange = onChange;
    }

    push(entry) {
        this.done.push(entry);
        if (this.done.length > HISTORY_MAX) this.done.shift();
        this.undone = [];
        this.onChange();
    }

    async undo() {
        return this.step(this.done, this.undone, 'undo');
    }

    async redo() {
        return this.step(this.undone, this.done, 'redo');
    }

    async step(from, to, how) {
        if (this.busy || !from.length) return null;
        const entry = from.pop();
        this.busy = true;
        try {
            await entry[how]();
        } finally {
            this.busy = false;
        }
        to.push(entry);
        this.onChange();
        return entry;
    }
}
