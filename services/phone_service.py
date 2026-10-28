"""Offline phone number intelligence (no network, no cost) via libphonenumber."""
import re
from typing import Any, Dict
from urllib.parse import quote

import phonenumbers
from phonenumbers import PhoneNumberType, carrier, geocoder, timezone

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


class PhoneParseError(ValueError):
    pass


def phone_info(raw: str, default_region: str = "") -> Dict[str, Any]:
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

    e164 = phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)
    plain = e164.lstrip("+")
    national = phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.NATIONAL)
    international = phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
    national_digits = re.sub(r"\D", "", national)

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
        # Formats people actually write the number in - useful for searching
        "search_formats": sorted({e164, plain, international, national, national_digits, f"+{plain}"}),
        "links": {
            "whatsapp": f"https://wa.me/{plain}",
            "telegram": f"https://t.me/+{plain}",
            "viber": f"viber://chat?number=%2B{plain}",
            "google": "https://www.google.com/search?q=" + quote(" OR ".join(f'"{f}"' for f in (e164, international, national))),
        },
        "note": "Carrier is the number's original operator - it may have been ported since. "
                "Run an HLR lookup to see the current network.",
    }
