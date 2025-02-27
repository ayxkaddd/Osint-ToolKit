from typing import List, Dict, Optional, Union, Any
from pydantic import BaseModel, Field

class Repo(BaseModel):
    name: str
    main_language: Optional[str] = None
    stars: int
    forks: int
    is_empty: bool
    is_fork: bool
    is_mirror: bool
    is_source: bool
    is_archived: bool
    is_private: bool

class ContributorName(BaseModel):
    repos: List[str]

class ContributorEntry(BaseModel):
    names: Dict[str, ContributorName]
    handle: str
    domain: str

class NameEntry(BaseModel):
    repos: List[str]

class UsernameHistoryEntry(BaseModel):
    names: Dict[str, NameEntry]

class RelatedDataEntry(BaseModel):
    names: Dict[str, NameEntry]
    handle: str
    domain: str

class NearNamesEntry(BaseModel):
    related_data: Dict[str, RelatedDataEntry]

class RegisteredEmail(BaseModel):
    avatar: str
    full_name: Union[bool, str]
    username: str
    is_target: bool

class InternalContribs(BaseModel):
    all: Dict = Field(default_factory=dict)
    no_github: Dict = Field(default_factory=dict)

class User(BaseModel):
    username: str
    name: str
    id: int
    is_site_admin: bool
    is_hireable: bool
    company: Optional[str] = None
    blog: Optional[str] = None
    location: Optional[str] = None
    bio: Optional[str] = None
    twitter: Optional[str] = None
    nb_public_repos: int = Field(alias="nb_public_repos")
    nb_followers: int = Field(alias="nb_followers")
    nb_following: int = Field(alias="nb_following")
    created_at: str
    updated_at: str
    avatar_url: str
    is_default_avatar: bool
    nb_ext_contribs: int = Field(alias="nb_ext_contribs")
    potential_friends: Dict = Field(default_factory=dict)
    repos: List[Repo]
    languages_stats: Dict[str, float]
    usernames: List[str]
    fullnames: List[str] = Field(default_factory=list)
    domains: List[str]
    ssh_keys: List[str]
    all_contribs: Dict[str, ContributorEntry]
    ext_contribs: Dict[str, ContributorEntry]
    internal_contribs: InternalContribs
    usernames_history: Dict[str, UsernameHistoryEntry]
    near_names: Dict[str, NearNamesEntry]
    emails: List[str]
    generated_emails: List[str]
    registered_emails: Dict[str, RegisteredEmail]
    type: str
    hireable: Optional[Any] = None
    orgs: List[str] = Field(default_factory=list)

    class Config:
        populate_by_name = True