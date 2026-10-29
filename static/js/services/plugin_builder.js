// Plugin builder (templates/plugin_builder.html, services/plugin_builder.py): a no-code
// plugin's plugin.yaml from a form. Try it sends the draft's request; the answer is shown
// as a tree whose values can be clicked to put them on the cards, with a live preview.
// The API key is written {key:API_KEY} in the form and becomes {settings.<ID>_API_KEY}.
(function () {
    const TYPES = window.builderTypes;
    const params = new URLSearchParams(location.search);
    const editId = params.get('edit');
    const fromId = params.get('from');
    const $ = (id) => document.getElementById(id);
    const val = (id) => $(id).value.trim();
    const ROW_BOXES = { query: 'fQuery', headers: 'fHeaders', fields: 'fFields', entities: 'fEntities' };

    const state = {
        editing: !!editId,
        idTouched: !!editId,
        extra: {},              // the loaded manifest: parts the form doesn't show are kept
        managedKeys: new Set(),
        fixedKey: null,
        keyLabel: '',
        raw: null,
        format: 'json',
        tryValue: '',
        tryType: '',
        detected: !!editId,     // first Try fills the results mapping, unless editing
        lookups: [{}],          // snapshots of each lookup (requests:); the form shows lookups[active]
        active: 0,
        lastTemplate: null,
        dirty: false,
        saving: false,
    };

    // ------------------------------------------------------------------ rows

    function addRow(kind, a = '', b = '') {
        const row = document.createElement('div');
        row.className = 'flex gap-2';
        row.dataset.row = kind;
        const placeholders = { query: ['name', '{value}'], headers: ['Header', 'value'], fields: ['Label', 'path or {template}'], entities: ['', 'path'] }[kind];
        const first = kind === 'entities'
            ? `<select data-a class="field field-sm !w-44 shrink-0">${Object.entries(TYPES).map(([t, l]) =>
                `<option value="${escapeAttr(t)}"${t === a ? ' selected' : ''}>${escapeHtml(l)}</option>`).join('')}</select>`
            : `<input data-a class="field field-sm !w-2/5 shrink-0${kind === 'fields' ? '' : ' font-mono'}" value="${escapeAttr(a)}" placeholder="${placeholders[0]}" autocomplete="off">`;
        const second = `<input data-b class="field field-sm font-mono flex-1 min-w-0" ${kind === 'query' || kind === 'headers' ? 'data-template' : 'data-path list="pathList"'}
            value="${escapeAttr(b)}" placeholder="${escapeAttr(placeholders[1])}" autocomplete="off">`;
        row.innerHTML = `${first}${second}<button type="button" data-remove class="px-2 text-gray-500 hover:text-red-300" title="Remove"><i class="fas fa-times"></i></button>`;
        $(ROW_BOXES[kind]).appendChild(row);
        return row;
    }

    function rows(kind) {
        return [...$(ROW_BOXES[kind]).querySelectorAll('[data-row]')]
            .map(r => [r.querySelector('[data-a]').value.trim(), r.querySelector('[data-b]').value.trim()])
            .filter(([a, b]) => a && b);
    }

    function clearRows(kind) {
        $(ROW_BOXES[kind]).innerHTML = '';
    }

    // ------------------------------------------------------------------ form <-> manifest

    function slug(text) {
        let id = String(text || '').toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 40);
        if (id && !/^[a-z]/.test(id)) id = `p_${id}`.slice(0, 40);
        return id;
    }

    const pluginId = () => val('fId') || slug(val('fName')) || 'draft';
    // editing keeps the plugin's key name (the stored key stays linked); new plugins get <ID>_API_KEY
    const keyName = () => (state.editing && state.fixedKey) || `${pluginId().toUpperCase()}_API_KEY`;
    const withKey = (text) => String(text).replaceAll('{key:API_KEY}', `{settings.${keyName()}}`);
    const accepts = () => [...document.querySelectorAll('[data-accept].active')].map(b => b.dataset.accept);

    // ------------------------------------------------------------------ lookups
    // The form shows one lookup (request + results mapping); each is kept as a snapshot.

    function readLookup() {
        const current = state.lookups[state.active] || {};
        return {
            ...current,
            name: val('fLookupName'),
            accepts: accepts(),
            method: $('fMethod').value,
            url: val('fUrl'),
            query: rows('query'),
            headers: rows('headers'),
            body: val('fBody'),
            empty: val('fEmpty'),
            items: $('fItems').value,
            title: val('fTitle'),
            subtitle: val('fSubtitle'),
            link: val('fLink'),
            image: val('fImage'),
            fields: rows('fields'),
            entities: rows('entities'),
            format: state.format,
            raw: state.raw,
            detected: state.detected,
            tryValue: val('tryValue'),
        };
    }

    function writeLookup(l) {
        $('fLookupName').value = l.name || '';
        setAccepts(l.accepts || []);
        $('fMethod').value = l.method || 'GET';
        $('fUrl').value = l.url || '';
        clearRows('query');
        (l.query || []).forEach(([k, v]) => addRow('query', k, v));
        if (!(l.query || []).length) addRow('query');
        clearRows('headers');
        (l.headers || []).forEach(([k, v]) => addRow('headers', k, v));
        $('fBody').value = l.body || '';
        $('fEmpty').value = l.empty || '404';
        ensureItemsOption(l.items || '');
        $('fItems').value = l.items || '';
        $('fTitle').value = l.title || '';
        $('fSubtitle').value = l.subtitle || '';
        $('fLink').value = l.link || '';
        $('fImage').value = l.image || '';
        clearRows('fields');
        (l.fields || []).forEach(([a, b]) => addRow('fields', a, b));
        clearRows('entities');
        (l.entities || []).forEach(([a, b]) => addRow('entities', a, b));
        state.format = l.format || 'json';
        state.raw = l.raw === undefined ? null : l.raw;
        state.detected = !!l.detected;
        $('tryValue').value = l.tryValue || '';
        $('tryStatus').innerHTML = '';
        if (state.raw !== null) {
            showAnswer();
        } else {
            $('rawCard').classList.add('hidden');
            $('previewCard').classList.add('hidden');
            $('redetect').disabled = true;
        }
    }

    function nameFromUrl(url) {
        const path = String(url || '').replace(/\?.*$/, '').replace(/\{[^}]*\}/g, '').split('/').filter(Boolean);
        const last = (path[path.length - 1] || '').replace(/[-_]+/g, ' ').trim();
        return last ? last[0].toUpperCase() + last.slice(1) : '';
    }

    function renderTabs() {
        const many = state.lookups.length > 1;
        $('lookupTabs').innerHTML = many ? state.lookups.map((l, i) =>
            `<button type="button" data-lookup="${i}" class="b-chip${i === state.active ? ' active' : ''}">${escapeHtml((i === state.active ? val('fLookupName') : l.name) || `Lookup ${i + 1}`)}</button>`).join('') : '';
        $('lookupTabs').classList.toggle('hidden', !many);
        $('lookupNameRow').classList.toggle('hidden', !many);
    }

    function switchLookup(index) {
        state.lookups[state.active] = readLookup();
        state.active = index;
        writeLookup(state.lookups[index]);
        renderTabs();
        refreshUi();
    }

    function addLookup() {
        state.lookups[state.active] = readLookup();
        const first = state.lookups[0];
        if (!first.name) first.name = nameFromUrl(first.url) || 'Lookup 1';
        let origin = '';
        try { origin = new URL(first.url.replace(/\{[^}]*\}/g, 'x')).origin + '/'; } catch (e) { /* no URL yet */ }
        state.lookups.push({ name: `Lookup ${state.lookups.length + 1}`, url: origin, query: [], headers: [], fields: [], entities: [] });
        state.active = state.lookups.length - 1;
        writeLookup(state.lookups[state.active]);
        renderTabs();
        changed();
        $('fLookupName').select();
    }

    function removeLookup() {
        if (state.lookups.length < 2 || !confirm(`Remove the lookup "${val('fLookupName') || state.active + 1}"?`)) return;
        state.lookups.splice(state.active, 1);
        state.active = 0;
        writeLookup(state.lookups[0]);
        renderTabs();
        changed();
    }

    // A lookup snapshot -> {accepts, request, response} (keeping parts the form doesn't show)
    function lookupPart(l) {
        const request = { ...((l.base && l.base.request) || {}) };
        request.method = l.method || 'GET';
        request.url = withKey(l.url || '');
        request.query = Object.fromEntries((l.query || []).map(([k, v]) => [k, withKey(v)]));
        request.headers = Object.fromEntries((l.headers || []).map(([k, v]) => [k, withKey(v)]));
        delete request.json;
        if (request.method === 'POST' && l.body) {
            try {
                request.json = JSON.parse(withKey(l.body));
            } catch (e) {
                state.bodyError = `${l.name || 'The lookup'}: the JSON body is not valid JSON`;
            }
        }
        request.empty_status = String(l.empty || '').split(/[\s,]+/).map(Number).filter(n => n >= 100 && n < 600);

        const response = { ...((l.base && l.base.response) || {}) };
        response.format = l.format || response.format || 'json';
        if (l.items) response.items = l.items; else delete response.items;
        for (const [key, value] of [['title', l.title], ['subtitle', l.subtitle], ['url', l.link], ['image', l.image]]) {
            if (value) response[key] = value; else delete response[key];
        }
        // no rows: every simple value of a result is shown
        if ((l.fields || []).length) response.fields = Object.fromEntries(l.fields); else delete response.fields;
        const entities = {};
        for (const [type, path] of l.entities || []) (entities[type] = entities[type] || []).push(path);
        response.entities = Object.fromEntries(Object.entries(entities).map(([t, p]) => [t, p.length === 1 ? p[0] : p]));
        return { accepts: l.accepts || [], request, response };
    }

    function commonManifest() {
        const m = JSON.parse(JSON.stringify(state.extra || {}));
        for (const key of ['id', 'request', 'response', 'requests', 'request_by_type', 'accepts']) delete m[key];
        m.name = val('fName');
        m.description = val('fDescription');
        m.icon = val('fIcon') || 'puzzle';
        m.site = val('fSite');
        m.cost = $('fCost').value;
        m.cost_note = val('fCostNote');
        const settings = { ...(m.settings || {}) };
        for (const key of state.managedKeys) delete settings[key];
        if ($('fNeedsKey').checked) {
            settings[keyName()] = { label: state.keyLabel || 'API key', secret: true, required: !$('fKeyOptional').checked };
        }
        m.settings = settings;
        return m;
    }

    // The whole plugin: request:/response: for one lookup, requests: for several
    function buildManifest() {
        state.lookups[state.active] = readLookup();
        state.bodyError = null;
        const m = commonManifest();
        if (state.lookups.length === 1) {
            const part = lookupPart(state.lookups[0]);
            m.accepts = part.accepts;
            m.request = part.request;
            m.response = part.response;
            if (state.extra.request_by_type) m.request_by_type = state.extra.request_by_type;
            return m;
        }
        const used = new Set();
        m.requests = state.lookups.map((l, i) => {
            let id = slug(l.name) || `lookup_${i + 1}`;
            while (used.has(id)) id = `${id}_${i + 1}`;
            used.add(id);
            return { id, name: l.name || `Lookup ${i + 1}`, ...lookupPart(l) };
        });
        return m;
    }

    // Just the lookup on screen, for Try it and the preview
    function buildActiveManifest() {
        state.lookups[state.active] = readLookup();
        state.bodyError = null;
        const m = commonManifest();
        const part = lookupPart(state.lookups[state.active]);
        return { ...m, accepts: part.accepts, request: part.request, response: part.response };
    }

    function setAccepts(types) {
        document.querySelectorAll('[data-accept]').forEach(b => b.classList.toggle('active', types.includes(b.dataset.accept)));
        updateTryTypes();
    }

    function ensureItemsOption(path) {
        if (!path || [...$('fItems').options].some(o => o.value === path)) return;
        $('fItems').insertAdjacentHTML('beforeend', `<option value="${escapeAttr(path)}">${escapeHtml(path === '.' ? 'The answer is a list' : path)}</option>`);
    }

    function applyMapping(r) {
        ensureItemsOption(r.items || '');
        $('fItems').value = r.items || '';
        $('fTitle').value = r.title || '';
        $('fSubtitle').value = r.subtitle || '';
        $('fLink').value = r.url || '';
        $('fImage').value = r.image || '';
        clearRows('fields');
        for (const [label, path] of Object.entries(r.fields || {})) addRow('fields', label, path);
        clearRows('entities');
        for (const [type, paths] of Object.entries(r.entities || {})) {
            for (const path of [].concat(paths)) addRow('entities', type, path);
        }
        if (r.format) state.format = r.format;
    }

    function loadManifest(m, id) {
        state.extra = JSON.parse(JSON.stringify(m));
        const prefix = `${id.toUpperCase()}_`;
        const own = Object.keys(m.settings || {}).filter(k => k.startsWith(prefix));
        const ownKey = own.find(k => /_API_KEY$/.test(k)) || own.find(k => m.settings[k].secret) || own[0];
        if (ownKey) {
            state.fixedKey = ownKey;
            state.keyLabel = m.settings[ownKey].label || '';
            state.managedKeys.add(ownKey);
        }
        const unkey = (text) => ownKey ? String(text).replaceAll(`{settings.${ownKey}}`, '{key:API_KEY}') : String(text);
        $('fName').value = m.name || '';
        $('fId').value = id;
        $('fDescription').value = m.description || '';
        $('fIcon').value = m.icon && m.icon !== 'puzzle' ? m.icon : '';
        $('fSite').value = m.site || '';
        $('fCost').value = m.cost || 'free';
        $('fCostNote').value = m.cost_note || '';
        $('fNeedsKey').checked = !!ownKey;
        $('fKeyOptional').checked = ownKey ? m.settings[ownKey].required === false : false;

        const snapshot = (name, accepts, req, res) => ({
            name, accepts: accepts || [],
            base: { request: req || {}, response: res || {} },
            method: (req || {}).method || 'GET',
            url: unkey((req || {}).url || ''),
            query: Object.entries((req || {}).query || {}).map(([k, v]) => [k, unkey(v)]),
            headers: Object.entries((req || {}).headers || {}).map(([k, v]) => [k, unkey(v)]),
            body: req && req.json !== undefined && req.json !== null ? unkey(JSON.stringify(req.json, null, 2)) : '',
            empty: ((req || {}).empty_status || [404]).join(', '),
            items: (res || {}).items || '',
            title: (res || {}).title || '',
            subtitle: (res || {}).subtitle || '',
            link: (res || {}).url || '',
            image: (res || {}).image || '',
            fields: Object.entries((res || {}).fields || {}),
            entities: Object.entries((res || {}).entities || {}).flatMap(([t, p]) => [].concat(p).map(path => [t, path])),
            format: (res || {}).format || 'json',
            raw: null,
            detected: true,   // keep the mapping it comes with
        });
        state.lookups = (m.requests || []).length
            ? m.requests.map(a => snapshot(a.name, a.accepts, a.request, a.response))
            : [snapshot('', m.accepts, m.request, m.response)];
        state.active = 0;
        writeLookup(state.lookups[0]);
        renderTabs();
        refreshUi();
    }

    function applyCurl(result) {
        const req = result.request;
        $('fMethod').value = req.method;
        $('fUrl').value = req.url;
        clearRows('query');
        Object.entries(req.query || {}).forEach(([k, v]) => addRow('query', k, v));
        clearRows('headers');
        Object.entries(req.headers || {}).forEach(([k, v]) => addRow('headers', k, v));
        $('fBody').value = req.json ? JSON.stringify(req.json, null, 2) : '';
        if (req.form && Object.keys(req.form).length && !req.json) {
            $('fBody').value = JSON.stringify(req.form, null, 2);
        }
        if (result.api_key) {
            $('fNeedsKey').checked = true;
            $('fKeyValue').value = result.api_key;
        }
        const host = (() => { try { return new URL(req.url.replace('{value}', 'x')).hostname; } catch (e) { return ''; } })();
        const site = host.replace(/^(api|www|v\d)\./, '');
        if (!val('fSite') && site) $('fSite').value = site;
        if (!val('fName') && site) $('fName').value = site;
        if (result.value) {
            if (!accepts().length && TYPES[result.value.type]) setAccepts([result.value.type]);
            $('tryValue').value = result.value.example;
            if (TYPES[result.value.type]) $('tryType').value = result.value.type;
        }
        const notes = [];
        if (result.api_key) notes.push(`<p class="text-emerald-300"><i class="fas fa-key mr-2"></i>API key found - it is saved in Settings as <span class="font-mono">${escapeHtml(keyName())}</span>, not in the plugin.</p>`);
        if (result.value) notes.push(`<p class="text-emerald-300"><i class="fas fa-check mr-2"></i>${escapeHtml(TYPES[result.value.type] || result.value.type)} <span class="font-mono">${escapeHtml(result.value.example)}</span> replaced with <span class="font-mono">{value}</span>.</p>`);
        for (const w of result.warnings || []) notes.push(`<p class="text-amber-300"><i class="fas fa-exclamation-triangle mr-2"></i>${escapeHtml(w)}</p>`);
        $('curlNotes').innerHTML = notes.join('');
        refreshUi();
    }

    // ------------------------------------------------------------------ UI state

    function updateTryTypes() {
        const types = accepts();
        const select = $('tryType');
        const current = select.value;
        select.innerHTML = types.map(t => `<option value="${escapeAttr(t)}">${escapeHtml(TYPES[t])}</option>`).join('')
            || '<option value="">Choose what it looks up</option>';
        if (types.includes(current)) select.value = current;
        select.classList.toggle('hidden', types.length < 2);
    }

    function refreshUi() {
        if (!state.idTouched && !state.editing) $('fId').value = slug(val('fName'));
        $('fKeyName').textContent = $('fNeedsKey').checked ? `saved as ${keyName()}` : '';
        $('fKeyBox').classList.toggle('hidden', !$('fNeedsKey').checked);
        $('fBodyBox').classList.toggle('hidden', $('fMethod').value !== 'POST');
        $('fIconPreview').outerHTML = `<i id="fIconPreview" data-lucide="${escapeAttr(val('fIcon') || 'puzzle')}" class="w-5 h-5 text-purple-300 shrink-0"></i>`;
        if (window.lucide) lucide.createIcons();
        schedule();
    }

    let timer = null;
    function schedule() {
        clearTimeout(timer);
        timer = setTimeout(() => { updateYaml(); updatePreview(); markUsed(); }, 300);
    }

    async function post(url, body) {
        const response = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            const detail = Array.isArray(data.detail) ? data.detail.map(d => d.msg).join(', ') : data.detail;
            throw new Error(detail || `HTTP ${response.status}`);
        }
        return data;
    }

    async function updateYaml() {
        if ($('yamlEdit').checked) return;
        try {
            const data = await post('/api/plugins/builder/yaml', { id: pluginId(), manifest: buildManifest() });
            renderTabs();
            $('yamlText').value = data.yaml;
            const error = state.bodyError || data.error;
            $('yamlError').textContent = error ? `Not ready to save: ${error}` : '';
            $('yamlError').classList.toggle('hidden', !error);
        } catch (e) { /* shown on save */ }
    }

    async function updatePreview() {
        if (state.raw === null) return;
        try {
            const data = await post('/api/plugins/builder/preview', {
                id: pluginId(), manifest: buildActiveManifest(), raw: state.raw, value: state.tryValue, type: state.tryType,
            });
            showCards(data.items);
            $('previewError').classList.add('hidden');
        } catch (e) {
            $('previewError').textContent = e.message;
            $('previewError').classList.remove('hidden');
        }
    }

    function showCards(items) {
        $('previewCard').classList.remove('hidden');
        $('previewCount').textContent = `${items.length} card${items.length === 1 ? '' : 's'}`;
        $('previewCards').innerHTML = items.length ? pluginCardsHtml(items.slice(0, 30))
            : '<p class="text-sm text-gray-400">No cards - check the results list and the paths.</p>';
        masonryPackAll($('previewCards'));
        if (window.lucide) lucide.createIcons();
    }

    // ------------------------------------------------------------------ the answer

    function findLists(value, path = '', out = [], depth = 0) {
        if (depth > 5 || value === null || typeof value !== 'object') return out;
        if (Array.isArray(value)) {
            if (value.some(v => v && typeof v === 'object' && !Array.isArray(v))) out.push(path || '.');
            if (state.format === 'text' && path === 'lines') out.push('lines');
            return out;
        }
        for (const [k, v] of Object.entries(value)) findLists(v, path ? `${path}.${k}` : k, out, depth + 1);
        return out;
    }

    function treeHtml(value, path, key, depth) {
        const label = key !== null ? `<span class="b-key">${escapeHtml(key)}</span>: ` : '';
        if (Array.isArray(value)) {
            const isList = value.some(v => v && typeof v === 'object' && !Array.isArray(v)) || (state.format === 'text' && path === 'lines');
            const head = `<span class="b-node" data-path="${escapeAttr(path)}" data-kind="${isList ? 'list' : 'value'}">${label}<span class="b-null">[${value.length}]</span></span>`;
            const shown = value.slice(0, 3);
            return `<details${depth < 4 ? ' open' : ''}><summary>${head}${isList ? '<span class="b-hint">list</span>' : ''}</summary>
                <div class="pl-4">${shown.map((v, i) => treeHtml(v, `${path}[${i}]`, String(i), depth + 1)).join('')}
                ${value.length > 3 ? `<div class="b-null">… ${value.length - 3} more</div>` : ''}</div></details>`;
        }
        if (value && typeof value === 'object') {
            return `<details${depth < 4 ? ' open' : ''}><summary>${label}<span class="b-null">{${Object.keys(value).length}}</span></summary>
                <div class="pl-4">${Object.entries(value).map(([k, v]) => treeHtml(v, path ? `${path}.${k}` : k, k, depth + 1)).join('')}</div></details>`;
        }
        const cls = typeof value === 'string' ? 'b-str' : value === null ? 'b-null' : 'b-num';
        const text = typeof value === 'string' ? JSON.stringify(value.length > 160 ? `${value.slice(0, 160)}…` : value) : String(value);
        return `<div><span class="b-node" data-path="${escapeAttr(path)}" data-kind="value">${label}<span class="${cls}">${escapeHtml(text)}</span></span></div>`;
    }

    function showAnswer() {
        $('rawCard').classList.remove('hidden');
        $('rawTree').innerHTML = state.raw && state.raw.truncated
            ? `<p class="text-amber-300">The answer is too large to show (${state.raw.characters.toLocaleString()} characters).</p>`
            : treeHtml(state.raw, '', null, 0);
        const lists = findLists(state.raw);
        const current = $('fItems').value;
        $('fItems').innerHTML = '<option value="">The whole answer is one result</option>'
            + [...new Set(lists)].map(p => `<option value="${escapeAttr(p)}">${escapeHtml(p === '.' ? 'The answer is a list' : p)}</option>`).join('');
        ensureItemsOption(current);
        $('fItems').value = current;
        markUsed();
    }

    // Path inside one result (what the mapping uses) for a path in the whole answer
    function relativePath(abs) {
        const items = $('fItems').value;
        const listMode = items || Array.isArray(state.raw);
        if (!listMode) return abs.replace(/\[\d+\]/g, '[]') || '.';
        const prefix = items && items !== '.' ? items : '';
        const match = abs.match(new RegExp(`^${prefix.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\[\\d+\\]`));
        if (!match) return null;
        return abs.slice(match[0].length).replace(/^\./, '').replace(/\[\d+\]/g, '[]') || '.';
    }

    // Highlight answer values the cards use
    function markUsed() {
        const used = new Set([val('fTitle'), val('fSubtitle'), val('fLink'), val('fImage'),
            ...rows('fields').map(r => r[1]), ...rows('entities').map(r => r[1])]);
        $('rawTree').querySelectorAll('.b-node[data-kind="value"]').forEach(node => {
            node.classList.toggle('b-used', used.has(relativePath(node.dataset.path)));
        });
        const datalist = new Set();
        $('rawTree').querySelectorAll('.b-node[data-kind="value"]').forEach(node => {
            const rel = relativePath(node.dataset.path);
            if (rel) datalist.add(rel);
        });
        $('pathList').innerHTML = [...datalist].map(p => `<option value="${escapeAttr(p)}">`).join('');
    }

    function labelFor(path) {
        const parts = path.replace(/\[\]/g, '').split('.');
        const last = parts[parts.length - 1] === '' ? 'Value' : parts[parts.length - 1];
        const words = last.replace(/([a-z])([A-Z])/g, '$1 $2').replace(/[_-]+/g, ' ').trim();
        return words ? words[0].toUpperCase() + words.slice(1) : path;
    }

    const menu = $('pathMenu');

    function openMenu(node, event) {
        const abs = node.dataset.path;
        const kind = node.dataset.kind;
        const item = (action, text, extra = '') => `<button type="button" data-menu="${action}" ${extra} class="w-full text-left px-3 py-1.5 hover:bg-gray-800">${text}</button>`;
        let html;
        if (kind === 'list') {
            html = `<div class="px-3 py-1.5 text-xs text-gray-500 font-mono truncate">${escapeHtml(abs || '.')}</div>`
                + item('items', '<i class="fas fa-th-large w-4 mr-2 text-purple-300"></i>One card per element');
        } else {
            const rel = relativePath(abs);
            if (rel === null) {
                html = '<p class="px-3 py-2 text-xs text-gray-400">Outside the results list. Pick the list that contains it, or "The whole answer is one result".</p>';
            } else {
                html = `<div class="px-3 py-1.5 text-xs text-gray-500 font-mono truncate" title="${escapeAttr(rel)}">${escapeHtml(rel)}</div>`
                    + item('fTitle', '<i class="fas fa-heading w-4 mr-2 text-purple-300"></i>Title')
                    + item('fSubtitle', '<i class="fas fa-font w-4 mr-2 text-purple-300"></i>Subtitle')
                    + item('fLink', '<i class="fas fa-external-link-alt w-4 mr-2 text-purple-300"></i>Link')
                    + item('fImage', '<i class="fas fa-image w-4 mr-2 text-purple-300"></i>Picture')
                    + item('field', '<i class="fas fa-list w-4 mr-2 text-purple-300"></i>Add as a row')
                    + `<div class="px-3 pt-2 pb-1 text-xs text-gray-500">Identifier to pivot on</div>
                       <div class="px-2 pb-2 flex flex-wrap gap-1">${['email', 'phone', 'username', 'domain', 'ip', 'url', 'telegram_username', 'telegram_id']
                        .map(t => `<button type="button" data-menu="entity" data-type="${t}" class="b-chip !px-2 !py-0.5">${escapeHtml(TYPES[t])}</button>`).join('')}</div>`;
                menu.dataset.rel = rel;
            }
        }
        menu.dataset.abs = abs;
        menu.innerHTML = html;
        menu.classList.remove('hidden');
        const x = Math.min(event.clientX, window.innerWidth - menu.offsetWidth - 8);
        const y = Math.min(event.clientY + 8, window.innerHeight - menu.offsetHeight - 8);
        menu.style.left = `${Math.max(8, x)}px`;
        menu.style.top = `${Math.max(8, y)}px`;
    }

    function closeMenu() {
        menu.classList.add('hidden');
    }

    menu.addEventListener('click', (event) => {
        const button = event.target.closest('[data-menu]');
        if (!button) return;
        const action = button.dataset.menu;
        const rel = menu.dataset.rel;
        if (action === 'items') {
            const path = menu.dataset.abs || '.';
            ensureItemsOption(path);
            $('fItems').value = path;
        } else if (action === 'field') {
            addRow('fields', labelFor(rel), rel);
        } else if (action === 'entity') {
            addRow('entities', button.dataset.type, rel);
        } else {
            $(action).value = rel;
        }
        closeMenu();
        changed();
    });

    $('rawTree').addEventListener('click', (event) => {
        const node = event.target.closest('.b-node');
        if (!node) return;
        event.preventDefault();
        event.stopPropagation();
        openMenu(node, event);
    });
    document.addEventListener('click', (event) => {
        if (!menu.contains(event.target)) closeMenu();
    });
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') closeMenu();
    });

    // ------------------------------------------------------------------ actions

    async function tryIt(detect) {
        state.tryValue = val('tryValue');
        state.tryType = $('tryType').value || accepts()[0] || '';
        if (!state.tryValue) {
            $('tryStatus').innerHTML = '<span class="text-amber-300">Enter a value to look up.</span>';
            return;
        }
        $('tryBtn').disabled = true;
        $('tryStatus').innerHTML = '<span class="text-gray-400"><i class="fas fa-spinner fa-spin mr-2"></i>Sending…</span>';
        const started = Date.now();
        try {
            const data = await post('/api/plugins/builder/test', {
                id: pluginId(), manifest: buildActiveManifest(), value: state.tryValue, type: state.tryType,
                settings: { [keyName()]: val('fKeyValue') }, detect: detect ?? !state.detected,
            });
            state.raw = data.raw;
            state.format = data.format;
            const seconds = ((Date.now() - started) / 1000).toFixed(1);
            const color = data.status < 300 ? 'text-emerald-300' : data.status < 500 ? 'text-amber-300' : 'text-red-300';
            $('tryStatus').innerHTML = `<div class="flex flex-wrap gap-x-3"><span class="${color} font-semibold">HTTP ${data.status}</span>
                <span class="text-gray-400">${seconds}s · ${escapeHtml(data.format === 'text' ? 'text' : 'JSON')}</span></div>
                <div class="text-xs text-gray-500 font-mono break-all mt-1">${escapeHtml(data.url)}</div>
                ${data.note ? `<p class="text-amber-300 mt-2">${escapeHtml(data.note)}</p>` : ''}
                ${data.error ? `<p class="text-red-300 mt-2 break-words">${escapeHtml(data.error)}</p>` : ''}`;
            showAnswer();
            if (data.suggestion) {
                applyMapping(data.suggestion);
                state.detected = true;
                $('tryStatus').insertAdjacentHTML('beforeend', '<p class="text-purple-300 mt-2"><i class="fas fa-magic mr-2"></i>Results mapping filled in from the answer - adjust it on the left or click values below.</p>');
            }
            $('redetect').disabled = false;
            $('redetect').title = '';
            if (data.items) showCards(data.items);
            changed();
        } catch (e) {
            $('tryStatus').innerHTML = `<span class="text-red-300 break-words">${escapeHtml(e.message)}</span>`;
        } finally {
            $('tryBtn').disabled = false;
        }
    }

    async function redetect() {
        if (state.raw === null) return;
        try {
            const data = await post('/api/plugins/builder/detect', { raw: state.raw, format: state.format });
            applyMapping(data.suggestion);
            showAnswer();
            changed();
        } catch (e) {
            showTemporaryNotification(e.message, 'error');
        }
    }

    async function save() {
        const manifest = buildManifest();
        if (state.bodyError && !$('yamlEdit').checked) {
            $('saveNote').innerHTML = `<span class="text-red-300">${escapeHtml(state.bodyError)}</span>`;
            return;
        }
        const id = pluginId();
        const body = { id, editing: state.editing, settings: { [keyName()]: val('fKeyValue') } };
        if ($('yamlEdit').checked) body.yaml = $('yamlText').value; else body.manifest = manifest;
        $('saveBtn').disabled = true;
        $('saveNote').textContent = 'Saving…';
        try {
            const plugin = await post('/api/plugins/builder/save', body);
            state.saving = true;
            location.href = plugin.page;
        } catch (e) {
            $('saveNote').innerHTML = `<span class="text-red-300">${escapeHtml(e.message)}</span>`;
            $('saveBtn').disabled = false;
        }
    }

    function changed() {
        state.dirty = true;
        refreshUi();
    }

    // ------------------------------------------------------------------ wiring

    $('curlImport').addEventListener('click', async () => {
        if (!val('curlInput')) return;
        try {
            applyCurl(await post('/api/plugins/builder/curl', { command: $('curlInput').value, example: val('curlExample') }));
            state.dirty = true;
        } catch (e) {
            $('curlNotes').innerHTML = `<p class="text-red-300">${escapeHtml(e.message)}</p>`;
        }
    });
    $('fAccepts').addEventListener('click', (event) => {
        const chip = event.target.closest('[data-accept]');
        if (!chip) return;
        chip.classList.toggle('active');
        updateTryTypes();
        changed();
    });
    document.querySelectorAll('[data-add-row]').forEach(b => b.addEventListener('click', () => {
        addRow(b.dataset.addRow).querySelector('[data-a]').focus();
    }));
    document.addEventListener('click', (event) => {
        const remove = event.target.closest('[data-remove]');
        if (remove) {
            remove.closest('[data-row]').remove();
            changed();
        }
    });
    // inserts go into the template field last typed in (the URL by default)
    document.addEventListener('focusin', (event) => {
        if (event.target.matches('[data-template]')) state.lastTemplate = event.target;
    });
    document.querySelectorAll('[data-insert]').forEach(b => b.addEventListener('mousedown', (event) => {
        event.preventDefault();   // keep the field's cursor
        const target = state.lastTemplate && document.body.contains(state.lastTemplate) ? state.lastTemplate : $('fUrl');
        const token = b.dataset.insert;
        const start = target.selectionStart ?? target.value.length;
        const end = target.selectionEnd ?? target.value.length;
        target.setRangeText(token, start, end, 'end');
        target.focus();
        if (token === '{key:API_KEY}') $('fNeedsKey').checked = true;
        changed();
    }));
    $('fId').addEventListener('input', () => { state.idTouched = true; });
    $('builderGrid').addEventListener('input', (event) => {
        if (event.target.closest('#importCard') || event.target.id === 'tryValue' || event.target.id === 'yamlText') return;
        changed();
    });
    $('builderGrid').addEventListener('change', (event) => {
        if (event.target.closest('#importCard') || event.target.id === 'tryType' || event.target.id === 'yamlEdit') return;
        changed();
    });
    $('tryBtn').addEventListener('click', () => tryIt());
    $('tryValue').addEventListener('keydown', (event) => { if (event.key === 'Enter') tryIt(); });
    $('redetect').addEventListener('click', redetect);
    $('addLookup').addEventListener('click', addLookup);
    $('removeLookup').addEventListener('click', removeLookup);
    $('lookupTabs').addEventListener('click', (event) => {
        const tab = event.target.closest('[data-lookup]');
        if (tab && Number(tab.dataset.lookup) !== state.active) switchLookup(Number(tab.dataset.lookup));
    });
    $('fLookupName').addEventListener('input', renderTabs);
    $('saveBtn').addEventListener('click', save);
    $('yamlEdit').addEventListener('change', () => {
        const editing = $('yamlEdit').checked;
        $('yamlText').readOnly = !editing;
        $('yamlNote').classList.toggle('hidden', !editing);
        if (!editing) updateYaml();
    });
    window.addEventListener('beforeunload', (event) => {
        if (state.dirty && !state.saving) event.preventDefault();
    });

    async function init() {
        updateTryTypes();
        const source = editId || fromId;
        if (source) {
            try {
                const response = await fetch(`/api/plugins/${encodeURIComponent(source)}/manifest`);
                const data = await response.json();
                if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
                if (editId && !data.editable) {
                    location.replace(`/plugins/builder?from=${encodeURIComponent(editId)}`);
                    return;
                }
                if (editId) {
                    loadManifest(data.manifest, editId);
                    $('fId').readOnly = true;
                    $('builderTitle').textContent = `Edit ${data.manifest.name || editId}`;
                    $('importCard').classList.add('hidden');
                    const key = [...state.managedKeys][0];
                    if (key && data.settings[key] && data.settings[key].configured) {
                        $('fKeyValue').placeholder = 'Saved - leave empty to keep it';
                    }
                } else {
                    const id = slug(`${fromId}_copy`);
                    loadManifest(data.manifest, fromId);
                    $('fId').value = id;
                    state.idTouched = true;
                    $('fName').value = `${data.manifest.name || fromId} (copy)`;
                    state.detected = true;   // keep the mapping it comes with
                    $('builderTitle').textContent = `New plugin from ${data.manifest.name || fromId}`;
                }
            } catch (e) {
                showTemporaryNotification(`Could not load the plugin: ${e.message}`, 'error');
            }
        } else {
            addRow('query');
        }
        renderTabs();
        state.dirty = false;
        refreshUi();
    }

    init();
})();
