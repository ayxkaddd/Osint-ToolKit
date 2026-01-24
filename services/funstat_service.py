import json
import re
import httpx
from typing import List, Optional, Dict, Any
from fastapi import HTTPException
import logging
from models.funstat_models import (
    TechInfo,
    ResolvedUser,
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


class FunstatService:
    def __init__(self, api_key: str, base_url: str = "https://funstat.info"):
        self.api_key = api_key
        self.base_url = base_url
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        json_data: Optional[Dict] = None
    ) -> Dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                url = f"{self.base_url}{endpoint}"

                response = await client.request(
                    method=method,
                    url=url,
                    headers=self.headers,
                    params=params,
                    json=json_data
                )

                response.raise_for_status()
                return response.json()

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


    async def get_user_basic_info_by_id(self, user_ids: List[int]) -> List[ResolvedUser]:
        """Get user info by telegram ID. Cost 0.10 per success found user info"""
        response = await self._make_request(
            "GET",
            "/api/v1/users/basic_info_by_id",
            params={"id": user_ids}
        )
        return [ResolvedUser(**user) for user in response.get("data", [])]

    async def resolve_username(self, usernames: List[str]) -> List[ResolvedUser]:
        response = await self._make_request(
            "GET",
            "/api/v1/users/resolve_username",
            params={"name": usernames}
        )
        return [ResolvedUser(**user) for user in response.get("data", [])]

    async def get_user_stats_min(self, user_id: int) -> UserStatsMin:
        response = await self._make_request(
            "GET",
            f"/api/v1/users/{user_id}/stats_min"
        )
        return UserStatsMin(**response)

    async def get_user_stats(self, user_id: int) -> UserStats:
        response = await self._make_request(
            "GET",
            f"/api/v1/users/{user_id}/stats"
        )
        return UserStats(**response.get("data", {}))

    async def get_user_groups(self, user_id: int) -> List[UsrChatInfo]:
        response = await self._make_request(
            "GET",
            f"/api/v1/users/{user_id}/groups"
        )
        return [UsrChatInfo(**group) for group in response.get("data", [])]

    async def get_user_groups_count(self, user_id: int, only_msg: bool = True) -> int:
        response = await self._make_request(
            "GET",
            f"/api/v1/users/{user_id}/groups_count",
            params={"onlyMsg": only_msg}
        )
        return response

    async def get_user_messages_count(self, user_id: int) -> int:
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
    ) -> Dict[str, Any]:
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
    ) -> Dict[str, Any]:
        all_messages = []
        page = 1
        page_size = 100
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

            if max_messages and total_fetched >= max_messages:
                all_messages = all_messages[:max_messages]
                break

            if page >= paging.total_pages:
                break

            page += 1

        message_analyzer = MessageAnalyzer()
        message_analysis_result = message_analyzer.analyze_conversation(
            messages=[msg.model_dump(by_alias=True) if hasattr(msg, 'model_dump') else msg.dict(by_alias=True) for msg in all_messages],
            include_message_analysis=True
        )

        return {
            "messages": all_messages,
            "messages_analysis": message_analysis_result,
            "total": len(all_messages),
            "tech": tech
        }

    async def get_user_names_history(self, user_id: int) -> List[UsrChatInfo]:
        response = await self._make_request(
            "GET",
            f"/api/v1/users/{user_id}/names"
        )
        return [UsrChatInfo(**item) for item in response.get("data", [])]

    async def get_user_usernames_history(self, user_id: int) -> List[UsrChatInfo]:
        response = await self._make_request(
            "GET",
            f"/api/v1/users/{user_id}/usernames"
        )
        return [UsrChatInfo(**item) for item in response.get("data", [])]

    async def get_user_common_groups_stat(self, user_id: int) -> List[UCommonGroupInfo]:
        response = await self._make_request(
            "GET",
            f"/api/v1/users/{user_id}/common_groups_stat"
        )
        return [UCommonGroupInfo(**item) for item in response.get("data", [])]

    async def get_user_reputation(self, user_id: int) -> Dict[str, Any]:
        response = await self._make_request(
            "GET",
            "/api/v1/users/reputation",
            params={"id": user_id}
        )
        return response

    async def get_user_stickers(self, user_id: int) -> List[StickerInfo]:
        response = await self._make_request(
            "GET",
            f"/api/v1/users/{user_id}/stickers"
        )
        return [StickerInfo(**item) for item in response.get("data", [])]

    async def search_username_usage(self, username: str) -> UsernameUsageModel:
        response = await self._make_request(
            "GET",
            "/api/v1/users/username_usage",
            params={"username": username}
        )
        return UsernameUsageModel(**response.get("data", {}))


    async def get_group_info(self, group_id: int) -> Dict[str, Any]:
        response = await self._make_request(
            "GET",
            f"/api/v1/groups/{group_id}"
        )
        return response

    async def get_group_members(self, group_id: int) -> List[GroupMember]:
        response = await self._make_request(
            "GET",
            f"/api/v1/groups/{group_id}/members"
        )
        return [GroupMember(**member) for member in response.get("data", [])]

    async def get_common_groups(self, user_ids: List[int]) -> List[ChatInfoExt]:
        response = await self._make_request(
            "GET",
            "/api/v1/groups/common_groups",
            params={"id": user_ids}
        )
        return [ChatInfoExt(**group) for group in response.get("data", [])]


    async def search_text(
        self,
        search_input: str,
        page: int = 1,
        page_size: int = 20
    ) -> Dict[str, Any]:
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


    async def get_random_bot(self) -> Dict[str, Any]:
        response = await self._make_request(
            "GET",
            "/api/v1/bot/random"
        )
        return response

