from fastapi import FastAPI, Request, Response
from fastapi.exceptions import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
import os
import logging

from models.auth_models import AuthDetails
from routes import (
    funstat_routes,
    setup_routes,
    username_routes,
    breach_routes,
    dnsrecon_routes,
    doxbin_routes,
    git_routes,
    oi_routes,
    resources_routes,
    settings_routes,
    templates,
    ns_routers,
    web_search_routes,
    whois_route,
    telegram_routes,
    face_search_routes
)
from auth.auth_handler import AuthHandler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


load_dotenv()

class OsintFrameWork:
    def __init__(self):
        self.app = FastAPI(title="Osint Framework", version="1.0.0")
        self.auth_handler = AuthHandler()
        self.setup_routes()
        self.setup_static_files()
        self.setup_auth()
        self.app.middleware("http")(self.setup_redirect_middleware)
        self.app.middleware("http")(self.verify_token_middleware)
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    def setup_static_files(self):
        self.app.mount("/static", StaticFiles(directory="static"), name="static")

    async def verify_token_middleware(self, request: Request, call_next):
        SKIP_PATHS = ["/", "/login"]
        SKIP_PREFIXES = ["/static", "/setup"]
        if request.url.path in SKIP_PATHS or any(request.url.path.startswith(prefix) for prefix in SKIP_PREFIXES):
            response = await call_next(request)
            return response

        token = request.cookies.get("access_token")
        if not token:
            logger.warning("token not found")
            return RedirectResponse(url="/")

        try:
            self.auth_handler.decode_token(token)
            response = await call_next(request)
            return response
        except HTTPException as e:
            logger.error(e)
            return RedirectResponse(url="/")
        except Exception as e:
            logger.error(e)
            return Response(status_code=501, content=f"Internal Server Error. Error message: {e}")

    async def setup_redirect_middleware(self, request: Request, call_next):
        def is_setup_complete():
            return setup_routes.check_setup_complete()

        ALLOWED_PATHS = {
            "/setup",
            "/setup/",
            "/setup/status",
            "/setup/complete",
            "/setup/admin",
            "/setup/features",
            "/setup/apis",
            "/setup/install-tools",
            "/setup/validate-api",
            "/setup/gitfive-guide",
            "/setup/system-check",
            "/login",
        }

        path = request.url.path

        if path.startswith("/static/"):
            return await call_next(request)

        if not is_setup_complete() and path not in ALLOWED_PATHS:
            return RedirectResponse(url="/setup")

        return await call_next(request)

    def setup_auth(self):
        root_email = os.getenv('ROOT_EMAIL')
        root_password = os.getenv('ROOT_PASSWORD')

        @self.app.post("/login")
        async def login(data: AuthDetails, response: Response):
            if data.email != root_email:
                raise HTTPException(status_code=401, detail='Invalid credentials')

            if not self.auth_handler.verify_password(data.password, root_password):
                raise HTTPException(status_code=401, detail='Invalid credentials')

            token = self.auth_handler.encode_token(data.email)
            response.set_cookie(
                key="access_token",
                value=token,
                httponly=True,
                secure=False,
                samesite="lax",
                max_age=86400
            )
            return {"success": True}

    def setup_routes(self) -> None:
        """Register all application routes."""

        routes_config = [
            (git_routes.router, "GitFive"),
            (ns_routers.router, "DNS"),
            (whois_route.router, "WHOIS"),
            (oi_routes.router, "OSINT"),
            (doxbin_routes.router, "Doxbin"),
            (telegram_routes.auth_router, "Telegram Auth"),
            (telegram_routes.bot_router, "Telegram Bot"),
            (dnsrecon_routes.router, "DNS Reconnaissance"),
            (breach_routes.router, "Breach Data"),
            (username_routes.router, "Username"),
            (face_search_routes.router, "Face Search"),
            (funstat_routes.user_router, "Funstat Users"),
            (funstat_routes.group_router, "Funstat Groups"),
            (funstat_routes.search_router, "Funstat Search"),
            (funstat_routes.media_router, "Funstat Media"),
            (funstat_routes.bot_router, "Funstat Bot"),
            (web_search_routes.osint_router, "Web Search"),
            (resources_routes.router, "Resources"),
            (settings_routes.router, "Settings"),
            (templates.router, "Templates"),
            (setup_routes.router, "Setup"),
        ]

        for router, tag in routes_config:
            self.app.include_router(
                router,
                tags=[tag],
            )

        logger.info(f"Registered {len(routes_config)} route groups")


app = OsintFrameWork().app