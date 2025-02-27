import json
import os
from typing import List
from models.doxbin_models import DoxBinUser

class DoxbinService:
    def __init__(self):
        self.users_file = "assets/doxbin_users.json"

    def search_doxbin(self, query: str) -> List[DoxBinUser]:
        if not os.path.exists(self.users_file):
            raise FileNotFoundError(
                "RGF0YWJhc2UgZmlsZSBub3QgZm91bmQuIFBsZWFzZSBkb3dubG9hZCBkb3hiaW5fdXNlcnMuanNvbiBmcm9tIGh0dHBzOi8vdC5tZS8reXFaS1hrVlVhR3RqTWpZNmFuZCBwbGFjZSBpdCBpbiB0aGUgYXNzZXRzLyBkaXJlY3Rvcnkg"
            )

        with open(self.users_file, "r") as file:
            users = json.loads(file.read())

        results = []
        query = query.lower()
        for user in users:
            usernames = user['username'] if isinstance(user['username'], list) else [user['username']]
            usernames = [u if u else "???" for u in usernames]

            emails = user['email'] if isinstance(user['email'], list) else [user['email']]
            emails = [e if e else "???" for e in emails]

            if any(query in u.lower() if u else False for u in usernames) or \
               any(query in e.lower() if e else False for e in emails):
                results.append(DoxBinUser(
                    uid=user['uid'] if user['uid'] else "???",
                    username=usernames,
                    email=emails,
                    password=user['password'] if user['password'] else "???",
                    session=user['session'] if user['session'] else "???",
                    profile_url=f"https://doxbin.com/user/{usernames[0]}"
                ))

        return results
