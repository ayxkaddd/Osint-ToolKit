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

// Identifiers the plugin found that no row shows (rows show theirs inline)
function pluginEntityChips(entities, shownValues = new Set()) {
    const chips = [];
    for (const [type, values] of Object.entries(entities || {})) {
        for (const value of values) if (!shownValues.has(String(value))) chips.push([type, value]);
    }
    if (!chips.length || typeof pivotChip !== 'function') return '';
    return `<div class="flex flex-wrap gap-1.5 mt-3">${chips.slice(0, 8).map(([type, value]) => pivotChip(type, value)).join('')}
        ${chips.length > 8 ? `<span class="text-xs text-gray-500 self-center">+${chips.length - 8}</span>` : ''}</div>`;
}

function pluginCardHtml(item) {
    const picture = safeUrl(item.image);
    const typeOf = new Map();
    for (const [type, values] of Object.entries(item.entities || {})) {
        for (const value of values) if (!typeOf.has(String(value))) typeOf.set(String(value), type);
    }
    const rows = (item.fields || []).filter(([, value]) => value !== undefined && value !== null && value !== '')
        .map(([label, value]) => [label, value, typeOf.get(String(value)) || null]);
    const { html, hidden } = oiRows(rows);
    const chips = pluginEntityChips(item.entities, new Set(rows.filter(r => r[2]).map(r => String(r[1]))));
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

// Plugins with several lookups (requests:) tag cards with the lookup's name
function pluginGroups(items) {
    const groups = new Map();
    for (const item of items || []) {
        const name = item.action || '';
        if (!groups.has(name)) groups.set(name, []);
        groups.get(name).push(item);
    }
    return [...groups.entries()];
}

function pluginGroupHead(name, count) {
    return `<h3 class="flex items-center gap-2 text-sm font-semibold text-white mt-6 first:mt-0 mb-3" data-plugin-group-head>${escapeHtml(name)}
        <span data-plugin-group-count class="text-xs font-normal text-purple-300 tabular-nums">${count}</span></h3>`;
}

function pluginLookupsHtml(lookups) {
    if (!(lookups || []).length) return '';
    const chip = (l) => {
        const [cls, text] = l.status === 'found' ? ['bg-emerald-500/10 text-emerald-300', `${l.count}`]
            : l.status === 'failed' ? ['bg-red-500/10 text-red-300', 'failed'] : ['bg-gray-800 text-gray-400', 'nothing found'];
        return `<span class="px-2 py-0.5 rounded-md text-xs ${cls}">${escapeHtml(l.name)} · ${escapeHtml(text)}</span>`;
    };
    return `<div class="flex flex-wrap gap-1.5 mb-4">${lookups.map(chip).join('')}</div>`;
}

function pluginNoticeHtml(result) {
    const parts = [];
    if (result.error) {
        parts.push(`<p class="text-sm text-red-300 mb-4"><i class="fas fa-exclamation-triangle mr-2"></i>${escapeHtml(result.error)}</p>`);
    }
    for (const warning of result.warnings || []) {
        parts.push(`<p class="text-sm text-amber-300/90 mb-2"><i class="fas fa-exclamation-triangle mr-2"></i>${escapeHtml(warning)}</p>`);
    }
    parts.push(pluginLookupsHtml(result.lookups));
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
    const groups = pluginGroups(items);
    const cards = groups.length > 1 || (groups[0] && groups[0][0])
        ? groups.map(([name, group]) => pluginGroupHead(name, group.length) + pluginCardsHtml(group)).join('')
        : pluginCardsHtml(items);
    return pluginNoticeHtml(result)
        + (items.length ? `<p class="text-xs text-gray-500 mb-3">${items.length} result${items.length === 1 ? '' : 's'}</p>` : '')
        + cards
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
        this.items = [];          // {el, group}
        this.grids = new Map();   // lookup name -> its cards (one unnamed grid for single-lookup plugins)
        root.innerHTML = `
            <div data-plugin-notice></div>
            <div data-plugin-filter-box class="hidden mb-4 relative">
                <i data-lucide="search" class="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-gray-500 pointer-events-none"></i>
                <input type="search" data-plugin-filter placeholder="Filter results…" class="field field-sm w-full !pl-9">
            </div>
            <p data-plugin-count class="hidden text-xs text-gray-500 mb-3"></p>
            <div data-plugin-cards></div>
            <div data-plugin-data></div>
            <div data-plugin-raw></div>`;
        this.cards = root.querySelector('[data-plugin-cards]');
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
            const group = event.item.action || '';
            this.items.push({ el, group });
            if (this.matches(el)) masonryAppend(this.grid(group), el);
            this.updateCount();
        } else if (event.event === 'data') {
            this.result.data = this.result.data === undefined ? event.data : [].concat(this.result.data, [event.data]);
            if (this.custom) return this.renderAll();
            this.root.querySelector('[data-plugin-data]').innerHTML = `<div class="mt-4">${renderValue(this.result.data)}</div>`;
        } else if (event.event === 'error') {
            this.result.error = event.detail;
        } else if (event.event === 'warning') {
            (this.result.warnings = this.result.warnings || []).push(event.detail);
        } else if (event.event === 'done') {
            this.result.completed = !!event.completed;
            this.result.note = event.note;
            this.result.lookups = event.lookups;
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

    // Cards of one lookup, under its name
    grid(group) {
        if (!this.grids.has(group)) {
            const section = document.createElement('section');
            section.innerHTML = (group ? pluginGroupHead(group, 0) : '') + '<div class="username-masonry"></div>';
            this.cards.appendChild(section);
            this.grids.set(group, section.querySelector('.username-masonry'));
        }
        return this.grids.get(group);
    }

    matches(el) {
        const text = this.filter.value.trim().toLowerCase();
        return !text || el.dataset.pluginText.includes(text);
    }

    applyFilter() {
        for (const [group, grid] of this.grids) {
            const shown = this.items.filter(i => i.group === group && this.matches(i.el)).map(i => i.el);
            masonryLayout(grid, shown);
            grid.parentElement.classList.toggle('hidden', !shown.length);
        }
        this.updateCount();
    }

    updateCount() {
        const total = this.items.length;
        const shown = this.cards.querySelectorAll('.username-result-card').length;
        for (const [group, grid] of this.grids) {
            const counter = grid.parentElement.querySelector('[data-plugin-group-count]');
            if (counter) {
                const all = this.items.filter(i => i.group === group).length;
                const visible = grid.querySelectorAll('.username-result-card').length;
                counter.textContent = visible === all ? all : `${visible} of ${all}`;
            }
        }
        const count = this.root.querySelector('[data-plugin-count]');
        count.classList.toggle('hidden', !total);
        count.textContent = shown === total ? `${total} result${total === 1 ? '' : 's'}` : `${shown} of ${total} results`;
        this.root.querySelector('[data-plugin-filter-box]').classList.toggle('hidden', total < 6);
    }
}
