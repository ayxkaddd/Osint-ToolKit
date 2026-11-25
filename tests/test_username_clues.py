"""Following the clues: usernames and links in found profiles lead to more accounts."""
import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from services.username_clues import SiteLinks, find_clues, plausible_username
from utils.stream_reducers import reduce_username_search

SITES = [
    {"name": "X", "uri_check": "https://api.x.test/{account}", "uri_pretty": "https://x.com/{account}"},
    {"name": "GitHub (User)", "uri_check": "https://github.com/{account}"},
    {"name": "Xanga", "uri_check": "https://{account}.xanga.com/"},
    {"name": "Archive", "uri_check": "https://web.archive.org/web/2/https://twitter.com/{account}"},
    {"name": "Search", "uri_check": "https://search.test/find?q={account}"},
]


@pytest.fixture(scope="module")
def links():
    return SiteLinks(SITES)


@pytest.mark.parametrize("url, expected", [
    ("https://x.com/moon_dev", ("X", "moon_dev")),
    ("twitter.com/moon_dev/", ("X", "moon_dev")),          # another name of the host, no scheme
    ("https://mobile.twitter.com/moon_dev", ("X", "moon_dev")),
    ("https://www.github.com/moon-dev", ("GitHub (User)", "moon-dev")),
    ("https://moondev.xanga.com/", ("Xanga", "moondev")),   # the username in the host
    ("https://x.com/moon_dev/status/1", None),
    ("https://search.test/find?q=moon", None),               # a search page is not a profile
    ("https://example.com/moon_dev", None),
])
def test_links_to_profiles_name_the_site_and_the_username(links, url, expected):
    assert links.match(url) == expected


def test_clues_from_a_socid_profile(links):
    profile = {"username": "alexmoon", "links": "['https://x.com/moon_dev', 'https://alexmoon.dev']",
               "twitter_username": "moon_dev", "github_username": "alexmoon", "telegram_username": "moon_tg",
               "your_username": "the_viewer", "email_username": "alex.m", "avatar_url": "https://x.com/someone",
               "bio": "builds things. alt: @moonie_x, mail alex@mail.test", "nickname": "Moonie"}
    clues = {c.value: c.to_dict() for c in find_clues(profile, "GitHub (User)", "alexmoon", links)}
    assert clues["moon_dev"] == {"value": "moon_dev", "kind": "link", "strength": "strong", "field": "links",
                                 "link": "https://x.com/moon_dev", "site": "X"}
    assert clues["moon_tg"] == {"value": "moon_tg", "kind": "username", "strength": "strong",
                                "field": "telegram_username", "site": "Telegram"}
    assert clues["moonie_x"]["strength"] == clues["Moonie"]["strength"] == "weak"
    # the searched one, the viewer, an email's first part, a picture, the email itself: not clues
    assert set(clues) == {"moon_dev", "moon_tg", "moonie_x", "Moonie"}


def test_clues_from_page_data_lists_and_nested_fields(links):
    profile = {"name": "Alex", "sameAs": ["https://twitter.com/moon_dev", "https://moondev.xanga.com"],
               "author": {"alternateName": "alex_m"}, "social": {"github_url": "https://github.com/settings"}}
    clues = {c.value: c for c in find_clues(profile, "Some site", "alexmoon", links)}
    assert set(clues) == {"moon_dev", "moondev", "alex_m"}
    assert clues["moondev"].site == "Xanga" and clues["alex_m"].strength == "weak"


def test_a_link_to_another_account_on_the_same_site_is_only_a_suggestion(links):
    clue, = find_clues({"links": "https://github.com/acme-org"}, "GitHub (User)", "alexmoon", links)
    assert (clue.value, clue.strength) == ("acme-org", "weak")


@pytest.mark.parametrize("value, ok", [
    ("moon_dev", True), ("moon.dev", True), ("Мун", True), ("a", False), ("12345", False), ("settings", False),
    ("has space", False), ("a@b.c", False), ("https://x.com", False), ("x" * 41, False), ("noreply", False),
])
def test_plausible_usernames(value, ok):
    assert plausible_username(value) is ok


# ---- the search follows them: fake sites whose profiles link to each other ----

