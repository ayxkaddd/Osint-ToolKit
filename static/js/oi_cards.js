// OSINT Industries result cards, shared by the OSINT Industries page and saved results.
// Cards come from services/oi_service.py:normalize_oi.

function oiFieldValue(value) {
    if (typeof value === 'boolean') return value ? 'yes' : 'no';
    if (typeof value === 'number') return value.toLocaleString();
    return String(value);
}

function oiCard(card) {
    const picture = safeUrl(card.picture);
    const profile = safeUrl(card.profile_url);
    const website = card.website ? safeUrl(/^https?:/i.test(card.website) ? card.website : `https://${card.website}`) : '';
    const chips = [
        card.username ? pivotChip('username', String(card.username)) : '',
        card.email ? pivotChip('email', String(card.email)) : '',
        card.phone ? pivotChip('phone', String(card.phone)) : '',
    ].join('');
    const meta = card.breach
        ? [card.created && `breached ${card.created}`]
        : [card.location, card.age && `age ${card.age}`, card.gender, card.created && `created ${card.created}`, card.last_seen && `last seen ${card.last_seen}`];
    const metaText = meta.filter(Boolean).map(v => escapeHtml(v)).join(' · ');
    const title = card.name && card.name !== card.module ? card.name : '';
    const fields = card.fields || [];
    return `
        <div class="bg-gray-950/60 rounded-lg p-4 border ${card.breach ? 'border-red-900/60' : 'border-gray-800'} min-w-0">
            <div class="flex items-start gap-3">
                ${picture ? `<img src="${escapeAttr(picture)}" alt="" loading="lazy" referrerpolicy="no-referrer" class="w-12 h-12 rounded-lg object-cover bg-gray-800 shrink-0" onerror="this.remove()">` : ''}
                <div class="min-w-0 flex-1">
                    <div class="flex items-center justify-between gap-2">
                        <span class="text-xs uppercase tracking-wide ${card.breach ? 'text-red-300' : 'text-purple-300'} truncate">${card.breach ? 'Breach · ' : ''}${escapeHtml(card.module)}</span>
                        <span class="flex items-center gap-2 shrink-0">
                            ${website ? `<a href="${escapeAttr(website)}" target="_blank" rel="noopener noreferrer" class="text-xs text-blue-400 hover:underline">site</a>` : ''}
                            ${profile ? `<a href="${escapeAttr(profile)}" target="_blank" rel="noopener noreferrer" class="text-xs text-blue-400 hover:underline">profile</a>` : ''}
                        </span>
                    </div>
                    ${title ? `<div class="text-white font-medium truncate">${escapeHtml(title)}</div>` : ''}
                    ${metaText ? `<div class="text-xs text-gray-500 mt-0.5">${metaText}</div>` : ''}
                    ${card.category && !card.breach ? `<div class="text-[11px] text-gray-600">${escapeHtml(card.category)}</div>` : ''}
                </div>
            </div>
            ${chips ? `<div class="flex flex-wrap gap-1.5 mt-2">${chips}</div>` : ''}
            ${card.bio && !card.breach ? `<p class="text-xs text-gray-400 mt-2 break-words">${escapeHtml(card.bio)}</p>` : ''}
            ${fields.length ? `<div class="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-xs">${fields.slice(0, 12).map(f =>
                `<div class="text-gray-500 truncate">${escapeHtml(f.label)}</div><div class="text-gray-300 break-words">${escapeHtml(oiFieldValue(f.value))}</div>`).join('')}</div>` : ''}
        </div>`;
}

function oiCardsHtml(modules, query) {
    const found = (modules || []).filter(m => m.registered !== false);
    if (!found.length) return '<p class="text-sm text-gray-400">No accounts found.</p>';
    const breaches = found.filter(m => m.breach).length;
    const accounts = found.length - breaches;
    const summary = [
        accounts && `${accounts} account${accounts === 1 ? '' : 's'}`,
        breaches && `<span class="text-red-300">${breaches} breach${breaches === 1 ? '' : 'es'}</span>`,
    ].filter(Boolean).join(' · ');
    return `
        <div class="text-sm text-gray-300 mb-4">${summary}${query ? ` for <span class="text-white">${escapeHtml(query)}</span>` : ''}</div>
        <div class="grid grid-cols-1 md:grid-cols-2 gap-3">${found.map(oiCard).join('')}</div>`;
}
