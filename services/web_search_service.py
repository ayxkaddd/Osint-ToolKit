"""
OSINT Search Service
Production-ready service for performing OSINT searches via SerpAPI
"""

from dataclasses import dataclass
from typing import Any, Optional
from enum import Enum
import asyncio
import httpx
from abc import ABC, abstractmethod
import re
import logging

logger = logging.getLogger(__name__)


class SearchEngine(Enum):
    """Supported search engines"""
    GOOGLE = "google"
    YANDEX = "yandex"


class InputType(Enum):
    """Supported input data types"""
    USERNAME = "username"
    FULL_NAME = "full_name"
    PHONE = "phone"
    EMAIL = "email"
    CUSTOM = "custom"  # For user-provided dorks


@dataclass
class SearchResult:
    """Normalized search result structure"""
    dork: str
    engine: str
    title: str
    url: str
    snippet: str
    position: int
    raw_data: Optional[dict[str, Any]] = None


class DorkGenerator(ABC):
    """Base class for dork generators"""

    @abstractmethod
    def generate(self, value: str, engine: SearchEngine) -> list[str]:
        """Generate search dorks for given value and engine"""
        pass


class UsernameDorkGenerator(DorkGenerator):
    """Generate dorks for username searches"""

    def generate(self, value: str, engine: SearchEngine) -> list[str]:
        username = value.strip()

        if engine == SearchEngine.GOOGLE:
            return [
                f'"{username}"',
                f'"{username}" site:github.com',
                f'"{username}" site:linkedin.com',
                f'"{username}" site:twitter.com OR site:x.com',
                f'"{username}" site:instagram.com',
                f'"{username}" site:facebook.com',
                f'inurl:"{username}" site:reddit.com',
                f'"{username}" (site:pastebin.com OR site:ghostbin.com)',
                f'"{username}" site:stackoverflow.com',
                f'"{username}" site:medium.com',
                f'intitle:"{username}" filetype:pdf',
                f'"{username}" inurl:profile',
                f'"{username}" "contact" OR "about" OR "bio"',
            ]
        else:  # Yandex
            return [
                f'"{username}"',
                f'"{username}" site:github.com',
                f'"{username}" site:linkedin.com',
                f'"{username}" site:vk.com',
                f'"{username}" site:ok.ru',
                f'"{username}" site:habr.com',
                f'url:"{username}" site:reddit.com',
                f'"{username}" site:instagram.com',
                f'"{username}" (site:pastebin.com | site:ghostbin.com)',
                f'"{username}" url:profile',
            ]


class FullNameDorkGenerator(DorkGenerator):
    """Generate dorks for full name searches"""

    def generate(self, value: str, engine: SearchEngine) -> list[str]:
        full_name = value.strip()

        if engine == SearchEngine.GOOGLE:
            return [
                f'"{full_name}"',
                f'"{full_name}" site:linkedin.com',
                f'"{full_name}" site:facebook.com',
                f'"{full_name}" (resume OR CV) filetype:pdf',
                f'"{full_name}" intitle:"about" OR intitle:"profile"',
                f'"{full_name}" site:twitter.com OR site:x.com',
                f'"{full_name}" "email" OR "contact"',
                f'"{full_name}" site:*.edu',
                f'"{full_name}" (site:crunchbase.com OR site:bloomberg.com)',
                f'"{full_name}" inurl:directory',
                f'"{full_name}" "phone" OR "mobile" OR "cell"',
                f'"{full_name}" site:github.com',
            ]
        else:  # Yandex
            return [
                f'"{full_name}"',
                f'"{full_name}" site:linkedin.com',
                f'"{full_name}" site:vk.com',
                f'"{full_name}" (резюме | CV) mime:pdf',
                f'"{full_name}" title:"профиль"',
                f'"{full_name}" site:ok.ru',
                f'"{full_name}" "email" | "контакт"',
                f'"{full_name}" site:habr.com',
            ]


class PhoneDorkGenerator(DorkGenerator):
    """Generate dorks for phone number searches"""

    def _normalize_phone(self, phone: str) -> list[str]:
        """Generate different phone number formats"""
        try:
            from services.phone_service import search_formats
            formats = search_formats(phone) or []
            if formats:
                return formats[:4]
        except Exception:
            pass  # not parseable as an international number - fall back to digit patterns
        digits = re.sub(r'\D', '', phone)
        variants = [digits]

        if len(digits) >= 10:
            # Add formatted versions
            if len(digits) == 10:
                variants.append(f"({digits[:3]}) {digits[3:6]}-{digits[6:]}")
                variants.append(f"{digits[:3]}-{digits[3:6]}-{digits[6:]}")
            elif len(digits) == 11:
                variants.append(f"+{digits[0]} ({digits[1:4]}) {digits[4:7]}-{digits[7:]}")
                variants.append(f"+{digits}")

        return list(set(variants))

    def generate(self, value: str, engine: SearchEngine) -> list[str]:
        phone_variants = self._normalize_phone(value)
        dorks = []

        if engine == SearchEngine.GOOGLE:
            for variant in phone_variants:
                dorks.extend([
                    f'"{variant}"',
                    f'"{variant}" site:truecaller.com',
                    f'"{variant}" site:whitepages.com',
                    f'"{variant}" (site:facebook.com OR site:linkedin.com)',
                    f'"{variant}" "contact" OR "owner"',
                ])

            # Add general patterns
            dorks.append(f'{phone_variants[0]} inurl:contact')
            dorks.append(f'{phone_variants[0]} filetype:xlsx OR filetype:csv')

        else:  # Yandex
            for variant in phone_variants:
                dorks.extend([
                    f'"{variant}"',
                    f'"{variant}" site:vk.com',
                    f'"{variant}" site:avito.ru',
                    f'"{variant}" "контакт" | "владелец"',
                ])

        return dorks[:15]  # Limit to avoid too many queries


