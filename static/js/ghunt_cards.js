// GHunt results, shared by the GHunt page (static/js/services/ghunt.js) and saved
// results on the investigation page (result_renderers.js). One renderer per GHunt
// module, chosen from the shape of GHunt's JSON output:
//   account (email / Gaia ID)  {PROFILE_CONTAINER: {profile, maps, play_games, calendar}}
//   drive                      {file, source_app, users, comments}
//   geolocate (BSSID)          {latitude, longitude, accuracy, address, pretty_address}
//   spiderdal (domain)         {sites, packages}

const GHUNT_USER_TYPES = {
    GOOGLE_USER: ['Google account', 'A regular Google account'],
    GOOGLE_ONE_USER: ['Google One', 'Pays for Google One storage'],
    GOOGLE_APPS_USER: ['Workspace', 'Account of an organization (Google Workspace)'],
    OWNER_USER_TYPE_UNKNOWN: ['Unknown type', ''],
};

function ghuntKind(data) {
    if (!data || typeof data !== 'object') return 'unknown';
    if (data.PROFILE_CONTAINER || data.profile) return 'account';
    if ('latitude' in data || 'pretty_address' in data) return 'geolocate';
    if ('sites' in data || 'packages' in data) return 'spiderdal';
    if ('file' in data || 'users' in data) return 'drive';
    return 'unknown';
}

