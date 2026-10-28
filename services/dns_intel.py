"""What DNS records say about a domain's owner.

Pure parsing helpers used by the DNS recon service: TXT/SPF/DMARC parsing,
site-verification tokens, mail/DNS provider fingerprints, certificate
transparency rows and Team Cymru ASN answers.
"""

import ipaddress
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

HOSTNAME_RE = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}$")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}")

# A token is per account: the same token on two domains means the same owner.
VERIFICATION_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"^google-site-verification=(.+)$", re.I), "Google Search Console"),
    (re.compile(r"^facebook-domain-verification=(.+)$", re.I), "Facebook / Meta Business"),
    (re.compile(r"^MS=(ms\d+)$", re.I), "Microsoft 365"),
    (re.compile(r"^apple-domain-verification=(.+)$", re.I), "Apple"),
    (re.compile(r"^atlassian-domain-verification=(.+)$", re.I), "Atlassian"),
    (re.compile(r"^docusign=(.+)$", re.I), "DocuSign"),
    (re.compile(r"^yandex-verification:\s*(.+)$", re.I), "Yandex Webmaster"),
    (re.compile(r"^mailru-verification:\s*(.+)$", re.I), "Mail.ru"),
    (re.compile(r"^ZOOM_verify_(.+)$", re.I), "Zoom"),
    (re.compile(r"^amazonses:(.+)$", re.I), "Amazon SES"),
    (re.compile(r"^keybase-site-verification=(.+)$", re.I), "Keybase"),
    (re.compile(r"^yahoo-verification-key=(.+)$", re.I), "Yahoo"),
    (re.compile(r"^loaderio=(.+)$", re.I), "loader.io"),
    (re.compile(r"^teamviewer-sso-verification=(.+)$", re.I), "TeamViewer"),
    (re.compile(r"^have-i-been-pwned-verification=(.+)$", re.I), "Have I Been Pwned"),
    (re.compile(r"^(?:stripe|openai|slack|dropbox|notion|canva|miro|pinterest|adobe-idp|globalsign|"
                r"cisco-ci|hubspot-developer|brave-ledger|onetrust|postman|webexdomain|knowbe4|"
                r"citrix|lastpass|zapier|twilio|mongodb-site|whimsical|smartsheet|"
                r"[a-z0-9]+)-(?:site|domain|developer|sso)?-?verification[=:]\s*(.+)$", re.I), ""),
]

SPF_SERVICES = {
    "_spf.google.com": "Google Workspace", "spf.protection.outlook.com": "Microsoft 365",
    "amazonses.com": "Amazon SES", "sendgrid.net": "SendGrid", "mailgun.org": "Mailgun",
    "servers.mcsv.net": "Mailchimp", "mandrillapp.com": "Mailchimp Transactional",
    "_spf.yandex.net": "Yandex 360", "_spf.mail.ru": "Mail.ru / VK WorkSpace", "zoho.com": "Zoho Mail",
    "zoho.eu": "Zoho Mail", "zohomail.com": "Zoho Mail", "protonmail.ch": "Proton Mail",
    "proton.me": "Proton Mail", "mtasv.net": "Postmark", "_spf.salesforce.com": "Salesforce",
    "mail.zendesk.com": "Zendesk", "hubspotemail.net": "HubSpot", "elasticemail.com": "Elastic Email",
    "sendinblue.com": "Brevo", "brevo.com": "Brevo", "mailjet.com": "Mailjet", "mx.ovh.com": "OVH",
    "gandi.net": "Gandi", "messagingengine.com": "Fastmail", "_spf.atlassian.net": "Atlassian",
    "emailsrvr.com": "Rackspace", "secureserver.net": "GoDaddy", "firebasemail.com": "Firebase",
    "unisender.com": "Unisender", "freshdesk.com": "Freshdesk", "helpscoutemail.com": "Help Scout",
    "icloud.com": "iCloud Mail", "sparkpostmail.com": "SparkPost", "mailersend.net": "MailerSend",
    "beget.com": "Beget", "timeweb.ru": "Timeweb", "smtp.yandex.ru": "Yandex 360", "_spf.qq.com": "Tencent",
}

