# OSINT Toolkit

[![Tests](https://github.com/ayxkaddd/Osint-ToolKit/actions/workflows/tests.yml/badge.svg)](https://github.com/ayxkaddd/Osint-ToolKit/actions/workflows/tests.yml)

A self-hosted web workspace for OSINT investigations. Built with FastAPI and TailwindCSS: every lookup is saved into an investigation, identifiers found in results become one-click pivots into the other modules, and findings, notes and reports live in one place.

## Preview

<img width="1000" height="594" alt="demo" src="https://github.com/user-attachments/assets/6eeb8b56-9fca-47f5-9549-c27360f8d869" />


## Features

### Investigations
- **Investigations**: every lookup is saved to the active investigation, follow-up lookups are grouped under the result they came from. Select several results to delete them, set their assessment, or move them to another investigation. Active, completed and archived cases have their own tabs; right-click an investigation or a result for its actions
- **Re-runs**: running the same lookup again shows what changed since last time - identifiers new and gone, changed fields, values added and removed
- **Pivots**: emails, phones, usernames, domains, IPs and Telegram IDs found in any result can be sent to the matching modules in one click
- **Shared with other investigations**: identifiers that another investigation has too are marked with the number of investigations, and their menu links to them
- **Timeline**: when things happened, from the dates inside the results - accounts created, domains registered or expiring, leaks, name changes, messages
- **Graph**: each investigation as a map - what you looked up on the left, each lookup a column to the right, what it found beyond it, and big results folded into groups that open on a click. Look up any node with another module and watch the new branch grow when it finishes; hide nodes or take them off the graph, add your own nodes (a person, a place, any identifier) and labelled links, undo and redo. Search (also inside folded groups), focus on a node, filters, the path between two nodes, a web layout beside the tree; moved nodes snap into line. The view is kept per investigation, the case report includes a picture of it, and it exports to PNG, SVG, JSON and GEXF (Gephi). Full screen at `/investigations/<id>/graph`
- **Add manually**: save what you found outside the toolkit (a site without an API, a Telegram bot, a leak) as a result - text, identifiers, a link, a date and files or pasted screenshots
- **Background lookups**: run a lookup from any identifier's menu and keep working; open it while it runs to watch the results arrive
- **Universal lookup**: paste an email, phone, @user, domain or IP in the top bar and run a module right from the dropdown, on any page, or open the full list of lookups. A phone number typed without its country code isn't guessed: the full numbers it could be are offered to pick from. The grid icon next to the box opens any module
- **Triage, notes and reports**: mark results as confirmed or important, keep Markdown notes with images (drag and drop or paste), print a case report (findings, timeline, files added, tracking IDs - nothing from other cases, so it can be shared) and export the whole case as a .zip with its files
- **Dashboard and settings**: each module shows whether it is ready and what it costs; modules that still need a key, a tool or a login are listed apart, each with a link to the field to fill in. API keys and tool paths are set in the browser (Settings, Plugins, the update check and Log out are in the ⋮ menu at the right of the top bar)
- **Nothing loaded from outside**: fonts and icons are served by the toolkit itself, so opening a page contacts no CDN
- **Plugins**: connect any service with an API without writing code - see [Plugins](#plugins)

### Modules
- **Username Search**: checks ~700 sites (WhatsMyName list) for an account, streams results live, says why a site couldn't be checked (blocked, rate limited) and re-checks those. Requests carry a real browser's fingerprint, so fewer sites block them. An overview sums up the photos, names, usernames and places the accounts show and when they were first and last active; each account's card leads with its picture, name and @handle, then the bio, follower counts and dates. Optionally also checks whether the username is a mailbox at ~20 email providers (Microsoft, Yahoo, AOL, Mail.ru, Zoho, Rambler, Posteo, Gmail and more) - see [Email providers](#email-providers)
- **OSINT Industries**: accounts registered to an email, phone or username
- **GHunt**: the Google account behind an email or Gaia ID
- **GitHub Analysis (GitFive)**: real emails and names from commits, linked accounts and SSH keys
- **Funstat**: Telegram users and groups - name history, groups, messages with full-size media, members, the public t.me avatar and bio
- **VK Profile History**: earlier names, photos, contacts and details of a VK profile, shown as the bot sends them
- **Face Search**: VK profiles with a similar face
- **Cavalier (Hudson Rock)**: infostealer infections that leaked logins for an email or username
- **Phone Lookup**: offline number analysis plus a paid HLR network lookup. A number without its country code is refused rather than read as some other country's; the numbers it could be are offered instead
- **Web Search**: search-engine dorks for a username, name, email or phone (optionally run through SerpAPI)
- **DNS Recon**: subdomains (crt.sh, subfinder, SecurityTrails, VirusTotal), mail/DNS/hosting providers, SPF/DMARC, verification tokens, analytics and ads IDs on the pages (with the other websites that use them, via BuiltWith), ASN hosting and DNS history
- **WHOIS History**: every archived WHOIS record of a domain - free preview of how many exist, then contacts, registrar/name server periods and a change log
- **Shared NS Lookup**: domains on the same name server pair, then parsed WHOIS and an httpx web fingerprint of each to group the domains most likely run by the same owner; favicon hashes link to a FOFA search for other sites with the same icon
- **IP Lookup**: location, network owner, reverse DNS, abuse reports and exposed services
- **External Resources**: a curated directory of OSINT sites, grouped by category and searchable, each tagged with its cost and the identifier types it takes; many open straight on an identifier from its pivot menu

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
`requirements-lock.txt` has the exact versions the project is tested with, if a newer release of a dependency causes problems.
The server runs from this folder; it is not a package to `pip install`.

4. Start the server and open `http://localhost:8000`:
```bash
uvicorn main:app
```
Run it as a single process (no `--workers`): investigations and the login limit are kept by that one process, so a second process on the same folder refuses to start.

Behind a reverse proxy (nginx, Caddy) that adds the client address to `X-Forwarded-For`, set `TRUST_PROXY_HEADERS=true` in `.env` so the login limit counts each client separately. If the proxy runs on another machine, also start uvicorn with `--forwarded-allow-ips <proxy address>`. When the proxy serves HTTPS, the login cookie is sent over HTTPS only, without setting anything (`COOKIE_SECURE=true` forces that).

5. The setup wizard opens on first start: create the admin login, pick the modules you want and add API keys. On the computer the server runs on it opens as it is; from another computer (a server on `0.0.0.0`, Docker), open the setup link printed in the server console (`/setup?token=...`), so nobody else who reaches the port can create the admin account. Everything can be changed later on the Settings page (it writes `.env` - see `.env.example` for all keys).

The CSS is prebuilt (`static/css/tailwind.css`). After changing templates, rebuild it with `npm install && npm run build:css`.

## Command-line client

`osint` works with the same investigations from a terminal: list them, show results and identifiers, run lookups and watch their answers arrive, export cases. It talks to a running server over its API, so you can use it on another computer too. Install it with [pipx](https://pipx.pypa.io) (or `uv tool install` with the same address) on Windows, macOS or Linux:

```bash
pipx install "git+https://github.com/ayxkaddd/Osint-ToolKit#subdirectory=cli"
osint login http://127.0.0.1:8000
osint list
osint lookup someone@example.com             # pick the modules to run, then see what each one answers
```

`osint lookup` asks which modules to run (nothing is ticked at first, since some cost money), then prints each answer when it finishes; streaming lookups such as username search print what they find as it arrives, like the web page. In scripts, `-m holehe,gravatar` names the modules instead. Read commands take `--json` for `jq`. All commands are in [cli/README.md](cli/README.md).

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

Only the email addresses GitFive proves are the target's become identifiers in the investigation; the addresses it generates to test, and those of other people who committed to the target's repositories, are shown on the module page but not saved as identifiers.

## GHunt

Install [GHunt](https://github.com/mxrch/GHunt) and run its `login` as the user that runs the server. Then set its paths in Settings (or `.env`), like GitFive:

```
GHUNT_VENV_PATH=/path/to/GHunt/venv
GHUNT_SCRIPT_PATH=/path/to/GHunt/main.py
```

With neither set, the `ghunt` command on the PATH is used.

## Email providers

Tick **Also check email providers** under the username search box to see whether the username is also a mailbox: for `someuser`, whether `someuser@outlook.com`, `@yahoo.com`, `@mail.ru` and so on exist. Found addresses become email chips you can look up in other modules.

- Each provider is asked the way its own signup or sign-in page asks ("is this name taken?"). There are no password-reset or recovery requests, so nothing reaches the owner of the address. A provider that doesn't answer clearly is shown as "couldn't check", with the reason, never as "not registered".
- **Gmail** is checked the way GHunt does it, with your GHunt session (run `ghunt login` first), and only after you allow it in the dialog on the page. The lookup goes straight to Google, never through proxies. To use a session file somewhere other than `~/.malfrats/ghunt/creds.m`, set `GHUNT_CREDS_PATH`.
- **Yandex and mail.de** are asked through their mail servers, which needs outbound port 25 (blocked by many home and cloud networks).
- **Proton and iCloud** no longer reveal whether an address exists; an address there still counts as found when it has a Gravatar profile.

Most provider checks are adapted from [mailcat](https://github.com/sharsil/mailcat) (Apache License 2.0).

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

## Proxies

Settings → **Proxies** sends the modules that query websites directly through proxies: Username Search, DNS Recon (crt.sh, subfinder, httpx), Shared NS Lookup, Face Search, Cavalier, WHOIS History and the t.me profile. OSINT Industries, Funstat, HLR, SerpAPI, GHunt, the Telegram connection and port scans stay direct.

- Off by default. Paste your own proxies, one per line: `ip:port`, `http://user:pass@host:port` or `socks5://host:port` (HTTP, HTTPS, SOCKS4 and SOCKS5).
- Without enough of your own, free public proxies are fetched from [monosans/proxy-list](https://github.com/monosans/proxy-list) and only the fast, working ones are used. Many sites block free proxies, so a username search can find fewer accounts through them; paid residential proxies work much better.
- Proxies are tested in the background, never during a search, and a request whose proxies fail goes out directly, so searches take about as long as without them.

## Paid API modules

| Module | Key | Get it from |
| --- | --- | --- |
| OSINT Industries | `OSINT_INDUSTRIES_API_KEY` | osint.industries |
| WHOIS History | `WHOIS_XML_API_KEY` | whoisxmlapi.com (checking how many records exist is free) |
| Web Search | `SERPAPI_KEY` | serpapi.com (dork links work without it) |
| IP Lookup (optional) | `IPINFO_API_TOKEN`, `ABUSEIPDB_API_KEY`, `SHODAN_API_KEY` | ipinfo.io, abuseipdb.com, shodan.io |

# Plugins

Plugins add your own modules: a page to search with, a place in the lookup box, pivots and background lookups, API keys in Settings, and results saved to the investigation like any other module.

- **No code**: Plugins page (⋮ menu at the right of the top bar → **Plugins**) → **New plugin**. Paste an example request from the service's API documentation (a `curl` line) - the address, settings and API key are filled in for you. Press **Test**, and the result cards are worked out from the answer automatically; click values in the answer to change what's shown. A service that does several things (e.g. checking an email and listing a company's emails) can be one plugin with several searches that share the API key.
- **Python**: `python -m plugins new my_plugin --python` creates a plugin with a `run(value, type, ctx)` function, for anything that needs more than one request.

The format, both kinds and examples are in [plugins/README.md](plugins/README.md). Examples ship with the toolkit: GitHub user, certificate transparency (crt.sh), Gravatar, OathNet and Hunter.io (one plugin with three searches: domain search, email verification, person enrichment).

Plugins you make, and the examples, run as they are. A plugin from someone else is marked **not checked**: a no-code one works, with a warning saying where your searches are sent, while one that runs code, reads another module's API key or connects to your local network stays off until you look at its files and turn it on. A plugin's `renderer.js` runs in your pages with your access to every investigation, so read it before turning it on.

## Security

- Pages only run the toolkit's own script files (a Content-Security-Policy), so a value from a result that slips past escaping can't run as a script. Plugin views use `data-click` instead of inline `onclick` (see [plugins/README.md](plugins/README.md)).
- Logins last 24 hours. **Log out everywhere** (⋮ menu) also ends the sessions in other browsers and any copied login cookie.
- Other websites can link to pages, but can't call the API or submit anything.

## Project Structure

- `/routes`: API route handlers and page routes
- `/services`: lookups and external integrations (`module_registry.py` lists every module, its inputs and requirements). Investigation storage is in `services/investigations/` and the plugin loader in `services/pluginkit/`, one module per area
- `/models`: Pydantic models
- `/utils`: investigation saving, stream reducers, settings, subprocess and Telegram helpers
- `/plugins`: plugins (one folder each), the plugin SDK and `python -m plugins`
- `/templates`, `/static`: pages, per-module JS (`static/js/services/`), the shared JS (`static/js/main.js`, an ES module made of `static/js/lib/`) and the Tailwind build
- `/tests`: automated tests (`pip install -r requirements-dev.txt`, then `python -m pytest`; `ruff check .` is the lint CI runs). They run in a temporary folder with their own settings and need no network
- `/investigation_results`, `/media`: local case data (git-ignored, never commit it)
