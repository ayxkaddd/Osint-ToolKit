// Which domains of an NS lookup are run by the same person/group.
// Pure helpers: RDAP parsing, signal extraction (WHOIS + web fingerprints) and grouping.

const NsAttribution = (() => {
    const REDACTED = /redacted|privacy|private|withheld|not disclosed|protected|proxy|gdpr|masked|anonymi|contact the registrar|statutory|on behalf of|whoisguard/i;

    // ---------------- RDAP ----------------
    function vcardFields(entity) {
        const card = (entity.vcardArray && entity.vcardArray[1]) || [];
        const out = {};
        for (const [name, params, , value] of card) {
            if (name === 'fn') out.name = value;
            else if (name === 'org') out.org = Array.isArray(value) ? value.join(' ') : value;
            else if (name === 'email' && !out.email) out.email = String(value).replace(/^mailto:/i, '');
            else if (name === 'tel' && !out.phone && !(params && [].concat(params.type || []).includes('fax'))) out.phone = String(value).replace(/^tel:/i, '');
            else if (name === 'adr') {
                const parts = Array.isArray(value) ? value.flat().filter(Boolean) : [];
                out.address = (params && params.label) || parts.join(', ');
                out.country = (params && params.cc) || (Array.isArray(value) ? value[6] : '') || out.country;
            }
        }
        return out;
    }

    function parseRdap(raw) {
        let data = raw;
        if (typeof raw === 'string') {
            try { data = JSON.parse(raw); } catch (e) { return null; }
        }
        if (!data || typeof data !== 'object' || (!data.ldhName && !data.entities)) return null;
        const events = {};
        (data.events || []).forEach(e => { events[e.eventAction] = e.eventDate; });
        const out = {
            domain: (data.ldhName || '').toLowerCase(),
            registrar: null, registrar_iana: null, abuse_email: null, abuse_phone: null,
            created: events.registration || null,
            updated: events['last changed'] || null,
            expires: events.expiration || null,
            statuses: data.status || [],
            nameservers: (data.nameservers || []).map(n => (n.ldhName || '').toLowerCase()).filter(Boolean),
            dnssec: data.secureDNS ? Boolean(data.secureDNS.delegationSigned) : null,
            contacts: [],
        };
        const walk = (entities) => (entities || []).forEach(entity => {
            const roles = entity.roles || [];
            const fields = vcardFields(entity);
            if (roles.includes('registrar')) {
                out.registrar = fields.name || fields.org || entity.handle;
                const iana = (entity.publicIds || []).find(p => /iana/i.test(p.type || ''));
                out.registrar_iana = iana ? iana.identifier : null;
            } else if (roles.includes('abuse')) {
                out.abuse_email = out.abuse_email || fields.email || null;
                out.abuse_phone = out.abuse_phone || fields.phone || null;
            } else if (roles.some(r => ['registrant', 'administrative', 'technical', 'billing'].includes(r))) {
                out.contacts.push({ roles, ...fields });
            }
            walk(entity.entities);
        });
        walk(data.entities);

        // Registrars put their own phone/email into redacted contacts (Cloudflare does):
        // those say nothing about the owner. A contact is real only with a real name,
        // organisation or email of its own.
        const registrarValues = new Set();
        const collect = (entities) => (entities || []).forEach(entity => {
            if ((entity.roles || []).some(r => r === 'registrar' || r === 'abuse')) {
                const f = vcardFields(entity);
                [f.email, f.phone].filter(Boolean).forEach(v => registrarValues.add(String(v).toLowerCase()));
            }
            collect(entity.entities);
        });
        collect(data.entities);
        const real = (v) => v && !REDACTED.test(v) && !registrarValues.has(String(v).toLowerCase());
        // Some registrars put a contact-form URL where the email goes
        const isEmail = (v) => /^[^\s@/]+@[^\s@/]+\.[a-z]{2,}$/i.test(String(v || ''));
        out.contacts = out.contacts.map(c => {
            const contact = { ...c, email: real(c.email) && isEmail(c.email) ? c.email : null, phone: real(c.phone) ? c.phone : null };
            contact.redacted = !(real(c.name) || real(c.org) || contact.email);
            if (contact.redacted) contact.phone = null;  // a phone alone on a redacted record is the proxy's
            return contact;
        });
        return out;
    }

    // ---------------- signals ----------------
    const GENERIC_TITLES = /^(index of|403 forbidden|404 not found|not found|forbidden|just a moment|attention required|welcome to nginx|apache2? .*default page|it works|default page|site not found|domain (is )?for sale|this domain|parked|coming soon|under construction|account suspended|web server's default page|access denied)/i;
    const TRACKER_LABELS = {
        google_analytics: 'Google Analytics', google_analytics_ua: 'Google Analytics (UA)', google_tag_manager: 'Google Tag Manager',
        adsense: 'AdSense', yandex_metrika: 'Yandex Metrika', facebook_pixel: 'Facebook pixel', hotjar: 'Hotjar',
        email: 'Email on the site', telegram: 'Telegram link on the site',
    };

    const hostOf = (url) => { try { return new URL(url).hostname.replace(/^www\./, ''); } catch (e) { return null; } };

    // whois: {domain: parsedRdap|null}, web: {domain: fingerprint}
    function buildSignals(whois, web) {
        const buckets = new Map();
        const add = (kind, label, strength, value, domain, display) => {
            if (!value) return;
            const key = `${kind}\u0000${String(value).toLowerCase()}`;
            if (!buckets.has(key)) buckets.set(key, { kind, label, strength, value: display || String(value), domains: new Set() });
            buckets.get(key).domains.add(domain);
        };

        Object.entries(whois || {}).forEach(([domain, w]) => {
            if (!w) return;
            (w.contacts || []).filter(c => !c.redacted).forEach(c => {
                if (c.email && !REDACTED.test(c.email)) add('whois_email', 'WHOIS contact email', 'strong', c.email, domain);
                if (c.phone && !REDACTED.test(c.phone)) add('whois_phone', 'WHOIS contact phone', 'strong', c.phone, domain);
                const who = c.org && !REDACTED.test(c.org) ? c.org : (c.name && !REDACTED.test(c.name) ? c.name : null);
                if (who) add('whois_owner', 'WHOIS registrant', 'strong', who, domain);
            });
            if (w.registrar && w.created) add('registered_together', 'Registered the same day at the same registrar', 'medium', `${w.registrar} · ${w.created.slice(0, 10)}`, domain);
            if (w.registrar) add('registrar', 'Registrar', 'weak', w.registrar, domain);
        });

        Object.entries(web || {}).forEach(([domain, f]) => {
            if (!f) return;
            Object.entries(f.trackers || {}).forEach(([kind, ids]) =>
                ids.forEach(id => add(`tracker_${kind}`, TRACKER_LABELS[kind] || kind, 'strong', id, domain)));
            const target = hostOf(f.final_url);
            if (target && target !== domain && target !== `www.${domain}`) add('redirect', 'Redirects to the same site', 'strong', target, domain);
            if (f.cert && f.cert.sha256) {
                const sans = (f.cert.sans || []).map(s => s.toLowerCase().replace(/^\*\./, ''));
                add('cert', 'Same TLS certificate', 'cert', f.cert.sha256, domain, `${f.cert.subject || '?'} (${f.cert.issuer || 'unknown issuer'})`);
                const bucket = buckets.get(`cert\u0000${f.cert.sha256.toLowerCase()}`);
                bucket.sans = [...new Set([...(bucket.sans || []), ...sans])];
            }
            if (f.body_sha256) add('body', 'Identical page', 'medium', f.body_sha256, domain, f.title ? `"${f.title}"` : f.body_sha256.slice(0, 16));
            if (f.favicon) add('favicon', 'Same favicon', 'medium', f.favicon, domain, `mmh3 ${f.favicon}`);
            if (f.title && !GENERIC_TITLES.test(f.title)) add('title', 'Same page title', 'medium', f.title, domain);
            (f.ips || []).forEach(ip => add('ip', 'Same IP address', 'weak', ip, domain));
            if (f.jarm) add('jarm', 'Same TLS server config (JARM)', 'weak', f.jarm, domain, f.jarm.slice(0, 20) + '…');
            const stack = (f.tech || []).map(t => t.split(':')[0]).sort().join(', ');
            if (stack) add('tech', 'Same technology stack', 'weak', stack, domain);
        });

        const answered = new Set([...Object.keys(web || {}), ...Object.keys(whois || {}).filter(d => whois[d])]).size || 1;
        const commonAt = Math.max(5, Math.ceil(answered * 0.4));
        const signals = [];
        for (const b of buckets.values()) {
            const domains = [...b.domains].sort();
            if (domains.length < 2) continue;
            let strength = b.strength;
            if (b.kind === 'cert') {
                // A certificate naming several of these domains is one owner's; a shared
                // hosting default cert (naming none of them) says little
                const named = domains.filter(d => (b.sans || []).some(s => s === d || d.endsWith('.' + s)));
                strength = named.length >= 2 ? 'strong' : 'weak';
            }
            const common = strength === 'medium' && domains.length >= commonAt;
            signals.push({ kind: b.kind, label: b.label, strength, value: b.value, domains, common });
        }
        const order = { strong: 0, medium: 1, weak: 2 };
        return signals.sort((a, b) => order[a.strength] - order[b.strength] || b.domains.length - a.domains.length);
    }

    // Domains joined by strong signals, or by medium ones that aren't common to the whole set
    function clusters(signals) {
        const parent = new Map();
        const find = (x) => { while (parent.get(x) !== x) { parent.set(x, parent.get(parent.get(x))); x = parent.get(x); } return x; };
        const union = (a, b) => { parent.set(find(a), find(b)); };
        const linking = signals.filter(s => s.strength === 'strong' || (s.strength === 'medium' && !s.common));
        linking.forEach(s => s.domains.forEach(d => { if (!parent.has(d)) parent.set(d, d); }));
        linking.forEach(s => s.domains.slice(1).forEach(d => union(s.domains[0], d)));
        const groups = new Map();
        for (const d of parent.keys()) {
            const root = find(d);
            if (!groups.has(root)) groups.set(root, new Set());
            groups.get(root).add(d);
        }
        return [...groups.values()].filter(g => g.size > 1).map(set => {
            const domains = [...set].sort();
            const reasons = linking.filter(s => s.domains.some(d => set.has(d)));
            const strong = reasons.filter(r => r.strength === 'strong').length;
            return { domains, reasons, confidence: strong >= 2 ? 'high' : strong === 1 ? 'likely' : 'possible' };
        }).sort((a, b) => ({ high: 0, likely: 1, possible: 2 }[a.confidence] - { high: 0, likely: 1, possible: 2 }[b.confidence]) || b.domains.length - a.domains.length);
    }

    return { parseRdap, buildSignals, clusters, REDACTED };
})();
window.NsAttribution = NsAttribution;
