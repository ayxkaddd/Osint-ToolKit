"""Test setup: every test session runs in a throwaway folder.

The app keeps all its state relative to the working directory (.env, investigations,
media, plugins), so the session moves into a temporary folder with its own .env
before the app is imported. The real .env and case data are never read or written.
"""
import io
import os
import shutil
import sys
import tempfile
from pathlib import Path

import bcrypt
import pytest

REPO = Path(__file__).resolve().parent.parent
EMAIL, PASSWORD = "test@example.com", "test-password"

_workdir = Path(tempfile.mkdtemp(prefix="osint-tests-"))
(_workdir / "static").symlink_to(REPO / "static")
(_workdir / "templates").symlink_to(REPO / "templates")
shutil.copy(REPO / "resources.json", _workdir / "resources.json")
(_workdir / "plugins").mkdir()
(_workdir / ".setup_complete").touch()
(_workdir / ".env").write_text(
    f"ROOT_EMAIL={EMAIL}\n"
    f"ROOT_PASSWORD='{bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt()).decode()}'\n"
    "JWT_SECRET=throwaway-secret-for-tests-only-0000000000\n"
    "GHUNT_VENV_PATH=/bin/true\nGHUNT_SCRIPT_PATH=/bin/true\n"
    # The proxy pool would otherwise fetch public proxy lists over the network at startup
    "PROXY_ENABLED=false\n"
    # Never the operator's real Google session (~/.malfrats/ghunt/creds.m) in tests
    f"GHUNT_CREDS_PATH={_workdir / 'no-ghunt-session'}\n"
)
os.chdir(_workdir)
sys.path.insert(0, str(REPO))


def pytest_sessionfinish(session, exitstatus):
    os.chdir(REPO)
    shutil.rmtree(_workdir, ignore_errors=True)


@pytest.fixture(scope="session")
def app():
    import main
    return main.app


@pytest.fixture(scope="session")
def client(app):
    from fastapi.testclient import TestClient
    with TestClient(app) as c:
        assert c.post("/login", json={"email": EMAIL, "password": PASSWORD}).status_code == 200
        yield c


@pytest.fixture
def anon(app):
    from fastapi.testclient import TestClient
    return TestClient(app)


@pytest.fixture
def investigation(client):
    response = client.post("/api/investigations/create", data={"name": "Test case", "description": ""})
    data = response.json()
    return data.get("investigation_id") or data["investigation"]["investigation_id"]


def png(size=(40, 30), color=(200, 30, 30), fmt="PNG", **kw) -> bytes:
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, fmt, **kw)
    return out.getvalue()
