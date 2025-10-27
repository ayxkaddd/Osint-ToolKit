import aiohttp
import asyncio
import random
import json
import time
import logging
from typing import List, Optional, AsyncGenerator
from urllib.parse import urlparse, parse_qs, quote
from bs4 import BeautifulSoup
from fastapi import HTTPException
from dataclasses import dataclass, asdict
from enum import Enum
from collections import defaultdict
import re
from aiohttp import TCPConnector, ClientTimeout
from functools import lru_cache
from datetime import datetime
import uuid

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    from socid_extractor import extract
except ImportError:
    extract = None
    logger.warning("socid_extractor not installed. Profile extraction disabled.")


class CheckStatus(Enum):
    """Status of username check"""
    FOUND = "found"
    NOT_FOUND = "not_found"
    ERROR = "error"
    RATE_LIMITED = "rate_limited"
    CHECKING = "checking"


class EventType(Enum):
    """Types of events sent to client"""
    SEARCH_STARTED = "search_started"
    SITE_CHECKING = "site_checking"
    SITE_RESULT = "site_result"
    SEARCH_PROGRESS = "search_progress"
    SEARCH_COMPLETED = "search_completed"
    ERROR = "error"
    DUCKDUCKGO_STARTED = "duckduckgo_started"
    DUCKDUCKGO_RESULT = "duckduckgo_result"


def serialize_enum_dict(data: dict) -> dict:
    """Recursively serialize enum values in a dictionary to their string values"""
    if isinstance(data, dict):
        return {key: serialize_enum_dict(value) for key, value in data.items()}
    elif isinstance(data, list):
        return [serialize_enum_dict(item) for item in data]
    elif isinstance(data, Enum):
        return data.value
    else:
        return data


@dataclass
class StreamEvent:
    """Event to be streamed to client"""
    event_type: EventType
    data: dict
    timestamp: str = None

    def __post_init__(self):
        if not self.timestamp:
            from datetime import datetime, timezone
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        """Convert to dict with serializable event_type and data"""
        d = asdict(self)
        d["event_type"] = self.event_type.value
        d["data"] = serialize_enum_dict(d["data"])
        return d

    def to_sse(self) -> str:
        """Convert to Server-Sent Event format"""
        return f"data: {json.dumps(self.to_dict())}\n\n"

    def to_json(self) -> dict:
        """Convert to JSON for WebSocket"""
        return self.to_dict()


@dataclass
class SiteResult:
    """Result from checking a single site"""
    site_name: str
    category: str
    url: str
    status: CheckStatus
    status_code: Optional[int] = None
    profile_data: Optional[dict] = None
    error_message: Optional[str] = None
    response_time: Optional[float] = None
    checked_at: Optional[str] = None

    def __post_init__(self):
        if not self.checked_at:
            self.checked_at = datetime.utcnow().isoformat()

    def to_dict(self) -> dict:
        """Convert to dict with serialized enum values"""
        data = asdict(self)
        data["status"] = self.status.value
        return data


class RateLimiter:
    """Rate limiter for API requests"""
    def __init__(self, max_requests: int = 100, time_window: int = 60):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = defaultdict(list)
        self._lock = asyncio.Lock()

    async def wait_if_needed(self, domain: str) -> float:
        """Wait if rate limit would be exceeded, return wait time"""
        async with self._lock:
            now = time.time()
            self.requests[domain] = [
                t for t in self.requests[domain]
                if now - t < self.time_window
            ]

            if len(self.requests[domain]) >= self.max_requests:
                sleep_time = self.time_window - (now - self.requests[domain][0])
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
                    self.requests[domain].clear()
                    self.requests[domain].append(time.time())
                    return sleep_time

            self.requests[domain].append(now)
            return 0


