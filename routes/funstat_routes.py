import logging
import re
import os
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from typing import List, Optional
from services.funstat_service import FunstatService
from models.funstat_models import (
    CombinedUserHistory,
    MessageContext,
    ResolvedUser,
    ThumbnailResult,
    UserNamesHistory,
    UserStatsMin,
    UserStats,
    UsrChatInfo,
    UCommonGroupInfo,
    StickerInfo,
    UsernameUsageModel,
    GroupMember,
    ChatInfoExt
)
from services.telethon_media_service import FULL_MEDIA_DIR, THUMBNAIL_DIR, MediaUnavailable, TelethonMediaService
from utils.telegram_client import TelegramNotAuthorized
from services import tme_service

from dotenv import load_dotenv
from utils.investigation_decorator import save_investigation

load_dotenv()
logger = logging.getLogger(__name__)

funstat_service = FunstatService()

telethon_service = TelethonMediaService(
    api_id=int(os.getenv("TG_API_ID", 123)),
    api_hash=os.getenv("TG_API_HASH", "your_api_hash"),
    phone=os.getenv("TG_PHONE_NUMBER", "your_phone_number")
)

user_router = APIRouter(prefix="/funstat/users", tags=["Users"])
group_router = APIRouter(prefix="/funstat/groups", tags=["Groups"])
search_router = APIRouter(prefix="/funstat/search", tags=["Search"])
media_router = APIRouter(prefix="/funstat/media", tags=["Media"])
bot_router = APIRouter(prefix="/funstat/bot", tags=["Bot"])


@bot_router.get("/balance")
async def funstat_balance():
    """Balance from the latest Funstat response (null until a request is made)."""
    from services.funstat_service import last_tech
    return {"balance": last_tech.get("balance"), "last_cost": last_tech.get("last_cost"),
            "endpoint": last_tech.get("endpoint")}

# ==================== USER ROUTES ====================

@user_router.get("/basic_info_by_id")
@save_investigation(service_name="funstat", method_name="lookup_user", skip_if=lambda users: not users)
async def get_user_basic_info_by_id(
    id: List[int] = Query(...)
) -> List[ResolvedUser]:
    """Get user info by telegram ID. Cost 0.10 per success found user info"""
    return await funstat_service.get_user_basic_info_by_id(id)

@user_router.get("/resolve_username")
@save_investigation(service_name="funstat", method_name="lookup_user", skip_if=lambda users: not users)
async def resolve_username(
    name: List[str] = Query(...)
) -> List[ResolvedUser]:
    """Resolve username to user info. Cost 0.10 per success"""
    return await funstat_service.resolve_username(name)

@user_router.get("/tme_profile")
@save_investigation(service_name="funstat", method_name="tme_profile")
async def get_tme_profile(username: str = Query(..., description="Telegram username or t.me link")):
    """Public name, bio and avatar from the t.me preview page (free, no login)."""
    try:
        return await tme_service.fetch_profile(username)
    except tme_service.TmeError as e:
        raise HTTPException(status_code=400 if "valid" in str(e) else 502, detail=str(e))

@user_router.get("/{user_id}/stats_min")
@save_investigation(service_name="funstat", method_name="stats_min")
async def get_user_stats_min(user_id: int) -> UserStatsMin:
    """Get basic user stats (FREE)"""
    return await funstat_service.get_user_stats_min(user_id)

@user_router.get("/{user_id}/stats")
@save_investigation(service_name="funstat", method_name="stats")
async def get_user_stats(user_id: int) -> UserStats:
    """Get full user stats (COST: 1)"""
    return await funstat_service.get_user_stats(user_id)

@user_router.get("/{user_id}/groups")
@save_investigation(service_name="funstat", method_name="groups")
async def get_user_groups(user_id: int) -> List[UsrChatInfo]:
    """Get user's groups (COST: 5)"""
    return await funstat_service.get_user_groups(user_id)

@user_router.get("/{user_id}/groups_count")
async def get_user_groups_count(
    user_id: int,
    onlyMsg: bool = True
) -> int:
    """Get total count of user's groups (FREE)"""
    return await funstat_service.get_user_groups_count(user_id, onlyMsg)

@user_router.get("/{user_id}/messages_count")
async def get_user_messages_count(user_id: int) -> int:
    """Get total count of user's messages (FREE)"""
    return await funstat_service.get_user_messages_count(user_id)