function ghuntDate(value) {
    if (!value) return '';
    const parsed = new Date(String(value).replace(/\//g, '-').replace(' (UTC)', 'Z').replace(' ', 'T'));
    if (isNaN(parsed)) return escapeHtml(value);
    const days = Math.floor((Date.now() - parsed) / 86400000);
    const ago = days <= 0 ? 'today' : days === 1 ? 'yesterday' : days < 60 ? `${days} days ago`
        : days < 730 ? `${Math.round(days / 30)} months ago` : `${Math.round(days / 365)} years ago`;
    return `<span title="${escapeAttr(value)}">${escapeHtml(parsed.toLocaleDateString())} <span class="text-gray-500">(${ago})</span></span>`;
}

function ghuntSection(icon, title, body, extra = '') {
    return `
        <section class="card !p-4">
            <h3 class="flex items-center gap-2 text-sm font-semibold text-gray-200 mb-3">
                <i data-lucide="${icon}" class="w-4 h-4 text-purple-400"></i>${escapeHtml(title)}${extra}
            </h3>
            ${body}
        </section>`;
}

function ghuntStat(label, value) {
    return `<div class="bg-gray-900/70 border border-gray-800 rounded-lg px-3 py-2 min-w-0">
        <div class="text-lg font-bold text-white tabular-nums">${escapeHtml(Number(value).toLocaleString())}</div>
        <div class="text-xs text-gray-400 truncate">${escapeHtml(label)}</div></div>`;
}

function ghuntBadge(text, cls = 'bg-gray-800 text-gray-300', title = '') {
    return `<span class="px-2 py-0.5 rounded-md text-xs ${cls}" ${title ? `title="${escapeAttr(title)}"` : ''}>${escapeHtml(text)}</span>`;
}

function ghuntRawJson(data) {
    return `
        <details class="text-sm">
            <summary class="cursor-pointer text-gray-500 hover:text-gray-300 select-none">Raw GHunt output</summary>
            <pre class="mt-2 p-3 bg-gray-950/70 border border-gray-800 rounded-lg text-xs text-gray-300 overflow-auto max-h-96">${escapeHtml(JSON.stringify(data, null, 2))}</pre>
        </details>`;
}

// Profile photo with the same reverse image search buttons as username search
function ghuntAvatar(url, isDefault) {
    const src = safeUrl(url);
    if (!src) return `<div class="w-24 h-24 rounded-full bg-gray-800 flex items-center justify-center shrink-0"><i data-lucide="user" class="w-10 h-10 text-gray-500"></i></div>`;
    const encoded = encodeURIComponent(src);
    return `
        <div class="relative shrink-0 group">
            <a href="${escapeAttr(src)}" target="_blank" rel="noopener noreferrer" title="Open the profile photo">
                <img src="${escapeAttr(src)}" alt="" referrerpolicy="no-referrer" class="w-24 h-24 rounded-full object-cover border-2 ${isDefault ? 'border-gray-700' : 'border-purple-500/60'}">
            </a>
            ${isDefault ? '' : `
            <div class="absolute -bottom-1 left-1/2 -translate-x-1/2 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                <a href="https://lens.google.com/uploadbyurl?url=${encoded}" target="_blank" rel="noopener noreferrer" title="Google reverse image search"
                   class="w-7 h-7 rounded-full bg-gray-900 border border-gray-700 flex items-center justify-center text-gray-300 hover:text-white"><i class="fab fa-google text-xs"></i></a>
                <a href="https://yandex.com/images/search?rpt=imageview&url=${encoded}" target="_blank" rel="noopener noreferrer" title="Yandex reverse image search"
                   class="w-7 h-7 rounded-full bg-gray-900 border border-gray-700 flex items-center justify-center text-gray-300 hover:text-white"><i class="fas fa-search text-xs"></i></a>
            </div>`}
        </div>`;
}

function ghuntAccountHtml(data) {
    const container = data.PROFILE_CONTAINER || data;
    const profile = container.profile || {};
    const pick = (obj) => (obj && (obj.PROFILE || Object.values(obj)[0])) || {};
    const name = pick(profile.names).fullname || pick(profile.names).displayName || '';
    const email = pick(profile.emails).value || '';
    const gaiaId = profile.personId || '';
    const photo = pick(profile.profilePhotos);
    const cover = pick(profile.coverPhotos);
    const lastEdit = pick(profile.sourceIds).lastUpdated;
    const userTypes = pick(profile.profileInfos).userTypes || [];
    const apps = pick(profile.inAppReachability).apps || [];
    const extended = profile.extendedData || {};
    const maps = container.maps || {};
    const mapsProfile = maps.profile || {};
    const stats = Object.entries(maps.stats || {});
    const shownStats = stats.filter(([, n]) => Number(n) > 0);
    const mapsUrl = gaiaId ? `https://www.google.com/maps/contrib/${encodeURIComponent(gaiaId)}/reviews` : '';

    const badges = [
        mapsProfile.local_guide ? ghuntBadge(`${mapsProfile.local_guide}${mapsProfile.local_guide_points ? ' · ' + mapsProfile.local_guide_points : ''}`, 'bg-amber-500/15 text-amber-300', 'Google Maps Local Guide') : '',
        ...userTypes.map(t => { const [label, tip] = GHUNT_USER_TYPES[t] || [t.replace(/_/g, ' ').toLowerCase(), '']; return ghuntBadge(label, 'bg-sky-500/15 text-sky-300', tip); }),
        extended.gplusData && extended.gplusData.isEntrepriseUser ? ghuntBadge('Enterprise user', 'bg-purple-500/15 text-purple-300') : '',
        photo.url ? ghuntBadge(photo.isDefault ? 'Default photo' : 'Custom photo', photo.isDefault ? 'bg-gray-800 text-gray-400' : 'bg-emerald-500/15 text-emerald-300') : '',
    ].filter(Boolean).join('');

    const header = `
        <section class="card !p-0 overflow-hidden">
            ${cover.url && !cover.isDefault ? `<a href="${escapeAttr(safeUrl(cover.url))}" target="_blank" rel="noopener noreferrer" title="Open the cover photo">
                <img src="${escapeAttr(safeUrl(cover.url))}" alt="" referrerpolicy="no-referrer" class="w-full h-32 object-cover"></a>` : ''}
            <div class="p-5 flex flex-col sm:flex-row gap-5">
                ${ghuntAvatar(photo.url, photo.isDefault)}
                <div class="min-w-0 flex-1 space-y-2">
                    <h2 class="text-2xl font-bold text-white break-words">${name ? escapeHtml(name) : '<span class="text-gray-500 font-normal text-lg">Name not public</span>'}</h2>
                    <div class="flex flex-wrap items-center gap-2 text-sm">
                        ${email ? `<span class="text-gray-500"><i data-lucide="mail" class="w-3.5 h-3.5 inline mr-1"></i></span>${pivotText('email', email)}` : ''}
                        ${gaiaId ? `<span class="text-gray-500 ml-2" title="Gaia ID: Google's permanent ID of the account"><i data-lucide="hash" class="w-3.5 h-3.5 inline mr-1"></i>Gaia</span>${pivotText('gaia_id', gaiaId)}` : ''}
                        ${name ? `<span class="text-gray-500 ml-2"><i data-lucide="user" class="w-3.5 h-3.5 inline mr-1"></i></span>${pivotText('text', name)}` : ''}
                    </div>
                    ${badges ? `<div class="flex flex-wrap gap-1.5">${badges}</div>` : ''}
                    ${lastEdit ? `<div class="text-xs text-gray-400"><i data-lucide="clock" class="w-3.5 h-3.5 inline mr-1"></i>Profile last changed ${ghuntDate(lastEdit)}</div>` : ''}
                    ${mapsUrl ? `<div class="pt-1"><a href="${escapeAttr(mapsUrl)}" target="_blank" rel="noopener noreferrer"
                        class="inline-flex items-center gap-1.5 text-sm text-purple-300 hover:text-white"><i data-lucide="map" class="w-4 h-4"></i>Google Maps profile and reviews</a></div>` : ''}
                </div>
            </div>
        </section>`;

    const mapsBody = shownStats.length
        ? `<div class="grid grid-cols-2 sm:grid-cols-4 gap-2">${shownStats.map(([k, n]) => ghuntStat(k, n)).join('')}</div>
           ${stats.length > shownStats.length ? `<p class="text-xs text-gray-500 mt-2">Nothing in: ${escapeHtml(stats.filter(([, n]) => !Number(n)).map(([k]) => k).join(', '))}</p>` : ''}`
        : `<p class="text-sm text-gray-400">${maps.stats ? 'No public reviews, ratings or photos on Google Maps.' : 'No Google Maps data.'}</p>`;

    const servicesBody = apps.length
        ? `<div class="flex flex-wrap gap-1.5">${apps.map(a => ghuntBadge(a, 'bg-gray-800 text-gray-200')).join('')}</div>
           <p class="text-xs text-gray-500 mt-2">Google services this account uses, as Google shows them to other users.</p>`
        : '<p class="text-sm text-gray-400">None visible.</p>';

    const dynamite = extended.dynamiteData || {};
    const details = [
        ['Account type', dynamite.entityType && dynamite.entityType.toLowerCase()],
        ['Workspace customer ID', dynamite.customerId],
        ['Presence (Google Chat)', dynamite.presence && dynamite.presence !== 'UNKNOWN' ? dynamite.presence.toLowerCase() : ''],
        ['Content restriction', extended.gplusData && extended.gplusData.contentRestriction],
    ].filter(([, v]) => v);
    const detailsBody = details.length
        ? `<dl class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">${details.map(([k, v]) =>
            `<dt class="text-gray-500">${escapeHtml(k)}</dt><dd class="text-gray-200 break-words">${escapeHtml(v)}</dd>`).join('')}</dl>`
        : '<p class="text-sm text-gray-400">Nothing more.</p>';

    const extraSections = [];
    if (container.play_games) extraSections.push(ghuntSection('gamepad-2', 'Play Games profile', renderValue(container.play_games)));
    if (container.calendar) {
        const events = (container.calendar.events && (container.calendar.events.items || container.calendar.events)) || [];
        extraSections.push(ghuntSection('calendar', 'Public calendar', `
            ${Array.isArray(events) && events.length ? `<div class="space-y-1.5 max-h-72 overflow-y-auto">${events.slice(0, 50).map(e => `
                <div class="text-sm"><span class="text-gray-500 text-xs mr-2">${escapeHtml(String((e.start && (e.start.date_time || e.start.date)) || '').slice(0, 16))}</span>
                ${escapeHtml(e.summary || e.title || 'Event')}</div>`).join('')}</div>` : renderValue(container.calendar.details || container.calendar)}`,
            ` <span class="text-xs font-normal text-emerald-300 ml-1">public</span>`));
    }

    return `
        <div class="space-y-4">
            ${header}
            <div class="grid gap-4 md:grid-cols-2">
                ${ghuntSection('map-pin', 'Google Maps activity', mapsBody)}
                ${ghuntSection('layout-grid', 'Google services', servicesBody)}
                ${ghuntSection('id-card', 'Account details', detailsBody)}
                ${!container.play_games ? ghuntSection('gamepad-2', 'Play Games', '<p class="text-sm text-gray-400">No public player profile.</p>') : ''}
                ${!container.calendar ? ghuntSection('calendar', 'Calendar', '<p class="text-sm text-gray-400">No public calendar.</p>') : ''}
            </div>
            ${extraSections.length ? `<div class="grid gap-4 md:grid-cols-2">${extraSections.join('')}</div>` : ''}
            ${ghuntRawJson(data)}
        </div>`;
}

function ghuntDriveHtml(data) {
    const file = data.file || {};
    const users = Array.isArray(data.users) ? data.users : [];
    const facts = [
        ['Type', file.mime_type], ['Size', file.file_size], ['Created', file.created_date], ['Modified', file.modified_date],
        ['Made with', data.source_app && (data.source_app.name || data.source_app.title)],
    ].filter(([, v]) => v);
    const userRows = users.map(u => `
        <div class="flex flex-wrap items-center gap-2 py-1.5 border-t border-gray-800 first:border-0">
            <span class="text-gray-200 font-medium">${escapeHtml(u.name || 'Unknown')}</span>
            ${u.email_address ? pivotText('email', u.email_address) : ''}
            ${u.gaia_id ? pivotText('gaia_id', u.gaia_id) : ''}
            ${u.role ? ghuntBadge(u.role) : ''}
            ${u.is_last_modifying_user ? ghuntBadge('last edited it', 'bg-amber-500/15 text-amber-300') : ''}
        </div>`).join('');
    return `
        <div class="space-y-4">
            <section class="card">
                <h2 class="text-xl font-bold text-white break-words">${escapeHtml(file.title || 'Drive file')}</h2>
                ${facts.length ? `<dl class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm mt-3">${facts.map(([k, v]) =>
                    `<dt class="text-gray-500">${escapeHtml(k)}</dt><dd class="text-gray-200 break-words">${k === 'Created' || k === 'Modified' ? ghuntDate(v) : escapeHtml(v)}</dd>`).join('')}</dl>` : ''}
                ${data.file ? '' : '<p class="text-sm text-gray-400 mt-2">The file could not be read - it may be private.</p>'}
            </section>
            ${ghuntSection('users', `People on this file (${users.length})`, users.length ? userRows : '<p class="text-sm text-gray-400">No one visible.</p>')}
            ${data.comments ? ghuntSection('message-square', 'Comments', renderValue(data.comments)) : ''}
            ${ghuntRawJson(data)}
        </div>`;
}

