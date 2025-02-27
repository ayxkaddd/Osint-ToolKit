import os
import requests
from dotenv import load_dotenv
from typing import List

load_dotenv()

class NsService:
    def __init__(self):
        self.domain = "api.hackertarget.com"
        self.uri = f"/findshareddns/"
        self.api_key = os.getenv("HACKER_TARGET_API_KEY")

    def get_domains_api(self, ns: str) -> List[str]:
        resp = requests.get(f"https://{self.domain}{self.uri}?q={ns}&apikey={self.api_key}")
        return resp.text.split("\n")

    def get_shared_domains(self, ns1: str, ns2: str) -> List[str]:
        domains_1 = self.get_domains_api(ns1)
        domains_2 = self.get_domains_api(ns2)
        duplicates = set(domains_1).intersection(set(domains_2))
        return list(duplicates)
