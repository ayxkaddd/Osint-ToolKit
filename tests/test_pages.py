"""Every module page opens, and renamed pages redirect from their old addresses."""
import pytest

PAGES = ["/dashboard", "/investigations", "/lookup", "/username", "/ghunt", "/gitfive", "/funstat", "/vk",
         "/websearch", "/dnsrecon", "/oi", "/phone", "/ip", "/whois", "/ns", "/cavalier", "/face-search",
         "/plugins", "/plugins/builder", "/settings", "/telegram_auth"]


@pytest.mark.parametrize("path", PAGES)
def test_page_opens(client, path):
    assert client.get(path).status_code == 200


@pytest.mark.parametrize("old,new", [("/git", "/gitfive"), ("/api", "/oi"), ("/hlr", "/phone")])
def test_old_page_addresses_redirect(client, old, new):
    response = client.get(old + "?load_result=abc&investigation=xyz", follow_redirects=False)
    assert response.status_code == 301
    assert response.headers["location"] == new + "?load_result=abc&investigation=xyz"


def test_module_pages_exist(client):
    pages = {m["page"] for m in client.get("/api/modules").json()["modules"] if m.get("page")}
    for page in pages:
        assert client.get(page).status_code == 200, page


def test_favicon_needs_no_login(anon):
    response = anon.get("/favicon.ico")
    assert response.status_code == 200 and response.headers["content-type"] == "image/x-icon"
    assert response.content[:4] == b"\x00\x00\x01\x00"   # an ICO file
    assert anon.get("/static/favicon.svg").headers["content-type"].startswith("image/svg+xml")


@pytest.mark.parametrize("path", ["/", "/dashboard"])
def test_pages_link_the_favicon(anon, client, path):
    page = (anon if path == "/" else client).get(path).text
    assert 'href="/static/favicon.svg"' in page and 'href="/static/favicon.ico"' in page


def test_unknown_page_has_a_way_back(client):
    """A browser gets a page (with the app's header), not {"detail": "Not Found"}."""
    response = client.get("/no-such-page", headers={"Accept": "text/html,application/xhtml+xml"})
    assert response.status_code == 404 and response.headers["content-type"].startswith("text/html")
    assert "Page not found" in response.text and 'href="/dashboard"' in response.text


def test_missing_investigation_and_plugin_pages_say_what_is_missing(client):
    html = {"Accept": "text/html"}
    response = client.get("/api/investigations/00000000-0000-4000-8000-000000000000/view", headers=html)
    assert response.status_code == 404 and "not found" in response.text and "<h1" in response.text
    response = client.get("/plugins/no_such_plugin", headers=html)
    assert response.status_code == 404 and "No plugin" in response.text and "<h1" in response.text


def test_scripts_still_get_json_for_missing_things(client):
    response = client.get("/no-such-page")
    assert response.status_code == 404 and response.json() == {"detail": "Not Found"}
    response = client.get("/api/investigations/00000000-0000-4000-8000-000000000000", headers={"Accept": "application/json"})
    assert response.status_code == 404 and "detail" in response.json()
    # not for other errors or other methods
    assert client.post("/no-such-page", headers={"Accept": "text/html"}).json() == {"detail": "Not Found"}


def test_page_scripts_do_not_redeclare_shared_names():
    """Every page loads the shared scripts (base.html) and then its own. A page script that
    declares a top-level const/let/class with a name a shared script already uses doesn't
    run at all ("Identifier ... has already been declared"), which broke the NS page."""
    import re
    from conftest import REPO

    shared = ["main.js", "masonry.js", "oi_cards.js", "ghunt_cards.js", "result_renderers.js", "plugin_cards.js", "notes.js"]
    any_declaration = re.compile(r"^(?:async\s+)?(?:function\s+|const\s+|let\s+|class\s+)([A-Za-z_$][\w$]*)", re.M)
    lexical = re.compile(r"^(?:const|let|class)\s+([A-Za-z_$][\w$]*)", re.M)
    scripts = REPO / "static" / "js"
    base = (REPO / "templates" / "base.html").read_text()
    taken = {}
    for name in shared:
        assert f"/static/js/{name}" in base, f"{name} is no longer loaded by base.html"
        for identifier in any_declaration.findall((scripts / name).read_text()):
            assert identifier not in taken or name == taken[identifier], f"{identifier}: {taken[identifier]} and {name}"
            taken[identifier] = name
    clashes = []
    for path in sorted(scripts.rglob("*.js")):
        if path.name in shared or path.name == "lucide.js":
            continue
        text = path.read_text()
        clashes += [f"{path.name}: {n} (also in {taken[n]})" for n in lexical.findall(text) if n in taken]
        # a shared const/let can't be redeclared as a function either
        shared_lexical = {n for name in shared for n in lexical.findall((scripts / name).read_text())}
        clashes += [f"{path.name}: {n}" for n in any_declaration.findall(text) if n in shared_lexical and n not in lexical.findall(text)]
    assert not clashes, clashes