function ghuntGeolocateHtml(data) {
    const lat = Number(data.latitude), lon = Number(data.longitude);
    const located = Number.isFinite(lat) && Number.isFinite(lon);
    const osm = located ? `https://www.openstreetmap.org/?mlat=${lat}&mlon=${lon}#map=17/${lat}/${lon}` : '';
    const gmap = located ? `https://www.google.com/maps/search/?api=1&query=${lat},${lon}` : '';
    return `
        <div class="space-y-4">
            <section class="card">
                ${located ? `
                    <div class="flex items-start gap-4">
                        <div class="w-12 h-12 rounded-lg bg-purple-600/20 flex items-center justify-center shrink-0"><i data-lucide="map-pin" class="w-6 h-6 text-purple-300"></i></div>
                        <div class="min-w-0 space-y-1">
                            <h2 class="text-xl font-bold text-white break-words">${escapeHtml(data.pretty_address || 'Location found')}</h2>
                            <div class="text-sm text-gray-400 font-mono">${lat.toFixed(6)}, ${lon.toFixed(6)}${data.accuracy ? ` <span class="font-sans">· within about ${escapeHtml(Math.round(data.accuracy))} m</span>` : ''}</div>
                            <div class="flex flex-wrap gap-3 pt-1 text-sm">
                                <a href="${escapeAttr(osm)}" target="_blank" rel="noopener noreferrer" class="text-purple-300 hover:text-white"><i data-lucide="map" class="w-4 h-4 inline mr-1"></i>OpenStreetMap</a>
                                <a href="${escapeAttr(gmap)}" target="_blank" rel="noopener noreferrer" class="text-purple-300 hover:text-white"><i data-lucide="map" class="w-4 h-4 inline mr-1"></i>Google Maps</a>
                            </div>
                        </div>
                    </div>` : '<p class="text-gray-400">Google does not know where this Wi-Fi access point is.</p>'}
            </section>
            ${ghuntRawJson(data)}
        </div>`;
}

