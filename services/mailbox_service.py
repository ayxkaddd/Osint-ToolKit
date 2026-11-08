"""Is a username also a mailbox? someuser -> someuser@gmail.com, @outlook.com, @proton.me ...

Each provider is asked the way its own signup or sign-in page asks ("is this name
taken?", "does this account exist?"), or, for Yandex and mail.de, its mail server
whether the mailbox exists (nothing is sent). No password reset or recovery flows:
nothing reaches the owner of the address.

A check that can't tell says so (status "error" and why); an error is never turned
into "not registered".

Most methods are adapted from mailcat (https://github.com/sharsil/mailcat, Apache
License 2.0, copyright the mailcat authors). Gmail asks Google's People API the way
GHunt does (https://github.com/mxrch/GHunt), with the GHunt session saved on this
machine, and only once the operator has allowed it (GMAIL_CHECK_USE_GOOGLE_SESSION).

Run from the command line: python -m services.mailbox_service check NAME [NAME...]
                           python -m services.mailbox_service selftest [KNOWN-NAME...]
"""
import asyncio
import base64
import hashlib
import json
import logging
import random
import re
import string
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

import httpx

from utils.browser_client import BrowserClient, BrowserResponse, RequestError, RequestTimeout
from utils.config import get_setting

logger = logging.getLogger(__name__)

FOUND, NOT_FOUND, ERROR, SKIPPED = "found", "not_found", "error", "skipped"
PROVIDER_TIMEOUT = 25.0  # Proton slows its availability answer down on purpose (~10s)
REQUEST_TIMEOUT = 15.0
MAX_PARALLEL = 16
# Seconds between the per-domain requests of providers that throttle bursts (Mail.ru, Rambler)
BURST_GAP = 0.35

GMAIL_PERMISSION_KEY = "GMAIL_CHECK_USE_GOOGLE_SESSION"
GHUNT_CREDS_KEY = "GHUNT_CREDS_PATH"
# Google Photos' own web API key and origin: the People API answers lookups from that site
GOOGLE_WEB_KEY = "AIzaSyAa2odBewW-sPJu3jMORr0aNedh3YlkiQc"
GOOGLE_WEB_ORIGIN = "https://photos.google.com"
GOOGLE_LOOKUP_URL = "https://people-pa.clients6.google.com/v2/people/lookup"


class CheckError(Exception):
    """The provider's answer doesn't say either way; the message says why."""


@dataclass
class MailboxResult:
    provider: str
    email: str
    status: str
    reason: Optional[str] = None
    aliases: list[str] = field(default_factory=list)  # other addresses of the same account
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v not in (None, [], {})}


@dataclass
class Provider:
    id: str
    name: str
    domains: list[str]
    check: Callable[[str, BrowserClient], Awaitable[list[MailboxResult]]]
    # The names the provider allows (lowercase); others are "not a valid address there"
    local_re: re.Pattern = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
    note: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rand(n: int = 12) -> str:
    return "".join(random.choices(string.ascii_lowercase, k=n))


def _unexpected(resp: BrowserResponse, provider: str = "") -> CheckError:
    """Why an answer can't be read: rate limit, a bot check, or something new."""
    code = resp.status_code
    if code == 429:
        return CheckError("Rate limited (HTTP 429) - try again later")
    head = resp.text[:20000].lower()
    if any(m in head for m in ("cf-chl", "challenge-platform", "just a moment", "captcha", "ddos-guard")):
        return CheckError(f"Blocked by a bot check (HTTP {code})")
    if code in (401, 403):
        return CheckError(f"Access denied (HTTP {code}) - the site blocks automated checks")
    if code >= 500:
        return CheckError(f"The site had an error (HTTP {code})")
    return CheckError(f"Unexpected answer (HTTP {code}){' from ' + provider if provider else ''}")


def _json(resp: BrowserResponse, provider: str = "") -> Any:
    try:
        return json.loads(resp.content or b"null")
    except ValueError:
        raise _unexpected(resp, provider) from None


def _found(provider: str, email: str, **kwargs) -> MailboxResult:
    return MailboxResult(provider, email, FOUND, **kwargs)


def _missing(provider: str, email: str) -> MailboxResult:
    return MailboxResult(provider, email, NOT_FOUND)


