import asyncio
from pathlib import Path
import random
import json
import time
import os
import logging
from typing import List, Optional, AsyncGenerator
from urllib.parse import parse_qsl, urlparse, parse_qs, quote
from bs4 import BeautifulSoup
from fastapi import HTTPException
from dataclasses import dataclass, asdict
from enum import Enum
from collections import defaultdict
import re
import httpx
from datetime import datetime
import uuid

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ACCOUNT = "{account}"  # where the username goes in WhatsMyName URLs and bodies

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
    PROFILE_EXTRACTED = "profile_extracted"


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


@dataclass
class SiteCheckOutcome:
    """Internal site check result plus response body for optional enrichment."""
    result: SiteResult
    response_text: Optional[str] = None


class RateLimiter:
    """Rate limiter for API requests"""
    def __init__(self, max_requests: int = 100, time_window: int = 60):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = defaultdict(list)
        self._lock = asyncio.Lock()

    async def wait_if_needed(self, domain: str) -> float:
        """Wait if rate limit would be exceeded, return wait time"""
        waited = 0.0
        while True:
            # Sleep outside the lock: it is shared by every check of every search
            async with self._lock:
                now = time.time()
                self.requests[domain] = [
                    t for t in self.requests[domain]
                    if now - t < self.time_window
                ]
                if len(self.requests[domain]) < self.max_requests:
                    self.requests[domain].append(now)
                    return waited
                sleep_time = self.time_window - (now - self.requests[domain][0])
            await asyncio.sleep(max(sleep_time, 0.05))
            waited += sleep_time


