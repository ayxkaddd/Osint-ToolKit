# Plugins

A plugin adds a module to the toolkit: a page to run it, a place in the lookup box,
the pivot menus and background lookups, its API key on the Settings page, and results
saved to the investigation like any other module's (notes can link and attach them).

Each folder in `plugins/` is one plugin; the folder name is its id. There are two kinds:

- **No-code** - `plugin.yaml` only. One HTTP request, and which parts of the answer
  to show. Covers most "add API X" cases.
- **Python** - `plugin.yaml` + `plugin.py`. For anything else: several requests,
  paging, hashing, a CLI tool, streaming results.

**No-code plugins can be built in the app**: Plugins page (puzzle icon) → **New plugin**.
Paste a curl command from the API's docs (the API key and the looked-up value are found
for you), press **Send** to try it, and the results mapping is filled in from the answer;
click values in the answer to show them on the cards. It writes the `plugin.yaml`
described below, and can edit or duplicate no-code plugins later.

Or create one from the toolkit's folder:

```sh
python -m plugins new hunter_io                       # no-code, looks up emails
python -m plugins new my_api --python --accepts username,email
python -m plugins list                                # every plugin and its state
```

Then open `/plugins/<id>`, tick **Test only** (nothing is saved) and try it. Changes to
the files are picked up automatically; **Raw response** under the results shows what the
API answered, which is what the `response:` paths below point into.

Examples in this folder: `github_user` and `crtsh` (no-code), `gravatar` (Python).

## Plugins from other sources

Plugins you create with `python -m plugins new` (or mark as yours) and the examples
here run as they are. Any other folder dropped into `plugins/` is treated as **from
another source**:

- a no-code plugin works, with a warning on its page saying where your lookups are sent;
  it may only connect to the hosts in its `plugin.yaml` (redirects included);
- a plugin that runs code (`plugin.py`, `renderer.js`), reads another module's API key,
  or connects to a local network address stays **off** until you review its files and
  enable it on the **Plugins** page (puzzle icon in the top bar). If its files change
  later, it is switched off again until you re-enable it.

An enabled Python plugin can do anything the toolkit can (read files, keys,
investigations), so only enable code you have read or that comes from someone you trust.

## plugin.yaml

```yaml
name: Hunter.io email verifier         # required
description: Whether an email exists and where it was seen online.
icon: mail-check                       # https://lucide.dev/icons name (default: puzzle)
site: hunter.io                        # card icon: this site's favicon
placeholder: someone@company.com       # input box hint
accepts: [email]                       # required - what it looks up (types below)
cost: paid                             # free (default) / paid: shown before running
cost_note: 1 Hunter credit
speed: fast                            # fast / medium / slow (shown in the lookup box)
concurrency: 2                         # background lookups at a time (1-5)
timeout: 120                           # Python plugins: seconds for the whole run

settings:                              # API keys etc., entered on the Settings page
  HUNTER_IO_API_KEY:                   # must start with the plugin id in capitals
    label: API key
    secret: true                       # masked in Settings, logs and saved results
    required: true                     # false: optional (lookups run without it)
    help: https://hunter.io/api-keys
```

Identifier types for `accepts` (and `entities` below): `email`, `phone`, `username`,
`domain`, `ip`, `url`, `telegram_id`, `telegram_username`, `vk`, `gaia_id`, `bssid`,
`crypto_btc`, `crypto_eth`, `text`. When a plugin accepts several, its page shows a
switch and the lookup box offers it for each.

Setting names start with the plugin's id (`hunter_io` -> `HUNTER_IO_...`). A plugin may
also use a built-in module's key (e.g. `SHODAN_API_KEY`); that needs a review if the
plugin is from another source.

## No-code plugins

### request:

```yaml
request:
  method: GET                          # GET (default) or POST
  url: https://api.hunter.io/v2/email-verifier
  query:                               # ?email=...&api_key=...
    email: "{value}"
    api_key: "{settings.HUNTER_IO_API_KEY}"
  headers:
    Accept: application/json
  # json: {email: "{value}"}           # POST body as JSON
  # form: {email: "{value}"}           # POST body as a form
  timeout: 30                          # seconds
  empty_status: [404]                  # these HTTP codes mean "nothing found"
```

Placeholders: `{value}` (what is looked up, cleaned up: emails lowercased, phones
as +E.164, `@` removed from usernames), `{type}` (its type) and
`{settings.NAME}`. In the url they are URL-encoded. A query/header/form entry that uses
an **optional** setting which isn't set is left out, so
`Authorization: Bearer {settings.X}` only goes out when there is a key.

Filters: `{value|lower}`, `|upper`, `|trim` (spaces and a leading @), `|md5`, `|sha1`,
`|sha256`, `|urlencode`, `|date` (first 10 characters: 2024-01-31), and they chain:
`{value|lower|md5}`.

`request_by_type:` gives a different request per input type:

```yaml
accepts: [email, domain]
request_by_type:
  email:  {url: "https://api.example.com/email/{value}"}
  domain: {url: "https://api.example.com/domain/{value}"}
```

### Several lookups (requests:)