PROFILES = {   # (site, username) -> where its profile links
    ("a", "alexmoon"): {"sameAs": ["{root}/b/moon_dev"], "alternateName": "weakone"},
    ("b", "moon_dev"): {"sameAs": ["{root}/a/third_one"]},
    ("a", "third_one"): {"sameAs": ["{root}/b/fourth_one"]},
}


class _Linked(BaseHTTPRequestHandler):
    hits: list = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        site, user = self.path.strip("/").split("/", 1)
        _Linked.hits.append((site, user))
        profile = PROFILES.get((site, user))
        if profile is None:
            body, code = "not found", 404
        else:
            root = f"http://{self.headers['Host']}"
            person = {"@context": "https://schema.org", "@type": "Person", "name": user,
                      **{k: ([v.format(root=root) for v in val] if isinstance(val, list) else val)
                         for k, val in profile.items()}}
            body, code = f"<html><script type='application/ld+json'>{json.dumps(person)}</script>Profile</html>", 200
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture(scope="module")
def linked_sites():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Linked)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    root = f"http://127.0.0.1:{srv.server_address[1]}"
    yield [{"name": name, "uri_check": f"{root}/{key}/{{account}}", "cat": "social", "e_code": 200,
            "e_string": "Profile", "m_code": 404, "m_string": "not found"} for key, name in (("a", "Alpha"), ("b", "Beta"))]
    srv.shutdown()


def _search(sites, **options):
    from services.username_service import StreamingUsernameSearchService
    service = StreamingUsernameSearchService(timeout_seconds=2, connect_timeout_seconds=1, stream_delay=0)
    service.get_metadata = lambda: {"sites": sites}
    _Linked.hits = []

    async def run():
        return [e.to_dict() async for e in service.stream_search("alexmoon", extract_profile=True, **options)]
    return asyncio.run(run())


def _of(events, kind):
    return [e["data"] for e in events if e["event_type"] == kind]


def test_the_search_follows_strong_clues_to_the_limits(linked_sites):
    events = _search(linked_sites, follow_clues=True)
    started = _of(events, "username_started")
    assert [(s["username"], s["depth"], s["via"]["site_name"], s["via"]["username"]) for s in started] == [
        ("moon_dev", 1, "Alpha", "alexmoon"), ("third_one", 2, "Beta", "moon_dev")]
    clues = {c["clue"]["value"]: (c["action"], c.get("reason")) for c in _of(events, "clue_found")}
    assert clues == {"moon_dev": ("follow", None), "weakone": ("suggest", "named on one profile only"),
                     "third_one": ("follow", None), "fourth_one": ("suggest", "2 steps from alexmoon")}
    # the linked account is checked at once, and not again in that username's own search
    assert _Linked.hits.count(("b", "moon_dev")) == 1
    beta = next(i for i, e in enumerate(events) if e["data"].get("site_name") == "Beta"
                and e["data"].get("searched") == "moon_dev" and e["event_type"] == "site_result")
    assert beta < next(i for i, e in enumerate(events) if e["event_type"] == "username_started")
    found = {(r["searched"], r["site_name"]) for r in _of(events, "site_result") if r["status"] == "found"}
    assert found == {("alexmoon", "Alpha"), ("moon_dev", "Beta"), ("third_one", "Alpha")}
    done = events[-1]["data"]
    assert [(f["username"], f["depth"], f["found"], f["checked"]) for f in done["followed"]] == [
        ("moon_dev", 1, 1, 2), ("third_one", 2, 1, 2)]
    assert done["total_checked"] == 6 and _of(events, "site_result")[-1]["progress"]["total"] == 6


def test_following_off_or_over_the_count_only_suggests(linked_sites):
    events = _search(linked_sites)
    assert not _of(events, "username_started")
    assert {c["clue"]["value"]: c["reason"] for c in _of(events, "clue_found")} == {
        "moon_dev": "following clues is off", "weakone": "named on one profile only"}
    events = _search(linked_sites, follow_clues=True, max_followed=1)
    assert [s["username"] for s in _of(events, "username_started")] == ["moon_dev"]
    assert {c["clue"]["value"]: c.get("reason") for c in _of(events, "clue_found")}["third_one"] == \
        "1 usernames followed already"