async def _each_domain(provider: str, local: str, domains: list[str],
                       one: Callable[[str], Awaitable[bool]], gap: float = 0.0) -> list[MailboxResult]:
    """One answer per domain (separate accounts): an error on one domain stays on that one.
    ``gap`` spaces the requests out for providers that rate-limit bursts."""
    async def run(i: int, domain: str) -> MailboxResult:
        email = f"{local}@{domain}"
        if gap:
            await asyncio.sleep(i * gap)
        try:
            return _found(provider, email) if await one(email) else _missing(provider, email)
        except Exception as e:  # noqa: BLE001
            return MailboxResult(provider, email, ERROR, _reason(e))
    return list(await asyncio.gather(*(run(i, d) for i, d in enumerate(domains))))


def _reason(error: BaseException) -> str:
    if isinstance(error, (asyncio.TimeoutError, RequestTimeout)):
        return "Timeout"
    if isinstance(error, CheckError):
        return str(error)
    if isinstance(error, RequestError):
        return f"Couldn't connect: {error}"
    logger.warning("mailbox check failed: %r", error)
    return "Unexpected error"


def _multipart(fields: dict[str, str]) -> tuple[bytes, str]:
    boundary = f"----mb{uuid.uuid4().hex}"
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n' for k, v in fields.items()]
    return ("".join(parts) + f"--{boundary}--\r\n").encode(), f"multipart/form-data; boundary={boundary}"


# ---------------------------------------------------------------------------
# Mail servers: "RCPT TO" answers whether a mailbox exists; no mail is sent
# ---------------------------------------------------------------------------

_SMTP_NO_USER = re.compile(r"5\.1\.[01]|no such (user|mailbox)|user unknown|does not exist|unknown user|"
                           r"mailbox (not found|unavailable)|invalid (recipient|mailbox)", re.I)


async def smtp_mailbox_exists(email: str, timeout: float = 6.0) -> bool:
    """True / False from the domain's mail server; CheckError when it won't say
    (port 25 blocked, the server refuses us, an answer that isn't about the mailbox)."""
    import dns.asyncresolver
    domain = email.rsplit("@", 1)[1]
    try:
        answers = await dns.asyncresolver.resolve(domain, "MX", lifetime=timeout)
    except Exception:  # noqa: BLE001
        raise CheckError(f"No mail server found for {domain}") from None
    host = str(sorted(answers, key=lambda r: r.preference)[0].exchange).rstrip(".")
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, 25), timeout)
    except (OSError, asyncio.TimeoutError):
        raise CheckError("Port 25 (mail servers) is blocked on this network") from None

    async def reply() -> tuple[int, str]:
        lines = []
        while True:
            line = (await asyncio.wait_for(reader.readline(), timeout)).decode(errors="replace").rstrip()
            lines.append(line[4:])
            if len(line) < 4 or line[3] != "-":
                return int(line[:3]) if line[:3].isdigit() else 0, " ".join(lines)

    async def say(command: str) -> tuple[int, str]:
        writer.write(f"{command}\r\n".encode())
        await writer.drain()
        return await reply()

    try:
        code, text = await reply()
        if code != 220:
            raise CheckError(f"The mail server refused the connection ({code})")
        code, _ = await say("EHLO localhost")
        if code != 250:
            code, _ = await say("HELO localhost")
        code, text = await say("MAIL FROM:<>")
        if code != 250:
            raise CheckError(f"The mail server refused the check ({code}: {text[:80]})")
        code, text = await say(f"RCPT TO:<{email}>")
        try:
            writer.write(b"QUIT\r\n")
            await writer.drain()
        except OSError:
            pass
    except asyncio.TimeoutError:
        raise CheckError("The mail server didn't answer") from None
    finally:
        writer.close()
    if code in (250, 251):
        return True
    if code in (550, 551, 553) and _SMTP_NO_USER.search(text):
        return False
    raise CheckError(f"The mail server answered {code}: {text[:80]}")


# ---------------------------------------------------------------------------
# Gmail: Google's People API, with the operator's GHunt session (opt-in)
# ---------------------------------------------------------------------------

def gmail_permission() -> bool:
    return (get_setting(GMAIL_PERMISSION_KEY) or "").strip().lower() in ("1", "true", "yes", "on")


def ghunt_creds_path() -> Path:
    return Path(get_setting(GHUNT_CREDS_KEY) or Path.home() / ".malfrats" / "ghunt" / "creds.m").expanduser()


