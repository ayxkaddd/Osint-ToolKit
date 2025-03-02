import os
import aiohttp
from models.update_models import Update

class UpdatesService:
    def __init__(self):
        self.username = 'ayxkaddd'
        self.repo = 'osint-toolkit'
        self.default_branch = 'main'

        self.local_commit_file_path = os.path.join(f'.git/refs/heads/{self.default_branch}')

    async def get_local_commit(self) -> str | None:
        try:
            with open(self.local_commit_file_path, 'r') as f:
                return f.read().strip()
        except Exception as e:
            print(f"Error getting local commit: {e}")
            return None

    async def get_remote_commit(self) -> Update | None:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f'https://api.github.com/repos/{self.username}/{self.repo}/commits/{self.default_branch}') as response:
                    data = await response.json()
                    return Update(
                        hash=data['sha'],
                        message=data['commit']['message'],
                        committer=data['commit']['committer']['name'],
                        date=data['commit']['committer']['date'],
                        url=data['html_url'],
                        author_avatar=data['committer']['avatar_url'],
                        stats=data['stats']
                    )
        except Exception as e:
            print(f"Error getting remote commit: {e}")
            return None

    async def check_for_updates(self) -> Update | None:
        local_commit = await self.get_local_commit()
        remote_commit = await self.get_remote_commit()

        if local_commit is None or remote_commit is None:
            return None

        if local_commit.strip() == remote_commit.hash.strip():
            return None
        return remote_commit
