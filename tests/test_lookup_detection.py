"""The lookup box: what a typed value is read as (services.entities.detect), the full
numbers offered for a phone typed without its country code, and /api/lookup/detect.

What the user types is never "noise": the filters that keep example.com, abuse@...,
private IPs and "admin" out of the identifiers *found in results* must not apply to it.
"""
from uuid import UUID

import pytest

from services.entities import (
    PHONE_SUGGESTIONS_MAX, detect, entities_from_parameters, extract_entities, make_entity, phone_suggestions,
)


def readings(query):
    return [(e.type, e.value) for e in detect(query)]


def first(query):
    found = readings(query)
    return found[0] if found else None


# ---------------------------------------------------------------------------
# Ordinary input
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("query, expected", [
    ("john.doe@gmail.com", ("email", "john.doe@gmail.com")),
    ("  John.Doe@Gmail.com ", ("email", "john.doe@gmail.com")),
    ("mailto:someone@company.co", ("email", "someone@company.co")),
    ("+1 (415) 555-2671", ("phone", "+14155552671")),
    ("+380 50 123 4567", ("phone", "+380501234567")),
    ("00380501234567", ("phone", "+380501234567")),
    ("380501234567", ("phone", "+380501234567")),          # country code included, + left out
    ("jdoe_admin", ("username", "jdoe_admin")),
    ("@durov", ("telegram_username", "durov")),
    ("acme-login.net", ("domain", "acme-login.net")),
    ("sub.shop.acme.io", ("domain", "sub.shop.acme.io")),
    ("8.8.8.8", ("ip", "8.8.8.8")),
    ("2001:4860:4860::8888", ("ip", "2001:4860:4860::8888")),
    ("https://acme.io/login?x=1", ("url", "https://acme.io/login?x=1")),
    ("https://github.com/torvalds", ("username", "torvalds")),
    ("https://t.me/durov", ("telegram_username", "durov")),
    ("t.me/durov", ("telegram_username", "durov")),
    ("https://vk.com/id12345", ("vk", "12345")),
    ("vk.com/durov", ("vk", "durov")),
    ("123456789012345678901", ("gaia_id", "123456789012345678901")),
    ("aa-bb-cc-dd-ee-ff", ("bssid", "AA:BB:CC:DD:EE:FF")),
    ("0x52908400098527886E0F7030069857D2E4169EE7", ("crypto_eth", "0x52908400098527886e0f7030069857d2e4169ee7")),
    ("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", ("crypto_btc", "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa")),
    ("John Smith", ("text", "John Smith")),
])
def test_first_reading(query, expected):
    assert first(query) == expected


def test_a_link_is_also_its_domain():
    assert readings("https://acme.io/login") == [("url", "https://acme.io/login"), ("domain", "acme.io")]
    assert ("domain", "github.com") in readings("https://github.com/torvalds")


def test_a_link_to_an_address_is_also_that_ip():
    assert readings("http://203.0.113.5:8080/admin") == [("url", "http://203.0.113.5:8080/admin"), ("ip", "203.0.113.5")]


def test_at_name_is_a_telegram_name_or_a_username():
    assert readings("@durov") == [("telegram_username", "durov"), ("username", "durov")]


def test_a_number_can_be_a_telegram_or_vk_id():
    assert readings("123456789") == [("telegram_id", "123456789"), ("vk", "123456789")]


@pytest.mark.parametrize("query", ["", "   ", "a", "@", "hello@", "http://[broken"])
def test_nothing_to_read(query):
    assert readings(query) == []


# ---------------------------------------------------------------------------
# Typed values are never noise
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("email", [
    "jdoe.admin@example.com",        # a noise domain
    "someone@example.org",
    "billing@godaddy.com",           # registrar boilerplate when found in WHOIS
    "support@acme-corp.net",         # a noise mailbox name
    "abuse@hosting.net",
    "jane.supporter@gmail.com",      # contains "support"
    "owner@privacy-shop.com",        # "privacy" in the domain
    "redacted.name@acme.io",
    "12345+tag@users.noreply.github.com",
])
def test_any_typed_email_is_an_email(email):
    assert readings(email) == [("email", email)]


@pytest.mark.parametrize("domain", ["example.com", "example.org", "cloudflare.com", "godaddy.com", "w3.org",
                                    "cdn.cloudflare.com", "gmail.com", "t.me"])
def test_any_typed_domain_is_a_domain(domain):
    assert readings(domain) == [("domain", domain)]


