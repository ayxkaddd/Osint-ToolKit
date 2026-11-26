"""Which domains of an NS lookup are run by the same person or group: the server's copy of
static/js/services/ns_attribution.js (the NS page's "Likely same owner"), so the
investigation graph groups the domains the same way. Keep the two in step."""
import json
import math
import re
from collections.abc import Iterable
from typing import Any, Optional
from urllib.parse import urlparse

REDACTED = re.compile(r"redacted|privacy|private|withheld|not disclosed|protected|proxy|gdpr|masked|anonymi|"
                      r"contact the registrar|statutory|on behalf of|whoisguard", re.I)
GENERIC_TITLES = re.compile(
    r"^(index of|403 forbidden|404 not found|not found|forbidden|just a moment|attention required|welcome to nginx"
    r"|apache2? .*default page|it works|default page|site not found|domain (is )?for sale|this domain|parked"
    r"|coming soon|under construction|account suspended|web server's default page|access denied)", re.I)
TRACKER_LABELS = {
    "google_analytics": "Google Analytics", "google_analytics_ua": "Google Analytics (UA)",
    "google_tag_manager": "Google Tag Manager", "adsense": "AdSense", "yandex_metrika": "Yandex Metrika",
    "facebook_pixel": "Facebook pixel", "hotjar": "Hotjar", "email": "Email on the site",
    "telegram": "Telegram link on the site",
}
EMAIL_SHAPE = re.compile(r"^[^\s@/]+@[^\s@/]+\.[a-z]{2,}$", re.I)


# -- RDAP --

def _vcard(entity: dict) -> dict[str, Any]:
    card = (entity.get("vcardArray") or [None, []])[1] or []
    out: dict[str, Any] = {}
    for row in card:
        if not isinstance(row, list) or len(row) < 4:
            continue
        name, params, _, value = row[:4]
        params = params if isinstance(params, dict) else {}
        if name == "fn":
            out["name"] = value
        elif name == "org":
            out["org"] = " ".join(map(str, value)) if isinstance(value, list) else value
        elif name == "email" and not out.get("email"):
            out["email"] = re.sub(r"^mailto:", "", str(value), flags=re.I)
        elif name == "tel" and not out.get("phone"):
            types = params.get("type") or []
            if "fax" not in (types if isinstance(types, list) else [types]):
                out["phone"] = re.sub(r"^tel:", "", str(value), flags=re.I)
        elif name == "adr":
            out["country"] = params.get("cc") or (value[6] if isinstance(value, list) and len(value) > 6 else "") \
                or out.get("country")
    return out


def parse_rdap(raw: Any) -> Optional[dict[str, Any]]:
    data = raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except ValueError:
            return None
    if not isinstance(data, dict) or (not data.get("ldhName") and not data.get("entities")):
        return None
    events = {e.get("eventAction"): e.get("eventDate") for e in data.get("events") or [] if isinstance(e, dict)}
    out: dict[str, Any] = {"registrar": None, "created": events.get("registration"), "contacts": []}

    def walk(entities):
        for entity in entities or []:
            if not isinstance(entity, dict):
                continue
            roles = entity.get("roles") or []
            fields = _vcard(entity)
            if "registrar" in roles:
                out["registrar"] = fields.get("name") or fields.get("org") or entity.get("handle")
            elif "abuse" in roles:
                pass
            elif any(r in ("registrant", "administrative", "technical", "billing") for r in roles):
                out["contacts"].append({"roles": roles, **fields})
            walk(entity.get("entities"))

    walk(data.get("entities"))
    # a registrar's own phone or email in a redacted contact says nothing about the owner
    registrar_values: set = set()

    def collect(entities):
        for entity in entities or []:
            if not isinstance(entity, dict):
                continue
            if any(r in ("registrar", "abuse") for r in entity.get("roles") or []):
                fields = _vcard(entity)
                registrar_values.update(str(v).lower() for v in (fields.get("email"), fields.get("phone")) if v)
            collect(entity.get("entities"))

    collect(data.get("entities"))

    def real(value) -> bool:
        return bool(value) and not REDACTED.search(str(value)) and str(value).lower() not in registrar_values

    contacts = []
    for c in out["contacts"]:
        contact = {**c, "email": c.get("email") if real(c.get("email")) and EMAIL_SHAPE.match(str(c.get("email")))
                   else None, "phone": c.get("phone") if real(c.get("phone")) else None}
        contact["redacted"] = not (real(c.get("name")) or real(c.get("org")) or contact["email"])
        if contact["redacted"]:
            contact["phone"] = None
        contacts.append(contact)
    out["contacts"] = contacts
    return out


def parse_whois(whois: Any) -> dict[str, Any]:
    """A saved WHOIS answer (ns.whois_analysis) as the NS page reads it."""
    if not isinstance(whois, dict) or whois.get("error"):
        return {"error": True, "contacts": []}     # answered, with nothing in it (as the page counts it)
    rdap = parse_rdap(whois.get("domain_raw_text"))
    if rdap:
        return rdap
    registrant, email = whois.get("registrant"), whois.get("email")
    return {
        "registrar": whois.get("registrar"), "created": whois.get("creation_date"),
        "contacts": [{"roles": ["registrant"], "org": registrant, "email": email,
                      "redacted": bool(REDACTED.search(registrant or ""))}] if registrant or email else [],
    }


# -- signals and groups --

