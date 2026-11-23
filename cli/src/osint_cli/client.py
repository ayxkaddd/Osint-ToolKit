"""The server's HTTP API.

The login token is sent as the ``access_token`` cookie, as the browser does: background
lookups started here call the server back with the caller's cookie, so a token sent any
other way would start lookups that then fail.
"""
from pathlib import Path
from typing import Any, Optional

import httpx

TIMEOUT = httpx.Timeout(30.0, connect=10.0)

# tests put an httpx.MockTransport here
transport: Optional[httpx.BaseTransport] = None


class ApiError(Exception):
    """A request the server refused or couldn't answer; the message says why, in words."""

    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


class SessionExpired(ApiError):
    pass


def _detail(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text.strip()[:300] or f"HTTP {response.status_code}"
    detail = data.get("detail") if isinstance(data, dict) else None
    if isinstance(detail, list):  # FastAPI validation errors
        return "; ".join(str(d.get("msg", d)) for d in detail)
    return str(detail or data)[:300]


class Client:
    def __init__(self, url: str, token: Optional[str] = None):
        self.url = url
        cookies = {"access_token": token} if token else None
        self.http = httpx.Client(base_url=url, cookies=cookies, timeout=TIMEOUT, transport=transport,
                                 headers={"User-Agent": "osint-toolkit-cli"})

    def close(self) -> None:
        self.http.close()

    def request(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            response = self.http.request(method, path, **kwargs)
        except httpx.TimeoutException:
            raise ApiError(f"{self.url} did not answer in time") from None
        except httpx.RequestError:
            raise ApiError(f"Could not reach the server at {self.url} - is it running?") from None
        if response.status_code == 401 and path != "/login":
            raise SessionExpired("Session expired, run `osint login`", 401)
        if response.status_code == 503 and "setup" in _detail(response).lower():
            raise ApiError("The server's setup isn't finished: open it in a browser first", 503)
        if response.status_code >= 400:
            raise ApiError(_detail(response), response.status_code)
        return response

    def get(self, path: str, **kwargs) -> Any:
        return self.request("GET", path, **kwargs).json()

    # --- login ---

    def login(self, email: str, password: str) -> str:
        """The new token (the access_token cookie the server set)."""
        try:
            response = self.request("POST", "/login", json={"email": email, "password": password})
        except ApiError as e:
            if e.status == 401:
                raise ApiError("Wrong email or password", 401) from None
            if e.status == 429:
                raise ApiError("Too many attempts - wait a few minutes and try again", 429) from None
            raise
        token = response.cookies.get("access_token")
        if not token:
            raise ApiError("The server didn't send a login token")
        return token

    def logout(self, everywhere: bool = False) -> None:
        self.request("POST", "/logout", params={"everywhere": "true"} if everywhere else None)

    # --- investigations ---

    def investigations(self) -> dict:
        return self.get("/api/investigations/")

    def current(self) -> dict:
        return self.get("/api/investigations/current")

    def set_current(self, investigation_id: str) -> dict:
        return self.request("POST", "/api/investigations/set", data={"investigation_id": investigation_id}).json()

    def investigation(self, investigation_id: str) -> dict:
        return self.get(f"/api/investigations/{investigation_id}")

    def results(self, investigation_id: str) -> dict:
        return self.get(f"/api/investigations/{investigation_id}/results")

    def entities(self, investigation_id: str, type: Optional[str] = None, limit: int = 5000) -> dict:
        params = {"limit": limit, **({"type": type} if type else {})}
        return self.get(f"/api/investigations/{investigation_id}/entities", params=params)

    def download(self, path: str, target: Path, params: Optional[dict] = None) -> int:
        """Save an answer to a file; returns its size."""
        try:
            with self.http.stream("GET", path, params=params, timeout=httpx.Timeout(300.0, connect=10.0)) as response:
                if response.status_code == 401:
                    raise SessionExpired("Session expired, run `osint login`", 401)
                if response.status_code >= 400:
                    response.read()
                    raise ApiError(_detail(response), response.status_code)
                size = 0
                with open(target, "wb") as f:
                    for chunk in response.iter_bytes():
                        f.write(chunk)
                        size += len(chunk)
                return size
        except httpx.RequestError:
            raise ApiError(f"Could not reach the server at {self.url} - is it running?") from None

    # --- modules and lookups ---

    def modules(self) -> dict:
        return self.get("/api/modules")

    def detect(self, query: str) -> dict:
        return self.get("/api/lookup/detect", params={"q": query})

    def start_job(self, module: str, type: str, value: str) -> dict:
        return self.request("POST", "/api/jobs", json={"module": module, "type": type, "value": value}).json()

    def jobs(self, investigation_id: Optional[str] = None, limit: int = 50) -> dict:
        params = {"limit": limit, **({"investigation_id": investigation_id} if investigation_id else {})}
        return self.get("/api/jobs", params=params)

    def cancel_job(self, job_id: str) -> dict:
        return self.request("DELETE", f"/api/jobs/{job_id}").json()