def _google_cookies() -> Optional[dict[str, str]]:
    """Cookies of the GHunt session (base64 JSON). The tokens in it are not read."""
    path = ghunt_creds_path()
    if not path.is_file():
        return None
    try:
        cookies = json.loads(base64.b64decode(path.read_text()).decode())["cookies"]
    except Exception:  # noqa: BLE001
        raise CheckError("The GHunt session file can't be read - run: ghunt login") from None
    return {str(k): str(v) for k, v in cookies.items()} if isinstance(cookies, dict) else None


def _sapisidhash(sapisid: str, origin: str, now: Optional[int] = None) -> str:
    ts = str(now if now is not None else int(time.time()))
    return f"{ts}_{hashlib.sha1(f'{ts} {sapisid} {origin}'.encode()).hexdigest()}"


async def google_account(email: str) -> MailboxResult:
    """Whether ``email`` is a Google account. Direct, never through a proxy: the session's
    cookies must not cross a public proxy, and a foreign address on the operator's
    session can set off a Google security alert."""
    name = "Gmail"
    if not gmail_permission():
        return MailboxResult(name, email, SKIPPED, "Needs your permission (uses your Google session)",
                             details={"needs_permission": True})
    cookies = _google_cookies()
    if not cookies:
        return MailboxResult(name, email, SKIPPED, "No GHunt session on this machine - run: ghunt login")
    sapisid = cookies.get("SAPISID")
    if not sapisid:
        return MailboxResult(name, email, SKIPPED, "The GHunt session has no SAPISID cookie - run: ghunt login")
    headers = {"X-Goog-Api-Key": GOOGLE_WEB_KEY, "Origin": GOOGLE_WEB_ORIGIN, "Referer": GOOGLE_WEB_ORIGIN + "/",
               "Authorization": f"SAPISIDHASH {_sapisidhash(sapisid, GOOGLE_WEB_ORIGIN)}"}
    params = {"id": email, "type": "EMAIL", "matchType": "EXACT",
              "requestMask.includeField.paths": "person.metadata"}
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, trust_env=False, cookies=cookies) as client:
        r = await client.get(GOOGLE_LOOKUP_URL, params=params, headers=headers)
    if r.status_code in (401, 403):
        raise CheckError("Google refused the session (expired?) - run: ghunt login")
    if r.status_code == 429:
        raise CheckError("Rate limited by Google - try again later")
    if r.status_code != 200:
        raise CheckError(f"Unexpected answer from Google (HTTP {r.status_code})")
    try:
        data = r.json() if r.content.strip() else {}
    except ValueError:
        raise CheckError("Unexpected answer from Google") from None
    person = next(iter((data.get("people") or {}).values()), None) if isinstance(data, dict) else None
    if not person:
        return _missing(name, email)
    for source in person.get("metadata", {}).get("identityInfo", {}).get("sourceIds", []):
        if source.get("container") == "PROFILE":
            return _found(name, email, details={"gaia_id": source.get("id") or person.get("personId")})
    # Known only from the operator's own contacts: not a Google account
    return _missing(name, email)


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

MS_DOMAINS = ["outlook.com", "hotmail.com", "live.com", "msn.com"]


async def check_microsoft(local: str, http: BrowserClient) -> list[MailboxResult]:
    # IfExistsResult: 0/5/6 a Microsoft account, 1 none; ThrottleStatus: answers can't be trusted
    async def one(email: str) -> bool:
        r = await http.request("POST", "https://login.microsoftonline.com/common/GetCredentialType",
                               json={"Username": email, "isOtherIdpSupported": "true"},
                               headers={"Origin": "https://login.microsoftonline.com",
                                        "Referer": "https://login.microsoftonline.com/"})
        d = _json(r, "Microsoft")
        if not isinstance(d, dict) or r.status_code != 200:
            raise _unexpected(r, "Microsoft")
        if d.get("ThrottleStatus") not in (0, None):
            raise CheckError("Rate limited by Microsoft - try again later")
        if d.get("IfExistsResult") in (0, 5, 6):
            return True
        if d.get("IfExistsResult") == 1:
            return False
        raise CheckError(f"Unexpected answer from Microsoft (IfExistsResult {d.get('IfExistsResult')})")
    return await _each_domain("Microsoft", local, MS_DOMAINS, one)


async def check_gmail(local: str, http: BrowserClient) -> list[MailboxResult]:
    return [await google_account(f"{local}@gmail.com")]


PROTON_ALIASES = ["protonmail.com", "pm.me", "protonmail.ch"]


