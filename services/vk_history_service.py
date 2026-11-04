import asyncio
import re
import time
from collections.abc import AsyncGenerator
from typing import Optional

from utils import telegram_client
import logging


from models.vk_history_models import ProfileEntry

# Field labels in the bot's snapshots, lower case and without the emoji in front
# (the same label comes with different emoji: "⚧ Пол", "👩‍❤️‍👨 Пол"). A label with a
# note in brackets ("Мобильный телефон (был указан в профиле)") is also looked up
# without it. Unknown labels are kept under ProfileEntry.other.
FIELD_LABELS = {
    'url вконтакте': 'url', 'url': 'url',
    'id вконтакте': 'vk_id',
    'username вк': 'username',
    'ф.и.': 'full_name', 'ф.и. (нормал.)': 'normalized_name',
    'фамилия': 'last_name', 'имя': 'first_name', 'aka': 'aka',
    'пол': 'gender', 'дата рождения': 'birth_date',
    'страна': 'country', 'регион': 'region', 'родной город': 'hometown', 'город': 'city',
    'контактная эл. почта': 'email', 'эл. почта': 'email', 'email': 'email',
    'мобильный телефон': 'mobile_phone', 'домашний телефон': 'home_phone', 'телефон': 'mobile_phone',
    'icq': 'icq', 'контакты': 'contacts',
    'сайт': 'website', 'www': 'website', 'домашняя страница': 'homepage',
    'последний вход': 'last_login', 'последний визит': 'last_visit', 'устройство': 'device',
    'фолловеры': 'followers', 'подписчики': 'followers',
    'университет': 'university', 'факультет': 'faculty', 'образование': 'education', 'карьера': 'career',
    'сем. положение': 'marital_status', 'семейное положение': 'marital_status', 'семья': 'family',
    'интересы': 'interests', 'музыка': 'music', 'фильмы': 'movies', 'тв': 'tv', 'книги': 'books',
    'игры': 'games', 'фото': 'photos',
}
# What the bot writes for "nothing"
EMPTY_VALUES = {'', '-', '--', '---', '----', '—', 'нет', 'null', 'none'}
# "❌ По этому профилю в 04.2022 году ничего не найдено!"
NOTHING_FOR_RE = re.compile(r'в\s+((?:\d{2}\.)?\d{4})\s+году\s+ничего не найдено', re.I)
# Emoji in front of a label ("ℹ️" counts as a letter for \w, so letters are listed)
LEADING_SYMBOLS_RE = re.compile(r'^[^0-9A-Za-zА-Яа-яЁё]+')
# "16.02.2017 23:08:52(Iphone)": the device the visit was made from
VISIT_DEVICE_RE = re.compile(r'^(.*?\d)\s*\(([^()]+)\)\s*$')

