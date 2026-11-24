// The graph's look: a colour and an icon per identifier type, the badges drawn on
// nodes, and the Cytoscape stylesheet. Labels are drawn on the canvas as text,
// so nothing from results is ever parsed as HTML here.

export const TYPE_COLORS = {
    username: '#a78bfa',
    email: '#38bdf8',
    phone: '#34d399',
    domain: '#fbbf24',
    ip: '#22d3ee',
    url: '#94a3b8',
    telegram_id: '#60a5fa',
    telegram_username: '#60a5fa',
    vk: '#818cf8',
    gaia_id: '#f87171',
    crypto_btc: '#fb923c',
    crypto_eth: '#fb923c',
    bssid: '#2dd4bf',
    name: '#f472b6',
    text: '#9ca3af',
};

// Lucide icon names (static/lucide.js)
export const TYPE_ICONS = {
    username: 'user',
    email: 'mail',
    phone: 'phone',
    domain: 'globe',
    ip: 'server',
    url: 'link',
    telegram_id: 'send',
    telegram_username: 'send',
    vk: 'user-round',
    gaia_id: 'key-round',
    crypto_btc: 'bitcoin',
    crypto_eth: 'coins',
    bssid: 'wifi',
    name: 'id-card',
    text: 'type',
};

// What the analyst adds besides identifiers
export const MANUAL_TYPES = {
    person: { label: 'Person', color: '#f472b6', icon: 'user-round' },
    organisation: { label: 'Organisation', color: '#c084fc', icon: 'building-2' },
    location: { label: 'Location', color: '#4ade80', icon: 'map-pin' },
    event: { label: 'Event', color: '#facc15', icon: 'calendar' },
    note: { label: 'Note', color: '#9ca3af', icon: 'sticky-note' },
    image: { label: 'Image', color: '#94a3b8', icon: 'image' },
};

export const typeColor = (type) => TYPE_COLORS[type] || MANUAL_TYPES[type]?.color || '#9ca3af';

const PURPLE = '#a855f7';
const AMBER = '#f59e0b';

// ---------------------------------------------------------------------------
// Icons and badges as SVG images (Cytoscape draws node images, not HTML)
// ---------------------------------------------------------------------------
const uriCache = new Map();

function svgUri(svg) {
    return 'data:image/svg+xml;utf8,' + encodeURIComponent(svg);
}

function lucideChildren(name) {
    const pascal = name.replace(/(^|-)([a-z0-9])/g, (_, __, c) => c.toUpperCase());
    const icon = window.lucide?.icons?.[pascal] || window.lucide?.icons?.Circle;
    const draw = ([tag, attrs, children = []]) =>
        `<${tag} ${Object.entries(attrs)
            .map(([k, v]) => `${k}="${String(v).replace(/"/g, '&quot;')}"`)
            .join(' ')}>${children.map(draw).join('')}</${tag}>`;
    // [svg, attrs, children]: only the children, the svg element is ours
    return icon ? (icon[2] || []).map(draw).join('') : '';
}

export function iconUri(name, color = '#ffffff', opacity = 0.6) {
    const key = `icon:${name}:${color}:${opacity}`;
    if (!uriCache.has(key))
        uriCache.set(
            key,
            svgUri(
                `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="${color}" stroke-opacity="${opacity}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${lucideChildren(name)}</svg>`
            )
        );
    return uriCache.get(key);
}

// A rounded pill with short text ("48", "+12", "×3")
function pillBadge(text, fill, color = '#ffffff') {
    const width = Math.max(16, 8 + text.length * 6.2);
    const key = `pill:${text}:${fill}:${color}`;
    if (!uriCache.has(key))
        uriCache.set(
            key,
            svgUri(
                `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="16" viewBox="0 0 ${width} 16"><rect x="0.5" y="0.5" width="${width - 1}" height="15" rx="7.5" fill="${fill}" stroke="#000" stroke-opacity=".6"/><text x="${width / 2}" y="11.5" text-anchor="middle" font-family="JetBrains Mono, ui-monospace, monospace" font-size="9.5" font-weight="700" fill="${color}">${text}</text></svg>`
            )
        );
    return { uri: uriCache.get(key), w: width, h: 16 };
}

// "Also in N other cases": a link icon and the number
function sharedBadge(count) {
    const text = String(count);
    const width = 20 + text.length * 6.2;
    const key = `shared:${text}`;
    if (!uriCache.has(key))
        uriCache.set(
            key,
            svgUri(
                `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="16" viewBox="0 0 ${width} 16"><rect x="0.5" y="0.5" width="${width - 1}" height="15" rx="7.5" fill="#312e81" stroke="#000" stroke-opacity=".6"/><g transform="translate(3 3) scale(.42)" fill="none" stroke="#c4b5fd" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round">${lucideChildren('link')}</g><text x="${15 + (text.length * 6.2) / 2}" y="11.5" text-anchor="middle" font-family="JetBrains Mono, ui-monospace, monospace" font-size="9.5" font-weight="700" fill="#c4b5fd">${text}</text></svg>`
            )
        );
    return { uri: uriCache.get(key), w: width, h: 16 };
}

