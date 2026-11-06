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
