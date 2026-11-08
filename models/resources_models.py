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
    # dashboard grouping: breaches, accounts, domains, infrastructure, images, telegram,
    # companies, crypto, archives
    category: str = "other"
    cost: Optional[str] = None          # free / freemium / paid
    types: list[str] = []               # identifier types it takes (services/entities.py)
    # {identifier type: address with {value}} - opens the site on that identifier (pivot menu)
    search: dict[str, str] = {}

class Resources(BaseModel):
    modules: list[Module]
    ext_res: list[ExternalResource]
