# OSINT Toolkit

A self-hosted web workspace for OSINT investigations. Built with FastAPI and TailwindCSS: every lookup is saved into an investigation, identifiers found in results become one-click pivots into the other modules, and findings, notes and reports live in one place.

## Preview

![image](https://github.com/user-attachments/assets/faf405e4-f0c8-43ba-95cf-bcea0469bcfc)


## Features

### Investigations
- **Investigations**: every lookup is saved to the active investigation, follow-up lookups are grouped under the result they came from
- **Pivots**: emails, phones, usernames, domains, IPs and Telegram IDs found in any result can be sent to the matching modules in one click
- **Universal lookup**: paste an email, phone, @user, domain or IP in the top bar and pick which modules to run
- **Triage, notes and reports**: mark results as confirmed or important, keep Markdown notes, export a report of the findings
- **Dashboard and settings**: each module shows whether it is ready and what it costs; API keys and tool paths are set in the browser

### Modules
- **Username Search**: checks ~700 sites (WhatsMyName list) for an account, streams results live, re-checks the sites that errored
- **OSINT Industries**: accounts registered to an email, phone or username
- **GHunt**: the Google account behind an email or Gaia ID
- **GitHub Analysis (GitFive)**: real emails and names from commits, linked accounts and SSH keys
- **Funstat**: Telegram users and groups - name history, groups, messages with full-size media, members, the public t.me avatar and bio
- **VK Profile History**: earlier names, photos and details of a VK profile
- **Face Search**: VK profiles with a similar face
- **Cavalier (Hudson Rock)**: infostealer infections that leaked logins for an email or username
- **Phone Lookup**: offline number analysis plus a paid HLR network lookup
- **Web Search**: search-engine dorks for a username, name, email or phone (optionally run through SerpAPI)
- **DNS Recon**: subdomains (crt.sh, subfinder, SecurityTrails, VirusTotal), mail/DNS/hosting providers, SPF/DMARC, verification tokens, ASN hosting and DNS history
- **WHOIS History**: every archived WHOIS record of a domain - free preview of how many exist, then contacts, registrar/name server periods and a change log
- **Shared NS Lookup**: domains on the same name server pair, then parsed WHOIS and an httpx web fingerprint of each to group the domains most likely run by the same owner
- **IP Lookup**: location, network owner, reverse DNS, abuse reports and exposed services
- **External Resources**: curated list of useful OSINT tools and websites

## Installation

1. Clone the repository:
```bash
git clone https://github.com/ayxkaddd/Osint-ToolKit
cd Osint-ToolKit
```

2. Create and activate a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install the dependencies:
```bash
pip install -r requirements.txt
```

4. Start the server and open `http://localhost:8000`:
```bash
uvicorn main:app
```

5. The setup wizard opens on first start: create the admin login, pick the modules you want and add API keys. Everything can be changed later on the Settings page (it writes `.env` - see `.env.example` for all keys).

The CSS is prebuilt (`static/css/tailwind.css`). After changing templates, rebuild it with `npm install && npm run build:css`.

# Modules Setup

Modules without an entry below need no setup. The dashboard marks any module that is missing a key or tool, with a link to fix it.

## GitHub Analysis (GitFive)

1. Clone and install GitFive:
```bash
git clone https://github.com/mxrch/GitFive
cd GitFive
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

2. Log in to a GitHub account (not your main one) and follow GitFive's instructions:
```bash
python main.py login
```

3. Add the paths in Settings (or `.env`):
```env
GITFIVE_VENV_PATH=/path/to/GitFive/venv/bin/python
GITFIVE_SCRIPT_PATH=/path/to/GitFive/main.py
```

## GHunt

Install [GHunt](https://github.com/mxrch/GHunt) and run `ghunt login` as the user that runs the server. If `ghunt` is not on the PATH, set `GHUNT_SCRIPT_PATH`.

## Telegram (Funstat media, VK history)

1. Create an app at https://my.telegram.org/apps and set `TG_API_ID` / `TG_API_HASH` (and `TG_PHONE_NUMBER`).
2. Open `/telegram_auth` in the toolkit and log in with the code Telegram sends you.

Funstat itself also needs `FUNSTAT_API_KEY`.

## DNS Recon and Shared NS Lookup

1. Install the ProjectDiscovery tools (optional, but they add subdomains, HTTP probing and the website fingerprints):
```bash
go install -v github.com/projectdiscovery/subfinder/v2/cmd/subfinder@latest
go install -v github.com/projectdiscovery/httpx/cmd/httpx@latest
```
Set `HTTPX_PATH` / `SUBFINDER_PATH` if they are not on the PATH as `httpx-toolkit` / `subfinder`.

2. Optional API keys:
```env
SECURITYTRAILS_API_KEY=your_key   # more subdomains + DNS history
VIRUSTOTAL_API_KEY=your_key
HACKER_TARGET_API_KEY=your_key    # shared NS lookups beyond the free daily limit
```

## Paid API modules

| Module | Key | Get it from |
| --- | --- | --- |
| OSINT Industries | `OSINT_INDUSTRIES_API_KEY` | osint.industries |
| WHOIS History | `WHOIS_XML_API_KEY` | whoisxmlapi.com (checking how many records exist is free) |
| Web Search | `SERPAPI_KEY` | serpapi.com (dork links work without it) |
| IP Lookup (optional) | `IPINFO_API_TOKEN`, `ABUSEIPDB_API_KEY`, `SHODAN_API_KEY` | ipinfo.io, abuseipdb.com, shodan.io |

## Project Structure

- `/routes`: API route handlers and page routes
- `/services`: lookups and external integrations (`module_registry.py` lists every module, its inputs and requirements)
- `/models`: Pydantic models
- `/utils`: investigation saving, stream reducers, settings, subprocess and Telegram helpers
- `/templates`, `/static`: pages, per-module JS (`static/js/services/`) and the Tailwind build
- `/investigation_results`, `/media`: local case data (git-ignored, never commit it)
