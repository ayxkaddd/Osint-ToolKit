#!/usr/bin/env python3
"""
DNS Reconnaissance FastAPI Backend
Using httpx-toolkit, subfinder, SecurityTrails API, and other free tools
"""

import asyncio
import json
import logging
import os
import re
import socket
import tempfile
import datetime
import xml.etree.ElementTree as ET
from typing import List, Dict, Any, Optional

from models.dnsrecon_models import ReconResults
import httpx
import dns.resolver
import whois
import dotenv

from services.dns_intel import (analyze_records, cymru_query_name, parse_crtsh,
                                parse_cymru_asname, parse_cymru_origin)
from utils.subprocess_runner import run_command
from utils.config import get_setting

dotenv.load_dotenv()
logger = logging.getLogger(__name__)

MAX_PROBED_NAMES = 1000
MAX_ASN_LOOKUPS = 100

class DNSReconService:
    # Read per call so values saved in settings apply without a restart
    @property
    def SECURITY_TRAILS_API_KEY(self):
        return get_setting('SECURITYTRAILS_API_KEY', '')

    @property
    def VIRUSTOTAL_API_KEY(self):
        return get_setting('VIRUSTOTAL_API_KEY', '')

    @property
    def HTTPX_PATH(self):
        return get_setting('HTTPX_PATH', 'httpx-toolkit')

    @property
    def SUBFINDER_PATH(self):
        return get_setting('SUBFINDER_PATH', 'subfinder')

    @property
    def NMAP_PATH(self):
        return get_setting('NMAP_PATH', 'nmap')

    @staticmethod
    def _client() -> httpx.AsyncClient:
        # One client per recon run: the service object is shared by all requests
        return httpx.AsyncClient(timeout=30.0, follow_redirects=True)

    async def run_subfinder(self, domain: str, deep_scan: bool, warnings: List[str]) -> List[str]:
        """Enumerate subdomains with subfinder (the domain itself is always included)."""
        cmd = [self.SUBFINDER_PATH, '-d', domain, '-silent']
        if deep_scan:
            cmd.extend(['-all', '-recursive'])
        result = await run_command(cmd, timeout=900 if deep_scan else 300)
        if result.returncode == 127:
            warnings.append(f"subfinder is not installed ({self.SUBFINDER_PATH}) - subdomains come from "
                            "certificate transparency and the configured APIs only")
        elif result.timed_out:
            warnings.append("subfinder timed out - subdomain list may be incomplete")
        elif result.returncode != 0:
            warnings.append(f"subfinder failed: {result.error_summary(200)}")

        found = {line.strip().lower() for line in result.stdout.splitlines() if line.strip()}
        found.add(domain)
        return sorted(found, key=lambda d: (d != domain, d))

    async def run_httpx_toolkit(self, subdomains: List[str], warnings: List[str]) -> List[Dict[str, Any]]:
        """Probe HTTP services with ProjectDiscovery httpx (JSON lines on stdout)."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("\n".join(subdomains))
            subdomain_file = f.name
        try:
            cmd = [
                self.HTTPX_PATH, '-l', subdomain_file, '-json', '-silent',
                '-title', '-tech-detect', '-status-code', '-content-length', '-response-time',
                '-server', '-http2', '-favicon', '-jarm', '-asn', '-cdn', '-ip',
                '-follow-redirects', '-random-agent',
            ]
            result = await run_command(cmd, timeout=600)
        finally:
            os.unlink(subdomain_file)

        if result.returncode == 127:
            warnings.append(f"httpx-toolkit is not installed ({self.HTTPX_PATH}) - HTTP probing skipped")
            return []
        if result.timed_out:
            warnings.append("HTTP probing timed out - results may be incomplete")
        results = []
        for line in result.stdout.splitlines():
            try:
                results.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        if not results and result.returncode not in (0, -1):
            warnings.append(f"httpx-toolkit failed: {result.error_summary(200)}")
        return results

    async def get_securitytrails_data(self, domain: str, client: httpx.AsyncClient) -> Dict[str, Any]:
        """Subdomains and A/MX/NS history from SecurityTrails (4 API calls -
        the free plan has 50 a month, so nothing else is requested)."""
        if not self.SECURITY_TRAILS_API_KEY:
            return {"error": "SecurityTrails API key not configured"}

        headers = {"APIKEY": self.SECURITY_TRAILS_API_KEY}
        base_url = "https://api.securitytrails.com/v1"
        out: Dict[str, Any] = {"subdomains": [], "history": {}, "errors": []}

        async def call(path: str) -> Optional[Dict[str, Any]]:
            try:
                response = await client.get(f"{base_url}{path}", headers=headers)
            except httpx.HTTPError as e:
                out["errors"].append(f"{path}: {e.__class__.__name__}")
                return None
            if response.status_code != 200:
                reason = {401: "invalid API key", 403: "not included in your plan",
                          429: "monthly quota or rate limit reached"}.get(response.status_code, "")
                out["errors"].append(f"{path}: HTTP {response.status_code} {reason}".strip())
                return None
            return response.json()

        data = await call(f"/domain/{domain}/subdomains?children_only=false")
        if data:
            out["subdomains"] = sorted({f"{s}.{domain}".lower() for s in data.get("subdomains") or [] if s})

        value_key = {"a": "ip", "mx": "host", "ns": "nameserver"}
        for rtype, key in value_key.items():
            await asyncio.sleep(1)  # free plan rate limit
            data = await call(f"/history/{domain}/dns/{rtype}")
            if not data:
                continue
            out["history"][rtype.upper()] = [{
                "values": [v.get(key) for v in record.get("values") or [] if v.get(key)],
                "organizations": record.get("organizations") or [],
                "first_seen": record.get("first_seen"),
                "last_seen": record.get("last_seen"),
            } for record in data.get("records") or []]
        return out

    async def get_virustotal_data(self, domain: str, client: httpx.AsyncClient) -> Dict[str, Any]:
        """Passive DNS, subdomains and flagged URLs from VirusTotal (1 API call)."""
        if not self.VIRUSTOTAL_API_KEY:
            return {"error": "VirusTotal API key not configured"}

        try:
            response = await client.get(
                "https://www.virustotal.com/vtapi/v2/domain/report",
                params={"apikey": self.VIRUSTOTAL_API_KEY, "domain": domain}
            )
        except httpx.HTTPError as e:
            return {"error": e.__class__.__name__}
        if response.status_code != 200:
            return {"error": f"HTTP {response.status_code}"}
        try:
            report = response.json()
        except ValueError:
            return {"error": "invalid response"}
        if report.get("response_code") == 0:
            return {"error": "domain is not in the VirusTotal dataset"}

        detected = [u for u in report.get("detected_urls") or [] if (u.get("positives") or 0) > 0]
        return {
            "subdomains": sorted({s.lower() for s in report.get("subdomains") or [] if s}),
            "resolutions": sorted(
                ({"ip": r.get("ip_address"), "last_resolved": (r.get("last_resolved") or "")[:10]}
                 for r in report.get("resolutions") or [] if r.get("ip_address")),
                key=lambda r: r["last_resolved"], reverse=True)[:200],
            "categories": sorted({str(v) for k, v in report.items() if k.endswith("category") and v}),
            "detected_urls": [{"url": u.get("url"), "positives": u.get("positives"), "total": u.get("total"),
                               "scan_date": u.get("scan_date")} for u in detected[:50]],
        }

    async def get_crtsh(self, domain: str, client: httpx.AsyncClient, warnings: List[str]):
        """Every name that ever appeared in a TLS certificate (free, no key)."""
        last_error = ""
        for attempt in range(2):
            try:
                response = await client.get("https://crt.sh/", params={"q": f"%.{domain}", "output": "json"},
                                            timeout=60.0)
                if response.status_code == 200:
                    return parse_crtsh(response.json(), domain)
                last_error = f"HTTP {response.status_code}"
            except (httpx.HTTPError, ValueError) as e:
                last_error = e.__class__.__name__
            await asyncio.sleep(3 * (attempt + 1))
        warnings.append(f"crt.sh (certificate transparency) is unavailable right now ({last_error}) - try again later")
        return {}, []

    async def resolve(self, name: str, record_type: str) -> List[str]:
        def run() -> List[str]:
            try:
                return [str(a) for a in dns.resolver.resolve(name, record_type, lifetime=8)]
            except Exception:
                return []
        return await asyncio.to_thread(run)

    async def asn_lookup(self, ips: List[str]) -> Dict[str, Dict[str, str]]:
        """Network owner per IP via Team Cymru's DNS interface (free, no key)."""
        sem = asyncio.Semaphore(16)
        names: Dict[str, str] = {}

        async def one(ip: str):
            query = cymru_query_name(ip)
            if not query:
                return ip, {}
            async with sem:
                answers = await self.resolve(query, "TXT")
            if not answers:
                return ip, {}
            info = parse_cymru_origin(answers[0])
            asn = info.get("asn")
            if asn and asn not in names:
                names[asn] = ""
                async with sem:
                    as_answers = await self.resolve(f"AS{asn}.asn.cymru.com", "TXT")
                names[asn] = parse_cymru_asname(as_answers[0]) if as_answers else ""
            return ip, info

        results = dict(await asyncio.gather(*(one(ip) for ip in ips)))
        for info in results.values():
            if info.get("asn"):
                info["as_name"] = names.get(info["asn"], "")
        return results

    async def get_dns_records_fallback(self, domain: str) -> Dict[str, List[str]]:
        """DNS records via dnspython (blocking resolver -> worker threads)."""
        record_types = ['A', 'AAAA', 'MX', 'NS', 'TXT', 'CNAME', 'SOA', 'CAA']
        values = await asyncio.gather(*(self.resolve(domain, rt) for rt in record_types))
        return dict(zip(record_types, values))

    async def resolve_many(self, names: List[str]) -> Dict[str, List[str]]:
        """A records for many names (which subdomains still exist, and where)."""
        sem = asyncio.Semaphore(32)

        async def one(name: str):
            async with sem:
                return name, await self.resolve(name, "A")
        return dict(await asyncio.gather(*(one(n) for n in names)))

    async def get_whois_info(self, domain: str) -> Dict[str, Any]:
        """Get WHOIS information"""
        try:
            w = await asyncio.to_thread(whois.whois, domain)
            return {
                'registrar': str(w.registrar) if w.registrar else None,
                'creation_date': str(w.creation_date) if w.creation_date else None,
                'expiration_date': str(w.expiration_date) if w.expiration_date else None,
                'updated_date': str(w.updated_date) if w.updated_date else None,
                'name_servers': w.name_servers if w.name_servers else [],
                'status': w.status if w.status else [],
                'emails': w.emails if w.emails else [],
                'country': str(w.country) if w.country else None,
                'org': str(w.org) if w.org else None,
                'registrant': str(w.name) if w.name else None,
                'admin_email': str(w.admin_email) if hasattr(w, 'admin_email') and w.admin_email else None
            }
        except Exception as e:
            return {'error': str(e)}

    async def run_nmap_scan(self, domain: str, warnings: List[str]) -> List[Dict[str, Any]]:
        """Port scan with nmap (XML output - nmap has no JSON output format).

        SYN scans and OS detection need root; without it use a TCP connect scan.
        """
        is_root = hasattr(os, "geteuid") and os.geteuid() == 0
        scan_flags = ['-sS', '-O'] if is_root else ['-sT']
        cmd = [self.NMAP_PATH, *scan_flags, '-sV', '--top-ports', '1000', '-T4',
               '--max-retries', '2', '-oX', '-', domain]
        result = await run_command(cmd, timeout=900)
        if result.returncode == 127:
            warnings.append("nmap is not installed - fell back to a basic check of common ports")
            return await self.basic_port_scan(domain)
        if result.timed_out:
            warnings.append("nmap timed out")
        try:
            return self.parse_nmap_xml(result.stdout)
        except ET.ParseError:
            warnings.append(f"nmap failed: {result.error_summary(200)} - fell back to a basic check of common ports")
            return await self.basic_port_scan(domain)

    @staticmethod
    def parse_nmap_xml(xml_text: str) -> List[Dict[str, Any]]:
        root = ET.fromstring(xml_text)
        results = []
        for host in root.findall('host'):
            address = host.find('address')
            ip = address.get('addr') if address is not None else None
            for port in host.findall('./ports/port'):
                state = port.find('state')
                service = port.find('service')
                results.append({
                    'host': ip,
                    'port': int(port.get('portid')),
                    'protocol': port.get('protocol'),
                    'state': state.get('state') if state is not None else None,
                    'service': service.get('name') if service is not None else None,
                    'product': service.get('product', '') if service is not None else '',
                    'version': service.get('version', '') if service is not None else '',
                    'extrainfo': service.get('extrainfo', '') if service is not None else '',
                })
        return results

    async def basic_port_scan(self, domain: str) -> List[Dict[str, Any]]:
        """Fallback: async TCP connect check of common ports."""
        common_ports = [21, 22, 23, 25, 53, 80, 110, 143, 443, 993, 995, 1433, 3306, 5432, 6379, 8080, 8443, 27017]
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(domain, None, type=socket.SOCK_STREAM)
            ip = infos[0][4][0]
        except OSError as e:
            return [{'error': f'Could not resolve {domain}: {e}'}]

        async def probe(port: int):
            try:
                _, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout=2)
                writer.close()
                return {'host': ip, 'port': port, 'state': 'open', 'service': self.get_service_name(port)}
            except (OSError, asyncio.TimeoutError):
                return None

        return [r for r in await asyncio.gather(*(probe(p) for p in common_ports)) if r]

    def get_service_name(self, port: int) -> str:
        """Get common service name for port"""
        services = {
            21: 'FTP', 22: 'SSH', 23: 'Telnet', 25: 'SMTP', 53: 'DNS',
            80: 'HTTP', 110: 'POP3', 143: 'IMAP', 443: 'HTTPS',
            993: 'IMAPS', 995: 'POP3S', 1433: 'MSSQL', 3306: 'MySQL',
            5432: 'PostgreSQL', 6379: 'Redis', 27017: 'MongoDB'
        }
        return services.get(port, 'Unknown')

    def analyze_security(self, httpx_results: List[Dict], external_data: Dict) -> Dict[str, Any]:
        """Analyze security based on httpx and external API results"""
        analysis = {
            'ssl_analysis': {
                'total_endpoints': 0,
                'https_enabled': 0,
                'ssl_issues': []
            },
            'security_headers': {
                'endpoints_checked': 0,
                'good_headers': 0,
                'missing_headers': []
            },
            'vulnerabilities': {
                'total_found': 0,
                'critical': 0,
                'high': 0,
                'medium': 0,
                'low': 0
            },
            'reputation': {
                'malicious_votes': 0,
                'suspicious_votes': 0,
                'clean_votes': 0
            }
        }

        # Analyze httpx results
        for result in httpx_results:
            analysis['ssl_analysis']['total_endpoints'] += 1

            if result.get('url', '').startswith('https://'):
                analysis['ssl_analysis']['https_enabled'] += 1

            # Check for security headers (if available in httpx output)
            if 'headers' in result:
                headers = result['headers']
                security_headers = [
                    'strict-transport-security',
                    'content-security-policy',
                    'x-frame-options',
                    'x-content-type-options'
                ]

                analysis['security_headers']['endpoints_checked'] += 1
                for header in security_headers:
                    if header in headers:
                        analysis['security_headers']['good_headers'] += 1
                    else:
                        analysis['security_headers']['missing_headers'].append(header)

        # URLs on the domain that VirusTotal engines flagged
        vt_data = external_data.get('virustotal', {})
        analysis['reputation']['malicious_votes'] = len(vt_data.get('detected_urls') or [])

        return analysis

    async def perform_recon(self, domain: str, deep_scan: bool = False,
                          include_ports: bool = False, use_external_apis: bool = True) -> ReconResults:
        """Main reconnaissance function. Independent steps run concurrently;
        tool problems are reported in ``warnings`` instead of failing silently."""
        timestamp = datetime.datetime.now().isoformat()
        warnings: List[str] = []
        logger.info("Starting reconnaissance for %s", domain)

        async with self._client() as client:
            async def external():
                if not use_external_apis:
                    return {}
                securitytrails, virustotal = await asyncio.gather(
                    self.get_securitytrails_data(domain, client),
                    self.get_virustotal_data(domain, client),
                )
                return {'securitytrails': securitytrails, 'virustotal': virustotal}

            async def ports():
                return await self.run_nmap_scan(domain, warnings) if include_ports else None

            (crt_names, cert_emails), subfinder_names, dns_records, dmarc, whois_info, external_data, port_results = \
                await asyncio.gather(
                    self.get_crtsh(domain, client, warnings),
                    self.run_subfinder(domain, deep_scan, warnings),
                    self.get_dns_records_fallback(domain),
                    self.resolve(f"_dmarc.{domain}", "TXT"),
                    self.get_whois_info(domain),
                    external(),
                    ports(),
                )

            securitytrails = external_data.get('securitytrails') or {}
            virustotal = external_data.get('virustotal') or {}
            for name, source in ((securitytrails, 'SecurityTrails'), (virustotal, 'VirusTotal')):
                if name.get('error') and 'not configured' not in name['error']:
                    warnings.append(f"{source}: {name['error']}")
            for error in securitytrails.get('errors') or []:
                warnings.append(f"SecurityTrails {error}")

            # Where each name was seen
            sources: Dict[str, List[str]] = {domain: ['target']}
            for names, source in ((subfinder_names, 'subfinder'), (crt_names, 'certificates'),
                                  (securitytrails.get('subdomains') or [], 'SecurityTrails'),
                                  (virustotal.get('subdomains') or [], 'VirusTotal')):
                for name in names:
                    if name == domain or name.endswith('.' + domain):
                        sources.setdefault(name, [])
                        if source not in sources[name]:
                            sources[name].append(source)
            names = sorted(sources, key=lambda d: (d != domain, d))
            probe_names = names[:MAX_PROBED_NAMES]
            if len(names) > MAX_PROBED_NAMES:
                warnings.append(f"{len(names)} names found - only the first {MAX_PROBED_NAMES} were resolved and probed")

            resolved, httpx_results = await asyncio.gather(
                self.resolve_many(probe_names),
                self.run_httpx_toolkit(probe_names, warnings),
            )
            resolved[domain] = dns_records.get('A', []) + dns_records.get('AAAA', [])

            # Hosting map: which names share an IP, and whose network it is
            by_ip: Dict[str, List[str]] = {}
            for name, ips in resolved.items():
                for ip in ips:
                    by_ip.setdefault(ip, []).append(name)
            top_ips = sorted(by_ip, key=lambda ip: -len(by_ip[ip]))[:MAX_ASN_LOOKUPS]
            asn = await self.asn_lookup(top_ips)

        hosting = [{
            'ip': ip,
            'asn': asn.get(ip, {}).get('asn'),
            'as_name': asn.get(ip, {}).get('as_name'),
            'prefix': asn.get(ip, {}).get('prefix'),
            'country': asn.get(ip, {}).get('country'),
            'hosts': sorted(by_ip[ip], key=lambda d: (d != domain, d)),
        } for ip in top_ips]

        security_analysis = self.analyze_security(httpx_results, external_data)

        # httpx's "host" field is the resolved IP; the probed name is "input"
        def probed_name(result: Dict[str, Any]) -> str:
            name = result.get('input') or result.get('url', '')
            return re.sub(r'^https?://', '', name).split('/')[0].split(':')[0].lower()

        httpx_by_host: Dict[str, Dict[str, Any]] = {}
        for result in httpx_results:
            httpx_by_host.setdefault(probed_name(result), result)

        subdomains_data = []
        for subdomain in names:
            probe = httpx_by_host.get(subdomain, {})
            cert = crt_names.get(subdomain, {})
            subdomains_data.append({
                'name': subdomain,
                'sources': sources[subdomain],
                'ips': resolved.get(subdomain, []),
                'resolves': bool(resolved.get(subdomain)),
                'first_cert': cert.get('first_seen'),
                'last_cert': cert.get('last_seen'),
                'httpx_data': probe,
                'is_alive': bool(probe),
                'technologies': probe.get('tech', []),
                'status_code': probe.get('status_code'),
                'title': probe.get('title'),
                'server': probe.get('webserver'),
                'content_length': probe.get('content_length'),
            })

        intel = analyze_records(dns_records, dmarc)
        intel['cert_emails'] = cert_emails
        dated = [c['first_seen'] for c in crt_names.values() if c.get('first_seen')]
        intel['first_certificate'] = min(dated) if dated else None

        dns_history = {
            'securitytrails': securitytrails.get('history') or {},
            'virustotal_resolutions': virustotal.get('resolutions') or [],
        }
        external_summary = {}
        if use_external_apis:
            external_summary = {
                'securitytrails': {'error': securitytrails['error']} if securitytrails.get('error') else
                {'subdomains': len(securitytrails.get('subdomains') or []), 'errors': securitytrails.get('errors') or []},
                'virustotal': {'error': virustotal['error']} if virustotal.get('error') else
                {'subdomains': len(virustotal.get('subdomains') or []), 'categories': virustotal.get('categories') or [],
                 'detected_urls': virustotal.get('detected_urls') or []},
            }

        alive_subdomains = [s for s in subdomains_data if s['is_alive']]
        all_technologies = [t for s in alive_subdomains for t in (s['technologies'] or [])]
        summary = {
            'total_subdomains': len(subdomains_data),
            'resolving_subdomains': sum(1 for s in subdomains_data if s['resolves']),
            'alive_subdomains': len(alive_subdomains),
            'unique_ips': len(by_ip),
            'unique_technologies': len(set(all_technologies)),
            'https_percentage': (security_analysis['ssl_analysis']['https_enabled'] /
                                 max(security_analysis['ssl_analysis']['total_endpoints'], 1)) * 100,
            'security_score': self.calculate_security_score(security_analysis),
            'external_apis_used': use_external_apis,
            'port_scan_performed': include_ports
        }
        if port_results:
            summary['open_ports_found'] = len([p for p in port_results if p.get('state') == 'open'])

        return ReconResults(
            domain=domain,
            timestamp=timestamp,
            subdomains=subdomains_data,
            dns_records=dns_records,
            whois_info=whois_info,
            httpx_results=httpx_results,
            security_analysis=security_analysis,
            port_scan_results=port_results,
            external_api_data=external_summary,
            summary=summary,
            warnings=warnings,
            intel=intel,
            hosting=hosting,
            dns_history=dns_history,
        )

    def calculate_security_score(self, security_analysis: Dict) -> int:
        """Calculate overall security score"""
        score = 100

        # Deduct points for missing HTTPS
        https_ratio = (security_analysis['ssl_analysis']['https_enabled'] /
                      max(security_analysis['ssl_analysis']['total_endpoints'], 1))
        score -= (1 - https_ratio) * 30

        # Deduct points for missing security headers
        if security_analysis['security_headers']['endpoints_checked'] > 0:
            header_ratio = (security_analysis['security_headers']['good_headers'] /
                          (security_analysis['security_headers']['endpoints_checked'] * 4))  # 4 key headers
            score -= (1 - header_ratio) * 25

        # Deduct points for reputation issues
        malicious_votes = security_analysis['reputation']['malicious_votes']
        if malicious_votes > 0:
            score -= min(malicious_votes * 10, 40)

        return max(int(score), 0)