class StreamingUsernameSearchService:
    def __init__(self,
                 max_concurrent_requests: int = 30,
                 timeout_seconds: int = 10,
                 connect_timeout_seconds: int = 5,
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
        # Blocked/dead hosts never complete the TCP connect: give up on those
        # early instead of holding a slot for the whole timeout
        self.timeout_seconds = timeout_seconds
        self.timeout = httpx.Timeout(timeout_seconds, connect=connect_timeout_seconds)
        self.max_retries = max_retries
        self.stream_delay = stream_delay
        self._metadata_cache = None
        self.rate_limiter = RateLimiter()
        self.semaphore = asyncio.Semaphore(max_concurrent_requests)
        # At most this many requests to one host at a time (sites sharing a host)
        self.per_host_limit = 5
        self._host_slots: dict = defaultdict(lambda: asyncio.Semaphore(self.per_host_limit))

        # Modern user agents
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
        ]

        self.base_headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
        }

        self._url_pattern = re.compile(r'\{account\}')
        self._account_confirmation_sites = {
            "Arch Linux GitLab",
            "Fanslist (OnlyFans)",
            "HackerOne",
            "InkBunny",
            "Mixi",
            "PatientsLikeMe",
            "Pinterest",
            "prv.pl",
            "ru_123rf",
            "thegatewaypundit",
            "Ubisoft",
            "Zbiornik",
        }

    WMN_URL = "https://raw.githubusercontent.com/WebBreacher/WhatsMyName/refs/heads/main/wmn-data.json"
    WMN_LOCAL = Path("assets") / "wmn-data.json"
    WMN_MAX_AGE = 24 * 3600

    def get_metadata(self) -> dict:
        """WhatsMyName site list. The local copy in assets/ is used straight away
        (a search must not wait on GitHub, which can be slow or unreachable);
        it is refreshed in the background when older than a day.
        Blocking - call it via asyncio.to_thread from async code."""
        if self._metadata_cache:
            return self._metadata_cache

        if self.WMN_LOCAL.exists():
            self._metadata_cache = json.loads(self.WMN_LOCAL.read_text())
            if time.time() - self.WMN_LOCAL.stat().st_mtime > self.WMN_MAX_AGE:
                import threading
                threading.Thread(target=self._refresh_metadata, daemon=True).start()
            return self._metadata_cache

        # No local copy yet: nothing to fall back on, so this one fetch must wait
        try:
            self._refresh_metadata(raise_errors=True)
            return self._metadata_cache
        except Exception as e:
            logger.error(f"Failed to fetch metadata: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to fetch the WhatsMyName site list: {str(e)}")

    def _refresh_metadata(self, raise_errors: bool = False):
        """Download the current WhatsMyName list and save it to assets/."""
        try:
            response = httpx.get(self.WMN_URL, timeout=httpx.Timeout(20, connect=5), follow_redirects=True)
            response.raise_for_status()
            data = response.json()
            if not data.get("sites"):
                raise ValueError("list has no sites")
            self.WMN_LOCAL.parent.mkdir(exist_ok=True)
            tmp = self.WMN_LOCAL.with_suffix(".json.part")
            tmp.write_text(response.text)
            tmp.replace(self.WMN_LOCAL)
            self._metadata_cache = data
            logger.info("WhatsMyName list updated: %d sites", len(data["sites"]))
        except Exception as e:
            if raise_errors:
                raise
            logger.warning(f"Could not update the WhatsMyName list ({e}); keeping the local copy")
            try:
                # Don't retry on every search when GitHub is unreachable
                os.utime(self.WMN_LOCAL)
            except OSError:
                pass

    def get_random_user_agent(self) -> str:
        """Get random user agent"""
        return random.choice(self.user_agents)

    def _text_matches_pattern(self, text: str, pattern: Optional[str]) -> bool:
        """
        Match text against a WMN marker. Markers are plain text, not regexes:
        reading them as regexes made "|" and "." wildcards and gave false
        positives (" | Cafecito</title>" matched any page titled "Cafecito").
        Empty marker means "status-code-only" match in WMN data.
        """
        if pattern is None:
            return False
        if pattern == "":
            return True
        return pattern in text or pattern.casefold() in text.casefold()

    def _response_confirms_account(self, site: dict, username: str, text: str) -> bool:
        """Extra guard for noisy WMN checks whose positive strings are generic."""
        site_name = site.get("name")
        if site_name not in self._account_confirmation_sites:
            return True

        username_folded = username.casefold()
        text_folded = text.casefold()

        if site_name == "Arch Linux GitLab":
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                return False
            if not isinstance(data, list):
                return False
            for item in data:
                if not isinstance(item, dict):
                    continue
                for field in ("username", "path", "name"):
                    value = item.get(field)
                    if isinstance(value, str) and value.casefold() == username_folded:
                        return True
            return False

        if site_name == "Fanslist (OnlyFans)":
            pattern = rf'data-username=["\']{re.escape(username)}["\']'
            return bool(re.search(pattern, text, re.IGNORECASE))

        if site_name == "HackerOne":
            pattern = rf'"username"\s*:\s*"{re.escape(username)}"'
            return bool(re.search(pattern, text, re.IGNORECASE))

        if site_name == "Pinterest":
            title_pattern = rf'\({re.escape(username)}\)\s*-\s*Profile\s*\|\s*Pinterest'
            return bool(re.search(title_pattern, text, re.IGNORECASE))

        if site_name == "thegatewaypundit":
            return f"/author/{username_folded}/" in text_folded

        return username_folded in text_folded

    def _try_parse_json(self, text: str) -> Optional[dict]:
        """Try to parse text as JSON, return dict or None"""
        try:
            # Try to find JSON in the text
            text = text.strip()

            # If it starts with { or [, try parsing directly
            if text.startswith(('{', '[')):
                data = json.loads(text)
                # Only return if it's a dict (not a list)
                if isinstance(data, dict):
                    return data

            # Try to find JSON object in text
            brace_start = text.find('{')
            if brace_start != -1:
                # Find matching closing brace
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

    def _check_response_match(self,
                                   response_status: int,
                                   text: str,
                                   site: dict,
                                   redirect_statuses: Optional[List[int]] = None) -> tuple[bool, bool]:
        """Check if response matches expected patterns"""
        redirect_statuses = redirect_statuses or []

        # Some WMN entries use redirects as the not-found signal. Because we
        # follow redirects to fetch the final page, preserve that signal here.
        if "m_code" in site and site["m_code"] in redirect_statuses:
            return False, True

        # Check for negative match first. Several sites return the same status
        # code for found and not-found pages, and their not-found page can also
        # contain broad positive strings like "LOGIN" or a shared page title.
        if "m_code" in site and response_status == site["m_code"]:
            m_string = site.get("m_string")
            if self._text_matches_pattern(text, m_string):
                return False, True

        # Check for positive match
        if response_status == site.get("e_code"):
            e_string = site.get("e_string")
            if self._text_matches_pattern(text, e_string):
                return True, False

        return False, False

    def _build_request(self, site: dict, username: str) -> tuple:
        """(url, method, request kwargs) for one site: GET, JSON POST or form POST."""
        url = self._url_pattern.sub(quote(username), site["uri_check"]).replace(ACCOUNT, quote(username))
        headers = self.base_headers.copy()
        headers["User-Agent"] = self.get_random_user_agent()
        headers.update(site.get("headers") or {})
        kwargs = {"headers": headers}
        if not site.get("post_body"):
            return url, "GET", kwargs

        post_body = site["post_body"].replace(ACCOUNT, username)
        content_type = headers.get("Content-Type", "").lower()
        if "json" in content_type:
            try:
                json_data = json.loads(post_body)
            except json.JSONDecodeError:
                json_data = None
            if isinstance(json_data, dict):
                kwargs["json"] = json_data
        elif "form-urlencoded" in content_type:
            form = dict(parse_qsl(post_body))
            if form:
                kwargs["data"] = form
        elif post_body:
            kwargs["content"] = post_body
        return url, "POST", kwargs

    def _outcome(self, site: dict, username: str, url: str, response: httpx.Response,
                 response_time: float, extract_profile: bool) -> SiteCheckOutcome:
        """Found / not found / no match, from a site's response."""
        raw = response.content
        try:
            text = raw.decode('utf-8')
        except UnicodeDecodeError:
            text = raw.decode('latin-1', errors='ignore')
        is_found, is_not_found = self._check_response_match(
            response.status_code, text, site, [r.status_code for r in response.history])
        if is_found and not self._response_confirms_account(site, username, text):
            is_found, is_not_found = False, True

        base = {"site_name": site["name"], "category": site.get("cat", "unknown"),
                "status_code": response.status_code, "response_time": response_time}
        if is_found:
            pretty = site.get("uri_pretty", site["uri_check"]).replace(ACCOUNT, username)
            return SiteCheckOutcome(result=SiteResult(**base, url=pretty, status=CheckStatus.FOUND),
                                    response_text=text if extract_profile else None)
        if is_not_found:
            return SiteCheckOutcome(result=SiteResult(**base, url=url, status=CheckStatus.NOT_FOUND))
        return SiteCheckOutcome(result=SiteResult(**base, url=url, status=CheckStatus.ERROR,
                                                  error_message="Response doesn't match expected patterns"))

    @staticmethod
    def _error(site: dict, url: str, message: str, start_time: float) -> SiteCheckOutcome:
        return SiteCheckOutcome(result=SiteResult(
            site_name=site["name"], category=site.get("cat", "unknown"), url=url,
            status=CheckStatus.ERROR, error_message=message, response_time=time.time() - start_time))

    async def check_single_site(self,
                                client: httpx.AsyncClient,
                                site: dict,
                                username: str,
                                extract_profile: bool = False) -> SiteCheckOutcome:
        """Check username on a single site (supports GET, JSON POST, and form POST)."""
        url, method, kwargs = self._build_request(site, username)
        domain = urlparse(url).netloc

        if site.get("name") == "Mixi" and not username.isdigit():
            return SiteCheckOutcome(result=SiteResult(
                site_name=site["name"], category=site.get("cat", "unknown"), url=url,
                status=CheckStatus.NOT_FOUND, error_message="Mixi check requires a numeric community id"))

        async with self.semaphore, self._host_slots[domain]:
            start_time = time.time()
            wait_time = await self.rate_limiter.wait_if_needed(domain)
            if wait_time > 0:
                logger.debug("Rate limited for %s, waited %.2fs", domain, wait_time)
            try:
                # The whole request, redirects included, within timeout_seconds
                response = await asyncio.wait_for(client.request(method, url, **kwargs), self.timeout_seconds)
            except (asyncio.TimeoutError, httpx.TimeoutException):
                return self._error(site, url, "Timeout", start_time)
            except httpx.HTTPError as e:
                return self._error(site, url, f"Client error: {e}", start_time)
            except Exception as e:
                return self._error(site, url, str(e), start_time)
            return self._outcome(site, username, url, response, time.time() - start_time, extract_profile)

    async def check_site_with_retry(self,
                                   client: httpx.AsyncClient,
                                   site: dict,
                                   username: str,
                                   extract_profile: bool = False) -> SiteCheckOutcome:
        """Check site with retry logic and exponential backoff"""
        last_result = None

        for attempt in range(max(1, self.max_retries)):
            outcome = await self.check_single_site(client, site, username, extract_profile)
            result = outcome.result
            if result.status in [CheckStatus.FOUND, CheckStatus.NOT_FOUND]:
                return outcome

            last_result = outcome

            # Only retry on timeout or rate limit errors
            if result.error_message and any(x in result.error_message.lower()
                                           for x in ['timeout', 'rate limit', 'too many']):
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(0.2 * (2 ** attempt))
            else:
                break

        return last_result

    async def extract_profile_data(self, text: str, url: str) -> Optional[dict]:
        """Extract profile data without blocking the event loop."""
        profile_data = None

        if extract:
            try:
                profile_data = await asyncio.to_thread(extract, text)
            except Exception as e:
                logger.debug(f"socid_extractor failed for {url}: {e}")

        if not profile_data:
            parsed_json = self._try_parse_json(text)
            if parsed_json:
                profile_data = parsed_json

        return profile_data

    DDG_URL = "https://duckduckgo.com/html/?q={query}"

    async def stream_duckduckgo_search(self,
                                      client: httpx.AsyncClient,
                                      username: str,
                                      queue_event):
        """Stream DuckDuckGo results"""
        # Notify start
        await queue_event(StreamEvent(
            event_type=EventType.DUCKDUCKGO_STARTED,
            data={"message": "Starting DuckDuckGo search"}
        ))

        query = quote(f'"{username}"')
        url = self.DDG_URL.format(query=query)
        headers = {
            "User-Agent": self.get_random_user_agent(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        }

        try:
            response = await client.get(url, headers=headers)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, "html.parser")
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

                            # Stream each result
                            await queue_event(StreamEvent(
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

    @staticmethod
    def _select_sites(sites: List[dict], categories, only_sites, priority_sites) -> List[dict]:
        if categories:
            categories_set = set(categories)
            sites = [s for s in sites if s.get("cat") in categories_set]
        # Re-check just these (sites that errored in an earlier run)
        if only_sites:
            wanted = set(only_sites)
            sites = [s for s in sites if s.get("name") in wanted]
        if priority_sites:
            priority_set = set(priority_sites)
            sites = ([s for s in sites if s.get("name") in priority_set]
                     + [s for s in sites if s.get("name") not in priority_set])
        return sites

    @staticmethod
    def _event_priority(event: StreamEvent) -> int:
        """Found sites and profiles go out before the high-volume "checking" events."""
        if event.event_type == EventType.PROFILE_EXTRACTED:
            return 0
        if event.event_type == EventType.SITE_RESULT:
            return 1 if event.data.get("status") == CheckStatus.FOUND.value else 2
        if event.event_type in [EventType.DUCKDUCKGO_RESULT, EventType.DUCKDUCKGO_STARTED]:
            return 3
        return 4

    @staticmethod
    def _count_result(event: StreamEvent, stats: dict, total: int) -> None:
        """Add a site result to the totals and attach the progress to the event."""
        if event.event_type != EventType.SITE_RESULT:
            return
        stats["checked"] += 1
        status = event.data["status"]
        key = "found" if status == CheckStatus.FOUND.value else "not_found" if status == CheckStatus.NOT_FOUND.value else "errors"
        stats[key] += 1
        event.data["progress"] = {
            "checked": stats["checked"], "total": total, "found": stats["found"],
            "not_found": stats["not_found"], "errors": stats["errors"],
            "percentage": round((stats["checked"] / total) * 100, 2),
        }

    async def _process_site(self, client: httpx.AsyncClient, site: dict, username: str,
                            extract_profile: bool, queue_event) -> None:
        """Check one site and queue its events (checking, result, extracted profile)."""
        await queue_event(StreamEvent(
            event_type=EventType.SITE_CHECKING,
            data={"site_name": site["name"], "category": site.get("cat", "unknown"),
                  "url": site["uri_check"].replace(ACCOUNT, username)}))
        outcome = await self.check_site_with_retry(client, site, username, extract_profile)
        result = outcome.result
        await queue_event(StreamEvent(event_type=EventType.SITE_RESULT, data=result.to_dict()))

        if extract_profile and result.status == CheckStatus.FOUND and outcome.response_text:
            profile_data = await self.extract_profile_data(outcome.response_text, result.url)
            if profile_data:
                result.profile_data = profile_data
                await queue_event(StreamEvent(
                    event_type=EventType.PROFILE_EXTRACTED,
                    data={"site_name": result.site_name, "category": result.category, "url": result.url,
                          "profile_data": profile_data, "checked_at": result.checked_at}))

    async def stream_search(self,
                           username: str,
                           include_duckduckgo: bool = False,
                           extract_profile: bool = False,
                           categories: Optional[List[str]] = None,
                           priority_sites: Optional[List[str]] = None,
                           only_sites: Optional[List[str]] = None) -> AsyncGenerator[StreamEvent, None]:
        """Stream search results as they become available."""
        search_id = str(uuid.uuid4())
        start_time = time.time()
        metadata = await asyncio.to_thread(self.get_metadata)
        sites = self._select_sites(metadata.get("sites", []), categories, only_sites, priority_sites)

        yield StreamEvent(
            event_type=EventType.SEARCH_STARTED,
            data={"search_id": search_id, "username": username, "total_sites": len(sites),
                  "categories": categories, "include_duckduckgo": include_duckduckgo,
                  "extract_profile": extract_profile})

        stats = {"checked": 0, "found": 0, "not_found": 0, "errors": 0}
        result_queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        sequence = 0

        async def queue_event(event: StreamEvent):
            nonlocal sequence
            sequence += 1
            await result_queue.put((self._event_priority(event), sequence, event))

        limits = httpx.Limits(max_connections=self.max_concurrent_requests,
                              max_keepalive_connections=self.max_concurrent_requests)
        async with httpx.AsyncClient(timeout=self.timeout, limits=limits, verify=False,
                                     follow_redirects=True, trust_env=True) as client:
            tasks = [asyncio.create_task(self._process_site(client, site, username, extract_profile, queue_event))
                     for site in sites]
            if include_duckduckgo:
                tasks.append(asyncio.create_task(self.stream_duckduckgo_search(client, username, queue_event)))

            while any(not task.done() for task in tasks) or not result_queue.empty():
                try:
                    _, _, event = await asyncio.wait_for(result_queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                self._count_result(event, stats, len(sites))
                yield event
                if event.event_type == EventType.DUCKDUCKGO_RESULT and self.stream_delay > 0:
                    await asyncio.sleep(self.stream_delay)

            await asyncio.gather(*tasks, return_exceptions=True)
            while not result_queue.empty():
                _, _, event = await result_queue.get()
                self._count_result(event, stats, len(sites))
                yield event
                if event.event_type == EventType.DUCKDUCKGO_RESULT and self.stream_delay > 0:
                    await asyncio.sleep(self.stream_delay)

        yield StreamEvent(
            event_type=EventType.SEARCH_COMPLETED,
            data={"search_id": search_id, "username": username,
                  "total_found": stats["found"], "total_not_found": stats["not_found"],
                  "total_errors": stats["errors"], "total_checked": stats["checked"],
                  "search_time_seconds": round(time.time() - start_time, 2),
                  "success_rate": round((stats["found"] / stats["checked"]) * 100, 2) if stats["checked"] > 0 else 0})
