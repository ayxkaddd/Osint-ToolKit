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