async def check_proton(local: str, http: BrowserClient) -> list[MailboxResult]:
    # Proton no longer tells: since late 2026 its signup check answers "already used" and
    # its key server returns a key for any name, made-up ones included. Gravatar can still
    # prove an address (below).
    return [MailboxResult("Proton", f"{local}@proton.me", SKIPPED, "Proton no longer reveals whether an address exists",
                          details={"gravatar_only": True})]


MAILRU_DOMAINS = ["mail.ru", "bk.ru", "inbox.ru", "list.ru", "internet.ru"]


async def check_mailru(local: str, http: BrowserClient) -> list[MailboxResult]:
    async def one(email: str) -> bool:
        r = await http.request("POST", "https://account.mail.ru/api/v1/user/exists", data={"email": email})
        d = _json(r, "Mail.ru")
        body = d.get("body") if isinstance(d, dict) else None
        if r.status_code != 200 or not isinstance(body, dict) or "exists" not in body:
            raise _unexpected(r, "Mail.ru")
        return bool(body["exists"])
    return await _each_domain("Mail.ru", local, MAILRU_DOMAINS, one, gap=BURST_GAP)


YANDEX_ALIASES = ["yandex.com", "ya.ru", "yandex.by", "yandex.kz", "yandex.ua"]


async def check_yandex(local: str, http: BrowserClient) -> list[MailboxResult]:
    email = f"{local}@yandex.ru"
    if await smtp_mailbox_exists(email):
        return [_found("Yandex", email, aliases=[f"{local}@{a}" for a in YANDEX_ALIASES])]
    return [_missing("Yandex", email)]


async def check_mailde(local: str, http: BrowserClient) -> list[MailboxResult]:
    email = f"{local}@mail.de"
    return [_found("mail.de", email) if await smtp_mailbox_exists(email) else _missing("mail.de", email)]


RAMBLER_DOMAINS = ["rambler.ru", "lenta.ru", "autorambler.ru", "myrambler.ru", "ro.ru", "rambler.ua"]


async def check_rambler(local: str, http: BrowserClient) -> list[MailboxResult]:
    async def one(email: str) -> bool:
        realm = email.split("@", 1)[1]
        r = await http.request("POST", "https://id.rambler.ru/jsonrpc",
                               json={"method": "Rambler::Id::login_available",
                                     "params": [{"username": local, "realm": realm}], "rpc": "2.0"},
                               headers={"Origin": "https://id.rambler.ru", "X-Client-Request-Id": _rand(20)})
        d = _json(r, "Rambler")
        result = d.get("result") if isinstance(d, dict) else None
        if r.status_code != 200 or not isinstance(result, dict):
            raise _unexpected(r, "Rambler")
        if (result.get("profile") or {}).get("status") == "exist":
            return True
        # A free name comes back as an error: {"errno": -2000, "strerror": "user not exist"}
        error = result.get("error") or {}
        if error.get("errno") == -2000 or "not exist" in str(error.get("strerror", "")).lower():
            return False
        raise CheckError(f"Unexpected answer from Rambler ({str(error.get('strerror') or result)[:80]})")
    # Rambler throttles bursts ("LoginAvailCheck is overflowed"): space the six realms out
    return await _each_domain("Rambler", local, RAMBLER_DOMAINS, one, gap=BURST_GAP)


_INPUT_TAG = re.compile(r"<input\b[^>]*>")
_INPUT_ATTR = re.compile(r'\b(name|value)="([^"]*)"')


def _signup_tokens(html: str) -> dict[str, str]:
    tokens = {}
    for tag in _INPUT_TAG.finditer(html):
        attrs = dict(_INPUT_ATTR.findall(tag.group(0)))
        if attrs.get("name") in ("crumb", "acrumb", "sessionIndex") and "value" in attrs:
            tokens[attrs["name"]] = attrs["value"]
    return tokens


