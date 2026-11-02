"""Offline phone number intelligence (no network, no cost) via libphonenumber.

The location and carrier tables take about 110 MB, and Python can't unload them, so
lookups run in a short-lived helper: this file, started as a script. The memory goes
back to the system when it exits. Run from the server, use ``lookup_phone``.
"""
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import phonenumbers
from phonenumbers import PhoneNumberType, timezone

LINE_TYPES = {
    PhoneNumberType.MOBILE: "mobile",
    PhoneNumberType.FIXED_LINE: "landline",
    PhoneNumberType.FIXED_LINE_OR_MOBILE: "landline or mobile",
    PhoneNumberType.VOIP: "VoIP",
    PhoneNumberType.TOLL_FREE: "toll free",
    PhoneNumberType.PREMIUM_RATE: "premium rate",
    PhoneNumberType.SHARED_COST: "shared cost",
    PhoneNumberType.PERSONAL_NUMBER: "personal number",
    PhoneNumberType.PAGER: "pager",
    PhoneNumberType.UAN: "UAN",
    PhoneNumberType.VOICEMAIL: "voicemail",
    PhoneNumberType.UNKNOWN: "unknown",
}


HELPER_TIMEOUT = 30
HELPER_LIMIT = 2  # each helper briefly uses about 125 MB
_helper_slots: Optional[asyncio.Semaphore] = None


class PhoneParseError(ValueError):
    pass


class PhoneLookupFailed(RuntimeError):
    """The helper crashed or timed out (not a problem with the number)."""


def _parse(raw: str, default_region: str = ""):
    """Parse a number in any format; numbers without + are tried as international."""
    text = (raw or "").strip()
    digits = re.sub(r"[^\d+]", "", text)
    if len(re.sub(r"\D", "", digits)) < 6:
        raise PhoneParseError("Enter a phone number with country code, e.g. +380 50 123 4567")
    candidate = digits if digits.startswith("+") else ("+" + digits[2:] if digits.startswith("00") else "+" + digits)
    try:
        number = phonenumbers.parse(candidate, None)
    except phonenumbers.NumberParseException:
        try:
            number = phonenumbers.parse(text, default_region.upper() or None)
        except phonenumbers.NumberParseException as e:
            raise PhoneParseError(f"Not a phone number: {e}") from e
    return number


def _search_formats(number) -> List[str]:
    """Formats people actually write the number in - useful for searching."""
    e164 = phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)
    plain = e164.lstrip("+")
    national = phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.NATIONAL)
    international = phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
    national_digits = re.sub(r"\D", "", national)
    return sorted({e164, plain, international, national, national_digits, f"+{plain}"})


def search_formats(raw: str) -> List[str]:
    """The number's written formats, without loading the location tables."""
    return _search_formats(_parse(raw))


def phone_info(raw: str, default_region: str = "") -> Dict[str, Any]:
    """The full analysis. Loads the location tables into this process: the server
    should use ``lookup_phone`` instead."""
    from phonenumbers import carrier, geocoder

    text = (raw or "").strip()
    number = _parse(raw, default_region)
    e164 = phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)
    plain = e164.lstrip("+")
    national = phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.NATIONAL)
    international = phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.INTERNATIONAL)

    return {
        "input": text,
        "valid": phonenumbers.is_valid_number(number),
        "possible": phonenumbers.is_possible_number(number),
        "e164": e164,
        "international": international,
        "national": national,
        "country_code": number.country_code,
        "region": phonenumbers.region_code_for_number(number),
        "location": geocoder.description_for_number(number, "en") or None,
        "carrier": carrier.name_for_number(number, "en") or None,
        "line_type": LINE_TYPES.get(phonenumbers.number_type(number), "unknown"),
        "timezones": list(timezone.time_zones_for_number(number)),
        "search_formats": _search_formats(number),
        "links": {
            "whatsapp": f"https://wa.me/{plain}",
            "telegram": f"https://t.me/+{plain}",
            "viber": f"viber://chat?number=%2B{plain}",
            "google": "https://www.google.com/search?q=" + quote(" OR ".join(f'"{f}"' for f in (e164, international, national))),
        },
        "note": "Carrier is the number's original operator - it may have been ported since. "
                "Run an HLR lookup to see the current network.",
    }


async def lookup_phone(raw: str) -> Dict[str, Any]:
    """``phone_info`` in a helper process, so the server never holds the tables."""
    global _helper_slots
    from utils.subprocess_runner import run_command

    if "\x00" in raw:
        raise PhoneParseError("Not a phone number")
    if _helper_slots is None:
        _helper_slots = asyncio.Semaphore(HELPER_LIMIT)
    # -I: nothing but the standard library and the venv can be imported by the helper
    async with _helper_slots:
        result = await run_command([sys.executable, "-I", str(Path(__file__).resolve()), raw], timeout=HELPER_TIMEOUT)
    if result.timed_out:
        raise PhoneLookupFailed("The phone lookup took too long")
    try:
        answer = json.loads(result.stdout)
    except ValueError:
        raise PhoneLookupFailed(f"The phone lookup failed: {result.error_summary(200)}") from None
    if "error" in answer:
        raise PhoneParseError(answer["error"])
    return answer["result"]


def _helper_main() -> None:
    try:
        print(json.dumps({"result": phone_info(sys.argv[1])}))
    except PhoneParseError as e:
        print(json.dumps({"error": str(e)}))


if __name__ == "__main__":
    _helper_main()