An API with several endpoints can be one plugin. Instead of `request:`/`response:`, list
them under `requests:`, each with its own id, name, inputs, request and response (same
format as above). All lookups that accept the looked-up type run at the same time; cards
are grouped by lookup, and one failing shows a warning next to the others' results. The
plugin page lets you choose which to run. They share the plugin's settings (one API key).

```yaml
name: Hunter.io
site: hunter.io
settings:
  HUNTER_IO_API_KEY: {label: API key, secret: true}
requests:
  - id: verify
    name: Email verifier
    accepts: [email]
    request:
      url: https://api.hunter.io/v2/email-verifier
      query: {email: "{value}", api_key: "{settings.HUNTER_IO_API_KEY}"}
    response:
      root: data
      title: email
      subtitle: status
      fields: {Score: score, Disposable: disposable}
  - id: domain_search
    name: Domain search
    accepts: [domain]
    request:
      url: https://api.hunter.io/v2/domain-search
      query: {domain: "{value}", api_key: "{settings.HUNTER_IO_API_KEY}"}
    response:
      items: data.emails
      title: value
```

`accepts:` at the top is optional here: the plugin accepts what its lookups do.

### response:

Paths point into the JSON answer: `name`, `owner.login`, `emails[0]`, and `sources[].uri`
(the `uri` of every element of `sources`, as a list).

```yaml
response:
  format: json                         # json (default) or text
  root: data                           # use this part of the answer
  items: results                       # a list in it: one card per element ("." = root is the list)
  unique: id                           # drop elements repeating this value
  limit: 200                           # at most this many cards
  title: "{first_name} {last_name}"    # card title (default: name/title/login/...)
  subtitle: position
  url: profile_url                     # the card's "Open" link
  image: avatar                        # picture, with reverse image search buttons
  site: domain                         # card icon: this site's favicon
  category: type
  fields:                              # rows on the card: label -> path or template
    Status: status
    Score: score
    Seen on: sources[].uri
    Checked: "{checked_at|date}"
  entities:                            # identifiers to pivot on: type -> path(s)
    email: email
    url: [website, sources[].uri]
```

Every value is either a **path** (`profile_url`) or a **template** with placeholders
(`"{first} {last}"`, `"https://site/u/{id}"`). Templates can also use `{$value}` and
`{$type}` (what was looked up). Without `fields:`, every simple top-level value of an
element becomes a row. With `format: text`, the answer is `{text, lines}`: use
`items: lines` for a card per line, and `"."` (or `{.}`) for the line itself.

Without `items:`, the root is one card (or one card per element if it is a list).

## Python plugins

`plugin.yaml` describes the plugin (everything above except `request:`/`response:`);
`plugin.py` defines `run`:

```python
from plugins.sdk import Item, PluginError

async def run(value, type, ctx):
    r = await ctx.http.get("https://api.example.com/lookup", params={"q": value},
                           headers={"X-Key": ctx.settings.MY_API_API_KEY})
    if r.status_code == 404:
        return None                         # "Nothing found"
    if r.status_code == 401:
        raise PluginError("The API key was rejected - check it in Settings")
    r.raise_for_status()                    # other errors: "api.example.com answered HTTP 500"
    return [Item(title=a["site"], url=a["url"], fields={"Joined": a["created"]},
                 entities={"url": a["url"]}) for a in r.json()["accounts"]]
```

`run` returns an `Item`, a list of them, any other JSON-like data (shown as a tree),
or None. Written with `yield Item(...)` it is an async generator, and each card appears
on the page as soon as it is yielded; a lookup stopped half way keeps what it found.
A plain `def run` (blocking code, e.g. `requests`) runs in a thread.

`Item(title, subtitle, url, image, site, icon, category, fields, entities)` - see
`plugins/sdk.py`. `fields` is `{"Label": value}` or `[("Label", value), ...]`; empty
values are left out. `entities` is `{"email": "a@b.c", "url": [...]}`.

`ctx`:

| | |
|---|---|
| `ctx.value`, `ctx.type` | what is looked up |
| `ctx.settings.NAME` | the plugin's settings (None when unset) |
| `ctx.http` | `httpx.AsyncClient` - 30 s timeout, follows redirects |
| `ctx.log` | logger; secret settings are masked in its output |
| `await ctx.run_command(["tool", value], timeout=120)` | run a CLI tool without blocking (`.returncode`, `.stdout`, `.stderr`) |

`PluginError("message")` shows the message to the user. Other exceptions show as
"plugin.py failed: ..." and the traceback goes to the server log.

## Custom result view (renderer.js)

Cards fit most results. For anything else, add `renderer.js`; it runs in every page
(so it needs a review when the plugin is from another source):

```js
registerPluginRenderer(pluginId, (result) => {
    // result: {plugin, value, type, items: [...], data, error, note, raw}
    // return HTML, or null for the standard cards (pluginCardsHtml(result.items))
    return `<p>${escapeHtml(result.value)}: ${result.items.length} hits</p>` + pluginCardsHtml(result.items);
});
```

Escape anything from the API with `escapeHtml()` / `escapeAttr()` and links with `safeUrl()`.