class VkHistoryService:
    timeout = 60          # seconds to wait for the bot to finish
    poll_interval = 1     # seconds between checks for new bot messages

    def __init__(self):
        self.session_name = "telegram_session"
        self.logger = logging.getLogger(__name__)
        if not telegram_client.is_configured():
            self.logger.warning("Telegram API ID and hash are not set; VK history needs them")

        self.client = None
        self._bot_lock = asyncio.Lock()

    async def ensure_client(self):
        """Use the app-wide Telegram client (one client per session file)."""
        self.client = await telegram_client.ensure_connected()

    @staticmethod
    def normalize_target(value: str) -> str:
        """Accept a VK id, id123, @screen_name or a vk.com link."""
        value = (value or "").strip()
        match = re.search(r"(?:https?://)?(?:m\.)?vk\.(?:com|ru)/([A-Za-z0-9_.]+)", value)
        if match:
            value = match.group(1)
        value = value.lstrip("@")
        if re.fullmatch(r"id\d+", value):
            value = value[2:]
        return value

    def strip_telegram_formatting(self, text: str) -> str:
        return re.sub(r'\*\*|__', '', text).strip()


    async def stream_request(self, user_id: str) -> AsyncGenerator[dict, None]:
        """Ask the bot about a profile and yield its answers as they arrive:

        * ``{"event": "waiting"}`` - another lookup is talking to the bot first
        * ``{"event": "started", "user_id"}``
        * ``{"event": "entry", "entry"}`` - one snapshot of the profile
        * ``{"event": "photos", "photos"}``
        * ``{"event": "nothing_for", "period"}`` - the bot has no snapshot for that month/year
        * ``{"event": "notice", "text"}`` - limits, "not found", other bot replies
        * ``{"event": "error", "detail"}``
        * ``{"event": "done", "complete", "count"}`` - complete is False after the timeout

        The caller connects the client and checks the target first (ensure_client,
        normalize_target), so those errors can still be answered with a status code.
        """
        user_id = self.normalize_target(user_id)
        # One conversation with the bot at a time: replies carry no request
        # id, so concurrent lookups would mix their answers.
        if self._bot_lock.locked():
            yield {"event": "waiting"}
        async with self._bot_lock:
            yield {"event": "started", "user_id": user_id}
            try:
                async for event in self._converse(user_id):
                    yield event
            except Exception as e:
                self.logger.error('VK history lookup failed: %s', str(e), exc_info=True)
                yield {"event": "error", "detail": str(e)}

    async def _converse(self, user_id: str) -> AsyncGenerator[dict, None]:
        bot_username = 'VKInfoRobot'
        bot_entity = await self.client.get_entity(bot_username)

        sent_msg = await self.client.send_message(bot_entity, user_id)
        self.logger.info('Message sent with ID: %s', sent_msg.id)

        start_time = time.time()
        last_message_id = sent_msg.id
        count = 0

        while time.time() - start_time < self.timeout:
            # Oldest first, so the answers come out in the bot's order
            messages = await self.client.get_messages(bot_entity, min_id=last_message_id, reverse=True)
            if not messages:
                await asyncio.sleep(self.poll_interval)
                continue

            completion_received = False
            for message in messages:
                plain_text = self.strip_telegram_formatting(message.text or '')
                self.logger.info('Processing message ID %s: %s...', message.id, plain_text[:100])
                last_message_id = max(last_message_id, message.id)

                if 'Поиск завершён!' in plain_text:
                    completion_received = True
                elif plain_text.startswith('🌐 История профиля ВКонтакте'):
                    count += 1
                    yield {"event": "entry", "entry": self.parse_profile_entry(plain_text).model_dump()}
                elif plain_text.startswith('🏞 Связанные с профилем фото'):
                    photos = self.parse_photo_urls(plain_text)
                    if photos:
                        yield {"event": "photos", "photos": photos}
                elif match := NOTHING_FOR_RE.search(plain_text):
                    yield {"event": "nothing_for", "period": match.group(1)}
                elif 'Поиск займёт' in plain_text:
                    continue   # "this will take a while"
                elif plain_text:
                    # Limits, "no listings found", "not a bot", subscription prompts, errors...
                    yield {"event": "notice", "text": plain_text[:500]}

            # Messages that came with the completion marker are handled first
            if completion_received:
                self.logger.info("Search completed successfully")
                yield {"event": "done", "complete": True, "count": count}
                return
            await asyncio.sleep(self.poll_interval)

        self.logger.warning("Timeout reached waiting for bot response")
        yield {"event": "done", "complete": False, "count": count}

    @staticmethod
    def _field_for(label: str) -> Optional[str]:
        label = LEADING_SYMBOLS_RE.sub('', label).strip().lower()
        return FIELD_LABELS.get(label) or FIELD_LABELS.get(re.sub(r'\s*\([^)]*\)', '', label).strip())

    def parse_profile_entry(self, text: str) -> ProfileEntry:
        """One snapshot ("🌐 История профиля ВКонтакте 08.2023 год:" and a line per field)."""
        lines = text.split('\n')
        match = re.search(r'(\d{2}\.\d{4}|\d{4}) год', lines[0])
        data: dict = {'year_month': match.group(1) if match else None, 'photos': [], 'other': {}}

        for line in lines[1:]:
            if ':' not in line:
                continue
            label, value = line.split(':', 1)
            label = re.sub(r'\*\*|__', '', label).strip()
            value = value.strip()
            if value.lower() in EMPTY_VALUES:
                continue
            field = self._field_for(label)
            shown_label = LEADING_SYMBOLS_RE.sub('', label).strip() or label
            if field is None:
                data['other'][shown_label] = value
            elif field == 'photos':
                for url in value.split(';'):
                    url = url.strip()
                    if url and url.lower() not in EMPTY_VALUES:
                        url = url if url.startswith('http') else f"https://{url}"
                        if url not in data['photos']:
                            data['photos'].append(url)
            elif field == 'followers':
                try:
                    data[field] = int(value.replace(' ', ''))
                except ValueError:
                    data['other'][shown_label] = value
            elif field in data:
                continue   # the first of two labels for one field wins ("Сайт", "WWW")
            else:
                if field == 'url' and not value.startswith('http'):
                    value = f"https://{value}"
                if field == 'last_visit' and (visit := VISIT_DEVICE_RE.match(value)):
                    value = visit.group(1)
                    data.setdefault('device', visit.group(2))
                data[field] = value

        if data['photos']:
            data['avatar'] = data['photos'][0]
        return ProfileEntry(**data)

    def parse_photo_urls(self, text: str) -> list[str]:
        try:
            urls = []
            lines = text.split('\n')[1:]  # Skip the header line

            for line in lines:
                if '▪️' in line:
                    url = line.split('▪️')[-1].strip()
                    if url:
                        # Ensure URL is properly formatted
                        if not url.startswith('http'):
                            url = f"https://{url}"
                        urls.append(url)
                        self.logger.debug('Parsed photo URL: %s', url)

            return urls
        except Exception as e:
            self.logger.error('Error parsing photo URLs: %s', str(e))
            self.logger.error('Text being parsed: %s', text)
            return []
