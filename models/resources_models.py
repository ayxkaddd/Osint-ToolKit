from typing import Dict, List, Optional
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
    tags: List[str]
    settings: Optional[Dict[str, Setting]] = None

class ExternalResource(BaseModel):
    name: str
    url: str
    favicon: str
    description: str

class Resources(BaseModel):
    modules: List[Module]
    ext_res: List[ExternalResource]
