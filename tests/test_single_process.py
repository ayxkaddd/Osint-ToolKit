"""One server process per data folder: a second one (uvicorn --workers 2) refuses to start."""
import subprocess
import sys
from pathlib import Path

from conftest import REPO

TRY_LOCK = (
    "import sys; sys.path.insert(0, sys.argv[1]); from utils import single_process\n"
    "try:\n    single_process.hold()\nexcept single_process.AnotherServerRunning as e:\n"
    "    print(e); sys.exit(3)\nprint('locked')\n"
)


def _other_process(folder: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-c", TRY_LOCK, str(REPO)], cwd=folder,
                          capture_output=True, text=True, timeout=30)


def test_second_process_on_the_folder_refuses(client):
    # the test app (its lifespan) holds the lock of the test folder
    assert Path(".server.lock").exists()
    other = _other_process(Path.cwd())
    assert other.returncode == 3, other.stderr
    assert "single process" in other.stdout and "--workers" in other.stdout


def test_other_folders_and_repeat_calls_are_fine(client, tmp_path):
    from utils import single_process
    single_process.hold()  # already held by this process: nothing happens
    assert _other_process(tmp_path).stdout.strip() == "locked"


def test_lock_is_free_after_release(tmp_path):
    from utils import single_process
    held = single_process._held
    try:
        single_process._held = None
        single_process.hold(tmp_path / ".server.lock")
        assert _other_process(tmp_path).returncode == 3
        single_process.release()
        assert _other_process(tmp_path).stdout.strip() == "locked"
    finally:
        single_process.release()
        single_process._held = held
