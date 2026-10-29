// Plugin results (services/plugin_loader.py), on the plugin page (PluginResultsView,
// streamed) and in saved results (renderPluginResult). Cards use the username search
// card styles and the OSINT Industries card helpers (oi_cards.js).
// /api/plugins/client.js calls registerPlugins() with every plugin's name and icon,
// then runs the renderer.js of plugins allowed to run code.

const PLUGINS = {};
const PLUGIN_RENDERERS = {};

function registerPlugins(list) {
    for (const plugin of list || []) {
        PLUGINS[plugin.id] = plugin;
        MODULES[plugin.id] = { name: plugin.name, icon: plugin.icon || 'puzzle', page: plugin.page };
    }
}

// renderer.js: registerPluginRenderer(pluginId, (result) => html). Return null to
// fall back to the standard cards (pluginCardsHtml(result.items) builds them).
function registerPluginRenderer(id, render) {
    PLUGIN_RENDERERS[id] = render;
}

function isPluginResult(data) {
    return !!data && typeof data === 'object' && data.kind === 'plugin_result';
}

function pluginItemText(item) {
    return [item.title, item.subtitle, item.category, ...(item.fields || []).map(f => f[1])]
        .filter(v => v !== undefined && v !== null).join(' ').toLowerCase();
}

function pluginEntityChips(entities) {
    const chips = [];
    for (const [type, values] of Object.entries(entities || {})) {
        for (const value of values) chips.push([type, value]);
    }
    if (!chips.length || typeof pivotChip !== 'function') return '';
    return `<div class="flex flex-wrap gap-1.5 mt-3">${chips.slice(0, 8).map(([type, value]) => pivotChip(type, value)).join('')}
        ${chips.length > 8 ? `<span class="text-xs text-gray-500 self-center">+${chips.length - 8}</span>` : ''}</div>`;
}

function pluginCardHtml(item) {
    const picture = safeUrl(item.image);
    const rows = (item.fields || []).filter(([, value]) => value !== undefined && value !== null && value !== '');
    const { html, hidden } = oiRows(rows);
    const chips = pluginEntityChips(item.entities);
    return `
        <div class="result-card username-result-card fade-in${picture ? ' has-profile-image' : ''}" data-plugin-text="${escapeAttr(pluginItemText(item))}">
            ${oiHeader(item.title || '', item.subtitle || item.category || '', [item.icon || ''], picture, '!normal-case')}
            ${html || chips ? `<div class="username-card-content">${html}${chips}</div>` : ''}
            ${oiActions(item.url, 'Open', hidden)}
        </div>`;
}

function pluginCardsHtml(items) {
    if (!(items || []).length) return '';
    return `<div class="username-masonry" data-masonry-pack>${items.map(pluginCardHtml).join('')}</div>`;
}

function pluginRawHtml(raw) {
    if (raw === undefined || raw === null) return '';
    const text = JSON.stringify(raw, null, 2);
    return `
        <details class="mt-5 text-sm">
            <summary class="cursor-pointer text-gray-400 hover:text-gray-200 select-none">Raw response</summary>
            <pre class="mt-2 p-3 bg-gray-950/70 border border-gray-800 rounded-lg text-xs text-gray-300 overflow-auto max-h-96">${escapeHtml(text)}</pre>
        </details>`;
}

function pluginNoticeHtml(result) {
    const parts = [];
    if (result.error) {
        parts.push(`<p class="text-sm text-red-300 mb-4"><i class="fas fa-exclamation-triangle mr-2"></i>${escapeHtml(result.error)}</p>`);
    }
    if (!result.error && result.completed === false) {
        parts.push('<p class="text-sm text-amber-300/80 mb-4">Stopped before the end - these are partial results.</p>');
    }
    const empty = !(result.items || []).length && (result.data === undefined || result.data === null);
    if (empty && !result.error) {
        parts.push(`<p class="text-sm text-gray-400">${escapeHtml(result.note || 'Nothing found')}.</p>`);
    }
    return parts.join('');
}