async def _oath_signup(local: str, provider: str, host: str, domain: str) -> list[MailboxResult]:
    """Yahoo and AOL share one signup: fresh tokens from the signup page, then "is this ID free?"."""
    email = f"{local}@{domain}"
    signup = f"https://{host}/account/create"
    async with BrowserClient(timeout=REQUEST_TIMEOUT, sticky=True) as sticky:
        page = await sticky.request("GET", signup)
        tokens = _signup_tokens(page.text)
        if page.status_code != 200 or len(tokens) < 3:
            raise _unexpected(page, provider)
        r = await sticky.request(
            "POST", f"https://{host}/account/create/validate?validateField=userId",
            data={**tokens, "specId": "yidregsimplified", "context": "REGISTRATION", "attrSetIndex": "0",
                  "tos0": "oath_freereg|us|en-US", "lastName": "r", "yidDomain": domain, "userId": local},
            headers={"Origin": f"https://{host}", "Referer": signup, "X-Requested-With": "XMLHttpRequest"})
    d = _json(r, provider)
    fields = d.get("fields") if isinstance(d, dict) else None
    if r.status_code != 200 or not isinstance(fields, dict):
        raise _unexpected(r, provider)
    error = ((fields.get("userId") or {}).get("error") or {}).get("id")
    if error in ("IDENTIFIER_EXISTS", "IDENTIFIER_NOT_AVAILABLE"):
        return [_found(provider, email)]
    if not error:
        return [_missing(provider, email)]
    # RESERVED_WORD_PRESENT, LENGTH_TOO_SHORT...: the name can't exist there, for other reasons
    return [MailboxResult(provider, email, SKIPPED, f"Not a valid {provider} ID ({error.replace('_', ' ').lower()})")]


async def check_yahoo(local: str, http: BrowserClient) -> list[MailboxResult]:
    return await _oath_signup(local, "Yahoo", "login.yahoo.com", "yahoo.com")


async def check_aol(local: str, http: BrowserClient) -> list[MailboxResult]:
    return await _oath_signup(local, "AOL", "login.aol.com", "aol.com")


async def check_zoho(local: str, http: BrowserClient) -> list[MailboxResult]:
    email = f"{local}@zohomail.com"
    r = await http.request("POST", "https://accounts.zoho.com/accounts/validate/register.ac",
                           data={"username": local, "servicename": "VirtualOffice", "serviceurl": "/"},
                           headers={"Origin": "https://www.zoho.com", "Referer": "https://www.zoho.com/"})
    d = _json(r, "Zoho")
    if r.status_code != 200 or not isinstance(d, dict):
        raise _unexpected(r, "Zoho")
    error = str((d.get("error") or {}).get("username", "")) if isinstance(d.get("error"), dict) else ""
    if "taken" in error.lower() or "already registered" in error.lower():
        return [_found("Zoho", email)]
    if not error:
        return [_missing("Zoho", email)]
    return [MailboxResult("Zoho", email, SKIPPED, f"Zoho: {error[:80]}")]


async def check_ukrnet(local: str, http: BrowserClient) -> list[MailboxResult]:
    email = f"{local}@ukr.net"
    # Often unreachable from outside Ukraine: give up sooner than the other checks
    async with BrowserClient(timeout=8, connect_timeout=5, sticky=True) as sticky:
        page = await sticky.request("GET", "https://accounts.ukr.net/registration")
        if page.status_code != 200:
            raise _unexpected(page, "Ukr.net")
        r = await sticky.request("POST", "https://accounts.ukr.net/api/v1/registration/reserve_login",
                                 json={"login": local})
    d = _json(r, "Ukr.net")
    if r.status_code != 200 or not isinstance(d, dict) or "available" not in d:
        raise _unexpected(r, "Ukr.net")
    return [_missing("Ukr.net", email) if d["available"] else _found("Ukr.net", email)]


async def check_posteo(local: str, http: BrowserClient) -> list[MailboxResult]:
    email = f"{local}@posteo.net"
    r = await http.request("GET", f"https://posteo.de/users/new/check_username?user%5Busername%5D={quote(local)}",
                           headers={"Referer": "https://posteo.de/en/signup", "X-Requested-With": "XMLHttpRequest"})
    answer = r.text.strip().lower()
    if r.status_code == 200 and answer == "false":
        return [_found("Posteo", email, details={"note": "also reachable at ~50 Posteo alias domains"})]
    if r.status_code == 200 and answer == "true":
        return [_missing("Posteo", email)]
    raise _unexpected(r, "Posteo")


async def check_runbox(local: str, http: BrowserClient) -> list[MailboxResult]:
    # The signup page's own "is this username available?" (one username for every Runbox domain)
    email = f"{local}@runbox.com"
    r = await http.request("GET", "https://runbox.com/rest/v1/signup/username_available"
                           f"?username={quote(local)}&domainType=runbox&runboxDomain=runbox.com&userDomain=",
                           headers={"Referer": "https://runbox.com/app/signup?runbox7=1"})
    d = _json(r, "Runbox")
    result = d.get("result") if isinstance(d, dict) else None
    if r.status_code != 200 or not isinstance(result, dict) or "available" not in result:
        raise _unexpected(r, "Runbox")
    if result["available"]:
        return [_missing("Runbox", email)]
    if result.get("reason") in (None, "username_taken"):
        return [_found("Runbox", email, details={"note": "also reachable at the other Runbox domains"})]
    return [MailboxResult("Runbox", email, SKIPPED, f"Runbox: {str(result['reason']).replace('_', ' ')}")]


