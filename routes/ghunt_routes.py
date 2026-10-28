from fastapi import APIRouter, HTTPException

from services.ghunt_service import GHuntError, GHuntModule, GHuntService
from utils.investigation_decorator import save_investigation

router = APIRouter(prefix="/api/ghunt")
ghunt_service = GHuntService()


async def _run(module: GHuntModule, target: str) -> dict:
    try:
        return await ghunt_service.run(module, target)
    except GHuntError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.get("/email")
@save_investigation(service_name="ghunt", method_name="lookup_ghunt_email")
async def ghunt_email(email: str) -> dict:
    return await _run("email", email)


@router.get("/gaia")
@save_investigation(service_name="ghunt", method_name="lookup_ghunt_gaia")
async def ghunt_gaia(gaia_id: str) -> dict:
    return await _run("gaia", gaia_id)


@router.get("/drive")
@save_investigation(service_name="ghunt", method_name="lookup_ghunt_drive")
async def ghunt_drive(drive_url: str) -> dict:
    return await _run("drive", drive_url)


@router.get("/geolocate")
@save_investigation(service_name="ghunt", method_name="lookup_ghunt_geolocate")
async def ghunt_geolocate(bssid: str) -> dict:
    return await _run("geolocate", bssid)


@router.get("/spiderdal")
@save_investigation(service_name="ghunt", method_name="lookup_ghunt_spiderdal")
async def ghunt_spiderdal(domain: str) -> dict:
    return await _run("spiderdal", domain)
