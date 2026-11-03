"""Settings come from the working folder's .env only, and changes apply without a restart."""
import os
from pathlib import Path


def test_real_env_is_not_loaded(app):
    from conftest import REPO
    real = REPO / ".env"
    if not real.exists():
        return
    ours = {line.split("=", 1)[0] for line in Path(".env").read_text().splitlines() if "=" in line}
    theirs = {line.split("=", 1)[0].strip() for line in real.read_text().splitlines()
              if "=" in line and not line.lstrip().startswith("#")}
    assert not [key for key in theirs - ours if key in os.environ]


def test_changes_apply_without_restart():
    from services.gitfive_service import GitFiveService
    from utils.config import update_env
    service = GitFiveService()
    update_env({"GITFIVE_VENV_PATH": "/opt/test/python"})
    assert service.venv_path == "/opt/test/python"
    update_env({"GITFIVE_VENV_PATH": None})