async def check_startmail(local: str, http: BrowserClient) -> list[MailboxResult]:
    email = f"{local}@startmail.com"
    r = await http.request("GET", f"https://mail.startmail.com/api/AvailableAddresses/{quote(local)}%40startmail.com",
                           headers={"X-Requested-With": "1.94.0"})
    # Taken: 404 with an XML error; free: 200 with an empty JSON answer. Anything else (a bot
    # check page, a new site) can't be read
    kind = r.headers.get("content-type", "")
    if r.status_code == 404 and "xml" in kind and "<error>" in r.text:
        return [_found("StartMail", email)]
    if r.status_code == 200 and "json" in kind and r.text.strip() in ("", "{}", "[]", "null"):
        return [_missing("StartMail", email)]
    raise _unexpected(r, "StartMail")


async def _check_address_availability(local: str, http: BrowserClient, provider: str, site: str,
                                      referer: str, domains: list[str]) -> list[MailboxResult]:
    """Eclipso and Firemail (same software): <available>0</available> means taken - but also
    "contains a word we don't allow" (admin, mail, test...). A made-up name that contains
    the username tells them apart: if it is "taken" too, no answer can be trusted."""
    async def available(address: str) -> bool:
        r = await http.request("GET", f"https://{site}/index.php?action=checkAddressAvailability&address={quote(address)}",
                               headers={"Referer": referer, "X-Requested-With": "XMLHttpRequest"})
        if r.status_code == 200 and ">0<" in r.text:
            return False
        if r.status_code == 200 and ">1<" in r.text:
            return True
        raise _unexpected(r, provider)
    if not await available(f"zzqx{local}xqzz@{domains[0]}"):
        return [MailboxResult(provider, f"{local}@{d}", SKIPPED, f"{provider} doesn't allow this name")
                for d in domains]

    async def taken(email: str) -> bool:
        return not await available(email)
    return await _each_domain(provider, local, domains, taken)


async def check_eclipso(local: str, http: BrowserClient) -> list[MailboxResult]:
    return await _check_address_availability(local, http, "Eclipso", "www.eclipso.eu",
                                             "https://www.eclipso.eu/signup/tariff-5",
                                             ["eclipso.eu", "eclipso.de", "eclipso.email"])


async def check_firemail(local: str, http: BrowserClient) -> list[MailboxResult]:
    return await _check_address_availability(local, http, "Firemail", "firemail.de",
                                             "https://firemail.de/E-Mail-Adresse-anmelden",
                                             ["firemail.de", "firemail.at", "firemail.eu"])


async def check_vivaldi(local: str, http: BrowserClient) -> list[MailboxResult]:
    email = f"{local}@vivaldi.net"
    r = await http.request("POST", "https://login.vivaldi.net/profile/validateField",
                           data={"field": "username", "value": local},
                           headers={"Origin": "https://login.vivaldi.net",
                                    "Referer": "https://login.vivaldi.net/profile/id/signup"})
    d = _json(r, "Vivaldi")
    if not isinstance(d, dict):
        raise _unexpected(r, "Vivaldi")
    error = str(d.get("error") or "")
    if "user exists" in error.lower():
        return [_found("Vivaldi", email)]
    if not error and r.status_code == 200:
        return [_missing("Vivaldi", email)]
    if error:
        return [MailboxResult("Vivaldi", email, SKIPPED, f"Vivaldi: {error[:80]}")]
    raise _unexpected(r, "Vivaldi")


async def check_mailum(local: str, http: BrowserClient) -> list[MailboxResult]:
    async def one(email: str) -> bool:
        name, domain = email.split("@", 1)
        r = await http.request("POST", "https://mailum.com/api/checkEmailExist4RegistrationV3",
                               content=f"email={quote(name)}&domain=%40{domain}",
                               headers={"Referer": "https://mailum.com/mailbox/",
                                        "Content-Type": "application/x-www-form-urlencoded"})
        answer = r.text.strip().lower()
        if r.status_code == 200 and answer in ("true", "false"):
            return answer == "false"  # "false": the address can't be registered - it exists
        raise _unexpected(r, "Mailum")
    return await _each_domain("Mailum", local, ["mailum.com", "cyberfear.com"], one)


