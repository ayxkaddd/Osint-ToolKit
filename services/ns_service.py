import requests
from dotenv import load_dotenv
from typing import List
from utils.config import get_setting

load_dotenv()


class NsLookupError(Exception):
    pass


class NsService:
    def __init__(self):
        self.domain = "api.hackertarget.com"
        self.uri = "/findshareddns/"

    @property
    def api_key(self):
        return get_setting("HACKER_TARGET_API_KEY")

    def get_domains_api(self, ns: str) -> List[str]:
        params = {"q": ns}
        if self.api_key:
            params["apikey"] = self.api_key
        resp = requests.get(f"https://{self.domain}{self.uri}", params=params, timeout=30)
        resp.raise_for_status()

        lines = [line.strip() for line in resp.text.splitlines() if line.strip()]
        # HackerTarget reports problems ("API count exceeded", "error check your
        # search parameter", ...) as a plain-text line instead of a domain list
        if len(lines) == 1 and (" " in lines[0] or lines[0].lower().startswith("error")):
            raise NsLookupError(f"HackerTarget: {lines[0]}")
        return [line.lower() for line in lines if " " not in line]

    def get_shared_domains(self, ns1: str, ns2: str) -> List[str]:
        domains_1 = self.get_domains_api(ns1)
        domains_2 = self.get_domains_api(ns2)
        return sorted(set(domains_1).intersection(domains_2))