@user_router.get("/{user_id}/messages")
@save_investigation(service_name="funstat", method_name="messages")
async def get_user_messages(
    user_id: int,
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
    group_id: Optional[int] = None,
    text_contains: Optional[str] = None,
    media_code: Optional[int] = None
):
    """
    Get user messages with optional filters
    COST: 10 per user if found and user has MORE THAN 100 messages
    """
    return await funstat_service.get_user_messages(
        user_id=user_id,
        page=page,
        page_size=pageSize,
        group_id=group_id,
        text_contains=text_contains,
        media_code=media_code
    )

@user_router.get("/{user_id}/messages/all")
@save_investigation(service_name="funstat", method_name="all_messages")
async def get_all_user_messages(
    user_id: int,
    group_id: Optional[int] = None,
    text_contains: Optional[str] = None,
    media_code: Optional[int] = None,
    max_messages: Optional[int] = None
):
    """
    Get ALL user messages by fetching all pages
    COST: 10 per user if found and user has MORE THAN 100 messages
    """
    return await funstat_service.get_all_user_messages(
        user_id=user_id,
        group_id=group_id,
        text_contains=text_contains,
        media_code=media_code,
        max_messages=max_messages
    )

@user_router.get("/{user_id}/names")
@save_investigation(service_name="funstat", method_name="names_history")
async def get_user_names_history(user_id: int) -> List[UserNamesHistory]:
    """Get user's name history (COST: 3)"""
    return await funstat_service.get_user_names_history(user_id)

@user_router.get("/{user_id}/user_names_history")
@save_investigation(service_name="funstat", method_name="names_and_usernames_history")
async def get_user_names_and_usernames_history(
    user_id: int,
) -> List[CombinedUserHistory]:
    """Get user's name and @username history (COST: 6)"""

    names_history = await funstat_service.get_user_names_history(user_id)
    usernames_history = await funstat_service.get_user_usernames_history(user_id)

    combined_history = [
        CombinedUserHistory(
            value=item.name,
            type="name",
            date_time=item.date_time,
        )
        for item in names_history
    ] + [
        CombinedUserHistory(
            value=item.name,
            type="username",
            date_time=item.date_time,
        )
        for item in usernames_history
    ]

    return sorted(combined_history, key=lambda x: x.date_time)

@user_router.get("/{user_id}/usernames")
@save_investigation(service_name="funstat", method_name="usernames_history")
async def get_user_usernames_history(user_id: int) -> List[UserNamesHistory]:
    """Get user's @username history (COST: 3)"""
    return await funstat_service.get_user_usernames_history(user_id)

@user_router.get("/{user_id}/common_groups_stat")
@save_investigation(service_name="funstat", method_name="common_groups_stat")
async def get_user_common_groups_stat(user_id: int) -> List[UCommonGroupInfo]:
    """Get users who share common groups (COST: 5)"""
    return await funstat_service.get_user_common_groups_stat(user_id)

@user_router.get("/reputation")
@save_investigation(service_name="funstat", method_name="reputation")
async def get_user_reputation(id: int = Query(...)) -> dict:
    """Get user reputation information (FREE)"""
    return await funstat_service.get_user_reputation(id)

@user_router.get("/{user_id}/stickers")
async def get_user_stickers(user_id: int) -> List[StickerInfo]:
    """Get sticker packs created by user (COST: 1 if found)"""
    return await funstat_service.get_user_stickers(user_id)

@user_router.get("/username_usage")
@save_investigation(service_name="funstat", method_name="username_usage")
async def search_username_usage(username: str = Query(...)) -> UsernameUsageModel:
    """Search username usage across users and groups (COST: 0.1)"""
    return await funstat_service.search_username_usage(username)

# ==================== GROUP ROUTES ====================

# Static paths must be registered before the /{group_id} catch-all so they
# are not shadowed by the dynamic segment.
@group_router.get("/common_groups")
@save_investigation(service_name="funstat", method_name="common_groups")
async def get_common_groups(
    id: List[int] = Query(...)
) -> List[ChatInfoExt]:
    """Get common groups for specified users (COST: 0.5)"""
    return await funstat_service.get_common_groups(id)

@group_router.get("/{group_id}")
@save_investigation(service_name="funstat", method_name="lookup_group")
async def get_group_info(group_id: int) -> dict:
    """Get group basic info, links and today stats (COST: 0.01)"""
    return await funstat_service.get_group_info(group_id)

@group_router.get("/{group_id}/members")
@save_investigation(service_name="funstat", method_name="group_members")
async def get_group_members(group_id: int) -> List[GroupMember]:
    """Get group members (COST: 15)"""
    return await funstat_service.get_group_members(group_id)

