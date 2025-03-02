from pydantic import BaseModel

class Update(BaseModel):
    hash: str
    message: str
    committer: str
    date: str
    url: str
    author_avatar: str
    stats: dict[str, int]