class StreamingUsernameSearchService:
    def __init__(self,
                 max_concurrent_requests: int = 30,
                 timeout_seconds: int = 10,
                 max_retries: int = 1,
                 stream_delay: float = 0.05):
        """
        Initialize streaming service

        Args:
            max_concurrent_requests: Maximum concurrent HTTP requests
            timeout_seconds: Timeout for each request
            max_retries: Maximum retries per site
            stream_delay: Small delay between streaming events for smoother client experience
        """
        self.max_concurrent_requests = max_concurrent_requests
        self.timeout = ClientTimeout(total=timeout_seconds)
        self.max_retries = max_retries
        self.stream_delay = stream_delay
        self._metadata_cache = None
        self.rate_limiter = RateLimiter()
        self.semaphore = asyncio.Semaphore(max_concurrent_requests)

        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
        ]

        self._url_pattern = re.compile(r'\{account\}')
        self._regex_cache = {}

    @lru_cache(maxsize=1)
    def get_metadata(self) -> dict:
        """Fetch and cache metadata"""
        if self._metadata_cache:
            return self._metadata_cache

        url = "https://raw.githubusercontent.com/WebBreacher/WhatsMyName/refs/heads/main/wmn-data.json"
        try:
            import requests
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            self._metadata_cache = response.json()
            return self._metadata_cache
        except Exception as e:
            logger.error(f"Failed to fetch metadata: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to fetch metadata: {str(e)}")

    def get_random_user_agent(self) -> str:
        """Get random user agent"""
        return random.choice(self.user_agents)

    def _get_compiled_regex(self, pattern: str) -> Optional[re.Pattern]:
        """Get or compile regex pattern with caching"""
        if pattern not in self._regex_cache:
            try:
                self._regex_cache[pattern] = re.compile(pattern, re.IGNORECASE)
            except re.error:
                self._regex_cache[pattern] = None
        return self._regex_cache[pattern]

    def _try_parse_json(self, text: str) -> Optional[dict]:
        """Try to parse text as JSON, return dict or None"""
        try:
            text = text.strip()

            if text.startswith(('{', '[')):
                data = json.loads(text)
                if isinstance(data, dict):
                    return data

            brace_start = text.find('{')
            if brace_start != -1:
                brace_count = 0
                for i in range(brace_start, len(text)):
                    if text[i] == '{':
                        brace_count += 1
                    elif text[i] == '}':
                        brace_count -= 1
                        if brace_count == 0:
                            json_str = text[brace_start:i+1]
                            data = json.loads(json_str)
                            if isinstance(data, dict):
                                return data
                            break
        except (json.JSONDecodeError, ValueError):
            pass
        return None

    async def _check_response_match(self,
                                   response_status: int,
                                   text: str,
                                   site: dict) -> tuple[bool, bool]:
        """Check if response matches expected patterns"""
        if response_status == site.get("e_code"):
            e_string = site.get("e_string", "")
            if e_string:
                if any(char in e_string for char in ['*', '+', '?', '[', ']', '(', ')', '|', '^', '$']):
                    compiled_pattern = self._get_compiled_regex(e_string)
                    if compiled_pattern:
                        if compiled_pattern.search(text):
                            return True, False
                    else:
                        if e_string in text:
                            return True, False
                else:
                    if e_string in text:
                        return True, False

        if "m_code" in site and "m_string" in site:
            if response_status == site["m_code"]:
                m_string = site["m_string"]
                if any(char in m_string for char in ['*', '+', '?', '[', ']', '(', ')', '|', '^', '$']):
                    compiled_pattern = self._get_compiled_regex(m_string)
                    if compiled_pattern:
                        if compiled_pattern.search(text):
                            return False, True
                    else:
                        if m_string in text:
                            return False, True
                else:
                    if m_string in text:
                        return False, True

        return False, False

    async def check_single_site(self,
                               session: aiohttp.ClientSession,
                               site: dict,
                               username: str,
                               extract_profile: bool = False) -> SiteResult:
        """Check username on a single site"""
        url = self._url_pattern.sub(quote(username), site["uri_check"])
        domain = urlparse(url).netloc

        start_time = time.time()

        async with self.semaphore:
            wait_time = await self.rate_limiter.wait_if_needed(domain)
            if wait_time > 0:
                logger.debug(f"Rate limited for {domain}, waited {wait_time:.2f}s")

            headers = {
                "User-Agent": self.get_random_user_agent(),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate, br",
                "DNT": "1",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
            }

            if "headers" in site:
                headers.update(site["headers"])

            try:
                async with session.get(
                    url,
                    headers=headers,
                    timeout=self.timeout,
                    allow_redirects=True,
                    ssl=False
                ) as response:
                    raw_bytes = await response.read()

                    text = None
                    encodings = ['utf-8', 'utf-8-sig', 'latin-1', 'iso-8859-1', 'windows-1252']

                    for encoding in encodings:
                        try:
                            text = raw_bytes.decode(encoding)
                            break
                        except (UnicodeDecodeError, LookupError):
                            continue

                    if not text:
                        text = raw_bytes.decode('utf-8', errors='ignore')

                    response_time = time.time() - start_time

                    is_found, is_not_found = await self._check_response_match(
                        response.status, text, site
                    )

                    if is_found:
                        result = SiteResult(
                            site_name=site["name"],
                            category=site.get("cat", "unknown"),
                            url=url,
                            status=CheckStatus.FOUND,
                            status_code=response.status,
                            response_time=response_time
                        )

                        if extract_profile:
                            profile_data = None

                            if extract:
                                try:
                                    profile_data = extract(text)
                                except Exception as e:
                                    logger.debug(f"socid_extractor failed for {url}: {str(e)}")

                            if not profile_data:
                                json_data = self._try_parse_json(text)
                                if json_data:
                                    profile_data = json_data

                            if profile_data:
                                result.profile_data = profile_data

                        return result

                    elif is_not_found:
                        return SiteResult(
                            site_name=site["name"],
                            category=site.get("cat", "unknown"),
                            url=url,
                            status=CheckStatus.NOT_FOUND,
                            status_code=response.status,
                            response_time=response_time
                        )
                    else:
                        return SiteResult(
                            site_name=site["name"],
                            category=site.get("cat", "unknown"),
                            url=url,
                            status=CheckStatus.ERROR,
                            status_code=response.status,
                            error_message="Response doesn't match expected patterns",
                            response_time=response_time
                        )

            except asyncio.TimeoutError:
                return SiteResult(
                    site_name=site["name"],
                    category=site.get("cat", "unknown"),
                    url=url,
                    status=CheckStatus.ERROR,
                    error_message="Timeout",
                    response_time=time.time() - start_time
                )
            except aiohttp.ClientError as e:
                return SiteResult(
                    site_name=site["name"],
                    category=site.get("cat", "unknown"),
                    url=url,
                    status=CheckStatus.ERROR,
                    error_message=f"Client error: {str(e)}",
                    response_time=time.time() - start_time
                )
            except Exception as e:
                return SiteResult(
                    site_name=site["name"],
                    category=site.get("cat", "unknown"),
                    url=url,
                    status=CheckStatus.ERROR,
                    error_message=str(e),
                    response_time=time.time() - start_time
                )

    async def check_site_with_retry(self,
                                   session: aiohttp.ClientSession,
                                   site: dict,
                                   username: str,
                                   extract_profile: bool = False) -> SiteResult:
        """Check site with retry logic"""
        last_result = None

        for attempt in range(self.max_retries):
            result = await self.check_single_site(session, site, username, extract_profile)

            if result.status in [CheckStatus.FOUND, CheckStatus.NOT_FOUND]:
                return result

            last_result = result

            if result.error_message and any(x in result.error_message.lower()
                                           for x in ['timeout', 'rate limit', 'too many']):
                if attempt < self.max_retries - 1:
                    backoff_time = 0.2 * (2 ** attempt)
                    await asyncio.sleep(backoff_time)
            else:
                break

        return last_result

    async def stream_duckduckgo_search(self,
                                      session: aiohttp.ClientSession,
                                      username: str,
                                      queue: asyncio.Queue):
        """Stream DuckDuckGo results"""
        await queue.put(StreamEvent(
            event_type=EventType.DUCKDUCKGO_STARTED,
            data={"message": "Starting DuckDuckGo search"}
        ))

        query = quote(f'"{username}"')
        url = f"https://duckduckgo.com/html/?q={query}"
        headers = {
            "User-Agent": self.get_random_user_agent(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        }

        try:
            async with session.get(url, headers=headers, timeout=self.timeout) as response:
                if response.status == 200:
                    text = await response.text()
                    soup = BeautifulSoup(text, "html.parser")
                    seen_domains = set()

                    for a_tag in soup.find_all("a", class_="result__a", href=True):
                        href = a_tag.get("href", "")
                        real_url = None

                        if "duckduckgo.com/l/?" in href:
                            parsed_url = urlparse(href)
                            real_url = parse_qs(parsed_url.query).get("uddg", [None])[0]
                        elif "duckduckgo.com" not in href:
                            real_url = href

                        if real_url:
                            domain = urlparse(real_url).netloc
                            if domain and domain not in seen_domains:
                                seen_domains.add(domain)

                                await queue.put(StreamEvent(
                                    event_type=EventType.DUCKDUCKGO_RESULT,
                                    data={
                                        "url": real_url,
                                        "domain": domain,
                                        "title": a_tag.get_text(strip=True)
                                    }
                                ))
                                await asyncio.sleep(self.stream_delay)

        except Exception as e:
            logger.error(f"DuckDuckGo search error: {str(e)}")

    async def stream_search(self,
                           username: str,
                           include_duckduckgo: bool = False,
                           extract_profile: bool = False,
                           categories: Optional[List[str]] = None,
                           priority_sites: Optional[List[str]] = None) -> AsyncGenerator[StreamEvent, None]:
        """
        Stream search results as they become available
        """
        search_id = str(uuid.uuid4())
        start_time = time.time()

        metadata = self.get_metadata()
        sites = metadata.get("sites", [])

        if categories:
            categories_set = set(categories)
            sites = [s for s in sites if s.get("cat") in categories_set]

        if priority_sites:
            priority_set = set(priority_sites)
            priority = [s for s in sites if s.get("name") in priority_set]
            regular = [s for s in sites if s.get("name") not in priority_set]
            sites = priority + regular

        yield StreamEvent(
            event_type=EventType.SEARCH_STARTED,
            data={
                "search_id": search_id,
                "username": username,
                "total_sites": len(sites),
                "categories": categories,
                "include_duckduckgo": include_duckduckgo,
                "extract_profile": extract_profile
            }
        )

        found_count = 0
        not_found_count = 0
        error_count = 0
        checked_count = 0

        result_queue = asyncio.Queue()

        async def process_site(site: dict):
            """Process a single site and add to queue"""
            await result_queue.put(StreamEvent(
                event_type=EventType.SITE_CHECKING,
                data={
                    "site_name": site["name"],
                    "category": site.get("cat", "unknown"),
                    "url": site["uri_check"].replace("{account}", username)
                }
            ))

            result = await self.check_site_with_retry(
                session, site, username, extract_profile
            )

            await result_queue.put(StreamEvent(
                event_type=EventType.SITE_RESULT,
                data=result.to_dict()
            ))

        connector = TCPConnector(
            limit=self.max_concurrent_requests,
            limit_per_host=5,
            ttl_dns_cache=300,
            force_close=False,
            enable_cleanup_closed=True
        )

        async with aiohttp.ClientSession(
            connector=connector,
            timeout=self.timeout,
            trust_env=True
        ) as session:
            tasks = []
            for site in sites:
                task = asyncio.create_task(process_site(site))
                tasks.append(task)

            if include_duckduckgo:
                ddg_task = asyncio.create_task(
                    self.stream_duckduckgo_search(session, username, result_queue)
                )
                tasks.append(ddg_task)

            sites_to_process = len(sites) * 2
            events_processed = 0

            while events_processed < sites_to_process or not result_queue.empty():
                try:
                    event = await asyncio.wait_for(
                        result_queue.get(),
                        timeout=1.0
                    )

                    if event.event_type == EventType.SITE_RESULT:
                        checked_count += 1
                        site_data = event.data

                        if site_data["status"] == CheckStatus.FOUND.value:
                            found_count += 1
                        elif site_data["status"] == CheckStatus.NOT_FOUND.value:
                            not_found_count += 1
                        else:
                            error_count += 1

                        event.data["progress"] = {
                            "checked": checked_count,
                            "total": len(sites),
                            "found": found_count,
                            "not_found": not_found_count,
                            "errors": error_count,
                            "percentage": round((checked_count / len(sites)) * 100, 2)
                        }

                    yield event

                    await asyncio.sleep(self.stream_delay)

                    if event.event_type in [EventType.SITE_CHECKING, EventType.SITE_RESULT]:
                        events_processed += 1

                except asyncio.TimeoutError:
                    if all(task.done() for task in tasks):
                        break
                    continue

            await asyncio.gather(*tasks, return_exceptions=True)

            while not result_queue.empty():
                event = await result_queue.get()

                if event.event_type == EventType.SITE_RESULT:
                    checked_count += 1
                    site_data = event.data

                    if site_data["status"] == CheckStatus.FOUND.value:
                        found_count += 1
                    elif site_data["status"] == CheckStatus.NOT_FOUND.value:
                        not_found_count += 1
                    else:
                        error_count += 1

                    event.data["progress"] = {
                        "checked": checked_count,
                        "total": len(sites),
                        "found": found_count,
                        "not_found": not_found_count,
                        "errors": error_count,
                        "percentage": round((checked_count / len(sites)) * 100, 2)
                    }

                yield event
                await asyncio.sleep(self.stream_delay)

        # Yield completion event
        elapsed_time = time.time() - start_time
        yield StreamEvent(
            event_type=EventType.SEARCH_COMPLETED,
            data={
                "search_id": search_id,
                "username": username,
                "total_found": found_count,
                "total_not_found": not_found_count,
                "total_errors": error_count,
                "total_checked": checked_count,
                "search_time_seconds": round(elapsed_time, 2),
                "success_rate": round((found_count / checked_count) * 100, 2) if checked_count > 0 else 0
            }
        )