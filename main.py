from fastapi import FastAPI, Request, Response
from fastapi.exceptions import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
import os

from models.auth_models import AuthDetails
from routes import doxbin_routes, git_routes, oi_routes, rosources_routes, settings_routes, templates, ns_routers, updates_routes, whois_route
from auth.auth_handler import AuthHandler

load_dotenv()

class OsintFrameWork:
    def __init__(self):
        self.app = FastAPI(title="Osint Framework", version="1.0.0")
        self.auth_handler = AuthHandler()
        self.setup_routes()
        self.setup_static_files()
        self.setup_auth()
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
        if request.url.path == "/" or request.url.path == "/login":
            response = await call_next(request)
            return response

        token = request.cookies.get("access_token")
        if not token:
            return RedirectResponse(url="/")

        try:
            self.auth_handler.decode_token(token)
            response = await call_next(request)
            return response
        except:
            return RedirectResponse(url="/")

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

    def setup_routes(self):
        self.app.include_router(
            git_routes.router,
            tags=["gitfive"],
        )
        self.app.include_router(
            ns_routers.router,
            tags=["ns"],
        )
        self.app.include_router(
            whois_route.router,
            tags=["whois"],
        )
        self.app.include_router(
            oi_routes.router,
            tags=["oi"],
        )
        self.app.include_router(
            doxbin_routes.router,
            tags=["doxbin"],
        )
        self.app.include_router(
            rosources_routes.router,
            tags=["resources"],
        )
        self.app.include_router(
            settings_routes.router,
            tags=["settings"],
        )
        self.app.include_router(
            updates_routes.router,
            tags=["updates"],
        )
        self.app.include_router(
            templates.router,
            tags=["templates"]
        )


app = OsintFrameWork().app