# ==================== SEARCH ROUTES ====================

@search_router.get("/text")
@save_investigation(service_name="funstat", method_name="search_text")
async def search_text(
    input: str = Query(...),
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100)
) -> dict:
    """Search who/when/where wrote specified text (COST: 0.1)"""
    return await funstat_service.search_text(input, page, pageSize)

# ==================== MEDIA ROUTES ====================

@media_router.on_event("startup")
async def startup_telethon():
    """Connect Telethon on startup. Failure (no session, locked session file,
    no network) must not stop the whole app - media endpoints retry lazily."""
    try:
        await telethon_service.start()
    except Exception as e:
        logging.getLogger(__name__).warning("Telegram media client not started: %s", e)

@media_router.on_event("shutdown")
async def shutdown_telethon():
    """Stop Telethon client on application shutdown"""
    await telethon_service.stop()

@media_router.get("/thumbnails/{filename}")
async def get_thumbnail(filename: str):
    """Serve a generated thumbnail (behind login, unlike /static)."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+\.jpg", filename):
        raise HTTPException(status_code=404, detail="Not found")
    path = os.path.join(THUMBNAIL_DIR, filename)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})

@media_router.get("/full")
async def get_full_media(
    chat_identifier: str = Query(..., description="Chat username (without @) or chat ID"),
    message_id: int = Query(...)
) -> dict:
    """Download a message's original photo or video through the Telegram session."""
    try:
        return await telethon_service.download_full_media(chat_identifier, message_id)
    except MediaUnavailable as e:
        raise HTTPException(status_code=404, detail=str(e))
    except TelegramNotAuthorized as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        logger.exception("Full media download failed for %s/%s", chat_identifier, message_id)
        raise HTTPException(status_code=502, detail=f"Telegram download failed: {e}")

@media_router.get("/avatars/{filename}")
async def get_avatar(filename: str):
    """Serve a saved t.me avatar (behind login)."""
    if not re.fullmatch(r"[a-z0-9_]+_[0-9a-f]{16}\.jpg", filename):
        raise HTTPException(status_code=404, detail="Not found")
    path = os.path.join(tme_service.AVATAR_DIR, filename)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})

@media_router.get("/files/{filename}")
async def get_media_file(filename: str):
    """Serve a downloaded original (behind login; supports range requests for video)."""
    if not re.fullmatch(r"[A-Za-z0-9_-]+\.(jpg|png|webp|gif|mp4|webm|mov)", filename):
        raise HTTPException(status_code=404, detail="Not found")
    path = os.path.join(FULL_MEDIA_DIR, filename)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path, headers={"Cache-Control": "private, max-age=86400"})

@media_router.post("/thumbnail/create")
async def create_thumbnail(
    chat_identifier: str = Query(..., description="Chat username (without @) or chat ID"),
    message_id: int = Query(...),
    save_original: bool = Query(False)
) -> dict:
    """Create thumbnail from message media (supports username or ID)"""
    result = await telethon_service.download_and_create_thumbnail(
        chat_identifier,
        message_id,
        save_original
    )

    if not result:
        raise HTTPException(
            status_code=404,
            detail="No media found in the specified message"
        )

    return result

@media_router.post("/thumbnail/batch")
async def create_thumbnails_batch(
    chat_identifier: str = Query(..., description="Chat username (without @) or chat ID"),
    message_ids: List[int] = Query(...)
) -> List[ThumbnailResult]:
    """Create thumbnails for multiple messages (supports username or ID)"""
    result = await telethon_service.batch_create_thumbnails(chat_identifier, message_ids)
    return result

@media_router.get("/messages/media")
async def get_chat_media_messages(
    chat_identifier: str = Query(..., description="Chat username (without @) or chat ID"),
    limit: int = Query(100, ge=1, le=1000),
    offset_id: int = Query(0, ge=0)
) -> List[dict]:
    """Get all messages with media from a chat (supports username or ID)"""
    return await telethon_service.get_chat_media_messages(
        chat_identifier=chat_identifier,
        limit=limit,
        offset_id=offset_id
    )

