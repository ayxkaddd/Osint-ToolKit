"""Setup wizard tool checks: GitFive is checked for its own packages, and `go install`
can't hang the setup page forever."""
import subprocess
from types import SimpleNamespace

from routes import setup_routes


def test_gitfive_check_imports_gitfive_packages_not_ghunt(tmp_path, monkeypatch):
    gitfive = tmp_path / "GitFive"
    (gitfive / "venv" / "bin").mkdir(parents=True)
    (gitfive / "venv" / "bin" / "python").touch()
    (gitfive / "main.py").touch()
    # found as ../GitFive from the working directory
    (tmp_path / "app").mkdir()
    monkeypatch.chdir(tmp_path / "app")

    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(setup_routes.subprocess, "run", fake_run)
    status = setup_routes.check_gitfive_detailed()

    assert status["status"] == "ready"
    assert calls and not any("ghunt" in part for part in calls[0])
    assert calls[0][-1] == setup_routes.GITFIVE_IMPORT_CHECK
    assert "trio" in calls[0][-1]


def test_go_install_stops_after_the_timeout(monkeypatch):
    monkeypatch.setattr(setup_routes, "check_dependency", lambda cmd: True)
    seen = {}

    def fake_run(cmd, **kw):
        seen.update(kw)
        raise subprocess.TimeoutExpired(cmd, kw["timeout"], output="go: downloading x\n")

    monkeypatch.setattr(setup_routes.subprocess, "run", fake_run)
    result = setup_routes.install_go_tool("subfinder", "example.com/subfinder@latest")

    assert seen["timeout"] == setup_routes.GO_INSTALL_TIMEOUT
    assert result["success"] is False
    assert "took longer than" in result["message"]
    assert "go: downloading x" in result["output"]


def test_go_install_reports_success(monkeypatch):
    monkeypatch.setattr(setup_routes, "check_dependency", lambda cmd: True)
    monkeypatch.setattr(setup_routes.shutil, "which", lambda cmd: f"/usr/bin/{cmd}")
    monkeypatch.setattr(setup_routes.subprocess, "run",
                        lambda cmd, **kw: SimpleNamespace(returncode=0, stdout="line1\nline2\n"))
    result = setup_routes.install_go_tool("subfinder", "example.com/subfinder@latest")
    assert result == {"success": True, "message": "Successfully installed subfinder",
                      "path": "/usr/bin/subfinder", "output": "line1\nline2"}


def test_admin_setup_error_keeps_details_in_the_log(app, monkeypatch, caplog):
    from fastapi.testclient import TestClient

    def fail(config):
        raise OSError("[Errno 13] Permission denied: '/srv/secret/.env'")

    monkeypatch.setattr(setup_routes, "check_setup_complete", lambda: False)
    monkeypatch.setattr(setup_routes, "save_env_config", fail)
    response = TestClient(app, client=("127.0.0.1", 5000)).post(
        "/setup/admin", data={"email": "admin@example.com", "password": "Admin-pass1", "confirm_password": "Admin-pass1"})
    assert response.status_code == 500
    assert "/srv/secret" not in response.text and "server log" in response.json()["detail"]
    assert "/srv/secret" in caplog.text
