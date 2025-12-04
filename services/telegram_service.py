import asyncio
import json
import re
import time
from typing import List
from telethon import TelegramClient
import os
from dotenv import load_dotenv
import logging

load_dotenv()

from models.telegram_models import VKProfileHistoryResponse, ProfileEntry

class TelegramService:
    def __init__(self):
        self.session_name = "telegram_session"
        self.logger = logging.getLogger(__name__)
        self.api_id = os.getenv('TELEGRAM_API_ID')
        self.api_hash = os.getenv('TELEGRAM_API_HASH')

        if not all([self.api_id, self.api_hash]):
            self.logger.error("Telegram API credentials not found in environment variables")

        self.client = None

        self.key_mapping = {
            '🔗 URL ВКонтакте': 'url',
            '🆔 id ВКонтакте': 'vk_id',
            '👤 Ф.И.': 'full_name',
            '👤 Фамилия': 'last_name',
            '👤 Имя': 'first_name',
            '⚧ Пол': 'gender',
            '🏡 Страна': 'country',
            '🏡 Родной город': 'hometown',
            '📅 Последний вход': 'last_login',
            '👣 Устройство': 'device',
            '👥 Фолловеры': 'followers',
            '🏫 Университет': 'university',
            '✔️ Факультет': 'faculty',
            '🔗 UserName ВК': 'username',
            '👩‍❤️‍👨 Сем. положение': 'marital_status',
            '👤 Ф.И. (нормал.)': 'normalized_name',
            '🌍 Страна': 'country',
            '🏡 Город': 'city',
            '🌍 Город': 'city',
            '🏫 Образование': 'education',
            '🏞 Фото': 'avatar',
            '🏥 Дата рождения': 'birth_date',
            '📆 Последний визит': 'last_visit',
        }

    async def ensure_client(self):
        """Ensure client is created and connected"""
        if not self.client:
            self.logger.info("Creating new Telegram client")
            self.client = TelegramClient(self.session_name, self.api_id, self.api_hash)

        if not self.client.is_connected():
            self.logger.info("Connecting client")
            await self.client.connect()

        if not await self.client.is_user_authorized():
            self.logger.error("Client not authorized!")
            raise Exception("Telegram client not authorized. Please run authentication first.")

    def strip_telegram_formatting(self, text: str) -> str:
        return re.sub(r'\*\*|__', '', text).strip()


    async def send_request(self, user_id: str) -> VKProfileHistoryResponse:
        try:
            self.logger.info(f"Starting request for user_id: {user_id}")
            await self.ensure_client()

            bot_username = 'VKHistoryRobot'
            bot_entity = await self.client.get_entity(bot_username)
            response = VKProfileHistoryResponse()

            sent_msg = await self.client.send_message(bot_entity, user_id)
            self.logger.info(f"Message sent with ID: {sent_msg.id}")

            timeout = 60
            start_time = time.time()
            last_message_id = sent_msg.id
            completion_received = False

            while time.time() - start_time < timeout:
                messages = await self.client.get_messages(
                    bot_entity,
                    min_id=last_message_id,
                    reverse=True
                )

                if not messages:
                    await asyncio.sleep(2)
                    continue

                for message in messages:
                    plain_text = self.strip_telegram_formatting(message.text)
                    self.logger.info(f"Processing message ID {message.id}: {plain_text[:100]}...")

                    last_message_id = max(last_message_id, message.id)

                    if 'Поиск завершён!' in plain_text:
                        self.logger.info("Found completion marker")
                        completion_received = True

                    if plain_text.startswith('🌐 История профиля ВКонтакте'):
                        entry = self.parse_profile_entry(plain_text)
                        response.entries.append(entry)
                    elif plain_text.startswith('🏞 Связанные с профилем фото'):
                        photos = self.parse_photo_urls(plain_text)
                        response.photos.extend(photos)

                if completion_received:
                    self.logger.info("Search completed successfully")
                    return response

                await asyncio.sleep(1)

            self.logger.warning("Timeout reached waiting for bot response")
            return response

        except Exception as e:
            self.logger.error(f"Error in send_request: {str(e)}", exc_info=True)
            raise

    def parse_profile_entry(self, text: str) -> ProfileEntry:
        try:
            lines = text.split('\n')
            header = lines[0]

            match = re.search(r'(\d{2}\.\d{4}|\d{4}) год', header)
            year_month = match.group(1) if match else None

            data = {'year_month': year_month}

            for line in lines[1:]:
                if ':' not in line:
                    continue

                key_part, value = line.split(':', 1)
                key_part = re.sub(r'\*\*|__', '', key_part).strip()
                value = value.strip()
                if key_part in self.key_mapping:
                    mapped_key = self.key_mapping[key_part]

                    if mapped_key == 'followers':
                        try:
                            value = int(value)
                        except (ValueError, TypeError):
                            self.logger.warning(f"Could not convert followers value to int: {value}")
                            value = None

                    if mapped_key == 'url' and not value.startswith('http'):
                        value = f"https://{value}"

                    data[mapped_key] = value

            self.logger.debug(f"Final parsed data: {data}")

            return ProfileEntry(**data)
        except Exception as e:
            self.logger.info(f"Error parsing profile entry: {str(e)}")
            self.logger.info(f"Text being parsed: {text}")
            raise


    def parse_photo_urls(self, text: str) -> List[str]:
        try:
            urls = []
            lines = text.split('\n')[1:]

            for line in lines:
                if '▪️' in line:
                    url = line.split('▪️')[-1].strip()
                    if url:
                        if not url.startswith('http'):
                            url = f"https://{url}"
                        urls.append(url)
                        self.logger.debug(f"Parsed photo URL: {url}")

            return urls
        except Exception as e:
            self.logger.error(f"Error parsing photo URLs: {str(e)}")
            self.logger.error(f"Text being parsed: {text}")
            return []