function renderPluginResult(result) {
    const custom = PLUGIN_RENDERERS[result.plugin];
    if (custom) {
        try {
            const html = custom(result);
            if (html) return html;
        } catch (e) {
            console.error(`Plugin ${result.plugin}: renderer failed`, e);
        }
    }
    const items = result.items || [];
    return pluginNoticeHtml(result)
        + (items.length ? `<p class="text-xs text-gray-500 mb-3">${items.length} result${items.length === 1 ? '' : 's'}</p>` : '')
        + pluginCardsHtml(items)
        + (result.data !== undefined && result.data !== null ? `<div class="mt-4">${renderValue(result.data)}</div>` : '')
        + pluginRawHtml(result.raw);
}

// Live results: cards are added as the plugin finds them
class PluginResultsView {
    constructor(root, pluginId) {
        this.root = root;
        this.pluginId = pluginId;
        this.result = { kind: 'plugin_result', plugin: pluginId, items: [], completed: false };
        this.custom = !!PLUGIN_RENDERERS[pluginId];
        this.items = [];
        root.innerHTML = `
            <div data-plugin-notice></div>
            <div data-plugin-filter-box class="hidden mb-4 relative">
                <i data-lucide="search" class="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-gray-500 pointer-events-none"></i>
                <input type="search" data-plugin-filter placeholder="Filter results…" class="field field-sm w-full !pl-9">
            </div>
            <p data-plugin-count class="hidden text-xs text-gray-500 mb-3"></p>
            <div data-plugin-cards class="username-masonry"></div>
            <div data-plugin-data></div>
            <div data-plugin-raw></div>`;
        this.grid = root.querySelector('[data-plugin-cards]');
        this.filter = root.querySelector('[data-plugin-filter]');
        this.filter.addEventListener('input', () => this.applyFilter());
        if (window.lucide) lucide.createIcons();
    }

    event(event) {
        if (event.event === 'item') {
            this.result.items.push(event.item);
            if (this.custom) return this.renderAll();
            const template = document.createElement('template');
            template.innerHTML = pluginCardHtml(event.item).trim();
            const el = template.content.firstElementChild;
            this.items.push(el);
            if (this.matches(el)) masonryAppend(this.grid, el);
            this.updateCount();
        } else if (event.event === 'data') {
            this.result.data = this.result.data === undefined ? event.data : [].concat(this.result.data, [event.data]);
            if (this.custom) return this.renderAll();
            this.root.querySelector('[data-plugin-data]').innerHTML = `<div class="mt-4">${renderValue(this.result.data)}</div>`;
        } else if (event.event === 'error') {
            this.result.error = event.detail;
        } else if (event.event === 'done') {
            this.result.completed = !!event.completed;
            this.result.note = event.note;
            this.result.raw = event.raw;
            this.finish();
        }
    }

    // Client side stop / network failure
    stopped(message) {
        if (message) this.result.error = message;
        this.finish();
    }

    finish() {
        if (this.custom) return this.renderAll();
        this.root.querySelector('[data-plugin-notice]').innerHTML = pluginNoticeHtml(this.result);
        this.root.querySelector('[data-plugin-raw]').innerHTML = pluginRawHtml(this.result.raw);
        this.updateCount();
    }

    renderAll() {
        this.root.innerHTML = renderPluginResult(this.result);
        masonryPackAll(this.root);
        if (window.lucide) lucide.createIcons();
    }

    matches(el) {
        const text = this.filter.value.trim().toLowerCase();
        return !text || el.dataset.pluginText.includes(text);
    }

    applyFilter() {
        masonryLayout(this.grid, this.items.filter(el => this.matches(el)));
        this.updateCount();
    }

    updateCount() {
        const total = this.items.length;
        const shown = this.grid.querySelectorAll('.username-result-card').length;
        const count = this.root.querySelector('[data-plugin-count]');
        count.classList.toggle('hidden', !total);
        count.textContent = shown === total ? `${total} result${total === 1 ? '' : 's'}` : `${shown} of ${total} results`;
        this.root.querySelector('[data-plugin-filter-box]').classList.toggle('hidden', total < 6);
    }
}
