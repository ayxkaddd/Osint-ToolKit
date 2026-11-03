from pydantic import BaseModel, field_validator
from typing import Any, Optional
import re

class DomainRequest(BaseModel):
    domain: str
    deep_scan: bool = False
    include_ports: bool = False
    use_external_apis: bool = True

    @field_validator('domain')
    @classmethod
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
    subdomains: list[dict[str, Any]]
    dns_records: dict[str, Any]
    whois_info: dict[str, Any]
    httpx_results: list[dict[str, Any]]
    security_analysis: dict[str, Any]
    port_scan_results: Optional[list[dict[str, Any]]] = None
    external_api_data: dict[str, Any]
    summary: dict[str, Any]
    # Tool problems (not installed, timed out, failed) - shown to the user
    warnings: list[str] = []
    # Owner intel from TXT/MX/NS/SOA/DMARC and certificates
    intel: dict[str, Any] = {}
    # IPs the names resolve to, with network owner (ASN)
    hosting: list[dict[str, Any]] = []
    # Earlier A/MX/NS values (SecurityTrails) and passive DNS (VirusTotal)
    dns_history: dict[str, Any] = {}