class EmailDorkGenerator(DorkGenerator):
    """Generate dorks for email address searches"""

    def generate(self, value: str, engine: SearchEngine) -> list[str]:
        email = value.strip()
        username = email.split('@')[0] if '@' in email else email
        domain = email.split('@')[1] if '@' in email else ""

        if engine == SearchEngine.GOOGLE:
            dorks = [
                f'"{email}"',
                f'"{email}" site:linkedin.com',
                f'"{email}" site:github.com',
                f'"{email}" (site:pastebin.com OR site:ghostbin.com)',
                f'"{email}" "password" OR "breach"',
                f'"{email}" site:twitter.com OR site:x.com',
                f'"{email}" filetype:pdf',
                f'"{email}" filetype:xlsx OR filetype:csv',
                f'inurl:"{username}"',
            ]

            if domain:
                dorks.extend([
                    f'"{username}" site:{domain}',
                    f'site:{domain} "contact" OR "team" OR "about"',
                ])

            return dorks

        else:  # Yandex
            dorks = [
                f'"{email}"',
                f'"{email}" site:vk.com',
                f'"{email}" site:habr.com',
                f'"{email}" (site:pastebin.com | site:ghostbin.com)',
                f'"{email}" mime:pdf',
            ]

            if domain:
                dorks.append(f'site:{domain} "контакт" | "команда"')

            return dorks


class CustomDorkGenerator(DorkGenerator):
    """Generator for custom user-provided dorks"""

    def generate(self, value: str, engine: SearchEngine) -> list[str]:
        """
        For custom dorks, value is already a dork string.
        Just return it as-is.
        """
        return [value.strip()]


class DorkGeneratorFactory:
    """Factory for creating appropriate dork generators"""

    _generators = {
        InputType.USERNAME: UsernameDorkGenerator(),
        InputType.FULL_NAME: FullNameDorkGenerator(),
        InputType.PHONE: PhoneDorkGenerator(),
        InputType.EMAIL: EmailDorkGenerator(),
        InputType.CUSTOM: CustomDorkGenerator(),
    }

    @classmethod
    def get_generator(cls, input_type: InputType) -> DorkGenerator:
        """Get appropriate dork generator for input type"""
        return cls._generators[input_type]


class SearchExecutor:
    """Executes searches via SerpAPI"""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://serpapi.com/search"

    async def search(
        self,
        dork: str,
        engine: SearchEngine,
        max_results: int = 10,
        client: Optional[httpx.AsyncClient] = None
    ) -> dict[str, Any]:
        """Execute a single search query"""

        params = {
            "api_key": self.api_key,
            "q": dork,
            "num": max_results,
        }

        if engine == SearchEngine.GOOGLE:
            params["engine"] = "google"
        else:
            params["engine"] = "yandex"

        own_client = client is None
        client = client or httpx.AsyncClient(timeout=60)
        try:
            response = await client.get(self.base_url, params=params)
            if response.status_code == 200:
                return response.json()
            logger.error("SerpAPI error %s: %s", response.status_code, response.text)
            raise Exception(f"SerpAPI error {response.status_code}: {response.text}")
        finally:
            if own_client:
                await client.aclose()

    async def search_multiple(
        self,
        dorks: list[str],
        engine: SearchEngine,
        max_results: int = 10,
        delay: float = 1.0
    ) -> list[dict[str, Any]]:
        """Execute multiple searches with rate limiting"""

        results = []
        async with httpx.AsyncClient(timeout=60) as client:
            for dork in dorks:
                try:
                    result = await self.search(dork, engine, max_results, client)
                    results.append({"dork": dork, "engine": engine.value, "data": result})
                    logger.info('Search completed for dork: %s...', dork[:50])
                    await asyncio.sleep(delay)  # Rate limiting
                except Exception as e:
                    logger.error("Search failed for dork '%s': %s", dork, str(e))
                    results.append({"dork": dork, "engine": engine.value, "error": str(e)})

        return results


