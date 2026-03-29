from telethon import TelegramClient
from telethon.tl.types import (
    MessageMediaPhoto, MessageMediaDocument,
    PhotoSize, PhotoCachedSize
)
from PIL import Image
import io
import os
import logging
import asyncio
import aiofiles
import re
from typing import Dict, List, Optional, Tuple, Any, Union
from datetime import datetime
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, asdict
from collections import OrderedDict
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class MessageContext:
    """Structured message context data"""
    chat_id: str
    target_message: Dict[str, Any]
    previous_messages: List[Dict[str, Any]]
    next_messages: List[Dict[str, Any]]
    reply_chain: List[Dict[str, Any]]
    context_size: int
    total_messages: int

from models.funstat_models import ThumbnailResult

class LRUCache:
    """Thread-safe LRU cache implementation"""

    def __init__(self, max_size: int = 1000):
        self.cache = OrderedDict()
        self.max_size = max_size
        self.lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[Any]:
        async with self.lock:
            if key in self.cache:
                # Move to end (most recently used)
                self.cache.move_to_end(key)
                return self.cache[key]
            return None

    async def set(self, key: str, value: Any):
        async with self.lock:
            if key in self.cache:
                self.cache.move_to_end(key)
            else:
                self.cache[key] = value
                if len(self.cache) > self.max_size:
                    # Remove oldest item
                    self.cache.popitem(last=False)

    async def clear(self):
        async with self.lock:
            self.cache.clear()