function ghuntSpiderdalHtml(data) {
    const sites = Object.values(data.sites || {});
    const packages = Object.values(data.packages || {});
    const host = (site) => String(site || '').replace(/^https?:\/\//, '').replace(/\/.*$/, '');
    const siteRows = sites.map(s => {
        const site = (s.asset && s.asset.site) || '';
        return `<div class="flex flex-wrap items-center gap-2 py-1.5 border-t border-gray-800 first:border-0">
            ${pivotText('domain', host(site), host(site))}
            <a href="${escapeAttr(safeUrl(site))}" target="_blank" rel="noopener noreferrer" class="text-gray-500 hover:text-white" title="Open"><i data-lucide="external-link" class="w-3.5 h-3.5"></i></a>
            ${(s.origins || []).length ? `<span class="text-xs text-gray-500">linked from ${s.origins.length} place${s.origins.length === 1 ? '' : 's'}</span>` : ''}
        </div>`;
    }).join('');
    const pkgRows = packages.map(p => {
        const name = (p.asset && p.asset.package_name) || '';
        return `<div class="py-1.5 border-t border-gray-800 first:border-0 min-w-0">
            <a href="https://play.google.com/store/apps/details?id=${encodeURIComponent(name)}" target="_blank" rel="noopener noreferrer"
               class="text-sm text-gray-200 hover:text-white font-mono">${escapeHtml(name)}</a>
            ${p.asset && p.asset.certificate ? `<div class="text-[11px] text-gray-500 font-mono break-all" title="Signing certificate (SHA-256)">${escapeHtml(p.asset.certificate)}</div>` : ''}
        </div>`;
    }).join('');
    return `
        <div class="space-y-4">
            <p class="text-sm text-gray-400">Websites and Android apps that declare each other as the same owner (Google Digital Asset Links).</p>
            <div class="grid gap-4 md:grid-cols-2">
                ${ghuntSection('globe', `Websites (${sites.length})`, sites.length ? siteRows : '<p class="text-sm text-gray-400">None found.</p>')}
                ${ghuntSection('smartphone', `Android apps (${packages.length})`, packages.length ? pkgRows : '<p class="text-sm text-gray-400">None found.</p>')}
            </div>
            ${ghuntRawJson(data)}
        </div>`;
}

function ghuntResultHtml(data) {
    switch (ghuntKind(data)) {
        case 'account': return ghuntAccountHtml(data);
        case 'drive': return ghuntDriveHtml(data);
        case 'geolocate': return ghuntGeolocateHtml(data);
        case 'spiderdal': return ghuntSpiderdalHtml(data);
        default: return renderValue(data);
    }
}
