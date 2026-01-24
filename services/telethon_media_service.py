from telethon import TelegramClient
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument, PeerChannel, PeerUser, PeerChat
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError
from PIL import Image
import io
import os
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import aiofiles
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

class TelethonMediaService:
    def __init__(
        self,
        api_id: Optional[int] = None,
        api_hash: Optional[str] = None,
        session_name: str = "telegram_session"
    ):
        load_dotenv()
        self.api_id = os.environ.get("TG_API_ID", api_id)
        self.api_hash = os.environ.get("TG_API_HASH", api_hash)
        self.session_name = session_name
        self.client: Optional[TelegramClient] = None
        self.thumbnail_dir = "static/thumbnails"
        self.entity_cache: Dict[str, any] = {}
        self.is_authenticated = False
        self.phone_code_hash = None
        self.current_phone = None
        os.makedirs(self.thumbnail_dir, exist_ok=True)

    def initialize_client(self):
        """Initialize the Telegram client without starting it."""
        if self.client is None:
            if not self.api_id or not self.api_hash:
                raise ValueError("API ID and API Hash must be provided before initializing client")

            self.client = TelegramClient(
                self.session_name,
                int(self.api_id),
                str(self.api_hash)
            )
            logger.info("Telethon client initialized (not authenticated yet)")

    async def connect(self):
        """Just connect without authentication."""
        if self.client is None:
            self.initialize_client()

        if not self.client.is_connected():
            await self.client.connect()
            logger.info("Client connected")

        # Check if already authorized
        if await self.client.is_user_authorized():
            self.is_authenticated = True
            logger.info("Client already authorized with existing session")
            return True
        else:
            logger.info("Client connected but not authorized")
            return False

    async def send_code_request(self, phone: str) -> dict:
        """Send verification code to phone number."""
        try:
            if self.client is None:
                self.initialize_client()

            if not self.client.is_connected():
                await self.client.connect()

            self.current_phone = phone
            sent_code = await self.client.send_code_request(phone)
            self.phone_code_hash = sent_code.phone_code_hash

            logger.info(f"Verification code sent to {phone}")
            return {
                "status": "success",
                "message": "Verification code sent to your phone"
            }
        except Exception as e:
            logger.error(f"Error sending code: {str(e)}")
            return {
                "status": "error",
                "message": str(e)
            }

    async def sign_in(self, phone: str, code: str, password: Optional[str] = None) -> dict:
        """Sign in with phone code (and optionally 2FA password)."""
        try:
            if not self.phone_code_hash:
                return {
                    "status": "error",
                    "message": "No verification code sent. Call send_code_request first."
                }

            try:
                await self.client.sign_in(
                    phone=phone,
                    code=code,
                    phone_code_hash=self.phone_code_hash
                )
                self.is_authenticated = True
                logger.info("Successfully authenticated!")
                return {
                    "status": "success",
                    "message": "Authentication successful"
                }
            except SessionPasswordNeededError:
                if password:
                    await self.client.sign_in(password=password)
                    self.is_authenticated = True
                    logger.info("Successfully authenticated with 2FA!")
                    return {
                        "status": "success",
                        "message": "Authentication successful (2FA)"
                    }
                else:
                    return {
                        "status": "2fa_required",
                        "message": "2FA password required"
                    }
        except PhoneCodeInvalidError:
            return {
                "status": "error",
                "message": "Invalid verification code"
            }
        except Exception as e:
            logger.error(f"Error signing in: {str(e)}")
            return {
                "status": "error",
                "message": str(e)
            }

    def update_credentials(self, api_id: int, api_hash: str):
        """Update API credentials after initialization."""
        self.api_id = api_id
        self.api_hash = api_hash

        # Reset client to use new credentials
        if self.client:
            self.client = None
            self.is_authenticated = False

        logger.info("Credentials updated")

    def _ensure_authenticated(self):
        """Check if client is authenticated before operations."""
        if not self.is_authenticated or self.client is None:
            raise RuntimeError(
                "Client is not authenticated. Please authenticate first."
            )

    async def stop(self):
        if self.client:
            await self.client.disconnect()
            self.is_authenticated = False
        logger.info("Telethon client stopped")

    def _get_media_type(self, message) -> Optional[str]:
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

    def _serialize_message(self, message) -> Dict:
        sender_info = {}
        if message.sender:
            sender_info = {
                "id": message.sender.id,
                "username": getattr(message.sender, 'username', None),
                "first_name": getattr(message.sender, 'first_name', None),
                "last_name": getattr(message.sender, 'last_name', None),
                "is_bot": getattr(message.sender, 'bot', False)
            }

        return {
            "message_id": message.id,
            "date": message.date,
            "text": message.text or "",
            "sender_id": message.sender_id,
            "sender": sender_info,
            "reply_to_message_id": message.reply_to.reply_to_msg_id if message.reply_to else None,
            "media_type": self._get_media_type(message),
            "has_media": bool(message.media),
            "is_forwarded": bool(message.fwd_from),
            "views": message.views,
            "forwards": message.forwards,
            "edit_date": message.edit_date
        }

    async def get_message_context(
        self,
        chat_identifier: any,
        message_id: int,
        context_size: int = 5,
        fetch_replies: bool = True
    ) -> Dict[str, any]:
        self._ensure_authenticated()

        try:
            entity = await self.resolve_entity_cached(chat_identifier)

            target_message = await self.client.get_messages(entity, ids=message_id)

            if not target_message:
                logger.warning(f"Message {message_id} not found in chat {chat_identifier}")
                return None

            prev_start = max(1, message_id - context_size)
            prev_ids = list(range(prev_start, message_id))
            next_ids = list(range(message_id + 1, message_id + context_size + 1))

            previous_messages = []
            if prev_ids:
                prev_msgs = await self.client.get_messages(entity, ids=prev_ids)
                previous_messages = [
                    self._serialize_message(msg) for msg in prev_msgs
                    if msg is not None
                ]
                previous_messages.sort(key=lambda x: x['message_id'])

            next_messages = []
            if next_ids:
                next_msgs = await self.client.get_messages(entity, ids=next_ids)
                next_messages = [
                    self._serialize_message(msg) for msg in next_msgs
                    if msg is not None
                ]
                next_messages.sort(key=lambda x: x['message_id'])

            reply_chain = []
            if fetch_replies and target_message.reply_to:
                reply_chain = await self._fetch_reply_chain(
                    entity,
                    target_message.reply_to.reply_to_msg_id
                )

            result = {
                "chat_id": str(chat_identifier),
                "target_message": self._serialize_message(target_message),
                "previous_messages": previous_messages,
                "next_messages": next_messages,
                "reply_chain": reply_chain,
                "context_size": context_size,
                "total_messages": 1 + len(previous_messages) + len(next_messages) + len(reply_chain)
            }

            logger.info(
                f"Fetched context for message {message_id}: "
                f"{len(previous_messages)} prev, {len(next_messages)} next, "
                f"{len(reply_chain)} in reply chain"
            )

            return result

        except Exception as e:
            logger.error(f"Error fetching message context: {str(e)}")
            raise

    async def _fetch_reply_chain(
        self,
        entity: any,
        reply_to_msg_id: int,
        max_depth: int = 10
    ) -> List[Dict]:
        reply_chain = []
        current_msg_id = reply_to_msg_id
        depth = 0

        while current_msg_id and depth < max_depth:
            try:
                msg = await self.client.get_messages(entity, ids=current_msg_id)

                if not msg:
                    break

                reply_chain.append(self._serialize_message(msg))

                if msg.reply_to:
                    current_msg_id = msg.reply_to.reply_to_msg_id
                    depth += 1
                else:
                    break

            except Exception as e:
                logger.warning(f"Error fetching reply message {current_msg_id}: {str(e)}")
                break

        return list(reversed(reply_chain))

    async def get_batch_message_contexts(
        self,
        chat_identifier: any,
        message_ids: List[int],
        context_size: int = 5,
        fetch_replies: bool = True
    ) -> List[Dict[str, any]]:
        self._ensure_authenticated()
        results = []

        for msg_id in message_ids:
            try:
                context = await self.get_message_context(
                    chat_identifier=chat_identifier,
                    message_id=msg_id,
                    context_size=context_size,
                    fetch_replies=fetch_replies
                )
                if context:
                    results.append(context)
            except Exception as e:
                logger.error(f"Failed to get context for message {msg_id}: {str(e)}")
                continue

        logger.info(f"Retrieved contexts for {len(results)}/{len(message_ids)} messages")
        return results

    async def get_conversation_thread(
        self,
        chat_identifier: any,
        message_id: int,
        include_context: bool = True,
        context_size: int = 5
    ) -> Dict[str, any]:
        self._ensure_authenticated()

        try:
            entity = await self.resolve_entity_cached(chat_identifier)

            target_message = await self.client.get_messages(entity, ids=message_id)

            if not target_message:
                return None

            thread = {
                "chat_id": str(chat_identifier),
                "target_message": self._serialize_message(target_message),
                "reply_chain": [],
                "context": {
                    "previous": [],
                    "next": []
                }
            }

            if target_message.reply_to:
                thread["reply_chain"] = await self._fetch_reply_chain(
                    entity,
                    target_message.reply_to.reply_to_msg_id
                )

            if include_context:
                context = await self.get_message_context(
                    chat_identifier=chat_identifier,
                    message_id=message_id,
                    context_size=context_size,
                    fetch_replies=False
                )
                thread["context"]["previous"] = context["previous_messages"]
                thread["context"]["next"] = context["next_messages"]

            return thread

        except Exception as e:
            logger.error(f"Error fetching conversation thread: {str(e)}")
            raise

    async def _create_thumbnail(
        self,
        image_bytes: bytes,
        size: Tuple[int, int] = (300, 300)
    ) -> bytes:
        try:
            image = Image.open(io.BytesIO(image_bytes))
            if image.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', image.size, (255, 255, 255))
                if image.mode == 'P':
                    image = image.convert('RGBA')
                background.paste(image, mask=image.split()[-1])
                image = background
            elif image.mode != 'RGB':
                image = image.convert('RGB')
            image.thumbnail(size, Image.Resampling.LANCZOS)
            output = io.BytesIO()
            image.save(output, format='JPEG', quality=85)
            return output.getvalue()
        except Exception as e:
            logger.error(f"Error creating thumbnail: {str(e)}")
            raise

    async def download_and_create_thumbnail(
        self,
        chat_identifier: any,
        message_id: int,
        save_original: bool = False
    ) -> Optional[Dict[str, any]]:
        self._ensure_authenticated()

        try:
            entity = await self.resolve_entity_cached(chat_identifier)
            message = await self.client.get_messages(entity, ids=message_id)
            if not message or not message.media:
                logger.warning(f"No media found in message {message_id} from chat {chat_identifier}")
                return None

            media_type = self._get_media_type(message)
            if media_type not in ["photo", "video", "image"]:
                logger.info(f"Media type {media_type} doesn't support thumbnails")
                return None

            media_bytes = await self.client.download_media(message.media, file=bytes)
            if not media_bytes:
                logger.warning(f"Failed to download media from message {message_id}")
                return None

            if media_type == "video":
                temp_video_path = f"{self.thumbnail_dir}/temp_video_{message_id}.mp4"
                async with aiofiles.open(temp_video_path, 'wb') as f:
                    await f.write(media_bytes)

                import subprocess
                temp_frame_path = f"{self.thumbnail_dir}/temp_frame_{message_id}.jpg"
                try:
                    subprocess.run([
                        'ffmpeg', '-i', temp_video_path,
                        '-vframes', '1', '-f', 'image2',
                        temp_frame_path
                    ], check=True, capture_output=True)
                    async with aiofiles.open(temp_frame_path, 'rb') as f:
                        media_bytes = await f.read()

                    os.remove(temp_video_path)
                    os.remove(temp_frame_path)
                except subprocess.CalledProcessError as e:
                    logger.error(f"FFmpeg error: {e.stderr}")
                    os.remove(temp_video_path)
                    return None

            thumbnail_bytes = await self._create_thumbnail(media_bytes)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            thumbnail_filename = f"thumb_{str(chat_identifier)}_{message_id}_{timestamp}.jpg"
            thumbnail_path = os.path.join(self.thumbnail_dir, thumbnail_filename)
            async with aiofiles.open(thumbnail_path, 'wb') as f:
                await f.write(thumbnail_bytes)

            if save_original and media_type in ["photo", "image"]:
                original_filename = f"orig_{str(chat_identifier)}_{message_id}_{timestamp}.jpg"
                original_path = os.path.join(self.thumbnail_dir, original_filename)
                async with aiofiles.open(original_path, 'wb') as f:
                    await f.write(media_bytes)
            else:
                original_path = None

            result = {
                "message_id": message_id,
                "chat_identifier": str(chat_identifier),
                "media_type": media_type,
                "thumbnail_path": thumbnail_path,
                "thumbnail_url": f"/static/thumbnails/{thumbnail_filename}",
                "original_path": original_path,
                "generated_at": datetime.now(),
                "file_size": len(thumbnail_bytes)
            }
            logger.info(f"Created thumbnail for message {message_id}: {thumbnail_filename}")
            return result
        except Exception as e:
            logger.error(f"Error processing media from message {message_id}: {str(e)}")
            raise

    async def get_chat_media_messages(
        self,
        chat_identifier: any,
        limit: int = 100,
        offset_id: int = 0
    ) -> List[Dict[str, any]]:
        self._ensure_authenticated()
        media_messages = []
        try:
            entity = await self.resolve_entity_cached(chat_identifier)
            async for message in self.client.iter_messages(
                entity,
                limit=limit,
                offset_id=offset_id
            ):
                if message.media:
                    media_type = self._get_media_type(message)
                    media_messages.append({
                        "message_id": message.id,
                        "date": message.date,
                        "media_type": media_type,
                        "has_text": bool(message.text),
                        "text_preview": message.text[:100] if message.text else None
                    })
            logger.info(f"Found {len(media_messages)} media messages in chat {chat_identifier}")
            return media_messages
        except Exception as e:
            logger.error(f"Error getting media messages from chat {chat_identifier}: {str(e)}")
            raise

    async def batch_create_thumbnails(
        self,
        chat_identifier: any,
        message_ids: List[int]
    ) -> List[Dict[str, any]]:
        self._ensure_authenticated()
        results = []
        for msg_id in message_ids:
            try:
                result = await self.download_and_create_thumbnail(chat_identifier, msg_id)
                if result:
                    results.append(result)
            except Exception as e:
                logger.error(f"Failed to process message {msg_id}: {str(e)}")
                continue
        logger.info(f"Created {len(results)} thumbnails out of {len(message_ids)} messages")
        return results

    async def encounter_entity(self, identifier):
        self._ensure_authenticated()

        print(f"[*] Attempting to encounter entity: {identifier}")
        try:
            if isinstance(identifier, str):
                clean_id = identifier.replace('https://t.me/', '').replace('t.me/', '').replace('@', '')
                for variant in [clean_id, f'@{clean_id}', f't.me/{clean_id}', f'https://t.me/{clean_id}']:
                    try:
                        entity = await self.client.get_entity(variant)
                        print(f"[+] Successfully encountered entity via direct resolution: {entity.id}")
                        return entity
                    except:
                        continue
        except Exception as e:
            print(f"[*] Direct resolution failed: {e}")

        print("[*] Getting dialogs to populate entity cache...")
        try:
            dialogs = await self.client.get_dialogs()
            print(f"[+] Retrieved {len(dialogs)} dialogs")
            if isinstance(identifier, str):
                clean_id = identifier.replace('https://t.me/', '').replace('t.me/', '').replace('@', '')
                for dialog in dialogs:
                    entity = dialog.entity
                    if hasattr(entity, 'username') and entity.username:
                        if entity.username.lower() == clean_id.lower():
                            print(f"[+] Found entity in dialogs by username: {entity.id}")
                            return entity
                    if hasattr(entity, 'title') and entity.title:
                        if entity.title.lower() == clean_id.lower():
                            print(f"[+] Found entity in dialogs by title: {entity.id}")
                            return entity
            elif isinstance(identifier, (int, str)) and str(identifier).lstrip('-').isdigit():
                target_id = int(identifier)
                if target_id > 0 and len(str(target_id)) > 10:
                    target_id = int(f'-100{target_id}')
                for dialog in dialogs:
                    if dialog.entity.id == target_id:
                        print(f"[+] Found entity in dialogs by ID: {dialog.entity.id}")
                        return dialog.entity
        except Exception as e:
            print(f"[*] Dialog retrieval failed: {e}")

        if isinstance(identifier, (int, str)) and str(identifier).lstrip('-').isdigit():
            entity_id = int(identifier)
            if entity_id > 0 and len(str(entity_id)) > 10:
                entity_id = int(f'-100{entity_id}')
            for peer_type in [PeerChannel, PeerUser, PeerChat]:
                try:
                    entity = await self.client.get_entity(peer_type(entity_id))
                    print(f"[+] Successfully encountered entity as {peer_type.__name__}: {entity.id}")
                    return entity
                except Exception:
                    continue

        if isinstance(identifier, str):
            clean_id = identifier.replace('https://t.me/', '').replace('t.me/', '').replace('@', '')
            try:
                messages = await self.client.get_messages(clean_id, limit=1)
                if messages:
                    entity = messages[0].chat
                    print(f"[+] Encountered entity through messages: {entity.id}")
                    return entity
            except Exception as e:
                print(f"[*] Message retrieval failed: {e}")

        raise ValueError(f"Could not encounter entity: {identifier}. Make sure you have access to this chat/channel and it exists.")

    async def resolve_entity_cached(self, identifier):
        self._ensure_authenticated()

        if isinstance(identifier, str):
            cache_key = identifier.replace('https://t.me/', '').replace('t.me/', '').replace('@', '').lower()
        else:
            cache_key = str(identifier)

        if cache_key in self.entity_cache:
            print(f"[✓] Using cached entity for: {cache_key}")
            return self.entity_cache[cache_key]

        print(f"[*] Entity not in cache, resolving: {identifier}")
        try:
            input_entity = await self.client.get_input_entity(identifier)
            self.entity_cache[cache_key] = input_entity
            print(f"[+] Cached entity from Telethon session: {cache_key}")
            return input_entity
        except (ValueError, TypeError):
            print(f"[*] Entity not in Telethon cache, encountering: {identifier}")
            try:
                entity = await self.encounter_entity(identifier)
                input_entity = await self.client.get_input_entity(entity)
                self.entity_cache[cache_key] = input_entity
                print(f"[+] Cached newly encountered entity: {cache_key}")
                return input_entity
            except Exception as e:
                raise ValueError(f"Failed to resolve entity {identifier}: {str(e)}")