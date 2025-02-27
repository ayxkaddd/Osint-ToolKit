import subprocess
import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

class GitService:
    def __init__(self):
        load_dotenv()

        self.venv_path = os.getenv('GITFIVE_VENV_PATH', 'venv/bin/python')
        self.gitfive_path = os.getenv('GITFIVE_SCRIPT_PATH', 'GitFive/main.py')

        self.venv_path = str(Path(self.venv_path).resolve())
        self.gitfive_path = str(Path(self.gitfive_path).resolve())

        self.assets_path = Path('./assets')
        self.assets_path.mkdir(exist_ok=True)

    def _sanitize_username(self, username: str) -> str:
        return ''.join(c for c in username if c.isalnum() or c in '-_')

    def run_gitfive(self, username: str) -> Optional[str]:
        username = self._sanitize_username(username)
        if not username:
            print("Invalid username")
            return None

        output_file = self.assets_path / f"{username}_data.json"
        output_file = str(output_file.resolve())

        try:
            cmd = [
                self.venv_path,
                self.gitfive_path,
                'user',
                username,
                '--json',
                output_file
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                timeout=300
            )

            if result.stderr:
                print(f"Warnings/Errors: {result.stderr}")

            if not Path(output_file).exists():
                print("Output file was not created")
                return None

            return output_file
        except subprocess.TimeoutExpired:
            print("Process timed out")
            return None
        except subprocess.CalledProcessError as e:
            print(f"Process failed with exit code {e.returncode}")
            print(f"Error output: {e.stderr}")
            return None
        except Exception as e:
            print(f"Unexpected error: {str(e)}")
            return None
