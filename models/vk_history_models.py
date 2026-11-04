from pydantic import BaseModel
from typing import Optional

class ProfileEntry(BaseModel):
    year_month: Optional[str] = None
    url: Optional[str] = None
    vk_id: Optional[str] = None
    full_name: Optional[str] = None
    last_name: Optional[str] = None
    first_name: Optional[str] = None
    normalized_name: Optional[str] = None
    aka: Optional[str] = None
    username: Optional[str] = None
    gender: Optional[str] = None
    birth_date: Optional[str] = None
    country: Optional[str] = None
    region: Optional[str] = None
    hometown: Optional[str] = None
    city: Optional[str] = None
    email: Optional[str] = None
    mobile_phone: Optional[str] = None
    home_phone: Optional[str] = None
    icq: Optional[str] = None
    contacts: Optional[str] = None
    website: Optional[str] = None
    homepage: Optional[str] = None
    last_login: Optional[str] = None
    last_visit: Optional[str] = None
    device: Optional[str] = None
    followers: Optional[int] = None
    university: Optional[str] = None
    faculty: Optional[str] = None
    education: Optional[str] = None
    career: Optional[str] = None
    marital_status: Optional[str] = None
    family: Optional[str] = None
    interests: Optional[str] = None
    music: Optional[str] = None
    movies: Optional[str] = None
    tv: Optional[str] = None
    books: Optional[str] = None
    games: Optional[str] = None
    avatar: Optional[str] = None
    # Every photo of this snapshot (avatar is the first)
    photos: list[str] = []
    # Lines the parser doesn't know yet, under the bot's own label - never dropped
    other: dict[str, str] = {}

class VKProfileHistoryResponse(BaseModel):
    entries: list[ProfileEntry] = []
    photos: list[str] = []
    # False when the bot didn't finish before the timeout (partial data)
    complete: bool = True
    # Other bot replies (limits, "not found", errors) - shown to the user
    notices: list[str] = []
    # Periods the bot has no snapshot for ("04.2022", "2010")
    empty_periods: list[str] = []
