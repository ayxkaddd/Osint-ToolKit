import os

from fastapi import APIRouter, HTTPException, Query, Depends

from typing import List, Optional

from services.funstat_service import FunstatService
from models.funstat_models import (
    ResolvedUser,
    UserStatsMin,
    UserStats,
    UsrChatInfo,
    UCommonGroupInfo,
    StickerInfo,
    UsernameUsageModel,
    GroupMember,
    ChatInfoExt
)
from services.telethon_media_service import TelethonMediaService
from dotenv import load_dotenv

load_dotenv()

funstat_service = FunstatService(
    api_key=os.getenv("FUNSTAT_API_KEY"),
    base_url=os.getenv("FUNSTAT_BASE_URL", "https://funstat.info")
)

telethon_service = TelethonMediaService()

user_router = APIRouter(prefix="/funstat/users")
group_router = APIRouter(prefix="/funstat/groups")
search_router = APIRouter(prefix="/funstat/search")
media_router = APIRouter(prefix="/funstat/media")
bot_router = APIRouter(prefix="/funstat/bot")

@user_router.get("/basic_info_by_id")
async def get_user_basic_info_by_id(
    id: List[int] = Query(...)
) -> List[ResolvedUser]:
    return await funstat_service.get_user_basic_info_by_id(id)

@user_router.get("/resolve_username")
async def resolve_username(
    name: List[str] = Query(...)
) -> List[ResolvedUser]:
    return await funstat_service.resolve_username(name)

@user_router.get("/{user_id}/stats_min")
async def get_user_stats_min(user_id: int) -> UserStatsMin:
    return await funstat_service.get_user_stats_min(user_id)

@user_router.get("/{user_id}/stats")
async def get_user_stats(user_id: int) -> UserStats:
    return await funstat_service.get_user_stats(user_id)

@user_router.get("/{user_id}/groups")
async def get_user_groups(user_id: int) -> List[UsrChatInfo]:
    return await funstat_service.get_user_groups(user_id)

@user_router.get("/{user_id}/groups_count")
async def get_user_groups_count(
    user_id: int,
    onlyMsg: bool = True
) -> int:
    return await funstat_service.get_user_groups_count(user_id, onlyMsg)

@user_router.get("/{user_id}/messages_count")
async def get_user_messages_count(user_id: int) -> int:
    return await funstat_service.get_user_messages_count(user_id)

@user_router.get("/{user_id}/messages")
async def get_user_messages(
    user_id: int,
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
    group_id: Optional[int] = None,
    text_contains: Optional[str] = None,
    media_code: Optional[int] = None
):
    return await funstat_service.get_user_messages(
        user_id=user_id,
        page=page,
        page_size=pageSize,
        group_id=group_id,
        text_contains=text_contains,
        media_code=media_code
    )

@user_router.get("/{user_id}/messages/all")
async def get_all_user_messages(
    user_id: int,
    group_id: Optional[int] = None,
    text_contains: Optional[str] = None,
    media_code: Optional[int] = None,
    max_messages: Optional[int] = None
):
    return await funstat_service.get_all_user_messages(
        user_id=user_id,
        group_id=group_id,
        text_contains=text_contains,
        media_code=media_code,
        max_messages=max_messages
    )

@user_router.get("/{user_id}/names")
async def get_user_names_history(user_id: int) -> List[UsrChatInfo]:
    return await funstat_service.get_user_names_history(user_id)

@user_router.get("/{user_id}/usernames")
async def get_user_usernames_history(user_id: int) -> List[UsrChatInfo]:
    return await funstat_service.get_user_usernames_history(user_id)

@user_router.get("/{user_id}/common_groups_stat")
async def get_user_common_groups_stat(user_id: int) -> List[UCommonGroupInfo]:
    return await funstat_service.get_user_common_groups_stat(user_id)

@user_router.get("/reputation")
async def get_user_reputation(id: int = Query(...)) -> dict:
    return await funstat_service.get_user_reputation(id)

@user_router.get("/{user_id}/stickers")
async def get_user_stickers(user_id: int) -> List[StickerInfo]:
    return await funstat_service.get_user_stickers(user_id)

@user_router.get("/username_usage")
async def search_username_usage(username: str = Query(...)) -> UsernameUsageModel:
    return await funstat_service.search_username_usage(username)

@group_router.get("/{group_id}")
async def get_group_info(group_id: int) -> dict:
    return await funstat_service.get_group_info(group_id)

@group_router.get("/{group_id}/members")
async def get_group_members(group_id: int) -> List[GroupMember]:
    return await funstat_service.get_group_members(group_id)

@group_router.get("/common_groups")
async def get_common_groups(
    id: List[int] = Query(...)
) -> List[ChatInfoExt]:
    return await funstat_service.get_common_groups(id)

@search_router.get("/text")
async def search_text(
    input: str = Query(...),
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100)
) -> dict:
    return await funstat_service.search_text(input, page, pageSize)

# @media_router.on_event("startup")
# async def startup_telethon():
#     await telethon_service.start()

@media_router.on_event("shutdown")
async def shutdown_telethon():
    await telethon_service.stop()

@media_router.post("/thumbnail/create")
async def create_thumbnail(
    chat_identifier: str = Query(..., description="Chat username (without @) or chat ID"),
    message_id: int = Query(...),
    save_original: bool = Query(False)
) -> dict:
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
) -> List[dict]:
    return await telethon_service.batch_create_thumbnails(chat_identifier, message_ids)

@media_router.get("/messages/media")
async def get_chat_media_messages(
    chat_identifier: str = Query(..., description="Chat username (without @) or chat ID"),
    limit: int = Query(100, ge=1, le=1000),
    offset_id: int = Query(0, ge=0)
) -> List[dict]:
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

    media_messages = [
        msg for msg in messages_data["messages"]
        if msg.mediaCode is not None
    ]

    thumbnails = []
    if create_thumbnails and media_messages:
        for msg in media_messages[:10]:
            try:
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

@bot_router.get("/random")
async def get_random_bot() -> dict:
    """Get random bot information"""
    return await funstat_service.get_random_bot()

analysis_router = APIRouter(prefix="/api/analysis", tags=["Analysis"])

@analysis_router.get("/user/complete_profile")
async def get_complete_user_profile(user_id: int, fetch_all_messages: bool = False) -> dict:
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

    media_messages = [
        msg for msg in messages_data["messages"]
        if msg.mediaCode is not None
    ][:10]

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
        except:
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

@media_router.get("/context/message")
async def get_message_context(
    chat_identifier: str = Query(..., description="Chat username (without @) or chat ID"),
    message_id: int = Query(..., description="Target message ID"),
    context_size: int = Query(5, ge=1, le=20, description="Number of messages before and after"),
    fetch_replies: bool = Query(True, description="Fetch reply chain")
) -> dict:
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
    messages_data = await funstat_service.get_user_messages(
        user_id=user_id,
        page=page,
        page_size=pageSize,
        group_id=group_id
    )

    enriched_messages = []
    for msg in messages_data["messages"][:10]:
        try:
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