class TelethonMediaService:
    _instance: Optional['TelethonMediaService'] = None
    _lock = asyncio.Lock()

    def __init__(
        self,
        api_id: int,
        api_hash: str,
        phone: str,
        session_name: str = "telegram_session",
        max_concurrent_requests: int = 10,
        thumbnail_cache_size: int = 1000,
        entity_cache_size: int = 500,
        thread_pool_workers: int = 4
    ):
        load_dotenv()

        # Telegram client configuration
        self.api_id = int(os.environ.get("TELEGRAM_API_ID", api_id))
        self.api_hash = os.environ.get("TELEGRAM_API_HASH", api_hash)
        self.phone = phone
        self.session_name = session_name

        # Client instance (initialized in start())
        self.client: Optional[TelegramClient] = None
        self._client_started = False
        self._start_lock = asyncio.Lock()

        # Directory configuration
        self.thumbnail_dir = "static/thumbnails"
        os.makedirs(self.thumbnail_dir, exist_ok=True)

        # Caching layers
        self._entity_cache = LRUCache(max_size=entity_cache_size)
        self._thumbnail_cache = LRUCache(max_size=thumbnail_cache_size)
        self._message_cache = LRUCache(max_size=1000)  # Short-lived message cache

        # Concurrency control
        self._semaphore = asyncio.Semaphore(max_concurrent_requests)
        self._entity_lock = asyncio.Lock()

        # Thread pool for CPU-bound operations
        self._thread_pool = ThreadPoolExecutor(max_workers=thread_pool_workers)

        logger.info(
            f"TelethonMediaService initialized: "
            f"max_concurrent={max_concurrent_requests}, "
            f"thread_pool={thread_pool_workers}"
        )

    @classmethod
    async def get_instance(
        cls,
        api_id: int = None,
        api_hash: str = None,
        phone: str = None,
        **kwargs
    ) -> 'TelethonMediaService':
        """
        Get singleton instance of TelethonMediaService

        Thread-safe singleton pattern ensuring single client instance
        """
        if cls._instance is None:
            async with cls._lock:
                if cls._instance is None:
                    if not all([api_id, api_hash, phone]):
                        raise ValueError(
                            "First call to get_instance() requires "
                            "api_id, api_hash, and phone"
                        )
                    cls._instance = cls(api_id, api_hash, phone, **kwargs)
                    await cls._instance.start()
        return cls._instance

    async def start(self):
        async with self._start_lock:
            if self._client_started:
                return

            # Validate all required credentials before attempting connection
            missing = []
            if not self.api_id:
                missing.append("TELEGRAM_API_ID")
            if not self.api_hash:
                missing.append("TELEGRAM_API_HASH")
            if not self.phone:
                missing.append("phone number")

            if missing:
                logger.warning(
                    f"Telethon client not started — missing credentials: "
                    f"{', '.join(missing)}. Telegram features will be unavailable."
                )
                return  # Graceful no-op, don't raise

            try:
                self.client = TelegramClient(
                    self.session_name,
                    int(self.api_id),
                    self.api_hash,
                    flood_sleep_threshold=60
                )
                await self.client.start(phone=self.phone)
                self._client_started = True
                logger.info("Telethon client started successfully")
            except Exception as e:
                logger.error(
                    f"Telethon client failed to start: {e}. "
                    f"Telegram features will be unavailable."
                )
                # Clean up partial client so it's not left in a broken state
                if self.client:
                    try:
                        await self.client.disconnect()
                    except Exception:
                        pass
                    self.client = None
                    
    async def stop(self):
        """Stop the Telegram client and cleanup resources"""
        async with self._start_lock:
            if self.client and self._client_started:
                await self.client.disconnect()
                self._client_started = False
                logger.info("Telethon client stopped")

            # Cleanup thread pool
            self._thread_pool.shutdown(wait=True)
            logger.info("Thread pool shut down")

    async def __aenter__(self):
        """Context manager entry"""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        await self.stop()

    @staticmethod
    def _normalize_identifier(identifier: Union[int, str]) -> str:
        if isinstance(identifier, int):
            return f"id:{identifier}"

        s = str(identifier).lower().strip()

        # Strip common prefixes
        s = re.sub(r'^(https?://)?(t\.me/|@)', '', s)
        s = s.strip('/')

        # Detect numeric IDs (including negative channel IDs)
        if s.lstrip('-').isdigit():
            return f"id:{s}"

        return f"username:{s}"

    async def resolve_entity_cached(self, identifier: Union[int, str]) -> Any:
        if not self._client_started:
            await self.start()

        cache_key = self._normalize_identifier(identifier)

        # Fast path: check cache
        cached = await self._entity_cache.get(cache_key)
        if cached is not None:
            logger.debug(f"Entity cache hit: {cache_key}")
            return cached

        # Slow path: resolve and cache
        async with self._entity_lock:
            # Double-check after acquiring lock (avoid duplicate resolutions)
            cached = await self._entity_cache.get(cache_key)
            if cached is not None:
                return cached

            try:
                # Direct resolution using Telethon's session cache
                input_peer = await self.client.get_input_entity(identifier)
                await self._entity_cache.set(cache_key, input_peer)
                logger.info(f"Entity resolved and cached: {cache_key}")
                return input_peer

            except (ValueError, TypeError) as e:
                logger.error(f"Entity resolution failed for '{identifier}': {e}")
                raise ValueError(
                    f"Cannot resolve entity '{identifier}'. "
                    f"Ensure you have access to this chat/channel. "
                    f"Error: {e}"
                ) from e

    async def invalidate_entity_cache(self, identifier: Union[int, str] = None):
        if identifier is None:
            await self._entity_cache.clear()
            logger.info("Cleared entire entity cache")
        else:
            cache_key = self._normalize_identifier(identifier)
            # Note: LRUCache doesn't have delete, so we just let it expire
            logger.info(f"Invalidated entity cache for: {cache_key}")

    def _get_media_type(self, message) -> Optional[str]:
        """Determine the type of media in a message"""
        if not message.media:
            return None

        if isinstance(message.media, MessageMediaPhoto):
            return "photo"
        elif isinstance(message.media, MessageMediaDocument):
            mime_type = message.media.document.mime_type
            if mime_type.startswith("video"):
                return "video"
            elif mime_type.startswith("image"):
                return "image"
            elif mime_type == "application/x-tgsticker":
                return "sticker"
            else:
                return "document"

        return "other"

    def _serialize_message(
        self,
        message,
        include_sender_details: bool = True,
        include_media_details: bool = False
    ) -> Dict[str, Any]:
        logger.info(f"{message}")
        result = {
            "message_id": message.id,
            "date": message.date.isoformat() if message.date else None,
            "text": message.text or "",
            "sender_id": message.sender_id,
            "reply_to_message_id": (
                message.reply_to.reply_to_msg_id
                if message.reply_to else None
            ),
            "media_type": self._get_media_type(message),
            "has_media": bool(message.media),
        }

        # Optional: detailed sender information (may require entity fetch)
        if include_sender_details and message.sender:
            result["sender"] = {
                "id": message.sender.id,
                "username": getattr(message.sender, 'username', None),
                "first_name": getattr(message.sender, 'first_name', None),
                "last_name": getattr(message.sender, 'last_name', None),
                "is_bot": getattr(message.sender, 'bot', False),
                "is_verified": getattr(message.sender, 'verified', False)
            }

        # Optional: detailed media metadata
        if include_media_details and message.media:
            result["media_details"] = {
                "is_forwarded": bool(message.fwd_from),
                "views": message.views,
                "forwards": message.forwards,
                "edit_date": message.edit_date.isoformat() if message.edit_date else None
            }

        return result


    async def get_message_context(
        self,
        chat_identifier: Union[int, str],
        message_id: int,
        context_size: int = 5,
        fetch_replies: bool = True,
        include_sender_details: bool = True,
        include_media_details: bool = False
    ) -> Optional[MessageContext]:
        async with self._semaphore:
            if not self._client_started:
                await self.start()

            try:
                entity = await self.resolve_entity_cached(chat_identifier)

                # CRITICAL FIX: First, verify the target message exists
                target_msg = await self.client.get_messages(entity, ids=message_id)

                if not target_msg:
                    logger.warning(
                        f"Message {message_id} not found in chat {chat_identifier}"
                    )
                    return None

                # Fetch messages before (reverse chronological)
                previous_messages = []
                if context_size > 0:
                    async for msg in self.client.iter_messages(
                        entity,
                        offset_id=message_id,  # Start from target
                        limit=context_size,
                        reverse=False  # Get older messages
                    ):
                        if msg.id < message_id:
                            previous_messages.append(msg)

                # Fetch messages after (chronological)
                next_messages = []
                if context_size > 0:
                    async for msg in self.client.iter_messages(
                        entity,
                        offset_id=message_id,  # Start from target
                        limit=context_size + 1,  # +1 because it includes the offset
                        reverse=True  # Get newer messages
                    ):
                        if msg.id > message_id:
                            next_messages.append(msg)

                # Sort messages
                previous_messages.sort(key=lambda m: m.id)
                next_messages.sort(key=lambda m: m.id)

                # Fetch reply chain if requested
                reply_chain = []
                if fetch_replies and target_msg.reply_to:
                    reply_chain = await self._fetch_reply_chain_optimized(
                        entity,
                        target_msg.reply_to.reply_to_msg_id,
                        include_sender_details,
                        include_media_details
                    )

                # Build result
                result = MessageContext(
                    chat_id=str(chat_identifier),
                    target_message=self._serialize_message(
                        target_msg,
                        include_sender_details,
                        include_media_details
                    ),
                    previous_messages=[
                        self._serialize_message(m, include_sender_details, include_media_details)
                        for m in previous_messages
                    ],
                    next_messages=[
                        self._serialize_message(m, include_sender_details, include_media_details)
                        for m in next_messages
                    ],
                    reply_chain=reply_chain,
                    context_size=context_size,
                    total_messages=(
                        1 + len(previous_messages) +
                        len(next_messages) + len(reply_chain)
                    )
                )

                logger.info(
                    f"Fetched context for message {message_id}: "
                    f"{len(previous_messages)} prev, {len(next_messages)} next, "
                    f"{len(reply_chain)} in reply chain"
                )

                return result

            except Exception as e:
                logger.error(f"Error fetching message context: {e}", exc_info=True)
                raise

    async def _fetch_reply_chain_optimized(
        self,
        entity: Any,
        reply_to_msg_id: int,
        include_sender_details: bool = False,
        include_media_details: bool = False,
        max_depth: int = 10
    ) -> List[Dict[str, Any]]:
        reply_ids = []
        current_id = reply_to_msg_id
        seen = set()

        # Phase 1: Collect all reply IDs (minimal fetches)
        while current_id and len(reply_ids) < max_depth:
            if current_id in seen:
                logger.warning(f"Circular reply detected at message {current_id}")
                break

            seen.add(current_id)
            reply_ids.append(current_id)

            # Check message cache first
            cached = await self._message_cache.get(f"msg_{current_id}")
            if cached and hasattr(cached, 'reply_to') and cached.reply_to:
                current_id = cached.reply_to.reply_to_msg_id
                continue

            # Fetch message to get next reply_to
            try:
                msg = await self.client.get_messages(entity, ids=current_id)

                if msg:
                    # Cache for future use
                    await self._message_cache.set(f"msg_{current_id}", msg)

                    if msg.reply_to:
                        current_id = msg.reply_to.reply_to_msg_id
                    else:
                        break
                else:
                    break

            except Exception as e:
                logger.warning(f"Reply chain break at {current_id}: {e}")
                break

        # Phase 2: Batch fetch all reply messages
        if not reply_ids:
            return []

        try:
            reply_messages = await self.client.get_messages(entity, ids=reply_ids)

            # Filter None and serialize
            serialized = []
            for msg in reply_messages:
                if msg is not None:
                    serialized.append(
                        self._serialize_message(
                            msg,
                            include_sender_details,
                            include_media_details
                        )
                    )
                    # Update cache
                    await self._message_cache.set(f"msg_{msg.id}", msg)

            # Reverse to show oldest first
            return list(reversed(serialized))

        except Exception as e:
            logger.error(f"Batch reply fetch failed: {e}")
            return []

    async def get_conversation_thread(
        self,
        chat_identifier: Union[int, str],
        message_id: int,
        include_context: bool = True,
        context_size: int = 5,
        include_sender_details: bool = False,
        include_media_details: bool = False
    ) -> Optional[Dict[str, Any]]:
        context = await self.get_message_context(
            chat_identifier=chat_identifier,
            message_id=message_id,
            context_size=context_size if include_context else 0,
            fetch_replies=True,
            include_sender_details=include_sender_details,
            include_media_details=include_media_details
        )

        if not context:
            return None

        return asdict(context)

    def _group_message_ids_into_ranges(
        self,
        sorted_ids: List[int],
        context_size: int
    ) -> List[Tuple[int, int, List[int]]]:
        if not sorted_ids:
            return []

        ranges = []
        current_range_start = sorted_ids[0] - context_size
        current_range_end = sorted_ids[0] + context_size
        current_ids = [sorted_ids[0]]

        for msg_id in sorted_ids[1:]:
            expanded_start = msg_id - context_size
            expanded_end = msg_id + context_size

            # Check if this message's range overlaps with current range
            if expanded_start <= current_range_end + 1:
                # Merge into current range
                current_range_end = max(current_range_end, expanded_end)
                current_ids.append(msg_id)
            else:
                # Start new range
                ranges.append((
                    max(1, current_range_start),
                    current_range_end,
                    current_ids
                ))
                current_range_start = expanded_start
                current_range_end = expanded_end
                current_ids = [msg_id]

        # Add final range
        ranges.append((
            max(1, current_range_start),
            current_range_end,
            current_ids
        ))

        logger.debug(
            f"Grouped {len(sorted_ids)} message IDs into {len(ranges)} ranges"
        )

        return ranges

    async def get_batch_message_contexts(
        self,
        chat_identifier: Union[int, str],
        message_ids: List[int],
        context_size: int = 5,
        fetch_replies: bool = True,
        include_sender_details: bool = False,
        include_media_details: bool = False,
        max_concurrent: int = 3
    ) -> List[Dict[str, Any]]:
        if not message_ids:
            return []

        # Sort and group message IDs
        sorted_ids = sorted(set(message_ids))
        ranges = self._group_message_ids_into_ranges(sorted_ids, context_size)

        entity = await self.resolve_entity_cached(chat_identifier)
        all_contexts = []

        # Process each range
        for range_start, range_end, msg_ids_in_range in ranges:
            try:
                # Single API call for entire range
                messages = await self.client.get_messages(
                    entity,
                    min_id=range_start - 1,
                    limit=range_end - range_start + 1
                )

                # Build message map for fast lookup
                message_map = {msg.id: msg for msg in messages if msg}

                # Build contexts from cached messages
                for msg_id in msg_ids_in_range:
                    if msg_id not in message_map:
                        logger.warning(f"Message {msg_id} not found in range")
                        continue

                    target_msg = message_map[msg_id]

                    # Partition messages
                    previous = [
                        m for m in message_map.values()
                        if m.id < msg_id
                    ]
                    next_msgs = [
                        m for m in message_map.values()
                        if m.id > msg_id
                    ]

                    # Sort
                    previous.sort(key=lambda m: m.id)
                    next_msgs.sort(key=lambda m: m.id)

                    # Limit to context_size
                    previous = previous[-context_size:]
                    next_msgs = next_msgs[:context_size]

                    # Fetch reply chain if needed
                    reply_chain = []
                    if fetch_replies and target_msg.reply_to:
                        reply_chain = await self._fetch_reply_chain_optimized(
                            entity,
                            target_msg.reply_to.reply_to_msg_id,
                            include_sender_details,
                            include_media_details
                        )

                    context = {
                        "chat_id": str(chat_identifier),
                        "target_message": self._serialize_message(
                            target_msg,
                            include_sender_details,
                            include_media_details
                        ),
                        "previous_messages": [
                            self._serialize_message(m, include_sender_details, include_media_details)
                            for m in previous
                        ],
                        "next_messages": [
                            self._serialize_message(m, include_sender_details, include_media_details)
                            for m in next_msgs
                        ],
                        "reply_chain": reply_chain,
                        "context_size": context_size,
                        "total_messages": 1 + len(previous) + len(next_msgs) + len(reply_chain)
                    }

                    all_contexts.append(context)

            except Exception as e:
                logger.error(
                    f"Range fetch failed [{range_start}-{range_end}]: {e}",
                    exc_info=True
                )
                continue

        logger.info(
            f"Retrieved {len(all_contexts)}/{len(message_ids)} message contexts"
        )

        return all_contexts

    def _get_media_hash(self, message) -> Optional[str]:
        if not message.media:
            return None

        if isinstance(message.media, MessageMediaPhoto):
            return f"photo_{message.media.photo.id}"
        elif isinstance(message.media, MessageMediaDocument):
            return f"doc_{message.media.document.id}"

        return None

    async def _download_thumbnail_optimized(
        self,
        message,
        preferred_size: int = 300
    ) -> Optional[bytes]:
        try:
            if isinstance(message.media, MessageMediaPhoto):
                photo = message.media.photo

                # Find appropriate thumbnail size
                suitable_sizes = [
                    s for s in photo.sizes
                    if isinstance(s, (PhotoSize, PhotoCachedSize))
                    and hasattr(s, 'w')
                    and s.w >= preferred_size * 0.5  # At least half desired size
                ]

                if not suitable_sizes:
                    # Fallback to any available size
                    suitable_sizes = [
                        s for s in photo.sizes
                        if isinstance(s, (PhotoSize, PhotoCachedSize))
                    ]

                if not suitable_sizes:
                    logger.warning("No suitable photo sizes found")
                    return None

                # Sort by size, prefer smallest that meets requirement
                suitable_sizes.sort(key=lambda s: getattr(s, 'w', 0))
                thumb_size = suitable_sizes[0]

                # Download ONLY this thumbnail size
                logger.debug(
                    f"Downloading photo thumbnail: "
                    f"{getattr(thumb_size, 'w', 0)}x{getattr(thumb_size, 'h', 0)}"
                )

                return await self.client.download_media(
                    message.media,
                    file=bytes,
                    thumb=thumb_size.type
                )

            elif isinstance(message.media, MessageMediaDocument):
                doc = message.media.document

                # Check for document thumbnail
                if hasattr(doc, 'thumbs') and doc.thumbs:
                    suitable_thumbs = [
                        t for t in doc.thumbs
                        if isinstance(t, (PhotoSize, PhotoCachedSize))
                    ]

                    if suitable_thumbs:
                        # Use largest available thumbnail
                        suitable_thumbs.sort(
                            key=lambda t: getattr(t, 'w', 0),
                            reverse=True
                        )

                        logger.debug(
                            f"Downloading document thumbnail: "
                            f"{getattr(suitable_thumbs[0], 'w', 0)}x"
                            f"{getattr(suitable_thumbs[0], 'h', 0)}"
                        )

                        return await self.client.download_media(
                            message.media,
                            file=bytes,
                            thumb=suitable_thumbs[0].type
                        )

                logger.warning(
                    f"No thumbnail available for document {doc.id}. "
                    f"Consider implementing frame extraction for videos."
                )
                return None

        except Exception as e:
            logger.error(f"Thumbnail download failed: {e}", exc_info=True)
            return None

    def _create_thumbnail_sync(
        self,
        image_bytes: bytes,
        size: Tuple[int, int] = (300, 300)
    ) -> bytes:
        try:
            image = Image.open(io.BytesIO(image_bytes))

            # Handle transparency
            if image.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', image.size, (255, 255, 255))
                if image.mode == 'P':
                    image = image.convert('RGBA')
                background.paste(image, mask=image.split()[-1])
                image = background
            elif image.mode != 'RGB':
                image = image.convert('RGB')

            # Create thumbnail
            image.thumbnail(size, Image.Resampling.LANCZOS)

            # Save to bytes
            output = io.BytesIO()
            image.save(output, format='JPEG', quality=85, optimize=True)
            return output.getvalue()

        except Exception as e:
            logger.error(f"Thumbnail creation failed: {e}", exc_info=True)
            raise

    async def download_and_create_thumbnail(
        self,
        chat_identifier: Union[int, str],
        message_id: int,
        size: Tuple[int, int] = (300, 300),
        force_regenerate: bool = False
    ) -> Optional[ThumbnailResult]:
        async with self._semaphore:
            if not self._client_started:
                await self.start()

            try:
                entity = await self.resolve_entity_cached(chat_identifier)
                message = await self.client.get_messages(entity, ids=message_id)

                if not message or not message.media:
                    logger.warning(
                        f"No media found in message {message_id} "
                        f"from chat {chat_identifier}"
                    )
                    return None

                media_type = self._get_media_type(message)
                if media_type not in ["photo", "video", "image"]:
                    logger.info(
                        f"Media type '{media_type}' doesn't support thumbnails"
                    )
                    return None

                # OPTIMIZATION: Check cache first
                media_hash = self._get_media_hash(message)
                if media_hash and not force_regenerate:
                    cached_path = await self._thumbnail_cache.get(media_hash)
                    if cached_path and os.path.exists(cached_path):
                        logger.debug(f"Thumbnail cache hit: {media_hash}")

                        # Get file size
                        file_size = os.path.getsize(cached_path)

                        return ThumbnailResult(
                            message_id=message_id,
                            chat_identifier=str(chat_identifier),
                            media_type=media_type,
                            thumbnail_path=cached_path,
                            thumbnail_url=f"/static/thumbnails/{os.path.basename(cached_path)}",
                            file_size=file_size,
                            cached=True,
                            generated_at=datetime.fromtimestamp(
                                os.path.getmtime(cached_path)
                            )
                        )

                # OPTIMIZATION: Download native thumbnail (not full media)
                thumbnail_bytes = await self._download_thumbnail_optimized(
                    message,
                    preferred_size=size[0]
                )

                if not thumbnail_bytes:
                    logger.warning(
                        f"No thumbnail available for message {message_id}"
                    )
                    return None

                # OPTIMIZATION: Process in thread pool (non-blocking)
                processed_bytes = await asyncio.to_thread(
                    self._create_thumbnail_sync,
                    thumbnail_bytes,
                    size
                )

                # Save to disk
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"thumb_{media_hash}_{timestamp}.jpg"
                filepath = os.path.join(self.thumbnail_dir, filename)

                async with aiofiles.open(filepath, 'wb') as f:
                    await f.write(processed_bytes)

                # Update cache
                if media_hash:
                    await self._thumbnail_cache.set(media_hash, filepath)

                result = ThumbnailResult(
                    message_id=message_id,
                    chat_identifier=str(chat_identifier),
                    media_type=media_type,
                    thumbnail_path=filepath,
                    thumbnail_url=f"/static/thumbnails/{filename}",
                    file_size=len(processed_bytes),
                    cached=False,
                    generated_at=datetime.now()
                )

                logger.info(
                    f"Created thumbnail for message {message_id}: "
                    f"{filename} ({len(processed_bytes)} bytes)"
                )

                print(result)

                return result

            except Exception as e:
                logger.error(
                    f"Error processing media from message {message_id}: {e}",
                    exc_info=True
                )
                raise

    async def batch_create_thumbnails(
        self,
        chat_identifier: Union[int, str],
        message_ids: List[int],
        size: Tuple[int, int] = (300, 300),
        max_concurrent: int = 5
    ) -> List[ThumbnailResult]:
        semaphore = asyncio.Semaphore(max_concurrent)

        async def process_one(msg_id: int) -> Optional[ThumbnailResult]:
            async with semaphore:
                try:
                    return await self.download_and_create_thumbnail(
                        chat_identifier,
                        msg_id,
                        size
                    )
                except Exception as e:
                    logger.error(f"Thumbnail failed for message {msg_id}: {e}")
                    return None

        # Run concurrently
        results = await asyncio.gather(
            *[process_one(msg_id) for msg_id in message_ids],
            return_exceptions=False
        )

        # Filter out None results
        successful = [r for r in results if r is not None]

        logger.info(
            f"Created {len(successful)}/{len(message_ids)} thumbnails "
            f"with concurrency={max_concurrent}"
        )

        return successful

    async def get_chat_media_messages(
        self,
        chat_identifier: Union[int, str],
        limit: int = 100,
        offset_id: int = 0,
        media_types: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        if not self._client_started:
            await self.start()

        entity = await self.resolve_entity_cached(chat_identifier)
        media_messages = []

        try:
            async for message in self.client.iter_messages(
                entity,
                limit=limit,
                offset_id=offset_id
            ):
                if message.media:
                    media_type = self._get_media_type(message)

                    # Filter by media type if specified
                    if media_types and media_type not in media_types:
                        continue

                    media_messages.append({
                        "message_id": message.id,
                        "date": message.date.isoformat() if message.date else None,
                        "media_type": media_type,
                        "has_text": bool(message.text),
                        "text_preview": message.text[:100] if message.text else None,
                        "sender_id": message.sender_id,
                    })

            logger.info(
                f"Found {len(media_messages)} media messages in "
                f"chat {chat_identifier}"
            )

            return media_messages

        except Exception as e:
            logger.error(
                f"Error getting media messages from chat {chat_identifier}: {e}",
                exc_info=True
            )
            raise

    async def get_chat_info(self, chat_identifier: Union[int, str]) -> Dict[str, Any]:
        if not self._client_started:
            await self.start()

        entity = await self.resolve_entity_cached(chat_identifier)
        full_entity = await self.client.get_entity(entity)

        info = {
            "id": full_entity.id,
            "title": getattr(full_entity, 'title', None),
            "username": getattr(full_entity, 'username', None),
            "type": full_entity.__class__.__name__,
        }

        # Add additional fields if available
        if hasattr(full_entity, 'participants_count'):
            info["participants_count"] = full_entity.participants_count

        if hasattr(full_entity, 'about'):
            info["about"] = full_entity.about

        return info

    async def clear_all_caches(self):
        """Clear all internal caches"""
        await self._entity_cache.clear()
        await self._thumbnail_cache.clear()
        await self._message_cache.clear()
        logger.info("Cleared all caches")

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get statistics about cache usage"""
        return {
            "entity_cache_size": len(self._entity_cache.cache),
            "thumbnail_cache_size": len(self._thumbnail_cache.cache),
            "message_cache_size": len(self._message_cache.cache),
            "client_started": self._client_started
        }
