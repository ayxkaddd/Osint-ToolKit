from pydantic import BaseModel, validator
from typing import List, Dict, Any, Optional
import re

class DomainRequest(BaseModel):
    domain: str
    deep_scan: bool = False
    include_ports: bool = False
    use_external_apis: bool = True

    @validator('domain')
    def validate_domain(cls, v):
        pattern = re.compile(
            r'^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$'
        )
        if not pattern.match(v):
            raise ValueError('Invalid domain format')
        return v.lower()

class ReconResults(BaseModel):
    domain: str
    timestamp: str
    subdomains: List[Dict[str, Any]]
    dns_records: Dict[str, Any]
    whois_info: Dict[str, Any]
    httpx_results: List[Dict[str, Any]]
    security_analysis: Dict[str, Any]
    port_scan_results: Optional[List[Dict[str, Any]]] = None
    external_api_data: Dict[str, Any]
    summary: Dict[str, Any]
    # Tool problems (not installed, timed out, failed) - shown to the user
    warnings: List[str] = []
    # Owner intel from TXT/MX/NS/SOA/DMARC and certificates
    intel: Dict[str, Any] = {}
    # IPs the names resolve to, with network owner (ASN)
    hosting: List[Dict[str, Any]] = []
    # Earlier A/MX/NS values (SecurityTrails) and passive DNS (VirusTotal)
    dns_history: Dict[str, Any] = {}