MX_PROVIDERS = {
    "google.com": "Google Workspace", "googlemail.com": "Google Workspace",
    "mail.protection.outlook.com": "Microsoft 365", "outlook.com": "Microsoft 365",
    "yandex.net": "Yandex 360", "yandex.ru": "Yandex 360", "mail.ru": "Mail.ru / VK WorkSpace",
    "zoho.com": "Zoho Mail", "zoho.eu": "Zoho Mail", "protonmail.ch": "Proton Mail",
    "mx.cloudflare.net": "Cloudflare Email Routing", "messagingengine.com": "Fastmail",
    "secureserver.net": "GoDaddy", "mailgun.org": "Mailgun", "pphosted.com": "Proofpoint",
    "mimecast.com": "Mimecast", "icloud.com": "iCloud Mail (custom domain)", "improvmx.com": "ImprovMX",
    "forwardemail.net": "Forward Email", "ovh.net": "OVH", "beget.com": "Beget", "timeweb.ru": "Timeweb",
    "qq.com": "Tencent", "emailsrvr.com": "Rackspace", "migadu.com": "Migadu", "amazonaws.com": "Amazon SES/WorkMail",
}

NS_PROVIDERS = {
    "ns.cloudflare.com": "Cloudflare", "awsdns": "AWS Route 53", "domaincontrol.com": "GoDaddy",
    "googledomains.com": "Google", "ns-cloud": "Google Cloud DNS", "azure-dns": "Azure DNS",
    "registrar-servers.com": "Namecheap", "nic.ru": "RU-CENTER", "reg.ru": "REG.RU",
    "yandex.net": "Yandex", "beget": "Beget", "timeweb": "Timeweb", "digitalocean.com": "DigitalOcean",
    "hetzner": "Hetzner", "ovh.net": "OVH", "vercel-dns.com": "Vercel", "nsone.net": "NS1",
    "dnsimple": "DNSimple", "linode.com": "Linode", "name.com": "Name.com", "dns-parking.com": "Hostinger",
    "dnsmadeeasy": "DNS Made Easy", "ultradns": "UltraDNS", "akam.net": "Akamai",
    "hostgator": "HostGator", "bluehost": "Bluehost", "wixdns.net": "Wix", "squarespacedns": "Squarespace",
    "porkbun.com": "Porkbun", "gandi.net": "Gandi", "netlify": "Netlify", "selectel": "Selectel",
    "constellix": "Constellix", "sprinthost": "SprintHost", "jino.ru": "Jino", "ihc.ru": "IHC", "masterhost": "Masterhost",
}


def match_provider(host: str, table: Dict[str, str]) -> Optional[str]:
    """Dotted needles match as a domain suffix, bare words anywhere in the name."""
    host = (host or "").lower().rstrip(".")
    for needle, name in table.items():
        if host == needle or host.endswith("." + needle) or ("." not in needle and needle in host):
            return name
    return None


def txt_value(raw: str) -> str:
    """dnspython renders TXT as '"part1" "part2"'; long records are split."""
    parts = re.findall(r'"((?:[^"\\]|\\.)*)"', raw or "")
    return "".join(parts) if parts else (raw or "").strip()


def parse_spf(record: str) -> Dict[str, Any]:
    includes, ips, services = [], [], []
    policy = None
    for term in record.split()[1:]:
        t = term.lstrip("+")
        lower = t.lower()
        if lower.startswith(("include:", "redirect=")):
            host = re.split(r"[:=]", t, 1)[1].lower()
            includes.append(host)
            service = match_provider(host, SPF_SERVICES)
            if service and service not in services:
                services.append(service)
        elif lower.startswith(("ip4:", "ip6:")):
            ips.append(t.split(":", 1)[1])
        elif lower.endswith("all"):
            policy = {"-all": "reject others (strict)", "~all": "soft fail others",
                      "?all": "neutral", "+all": "allow anyone (misconfigured)", "all": "allow anyone (misconfigured)"
                      }.get(lower, lower)
    return {"record": record, "includes": includes, "ips": ips, "services": services, "policy": policy}


def parse_dmarc(record: str) -> Dict[str, Any]:
    tags = {}
    for part in record.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            tags[k.strip().lower()] = v.strip()
    emails = []
    for key in ("rua", "ruf"):
        for uri in tags.get(key, "").split(","):
            uri = uri.strip()
            if uri.lower().startswith("mailto:"):
                email = uri[7:].split("!")[0].strip().lower()
                if email and email not in emails:
                    emails.append(email)
    return {"record": record, "policy": tags.get("p"), "report_emails": emails}


