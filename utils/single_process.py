"""One server process per data folder.

Investigations are JSON files guarded by a lock inside the process
(``_STORE_LOCK`` in services/investigation_service.py), and the login limit is
kept in memory. A second process on the same folder (``uvicorn --workers 2``, or
another server started here) would interleave writes and corrupt cases, so the
first process holds a lock on ``.server.lock`` and any other one refuses to start.
The operating system releases the lock when the process ends, so a crash never
leaves it behind.
"""
import os
from pathlib import Path
from typing import IO, Optional

LOCK_PATH = Path(".server.lock")

_held: Optional[IO[str]] = None


class AnotherServerRunning(RuntimeError):
    pass


def _lock(handle: IO[str]) -> None:
    try:
        import fcntl
    except ImportError:  # Windows
        import msvcrt
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def hold(path: Path = LOCK_PATH) -> None:
    """Take the folder's lock for this process (again: no-op), or raise AnotherServerRunning."""
    global _held
    if _held is not None:
        return
    handle = open(path, "a+")
    try:
        _lock(handle)
    except OSError:
        handle.close()
        raise AnotherServerRunning(
            f"Another server process is already using this folder ({Path.cwd()}). "
            "Run the toolkit as a single process: without --workers, and one server per folder."
        ) from None
    handle.seek(0)
    handle.truncate()
    handle.write(f"{os.getpid()}\n")
    handle.flush()
    _held = handle


def stop_supervisor() -> None:
    """When this process is a worker uvicorn started (--workers, --reload), stop uvicorn
    itself: it would otherwise start a new worker as soon as this one exits, forever."""
    import multiprocessing
    import signal
    parent = multiprocessing.parent_process()
    if parent is not None and parent.pid:
        os.kill(parent.pid, signal.SIGTERM)


def release() -> None:
    global _held
    if _held is not None:
        _held.close()
        _held = None
