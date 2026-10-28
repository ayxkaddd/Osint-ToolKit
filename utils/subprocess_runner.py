"""Run external CLI tools (GitFive, GHunt, ...) without blocking the server.

``subprocess.run`` inside an async route freezes every request until the tool
exits (GitFive can take minutes). This runs the process on the event loop,
kills it on timeout and returns its output for error reporting.
"""
import asyncio
import errno
import logging
from dataclasses import dataclass
from typing import Optional, Sequence

logger = logging.getLogger(__name__)


@dataclass
class CommandResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False

    def error_summary(self, limit: int = 600) -> str:
        """Last meaningful lines of output, for showing to the user."""
        text = (self.stderr.strip() or self.stdout.strip())
        lines = [line for line in text.splitlines() if line.strip()]
        summary = "\n".join(lines[-8:])
        return summary[-limit:] if summary else f"exit code {self.returncode}"


async def run_command(cmd: Sequence[str], timeout: float, cwd: Optional[str] = None) -> CommandResult:
    logger.info("Running %s", cmd[0] if cmd else "?")
    async def spawn(args):
        return await asyncio.create_subprocess_exec(
            *args,
            # Tools like httpx/subfinder read targets from a non-terminal stdin and
            # would wait forever on the server's; they get their input as arguments
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )

    try:
        try:
            process = await spawn(cmd)
        except OSError as e:
            if e.errno != errno.ENOEXEC:
                raise
            # A script without a "#!" line: run it with sh, as a shell would
            process = await spawn(["/bin/sh", *cmd])
    except FileNotFoundError:
        return CommandResult(127, "", f"Program not found: {cmd[0]}")
    except PermissionError:
        return CommandResult(126, "", f"Program is not executable: {cmd[0]}")
    except OSError as e:
        return CommandResult(126, "", f"Could not start {cmd[0]}: {e.strerror or e}")

    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        process.kill()
        stdout, stderr = await process.communicate()
        return CommandResult(-1, stdout.decode(errors="replace"), stderr.decode(errors="replace"), timed_out=True)
    except asyncio.CancelledError:
        # Client went away: don't leave the tool running
        process.kill()
        await process.wait()
        raise
    returncode = process.returncode if process.returncode is not None else -1
    return CommandResult(returncode, stdout.decode(errors="replace"), stderr.decode(errors="replace"))
