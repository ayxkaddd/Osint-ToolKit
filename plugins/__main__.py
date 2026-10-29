"""python -m plugins new <id> [--python] [--accepts email,username] [--name "Name"]
python -m plugins list

Run from the toolkit's folder. A plugin made with ``new`` is marked as yours, so
it runs without the "from another source" review.
"""
import argparse
import sys
from pathlib import Path
from textwrap import dedent

NO_CODE = '''\
# {name} - no-code plugin. Reference: plugins/README.md
name: {name}
description: What it finds, in one sentence.
icon: puzzle                 # https://lucide.dev/icons
site: api.example.com        # card icon: this site's favicon
accepts: [{accepts}]

settings:
  {key}:
    label: API key
    secret: true

request:
  url: https://api.example.com/v1/lookup
  query:
    q: "{{value}}"
  headers:
    Authorization: Bearer {{settings.{key}}}

response:
  # root: data             # the part of the answer to use
  # items: results         # a list in it: one card per element
  title: "{{name}}"
  subtitle: "{{username}}"
  url: profile_url
  image: avatar
  fields:
    Email: email
    Location: location
    Joined: "{{created_at|date}}"
  entities:
    email: email
    url: profile_url
'''

PYTHON_YAML = '''\
# {name} - Python plugin: plugin.py does the lookup. Reference: plugins/README.md
name: {name}
description: What it finds, in one sentence.
icon: puzzle                 # https://lucide.dev/icons
site: api.example.com        # card icon: this site's favicon
accepts: [{accepts}]

settings:
  {key}:
    label: API key
    secret: true
'''

PYTHON_CODE = '''\
"""{name}."""
from plugins.sdk import Item, PluginError


async def run(value, type, ctx):
    r = await ctx.http.get("https://api.example.com/v1/lookup", params={{"q": value}},
                           headers={{"Authorization": f"Bearer {{ctx.settings.{key}}}"}})
    if r.status_code == 404:
        return None                      # "Nothing found"
    if r.status_code == 401:
        raise PluginError("The API key was rejected - check it in Settings")
    r.raise_for_status()
    data = r.json()

    # One card per result. Use `yield Item(...)` instead of return to show cards as they come.
    return [
        Item(
            title=row.get("name") or value,
            subtitle=row.get("username", ""),
            url=row.get("profile_url", ""),
            image=row.get("avatar", ""),
            fields={{"Email": row.get("email"), "Location": row.get("location")}},
            entities={{"email": row.get("email"), "url": row.get("profile_url")}},
        )
        for row in data.get("results", [])
    ]
'''


def cmd_new(args) -> int:
    from services import plugin_loader
    from services.entities import ENTITY_TYPES

    plugin_id = args.id.strip().lower()
    if not plugin_loader.ID_RE.match(plugin_id):
        print("The id is the folder name: lowercase letters, digits and _ (2-40 characters), e.g. hunter_io")
        return 1
    if plugin_id in plugin_loader.RESERVED_IDS:
        print(f"'{plugin_id}' is the name of a built-in module - pick another")
        return 1
    accepts = [t.strip() for t in args.accepts.split(",") if t.strip()]
    unknown = [t for t in accepts if t not in ENTITY_TYPES]
    if unknown:
        print(f"Unknown type {', '.join(unknown)}. Types: {', '.join(ENTITY_TYPES)}")
        return 1
    folder = plugin_loader.PLUGINS_DIR / plugin_id
    if folder.exists():
        print(f"{folder} already exists")
        return 1
    values = {"name": args.name or plugin_id.replace("_", " ").title(), "accepts": ", ".join(accepts),
              "key": f"{plugin_id.upper()}_API_KEY"}
    folder.mkdir(parents=True)
    if args.python:
        (folder / "plugin.yaml").write_text(PYTHON_YAML.format(**values))
        (folder / "plugin.py").write_text(PYTHON_CODE.format(**values))
    else:
        (folder / "plugin.yaml").write_text(NO_CODE.format(**values))
    plugin_loader.write_trust(plugin_id, "local")
    files = ", ".join(p.name for p in sorted(folder.iterdir()))
    print(dedent(f"""\
        Created {folder}/ ({files}), marked as your plugin.
        Edit it, then open /plugins/{plugin_id} in the toolkit to try it.
        Its API key goes in Settings ({values['key']})."""))
    return 0


def cmd_list(_args) -> int:
    from services import plugin_loader

    plugins = plugin_loader.refresh(force=True)
    if not plugins:
        print("No plugins. Create one: python -m plugins new <id>")
    for plugin in plugins.values():
        state = plugin.error or plugin.blocked() or ("ready" if not plugin.missing_settings()
                                                     else f"needs {', '.join(plugin.missing_settings())}")
        print(f"{plugin.id:24} {plugin.kind:7} {plugin.source:11} {state}")
    return 0


def main() -> int:
    if not Path("main.py").exists() or not Path("plugins").is_dir():
        print("Run this from the toolkit's folder (where main.py is)")
        return 1
    sys.path.insert(0, ".")
    parser = argparse.ArgumentParser(prog="python -m plugins", description="Toolkit plugins")
    sub = parser.add_subparsers(dest="command", required=True)
    new = sub.add_parser("new", help="create a plugin")
    new.add_argument("id", help="folder name / id, e.g. hunter_io")
    new.add_argument("--python", action="store_true", help="Python plugin (plugin.py) instead of no-code")
    new.add_argument("--accepts", default="email", help="what it looks up, comma separated (default: email)")
    new.add_argument("--name", help="display name")
    new.set_defaults(func=cmd_new)
    sub.add_parser("list", help="list plugins and their state").set_defaults(func=cmd_list)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
