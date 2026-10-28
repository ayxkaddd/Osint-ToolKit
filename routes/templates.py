from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from services.investigation_service import InvestigationService

router = APIRouter()
templates = Jinja2Templates(directory="templates")
investigation_service = InvestigationService()

@router.get('/')
def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

@router.post("/")
def index_post(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

@router.get('/dashboard')
def dashboard(request: Request):
    return templates.TemplateResponse(request=request, name="dashboard.html")

@router.get('/git')
def git_lookup_page(request: Request):
    return templates.TemplateResponse(request=request, name="git.html")

@router.get('/ns')
def ns_lookup_page(request: Request):
    return templates.TemplateResponse(request=request, name="ns_lookup.html")

@router.get('/api')
def api_page(request: Request):
    return templates.TemplateResponse(request=request, name="use_api.html")

@router.get('/cavalier')
def cavalier_page(request: Request):
    return templates.TemplateResponse(request=request, name="cavalier.html")

@router.get('/whois')
def whois_page(request: Request):
    return templates.TemplateResponse(request=request, name="whois_history.html")

@router.get('/hlr')
def hlr_page(request: Request):
    return templates.TemplateResponse(request=request, name="hlr_lookup.html")

@router.get('/telegram_auth')
def telegram_auth_page(request: Request):
    return templates.TemplateResponse(request=request, name="telegram_auth.html")

@router.get('/vk')
def vk_page(request: Request):
    return templates.TemplateResponse(request=request, name="telegram.html")

@router.get('/dnsrecon')
def dnsrecon_page(request: Request):
    return templates.TemplateResponse(request=request, name="dnsrecon.html")

@router.get('/username')
def username_page(request: Request):
    return templates.TemplateResponse(request=request, name="username.html")
    

@router.get('/investigations')
def investigations_page(request: Request):
    return templates.TemplateResponse(request=request, name="investigations_dash.html")

@router.get('/ghunt')
def ghunt_page(request: Request):
    return templates.TemplateResponse(request=request, name="ghunt.html")

@router.get('/face-search')
def face_search_page(request: Request):
    return templates.TemplateResponse(request=request, name="face_search.html")

@router.get("/reports/{filename}")
async def get_report(filename: str):
    REPORTS_DIR = Path("reports").resolve()

    try:
        requested_path = (REPORTS_DIR / filename).resolve()
        if not str(requested_path).startswith(str(REPORTS_DIR)):
            return HTMLResponse("Access denied", status_code=403)
        if not requested_path.is_file():
            return HTMLResponse("File not found", status_code=404)
        return FileResponse(str(requested_path))
    except (ValueError, OSError):
        return HTMLResponse("Invalid file path", status_code=400)


@router.get("/notes/")
async def notes_page(request: Request):
    current = investigation_service.get_current_investigation()
    if not current:
        return RedirectResponse(url="/investigations")
    return templates.TemplateResponse(
        request=request,
        name="notes_test.html",
        context={"investigation_id": str(current)}
    )

@router.get("/funstat")
def funstat_page(request: Request):
    return templates.TemplateResponse(request=request, name="funstat.html")


@router.get("/websearch")
def websearch_page(request: Request):
    return templates.TemplateResponse(request=request, name="web_search.html")


@router.get("/lookup")
def lookup_page(request: Request):
    return templates.TemplateResponse(request=request, name="lookup.html")


@router.get("/ip")
def ip_page(request: Request):
    return templates.TemplateResponse(request=request, name="ip.html")


@router.get("/settings")
def settings_page(request: Request):
    return templates.TemplateResponse(request=request, name="settings.html")
