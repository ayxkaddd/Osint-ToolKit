import asyncio
import json
import os
from typing import Any, Dict, List

from dotenv import load_dotenv

from utils.subprocess_runner import run_command

load_dotenv()

SHARETRACE_TIMEOUT = 30
SHARETRACE_CONCURRENCY = 4


class ShareTraceService:
    def __init__(self):
        self.python_path = os.getenv('SHARETRACE_PYTHON_PATH', 'python')
        self.sharetrace_dir = os.getenv('SHARETRACE_MODULE_PATH')

    async def run_sharetrace(self, link: str) -> Dict[str, Any]:
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

    async def run_many(self, links: List[str]) -> List[Dict[str, Any]]:
        """Enrich several links in parallel (bounded), keeping input order."""
        semaphore = asyncio.Semaphore(SHARETRACE_CONCURRENCY)

        async def one(link: str) -> Dict[str, Any]:
            async with semaphore:
                return await self.run_sharetrace(link)

        return list(await asyncio.gather(*(one(link) for link in links)))
