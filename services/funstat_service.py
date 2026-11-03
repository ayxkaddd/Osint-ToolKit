import asyncio
import httpx
from typing import Optional, Any
from fastapi import HTTPException
import logging
from services.message_analyzer import MessageAnalyzer
from utils.config import get_setting
from models.funstat_models import (
    TechInfo,
    ResolvedUser,
    UserNamesHistory,
    UserStatsMin,
    UserStats,
    UsrChatInfo,
    UCommonGroupInfo,
    StickerInfo,
    UsernameUsageModel,
    UserMessage,
    Paging,
    WhoWroteText,
    GroupMember,
    ChatInfoExt
)

logger = logging.getLogger(__name__)


# requestCost / currentBalance from the latest response: every call reports
# them, so the balance is known without spending anything
last_tech: dict[str, Any] = {}


class FunstatService:
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        self._api_key = api_key
        self._base_url = base_url

    # Read per call so a key saved in Settings applies without a restart
    @property
    def api_key(self) -> str:
        return self._api_key or get_setting("FUNSTAT_API_KEY", "") or ""

    @property
    def base_url(self) -> str:
        return self._base_url or get_setting("FUNSTAT_BASE_URL", "") or "https://telelog.org"

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict] = None,
        json_data: Optional[dict] = None
    ) -> dict[str, Any]:
        """Make HTTP request to Funstat API"""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                url = f"{self.base_url}{endpoint}"

                # Never log self.headers: it carries the API bearer token
                logger.debug("Funstat %s %s params=%s", method, endpoint, params)

                response = await client.request(
                    method=method,
                    url=url,
                    headers=self.headers,
                    params=params,
                    json=json_data
                )

                response.raise_for_status()
                data = response.json()
                tech = data.get("tech") if isinstance(data, dict) else None
                if isinstance(tech, dict) and "currentBalance" in tech:
                    last_tech.update(balance=tech.get("currentBalance"), last_cost=tech.get("requestCost"),
                                     endpoint=endpoint.split("?")[0])
                return data

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error: {e.response.status_code} - {e.response.text}")
            raise HTTPException(
                status_code=e.response.status_code,
                detail=f"Funstat API error: {e.response.text}"
            )
        except httpx.RequestError as e:
            logger.error(f"Request error: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Request to Funstat API failed: {str(e)}"
            )
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Unexpected error: {str(e)}"
            )

    # ==================== USER ENDPOINTS ====================

    async def get_user_basic_info_by_id(self, user_ids: list[int]) -> list[ResolvedUser]:
        """Get user info by telegram ID. Cost 0.10 per success found user info"""
        response = await self._make_request(
            "GET",
            "/api/v1/users/basic_info_by_id",
            params={"id": user_ids}
        )
        return [ResolvedUser(**user) for user in response.get("data", [])]

    async def resolve_username(self, usernames: list[str]) -> list[ResolvedUser]:
        """Cost 0.10 per success found user info"""
        response = await self._make_request(
            "GET",
            "/api/v1/users/resolve_username",
            params={"name": usernames}
        )
        return [ResolvedUser(**user) for user in response.get("data", [])]

    async def get_user_stats_min(self, user_id: int) -> UserStatsMin:
        """User basic stats (known data in db) FREE"""
        response = await self._make_request(
            "GET",
            f"/api/v1/users/{user_id}/stats_min"
        )
        return UserStatsMin(**response)

    async def get_user_stats(self, user_id: int) -> UserStats:
        """Full user stats COST: 1"""
        response = await self._make_request(
            "GET",
            f"/api/v1/users/{user_id}/stats"
        )
        return UserStats(**response.get("data", {}))

    async def get_user_groups(self, user_id: int) -> list[UsrChatInfo]:
        """Known user groups (COST: 5)"""
        response = await self._make_request(
            "GET",
            f"/api/v1/users/{user_id}/groups"
        )
        return [UsrChatInfo(**group) for group in response.get("data", [])]

    async def get_user_groups_count(self, user_id: int, only_msg: bool = True) -> int:
        """Total count user groups (FREE)"""
        response = await self._make_request(
            "GET",
            f"/api/v1/users/{user_id}/groups_count",
            params={"onlyMsg": only_msg}
        )
        return response

    async def get_user_messages_count(self, user_id: int) -> int:
        """Total count user messages (FREE)"""
        response = await self._make_request(
            "GET",
            f"/api/v1/users/{user_id}/messages_count"
        )
        return response

    async def get_user_messages(
        self,
        user_id: int,
        page: int = 1,
        page_size: int = 20,
        group_id: Optional[int] = None,
        text_contains: Optional[str] = None,
        media_code: Optional[int] = None
    ) -> dict[str, Any]:
        """Get user messages (COST: 10 per user if found and user has MORE THAN 100 messages)"""
        params = {
            "page": page,
            "pageSize": page_size
        }
        if group_id:
            params["group_id"] = group_id
        if text_contains:
            params["text_contains"] = text_contains
        if media_code is not None:
            params["media_code"] = media_code

        response = await self._make_request(
            "GET",
            f"/api/v1/users/{user_id}/messages",
            params=params
        )


        return {
            "messages": [UserMessage(**msg) for msg in response.get("data", [])],
            "paging": Paging(**response.get("paging", {})),
            "tech": TechInfo(**response.get("tech", {}))
        }

    async def get_all_user_messages(
        self,
        user_id: int,
        group_id: Optional[int] = None,
        text_contains: Optional[str] = None,
        media_code: Optional[int] = None,
        max_messages: Optional[int] = None
    ) -> dict[str, Any]:
        """Get ALL user messages by fetching all pages"""
        all_messages = []
        page = 1
        page_size = 100  # Max page size for efficiency
        total_fetched = 0

        logger.info(f"Fetching all messages for user {user_id}")

        while True:
            response = await self.get_user_messages(
                user_id=user_id,
                page=page,
                page_size=page_size,
                group_id=group_id,
                text_contains=text_contains,
                media_code=media_code
            )

            messages = response["messages"]
            paging = response["paging"]
            tech = response["tech"]

            all_messages.extend(messages)
            total_fetched += len(messages)

            logger.info(f"Fetched page {page}/{paging.total_pages}, got {len(messages)} messages, total: {total_fetched}")

            # Check if we've reached the max or all pages
            if max_messages and total_fetched >= max_messages:
                all_messages = all_messages[:max_messages]
                break

            if page >= paging.total_pages:
                break

            page += 1

        # Regex-heavy analysis of every message: keep it off the event loop
        message_analyzer = MessageAnalyzer()
        message_analysis_result = await asyncio.to_thread(
            message_analyzer.analyze_conversation,
            messages=[msg.model_dump(by_alias=True) if hasattr(msg, 'model_dump') else msg.dict(by_alias=True) for msg in all_messages],
            include_message_analysis=True,
        )

        return {
            "messages": all_messages,
            "messages_analysis": message_analysis_result,
            "total": len(all_messages),
            "tech": tech
        }

    async def get_user_names_history(self, user_id: int) -> list[UserNamesHistory]:
        """User (firstname + lastname) history COST: 3"""
        response = await self._make_request(
            "GET",
            f"/api/v1/users/{user_id}/names"
        )
        return [UserNamesHistory(**item) for item in response.get("data", [])]

    async def get_user_usernames_history(self, user_id: int) -> list[UserNamesHistory]:
        """@usernames history COST: 3"""
        response = await self._make_request(
            "GET",
            f"/api/v1/users/{user_id}/usernames"
        )
        return [UserNamesHistory(**item) for item in response.get("data", [])]

    async def get_user_common_groups_stat(self, user_id: int) -> list[UCommonGroupInfo]:
        """Return users who has common groups with specified user [cost 5]"""
        response = await self._make_request(
            "GET",
            f"/api/v1/users/{user_id}/common_groups_stat"
        )
        return [UCommonGroupInfo(**item) for item in response.get("data", [])]

    async def get_user_reputation(self, user_id: int) -> dict[str, Any]:
        """Return user reputation information [FREE]"""
        response = await self._make_request(
            "GET",
            "/api/v1/users/reputation",
            params={"id": user_id}
        )
        return response

    async def get_user_stickers(self, user_id: int) -> list[StickerInfo]:
        """Sticker packs created by user [COST 1 if success found any]"""
        response = await self._make_request(
            "GET",
            f"/api/v1/users/{user_id}/stickers"
        )
        return [StickerInfo(**item) for item in response.get("data", [])]

    async def search_username_usage(self, username: str) -> UsernameUsageModel:
        """Search username usage [COST 0.1 EACH request]"""
        response = await self._make_request(
            "GET",
            "/api/v1/users/username_usage",
            params={"username": username}
        )
        return UsernameUsageModel(**response.get("data", {}))

    # ==================== GROUP ENDPOINTS ====================

    async def get_group_info(self, group_id: int) -> dict[str, Any]:
        """Group basic info, links and today stats COST 0.01"""
        response = await self._make_request(
            "GET",
            f"/api/v1/groups/{group_id}"
        )
        return response

    async def get_group_members(self, group_id: int) -> list[GroupMember]:
        """Group members [COST 15 each request]"""
        response = await self._make_request(
            "GET",
            f"/api/v1/groups/{group_id}/members"
        )
        return [GroupMember(**member) for member in response.get("data", [])]

    async def get_common_groups(self, user_ids: list[int]) -> list[ChatInfoExt]:
        """Return common groups specified users [COST 0.5 each request]"""
        response = await self._make_request(
            "GET",
            "/api/v1/groups/common_groups",
            params={"id": user_ids}
        )
        return [ChatInfoExt(**group) for group in response.get("data", [])]

    # ==================== TEXT SEARCH ENDPOINTS ====================

    async def search_text(
        self,
        search_input: str,
        page: int = 1,
        page_size: int = 20
    ) -> dict[str, Any]:
        """Search who/when/where wrote specified text message [COST 0.1 each request]"""
        response = await self._make_request(
            "GET",
            "/api/v1/text/search",
            params={
                "input": search_input,
                "page": page,
                "pageSize": page_size
            }
        )

        data = response.get("data", {})
        return {
            "results": [WhoWroteText(**item) for item in data.get("data", [])],
            "total": data.get("total", 0),
            "currentPage": data.get("currentPage", page),
            "pageSize": data.get("pageSize", page_size),
            "totalPages": data.get("totalPages", 0),
            "isLastPage": data.get("isLastPage", False),
            "tech": TechInfo(**response.get("tech", {}))
        }

    # ==================== BOT ENDPOINTS ====================

    async def get_random_bot(self) -> dict[str, Any]:
        """Get random bot"""
        response = await self._make_request(
            "GET",
            "/api/v1/bot/random"
        )
        return response