def _host(url: Any) -> Optional[str]:
    try:
        host = urlparse(str(url)).hostname
    except ValueError:
        return None
    return re.sub(r"^www\.", "", host) if host else None


def build_signals(whois: dict[str, Any], web: dict[str, Any]) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}

    def add(kind, label, strength, value, domain, display=None):
        if not value:
            return
        key = f"{kind}\0{str(value).lower()}"
        bucket = buckets.setdefault(key, {"kind": kind, "label": label, "strength": strength,
                                          "value": display or str(value), "domains": set()})
        bucket["domains"].add(domain)

    for domain, w in (whois or {}).items():
        if not w:
            continue
        for c in w.get("contacts") or []:
            if c.get("redacted"):
                continue
            if c.get("email") and not REDACTED.search(c["email"]):
                add("whois_email", "WHOIS contact email", "strong", c["email"], domain)
            if c.get("phone") and not REDACTED.search(c["phone"]):
                add("whois_phone", "WHOIS contact phone", "strong", c["phone"], domain)
            org, name = c.get("org"), c.get("name")
            who = org if org and not REDACTED.search(org) else name if name and not REDACTED.search(name) else None
            if who:
                add("whois_owner", "WHOIS registrant", "strong", who, domain)
        if w.get("registrar") and w.get("created"):
            add("registered_together", "Registered the same day at the same registrar", "medium",
                f"{w['registrar']} · {str(w['created'])[:10]}", domain)
        if w.get("registrar"):
            add("registrar", "Registrar", "weak", w["registrar"], domain)

    for domain, f in (web or {}).items():
        if not isinstance(f, dict):
            continue
        for kind, ids in (f.get("trackers") or {}).items():
            for tracker in ids or []:
                add(f"tracker_{kind}", TRACKER_LABELS.get(kind, kind), "strong", tracker, domain)
        target = _host(f.get("final_url"))
        if target and target not in (domain, f"www.{domain}"):
            add("redirect", "Redirects to the same site", "strong", target, domain)
        cert = f.get("cert") if isinstance(f.get("cert"), dict) else None
        if cert and cert.get("sha256"):
            sans = [str(s).lower().removeprefix("*.") for s in cert.get("sans") or []]
            add("cert", "Same TLS certificate", "cert", cert["sha256"], domain,
                f"{cert.get('subject') or '?'} ({cert.get('issuer') or 'unknown issuer'})")
            bucket = buckets[f"cert\0{cert['sha256'].lower()}"]
            bucket["sans"] = list(dict.fromkeys([*(bucket.get("sans") or []), *sans]))
        if f.get("body_sha256"):
            add("body", "Identical page", "medium", f["body_sha256"], domain,
                f'"{f["title"]}"' if f.get("title") else str(f["body_sha256"])[:16])
        if f.get("favicon"):
            add("favicon", "Same favicon", "medium", f["favicon"], domain, f"mmh3 {f['favicon']}")
        if f.get("title") and not GENERIC_TITLES.search(f["title"]):
            add("title", "Same page title", "medium", f["title"], domain)
        for ip in f.get("ips") or []:
            add("ip", "Same IP address", "weak", ip, domain)
        if f.get("jarm"):
            add("jarm", "Same TLS server config (JARM)", "weak", f["jarm"], domain, str(f["jarm"])[:20] + "…")
        stack = ", ".join(sorted(str(t).split(":")[0] for t in f.get("tech") or []))
        if stack:
            add("tech", "Same technology stack", "weak", stack, domain)

    answered = len(set(web or {}) | {d for d, w in (whois or {}).items() if w}) or 1
    common_at = max(5, math.ceil(answered * 0.4))
    signals = []
    for bucket in buckets.values():
        domains = sorted(bucket["domains"])
        if len(domains) < 2:
            continue
        strength = bucket["strength"]
        if bucket["kind"] == "cert":
            named = [d for d in domains if any(s == d or d.endswith("." + s) for s in bucket.get("sans") or [])]
            strength = "strong" if len(named) >= 2 else "weak"
        signals.append({"kind": bucket["kind"], "label": bucket["label"], "strength": strength,
                        "value": bucket["value"], "domains": domains,
                        "common": strength == "medium" and len(domains) >= common_at})
    order = {"strong": 0, "medium": 1, "weak": 2}
    signals.sort(key=lambda s: (order[s["strength"]], -len(s["domains"])))
    return signals


def clusters(signals: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Domains joined by strong signals, or by medium ones not common to the whole set."""
    linking = [s for s in signals if s["strength"] == "strong" or (s["strength"] == "medium" and not s["common"])]
    parent: dict[str, str] = {}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for s in linking:
        for d in s["domains"]:
            parent.setdefault(d, d)
    for s in linking:
        for d in s["domains"][1:]:
            parent[find(s["domains"][0])] = find(d)
    groups: dict[str, set] = {}
    for d in parent:
        groups.setdefault(find(d), set()).add(d)
    out = []
    for members in groups.values():
        if len(members) < 2:
            continue
        reasons = [s for s in linking if any(d in members for d in s["domains"])]
        strong = sum(1 for r in reasons if r["strength"] == "strong")
        out.append({"domains": sorted(members), "reasons": reasons,
                    "confidence": "high" if strong >= 2 else "likely" if strong == 1 else "possible"})
    rank = {"high": 0, "likely": 1, "possible": 2}
    out.sort(key=lambda g: (rank[g["confidence"]], -len(g["domains"])))
    return out
