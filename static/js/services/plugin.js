// Plugin page (templates/plugin.html): runs /api/plugins/<id>/run (or /test) and
// shows the NDJSON events as cards (PluginResultsView, static/js/plugin_cards.js).
const plugin = window.pluginInfo;
window.currentService = plugin.id;

const els = {
    input: document.getElementById('pluginInput'),
    run: document.getElementById('pluginRun'),
    stop: document.getElementById('pluginStop'),
    test: document.getElementById('pluginTest'),
    types: document.querySelectorAll('#pluginType [data-type]'),
    result: document.getElementById('pluginResult'),
    statusIcon: document.getElementById('pluginStatusIcon'),
    statusText: document.getElementById('pluginStatusText'),
    error: document.getElementById('pluginError'),
    cards: document.getElementById('pluginCards'),
};

const state = { type: plugin.accepts[0] && plugin.accepts[0].type, controller: null, view: null };

const STATUS_ICONS = {
    running: '<i class="fas fa-spinner fa-spin text-purple-300"></i>',
    done: '<i class="fas fa-check text-emerald-400"></i>',
    stopped: '<i class="fas fa-stop text-amber-300"></i>',
    error: '<i class="fas fa-times text-red-400"></i>',
};

function setStatus(kind, text) {
    els.statusIcon.innerHTML = STATUS_ICONS[kind] || '';
    els.statusText.textContent = text;
}

function showError(message) {
    els.error.textContent = message;
    els.error.classList.remove('hidden');
}

function resetResult() {
    els.error.classList.add('hidden');
    els.result.classList.remove('hidden');
    state.view = new PluginResultsView(els.cards, plugin.id);
}

function setBusy(busy) {
    els.run.disabled = busy || !plugin.enabled;
    els.stop.classList.toggle('hidden', !busy);
}

function countText(count) {
    return `${count} result${count === 1 ? '' : 's'}`;
}

els.types.forEach((button) => button.addEventListener('click', () => {
    state.type = button.dataset.type;
    els.types.forEach((b) => b.classList.toggle('active', b === button));
}));

window.loadResultIntoView = function (result, record) {
    if (!isPluginResult(result)) return;
    resetResult();
    els.cards.innerHTML = renderPluginResult(result);
    masonryPackAll(els.cards);
    if (window.lucide) lucide.createIcons();
    const when = record && record.timestamp ? ` · ${new Date(record.timestamp).toLocaleString()}` : '';
    setStatus('done', `Saved result for ${result.value || '…'}: ${countText((result.items || []).length)}${when}`);
};

async function runLookup() {
    const value = els.input.value.trim();
    if (!value || !plugin.enabled) return;
    if (state.controller) state.controller.abort();
    resetResult();
    setBusy(true);
    const test = els.test.checked;
    const started = Date.now();
    let count = 0;
    let finished = false;
    setStatus('running', `Looking up ${value}…`);
    state.controller = new AbortController();

    const handle = (event) => {
        state.view.event(event);
        if (event.event === 'item') {
            count += 1;
            setStatus('running', `Looking up ${value}… ${countText(count)} so far`);
        } else if (event.event === 'error') {
            showError(event.detail);
        } else if (event.event === 'done') {
            finished = true;
        }
    };

    try {
        const response = await fetch(`/api/plugins/${encodeURIComponent(plugin.id)}/${test ? 'test' : 'run'}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ value, type: state.type }),
            signal: state.controller.signal,
        });
        if (!response.ok) {
            const data = await response.json().catch(() => ({}));
            const detail = Array.isArray(data.detail) ? data.detail.map(d => d.msg).join(', ') : data.detail;
            throw new Error(detail || `Request failed (${response.status})`);
        }
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        for (;;) {
            const { done, value: chunk } = await reader.read();
            if (done) break;
            buffer += decoder.decode(chunk, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop();
            for (const line of lines) {
                if (!line.trim()) continue;
                try {
                    handle(JSON.parse(line));
                } catch (e) {
                    console.error('Bad plugin event', e);
                }
            }
        }
    } catch (error) {
        if (error.name !== 'AbortError') {
            showError(error.message);
            state.view.stopped();
            setStatus('error', 'Lookup failed');
            setBusy(false);
            state.controller = null;
            return;
        }
    }
    state.controller = null;
    setBusy(false);
    const seconds = ((Date.now() - started) / 1000).toFixed(1);
    const saved = test ? ' · test, not saved' : '';
    if (finished) {
        setStatus('done', `${countText(count)} in ${seconds}s${saved}`);
    } else {
        state.view.stopped();
        setStatus('stopped', `Stopped after ${seconds}s · ${countText(count)}${saved}`);
    }
}

els.run.addEventListener('click', runLookup);
els.input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') runLookup();
});
els.stop.addEventListener('click', () => state.controller && state.controller.abort());
setBusy(false);
