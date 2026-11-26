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

// Cards: what a lookup said about one thing (services/investigations/cards.py)
export const CARD_KINDS = {
    account: { label: 'Account', plural: 'Accounts', color: '#a78bfa', icon: 'circle-user-round' },
    person: { label: 'Person', plural: 'People', color: '#f472b6', icon: 'users' },
    breach: { label: 'Breach', plural: 'Breaches', color: '#f87171', icon: 'shield-alert' },
    registration: { label: 'Registration', plural: 'Registrations', color: '#fbbf24', icon: 'file-badge' },
    network: { label: 'Network', plural: 'Networks', color: '#22d3ee', icon: 'network' },
    place: { label: 'Place', plural: 'Places', color: '#4ade80', icon: 'map-pin' },
    mention: { label: 'Mention', plural: 'Mentions', color: '#94a3b8', icon: 'message-square-quote' },
    document: { label: 'Document', plural: 'Documents', color: '#9ca3af', icon: 'file-text' },
    record: { label: 'Record', plural: 'Records', color: '#9ca3af', icon: 'file-text' },
};

// Facts two cards share: a node that links them
export const FACT_KINDS = {
    password: { label: 'Password', color: '#f87171', icon: 'key-round' },
    hash: { label: 'Password hash', color: '#fb923c', icon: 'hash' },
    address: { label: 'Address', color: '#4ade80', icon: 'house' },
    dob: { label: 'Birth date', color: '#f472b6', icon: 'cake' },
    city: { label: 'City', color: '#4ade80', icon: 'building-2' },
};

// What a card's badge says about a breach
export const FLAG_NAMES = {
    password: 'password',
    hash: 'password hash',
    address: 'address',
    dob: 'birth date',
    phone: 'phone',
    card: 'bank card',
    id: 'ID number',
    tor: 'Tor',
    admin: 'admin',
};

export const cardColor = (kind) => CARD_KINDS[kind]?.color || '#9ca3af';

// Not drawn: hidden or taken off by the analyst, left out by a filter, outside the focus
export const OFF = '.is-hidden, .filtered, .unfocused';

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

