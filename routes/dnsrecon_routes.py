import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException

from models.dnsrecon_models import DomainRequest, ReconResults
from services.dnsrecon_service import DNSReconService
from utils.investigation_decorator import save_investigation
from utils.subprocess_runner import run_command

router = APIRouter(prefix="/api/recon")
dns_recon_service = DNSReconService()


@router.post("/")
@save_investigation(service_name="dns_recon", method_name="lookup_dns_recon")
async def perform_reconnaissance(request: DomainRequest, investigation_id: Optional[str] = None) -> ReconResults:
    """Perform comprehensive DNS reconnaissance"""
    try:
        return await dns_recon_service.perform_recon(
            domain=request.domain,
            deep_scan=request.deep_scan,
            include_ports=request.include_ports,
            use_external_apis=request.use_external_apis
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reconnaissance failed: {str(e)}") from e


@router.get("/health")
async def health_check():
    """Which recon tools are available (checks the configured binaries)."""
    tools = {
        "subfinder": [dns_recon_service.SUBFINDER_PATH, "-version"],
        "httpx": [dns_recon_service.HTTPX_PATH, "-version"],
        "nmap": [dns_recon_service.NMAP_PATH, "--version"],
    }
    tools_status = {}
    for name, cmd in tools.items():
        result = await run_command(cmd, timeout=15)
        tools_status[name] = "installed" if result.returncode == 0 else "not_found"

    return {
        "status": "healthy",
        "timestamp": datetime.datetime.now().isoformat(),
        "tools": tools_status,
        "api_keys": {
            "securitytrails": bool(dns_recon_service.SECURITY_TRAILS_API_KEY),
            "virustotal": bool(dns_recon_service.VIRUSTOTAL_API_KEY),
        },
    }