def parse_verification(record: str) -> Optional[Dict[str, str]]:
    for pattern, service in VERIFICATION_PATTERNS:
        m = pattern.match(record.strip())
        if m:
            if not service:
                prefix = record.split("-", 1)[0] if "-verification" in record.lower() else record.split("=")[0]
                service = prefix.strip().capitalize()
            return {"service": service, "token": m.group(m.lastindex or 0).strip(), "record": record.strip()}
    return None


def analyze_records(records: Dict[str, List[str]], dmarc_txt: Iterable[str]) -> Dict[str, Any]:
    """Owner intel from the domain's own DNS answers."""
    txt = [txt_value(r) for r in records.get("TXT", [])]
    spf = next((parse_spf(t) for t in txt if t.lower().startswith("v=spf1")), None)
    verifications, other = [], []
    for t in txt:
        if t.lower().startswith("v=spf1"):
            continue
        v = parse_verification(t)
        (verifications.append(v) if v else other.append(t))

    dmarc_records = [txt_value(r) for r in dmarc_txt]
    dmarc = next((parse_dmarc(r) for r in dmarc_records if r.lower().startswith("v=dmarc1")), None)

    def providers(values: List[str], table: Dict[str, str], strip_pref: bool = False) -> List[str]:
        out = []
        for value in values:
            host = value.split()[-1] if strip_pref else value
            name = match_provider(host, table)
            if name and name not in out:
                out.append(name)
        return out

    emails = list(dict.fromkeys(e.lower() for t in other for e in EMAIL_RE.findall(t)))
    soa = (records.get("SOA") or [""])[0].split()
    if len(soa) >= 2 and "." in soa[1]:
        # SOA RNAME: the first unescaped dot is the @ (hostmaster.example.com)
        local, host = (re.split(r"(?<!\\)\.", soa[1].rstrip("."), 1) + [""])[:2]
        local = local.replace("\\.", ".")
        generic = "hostmaster" in local.lower() or "dns" in local.lower() or local.lower() in ("root", "admin", "noc")
        if host and not generic:
            emails.append(f"{local.lower()}@{host.lower()}")

    return {
        "mail_providers": providers(records.get("MX", []), MX_PROVIDERS, strip_pref=True),
        "dns_providers": providers(records.get("NS", []), NS_PROVIDERS),
        "spf": spf,
        "dmarc": dmarc,
        "verifications": verifications,
        "other_txt": other,
        "emails": emails,
    }


def parse_crtsh(rows: List[Dict[str, Any]], domain: str) -> Tuple[Dict[str, Dict[str, Any]], List[str]]:
    """Names (and the rare email) from certificate transparency rows."""
    names: Dict[str, Dict[str, Any]] = {}
    emails: List[str] = []
    for row in rows:
        seen = str(row.get("not_before") or row.get("entry_timestamp") or "")[:10]
        for name in str(row.get("name_value", "")).splitlines():
            name = name.strip().lower()
            if "@" in name:
                if EMAIL_RE.fullmatch(name) and name not in emails:
                    emails.append(name)
                continue
            name = name.lstrip("*.").rstrip(".")
            if not (name == domain or name.endswith("." + domain)) or not HOSTNAME_RE.match(name):
                continue
            entry = names.setdefault(name, {"first_seen": seen, "last_seen": seen, "certs": 0})
            entry["certs"] += 1
            if seen:
                entry["first_seen"] = min(filter(None, [entry["first_seen"], seen]))
                entry["last_seen"] = max(entry["last_seen"] or "", seen)
    return names, emails


def cymru_query_name(ip: str) -> Optional[str]:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return None
    if addr.is_private or addr.is_loopback or addr.is_reserved:
        return None
    if addr.version == 4:
        return ".".join(reversed(ip.split("."))) + ".origin.asn.cymru.com"
    nibbles = addr.reverse_pointer.replace(".ip6.arpa", "")
    return nibbles + ".origin6.asn.cymru.com"


def parse_cymru_origin(txt: str) -> Dict[str, str]:
    # "15169 | 8.8.8.0/24 | US | arin | 2014-03-14"
    parts = [p.strip() for p in txt_value(txt).split("|")]
    keys = ["asn", "prefix", "country", "registry", "allocated"]
    out = dict(zip(keys, parts))
    out["asn"] = (out.get("asn") or "").split()[0] if out.get("asn") else ""
    return out


def parse_cymru_asname(txt: str) -> str:
    # "15169 | US | arin | 2000-03-30 | GOOGLE, US"
    parts = [p.strip() for p in txt_value(txt).split("|")]
    return parts[-1] if len(parts) >= 5 else ""
