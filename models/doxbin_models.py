from pydantic import BaseModel
from typing import List

class DoxBinUser(BaseModel):
    uid: str
    username: List[str]
    email: List[str]
    password: str
    session: str
    profile_url: str
