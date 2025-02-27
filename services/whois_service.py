import json
import os
import re
from typing import Dict
import aiohttp
from fastapi import HTTPException

class WhoisService:
    def __init__(self):
        self.domain = "78.46.239.70:8000"
        self.uri = "/api/whois"
        self.whois_history_domain = "whois-history.whoisxmlapi.com"
        self.wx_api_key = os.getenv("WHOIS_XML_API_KEY")

    async def lookup_whois_history(self, domain: str):
        async with aiohttp.ClientSession() as session:
            async with session.post(f'https://{self.whois_history_domain}/api/v1?apiKey={self.wx_api_key}&domainName={domain}&mode=purchase') as resp:
                if resp.status != 200:
                    raise HTTPException(status_code=resp.status, detail="WHOIS lookup failed")
        data = await resp.json()
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

                top_registrar = (data.get('registrar') or {}).get('provider')

                combined_data = self.combine_whois_data(
                    domain_parsed,
                    domain_records,
                    top_registrar
                )

                combined_data['domain_raw_text'] = domain_raw_text
                return combined_data

    def parse_domain_json(self, raw_json_text: str) -> dict:
        try:
            data = json.loads(raw_json_text)
            result = {}

            for entity in data.get('entities', []):
                roles = entity.get('roles', [])
                if 'registrant' in roles:
                    vcard = entity.get('vcardArray', [])[1] if len(entity.get('vcardArray', [])) > 1 else []
                    for item in vcard:
                        if item[0] == 'org' and item[2] == 'text':
                            result['registrant'] = item[3]
                        elif item[0] == 'email' and item[2] == 'text':
                            result['email'] = item[3]

            for event in data.get('events', []):
                if event.get('eventAction') == 'registration':
                    result['creation_date'] = event.get('eventDate')
                elif event.get('eventAction') == 'expiration':
                    result['expiration_date'] = event.get('eventDate')

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
        result = {
            'registrant': None,
            'email': None,
            'creation_date': None,
            'expiration_date': None,
            'registrar': None,
            'nameservers': [],
            'statuses': []
        }

        result['registrant'] = (
            structured_data.get('registrant', {}).get('organization') or
            domain_data.get('registrant')
        )

        result['email'] = (
            structured_data.get('abuse', {}).get('email') or
            structured_data.get('registrant', {}).get('email') or
            domain_data.get('email')
        )

        result['creation_date'] = (
            structured_data.get('registeredAt') or
            domain_data.get('creation_date')
        )
        result['expiration_date'] = (
            structured_data.get('expiresAt') or
            domain_data.get('expiration_date')
        )

        result['registrar'] = (
            top_registrar or
            structured_data.get('registrar') or
            domain_data.get('registrar')
        )

        result['nameservers'] = structured_data.get('nameServers', [])
        result['statuses'] = structured_data.get('statuses', [])

        if not result['registrar']:
            result['registrar'] = self.parse_rawtext_for_registrar(
                structured_data.get('rawText', '')
            )

        return result

    def parse_rawtext_for_registrar(self, raw_text: str) -> str:
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