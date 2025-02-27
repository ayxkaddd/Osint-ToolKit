from typing import List
from pydantic import BaseModel

class ExternalResource(BaseModel):
    name: str
    url: str
    favicon: str
    description: str

class Module(BaseModel):
    name: str
    description: str
    endpoint: str
    icon: str
    icon_color: str
    icon_type: str
    tags: List[str]

class Resourses(BaseModel):
    modules: List[Module]
    ext_res: List[ExternalResource]