@media_router.get("/process/user_messages")
async def process_user_messages_media(
    user_id: int = Query(...),
    group_id: Optional[int] = None,
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
    create_thumbnails: bool = Query(True),
    fetch_all: bool = Query(False, description="Fetch all messages instead of paginated")
) -> dict:
    """
    Get user messages and optionally create thumbnails for media
    Combines Funstat API with Telethon media processing
    """
    # Get messages from Funstat API
    if fetch_all:
        messages_data = await funstat_service.get_all_user_messages(
            user_id=user_id,
            group_id=group_id
        )
        paging = None
    else:
        messages_data = await funstat_service.get_user_messages(
            user_id=user_id,
            page=page,
            page_size=pageSize,
            group_id=group_id
        )
        paging = messages_data.get("paging")

    # Filter messages with media
    media_messages = [
        msg for msg in messages_data["messages"]
        if msg.mediaCode is not None
    ]

    # Create thumbnails if requested
    thumbnails = []
    if create_thumbnails and media_messages:
        for msg in media_messages[:10]:  # Limit to first 10 for performance
            try:
                # Use username if available, otherwise use ID
                chat_identifier = msg.group.username if msg.group.username else str(msg.group.id)

                thumbnail = await telethon_service.download_and_create_thumbnail(
                    chat_identifier=chat_identifier,
                    message_id=msg.messageId
                )
                if thumbnail:
                    thumbnails.append(thumbnail)
            except Exception as e:
                print(f"Failed to create thumbnail for message {msg.messageId}: {e}")

    return {
        "messages": messages_data["messages"],
        "media_count": len(media_messages),
        "thumbnails": thumbnails,
        "paging": paging,
        "tech": messages_data.get("tech")
    }

# ==================== BOT ROUTES ====================

@bot_router.get("/random")
async def get_random_bot() -> dict:
    """Get random bot information"""
    return await funstat_service.get_random_bot()

# ==================== COMBINED ANALYSIS ROUTES ====================

analysis_router = APIRouter(prefix="/api/analysis", tags=["Analysis"])

@analysis_router.get("/user/complete_profile")
async def get_complete_user_profile(user_id: int, fetch_all_messages: bool = False) -> dict:
    """
    Get complete user profile including stats, groups, and recent media
    Combines multiple API calls for comprehensive analysis
    """
    # Gather all user data
    stats = await funstat_service.get_user_stats(user_id)
    groups = await funstat_service.get_user_groups(user_id)

    if fetch_all_messages:
        messages_data = await funstat_service.get_all_user_messages(
            user_id=user_id
        )
    else:
        messages_data = await funstat_service.get_user_messages(
            user_id=user_id,
            page=1,
            page_size=50
        )

    # Get messages with media
    media_messages = [
        msg for msg in messages_data["messages"]
        if msg.mediaCode is not None
    ][:10]  # Limit to 10 most recent

    # Create thumbnails for recent media
    thumbnails = []
    for msg in media_messages:
        try:
            chat_identifier = msg.group.username if msg.group.username else str(msg.group.id)

            thumbnail = await telethon_service.download_and_create_thumbnail(
                chat_identifier=chat_identifier,
                message_id=msg.messageId
            )
            if thumbnail:
                thumbnails.append(thumbnail)
        except Exception:
            continue

    return {
        "user_id": user_id,
        "stats": stats,
        "total_groups": len(groups),
        "top_groups": groups[:5],
        "recent_messages_count": len(messages_data["messages"]),
        "media_messages_count": len(media_messages),
        "recent_thumbnails": thumbnails
    }


# Add these new endpoints to your media_router in routes/funstat_routes.py

@media_router.get("/context/message")
async def get_message_context(
    chat_identifier: str = Query(..., description="Chat username (without @) or chat ID"),
    message_id: int = Query(..., description="Target message ID"),
    context_size: int = Query(5, ge=1, le=20, description="Number of messages before and after"),
    fetch_replies: bool = Query(True, description="Fetch reply chain")
) -> MessageContext:
    """
    Get conversation context around a specific message

    Returns:
        - target_message: The requested message
        - previous_messages: Messages before target (118-122 for message 123)
        - next_messages: Messages after target (124-128 for message 123)
        - reply_chain: Messages in reply thread if target replies to something
    """
    context = await telethon_service.get_message_context(
        chat_identifier=chat_identifier,
        message_id=message_id,
        context_size=context_size,
        fetch_replies=fetch_replies
    )

    if not context:
        raise HTTPException(
            status_code=404,
            detail=f"Message {message_id} not found in chat {chat_identifier}"
        )

    return context


