import asyncio
import json
import tempfile
import os
import datetime
from typing import List, Dict, Any

from models.dnsrecon_models import ReconResults
import httpx
import dns.resolver
import whois
import dotenv

dotenv.load_dotenv()

class DNSReconService:
    def __init__(self):
        self.http_client = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True
        )
        self.SECURITY_TRAILS_API_KEY = os.getenv('SECURITYTRAILS_API_KEY', 'your-free-api-key-here')
        self.VIRUSTOTAL_API_KEY = os.getenv('VIRUSTOTAL_API_KEY', 'your-free-api-key-here')
        self.HTTPX_PATH = os.getenv('HTTPX_PATH', 'httpx-toolkit')
        self.SUBFINDER_PATH = os.getenv('SUBFINDER_PATH', 'subfinder')
        self.NMAP_PATH = os.getenv('NMAP_PATH', 'nmap')

    async def __aenter__(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.http_client.aclose()

    async def run_subfinder(self, domain: str, deep_scan: bool = False) -> List[str]:
        """Run subfinder to enumerate subdomains"""
        try:
            with tempfile.NamedTemporaryFile(mode='w+', suffix='.txt', delete=False) as f:
                output_file = f.name

            cmd = [self.SUBFINDER_PATH, '-d', domain, '-o', output_file, '-silent']

            if deep_scan:
                cmd.extend(['-all', '-recursive'])

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            await process.communicate()

            subdomains = []
            if os.path.exists(output_file):
                with open(output_file, 'r') as f:
                    subdomains = [line.strip() for line in f if line.strip()]
                os.unlink(output_file)

            if domain not in subdomains:
                subdomains.insert(0, domain)

            return list(set(subdomains))

        except Exception as e:
            print(f"Subfinder error: {e}")
            return [domain]

    async def run_httpx_toolkit(self, subdomains: List[str]) -> List[Dict[str, Any]]:
        """Run httpx toolkit for HTTP probing and technology detection"""
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
                subdomain_file = f.name
                for subdomain in subdomains:
                    f.write(f"{subdomain}\n")

            with tempfile.NamedTemporaryFile(mode='w+', suffix='.json', delete=False) as f:
                output_file = f.name

            cmd = [
                self.HTTPX_PATH,
                '-l', subdomain_file,
                '-json',
                '-o', output_file,
                '-title',
                '-tech-detect',
                '-status-code',
                '-content-length',
                '-response-time',
                '-server',
                '-method',
                '-websocket',
                '-pipeline',
                '-http2',
                '-favicon',
                '-jarm',
                '-asn',
                '-cdn',
                '-probe',
                '-follow-redirects',
                '-random-agent',
                '-silent'
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            await process.communicate()

            results = []
            if os.path.exists(output_file):
                with open(output_file, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                result = json.loads(line)
                                results.append(result)
                            except json.JSONDecodeError:
                                continue

                os.unlink(output_file)

            os.unlink(subdomain_file)
            return results

        except Exception as e:
            print(f"Httpx toolkit error: {e}")
            return []

    async def get_securitytrails_data(self, domain: str) -> Dict[str, Any]:
        """Get comprehensive DNS data from SecurityTrails API"""
        if not self.SECURITYTRAILS_API_KEY or self.SECURITYTRAILS_API_KEY == "your-free-api-key-here":
            return {"error": "SecurityTrails API key not configured"}

        headers = {"APIKEY": self.SECURITYTRAILS_API_KEY}
        base_url = "https://api.securitytrails.com/v1"

        data = {
            "domain_info": {},
            "dns_history": {},
            "subdomains": {},
            "whois_history": {},
            "ssl_certificates": {}
        }

        endpoints = {
            "domain_info": f"/domain/{domain}",
            "dns_history": f"/history/{domain}/dns",
            "subdomains": f"/domain/{domain}/subdomains",
            "whois_history": f"/history/{domain}/whois",
            "ssl_certificates": f"/domain/{domain}/ssl"
        }

        for key, endpoint in endpoints.items():
            try:
                response = await self.http_client.get(
                    f"{base_url}{endpoint}",
                    headers=headers
                )
                if response.status_code == 200:
                    data[key] = response.json()
                else:
                    data[key] = {"error": f"HTTP {response.status_code}"}
            except Exception as e:
                data[key] = {"error": str(e)}

            await asyncio.sleep(1)

        return data

    async def get_virustotal_data(self, domain: str) -> Dict[str, Any]:
        """Get domain reputation data from VirusTotal API"""
        if not self.VIRUSTOTAL_API_KEY or self.VIRUSTOTAL_API_KEY == "your-free-api-key-here":
            return {"error": "VirusTotal API key not configured"}

        try:
            response = await self.http_client.get(
                "https://www.virustotal.com/vtapi/v2/domain/report",
                params={"apikey": self.VIRUSTOTAL_API_KEY, "domain": domain}
            )

            if response.status_code == 200:
                return response.json()
            else:
                return {"error": f"HTTP {response.status_code}"}

        except Exception as e:
            return {"error": str(e)}

    async def get_dns_records_fallback(self, domain: str) -> Dict[str, List[str]]:
        """Fallback DNS record lookup using dnspython"""
        records = {
            'A': [], 'AAAA': [], 'MX': [], 'NS': [], 'TXT': [],
            'CNAME': [], 'SOA': [], 'CAA': [], 'SRV': []
        }

        record_types = ['A', 'AAAA', 'MX', 'NS', 'TXT', 'CNAME', 'SOA', 'CAA', 'SRV']

        for record_type in record_types:
            try:
                answers = dns.resolver.resolve(domain, record_type)
                records[record_type] = [str(answer) for answer in answers]
            except:
                continue

        return records

    async def get_whois_info(self, domain: str) -> Dict[str, Any]:
        """Get WHOIS information"""
        try:
            w = whois.whois(domain)
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

    async def run_nmap_scan(self, domain: str) -> List[Dict[str, Any]]:
        """Run nmap scan for port discovery"""
        try:
            cmd = [
                self.NMAP_PATH,
                '-sS',
                '-O', 
                '-sV',
                '--top-ports', '1000',
                '-T4', 
                '--max-retries', '2',
                '-oJ', '-',
                domain
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate()

            if stdout:
                try:
                    nmap_result = json.loads(stdout.decode())
                    return self.parse_nmap_results(nmap_result)
                except json.JSONDecodeError:
                    return [{'error': 'Failed to parse nmap JSON output'}]

            return [{'error': 'No nmap output received'}]

        except Exception:
            return await self.basic_port_scan(domain)

    def parse_nmap_results(self, nmap_data: Dict) -> List[Dict[str, Any]]:
        """Parse nmap JSON results"""
        results = []

        if 'scan' in nmap_data:
            for host, host_data in nmap_data['scan'].items():
                if 'tcp' in host_data:
                    for port, port_data in host_data['tcp'].items():
                        results.append({
                            'host': host,
                            'port': int(port),
                            'state': port_data.get('state'),
                            'service': port_data.get('name'),
                            'version': port_data.get('version', ''),
                            'product': port_data.get('product', ''),
                            'extrainfo': port_data.get('extrainfo', '')
                        })

        return results

    async def basic_port_scan(self, domain: str) -> List[Dict[str, Any]]:
        """Basic port scan fallback"""
        import socket

        common_ports = [21, 22, 23, 25, 53, 80, 110, 143, 443, 993, 995, 1433, 3306, 5432, 6379, 27017]
        results = []

        try:
            ip = socket.gethostbyname(domain)

            for port in common_ports:
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(2)
                    result = sock.connect_ex((ip, port))
                    sock.close()

                    if result == 0:
                        results.append({
                            'host': ip,
                            'port': port,
                            'state': 'open',
                            'service': self.get_service_name(port)
                        })
                except:
                    continue

        except Exception as e:
            return [{'error': str(e)}]

        return results

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

        for result in httpx_results:
            analysis['ssl_analysis']['total_endpoints'] += 1

            if result.get('url', '').startswith('https://'):
                analysis['ssl_analysis']['https_enabled'] += 1

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

        vt_data = external_data.get('virustotal', {})
        if 'positives' in vt_data and 'total' in vt_data:
            analysis['reputation']['malicious_votes'] = vt_data.get('positives', 0)
            analysis['reputation']['clean_votes'] = vt_data.get('total', 0) - vt_data.get('positives', 0)

        return analysis

    async def perform_recon(self, domain: str, deep_scan: bool = False,
                          include_ports: bool = False, use_external_apis: bool = True) -> ReconResults:
        """Main reconnaissance function"""
        timestamp = datetime.datetime.now().isoformat()

        print(f"Starting reconnaissance for {domain}...")

        print("Finding subdomains...")
        subdomains = await self.run_subfinder(domain, deep_scan)
        print(f"Found {len(subdomains)} subdomains")

        print("Probing HTTP endpoints with httpx toolkit...")
        httpx_results = await self.run_httpx_toolkit(subdomains)
        print(f"Probed {len(httpx_results)} endpoints")

        print("Getting DNS records...")
        dns_records = await self.get_dns_records_fallback(domain)

        print("Getting WHOIS information...")
        whois_info = await self.get_whois_info(domain)

        external_data = {}
        if use_external_apis:
            print("Gathering external API data...")

            external_data['securitytrails'] = await self.get_securitytrails_data(domain)

            external_data['virustotal'] = await self.get_virustotal_data(domain)

        port_results = None
        if include_ports:
            print("Scanning ports...")
            port_results = await self.run_nmap_scan(domain)

        print("Analyzing security...")
        security_analysis = self.analyze_security(httpx_results, external_data)

        subdomains_data = []
        httpx_by_host = {result.get('host', result.get('url', '').replace('https://', '').replace('http://', '')): result for result in httpx_results}

        for subdomain in subdomains:
            subdomain_info = {
                'name': subdomain,
                'httpx_data': httpx_by_host.get(subdomain, {}),
                'is_alive': subdomain in httpx_by_host,
                'technologies': httpx_by_host.get(subdomain, {}).get('technologies', []),
                'status_code': httpx_by_host.get(subdomain, {}).get('status_code'),
                'title': httpx_by_host.get(subdomain, {}).get('title'),
                'server': httpx_by_host.get(subdomain, {}).get('server'),
                'content_length': httpx_by_host.get(subdomain, {}).get('content_length')
            }
            subdomains_data.append(subdomain_info)

        alive_subdomains = [s for s in subdomains_data if s['is_alive']]
        all_technologies = []
        for s in alive_subdomains:
            if s['technologies']:
                all_technologies.extend(s['technologies'])

        summary = {
            'total_subdomains': len(subdomains_data),
            'alive_subdomains': len(alive_subdomains),
            'unique_technologies': len(set(all_technologies)),
            'https_percentage': (security_analysis['ssl_analysis']['https_enabled'] /
                               max(security_analysis['ssl_analysis']['total_endpoints'], 1)) * 100,
            'security_score': self.calculate_security_score(security_analysis),
            'external_apis_used': use_external_apis,
            'port_scan_performed': include_ports
        }

        if port_results:
            open_ports = [p for p in port_results if p.get('state') == 'open']
            summary['open_ports_found'] = len(open_ports)

        return ReconResults(
            domain=domain,
            timestamp=timestamp,
            subdomains=subdomains_data,
            dns_records=dns_records,
            whois_info=whois_info,
            httpx_results=httpx_results,
            security_analysis=security_analysis,
            port_scan_results=port_results,
            external_api_data=external_data,
            summary=summary
        )

    def calculate_security_score(self, security_analysis: Dict) -> int:
        """Calculate overall security score"""
        score = 100

        https_ratio = (security_analysis['ssl_analysis']['https_enabled'] /
                      max(security_analysis['ssl_analysis']['total_endpoints'], 1))
        score -= (1 - https_ratio) * 30

        if security_analysis['security_headers']['endpoints_checked'] > 0:
            header_ratio = (security_analysis['security_headers']['good_headers'] /
                          (security_analysis['security_headers']['endpoints_checked'] * 4))  # 4 key headers
            score -= (1 - header_ratio) * 25

        malicious_votes = security_analysis['reputation']['malicious_votes']
        if malicious_votes > 0:
            score -= min(malicious_votes * 10, 40)

        return max(int(score), 0)
