"""The script that adds the plugins' renderer.js files to every page."""
import json


from .registry import refresh


def client_script() -> str:
    """JS for every page: plugin names/icons for saved results, plus the custom
    renderers of plugins allowed to run code."""
    plugins = [p for p in refresh().values() if p.manifest]
    meta = [{"id": p.id, "name": p.name, "icon": p.manifest.icon if p.manifest else "puzzle",
             "page": f"/plugins/{p.id}", "icon_url": p.icon_url} for p in plugins]
    parts = [f"registerPlugins({json.dumps(meta, ensure_ascii=False)});"]
    for plugin in plugins:
        if not plugin.has_renderer or plugin.blocked():
            continue
        try:
            code = (plugin.path / "renderer.js").read_text(encoding="utf-8")
        except OSError:
            continue
        parts.append(
            f"/* plugin {plugin.id}: renderer.js */\n"
            f"try {{ (function (pluginId) {{\n{code}\n}})({json.dumps(plugin.id)}); }}\n"
            f"catch (e) {{ console.error({json.dumps(f'Plugin {plugin.id}: renderer.js failed')}, e); }}"
        )
    return "\n\n".join(parts) + "\n"