@pytest.mark.parametrize("ip", ["192.168.1.5", "10.0.0.1", "127.0.0.1", "169.254.10.10", "0.0.0.0", "::1", "fe80::1"])
def test_any_typed_ip_is_an_ip(ip):
    assert readings(ip) == [("ip", ip)]


@pytest.mark.parametrize("name", ["admin", "user", "test", "root", "null", "support", "unknown"])
def test_any_typed_name_is_a_username(name):
    assert readings(name) == [("username", name)]


def test_typed_links_keep_noise_hosts_and_pictures():
    assert first("https://example.com/page") == ("url", "https://example.com/page")
    assert first("https://acme.io/photo.jpg") == ("url", "https://acme.io/photo.jpg")
    assert first("http://192.168.0.1/admin") == ("url", "http://192.168.0.1/admin")


def test_noise_is_still_dropped_from_results():
    """The other half of the rule: none of these become identifiers when a module returns them."""
    found = {e.key for e, _ in extract_entities({
        "email": "abuse@registrar-example.net", "contact": "write to someone@example.com or real.person@acme.io",
        "domain": "example.org", "ip": "192.168.1.5", "username": "admin", "url": "https://acme.io/logo.png",
    })}
    assert found == {"email:real.person@acme.io", "domain:acme.io"}
    for kind, value in [("email", "x@example.com"), ("domain", "example.com"), ("ip", "10.0.0.1"), ("username", "admin")]:
        assert make_entity(kind, value) is None
        assert make_entity(kind, value, typed=True) is not None


def test_typed_values_still_need_the_right_shape():
    for kind, value in [("email", "not an email"), ("email", "a@b"), ("domain", "no spaces.com"), ("domain", "nodot"),
                        ("ip", "999.1.1.1"), ("url", "ftp://acme.io"), ("url", "acme.io"), ("username", "two words"),
                        ("username", "12345"), ("username", "a@b.co")]:
        assert make_entity(kind, value, typed=True) is None, (kind, value)


def test_what_was_looked_up_is_recorded_even_if_it_is_noise():
    assert [e.key for e in entities_from_parameters({"kwargs": {"domain": "example.com"}}, "whois")] == ["domain:example.com"]
    assert [e.key for e in entities_from_parameters({"kwargs": {"ip": "192.168.1.5"}}, "ip")] == ["ip:192.168.1.5"]
    assert [e.key for e in entities_from_parameters({"kwargs": {"username": "admin"}}, "username")] == ["username:admin"]
    assert [e.key for e in entities_from_parameters({"kwargs": {"query": "abuse@example.com"}}, "oi")] == ["email:abuse@example.com"]


# ---------------------------------------------------------------------------
# Words with a dot: a site or a handle
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("query", ["john.doe", "user.name", "max.mustermann"])
def test_dotted_handle_is_offered_as_a_username_too(query):
    assert readings(query) == [("domain", query), ("username", query)]


@pytest.mark.parametrize("query", ["john.com", "acme.io", "site.ru", "www.acme.org", "a.b.example.net"])
def test_a_site_is_only_a_domain(query):
    assert [kind for kind, _ in readings(query)] == ["domain"]


def test_version_like_numbers_are_not_addresses_or_domains():
    assert readings("1.2.3") == [("username", "1.2.3")]


# ---------------------------------------------------------------------------
# Phone numbers without a country code
# ---------------------------------------------------------------------------

def values(query, prefer=()):
    return [s["value"] for s in phone_suggestions(query, prefer)]


@pytest.mark.parametrize("query", ["4155552671", "(415) 555-2671", "415-555-2671", "415.555.2671", " 415 555 2671 "])
def test_national_number_is_not_guessed(query):
    assert "phone" not in [kind for kind, _ in readings(query)]
    assert values(query)[0] == "+14155552671"


def test_suggestion_says_which_number_and_country():
    suggestion = phone_suggestions("(415) 555-2671")[0]
    assert suggestion == {"type": "phone", "value": "+14155552671", "display": "+1 415-555-2671",
                          "region": "US", "country": "United States / Canada"}


def test_suggestions_are_valid_distinct_numbers():
    for query in ["4155552671", "89161234567", "0501234567", "07911123456"]:
        found = values(query)
        assert found and len(found) == len(set(found)) <= PHONE_SUGGESTIONS_MAX
        for value in found:
            assert first(value) == ("phone", value)


