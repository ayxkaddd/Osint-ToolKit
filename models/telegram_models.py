from pydantic import BaseModel
from typing import Optional, List

class ProfileEntry(BaseModel):
    year_month: Optional[str] = None
    url: Optional[str] = None
    vk_id: Optional[str] = None
    full_name: Optional[str] = None
    last_name: Optional[str] = None
    first_name: Optional[str] = None
    gender: Optional[str] = None
    country: Optional[str] = None
    hometown: Optional[str] = None
    city: Optional[str] = None
    last_login: Optional[str] = None
    device: Optional[str] = None
    followers: Optional[int] = None
    university: Optional[str] = None
    faculty: Optional[str] = None
    username: Optional[str] = None
    marital_status: Optional[str] = None
    normalized_name: Optional[str] = None
    education: Optional[str] = None
    avatar: Optional[str] = None
    birth_date: Optional[str] = None
    last_visit: Optional[str] = None

class VKProfileHistoryResponse(BaseModel):
    entries: List[ProfileEntry] = []
    photos: List[str] = []
