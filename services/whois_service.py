import json
import re
from typing import Any, Dict, List, Optional
import aiohttp
from fastapi import HTTPException
from utils.config import get_setting

class WhoisService:
    def __init__(self):
        self.domain = "78.46.239.70:8000"
        self.uri = "/api/whois"
        self.whois_history_domain = "whois-history.whoisxmlapi.com"

    @property
    def wx_api_key(self):
        return get_setting("WHOIS_XML_API_KEY")

    async def _history_request(self, domain: str, mode: str) -> Dict[str, Any]:
        if not self.wx_api_key:
            raise HTTPException(status_code=400, detail="WHOIS_XML_API_KEY is not configured - add it in Settings")
        params = {'apiKey': self.wx_api_key, 'domainName': domain, 'mode': mode, 'outputFormat': 'JSON'}
        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(f'https://{self.whois_history_domain}/api/v1', params=params) as resp:
                data = await resp.json(content_type=None)
                if resp.status != 200 or (isinstance(data, dict) and data.get('messages')):
                    message = data.get('messages') if isinstance(data, dict) else None
                    raise HTTPException(status_code=resp.status if resp.status != 200 else 502,
                                        detail=f"WhoisXML: {message or 'HTTP ' + str(resp.status)}")
                return data

    async def preview_whois_history(self, domain: str) -> Dict[str, Any]:
        """How many historical records exist (free - no credits used)."""
        data = await self._history_request(domain, 'preview')
        return {'domain': domain, 'records_count': data.get('recordsCount', 0)}

    async def lookup_whois_history(self, domain: str):
        """Every archived WHOIS snapshot (uses WhoisXML credits) plus who/what changed."""
        data = await self._history_request(domain, 'purchase')
        records = data.get('records') or []
        for record in records:
            record.pop('rawText', None)  # same content as cleanText, often several KB
        data['domain'] = domain
        data['analysis'] = analyze_whois_history(records)
        return data

    async def lookup_whois(self, domain: str):
        async with aiohttp.ClientSession() as session:
            async with session.post(f'http://{self.domain}{self.uri}', json={"address": domain}) as resp:
                if resp.status != 200:
                    raise HTTPException(status_code=resp.status, detail="WHOIS lookup failed")

                data = await resp.json()
                domain_records = (data.get('records') or {}).get('domain') or {}
                domain_raw_text = domain_records.get('rawText', '{}')
                domain_parsed = self.parse_domain_json(domain_raw_text)

                # Get top-level registrar information
                top_registrar = (data.get('registrar') or {}).get('provider')

                combined_data = self.combine_whois_data(
                    domain_parsed,
                    domain_records,
                    top_registrar
                )

                combined_data['domain_raw_text'] = domain_raw_text
                return combined_data

    def parse_domain_json(self, raw_json_text: str) -> dict:
        """Parse the domain JSON data from rawText."""
        try:
            data = json.loads(raw_json_text)
            result = {}

            # Extract registrant info from entities
            for entity in data.get('entities', []):
                roles = entity.get('roles', [])
                if 'registrant' in roles:
                    vcard = entity.get('vcardArray', [])[1] if len(entity.get('vcardArray', [])) > 1 else []
                    for item in vcard:
                        if item[0] == 'org' and item[2] == 'text':
                            result['registrant'] = item[3]
                        elif item[0] == 'email' and item[2] == 'text':
                            result['email'] = item[3]

            # Extract dates
            for event in data.get('events', []):
                if event.get('eventAction') == 'registration':
                    result['creation_date'] = event.get('eventDate')
                elif event.get('eventAction') == 'expiration':
                    result['expiration_date'] = event.get('eventDate')

            # Extract registrar from entities
            for entity in data.get('entities', []):
                if 'registrar' in entity.get('roles', []):
                    vcard = entity.get('vcardArray', [])[1] if len(entity.get('vcardArray', [])) > 1 else []
                    for item in vcard:
                        if item[0] == 'org' and item[2] == 'text':
                            result['registrar'] = item[3]

            return result
        except json.JSONDecodeError:
            return {}

    def combine_whois_data(self, domain_data: Dict, structured_data: Dict, top_registrar: str) -> Dict:
        """Combine data from all sources, preferring structured data when available."""
        result = {
            'registrant': None,
            'email': None,
            'creation_date': None,
            'expiration_date': None,
            'registrar': None,
            'nameservers': [],
            'statuses': []
        }

        # Registrant
        result['registrant'] = (
            structured_data.get('registrant', {}).get('organization') or
            domain_data.get('registrant')
        )

        # The owner's email; the registrar's abuse desk is kept apart (it is the
        # same for every domain at that registrar, so it must not group domains)
        result['email'] = (
            structured_data.get('registrant', {}).get('email') or
            domain_data.get('email')
        )
        result['abuse_email'] = structured_data.get('abuse', {}).get('email')

        # Dates
        result['creation_date'] = (
            structured_data.get('registeredAt') or
            domain_data.get('creation_date')
        )
        result['expiration_date'] = (
            structured_data.get('expiresAt') or
            domain_data.get('expiration_date')
        )

        # Registrar (prioritize top-level registrar from API response)
        result['registrar'] = (
            top_registrar or
            structured_data.get('registrar') or
            domain_data.get('registrar')
        )

        # Additional fields
        result['nameservers'] = structured_data.get('nameServers', [])
        result['statuses'] = structured_data.get('statuses', [])

        # Fallback to raw text parsing for missing fields
        if not result['registrar']:
            result['registrar'] = self.parse_rawtext_for_registrar(
                structured_data.get('rawText', '')
            )

        return result

    def parse_rawtext_for_registrar(self, raw_text: str) -> str:
        """Fallback parser for registrar from raw text"""
        patterns = [
            r'Registrar:\s*([^\n]+)',
            r'registrar\":\s*{\s*\"provider\":\s*\"([^\"]+)',
            r'RegistrarName:\s*([^\n]+)'
        ]
        for pattern in patterns:
            match = re.search(pattern, raw_text, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None


# ---------------------------------------------------------------------------
# History analysis
# ---------------------------------------------------------------------------

PRIVACY_RE = re.compile(
    r"redacted|privacy|private|protect|proxy|whoisguard|withheld|not disclosed|gdpr|masked|"
    r"anonymi|data protected|contact the registrar|identity|on behalf of|statutory", re.I)
CONTACT_ROLES = {
    'registrantContact': 'registrant', 'administrativeContact': 'admin',
    'technicalContact': 'tech', 'billingContact': 'billing', 'zoneContact': 'zone',
}
CONTACT_FIELDS = ('name', 'organization', 'email', 'telephone', 'street', 'city', 'state', 'postalCode', 'country')


def _record_date(record: Dict[str, Any]) -> str:
    """When the snapshot was taken (falls back to the record's own dates)."""
    audit = record.get('audit') or {}
    for value in (audit.get('updatedDate'), record.get('updatedDateISO8601'),
                  audit.get('createdDate'), record.get('createdDateISO8601')):
        if value:
            return str(value)[:10]
    return ''


def _clean(value: Any) -> Optional[str]:
    text = str(value or '').strip()
    return text or None


def _contact(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    contact = {k: _clean(raw.get(k)) for k in CONTACT_FIELDS}
    if not any(contact.values()):
        return None
    identifying = [contact[k] for k in ('name', 'organization', 'email', 'telephone') if contact[k]]
    contact['privacy'] = bool(identifying) and all(PRIVACY_RE.search(v) for v in identifying)
    return contact


def _summary(contact: Optional[Dict[str, Any]]) -> str:
    if not contact:
        return ''
    return ' / '.join(v for v in (contact.get('name'), contact.get('organization'), contact.get('email')) if v)


def analyze_whois_history(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Everyone ever listed, registrar/name server periods and a change log."""
    snapshots = sorted(records, key=_record_date)
    contacts: Dict[tuple, Dict[str, Any]] = {}
    registrars: Dict[str, Dict[str, str]] = {}
    nameservers: Dict[str, Dict[str, str]] = {}
    timeline: List[Dict[str, Any]] = []
    previous: Optional[Dict[str, Any]] = None

    def seen(table: Dict[str, Dict[str, str]], key: str, date: str):
        entry = table.setdefault(key, {'first_seen': date, 'last_seen': date})
        if date:
            entry['first_seen'] = min(filter(None, [entry['first_seen'], date]))
            entry['last_seen'] = max(entry['last_seen'] or '', date)

    for record in snapshots:
        date = _record_date(record)
        registrar = _clean(record.get('registrarName'))
        ns = sorted({str(n).lower().rstrip('.') for n in (record.get('nameServers') or []) if n})
        state = {'registrar': registrar, 'nameservers': ns,
                 'status': sorted(set(record.get('status') or [])) if isinstance(record.get('status'), list)
                 else _clean(record.get('status'))}
        for field, role in CONTACT_ROLES.items():
            contact = _contact(record.get(field) or {})
            state[role] = _summary(contact)
            if not contact:
                continue
            key = tuple((contact.get(k) or '').lower() for k in ('name', 'organization', 'email', 'telephone'))
            entry = contacts.setdefault(key, {**contact, 'roles': [], 'first_seen': date, 'last_seen': date})
            if role not in entry['roles']:
                entry['roles'].append(role)
            if date:
                entry['first_seen'] = min(filter(None, [entry['first_seen'], date]))
                entry['last_seen'] = max(entry['last_seen'] or '', date)
        if registrar:
            seen(registrars, registrar, date)
        for n in ns:
            seen(nameservers, n, date)

        changes = []
        if previous is not None:
            for key in ('registrar', 'nameservers', 'registrant', 'admin', 'tech', 'status'):
                before, after = previous.get(key), state.get(key)
                if before != after and (before or after):
                    fmt = lambda v: ', '.join(v) if isinstance(v, list) else (v or '(none)')
                    changes.append({'field': key, 'from': fmt(before), 'to': fmt(after)})
        if changes or previous is None:
            timeline.append({
                'date': date,
                'first': previous is None,
                'registrar': registrar,
                'registrant': state.get('registrant'),
                'created': _clean(record.get('createdDateISO8601')),
                'expires': _clean(record.get('expiresDateISO8601')),
                'changes': changes,
            })
        previous = state

    created = sorted(filter(None, (_clean(r.get('createdDateISO8601')) for r in records)))
    ordered = lambda table: [{'name': k, **v} for k, v in sorted(table.items(), key=lambda kv: kv[1]['first_seen'] or '')]
    people = sorted(contacts.values(), key=lambda c: (c['privacy'], c['first_seen'] or ''))
    return {
        'snapshots': len(snapshots),
        'first_snapshot': _record_date(snapshots[0]) if snapshots else None,
        'last_snapshot': _record_date(snapshots[-1]) if snapshots else None,
        'first_registered': created[0][:10] if created else None,
        'contacts': people,
        'real_contacts': sum(1 for c in people if not c['privacy']),
        'registrars': ordered(registrars),
        'nameservers': ordered(nameservers),
        'timeline': list(reversed(timeline)),
    }
