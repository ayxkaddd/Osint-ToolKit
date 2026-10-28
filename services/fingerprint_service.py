"""Web fingerprints of many domains (httpx-toolkit), to tell which share an owner.

One JSON line per domain from httpx: title, status, redirects, technologies,
server, IPs/ASN/CDN, body and favicon hashes, JARM, TLS certificate, and IDs
embedded in the page (analytics/ads/pixels, contact emails, Telegram links).
"""

import asyncio
import json
import os
import re
import tempfile
from typing import Any, AsyncGenerator, Dict, List

from utils.config import get_setting

# Page IDs that are set per account: a shared one is close to proof of a shared owner.
# httpx (Go RE2) returns the full match; the Python pattern pulls out the ID.
TRACKERS = {
    "google_analytics": ("Google Analytics", r"G-[A-Z0-9]{8,12}", r"G-[A-Z0-9]{8,12}"),
    "google_analytics_ua": ("Google Analytics (UA)", r"UA-[0-9]{4,10}-[0-9]{1,4}", r"UA-[0-9]{4,10}"),
    "google_tag_manager": ("Google Tag Manager", r"GTM-[A-Z0-9]{5,8}", r"GTM-[A-Z0-9]{5,8}"),
    "adsense": ("Google AdSense", r"pub-[0-9]{14,20}", r"pub-[0-9]{14,20}"),
    "yandex_metrika": ("Yandex Metrika", r"(?:ym\(|mc\.yandex\.ru/watch/|yaCounter)[0-9]{5,10}", r"[0-9]{5,10}"),
    "facebook_pixel": ("Facebook pixel", r"fbq\(['\"]init['\"],\s*['\"][0-9]{10,20}", r"[0-9]{10,20}"),
    "hotjar": ("Hotjar", r"hjid:\s*[0-9]{5,10}", r"[0-9]{5,10}"),
    "email": ("Email on page", r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,12}", None),
    "telegram": ("Telegram link", r"(?:t\.me|telegram\.me)/[A-Za-z0-9_+]{4,40}", None),
}
NOISE_EMAIL = re.compile(r"\.(png|jpe?g|gif|svg|webp|css|js)$|example\.|sentry|wixpress|@2x|@3x|u00", re.I)

MAX_DOMAINS = 1000


class FingerprintError(Exception):
    pass


def _ids(kind: str, matches: List[str]) -> List[str]:
    _, _, id_pattern = TRACKERS[kind]
    out: List[str] = []
    for match in matches:
        if kind == "email":
            value = match.lower()
            if NOISE_EMAIL.search(value):
                continue
        elif kind == "telegram":
            value = "t.me/" + match.split("/", 1)[1].rstrip("/").lower()
            if value.split("/")[1] in ("share", "joinchat", "s", "iv", "proxy", "addstickers"):
                continue
        else:
            found = re.search(id_pattern, match)
            value = found.group(0) if found else None
        if value and value not in out:
            out.append(value)
    return out[:20]


def normalize(line: Dict[str, Any]) -> Dict[str, Any]:
    """httpx JSON line -> compact fingerprint."""
    extracts = line.get("extracts") or {}
    trackers: Dict[str, List[str]] = {}
    for kind, (_, go_pattern, _) in TRACKERS.items():
        ids = _ids(kind, extracts.get(go_pattern) or [])
        if ids:
            trackers[kind] = ids
    tls = line.get("tls") or {}
    hashes = line.get("hash") or {}
    return {
        "domain": (line.get("input") or "").lower(),
        "url": line.get("url"),
        "final_url": line.get("final_url") or line.get("url"),
        "status": line.get("status_code"),
        "title": (line.get("title") or "").strip() or None,
        "server": line.get("webserver"),
        "tech": line.get("tech") or [],
        "ips": line.get("a") or [],
        "cname": line.get("cname") or [],
        "asn": (line.get("asn") or {}).get("as_name") if isinstance(line.get("asn"), dict) else None,
        "cdn": line.get("cdn_name"),
        "content_length": line.get("content_length"),
        "body_sha256": hashes.get("body_sha256"),
        "favicon": line.get("favicon"),
        "jarm": line.get("jarm_hash") if line.get("jarm_hash") and set(line["jarm_hash"]) != {"0"} else None,
        "cert": {
            "sha256": (tls.get("fingerprint_hash") or {}).get("sha256"),
            "subject": tls.get("subject_cn"),
            "issuer": tls.get("issuer_cn") or ", ".join(tls.get("issuer_org") or []),
            "sans": (tls.get("subject_an") or [])[:50],
            "not_before": tls.get("not_before"),
        } if tls.get("probe_status") else None,
        "trackers": trackers,
    }


async def fingerprint_domains(domains: List[str]) -> AsyncGenerator[Dict[str, Any], None]:
    """Yields {"type": "domain", ...} per answering domain, then {"type": "complete"}."""
    domains = list(dict.fromkeys(d.strip().lower() for d in domains if d.strip()))[:MAX_DOMAINS]
    binary = get_setting("HTTPX_PATH", "httpx-toolkit") or "httpx-toolkit"
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write("\n".join(domains))
        list_file = f.name
    cmd = [binary, "-l", list_file, "-json", "-silent", "-no-color",
           "-title", "-status-code", "-content-length", "-web-server", "-ip", "-cname", "-asn",
           "-tech-detect", "-hash", "sha256", "-favicon", "-jarm", "-tls-grab",
           "-follow-redirects", "-random-agent", "-timeout", "12", "-retries", "1", "-threads", "40",
           "-rstr", "2000000"]
    for _, go_pattern, _ in TRACKERS.values():
        cmd += ["-er", go_pattern]

    try:
        proc = await asyncio.create_subprocess_exec(
            # httpx reads targets from stdin when it isn't a terminal: give it nothing
            *cmd, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, limit=32 * 1024 * 1024)
    except FileNotFoundError as e:
        os.unlink(list_file)
        raise FingerprintError(f"httpx-toolkit is not installed ({binary}) - set HTTPX_PATH in Settings") from e

    seen = set()
    try:
        assert proc.stdout is not None
        while True:
            try:
                raw = await asyncio.wait_for(proc.stdout.readline(), timeout=900)
            except asyncio.TimeoutError:
                break
            if not raw:
                break
            try:
                line = json.loads(raw)
            except ValueError:
                continue
            if line.get("failed"):
                continue
            fp = normalize(line)
            if not fp["domain"] or fp["domain"] in seen:
                continue
            seen.add(fp["domain"])
            yield {"type": "domain", "domain": fp["domain"], "fingerprint": fp,
                   "done": len(seen), "total": len(domains)}
    finally:
        if proc.returncode is None:
            proc.kill()
        await proc.wait()
        os.unlink(list_file)
    yield {"type": "complete", "total": len(domains), "answered": len(seen),
           "no_response": sorted(set(domains) - seen)}
