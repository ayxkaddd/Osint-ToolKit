from fastapi import APIRouter, HTTPException
from models.dnsrecon_models import DomainRequest, ReconResults
from services.dnsrecon_service import DNSReconService

router = APIRouter(prefix="/api/recon")
dns_recon_service = DNSReconService()

@router.post("/")
async def perform_reconnaissance(request: DomainRequest) -> ReconResults:
    """Perform comprehensive DNS reconnaissance"""
    try:
        async with dns_recon_service as service:
            results = await service.perform_recon(
                domain=request.domain,
                deep_scan=request.deep_scan,
                include_ports=request.include_ports,
                use_external_apis=request.use_external_apis
            )
            return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reconnaissance failed: {str(e)}")
