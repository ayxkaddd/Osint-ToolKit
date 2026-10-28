from fastapi import FastAPI, Request, Response
from fastapi.exceptions import HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
import hmac
import logging
import time
from collections import defaultdict, deque

from models.auth_models import AuthDetails
from routes import (
    cavalier_routes,
    face_search_routes,
    investigation_routes,
    setup_routes,
    sharetrace_routes,
    username_routes,
    dnsrecon_routes,
    git_routes,
    ghunt_routes,
    hlr_routes,
    lookup_routes,
    oi_routes,
    rosources_routes,
    settings_routes,
    templates,
    ns_routers,
    updates_routes,
    web_search_routes,
    whois_route,
    telegram_routes,
    funstat_routes,
)
from auth.auth_handler import AuthHandler
from utils.config import get_setting

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


load_dotenv()

# Paths reachable without a session
PUBLIC_PATHS = {"/", "/login", "/logout"}
# Setup endpoints that stay public after setup is complete (read-only)
PUBLIC_AFTER_SETUP = {"/setup/status"}
# Prefixes whose callers expect JSON rather than an HTML redirect
API_PREFIXES = ("/api/", "/funstat/", "/web/", "/auth/", "/setup/")

LOGIN_MAX_FAILURES = 5
LOGIN_WINDOW_SECONDS = 15 * 60


class OsintFrameWork:
    def __init__(self):
        self.app = FastAPI(title="Osint Framework", version="1.0.0")
        self.auth_handler = AuthHandler()
        self.failed_logins: dict[str, deque] = defaultdict(deque)
        self.setup_routes()
        self.setup_static_files()
        self.setup_auth()
        self.app.middleware("http")(self.access_middleware)

    def setup_static_files(self):
        self.app.mount("/static", StaticFiles(directory="static"), name="static")

    def _is_authenticated(self, request: Request) -> bool:
        token = request.cookies.get("access_token")
        if not token:
            return False
        try:
            self.auth_handler.decode_token(token)
            return True
        except HTTPException:
            return False

    @staticmethod
    def _wants_json(path: str) -> bool:
        return path.startswith(API_PREFIXES)

    async def access_middleware(self, request: Request, call_next):
        path = request.url.path

        if path.startswith("/static/"):
            return await call_next(request)

        setup_complete = setup_routes.check_setup_complete()

        if not setup_complete:
            # Until setup is finished only the setup wizard (and its API) is usable
            if path == "/setup" or path.startswith("/setup/"):
                return await call_next(request)
            if self._wants_json(path):
                return JSONResponse({"detail": "Setup is not complete"}, status_code=503)
            return RedirectResponse(url="/setup")

        if path in PUBLIC_PATHS or path in PUBLIC_AFTER_SETUP:
            return await call_next(request)

        if self._is_authenticated(request):
            return await call_next(request)

        if self._wants_json(path):
            return JSONResponse({"detail": "Not authenticated"}, status_code=401)
        return RedirectResponse(url="/")

    def _login_blocked(self, ip: str) -> bool:
        attempts = self.failed_logins[ip]
        cutoff = time.monotonic() - LOGIN_WINDOW_SECONDS
        while attempts and attempts[0] < cutoff:
            attempts.popleft()
        return len(attempts) >= LOGIN_MAX_FAILURES

    def setup_auth(self):
        @self.app.post("/login")
        async def login(data: AuthDetails, request: Request, response: Response):
            ip = request.client.host if request.client else "unknown"
            if self._login_blocked(ip):
                raise HTTPException(status_code=429, detail='Too many failed attempts, try again later')

            # Read credentials at request time so changes made in setup apply immediately
            root_email = get_setting('ROOT_EMAIL') or ""
            root_password = get_setting('ROOT_PASSWORD')

            email_ok = hmac.compare_digest(data.email.strip().lower(), root_email.strip().lower())
            password_ok = self.auth_handler.verify_password(data.password, root_password)
            if not (email_ok and password_ok):
                self.failed_logins[ip].append(time.monotonic())
                logger.warning("Failed login attempt from %s", ip)
                raise HTTPException(status_code=401, detail='Invalid credentials')

            self.failed_logins.pop(ip, None)
            token = self.auth_handler.encode_token(root_email)
            response.set_cookie(
                key="access_token",
                value=token,
                httponly=True,
                secure=(get_setting('COOKIE_SECURE', 'false') or '').lower() == 'true',
                samesite="lax",
                max_age=86400
            )
            return {"success": True}

        @self.app.post("/logout")
        async def logout():
            response = JSONResponse({"success": True})
            response.delete_cookie("access_token")
            return response

    def setup_routes(self) -> None:
        """Register all application routes."""

        routes_config = [
            (setup_routes.router, "Setup"),
            (git_routes.router, "GitFive"),
            (ns_routers.router, "DNS"),
            (whois_route.router, "WHOIS"),
            (oi_routes.router, "OSINT"),
            (telegram_routes.auth_router, "Telegram Auth"),
            (telegram_routes.bot_router, "Telegram Bot"),
            (dnsrecon_routes.router, "DNS Reconnaissance"),
            (hlr_routes.router, "HLR"),
            (username_routes.router, "Username"),
            (rosources_routes.router, "Resources"),
            (settings_routes.router, "Settings"),
            (cavalier_routes.router, "Cavalier"),
            (lookup_routes.router, "Lookup & jobs"),
            (updates_routes.router, "Updates"),
            (templates.router, "Templates"),
            (investigation_routes.router, "Investigations"),
            (ghunt_routes.router, "GHunt"),
            (face_search_routes.router, "Face Search"),
            (funstat_routes.user_router, "Funstat Users"),
            (funstat_routes.group_router, "Funstat Groups"),
            (funstat_routes.search_router, "Funstat Search"),
            (funstat_routes.media_router, "Funstat Media"),
            (funstat_routes.bot_router, "Funstat Bot"),
            (sharetrace_routes.router, "ShareTrace"),
            (web_search_routes.osint_router, "OSINT Search"),
        ]

        for router, tag in routes_config:
            self.app.include_router(
                router,
                tags=[tag],
            )

        logger.info(f"Registered {len(routes_config)} route groups")


app = OsintFrameWork().app
