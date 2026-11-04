from typing import Optional
from pydantic import BaseModel

class Setting(BaseModel):
    type: str
    label: str

class Module(BaseModel):
    name: str
    description: str
    endpoint: str
    icon: str
    icon_color: str
    icon_type: str
    tags: list[str]
    settings: Optional[dict[str, Setting]] = None

class ExternalResource(BaseModel):
    name: str
    url: str
    favicon: str
    description: str

class Resources(BaseModel):
    modules: list[Module]
    ext_res: list[ExternalResource]
