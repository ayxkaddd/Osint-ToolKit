import json
import logging
import os
import re
from pathlib import Path

from dotenv import load_dotenv

from utils.subprocess_runner import run_command

logger = logging.getLogger(__name__)

GITFIVE_TIMEOUT = 600
# GitHub logins: alphanumerics and single hyphens, max 39 chars
GITHUB_LOGIN_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$")


class GitFiveError(Exception):
    pass


class GitService:
    def __init__(self):
        load_dotenv()
        self.venv_path = os.getenv('GITFIVE_VENV_PATH', 'venv/bin/python')
        self.gitfive_path = str(Path(os.getenv('GITFIVE_SCRIPT_PATH', 'GitFive/main.py')).resolve())
        self.assets_path = Path('./assets')
        self.assets_path.mkdir(exist_ok=True)

    @staticmethod
    def normalize_username(username: str) -> str:
        username = (username or "").strip().lstrip("@")
        match = re.search(r"github\.com/([^/?#\s]+)", username)
        if match:
            username = match.group(1)
        if not GITHUB_LOGIN_RE.match(username):
            raise GitFiveError("Not a valid GitHub username")
        return username

    def output_path(self, username: str) -> Path:
        return self.assets_path / f"{username}_data.json"

    async def run_gitfive(self, username: str, refresh: bool = False) -> tuple[dict, bool]:
        """Return (GitFive JSON, from_cache). Results are cached per username;
        ``refresh`` re-runs GitFive."""
        username = self.normalize_username(username)
        output = self.output_path(username)
        if output.exists() and not refresh:
            return json.loads(output.read_text()), True

        # Write to a temp file so a failed run never leaves (or returns) stale data
        tmp = output.with_name(output.name + ".tmp")
        tmp.unlink(missing_ok=True)
        result = await run_command(
            [self.venv_path, self.gitfive_path, 'user', username, '--json', str(tmp.resolve())],
            timeout=GITFIVE_TIMEOUT,
        )
        if result.timed_out:
            raise GitFiveError(f"GitFive did not finish within {GITFIVE_TIMEOUT // 60} minutes")
        if result.returncode != 0 or not tmp.exists():
            tmp.unlink(missing_ok=True)
            raise GitFiveError(f"GitFive failed: {result.error_summary()}")

        os.replace(tmp, output)
        return json.loads(output.read_text()), False