// A round badge with an icon (check, star)
function iconBadge(name, fill, color = '#ffffff') {
    const key = `badge:${name}:${fill}:${color}`;
    if (!uriCache.has(key))
        uriCache.set(
            key,
            svgUri(
                `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16"><circle cx="8" cy="8" r="7.5" fill="${fill}" stroke="#000" stroke-opacity=".6"/><g transform="translate(3.5 3.5) scale(.375)" fill="none" stroke="${color}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">${lucideChildren(name)}</g></svg>`
            )
        );
    return { uri: uriCache.get(key), w: 16, h: 16 };
}

// ---------------------------------------------------------------------------
// What a node shows: its icon (or picture) and badges, as Cytoscape's
// parallel background-image lists. Computed when a node's data changes.
// ---------------------------------------------------------------------------
const CORNERS = {
    'top-right': ['100%', '0%', 5, -5],
    'bottom-right': ['100%', '100%', 5, 5],
    'top-left': ['0%', '0%', -5, -5],
    right: ['100%', '50%', 12, 0],
};

export function decorate(data) {
    const layers = [];
    const add = (uri, extra) =>
        layers.push({ uri, w: '55%', h: '55%', x: '50%', y: '50%', ox: 0, oy: 0, fit: 'none', over: false, ...extra });
    const badge = (b, corner) => {
        const [x, y, ox, oy] = CORNERS[corner];
        add(b.uri, { w: `${b.w}px`, h: `${b.h}px`, x, y, ox, oy, over: true });
    };

    if (data.kind === 'identifier') {
        add(iconUri(TYPE_ICONS[data.type] || 'circle'));
        if (data.picture) add(data.picture, { w: '100%', h: '100%', fit: 'cover' });
        if (data.status === 'confirmed') badge(iconBadge('check', PURPLE), 'top-right');
        else if (data.status === 'important') badge(iconBadge('star', AMBER, '#1f1300'), 'top-right');
        if (data.shared) badge(sharedBadge(data.shared), 'bottom-right');
    } else if (data.kind === 'manual') {
        add(iconUri(MANUAL_TYPES[data.type]?.icon || TYPE_ICONS[data.type] || 'circle'));
        if (data.picture) add(data.picture, { w: '100%', h: '100%', fit: 'cover' });
        // the analyst's own
        badge(iconBadge('pencil', '#374151', '#e5e7eb'), 'top-left');
    } else if (data.kind === 'lookup') {
        add(iconUri(data.icon || 'terminal', '#c4b5fd', 0.9), { w: '16px', h: '16px', x: '0%', ox: 12 });
        // + how many findings it hides; − when it is open and can fold
        if (data.open && data.foldable) badge(pillBadge('−', '#374151'), 'right');
        else if (!data.open && data.hidden) badge(pillBadge(`+${data.hidden}`, '#6d28d9'), 'right');
    } else if (data.kind === 'group') {
        add(iconUri('layers', data.color, 0.75));
        badge(pillBadge(data.open ? '−' : String(data.count), data.open ? '#1f2937' : '#6d28d9'), 'top-right');
    } else if (data.kind === 'more') {
        add(iconUri('ellipsis', '#9ca3af', 0.8));
    }
    return layers;
}

const layer = (key) => (ele) => {
    const layers = ele.data('decor') || [];
    return layers.length ? layers.map((l) => l[key]) : key === 'uri' ? 'none' : [];
};