// Edges to cards and from them, by what the card is
const EDGE_COLORS = {
    account: '#7c6bb8',
    person: '#b0628f',
    breach: '#b45454',
    registration: '#a5843a',
    network: '#2b8796',
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
        if (!data.open && data.hidden) badge(pillBadge(`+${data.hidden}`, '#6d28d9'), 'right');
    } else if (data.kind === 'card') {
        // the picture (or the kind's icon) on the left, the text beside it (stylesheet)
        const side = { w: '34px', h: '34px', x: '0%', ox: 9 };
        add(iconUri(CARD_KINDS[data.card]?.icon || 'file-text', data.color, 0.85), {
            ...side,
            w: '20px',
            h: '20px',
            ox: 16,
        });
        if (data.picture) add(data.picture, { ...side, fit: 'cover' });
        if (data.flags?.includes('password')) badge(iconBadge('key-round', '#b91c1c'), 'top-right');
        else if (data.flags?.length && data.card === 'breach') badge(iconBadge('shield-alert', '#9a3412'), 'top-right');
        if (data.found_by > 1) badge(pillBadge(`×${data.found_by}`, '#4c1d95'), 'top-left');
        if (!data.open && data.hidden) badge(pillBadge(`+${data.hidden}`, '#6d28d9'), 'right');
    } else if (data.kind === 'fact') {
        add(iconUri(FACT_KINDS[data.fact]?.icon || 'link', data.color, 0.9), { w: '50%', h: '50%' });
        badge(pillBadge(String(data.count), '#374151'), 'top-right');
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
        // a group of accounts shows one of their pictures
        if (data.pictures?.length) add(data.pictures[0], { w: '100%', h: '100%', fit: 'cover' });
        else add(iconUri(CARD_KINDS[data.card]?.icon || 'layers', data.color, 0.75));
        badge(pillBadge(data.open ? '−' : String(data.count), data.open ? '#1f2937' : '#6d28d9'), 'top-right');
    } else if (data.kind === 'pending') {
        add(
            iconUri(
                data.status === 'failed' ? 'triangle-alert' : 'search',
                data.status === 'failed' ? '#fca5a5' : '#c4b5fd',
                0.9
            ),
            {
                w: '16px',
                h: '16px',
                x: '0%',
                ox: 12,
            }
        );
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
                // no label when it would be too small to read: a node's from about zoom 0.45
                // (decided when drawing: zooming restyles nothing)
                'min-zoomed-font-size': 5,
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
        // a card: a rounded box, its picture on the left, title and subtitle beside it
        {
            selector: 'node[kind = "card"]',
            style: {
                shape: 'round-rectangle',
                'corner-radius': 10,
                'background-color': '#151621',
                'border-width': 1.5,
                'border-color': 'data(color)',
                'border-opacity': 0.75,
                color: '#e5e7eb',
                'font-size': 11,
                'text-valign': 'center',
                'text-halign': 'center',
                'text-margin-y': 0,
                'text-margin-x': 22,
                'text-wrap': 'wrap',
                'text-max-width': 'data(textWidth)',
                'text-justification': 'left',
                'line-height': 1.4,
                'text-outline-width': 0,
                // a card's title reads further out than an identifier's value (about zoom 0.3)
                'min-zoomed-font-size': 3.5,
            },
        },
        { selector: 'node[kind = "card"][card = "breach"]', style: { 'background-color': '#1d1418' } },
        { selector: 'node[kind = "card"]:selected', style: { 'underlay-shape': 'round-rectangle' } },
        // a fact two records share: a small diamond
        {
            selector: 'node[kind = "fact"]',
            style: {
                shape: 'diamond',
                'background-color': '#0f1017',
                'border-color': 'data(color)',
                'font-size': 10,
                color: '#e5e7eb',
            },
        },
        // a lookup still running: a purple arc turning round it (pivot.js moves the dash)
        {
            selector: 'node[kind = "pending"]',
            style: {
                shape: 'round-rectangle',
                'corner-radius': 12,
                'background-color': '#0f1017',
                'border-color': '#a855f7',
                'border-width': 2,
                'border-style': 'dashed',
                'border-dash-pattern': [26, 70],
                color: '#ddd6fe',
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
        {
            selector: 'node[kind = "pending"][status = "failed"]',
            style: { 'border-color': '#ef4444', 'border-style': 'solid', color: '#fca5a5' },
        },
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
                width: 1.8,
                'line-color': '#64748b',
                'line-opacity': 0.75,
                'curve-style': 'round-taxi',
                'taxi-direction': 'rightward',
                'taxi-turn': '45%',
                'taxi-radius': 14,
                'target-arrow-shape': 'triangle',
                'target-arrow-color': '#64748b',
                'arrow-scale': 0.8,
            },
        },
        // links to a card and from it take the card's colour
        ...Object.entries(EDGE_COLORS).map(([kind, color]) => ({
            selector: `edge[card = "${kind}"]`,
            style: { 'line-color': color, 'target-arrow-color': color },
        })),
        {
            selector: 'edge[kind = "fact"]',
            style: {
                'line-style': 'dashed',
                'line-dash-pattern': [4, 4],
                'line-color': '#a16207',
                'target-arrow-shape': 'none',
            },
        },
        // what a link says ("in breach", "named in profile"), when close enough to read it
        {
            selector: 'edge[label]',
            style: {
                label: 'data(label)',
                color: '#cbd5e1',
                'font-family': 'JetBrains Mono, ui-monospace, monospace',
                'font-size': 9,
                'text-background-color': '#0f1017',
                'text-background-padding': 2,
                'text-background-shape': 'roundrectangle',
                'text-background-opacity': 0.9,
                // what a link says, only close enough to read it (about zoom 0.9)
                'min-zoomed-font-size': 8,
            },
        },
        // the web layout: straight links
        { selector: 'edge.web', style: { 'curve-style': 'straight' } },
        // links outside the tree (an identifier found in two branches): a plain curve
        {
            selector: 'edge.cross',
            style: {
                'curve-style': 'unbundled-bezier',
                'line-style': 'dashed',
                'line-dash-pattern': [6, 4],
                width: 1.4,
                'line-opacity': 0.6,
            },
        },
        // a link into a grid: the grid's frame has one link for all (lanes.js); shown on hover
        { selector: 'edge.in-grid', style: { 'line-opacity': 0, 'target-arrow-shape': 'none', label: '' } },
        {
            selector: 'edge.lit',
            style: {
                'line-color': 'data(color)',
                'target-arrow-color': 'data(color)',
                'line-opacity': 1,
                width: 2.6,
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
                'text-background-padding': 2,
                'text-background-shape': 'roundrectangle',
                'text-rotation': 'autorotate',
                'text-background-opacity': 0.9,
            },
        },
        // a username that a found profile names or links to (the search followed it)
        {
            selector: 'edge[kind = "clue"]',
            style: {
                'line-style': 'dashed',
                'line-dash-pattern': [7, 5],
                'line-color': '#fbbf24',
                'target-arrow-color': '#fbbf24',
                'line-opacity': 0.85,
                width: 2,
                label: 'data(label)',
                color: '#fde68a',
                'font-family': 'JetBrains Mono, ui-monospace, monospace',
                'font-size': 9,
                'text-background-color': '#0f1017',
                'text-background-padding': 2,
                'text-background-shape': 'roundrectangle',
                'text-background-opacity': 0.9,
            },
        },
        { selector: 'node[kind = "manual"]', style: { 'border-style': 'double', 'border-width': 3 } },
        {
            selector: 'node.link-from',
            style: { 'underlay-color': '#c4b5fd', 'underlay-opacity': 0.4, 'underlay-padding': 9 },
        },
        { selector: '.is-hidden, .filtered, .unfocused', style: { display: 'none' } },
        // search: what matches glows, the rest steps back
        {
            selector: 'node.match',
            style: { 'underlay-color': '#a855f7', 'underlay-opacity': 0.45, 'underlay-padding': 9 },
        },
        { selector: '.search-dim', style: { opacity: 0.18 } },
        // on the way to what a filter shows, without matching it
        { selector: 'node.filter-dim', style: { opacity: 0.4 } },
        // a path between two nodes
        { selector: 'node.on-path', style: { 'border-color': '#c4b5fd', 'border-width': 3 } },
        {
            selector: 'edge.on-path',
            style: { 'line-color': '#c4b5fd', 'target-arrow-color': '#c4b5fd', 'line-opacity': 1, width: 2.5 },
        },
        { selector: '.path-dim', style: { opacity: 0.15 } },
        // the neighbours of the node under the pointer
        { selector: 'node.near', style: { 'border-width': 3 } },
    ];
}
