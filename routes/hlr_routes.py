from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from services.hlr_service import HLRService
from utils.investigation_decorator import save_investigation

router = APIRouter(prefix="/api/hlr")
hlr_service = HLRService()

class HLRRequest(BaseModel):
    phones: str

@router.post("/lookup")
@save_investigation(service_name="hlr", method_name="hlr_lookup")
async def hlr_lookup(request: HLRRequest):
    """
    Perform HLR lookup for phone numbers
    Phone numbers should be comma-separated
    """
    try:
        return await hlr_service.lookup_numbers(request.phones)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e