// ---------------------------------------------------------------------------
// Stylesheet
// ---------------------------------------------------------------------------
export function stylesheet() {
    return [
        {
            selector: 'node',
            style: {
                width: 'data(w)',
                height: 'data(h)',
                'background-color': '#1a1b26',
                'border-width': 2,
                'border-color': 'data(color)',
                label: 'data(label)',
                color: '#e5e7eb',
                'font-family': 'JetBrains Mono, ui-monospace, monospace',
                'font-size': 11,
                'text-valign': 'bottom',
                'text-margin-y': 6,
                'text-outline-color': '#000',
                'text-outline-width': 2,
                'text-outline-opacity': 0.85,
                'min-zoomed-font-size': 5,
                'background-image': layer('uri'),
                'background-width': layer('w'),
                'background-height': layer('h'),
                'background-position-x': layer('x'),
                'background-position-y': layer('y'),
                'background-offset-x': layer('ox'),
                'background-offset-y': layer('oy'),
                'background-fit': layer('fit'),
                'background-clip': (ele) => (ele.data('decor') || []).map((l) => (l.over ? 'none' : 'node')),
                'background-image-containment': (ele) =>
                    (ele.data('decor') || []).map((l) => (l.over ? 'over' : 'inside')),
                'background-image-crossorigin': 'null',
                'background-image-smoothing': 'yes',
                'overlay-opacity': 0,
                'transition-property': 'opacity, border-color',
                'transition-duration': 180,
            },
        },
        {
            selector: 'node[kind = "lookup"]',
            style: {
                shape: 'round-rectangle',
                'corner-radius': 12,
                'background-color': '#0f1017',
                'border-color': '#24283b',
                'border-width': 1.5,
                color: '#d1d5db',
                'font-size': 10,
                'text-valign': 'center',
                'text-halign': 'center',
                'text-margin-y': 0,
                'text-margin-x': 11,
                'text-wrap': 'wrap',
                'text-justification': 'left',
                'line-height': 1.35,
                'text-outline-width': 0,
            },
        },
        { selector: 'node[kind = "lookup"][?rerun]', style: { 'border-color': '#4c1d95' } },
        {
            selector: 'node[kind = "group"]',
            style: {
                'background-color': '#0f1017',
                'outline-width': 1.5,
                'outline-color': 'data(color)',
                'outline-offset': 3,
                'outline-opacity': 0.4,
                color: '#d1d5db',
            },
        },
        {
            selector: 'node[kind = "more"]',
            style: {
                'background-color': '#0f1017',
                'border-color': '#4b5563',
                'border-style': 'dashed',
                'border-width': 1.5,
                color: '#9ca3af',
                'font-size': 10,
            },
        },
        { selector: 'node[?root]', style: { 'border-width': 3, 'font-weight': 'bold' } },
        { selector: 'node[status = "confirmed"]', style: { 'border-color': PURPLE, 'border-width': 3 } },
        { selector: 'node[status = "false_positive"]', style: { opacity: 0.35, 'border-style': 'dashed' } },
        {
            selector: 'node.hover',
            style: {
                width: (ele) => ele.data('w') * 1.08,
                height: (ele) => ele.data('h') * 1.08,
                'z-index': 20,
            },
        },
        {
            selector: 'node:selected',
            style: {
                'underlay-color': PURPLE,
                'underlay-opacity': 0.3,
                'underlay-padding': 7,
                'underlay-shape': 'ellipse',
                'z-index': 30,
            },
        },
        { selector: 'node[kind = "lookup"]:selected', style: { 'underlay-shape': 'round-rectangle' } },
        {
            selector: 'node.pulse',
            style: { 'underlay-color': PURPLE, 'underlay-opacity': 0.45, 'underlay-padding': 12 },
        },
        {
            selector: 'edge',
            style: {
                width: 1,
                'line-color': '#4b5563',
                'line-opacity': 0.45,
                'curve-style': 'round-taxi',
                'taxi-direction': 'rightward',
                'taxi-turn': '45%',
                'taxi-radius': 14,
                'target-arrow-shape': 'triangle',
                'target-arrow-color': '#4b5563',
                'arrow-scale': 0.55,
                'transition-property': 'line-color, line-opacity, target-arrow-color, opacity',
                'transition-duration': 180,
            },
        },
        // links outside the tree (an identifier found in two branches): a plain curve
        {
            selector: 'edge.cross',
            style: { 'curve-style': 'unbundled-bezier', 'line-style': 'dashed', 'line-dash-pattern': [4, 4] },
        },
        {
            selector: 'edge.lit',
            style: {
                'line-color': 'data(color)',
                'target-arrow-color': 'data(color)',
                'line-opacity': 0.95,
                width: 1.5,
            },
        },
        {
            selector: 'edge[kind = "manual"]',
            style: {
                'curve-style': 'unbundled-bezier',
                'line-style': 'dashed',
                'line-dash-pattern': [6, 4],
                'line-color': '#c4b5fd',
                'target-arrow-color': '#c4b5fd',
                'line-opacity': 0.75,
                width: 1.5,
                label: 'data(label)',
                color: '#ddd6fe',
                'font-family': 'JetBrains Mono, ui-monospace, monospace',
                'font-size': 9,
                'text-background-color': '#0f1017',
                'text-background-opacity': 0.9,
                'text-background-padding': 2,
                'text-background-shape': 'roundrectangle',
                'text-rotation': 'autorotate',
                'min-zoomed-font-size': 5,
            },
        },
        { selector: 'node[kind = "manual"]', style: { 'border-style': 'double', 'border-width': 3 } },
        {
            selector: 'node.link-from',
            style: { 'underlay-color': '#c4b5fd', 'underlay-opacity': 0.4, 'underlay-padding': 9 },
        },
        { selector: '.is-hidden', style: { display: 'none' } },
        { selector: '.faded', style: { opacity: 0.2 } },
        { selector: 'node[status = "false_positive"].faded', style: { opacity: 0.1 } },
    ];
}