def test_the_readers_countries_come_first():
    assert values("0501234567", ["UA"])[0] == "+380501234567"
    assert values("89161234567", ["RU"])[0] == "+79161234567"
    assert values("4155552671", ["RU", "US"])[:2] == ["+74155552671", "+14155552671"]
    # unknown or malformed regions are ignored
    assert values("0501234567", ["xx", "", "ua"])[0] == "+380501234567"


def test_trunk_prefixes_are_understood():
    assert "+79161234567" in values("8 (916) 123-45-67")     # Russia's 8
    assert "+447911123456" in values("07911 123456")         # the UK's 0


@pytest.mark.parametrize("query", [
    "+14155552671",        # has its country code
    "+1 415 555 2671",
    "00380501234567",
    "380501234567",        # a full number without the +: detect() reads it
    "12345",               # too short
    "1234567890123456",    # too long
    "hello", "john.doe@gmail.com", "8.8.8.8 ", "415-555-2671 ext", "",
])
def test_no_suggestions_when_not_a_national_number(query):
    assert phone_suggestions(query) == []


def test_picking_a_suggestion_gives_a_phone():
    for suggestion in phone_suggestions("4155552671"):
        assert first(suggestion["value"]) == ("phone", suggestion["value"])
        assert phone_suggestions(suggestion["value"]) == []


# ---------------------------------------------------------------------------
# /api/lookup/detect
# ---------------------------------------------------------------------------

def detect_api(client, query, **headers):
    response = client.get("/api/lookup/detect", params={"q": query}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_api_offers_modules_for_a_noise_email(client):
    data = detect_api(client, "jdoe.admin@example.com")
    assert [(c["type"], c["value"], c["label"]) for c in data["candidates"]] == [("email", "jdoe.admin@example.com", "Email")]
    assert data["candidates"][0]["modules"], "an email has modules that look it up"
    assert data["suggestions"] == []


def test_api_reads_private_ip_and_noise_domain(client):
    assert [c["type"] for c in detect_api(client, "192.168.1.5")["candidates"]] == ["ip"]
    assert [c["type"] for c in detect_api(client, "example.org")["candidates"]] == ["domain"]


def test_api_suggests_numbers_for_a_national_phone(client):
    data = detect_api(client, "(415) 555-2671")
    assert "phone" not in [c["type"] for c in data["candidates"]]
    assert data["suggestions"][0]["value"] == "+14155552671"
    assert set(data["suggestions"][0]) == {"type", "value", "display", "region", "country"}


def test_api_puts_the_browsers_country_first(client):
    headers = {"Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7"}
    assert detect_api(client, "0501234567", **headers)["suggestions"][0]["value"] == "+380501234567"
    # languages without a country, and junk, are ignored
    for value in ["en", "*", "en-, -US;q=x, zz-ZZZ", ""]:
        assert detect_api(client, "4155552671", **{"Accept-Language": value})["suggestions"][0]["value"] == "+14155552671"


def test_api_unreadable_query_has_no_candidates(client):
    data = detect_api(client, "@")
    assert data["candidates"] == [] and data["suggestions"] == []


def test_api_needs_a_query(client):
    assert client.get("/api/lookup/detect").status_code == 422
    assert client.get("/api/lookup/detect", params={"q": ""}).status_code == 422
    assert client.get("/api/lookup/detect", params={"q": "x" * 501}).status_code == 422


def test_earlier_lookup_of_a_noise_value_is_found(client, investigation):
    """A lookup of example.com is listed as already done (so a paid one isn't repeated)."""
    from services.investigation_service import investigation_service as service
    service.save_investigation_result(UUID(investigation), "whois", "lookup_whois",
                                      {"kwargs": {"domain": "example.com"}}, {"registrar": "IANA"})
    response = client.get(f"/api/investigations/{investigation}/entities/lookups",
                          params={"type": "domain", "value": "Example.com"})
    assert [lookup["service"] for lookup in response.json()["lookups"]] == ["whois"]


def test_manual_identifiers_keep_noise_values(client, investigation):
    """Identifiers typed into "Add manually" are the user's own: example.com stays."""
    response = client.post(f"/api/investigations/{investigation}/manual", data={
        "title": "From a forum", "text": "seen in a post",
        "identifiers": "jdoe.admin@example.com\n192.168.1.5\nadmin",
    })
    assert response.status_code == 201, response.text
    entities = client.get(f"/api/investigations/{investigation}/entities").json()["entities"]
    keys = {f"{e['type']}:{e['value']}" for e in entities}
    assert {"email:jdoe.admin@example.com", "ip:192.168.1.5", "username:admin"} <= keys