class ResultNormalizer:
    """Normalizes search results to unified format"""

    @staticmethod
    def normalize(raw_results: list[dict[str, Any]]) -> list[SearchResult]:
        """Normalize raw SerpAPI results to SearchResult objects"""

        normalized = []

        for raw in raw_results:
            dork = raw.get("dork", "")
            engine = raw.get("engine", "")
            data = raw.get("data", {})

            if "error" in raw:
                continue

            # Extract organic results
            organic = data.get("organic_results", [])

            for idx, result in enumerate(organic, 1):
                normalized.append(SearchResult(
                    dork=dork,
                    engine=engine,
                    title=result.get("title", ""),
                    url=result.get("link", ""),
                    snippet=result.get("snippet", ""),
                    position=result.get("position", idx),
                    raw_data=result
                ))

        return normalized


class OSINTSearchService:
    """Main OSINT search service"""

    def __init__(self, api_key: str):
        self.executor = SearchExecutor(api_key)
        self.normalizer = ResultNormalizer()

    async def search(
        self,
        value: str,
        input_type: InputType,
        engines: list[SearchEngine],
        max_results_per_dork: int = 10,
        rate_limit_delay: float = 1.0
    ) -> dict[str, Any]:
        """
        Perform OSINT search

        Args:
            value: The input value to search for (or custom dork)
            input_type: Type of input (username, email, etc.)
            engines: List of search engines to use
            max_results_per_dork: Maximum results per dork query
            rate_limit_delay: Delay between requests in seconds

        Returns:
            Dictionary containing all search results and metadata
        """

        generator = DorkGeneratorFactory.get_generator(input_type)
        all_results = []

        for engine in engines:
            dorks = generator.generate(value, engine)
            logger.info('Generated %s dorks for %s on %s', len(dorks), input_type.value, engine.value)

            raw_results = await self.executor.search_multiple(
                dorks=dorks,
                engine=engine,
                max_results=max_results_per_dork,
                delay=rate_limit_delay
            )

            all_results.extend(raw_results)

        normalized_results = self.normalizer.normalize(all_results)

        # Deduplicate results by URL
        unique_results = {}
        for result in normalized_results:
            if result.url not in unique_results:
                unique_results[result.url] = result

        # Dorks that failed (quota exhausted, bad key, ...) - otherwise the user
        # only sees "0 results" with no reason
        errors = [{"dork": r.get("dork"), "engine": r.get("engine"), "error": r["error"]}
                  for r in all_results if r.get("error")]
        return {
            "errors": errors,
            "dorks_executed": len(all_results),
            "query": {
                "value": value,
                "type": input_type.value,
                "engines": [e.value for e in engines],
            },
            "total_results": len(unique_results),
            "results": [
                {
                    "dork": r.dork,
                    "engine": r.engine,
                    "title": r.title,
                    "url": r.url,
                    "snippet": r.snippet,
                    "position": r.position,
                }
                for r in unique_results.values()
            ]
        }

    async def search_custom_dorks(
        self,
        dorks: list[str],
        engines: list[SearchEngine],
        max_results_per_dork: int = 10,
        rate_limit_delay: float = 1.0
    ) -> dict[str, Any]:
        """
        Perform search with user-provided custom dorks

        Args:
            dorks: List of custom dork queries
            engines: List of search engines to use
            max_results_per_dork: Maximum results per dork query
            rate_limit_delay: Delay between requests in seconds

        Returns:
            Dictionary containing all search results and metadata
        """

        all_results = []

        for engine in engines:
            logger.info('Searching %s custom dorks on %s', len(dorks), engine.value)

            raw_results = await self.executor.search_multiple(
                dorks=dorks,
                engine=engine,
                max_results=max_results_per_dork,
                delay=rate_limit_delay
            )

            all_results.extend(raw_results)

        normalized_results = self.normalizer.normalize(all_results)

        # Deduplicate results by URL
        unique_results = {}
        for result in normalized_results:
            if result.url not in unique_results:
                unique_results[result.url] = result

        # Dorks that failed (quota exhausted, bad key, ...) - otherwise the user
        # only sees "0 results" with no reason
        errors = [{"dork": r.get("dork"), "engine": r.get("engine"), "error": r["error"]}
                  for r in all_results if r.get("error")]
        return {
            "errors": errors,
            "dorks_executed": len(all_results),
            "query": {
                "custom_dorks": dorks,
                "type": "custom",
                "engines": [e.value for e in engines],
            },
            "total_results": len(unique_results),
            "results": [
                {
                    "dork": r.dork,
                    "engine": r.engine,
                    "title": r.title,
                    "url": r.url,
                    "snippet": r.snippet,
                    "position": r.position,
                }
                for r in unique_results.values()
            ]
        }

    def get_available_dorks(
        self,
        value: str,
        input_type: InputType,
        engines: list[SearchEngine]
    ) -> dict[str, list[str]]:
        """
        Get available dorks without executing searches

        Args:
            value: The input value
            input_type: Type of input
            engines: List of search engines

        Returns:
            Dictionary mapping engine names to dork lists
        """

        generator = DorkGeneratorFactory.get_generator(input_type)
        dorks_by_engine = {}

        for engine in engines:
            dorks = generator.generate(value, engine)
            dorks_by_engine[engine.value] = dorks

        return dorks_by_engine


# Export public API
__all__ = [
    'OSINTSearchService',
    'SearchEngine',
    'InputType',
    'SearchResult',
]