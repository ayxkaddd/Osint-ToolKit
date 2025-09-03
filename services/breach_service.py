import requests
from dotenv import load_dotenv
from typing import List

load_dotenv()

class BreachService:
    def __init__(self):
        self.domain = "breach.vip"
        self.uri = f"/api/search"

    def search_breach(self, term: str, fields: List[str] = ["email"], wildcard: bool = False, case_sensitive: bool = False):
        headers = {
            "Content-Type": "application/json",
        }

        data = {
            "term": term,
            "fields": fields,
            "categories": [
              "minecraft"
            ],
            "wildcard": wildcard,
            "case_sensitive": case_sensitive
        }

        response = requests.post(f"https://{self.domain}{self.uri}", headers=headers, json=data)
        return response.json()
