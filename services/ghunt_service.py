import json
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

from utils.subprocess_runner import run_command

logger = logging.getLogger(__name__)

GHuntModule = Literal['email', 'gaia', 'drive', 'geolocate', 'spiderdal']
GHUNT_TIMEOUT = 300

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
GAIA_RE = re.compile(r"^\d{15,25}$")
BSSID_RE = re.compile(r"^[0-9A-Fa-f]{2}([:-][0-9A-Fa-f]{2}){5}$")
DRIVE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{10,}$")
DOMAIN_RE = re.compile(r"^(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,}$")


class GHuntError(Exception):
    pass


class GHuntService:
    """Runs the GHunt CLI. Arguments are passed without a shell, so the risk is
    option injection, not command injection: every target is validated for its
    type (and may not start with '-') instead of having characters stripped,
    which used to mangle Drive URLs."""

    def __init__(self):
        load_dotenv()
        self.ghunt_path = os.getenv('GHUNT_SCRIPT_PATH', 'ghunt')
        self.work_dir = Path('./assets/ghunt')
        self.work_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def validate(module: GHuntModule, target: str) -> str:
        target = (target or "").strip()
        if not target or target.startswith("-"):
            raise GHuntError("Enter a target")
        if module == "email" and not EMAIL_RE.match(target):
            raise GHuntError("Not a valid email address")
        if module == "gaia" and not GAIA_RE.match(target):
            raise GHuntError("A Gaia ID is a 15-25 digit number")
        if module == "geolocate":
            if not BSSID_RE.match(target):
                raise GHuntError("BSSID must look like AA:BB:CC:DD:EE:FF")
            target = target.replace("-", ":").upper()
        if module == "drive":
            is_url = re.match(r"^https://(drive|docs)\.google\.com/", target)
            if not is_url and not DRIVE_ID_RE.match(target):
                raise GHuntError("Enter a Google Drive/Docs URL or file ID")
        if module == "spiderdal":
            host = re.sub(r"^https?://", "", target).split("/")[0]
            if not DOMAIN_RE.match(host):
                raise GHuntError("Enter a domain, e.g. example.com")
            target = f"https://{host}"
        return target

    @staticmethod
    def _clean_output(text: str) -> str:
        """GHunt output minus its ASCII-art banner and credits, last lines only."""
        lines = []
        for line in (text or "").splitlines():
            stripped = line.strip()
            if not stripped or "888" in stripped or "Y8P" in stripped or "mxrch" in stripped \
                    or "Sponsors" in stripped or "github.com/sponsors" in stripped:
                continue
            lines.append(stripped)
        return "\n".join(lines[-6:])[-600:]

    async def run(self, module: GHuntModule, target: str) -> dict:
        target = self.validate(module, target)
        # Unique output file per run: a failed run can't return a previous result
        output = self.work_dir / f"{module}_{uuid.uuid4().hex}.json"
        if module == 'spiderdal':
            cmd = [self.ghunt_path, 'spiderdal', '-u', target, '--json', str(output.resolve())]
        else:
            cmd = [self.ghunt_path, module, target, '--json', str(output.resolve())]

        try:
            result = await run_command(cmd, timeout=GHUNT_TIMEOUT)
            if result.timed_out:
                raise GHuntError(f"GHunt did not finish within {GHUNT_TIMEOUT // 60} minutes")
            if not output.exists():
                summary = self._clean_output(result.stderr or result.stdout) or result.error_summary()
                if re.search(r"login|credential|cookies|oauth|master token", summary, re.I):
                    raise GHuntError(f"GHunt is not logged in (run `ghunt login` on the server). {summary}")
                raise GHuntError(f"GHunt failed: {summary}")
            try:
                return json.loads(output.read_text())
            except json.JSONDecodeError as e:
                raise GHuntError("GHunt produced unreadable output") from e
        finally:
            output.unlink(missing_ok=True)
