from datetime import datetime
from typing import Optional, List, Any
from pydantic import BaseModel, Field, ConfigDict

class BaseSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

class TechInfo(BaseSchema):
    request_cost: float = Field(default=0, alias="requestCost")
    current_balance: float = Field(default=0, alias="currentBalance")
    request_duration: str = Field(default="", alias="requestDuration")

class ChatInfo(BaseSchema):
    id: int
    title: str
    is_private: bool = Field(..., alias="isPrivate")
    username: Optional[str] = None

class ChatInfoExt(ChatInfo):
    is_channel: bool = Field(..., alias="isChannel")
    link: Optional[str] = None

class Paging(BaseSchema):
    total: int
    current_page: int = Field(..., alias="currentPage")
    page_size: int = Field(..., alias="pageSize")
    total_pages: int = Field(..., alias="totalPages")

class ResolvedUser(BaseSchema):
    id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    is_active: bool
    is_bot: bool
    has_premium: Optional[bool] = None

class UserStatsMin(BaseSchema):
    id: int
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    is_bot: bool = False
    is_active: bool = False
    first_msg_date: Optional[datetime] = None
    last_msg_date: Optional[datetime] = None
    total_msg_count: int
    msg_in_groups_count: int
    adm_in_groups: int
    usernames_count: int
    names_count: int
    total_groups: int

class UserStats(UserStatsMin):
    is_cyrillic_primary: Optional[bool] = None
    lang_code: Optional[str] = None
    unique_percent: Optional[float] = None
    circle_count: int
    voice_count: int
    reply_percent: float
    media_percent: float
    link_percent: float
    favorite_chat: Optional[ChatInfo] = None
    media_usage: Optional[str] = None

class UserMessage(BaseSchema):
    date: datetime
    message_id: int = Field(..., alias="messageId")
    reply_to_message_id: Optional[int] = Field(None, alias="replyToMessageId")
    media_code: Optional[int] = Field(None, alias="mediaCode")
    media_name: Optional[str] = Field(None, alias="mediaName")
    text: Optional[str] = None
    group: Optional[ChatInfo] = None

class UsrChatInfo(BaseSchema):
    chat: ChatInfo
    last_message_id: Optional[int] = Field(None, alias="lastMessageId")
    messages_count: Optional[int] = Field(None, alias="messagesCount")
    last_message: Optional[datetime] = Field(None, alias="lastMessage")
    first_message: Optional[datetime] = Field(None, alias="firstMessage")
    is_admin: bool = Field(False, alias="isAdmin")
    is_left: bool = Field(False, alias="isLeft")

class UCommonGroupInfo(BaseSchema):
    user_id: int
    common_groups: int
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    username: Optional[str] = None
    is_user_active: bool

class GroupMember(BaseSchema):
    id: Optional[int] = None
    username: Optional[str] = None
    name: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    is_admin: Optional[bool] = None
    is_active: bool = False
    today_msg: int = 0
    has_prem: Optional[bool] = None
    has_photo: bool = False
    dc_id: Optional[int] = None

class StickerInfo(BaseSchema):
    sticker_set_id: int
    last_seen: datetime
    min_seen: datetime
    resolved: Optional[datetime] = None
    title: Optional[str] = None
    short_name: Optional[str] = None
    stickers_count: Optional[int] = None

class WhoWroteText(BaseSchema):
    message_id: Optional[int] = None
    user_id: Optional[int] = None
    date: Optional[datetime] = None
    name: Optional[str] = None
    username: Optional[str] = None
    is_active: bool = False
    group: Optional[ChatInfoExt] = None
    text: Optional[str] = None

class UsernameUsageModel(BaseSchema):
    actual_users: Optional[List[ResolvedUser]] = Field(None, alias="actualUsers")
    usage_by_users_in_the_past: Optional[List[ResolvedUser]] = Field(None, alias="usageByUsersInThePast")
    actual_groups_or_channels: Optional[List[ChatInfoExt]] = Field(None, alias="actualGroupsOrChannels")
    mention_by_channel_or_group_desc: Optional[List[ChatInfoExt]] = Field(None, alias="mentionByChannelOrGroupDesc")

class ApiResponse(BaseSchema):
    success: bool
    tech: TechInfo
    data: Optional[Any] = None

class PagedResponse(ApiResponse):
    paging: Paging

class MediaThumbnail(BaseSchema):
    message_id: int
    chat_id: int
    thumbnail_url: str
    media_type: str
    generated_at: datetime
