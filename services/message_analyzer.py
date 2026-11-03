"""Finds identifiers and risky content in Telegram messages (Funstat "all messages").

Regex-based and offline: emails, phones, crypto wallets, card numbers, usernames,
links, ages and more, with validation, risk scores and per-conversation summaries.
"""
import re
from functools import lru_cache
from typing import Dict, List


@lru_cache(maxsize=None)
def _rx(pattern: str, flags: int = 0) -> "re.Pattern":
    """Compiled regex for a fixed pattern. The analyzer runs dozens of these per message,
    so this skips the lookup in re.search and re.match. Not for patterns built from text."""
    return re.compile(pattern, flags)


class MessageAnalyzer:
    """
    Advanced Telegram message analyzer for sensitive data and patterns.

    Features:
    - Context-aware data extraction (age, phone, cards, crypto)
    - Telegram-specific pattern detection (TON wallets, deep links, NFTs)
    - Scam pattern recognition
    - Intent classification
    - False positive reduction through validation
    - Multilingual support (EN/RU/UK)
    """

    # Enhanced regex patterns for various data types
    PATTERNS = {
        # URLs and links
        'url': re.compile(
            r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+',
            re.UNICODE
        ),
        'domain': re.compile(
            r'(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}',
            re.UNICODE
        ),

        # Email addresses
        'email': re.compile(
            r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
            re.UNICODE
        ),

        # Phone numbers - strict pattern to avoid dates
        'phone': re.compile(
            r'''(?x)
            (?<!\d)  # not preceded by digit
            (?:
                # International format with + (most reliable indicator)
                \+\d{7,15}
                |
                # International with spaces/dashes after +
                \+\d{1,3}[\s\-]\d{2,4}[\s\-]\d{2,4}[\s\-]?\d{2,4}
                |
                # Parentheses format (clear phone indicator)
                \(\d{3}\)[\s\-]?\d{3}[\s\-]?\d{4}
                |
                # Obfuscated with asterisks (clear intentional hiding)
                \+?\d{1,3}[\s\-]*\*+[\s\-]*\d{2,4}
                |
                # Standard format with exactly 3 groups of 3-4 digits
                # BUT exclude if it looks like a date (starts with 4 digits followed by -)
                (?!(?:19|20)\d{2}[-/])  # not a year
                (?!\d{2,3}[\.])  # not DD. or DDD.
                \d{3}[\s\-]\d{3}[\s\-]\d{4}
            )
            (?!\s+\d{2}(?:\s|$))  # not followed by space and 2 digits (hour indicator)
            (?![-/.]\d{2})  # not followed by date-like pattern
            (?!\d)  # not followed by more digits
            ''',
            re.UNICODE
        ),

        # Obfuscated phone numbers (hidden middle digits)
        'phone_obfuscated': re.compile(
            r'\+?\d{1,3}[\s\-]*\*{2,}[\s\-]*\d{2,4}',
            re.UNICODE
        ),

        # Crypto wallet addresses
        'btc_wallet': re.compile(
            r'\b(?:[13][a-km-zA-HJ-NP-Z1-9]{25,34}|bc1[a-z0-9]{39,59})\b',
            re.UNICODE
        ),
        'eth_wallet': re.compile(
            r'\b0x[a-fA-F0-9]{40}\b',
            re.UNICODE
        ),
        'usdt_trc20': re.compile(
            r'\bT[A-Za-z1-9]{33}\b',
            re.UNICODE
        ),

        # TON blockchain patterns
        'ton_wallet': re.compile(
            r'''(?x)
            (?:
                # User-friendly format (base64url, 48 chars)
                \b[EU][Qf][A-Za-z0-9_-]{46}\b
                |
                # Raw format (64 hex chars with optional workchain)
                (?:(?:0|-1):)?[a-fA-F0-9]{64}\b
                |
                # Bounceable/non-bounceable variants
                \b[kK][Qf][A-Za-z0-9_-]{46}\b
            )
            ''',
            re.UNICODE
        ),

        'ton_dns': re.compile(
            r'\b[a-z0-9][a-z0-9-]{1,61}[a-z0-9]\.ton\b',
            re.IGNORECASE | re.UNICODE
        ),

        # Telegram NFT and marketplace links
        'telegram_nft_link': re.compile(
            r'''(?x)
            (?:
                https?://(?:t\.me|fragment\.com)/
                (?:nft|gift|collectible|username|number)/
                [A-Za-z0-9_-]+
                |
                https?://(?:getgems\.io|tondiamonds\.io)/
                (?:nft|collection)/[A-Za-z0-9_-]+
            )
            ''',
            re.IGNORECASE | re.UNICODE
        ),

        # Telegram deep links
        'telegram_deeplink': re.compile(
            r'''(?x)
            (?:
                # tg:// protocol links
                tg://(?:resolve|join|msg|login|privatepost|share|
                       passport|settings|proxy|socks|boost|invoice)
                \?[a-zA-Z0-9_=&%-]+
                |
                # t.me special links
                https?://t(?:elegram)?\.me/
                (?:
                    joinchat/[A-Za-z0-9_-]{22,}  # private invite
                    |
                    \+[A-Za-z0-9_-]{16,}  # short invite link
                    |
                    c/\d+/\d+  # private channel post
                    |
                    s/[A-Za-z0-9_]+  # story link
                    |
                    iv/[A-Za-z0-9_]+  # instant view
                )
            )
            ''',
            re.IGNORECASE | re.UNICODE
        ),

        # Bank card numbers - enhanced
        'card_number': re.compile(
            r'''(?x)
            (?<!\d)  # not part of longer number
            (?:
                # Standard 16-digit with optional separators
                \d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}
                |
                # 13-15 digit cards (Visa, some debit)
                \d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{1,3}
                |
                # AmEx format (15 digits: 4-6-5)
                \d{4}[\s\-]?\d{6}[\s\-]?\d{5}
                |
                # Obfuscated patterns
                \d{4}[\s\-]?\*{4}[\s\-]?\*{4}[\s\-]?\d{4}
            )
            (?!\d)
            ''',
            re.UNICODE
        ),

        # Enhanced age patterns with multilingual support
        'age_pattern': re.compile(
            r'''(?x)  # verbose mode
            # Explicit age statements
            (?:(?:I'm|I\s+am|he's|she's|they're|мне|ему|ей|им)\s+)?
            (?:about|around|почти|примерно|приблизно)?\s*
            (1[89]|[2-6][0-9]|70)
            \s*(?:years?\s+old|y/?o|yrs?|лет|років|годиков?|годочків|y\.?\s?o\.?)\b
            |
            # Age prefix patterns
            \b(?:age|aged|возраст|вік)[\s:]+
            (1[89]|[2-6][0-9]|70)\b
            |
            # Birthday context
            (?:turn(?:ed|ing)?|became|исполнилось|виповнилося)\s+
            (1[89]|[2-6][0-9]|70)
            |
            # Slang patterns
            (?:20-something|30-something|двадцать\s+с\s+чем-то)
            ''',
            re.IGNORECASE | re.UNICODE
        ),

        # Contextual age numbers (requires validation)
        'age_number': re.compile(
            r'\b(1[89]|[2-6][0-9]|70)\b',
            re.UNICODE
        ),

        # Telegram usernames
        'telegram_username': re.compile(
            r'@[a-zA-Z0-9_]{5,32}\b',
            re.UNICODE
        ),

        # Fragment premium usernames (stricter validation)
        'fragment_username': re.compile(
            r'@[a-z][a-z0-9_]{4,31}\b',
            re.IGNORECASE | re.UNICODE
        ),

        # Telegram anonymous numbers
        'anonymous_number': re.compile(
            r'\+888\s*\d{7,10}',
            re.UNICODE
        ),

        # IP addresses
        'ipv4': re.compile(
            r'\b(?:\d{1,3}\.){3}\d{1,3}\b',
            re.UNICODE
        ),

        # Dates
        'date': re.compile(
            r'\b\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}\b',
            re.UNICODE
        ),

        # Passport/ID numbers
        'id_number': re.compile(
            r'\b[A-Z]{2}\d{6,10}\b',
            re.UNICODE
        ),

        # IBAN
        'iban': re.compile(
            r'\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b',
            re.UNICODE
        ),
    }

    # Suspicious keywords by category
    SUSPICIOUS_KEYWORDS = {
        'financial': [
            'transfer', 'payment', 'wire', 'bank', 'card', 'cvv', 'pin',
            'переказ', 'оплата', 'карта', 'банк', 'перевод', 'платеж'
        ],
        'personal_data': [
            'passport', 'ssn', 'license', 'id card', 'birth certificate',
            'паспорт', 'удостоверение', 'свідоцтво', 'посвідчення'
        ],
        'crypto': [
            'wallet', 'bitcoin', 'ethereum', 'usdt', 'crypto', 'btc', 'eth', 'ton',
            'гаманець', 'крипта', 'кошелек', 'криптовалюта'
        ],
        'scam_indicators': [
            'urgent', 'act now', 'limited time', 'verify', 'suspend',
            'терміново', 'обмежений час', 'підтвердіть', 'срочно', 'ограниченное время'
        ]
    }

    # Telegram-specific scam patterns
    TELEGRAM_SCAM_PATTERNS = {
        'fake_support': [
            r'@(?:telegram|support|security|verify|admin)(?:_?official|_?help|_?bot)?',
            r'официальн(?:ая|ый)\s+поддержка',
            r'офіційна\s+підтримка',
            r'verify\s+your\s+account',
            r'suspend(?:ed)?\s+account',
            r'подтверд(?:ите|ить)\s+аккаунт',
            r'підтверд(?:іть|ити)\s+акаунт',
        ],

        'session_steal': [
            r'(?:send|forward|enter)\s+(?:the\s+)?code',
            r'login\s+code',
            r'verification\s+code',
            r'(?:отправ|пришл|введ)(?:ь|и|ите)\s+код',
            r'(?:надішл|введ)(?:іть|ити)\s+код',
            r'SMS\s+код',
            r'Telegram\s+code',
        ],

        'wallet_drain': [
            r'connect\s+(?:your\s+)?wallet',
            r'claim\s+(?:your\s+)?(?:nft|airdrop|reward|gift)',
            r'free\s+(?:nft|ton|usdt|crypto)',
            r'подключ(?:и|ите)\s+кошел[её]к',
            r'підключ(?:і|іть)\s+гаманець',
            r'получ(?:и|ите)\s+(?:бесплатн|халяв)',
            r'отрима(?:й|йте)\s+безкоштовн',
        ],

        'fake_escrow': [
            r'(?:гарант|escrow|middleman|посредник|посередник)',
            r'safe\s+(?:deal|trade|exchange)',
            r'безопасн(?:ая|ый)\s+(?:сделк|обмен)',
            r'безпечн(?:а|ий)\s+(?:угод|обмін)',
            r'через\s+гаранта',
        ],

        'urgency_manipulation': [
            r'(?:urgent|срочно|терміново).*(?:act|действ|діяти|limited)',
            r'(?:only|только|лише|тільки)\s+\d+\s+(?:hours?|mins?|часов|минут|годин|хвилин)',
            r'offer\s+expires?',
            r'(?:предложение|пропозиція)\s+(?:истека|заканчива|закінчу)',
        ],

        'too_good': [
            r'\d+%\s+(?:profit|прибыл|прибуток)',
            r'guaranteed\s+(?:profit|return)',
            r'гарантирован(?:ный|ная)\s+(?:доход|прибыл)',
            r'гарантован(?:ий|а)\s+(?:дохід|прибуток)',
            r'(?:double|triple|удво|утро|подво|потро).*(?:money|деньг|гроші|investment)',
        ],
    }

    def __init__(self):
        """Initialize the MessageAnalyzer"""
        pass

    def _luhn_check(self, card_number: str) -> bool:
        """
        Validate card number using Luhn algorithm.

        Args:
            card_number: Card number string (digits only)

        Returns:
            True if valid according to Luhn algorithm
        """
        def digits_of(n):
            return [int(d) for d in str(n)]

        digits = digits_of(card_number)
        odd_digits = digits[-1::-2]
        even_digits = digits[-2::-2]

        checksum = sum(odd_digits)
        for d in even_digits:
            checksum += sum(digits_of(d * 2))

        return checksum % 10 == 0

    def _validate_bin(self, bin_prefix: str) -> bool:
        """
        Validate BIN (Bank Identification Number) - first 6 digits of card.

        Args:
            bin_prefix: First 6 digits of card number

        Returns:
            True if BIN matches known card network patterns
        """
        # Major card network prefixes
        VALID_BINS = {
            'visa': [r'^4'],
            'mastercard': [r'^5[1-5]', r'^2[2-7]'],
            'amex': [r'^3[47]'],
            'mir': [r'^220[0-4]'],  # Russian MIR cards
            'discover': [r'^6(?:011|5)'],
            'maestro': [r'^(?:5[06789]|6)'],
            'unionpay': [r'^62'],
        }

        for network, patterns in VALID_BINS.items():
            for pattern in patterns:
                if _rx(pattern).match(bin_prefix):
                    return True

        return False

    def _validate_phone(self, phone: str, context: str = '') -> bool:
        """
        Validate if a string is actually a phone number with Telegram-aware logic.

        Args:
            phone: Potential phone number string
            context: Surrounding text for context validation

        Returns:
            True if likely a phone number
        """
        original = phone.strip()
        digits_only = _rx(r'\D').sub('', phone)

        # PRIORITY 1: Reject dates IMMEDIATELY (most common false positive)
        # This must be first and absolute - but DON'T reject international phones
        DATE_REJECTION_PATTERNS = [
            r'^\d{4}[-/\.]\d{2}[-/\.]',  # YYYY-MM- (but not +XXXX which is phone)
            r'^\d{2}[-/\.]\d{2}[-/\.]\d{4}',  # DD-MM-YYYY
            r'^\d{2}[-/\.]\d{2}[-/\.]\d{2}',  # DD-MM-YY
            r'^\d{1,2}[-/\.]\d{1,2}[-/\.]\d{2,4}',  # Any date format
            r'^(19|20)\d{2}[-/]',  # Starts with year 19xx or 20xx
            r'[-/\.]\d{2}[-/\.]\d{2,4}$',  # Ends like a date
            r'\d{4}.*\d{2}.*\d{2}.*\d{2}$',  # Year-month-day-hour pattern
        ]

        # Only apply date rejection if it doesn't start with + (international phone indicator)
        if not original.startswith('+'):
            for pattern in DATE_REJECTION_PATTERNS:
                if _rx(pattern).search(original):
                    return False

        # PRIORITY 2: Reject IP addresses
        if _rx(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$').match(original):
            return False

        # PRIORITY 3: Reject if contains multiple dots (IP-like or date-like)
        if original.count('.') >= 2:
            return False

        # Basic length checks
        if len(digits_only) < 7:
            return False
        if len(digits_only) > 15:
            return False

        # Reject if ends with space and 2 digits (hour indicator)
        if _rx(r'\s+\d{2}$').search(original):
            return False

        # Reject if has newline followed by digits (common in logs/data)
        if '\n' in original:
            return False

        # NON-PHONE PATTERNS
        NON_PHONE_PATTERNS = [
            r'^\d{4}$',  # 4 digits = year
            r'^\d{6,7}$',  # 6-7 digits without separators
            r'^\d{8}$',  # 8 digits without separators or context
            r'^[0-9a-f]{8,}$',  # hex-like
            r'^\d{4}-\d{4}$',  # simple range
        ]

        for pattern in NON_PHONE_PATTERNS:
            if _rx(pattern).match(original):
                return False

        # Phone numbers with + are usually legitimate (international format)
        if original.startswith('+'):
            # But check it's not +YYYY (year)
            if _rx(r'^\+\d{4}$').match(original):
                return False
            # Must have at least 10 digits for international
            if len(digits_only) >= 10:
                return True

        # Obfuscated phones are likely real (people hide them intentionally)
        if '*' in original:
            return True

        # Check for phone context keywords
        PHONE_CONTEXT = [
            'phone', 'tel', 'номер', 'телефон', 'телефону', 'contact',
            'call', 'whatsapp', 'viber', 'signal', 'звони', 'звоні',
            'пиши', 'write me', 'dm me', 'писати', 'mobile', 'сотовый',
            'мобильный', 'мобільний', 'позвони', 'подзвони'
        ]

        has_phone_context = any(word in context.lower() for word in PHONE_CONTEXT)

        # Strong phone indicators
        PHONE_INDICATORS = [
            r'\(\d{3,4}\)',  # Area code in parentheses
            r'^\+\d',  # Starts with +
            r'\d{3}[-\s]\d{3}[-\s]\d{4}',  # US-style
            r'\d{3}[-\s]\d{2}[-\s]\d{2}',  # Common format
        ]

        for indicator in PHONE_INDICATORS:
            if _rx(indicator).search(original):
                return True

        # Without clear phone context, be very strict
        if not has_phone_context:
            # Must have proper phone separators
            if not _rx(r'[\s\-\(\)]').search(original):
                return False
            # Must have reasonable length
            if len(digits_only) < 10:
                return False

        # Final safety check: if digits start with year pattern, reject
        if digits_only.startswith(('19', '20')) and len(digits_only) >= 8:
            return False

        return True

    def _validate_card(self, card: str, context: str = '') -> bool:
        """
        Validate if a string looks like a credit/debit card with advanced checks.

        Args:
            card: Potential card number string
            context: Surrounding text for context validation

        Returns:
            True if likely a card number
        """
        digits_only = _rx(r'[\s\-\*]').sub('', card)

        # Remove asterisks for length check of visible digits
        visible_digits = digits_only.replace('*', '')

        # Length validation
        if '*' in digits_only:
            # Obfuscated card - accept if format looks right
            if len(digits_only) in [16, 19]:  # 16 digits or with separators
                return True
        else:
            if len(visible_digits) not in [13, 14, 15, 16]:
                return False

        # Reject all-same digits
        if len(set(visible_digits)) == 1:
            return False

        # Reject sequential patterns
        if _rx(r'^(0123|1234|2345|3456|4567|5678|6789)').match(visible_digits):
            return False

        # Context checks
        CARD_CONTEXT = [
            'card', 'карта', 'карточка', 'картка', 'cvv', 'cvc',
            'exp', 'expires', 'действует', 'діє', 'valid', 'дійсна',
            'visa', 'mastercard', 'мир', 'maestro', 'амекс', 'amex'
        ]

        has_card_context = any(word in context.lower() for word in CARD_CONTEXT)

        # Luhn algorithm check (only for complete, non-obfuscated cards)
        if '*' not in digits_only and len(visible_digits) == 16:
            if not self._luhn_check(visible_digits):
                # Failed Luhn - only accept with strong context
                return has_card_context

        # BIN validation (first 6 digits identify card type)
        if len(visible_digits) >= 6:
            bin_prefix = visible_digits[:6]
            if not self._validate_bin(bin_prefix):
                # Unknown BIN - accept only with context
                return has_card_context

        return True

    def _validate_age(self, number: str, text: str, position: int = None) -> bool:
        """
        Validate if a number is actually an age indicator with context awareness.

        Args:
            number: The number string to validate
            text: Full message text
            position: Position of number in text (optional)

        Returns:
            True only if strong context indicators suggest it's an age
        """

        # Telegram-specific age context patterns
        AGE_INDICATORS = {
            'strong': [
                r'\b(?:I\'m|I\s+am|мне|ему|ей|им|мені|йому|їй)\s+' + re.escape(number),
                r'\b' + re.escape(number) + r'\s+(?:лет|років|y/?o|yrs?|years?\s+old)\b',
                r'\b(?:aged?|возраст|вік)[\s:]+' + re.escape(number),
                r'\b(?:turning?|became|исполнилось|виповнилося)\s+' + re.escape(number),
                r'\b' + re.escape(number) + r'[-\s]year[-\s]old',
                r'(?:👶|🎂|🎉|🥳).*' + re.escape(number),  # emoji context
            ],
            'weak': [
                r'\b(?:человек|person|girl|boy|dude|людина|дівчина|хлопець)\b.*' + re.escape(number),
                r'\b' + re.escape(number) + r'.*(?:ищу|looking for|seeking|шукаю)',
            ]
        }

        # Anti-patterns (strong indicators it's NOT age)
        ANTI_PATTERNS = [
            r'\b' + re.escape(number) + r'\s*(?:руб|₽|\$|€|грн|usd|usdt|btc|eth|ton)',
            r'\b' + re.escape(number) + r'\s*(?:k\b|кк|тыс|млн|штук|pieces|шт)',
            r'(?:price|цена|ціна|стоит|коштує|costs).*' + re.escape(number),
            r'\b' + re.escape(number) + r'\s*(?:дней|днів|days|hours|годин|минут|хвилин)',
            r'\b' + re.escape(number) + r'%',  # percentages
            r'\b' + re.escape(number) + r'\s*(?:GB|MB|TB|КБ|МБ|ГБ)',  # file sizes
            r'#' + re.escape(number),  # hashtags/IDs
            r'v?' + re.escape(number) + r'\.\d',  # version numbers
            r'\b' + re.escape(number) + r'\s*(?:активов|activations|выводов|withdrawals)',
            r'(?:онлайн|online|servers?|серверов).*' + re.escape(number),
        ]

        text_lower = text.lower()

        # Check anti-patterns first (faster rejection)
        for pattern in ANTI_PATTERNS:
            if _rx(pattern, re.IGNORECASE).search(text_lower):
                return False

        # Check strong indicators
        for pattern in AGE_INDICATORS['strong']:
            if _rx(pattern, re.IGNORECASE).search(text_lower):
                return True

        # Extract local context (50 chars before/after)
        if position is not None:
            start = max(0, position - 50)
            end = min(len(text_lower), position + len(number) + 50)
            context = text_lower[start:end]
        else:
            # Find position if not provided
            match = re.search(r'\b' + re.escape(number) + r'\b', text_lower)
            if match:
                start = max(0, match.start() - 50)
                end = min(len(text_lower), match.end() + 50)
                context = text_lower[start:end]
            else:
                context = text_lower

        # Telegram-specific person indicators
        PERSON_MARKERS = [
            'девушка', 'парень', 'girl', 'boy', 'guy', 'gal',
            'дівчина', 'хлопець', 'чувак', 'красотка',
            'looking for', 'ищу', 'шукаю', 'знакомств',
            'meet', 'знайомств', 'dating'
        ]

        has_person_marker = any(marker in context for marker in PERSON_MARKERS)

        # Weak indicators only count if person context exists
        if has_person_marker:
            for pattern in AGE_INDICATORS['weak']:
                if _rx(pattern, re.IGNORECASE).search(text_lower):
                    return True

        return False

    def _is_example_or_test(self, text: str) -> bool:
        """
        Detect if message contains example/test data vs real sensitive information.

        Args:
            text: Message text to analyze

        Returns:
            True if message appears to be example/test data
        """
        text_lower = text.lower()

        EXAMPLE_MARKERS = [
            r'\b(?:example|пример|приклад|test|тест)\b',
            r'\b(?:like|such as|например|наприклад|типа)\b',
            r'\b(?:format|формат|вид|вигляд)\b',
            r'[x]{4,}',  # XXXX-XXXX-XXXX-XXXX
            r'\*{4,}',   # ****-****-****-****
            r'\d{4}(?:[\s\-]\d{4}){3}.*(?:example|пример|приклад)',
            r'(?:sample|образец|зразок)',
            r'(?:template|шаблон)',
        ]

        for marker in EXAMPLE_MARKERS:
            if _rx(marker).search(text_lower):
                return True

        # Check if numbers are too perfect (all same, sequential)
        numbers = _rx(r'\d{4,}').findall(text)
        for num in numbers:
            if len(set(num)) == 1:  # all same digit
                return True
            if num in ['1234567890', '0123456789', '1111111111', '0000000000']:
                return True
            # Check for sequential patterns
            if _rx(r'^(?:0123|1234|2345|3456|4567|5678|6789)').match(num):
                return True

        return False

    def _detect_intent(self, text: str, extracted_data: Dict) -> str:
        """
        Detect user intent with the extracted sensitive data.

        Args:
            text: Message text
            extracted_data: Dictionary of extracted data types

        Returns:
            Intent category string
        """
        text_lower = text.lower()

        # Intent marker patterns
        INTENT_PATTERNS = {
            'sharing': [
                r'\b(?:my|мой|мій|моя|моє)\b',
                r'\b(?:here(?:\s+is)?|вот|ось)\b',
                r'\b(?:this\s+is|это|це)\b',
                r'\b(?:take|возьми|візьми)\b',
            ],
            'requesting': [
                r'\b(?:send|give|provide|share)\b',
                r'\b(?:отправ|дай|скинь|кинь|присыл|надішл)\b',
                r'\b(?:need|want|looking for|требуется)\b',
                r'\b(?:нужн|хочу|треба|шукаю|потрібн)\b',
            ],
            'selling': [
                r'\b(?:sell|sale|продаж|продам|продаю)\b',
                r'\b(?:price|цена|ціна|стоимость|вартість)\b',
                r'\b(?:buy|купить|купити|купля)\b',
                r'\$\d+|\d+\s*(?:руб|грн|usd|₽)',
            ],
            'verifying': [
                r'\b(?:verify|confirm|check|valid|working)\b',
                r'\b(?:проверь|подтверд|валидн|перевір|підтверд)\b',
                r'\b(?:работает|рабочий|робочий|працює)\b',
            ],
            'warning': [
                r'\b(?:scam|fraud|fake|осторожн|обережн)\b',
                r'\b(?:мошенник|обман|кидал|шахра)\b',
                r'\b(?:не\s+(?:верь|отправля|давай|віря|надсила))\b',
                r'\b(?:don\'t|do not)\s+(?:trust|send|give)\b',
            ],
            'offering_service': [
                r'\b(?:offer|предлага|пропоную)\b',
                r'\b(?:service|услуг|послуг)\b',
                r'\b(?:help|помо[гж]|допомо)\b',
            ],
        }

        for intent, patterns in INTENT_PATTERNS.items():
            for pattern in patterns:
                if _rx(pattern).search(text_lower):
                    return intent

        return 'unknown'

    def _analyze_emoji_context(self, text: str) -> Dict:
        """
        Analyze emojis in the message for context (Telegram users use emojis heavily).

        Args:
            text: Message text

        Returns:
            Dictionary of emoji categories found
        """
        RISK_EMOJIS = {
            'financial': ['💰', '💵', '💴', '💶', '💷', '💳', '🏦', '💸', '🤑', '💲'],
            'warning': ['⚠️', '🚨', '⛔', '🚫', '❌', '❗', '‼️', '🛑'],
            'scam': ['🎁', '🎉', '🎊', '🆓', '🔥', '💎', '🚀', '💯', '⚡'],
            'celebration': ['🎂', '🎈', '🥳', '🎆', '🎇', '🎃', '🎄'],
            'person': ['👤', '👥', '🙋', '🙋‍♂️', '🙋‍♀️', '👶', '🧒', '👦', '👧'],
            'crypto': ['₿', '💎', '🚀', '📈', '📉', '🌙'],
        }

        emoji_context = {}

        for category, emojis in RISK_EMOJIS.items():
            found = [e for e in emojis if e in text]
            if found:
                emoji_context[category] = found

        return emoji_context

    def _detect_scam_patterns(self, text: str) -> Dict[str, List[str]]:
        """
        Detect Telegram-specific scam patterns in message.

        Args:
            text: Message text

        Returns:
            Dictionary of detected scam pattern categories
        """
        detected = {}
        text_lower = text.lower()

        for category, patterns in self.TELEGRAM_SCAM_PATTERNS.items():
            matches = []
            for pattern in patterns:
                if _rx(pattern).search(text_lower):
                    matches.append(pattern)

            if matches:
                detected[category] = matches

        return detected

    def _calculate_risk_score(self, extracted_data: Dict, context: Dict = None) -> int:
        """
        Calculate risk score based on extracted data and context.

        Args:
            extracted_data: Dictionary of extracted data types
            context: Optional context dictionary with intent, scam patterns, etc.

        Returns:
            Risk score from 0-100
        """
        score = 0

        # Base weights for different data types
        weights = {
            'card_number': 30,
            'ton_wallet': 25,
            'btc_wallet': 25,
            'eth_wallet': 25,
            'usdt_trc20': 25,
            'iban': 30,
            'id_number': 20,
            'phone': 15,
            'phone_obfuscated': 20,  # Obfuscated = intentional hiding
            'email': 10,
            'telegram_deeplink': 15,  # Private invites can be risky
            'telegram_nft_link': 10,
            'anonymous_number': 20,
            'age_pattern': 12,
            'age_number': 10,
            'ton_dns': 8,
            'ipv4': 8,
            'url': 5,
            'domain': 3,
            'date': 2,
            'telegram_username': 3,
            'fragment_username': 5,
        }

        # Calculate base score
        for data_type, items in extracted_data.items():
            if items and data_type in weights:
                count = min(len(items), 3)  # Cap at 3 to prevent score inflation
                score += weights[data_type] * count

        # Context-based adjustments
        if context:
            # Multiple high-risk data types together
            high_risk_types = {
                'card_number', 'ton_wallet', 'btc_wallet',
                'eth_wallet', 'iban', 'phone_obfuscated', 'id_number'
            }
            found_high_risk = len(set(extracted_data.keys()) & high_risk_types)

            if found_high_risk >= 2:
                score = int(score * 1.3)
            if found_high_risk >= 3:
                score = int(score * 1.5)

            # Scam pattern detection
            scam_patterns = context.get('scam_patterns', {})
            if scam_patterns:
                scam_count = sum(len(patterns) for patterns in scam_patterns.values())
                score += scam_count * 15

            # Intent-based adjustment
            intent = context.get('intent')
            if intent == 'selling':
                score = int(score * 1.2)  # Selling credentials/accounts
            elif intent == 'warning':
                score = int(score * 0.7)  # Warning others reduces risk
            elif intent == 'verifying':
                score = int(score * 1.1)

            # Example/test detection
            if context.get('is_example'):
                score = int(score * 0.3)  # Dramatically reduce for examples

            # Emoji context
            emoji_ctx = context.get('emoji_context', {})
            if 'scam' in emoji_ctx:
                score = int(score * 1.2)
            if 'warning' in emoji_ctx:
                score = int(score * 1.15)
            if 'financial' in emoji_ctx and len(extracted_data) > 2:
                score = int(score * 1.1)

        return min(int(score), 100)

    def _analyze_keywords(self, text: str) -> Dict[str, List[str]]:
        """
        Find suspicious keywords in text.

        Args:
            text: Message text

        Returns:
            Dictionary of found keyword categories
        """
        found_keywords = {}
        text_lower = text.lower()

        for category, keywords in self.SUSPICIOUS_KEYWORDS.items():
            found = [kw for kw in keywords if kw.lower() in text_lower]
            if found:
                found_keywords[category] = found

        return found_keywords

    def _analyze_context(self, text: str, extracted_data: Dict) -> Dict:
        """
        Analyze message context and patterns.

        Args:
            text: Message text
            extracted_data: Extracted data dictionary

        Returns:
            Context analysis dictionary
        """
        context = {
            "has_multiple_data_types": len(extracted_data) > 2,
            "has_financial_indicators": False,
            "has_personal_data_indicators": False,
            "message_characteristics": []
        }

        # Identify sensitive data types
        sensitive_types = {
            'card_number', 'btc_wallet', 'eth_wallet', 'usdt_trc20',
            'ton_wallet', 'iban', 'phone', 'phone_obfuscated',
            'email', 'id_number'
        }
        found_sensitive = set(extracted_data.keys()) & sensitive_types

        if len(found_sensitive) >= 2:
            context["has_multiple_data_types"] = True
            context["message_characteristics"].append("multiple_sensitive_data")

        # Financial indicators
        financial_types = {
            'card_number', 'iban', 'btc_wallet', 'eth_wallet',
            'usdt_trc20', 'ton_wallet'
        }
        if any(k in extracted_data for k in financial_types):
            context["has_financial_indicators"] = True
            context["message_characteristics"].append("financial_data")

        # Personal data indicators
        personal_types = {
            'phone', 'phone_obfuscated', 'email', 'id_number',
            'age_pattern', 'age_number'
        }
        if any(k in extracted_data for k in personal_types):
            context["has_personal_data_indicators"] = True
            context["message_characteristics"].append("personal_data")

        # High data density (lots of data in short message)
        if len(text) < 200 and len(extracted_data) >= 3:
            context["message_characteristics"].append("high_data_density")

        return context

    def _generate_warnings(self, analysis: Dict, context: Dict = None) -> List[str]:
        """
        Generate human-readable warnings for detected data.

        Args:
            analysis: Analysis dictionary
            context: Optional context dictionary

        Returns:
            List of warning strings
        """
        warnings = []
        extracted = analysis.get("extracted_data", {})

        # Data type warnings
        if 'card_number' in extracted:
            warnings.append("⚠️ Bank card number detected")

        if any(k in extracted for k in ['btc_wallet', 'eth_wallet', 'usdt_trc20']):
            warnings.append("⚠️ Cryptocurrency wallet address detected")

        if 'ton_wallet' in extracted:
            warnings.append("⚠️ TON wallet address detected")

        if 'email' in extracted:
            warnings.append("📧 Email address detected")

        if 'phone' in extracted or 'phone_obfuscated' in extracted:
            warnings.append("📱 Phone number detected")

        if 'iban' in extracted:
            warnings.append("🏦 IBAN detected")

        if 'id_number' in extracted:
            warnings.append("🆔 ID/Passport number pattern detected")

        if 'telegram_deeplink' in extracted:
            warnings.append("🔗 Telegram private link detected")

        if 'anonymous_number' in extracted:
            warnings.append("📞 Telegram anonymous number detected")

        # Context-based warnings
        if analysis.get("context", {}).get("has_multiple_data_types"):
            warnings.append("🚨 Multiple sensitive data types in one message")

        # Scam pattern warnings
        if context and context.get('scam_patterns'):
            scam_types = list(context['scam_patterns'].keys())
            if 'fake_support' in scam_types:
                warnings.append("⚠️ Fake support account pattern detected")
            if 'session_steal' in scam_types:
                warnings.append("🚨 Session stealing attempt detected")
            if 'wallet_drain' in scam_types:
                warnings.append("⚠️ Wallet draining scam pattern detected")
            if 'fake_escrow' in scam_types:
                warnings.append("⚠️ Fake escrow/middleman pattern detected")

        # Keyword warnings
        keywords = analysis.get("keywords", {})
        if keywords.get("scam_indicators"):
            warnings.append("⚠️ Scam indicators detected")

        # Risk score warnings
        risk_score = analysis.get("risk_score", 0)
        if risk_score >= 70:
            warnings.append(f"🔴 Critical risk message (score: {risk_score})")
        elif risk_score >= 50:
            warnings.append(f"🟠 High risk message (score: {risk_score})")

        return warnings

    def analyze_message(self, text: str, extended: bool = True) -> Dict:
        """
        Analyze a single message text for sensitive data and patterns.

        Args:
            text: Message text to analyze
            extended: Include extended analysis (keywords, context, scam patterns)

        Returns:
            Dictionary with analysis results (only includes detected data)
        """
        if not text:
            return {
                "has_sensitive_data": False,
                "is_empty": True
            }

        # Check if this is example/test data first
        is_example = self._is_example_or_test(text)

        extracted_data = {}

        # Extract all patterns
        for data_type, pattern in self.PATTERNS.items():
            matches = pattern.findall(text)
            if matches:
                # Handle tuples from regex groups
                if matches and isinstance(matches[0], tuple):
                    matches = [m[0] if isinstance(m, tuple) else m for m in matches]

                matches = [str(m).strip() for m in matches if m]

                # Apply type-specific validators with context
                if data_type == 'phone':
                    matches = [m for m in matches if self._validate_phone(m, text)]
                elif data_type == 'phone_obfuscated':
                    matches = [m for m in matches if '*' in m]
                elif data_type == 'card_number':
                    matches = [m for m in matches if self._validate_card(m, text)]
                elif data_type in ['age_number', 'age_pattern']:
                    # Get position for context-aware validation
                    validated = []
                    for m in matches:
                        pos = text.find(m)
                        if self._validate_age(m, text, pos):
                            validated.append(m)
                    matches = validated
                elif data_type == 'ipv4':
                    # Validate it's not a phone number pattern
                    matches = [m for m in matches if not self._validate_phone(m, text)]

                # Remove duplicates
                matches = list(set(matches))

                if matches:
                    extracted_data[data_type] = matches

        analysis = {"has_sensitive_data": bool(extracted_data)}

        if extracted_data:
            # Build context object
            context = {
                'is_example': is_example,
                'intent': self._detect_intent(text, extracted_data),
                'emoji_context': self._analyze_emoji_context(text),
            }

            if extended:
                context['scam_patterns'] = self._detect_scam_patterns(text)

            analysis["extracted_data"] = extracted_data
            analysis["data_types_found"] = list(extracted_data.keys())
            analysis["risk_score"] = self._calculate_risk_score(extracted_data, context)

            # Risk level classification
            if is_example:
                analysis["risk_level"] = "example"  # Special category
            elif analysis["risk_score"] >= 80:
                analysis["risk_level"] = "critical"
            elif analysis["risk_score"] >= 50:
                analysis["risk_level"] = "high"
            elif analysis["risk_score"] >= 20:
                analysis["risk_level"] = "medium"
            else:
                analysis["risk_level"] = "low"

            if extended:
                # Add keywords analysis
                keywords = self._analyze_keywords(text)
                if keywords:
                    analysis["keywords"] = keywords

                # Add context analysis
                context_analysis = self._analyze_context(text, extracted_data)
                if any(context_analysis.values()):
                    analysis["context"] = context_analysis

                # Add intent and other context
                analysis["intent"] = context['intent']

                if context.get('scam_patterns'):
                    analysis["scam_patterns"] = context['scam_patterns']

                if context.get('emoji_context'):
                    analysis["emoji_context"] = context['emoji_context']

                # Generate warnings
                warnings = self._generate_warnings(analysis, context)
                if warnings:
                    analysis["warnings"] = warnings

        return analysis

    def analyze_conversation(
        self,
        messages: List[Dict],
        include_message_analysis: bool = True
    ) -> Dict:
        """
        Analyze entire conversation for patterns.

        Args:
            messages: List of message dictionaries with 'text' and 'message_id'
            include_message_analysis: Include individual message analysis

        Returns:
            Conversation-level analysis (only includes messages with sensitive data)
        """
        total_messages = len(messages)
        messages_with_sensitive_data = 0

        risk_summary = {
            "critical": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
            "example": 0,
        }
        data_type_frequency = {}

        analyzed_messages = []
        all_extracted_data = {}

        # Accounts often repeat the same message; each distinct text is analyzed once
        analyzed_texts: Dict[str, Dict] = {}

        for msg in messages:
            text = msg.get("text", "")
            if not text:
                continue

            msg_analysis = analyzed_texts.get(text)
            if msg_analysis is None:
                msg_analysis = analyzed_texts[text] = self.analyze_message(text, extended=True)

            if not msg_analysis.get("has_sensitive_data"):
                continue

            messages_with_sensitive_data += 1

            # Build message analysis object
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

            # Add optional fields if present
            if "intent" in msg_analysis:
                message_obj["intent"] = msg_analysis["intent"]
            if "scam_patterns" in msg_analysis:
                message_obj["scam_patterns"] = msg_analysis["scam_patterns"]
            if "warnings" in msg_analysis:
                message_obj["warnings"] = msg_analysis["warnings"]

            # Add group info if available
            if "group" in msg:
                message_obj["group"] = msg["group"]

            analyzed_messages.append(message_obj)

            # Update risk summary
            risk_level = msg_analysis.get("risk_level", "low")
            risk_summary[risk_level] += 1

            # Aggregate data
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

        # Convert sets to lists for JSON serialization
        aggregated_data_list = {k: list(v) for k, v in all_extracted_data.items()}

        # Calculate overall conversation risk
        overall_risk = self._calculate_conversation_risk({
            "total_messages": total_messages,
            "messages_with_sensitive_data": messages_with_sensitive_data,
            "risk_summary": risk_summary,
            "aggregated_data": aggregated_data_list,
        })

        conversation_analysis = {
            "has_sensitive_data": True,
            "total_messages": total_messages,
            "messages_with_sensitive_data": messages_with_sensitive_data,
            "aggregated_data": aggregated_data_list,
            "risk_summary": risk_summary,
            "data_type_frequency": data_type_frequency,
            "overall_risk_score": overall_risk,
        }

        # Add overall risk level
        if overall_risk >= 70:
            conversation_analysis["overall_risk_level"] = "critical"
        elif overall_risk >= 50:
            conversation_analysis["overall_risk_level"] = "high"
        elif overall_risk >= 25:
            conversation_analysis["overall_risk_level"] = "medium"
        else:
            conversation_analysis["overall_risk_level"] = "low"

        if include_message_analysis and analyzed_messages:
            conversation_analysis["message_analyses"] = analyzed_messages

        return conversation_analysis

    def _calculate_conversation_risk(self, conv_analysis: Dict) -> int:
        """
        Calculate overall conversation risk score.

        Args:
            conv_analysis: Conversation analysis dictionary

        Returns:
            Risk score from 0-100
        """
        total = conv_analysis["total_messages"]
        if total == 0:
            return 0

        sensitive_count = conv_analysis["messages_with_sensitive_data"]
        sensitive_ratio = sensitive_count / total

        # Weight risk levels
        risk_summary = conv_analysis["risk_summary"]
        weighted_score = (
            risk_summary.get("critical", 0) * 100 +
            risk_summary.get("high", 0) * 60 +
            risk_summary.get("medium", 0) * 30 +
            risk_summary.get("low", 0) * 10 +
            risk_summary.get("example", 0) * 2  # Examples have minimal weight
        ) / max(total, 1)

        # Data type diversity factor
        data_type_count = len(conv_analysis["aggregated_data"])
        diversity_factor = min(data_type_count * 5, 30)

        # Final score calculation
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
        """
        Analyze a user's messaging patterns for suspicious behavior.

        Args:
            user_messages: List of messages from the user
            user_id: User ID

        Returns:
            User behavior analysis (only if sensitive data found)
        """
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

        # Behavior flag detection
        behavior_flags = []

        if frequency > 0.3:
            behavior_flags.append("high_sensitive_data_frequency")

        if len(conv_analysis["aggregated_data"]) >= 5:
            behavior_flags.append("diverse_sensitive_data_types")

        if conv_analysis["risk_summary"].get("critical", 0) > 0:
            behavior_flags.append("critical_risk_messages")

        if conv_analysis["risk_summary"].get("high", 0) > 2:
            behavior_flags.append("multiple_high_risk_messages")

        if behavior_flags:
            user_analysis["behavior_flags"] = behavior_flags

        # Overall user risk assessment
        overall_risk = conv_analysis.get("overall_risk_score", 0)
        if overall_risk >= 70:
            user_analysis["risk_assessment"] = "critical"
        elif overall_risk >= 50:
            user_analysis["risk_assessment"] = "high"
        elif overall_risk >= 25:
            user_analysis["risk_assessment"] = "medium"

        return user_analysis
