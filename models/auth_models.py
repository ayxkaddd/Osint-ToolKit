from pydantic import BaseModel

class AuthDetails(BaseModel):
    email: str
    password: str