async def check_duck(local: str, http: BrowserClient) -> list[MailboxResult]:
    email = f"{local}@duck.com"
    body, content_type = _multipart({"code": "01337", "user": local, "email": "mail@example.com"})
    r = await http.request("POST", "https://quack.duckduckgo.com/api/auth/signup", content=body,
                           headers={"Content-Type": content_type, "Origin": "https://duckduckgo.com",
                                    "Referer": "https://duckduckgo.com/"})
    if "unavailable_username" in r.text:
        return [_found("DuckDuckGo", email)]
    d = _json(r, "DuckDuckGo")
    # Any other refusal (the made-up invite code, the address) means the name itself was fine
    if isinstance(d, dict) and d.get("error") and d.get("error") != "unavailable_username":
        return [_missing("DuckDuckGo", email)]
    raise _unexpected(r, "DuckDuckGo")


async def check_icloud(local: str, http: BrowserClient) -> list[MailboxResult]:
    # Apple has no check that doesn't involve its recovery flow: only Gravatar can tell (below)
    return [MailboxResult("iCloud", f"{local}@icloud.com", SKIPPED, "Apple has no silent check",
                          details={"gravatar_only": True})]


_GENERIC = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
PROVIDERS: list[Provider] = [
    Provider("gmail", "Gmail", ["gmail.com"], check_gmail,
             re.compile(r"[a-z0-9][a-z0-9.]{4,28}[a-z0-9]"),
             note="Google People API with your GHunt session, once you allow it"),
    Provider("microsoft", "Microsoft", MS_DOMAINS, check_microsoft, re.compile(r"[a-z][a-z0-9._-]{0,63}")),
    Provider("yahoo", "Yahoo", ["yahoo.com"], check_yahoo, re.compile(r"[a-z][a-z0-9._]{3,31}")),
    Provider("aol", "AOL", ["aol.com"], check_aol, re.compile(r"[a-z][a-z0-9._]{3,31}")),
    Provider("proton", "Proton", ["proton.me", *PROTON_ALIASES], check_proton, re.compile(r"[a-z0-9][a-z0-9._-]{0,39}"),
             note="Gravatar only: Proton hides whether an address exists"),
    Provider("zoho", "Zoho", ["zohomail.com"], check_zoho, _GENERIC),
    Provider("icloud", "iCloud", ["icloud.com"], check_icloud, _GENERIC),
    Provider("mailru", "Mail.ru", MAILRU_DOMAINS, check_mailru, _GENERIC),
    Provider("yandex", "Yandex", ["yandex.ru", *YANDEX_ALIASES], check_yandex,
             re.compile(r"[a-z][a-z0-9.-]{0,29}"), note="the mail server (port 25)"),
    Provider("rambler", "Rambler", RAMBLER_DOMAINS, check_rambler, _GENERIC),
    Provider("ukrnet", "Ukr.net", ["ukr.net"], check_ukrnet, _GENERIC),
    Provider("posteo", "Posteo", ["posteo.net"], check_posteo, _GENERIC),
    Provider("runbox", "Runbox", ["runbox.com"], check_runbox, _GENERIC),
    Provider("startmail", "StartMail", ["startmail.com"], check_startmail, _GENERIC),
    Provider("firemail", "Firemail", ["firemail.de", "firemail.at", "firemail.eu"], check_firemail, _GENERIC),
    Provider("eclipso", "Eclipso", ["eclipso.eu", "eclipso.de", "eclipso.email"], check_eclipso, _GENERIC),
    Provider("mailde", "mail.de", ["mail.de"], check_mailde, _GENERIC, note="the mail server (port 25)"),
    Provider("vivaldi", "Vivaldi", ["vivaldi.net"], check_vivaldi, _GENERIC),
    Provider("mailum", "Mailum", ["mailum.com", "cyberfear.com"], check_mailum, _GENERIC),
    Provider("duck", "DuckDuckGo", ["duck.com"], check_duck, _GENERIC),
]
PROVIDERS_BY_ID = {p.id: p for p in PROVIDERS}


# ---------------------------------------------------------------------------
# Gravatar: a profile proves the address exists, and adds a name and a picture
# ---------------------------------------------------------------------------

