import asyncio
import json
from typing import Any


from utils.config import get_setting
from utils.subprocess_runner import run_command


SHARETRACE_TIMEOUT = 30
SHARETRACE_CONCURRENCY = 4


class ShareTraceService:
    @property
    def python_path(self) -> str:
        return get_setting('SHARETRACE_PYTHON_PATH') or 'python'

    @property
    def sharetrace_dir(self):
        return get_setting('SHARETRACE_MODULE_PATH')

    async def run_sharetrace(self, link: str) -> dict[str, Any]:
        """Run sharetrace for one link; errors are returned in the result."""
        result = await run_command(
            [self.python_path, '-m', 'sharetrace', link, '--json'],
            timeout=SHARETRACE_TIMEOUT,
            cwd=self.sharetrace_dir or None,
        )
        if result.timed_out:
            return {"error": "Command timed out", "link": link}
        if result.returncode != 0:
            return {"error": "Sharetrace command failed", "return_code": result.returncode,
                    "stderr": result.error_summary(), "link": link}
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return {"error": "Failed to parse JSON output", "raw_output": result.stdout[:2000], "link": link}

    async def run_many(self, links: list[str]) -> list[dict[str, Any]]:
        """Enrich several links in parallel (bounded), keeping input order."""
        semaphore = asyncio.Semaphore(SHARETRACE_CONCURRENCY)

        async def one(link: str) -> dict[str, Any]:
            async with semaphore:
                return await self.run_sharetrace(link)

        return list(await asyncio.gather(*(one(link) for link in links)))