@media_router.get("/context/batch")
async def get_batch_message_contexts(
    chat_identifier: str = Query(..., description="Chat username (without @) or chat ID"),
    message_ids: List[int] = Query(..., description="List of message IDs"),
    context_size: int = Query(5, ge=1, le=20, description="Number of messages before and after"),
    fetch_replies: bool = Query(True, description="Fetch reply chains")
) -> List[dict]:
    """
    Get conversation contexts for multiple messages
    Useful for analyzing multiple conversations at once
    """
    contexts = await telethon_service.get_batch_message_contexts(
        chat_identifier=chat_identifier,
        message_ids=message_ids,
        context_size=context_size,
        fetch_replies=fetch_replies
    )

    return contexts


@media_router.get("/context/thread")
async def get_conversation_thread(
    chat_identifier: str = Query(..., description="Chat username (without @) or chat ID"),
    message_id: int = Query(..., description="Target message ID"),
    include_context: bool = Query(True, description="Include surrounding messages"),
    context_size: int = Query(5, ge=1, le=20, description="Number of messages before/after if include_context=True")
) -> dict:
    """
    Get a complete conversation thread including reply chain and context

    This is a comprehensive endpoint that combines:
    - The target message
    - All messages it replies to (reply chain)
    - Surrounding messages for context
    """
    thread = await telethon_service.get_conversation_thread(
        chat_identifier=chat_identifier,
        message_id=message_id,
        include_context=include_context,
        context_size=context_size
    )

    if not thread:
        raise HTTPException(
            status_code=404,
            detail=f"Message {message_id} not found in chat {chat_identifier}"
        )

    return thread


@media_router.get("/context/user_messages_with_context")
async def get_user_messages_with_context(
    user_id: int = Query(...),
    group_id: Optional[int] = None,
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
    context_size: int = Query(5, ge=1, le=20),
    fetch_replies: bool = Query(True)
) -> dict:
    """
    Get user messages from Funstat API and enrich them with conversation context

    This combines:
    1. Funstat API to find user messages
    2. Telethon to fetch context around each message

    Perfect for analyzing user behavior in conversations
    """
    # Get messages from Funstat API
    messages_data = await funstat_service.get_user_messages(
        user_id=user_id,
        page=page,
        page_size=pageSize,
        group_id=group_id
    )

    # Enrich with context for each message
    enriched_messages = []
    for msg in messages_data["messages"][:10]:  # Limit to first 10 for performance
        try:
            # Use username if available, otherwise use ID
            chat_identifier = msg.group.username if msg.group.username else str(msg.group.id)

            context = await telethon_service.get_message_context(
                chat_identifier=chat_identifier,
                message_id=msg.messageId,
                context_size=context_size,
                fetch_replies=fetch_replies
            )

            enriched_messages.append({
                "funstat_data": msg.dict(),
                "context": context
            })
        except Exception as e:
            print(f"Failed to get context for message {msg.messageId}: {e}")
            enriched_messages.append({
                "funstat_data": msg.dict(),
                "context": None,
                "error": str(e)
            })

    return {
        "enriched_messages": enriched_messages,
        "total_messages": len(messages_data["messages"]),
        "enriched_count": len([m for m in enriched_messages if m.get("context")]),
        "paging": messages_data.get("paging"),
        "tech": messages_data.get("tech")
    }


# Example usage endpoint that demonstrates the feature
@media_router.get("/context/example")
async def context_example() -> dict:
    """
    Example demonstrating how to use the context API

    This shows what you'd get for a message in a group
    """
    return {
        "description": "Conversation context scraper for Telegram messages",
        "endpoints": {
            "/context/message": {
                "description": "Get context around a single message",
                "example": {
                    "chat_identifier": "group123",
                    "message_id": 123,
                    "context_size": 5,
                    "fetch_replies": True
                },
                "returns": {
                    "target_message": "Message 123",
                    "previous_messages": "Messages 118-122",
                    "next_messages": "Messages 124-128",
                    "reply_chain": "Messages that 123 replies to (if any)"
                }
            },
            "/context/batch": {
                "description": "Get contexts for multiple messages",
                "use_case": "Analyze multiple conversations at once"
            },
            "/context/thread": {
                "description": "Get complete conversation thread",
                "use_case": "Deep dive into a specific discussion"
            },
            "/context/user_messages_with_context": {
                "description": "Combine Funstat user messages with conversation context",
                "use_case": "Analyze user behavior in conversations"
            }
        },
        "features": [
            "Fetches N messages before and after target",
            "Recursively fetches reply chains",
            "Handles reply-to relationships",
            "Supports batch processing",
            "Works with usernames or chat IDs"
        ]
    }