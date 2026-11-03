from typing import Optional, Union, Any
from pydantic import BaseModel, Field, ConfigDict

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
    repos: list[str]

class ContributorEntry(BaseModel):
    names: dict[str, ContributorName]
    handle: str
    domain: str

class NameEntry(BaseModel):
    repos: list[str]

class UsernameHistoryEntry(BaseModel):
    names: dict[str, NameEntry]

class RelatedDataEntry(BaseModel):
    names: dict[str, NameEntry]
    handle: str
    domain: str

class NearNamesEntry(BaseModel):
    related_data: dict[str, RelatedDataEntry]

class RegisteredEmail(BaseModel):
    avatar: str
    full_name: Union[bool, str]
    username: str
    is_target: bool

class InternalContribs(BaseModel):
    all: dict = Field(default_factory=dict)
    no_github: dict = Field(default_factory=dict)

class Org(BaseModel):
    handle: str
    name: str
    link: Optional[str] = None
    cname: Optional[str] = None

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
    potential_friends: dict = Field(default_factory=dict)
    repos: list[Repo]
    languages_stats: dict[str, float]
    usernames: list[str]
    fullnames: list[str] = Field(default_factory=list)
    domains: list[str]
    ssh_keys: list[str]
    all_contribs: dict[str, ContributorEntry]
    ext_contribs: dict[str, ContributorEntry]
    internal_contribs: InternalContribs
    usernames_history: dict[str, UsernameHistoryEntry]
    near_names: dict[str, NearNamesEntry]
    emails: list[str]
    generated_emails: list[str]
    registered_emails: dict[str, RegisteredEmail]
    type: str
    hireable: Optional[Any] = None
    orgs: list[Org] = Field(default_factory=list)

    model_config = ConfigDict(populate_by_name=True)