async def gravatar(email: str, http: BrowserClient) -> Optional[dict[str, Any]]:
    digest = hashlib.md5(email.strip().lower().encode()).hexdigest()
    key = get_setting("GRAVATAR_API_KEY")
    try:
        r = await http.request("GET", f"https://api.gravatar.com/v3/profiles/{digest}",
                               headers={"Authorization": f"Bearer {key}"} if key else None)
        p = json.loads(r.content) if r.status_code == 200 else None
    except (RequestError, ValueError):
        return None
    if not isinstance(p, dict):
        return None
    info = {"name": p.get("display_name"), "picture": p.get("avatar_url"), "gravatar": p.get("profile_url"),
            "location": p.get("location")}
    return {k: v for k, v in info.items() if v}


# ---------------------------------------------------------------------------
# Running the checks
# ---------------------------------------------------------------------------

async def _run_provider(provider: Provider, local: str, http: BrowserClient) -> list[MailboxResult]:
    if not provider.local_re.fullmatch(local):
        return [MailboxResult(provider.name, f"{local}@{provider.domains[0]}", SKIPPED,
                              f"Not a valid {provider.name} address")]
    try:
        results = await asyncio.wait_for(provider.check(local, http), PROVIDER_TIMEOUT)
    except Exception as e:  # noqa: BLE001 - one provider failing never stops the others
        return [MailboxResult(provider.name, f"{local}@{provider.domains[0]}", ERROR, _reason(e))]
    for result in results:
        lookup = result.status == FOUND or result.details.get("gravatar_only")
        profile = await gravatar(result.email, http) if lookup else None
        if profile:
            result.details.update(profile)
            if result.status == SKIPPED:  # iCloud: Gravatar is the only proof there is
                result.status, result.reason = FOUND, "Has a Gravatar profile"
        result.details.pop("gravatar_only", None)
    return results


async def check_mailboxes(username: str, provider_ids: Optional[list[str]] = None) -> AsyncIterator[MailboxResult]:
    """Results as each provider answers (all providers at once)."""
    local = username.strip().lstrip("@").lower()
    providers = [PROVIDERS_BY_ID[i] for i in provider_ids or [] if i in PROVIDERS_BY_ID] or PROVIDERS
    limit = asyncio.Semaphore(MAX_PARALLEL)
    queue: asyncio.Queue = asyncio.Queue()
    async with BrowserClient(timeout=REQUEST_TIMEOUT, max_clients=MAX_PARALLEL * 2) as http:
        async def run(provider: Provider) -> None:
            async with limit:
                for result in await _run_provider(provider, local, http):
                    await queue.put(result)

        tasks = [asyncio.create_task(run(p)) for p in providers]
        done = asyncio.gather(*tasks)
        try:
            while not (done.done() and queue.empty()):
                try:
                    yield await asyncio.wait_for(queue.get(), 0.25)
                except asyncio.TimeoutError:
                    continue
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


# ---------------------------------------------------------------------------
# Command line: check names, and the self-test that spots broken providers
# ---------------------------------------------------------------------------

async def _print_checks(names: list[str]) -> dict[str, list[MailboxResult]]:
    out: dict[str, list[MailboxResult]] = {}
    for name in names:
        start = time.monotonic()
        out[name] = [r async for r in check_mailboxes(name)]
        print(f"\n{name} ({time.monotonic() - start:.1f}s)")
        for r in sorted(out[name], key=lambda r: (r.provider, r.email)):
            print(f"  {r.status:10} {r.email:34} {r.reason or ''} {r.details or ''}")
    return out


async def _selftest(known: list[str]) -> int:
    """A made-up name must be "not registered" everywhere it can be checked; the known
    names (taken almost everywhere, e.g. "john") must come back registered."""
    made_up = _rand(12)
    results = await _print_checks([made_up, *known])
    broken = sorted({r.provider for r in results[made_up] if r.status == FOUND})
    print("\nmade-up name reported as registered (broken check):", ", ".join(broken) or "none")
    for name in known:
        missing = sorted({r.provider for r in results[name] if r.status == NOT_FOUND})
        print(f'"{name}" reported as not registered (check those):', ", ".join(missing) or "none")
    return 1 if broken else 0


if __name__ == "__main__":
    import sys
    from utils.config import load_env
    load_env()
    command, *args = sys.argv[1:] or ["selftest"]
    if command == "check" and args:
        asyncio.run(_print_checks(args))
    elif command == "selftest":
        raise SystemExit(asyncio.run(_selftest(args)))
    else:
        print(__doc__)