class MessageAnalyzer:
    PATTERNS = {
        'url': re.compile(
            r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
        ),
        'domain': re.compile(
            r'(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}'
        ),

        'email': re.compile(
            r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        ),

        'phone': re.compile(
            r'(?:\+?\d{1,3}[\s.-]?)?\(?\d{2,4}\)?[\s.-]?\d{2,4}[\s.-]?\d{2,4}[\s.-]?\d{2,4}(?![\d-])'
        ),

        'btc_wallet': re.compile(
            r'\b[13][a-km-zA-HJ-NP-Z1-9]{25,34}\b|bc1[a-z0-9]{39,59}\b'
        ),
        'eth_wallet': re.compile(
            r'\b0x[a-fA-F0-9]{40}\b'
        ),
        'usdt_trc20': re.compile(
            r'\bT[A-Za-z1-9]{33}\b'
        ),

        'card_number': re.compile(
            r'\b(?:\d{4}[-\s]?){3}\d{4}\b'
        ),

        'age_pattern': re.compile(
            r'\b(?:(?:1[89]|[2-6][0-9]|70)\s*(?:years?|y\.?o\.?|лет|год|роки|years old|y\.o\.))|(?:(?:years?|y\.?o\.?|лет|год|роки|years old|y\.o\.)\s*(?:1[89]|[2-6][0-9]|70))\b',
            re.IGNORECASE
        ),

        'age_number': re.compile(
            r'\b(1[89]|[2-6][0-9]|70)\b'
        ),

        'telegram_username': re.compile(
            r'@[a-zA-Z0-9_]{5,32}\b'
        ),

        'ipv4': re.compile(
            r'\b(?:\d{1,3}\.){3}\d{1,3}\b'
        ),

        'date': re.compile(
            r'\b\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}\b'
        ),

        'id_number': re.compile(
            r'\b[A-Z]{2}\d{6,10}\b'
        ),

        'iban': re.compile(
            r'\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b'
        ),
    }

    SUSPICIOUS_KEYWORDS = {
        'financial': [
            'transfer', 'payment', 'wire', 'bank', 'card', 'cvv', 'pin',
            'переказ', 'оплата', 'карта', 'банк', 'перевод'
        ],
        'personal_data': [
            'passport', 'ssn', 'license', 'id card', 'birth certificate',
            'паспорт', 'удостоверение', 'свідоцтво'
        ],
        'crypto': [
            'wallet', 'bitcoin', 'ethereum', 'usdt', 'crypto', 'btc', 'eth',
            'гаманець', 'крипта', 'кошелек'
        ],
        'scam_indicators': [
            'urgent', 'act now', 'limited time', 'verify', 'suspend',
            'терміново', 'обмежений час', 'підтвердіть'
        ]
    }

    def __init__(self):
        pass

    def _validate_phone(self, phone: str) -> bool:
        digits_only = re.sub(r'\D', '', phone)

        if len(digits_only) < 10:
            return False

        if len(digits_only) > 15:
            return False

        if len(digits_only) == 4:
            return False

        if re.match(r'^\d{1,4}-\d{1,4}$', phone.strip()):
            return False

        if re.match(r'^\d{4,6}$', phone.strip()):
            return False

        if not re.match(r'^[\+\d]', phone.strip()):
            return False

        return True

    def _validate_card(self, card: str) -> bool:
        digits_only = re.sub(r'[\s-]', '', card)

        if len(digits_only) != 16:
            return False

        if len(set(digits_only)) == 1:
            return False

        return True

    def _validate_age(self, number: str, text: str) -> bool:
        num = int(number)

        age_keywords = [
            'years', 'year', 'old', 'age', 'aged', 'born', 'birth',
            'лет', 'год', 'возраст', 'роки', 'y.o', 'yo', 'yrs',
            'teenage', 'teen', 'adult', 'minor', 'senior', 'elderly',
            'kid', 'baby', 'child', 'young', 'older', 'younger'
        ]

        non_age_keywords = [
            'rub', 'руб', 'dollar', 'день', 'days', 'день', 'price', 'cost',
            'кк', 'k', 'million', 'млн', 'thousand', 'тыс', 'coins', 'монет',
            'cash', 'money', 'стоит', 'costs', 'за', 'штук', 'pieces',
            'магазин', 'shop', 'продам', 'sell', 'купить', 'buy',
            'актив', 'activation', 'вывод', 'withdraw', 'баланс', 'balance',
            'финка', 'финансы', 'finance', 'онлаин', 'online', 'кк'
        ]

        text_lower = text.lower()

        has_age_keyword = any(keyword in text_lower for keyword in age_keywords)

        has_non_age_keyword = any(keyword in text_lower for keyword in non_age_keywords)

        if has_non_age_keyword:
            return False

        if has_age_keyword:
            return True

        number_pattern = re.compile(rf'\b{re.escape(number)}\b')
        match = number_pattern.search(text_lower)

        if match:
            start = max(0, match.start() - 50)
            end = min(len(text_lower), match.end() + 50)
            context = text_lower[start:end]

            non_age_phrases = [
                'дней', 'дни', 'день', 'days', 'day',
                'кк', 'монет', 'coins', 'coins',
                'штук', 'pieces', 'штуки',
                'за ', 'for ',
                'магазин', 'shop', 'цена', 'price',
                'финка', 'финансы',
                'онлаин', 'online',
                'серверов', 'servers',
                'людей', 'people',
                'дом', 'дома', 'house', 'houses',
                'земли', 'земля',
            ]

            if any(phrase in context for phrase in non_age_phrases):
                return False

            age_phrases = [
                'ему', 'им', 'мне', 'тебе',
                'человек', 'person',
                'девушка', 'парень', 'girl', 'boy',
                'ребенок', 'child', 'взрослый', 'adult',
                'молодой', 'старый', 'young', 'old',
            ]

            if any(phrase in context for phrase in age_phrases):
                return True

        return False

    def analyze_message(self, text: str, extended: bool = True) -> Dict:
        if not text:
            return {
                "has_sensitive_data": False,
                "is_empty": True
            }

        extracted_data = {}

        for data_type, pattern in self.PATTERNS.items():
            matches = pattern.findall(text)
            if matches:
                if matches and isinstance(matches[0], tuple):
                    matches = [m[0] if isinstance(m, tuple) else m for m in matches]

                matches = [str(m).strip() for m in matches if m]

                if data_type == 'phone':
                    matches = [m for m in matches if self._validate_phone(m)]
                elif data_type == 'card_number':
                    matches = [m for m in matches if self._validate_card(m)]
                elif data_type == 'age_number':
                    matches = [m for m in matches if self._validate_age(m, text)]

                matches = list(set(matches))

                if matches:
                    extracted_data[data_type] = matches

        analysis = {
            "has_sensitive_data": bool(extracted_data),
        }

        if extracted_data:
            analysis["extracted_data"] = extracted_data
            analysis["data_types_found"] = list(extracted_data.keys())
            analysis["risk_score"] = self._calculate_risk_score(extracted_data)

            if analysis["risk_score"] >= 80:
                analysis["risk_level"] = "critical"
            elif analysis["risk_score"] >= 50:
                analysis["risk_level"] = "high"
            elif analysis["risk_score"] >= 20:
                analysis["risk_level"] = "medium"
            else:
                analysis["risk_level"] = "low"

            if extended:
                keywords = self._analyze_keywords(text)
                if keywords:
                    analysis["keywords"] = keywords

                context = self._analyze_context(text, extracted_data)
                if any(context.values()):
                    analysis["context"] = context

                warnings = self._generate_warnings(analysis)
                if warnings:
                    analysis["warnings"] = warnings

        return analysis
    def _calculate_risk_score(self, extracted_data: Dict) -> int:
        score = 0

        weights = {
            'card_number': 25,
            'btc_wallet': 20,
            'eth_wallet': 20,
            'usdt_trc20': 20,
            'email': 10,
            'phone': 15,
            'iban': 25,
            'id_number': 20,
            'ipv4': 10,
            'url': 5,
            'age_pattern': 15,
            'coordinates': 10,
            'telegram_username': 5,
            'date': 3,
            'domain': 3,
        }

        for data_type, items in extracted_data.items():
            if items and data_type in weights:
                score += weights[data_type] * min(len(items), 3)

        return min(score, 100)

    def _analyze_keywords(self, text: str) -> Dict[str, List[str]]:
        found_keywords = {}
        text_lower = text.lower()

        for category, keywords in self.SUSPICIOUS_KEYWORDS.items():
            found = [kw for kw in keywords if kw.lower() in text_lower]
            if found:
                found_keywords[category] = found

        return found_keywords

    def _analyze_context(self, text: str, extracted_data: Dict) -> Dict:
        """Analyze context and patterns"""
        context = {
            "has_multiple_data_types": len(extracted_data) > 2,
            "has_financial_indicators": False,
            "has_personal_data_indicators": False,
            "message_characteristics": []
        }

        sensitive_types = {'card_number', 'btc_wallet', 'eth_wallet', 'usdt_trc20',
                          'iban', 'phone', 'email', 'id_number'}
        found_sensitive = set(extracted_data.keys()) & sensitive_types

        if len(found_sensitive) >= 2:
            context["has_multiple_data_types"] = True
            context["message_characteristics"].append("multiple_sensitive_data")

        if any(k in extracted_data for k in ['card_number', 'iban', 'btc_wallet', 'eth_wallet']):
            context["has_financial_indicators"] = True
            context["message_characteristics"].append("financial_data")

        if any(k in extracted_data for k in ['phone', 'email', 'id_number', 'age_pattern']):
            context["has_personal_data_indicators"] = True
            context["message_characteristics"].append("personal_data")

        if len(text) < 200 and len(extracted_data) >= 3:
            context["message_characteristics"].append("high_data_density")

        return context

    def _generate_warnings(self, analysis: Dict) -> List[str]:
        """Generate human-readable warnings"""
        warnings = []

        extracted = analysis.get("extracted_data", {})

        if 'card_number' in extracted:
            warnings.append("⚠️ Bank card number detected")

        if any(k in extracted for k in ['btc_wallet', 'eth_wallet', 'usdt_trc20']):
            warnings.append("⚠️ Cryptocurrency wallet address detected")

        if 'email' in extracted:
            warnings.append("📧 Email address detected")

        if 'phone' in extracted:
            warnings.append("📱 Phone number detected")

        if 'iban' in extracted:
            warnings.append("🏦 IBAN detected")

        if 'id_number' in extracted:
            warnings.append("🆔 ID/Passport number pattern detected")

        if analysis.get("context", {}).get("has_multiple_data_types"):
            warnings.append("🚨 Multiple sensitive data types in one message")

        keywords = analysis.get("keywords", {})
        if keywords.get("scam_indicators"):
            warnings.append("⚠️ Scam indicators detected")

        if analysis.get("risk_score", 0) >= 50:
            warnings.append(f"🔴 High risk message (score: {analysis['risk_score']})")

        return warnings

    def analyze_conversation(
        self,
        messages: List[Dict],
        include_message_analysis: bool = True
    ) -> Dict:
        total_messages = len(messages)
        messages_with_sensitive_data = 0

        aggregated_data = {}
        risk_summary = {
            "critical": 0,
            "high": 0,
            "medium": 0,
            "low": 0
        }
        data_type_frequency = {}

        analyzed_messages = []

        all_extracted_data = {}

        for msg in messages:
            text = msg.get("text", "")
            if not text:
                continue

            msg_analysis = self.analyze_message(text, extended=True)

            if not msg_analysis.get("has_sensitive_data"):
                continue

            messages_with_sensitive_data += 1

            message_obj = {
                "has_sensitive_data": True,
                "extracted_data": msg_analysis.get("extracted_data", {}),
                "data_types_found": msg_analysis.get("data_types_found", []),
                "risk_score": msg_analysis.get("risk_score", 0),
                "risk_level": msg_analysis.get("risk_level", "low"),
                "message_id": msg.get("messageId"),
                "date": msg.get("date"),
                "text": text,
            }

            if "group" in msg:
                message_obj["group"] = msg["group"]

            analyzed_messages.append(message_obj)

            risk_level = msg_analysis.get("risk_level", "low")
            risk_summary[risk_level] += 1

            extracted = msg_analysis.get("extracted_data", {})
            for data_type, items in extracted.items():
                if data_type not in all_extracted_data:
                    all_extracted_data[data_type] = set()
                all_extracted_data[data_type].update(items)

                data_type_frequency[data_type] = data_type_frequency.get(data_type, 0) + 1

        if messages_with_sensitive_data == 0:
            return {
                "has_sensitive_data": False,
                "total_messages": total_messages,
                "messages_with_sensitive_data": 0
            }

        aggregated_data_list = {k: list(v) for k, v in all_extracted_data.items()}

        conversation_analysis = {
            "has_sensitive_data": True,
            "total_messages": total_messages,
            "messages_with_sensitive_data": messages_with_sensitive_data,
            "aggregated_data": aggregated_data_list,
            "risk_summary": risk_summary,
            "data_type_frequency": data_type_frequency,
        }

        if include_message_analysis and analyzed_messages:
            conversation_analysis["message_analyses"] = analyzed_messages

        return conversation_analysis

    def _calculate_conversation_risk(self, conv_analysis: Dict) -> int:
        """Calculate overall conversation risk score"""
        total = conv_analysis["total_messages"]
        if total == 0:
            return 0

        sensitive_ratio = conv_analysis["messages_with_sensitive_data"] / total

        risk_summary = conv_analysis["risk_summary"]
        weighted_score = (
            risk_summary["critical"] * 100 +
            risk_summary["high"] * 60 +
            risk_summary["medium"] * 30 +
            risk_summary["low"] * 10
        ) / max(total, 1)

        data_type_count = len(conv_analysis["aggregated_data"])
        diversity_factor = min(data_type_count * 5, 30)

        final_score = min(
            int(sensitive_ratio * 50 + weighted_score * 0.4 + diversity_factor),
            100
        )

        return final_score

    def analyze_user_pattern(
        self,
        user_messages: List[Dict],
        user_id: int
    ) -> Dict:
        conv_analysis = self.analyze_conversation(
            user_messages,
            include_message_analysis=False
        )

        if not conv_analysis.get("has_sensitive_data"):
            return {
                "user_id": user_id,
                "has_sensitive_data": False,
                "total_messages_analyzed": len(user_messages),
                "messages_with_sensitive_data": 0
            }

        sensitive_count = conv_analysis["messages_with_sensitive_data"]
        total_count = conv_analysis["total_messages"]
        frequency = sensitive_count / total_count if total_count > 0 else 0

        user_analysis = {
            "user_id": user_id,
            "has_sensitive_data": True,
            "total_messages_analyzed": total_count,
            "sensitive_data_sharing": {
                "frequency": round(frequency, 3),
                "data_types": list(conv_analysis["aggregated_data"].keys()),
                "total_instances": sensitive_count
            },
            "risk_assessment": "low",
            "conversation_summary": conv_analysis
        }

        behavior_flags = []

        if frequency > 0.3:
            behavior_flags.append("high_sensitive_data_frequency")

        if len(conv_analysis["aggregated_data"]) >= 5:
            behavior_flags.append("diverse_sensitive_data_types")

        if conv_analysis["risk_summary"]["critical"] > 0:
            behavior_flags.append("critical_risk_messages")

        if behavior_flags:
            user_analysis["behavior_flags"] = behavior_flags

        overall_risk = conv_analysis.get("overall_risk_score", 0)
        if overall_risk >= 70:
            user_analysis["risk_assessment"] = "critical"
        elif overall_risk >= 50:
            user_analysis["risk_assessment"] = "high"
        elif overall_risk >= 25:
            user_analysis["risk_assessment"] = "medium"

        return user_analysis