def test_the_saved_result_keeps_where_each_account_came_from(linked_sites):
    saved = reduce_username_search(_search(linked_sites, follow_clues=True))
    by_site = {(r["searched"], r["site_name"]): r for r in saved["results"]}
    alpha = by_site[("alexmoon", "Alpha")]
    assert {c["value"]: c["action"] for c in alpha["clues"]} == {"moon_dev": "follow", "weakone": "suggest"}
    assert [(f["username"], f["depth"], f["via"]["site_name"], f["found"]) for f in saved["followed"]] == [
        ("moon_dev", 1, "Alpha", 1), ("third_one", 2, "Beta", 1)]
    assert saved["username"] == "alexmoon" and saved["stats"]["found"] == 3 and saved["stats"]["total"] == 6


def test_clues_are_identifiers_of_the_account_they_were_found_in():
    from services.entities import extract_entities
    result = {"username": "alexmoon", "results": [{
        "site_name": "Alpha", "url": "https://a.test/alexmoon", "searched": "alexmoon",
        "profile_data": {"twitter_username": "moon_tw", "your_username": "the_viewer"},
        "clues": [{"value": "moon_dev", "kind": "link", "link": "https://x.com/moon_dev", "action": "follow"},
                  {"value": "weakone", "kind": "username", "action": "suggest"}]}]}
    found = {(e.type, e.value): path for e, path in extract_entities(result, "username")}
    assert found[("username", "moon_dev")] == "results[0].clues[0].username"
    assert found[("username", "weakone")] == "results[0].clues[1].username"
    assert found[("username", "moon_tw")] == "results[0].profile_data.twitter_username"
    assert ("username", "the_viewer") not in found


@pytest.mark.parametrize("site_name, check_url, value, own", [
    ("CastingCallClub", "https://www.castingcall.club/m/{account}", "CastingCallClub", True),
    ("CastingCallClub", "https://www.castingcall.club/m/{account}", "CCC", True),            # its initials
    ("RumbleUser", "https://rumble.com/user/{account}", "rumblevideo", True),
    ("Ko-Fi", "https://ko-fi.com/{account}", "kofi_button", True),
    ("Ko-Fi", "https://ko-fi.com/{account}", "johnart", False),
    ("GitHub (User)", "https://github.com/{account}", "moon_dev", False),
])
def test_the_site_own_accounts_are_not_clues(site_name, check_url, value, own):
    """A profile page names the site's own accounts too (footer links, the site's description):
    they are never the owner's."""
    links = SiteLinks([*SITES, {"name": site_name, "uri_check": check_url}])
    clues = find_clues({"links": f"['https://x.com/{value}']", "alternateName": value}, site_name, "john", links)
    assert (not clues) is own


def test_the_site_description_on_a_profile_page_is_not_the_profile():
    from services.username_service import _page_profile
    site = {"@context": "https://schema.org", "@type": "Organization", "name": "Casting Call Club",
            "alternateName": "CCC", "url": "https://www.castingcall.club",
            "sameAs": ["https://x.com/CastingCallClub"]}
    page = f"<html><script type='application/ld+json'>{json.dumps(site)}</script><title>john</title></html>"
    assert _page_profile(page, "text/html", "john") == (None, None)
    person = {"@type": "Person", "name": "John", "sameAs": ["https://x.com/john_vo"]}
    page = page.replace("</html>", f"<script type='application/ld+json'>{json.dumps(person)}</script></html>")
    assert _page_profile(page, "text/html", "john")[1] == {"name": "John", "sameAs": ["https://x.com/john_vo"]}
    # an organisation that the page says it is the profile of (a company's page) is still read
    profile_page = {"@type": "ProfilePage", "mainEntity": {"@type": "Organization", "name": "Acme"}}
    page = f"<html><script type='application/ld+json'>{json.dumps(profile_page)}</script></html>"
    assert _page_profile(page, "text/html", "acme")[1] == {"name": "Acme"}


def test_site_own_clues_saved_earlier_are_not_identifiers():
    from services.entities import extract_entities
    result = {"username": "john", "results": [{
        "site_name": "CastingCallClub", "url": "https://www.castingcall.club/m/john", "searched": "john",
        "clues": [{"value": "CastingCallClub", "kind": "link", "action": "follow"},
                  {"value": "john_vo", "kind": "link", "action": "follow"}]}]}
    found = {e.value for e, _ in extract_entities(result, "username") if e.type == "username"}
    assert found == {"john", "john_vo"}   # the searched one, and the clue that is the owner's
