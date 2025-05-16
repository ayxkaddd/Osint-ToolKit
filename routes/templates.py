from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

router = APIRouter()
templates = Jinja2Templates(directory="templates")

@router.get('/')
def index(request: Request):
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

@router.get('/doxbin')
def doxbin_page(request: Request):
    return templates.TemplateResponse(request=request, name="doxbin.html")

@router.get('/whois')
def whois_page(request: Request):
    return templates.TemplateResponse(request=request, name="whois_history.html")

@router.get('/telegram_auth')
def telegram_auth_page(request: Request):
    return templates.TemplateResponse(request=request, name="telegram_auth.html")

@router.get('/vk')
def vk_page(request: Request):
    return templates.TemplateResponse(request=request, name="telegram.html")


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
