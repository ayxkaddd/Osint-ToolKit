"""The investigation graph: nodes, links, groups, the node budget and paging."""
import time
from uuid import UUID

import pytest


def _service():
    from services.investigation_service import investigation_service
    return investigation_service


def _save(inv, service, method, parameters, result, parent=None):
    return _service().save_investigation_result(UUID(inv), service, method, parameters, result,
                                                parent_result_id=parent)


def _sites(username, count, categories=("social", "coding")):
    return {"username": username, "results": [
        {"site_name": f"Site{i}", "url": f"https://site{i}.test/{username}", "category": categories[i % len(categories)]}
        for i in range(count)]}


def _graph(client, inv, **params):
    response = client.get(f"/api/investigations/{inv}/graph", params=params)
    assert response.status_code == 200
    data = response.json()
    return data, {n["id"]: n for n in data["nodes"]}, {(e["source"], e["target"]): e for e in data["edges"]}


def test_lookups_sit_between_what_was_searched_and_what_was_found(client, investigation):
    rid = _save(investigation, "username", "lookup_username", {"username": "jdoe"},
                {"username": "jdoe", "results": [
                    {"site_name": "GitHub", "url": "https://github.com/jdoe", "category": "coding",
                     "profile_data": {"email": "jdoe@mail.test"}}]})
    _save(investigation, "ghunt", "lookup_ghunt_email", {"email": "jdoe@mail.test"},
          {"gaia_id": "123456789012345678901"}, parent=rid)
    child_id = _service().get_result(UUID(investigation), rid)["children"][0]["child_id"]

    data, nodes, edges = _graph(client, investigation)
    lookup, child = f"r:{rid}", f"r:{rid}:{child_id}"
    assert nodes["e:username:jdoe"]["root"] is True
    assert nodes[lookup]["kind"] == "lookup" and nodes[lookup]["service"] == "username"
    assert edges[("e:username:jdoe", lookup)]["kind"] == "searched"
    assert edges[(lookup, "e:url:https://github.com/jdoe")]["kind"] == "found"
    # the email was found by the username search and looked up with GHunt: the branch grows from it
    assert edges[(lookup, "e:email:jdoe@mail.test")]["service"] == "username"
    assert edges[("e:email:jdoe@mail.test", child)]["kind"] == "searched"
    assert (child, "e:gaia_id:123456789012345678901") in edges
    assert all(e["source"] in nodes and e["target"] in nodes for e in data["edges"])
    assert data["state"] == {}


def test_an_identifier_found_twice_is_one_node(client, investigation):
    first = _save(investigation, "whois", "lookup_whois", {"domain": "one.test"}, {"email": "owner@mail.test"})
    second = _save(investigation, "whois", "lookup_whois", {"domain": "two.test"}, {"email": "owner@mail.test"})
    _, nodes, edges = _graph(client, investigation)
    assert nodes["e:email:owner@mail.test"]["found_by"] == 2
    assert (f"r:{first}", "e:email:owner@mail.test") in edges and (f"r:{second}", "e:email:owner@mail.test") in edges
    assert [n["id"] for n in nodes.values()].count("e:email:owner@mail.test") == 1


def test_big_results_are_grouped_and_open_a_page_at_a_time(client, investigation):
    rid = _save(investigation, "username", "lookup_username", {"username": "many"}, _sites("many", 50))
    data, nodes, edges = _graph(client, investigation)
    lookup = f"r:{rid}"
    groups = {n["key"]: n for n in nodes.values() if n["kind"] == "group"}
    assert {k: g["count"] for k, g in groups.items()} == {"category:social": 25, "category:coding": 25}
    assert groups["category:social"]["label"] == "Accounts · social"
    assert nodes[lookup]["found"] == 50 and nodes[lookup]["hidden"] == 50
    assert not any(n["kind"] == "identifier" and n["type"] == "url" for n in nodes.values())
    assert data["stats"]["folded"] == 50 and data["stats"]["groups"] == 2

    group = groups["category:social"]["id"]
    page = client.get(f"/api/investigations/{investigation}/graph/expand",
                      params={"node": group, "limit": 10}).json()
    assert page["total"] == 25
    assert [n["kind"] for n in page["nodes"]] == ["identifier"] * 10 + ["more"]
    more = page["nodes"][-1]
    assert more == {"id": f"more:{group}:10", "kind": "more", "parent": group, "offset": 10, "count": 15}
    assert all(e["source"] == group for e in page["edges"])

    rest = client.get(f"/api/investigations/{investigation}/graph/expand",
                      params={"node": more["id"], "limit": 40}).json()
    assert len(rest["nodes"]) == 15 and rest["offset"] == 10
    assert not {n["id"] for n in rest["nodes"]} & {n["id"] for n in page["nodes"]}

    # opening the lookup itself gives its groups
    opened = client.get(f"/api/investigations/{investigation}/graph/expand", params={"node": lookup}).json()
    assert sorted(n["id"] for n in opened["nodes"]) == sorted(g["id"] for g in groups.values())


def test_few_findings_are_shown_as_they_are(client, investigation):
    rid = _save(investigation, "username", "lookup_username", {"username": "few"}, _sites("few", 8))
    _, nodes, _ = _graph(client, investigation)
    assert sum(1 for n in nodes.values() if n["kind"] == "identifier" and n["type"] == "url") == 8
    assert nodes[f"r:{rid}"]["hidden"] == 0 and nodes[f"r:{rid}"]["open"] is True


def test_identifiers_that_matter_are_shown_outside_their_group(client, investigation):
    _save(investigation, "username", "lookup_username", {"username": "pinned"}, _sites("pinned", 30))
    client.patch(f"/api/investigations/{investigation}/entities",
                 json={"key": "url:https://site3.test/pinned", "status": "confirmed"})
    _, nodes, _ = _graph(client, investigation)
    assert nodes["e:url:https://site3.test/pinned"]["status"] == "confirmed"
    group = next(n for n in nodes.values() if n["kind"] == "group" and n["key"] == "category:coding")
    assert group["count"] == 14

    # and first in the lookup's children
    rid = next(n for n in nodes.values() if n["kind"] == "lookup")["id"]
    opened = client.get(f"/api/investigations/{investigation}/graph/expand", params={"node": rid}).json()
    assert opened["nodes"][0]["id"] == "e:url:https://site3.test/pinned"


def test_shared_identifiers_are_shown_with_how_many_cases(client):
    def new(name):
        data = client.post("/api/investigations/create", data={"name": name}).json()
        return data.get("investigation_id") or data["investigation"]["investigation_id"]
    first, second = new("Graph A"), new("Graph B")
    _save(first, "username", "lookup_username", {"username": "sharer"}, _sites("sharer", 20))
    _save(second, "whois", "lookup_whois", {"domain": "sharer.test"}, {"website": "https://site7.test/sharer"})
    _, nodes, _ = _graph(client, first)
    assert nodes["e:url:https://site7.test/sharer"]["shared"] == 1
    assert nodes["e:username:sharer"]["shared"] == 0


def test_running_a_lookup_again_is_one_lookup_with_several_runs(client, investigation):
    first = _save(investigation, "username", "lookup_username", {"username": "again"}, _sites("again", 20))
    second = _save(investigation, "username", "lookup_username", {"username": "again"},
                   {**_sites("again", 21), "stats": {"completed": True}})
    other = _save(investigation, "username", "lookup_username", {"username": "different"}, _sites("different", 2))
    _, nodes, edges = _graph(client, investigation)
    lookups = [n for n in nodes.values() if n["kind"] == "lookup"]
    assert sorted(n["id"] for n in lookups) == sorted([f"r:{first}", f"r:{other}"])
    lookup = nodes[f"r:{first}"]
    # the first run's id, the latest run's result; findings of every run
    assert lookup["rerun"] is True and lookup["result_id"] == second
    assert [run["result_id"] for run in lookup["runs"]] == [second, first]
    assert lookup["found"] == 21
    assert nodes[f"r:{other}"]["rerun"] is False and len(nodes[f"r:{other}"]["runs"]) == 1
    assert ("e:username:again", f"r:{first}") in edges
    groups = [n for n in nodes.values() if n["kind"] == "group"]
    assert sorted((g["lookup"], g["count"]) for g in groups) == [(f"r:{first}", 10), (f"r:{first}", 11)]

    # a site found by both runs was found by one lookup
    page = client.get(f"/api/investigations/{investigation}/graph/expand", params={"node": groups[0]["id"]}).json()
    assert {n["found_by"] for n in page["nodes"]} == {1}
    # any run opens the lookup
    by_later_run = client.get(f"/api/investigations/{investigation}/graph/expand", params={"node": f"r:{second}"})
    assert by_later_run.json()["node"] == f"r:{first}"


def test_followups_of_reruns_are_merged_too(client, investigation):
    first = _save(investigation, "funstat", "lookup_user", {"id": "777000111"}, {"id": 777000111})
    _save(investigation, "funstat", "stats", {"id": "777000111"}, {"messages": 5}, parent=first)
    second = _save(investigation, "funstat", "lookup_user", {"id": "777000111"}, {"id": 777000111})
    _save(investigation, "funstat", "stats", {"id": "777000111"}, {"messages": 6}, parent=second)
    _, nodes, _ = _graph(client, investigation)
    lookups = [n for n in nodes.values() if n["kind"] == "lookup"]
    assert sorted((n["method"], len(n["runs"])) for n in lookups) == [("lookup_user", 2), ("stats", 2)]


def test_things_added_by_hand_are_never_merged(client, investigation):
    for _ in range(2):
        _save(investigation, "manual", "upload", {"title": "Same title"}, {"kind": "manual", "text": "x@hand.test"})
    _, nodes, _ = _graph(client, investigation)
    assert sum(1 for n in nodes.values() if n["kind"] == "lookup") == 2


def test_shared_identifiers_give_way_to_the_budget(client):
    def new(name):
        data = client.post("/api/investigations/create", data={"name": name}).json()
        return data.get("investigation_id") or data["investigation"]["investigation_id"]
    first, second = new("Budget A"), new("Budget B")
    _save(first, "username", "lookup_username", {"username": "crowd"}, _sites("crowd", 40))
    _save(second, "username", "lookup_username", {"username": "crowd2"},
          {"username": "crowd2", "results": [{"site_name": "x", "url": f"https://site{i}.test/crowd",
                                              "category": "social"} for i in range(40)]})
    roomy = _service().get_graph(UUID(first))
    assert sum(1 for n in roomy["nodes"] if n["kind"] == "identifier" and n["type"] == "url") == 40

    # the username, its lookup and two groups: no room for the shared sites
    tight = _service().get_graph(UUID(first), budget=4)
    nodes = {n["id"]: n for n in tight["nodes"]}
    assert len(nodes) == 4
    assert {n["key"]: n["count"] for n in nodes.values() if n["kind"] == "group"} == {
        "category:social": 20, "category:coding": 20}
    group = next(n["id"] for n in nodes.values() if n["kind"] == "group")
    page = _service().expand_graph_node(UUID(first), group, budget=4)
    assert len(page["nodes"]) == 20 and all(n["shared"] == 1 for n in page["nodes"])

    # with some room, some of them are shown on their own
    some = _service().get_graph(UUID(first), budget=10)
    assert len(some["nodes"]) <= 10
    assert sum(1 for n in some["nodes"] if n["kind"] == "identifier" and n["type"] == "url") == 6


def test_noise_and_false_positives_are_left_out_unless_asked(client, investigation):
    rid = _save(investigation, "whois", "lookup_whois", {"domain": "quiet.test"},
                {"emails": ["real@quiet.test", "wrong@quiet.test"]})
    service = _service()
    entities = service._load_entities(UUID(investigation))
    # saved before today's noise rules
    entities["email:abuse@quiet.test"] = {
        "key": "email:abuse@quiet.test", "type": "email", "value": "abuse@quiet.test", "display": "abuse@quiet.test",
        "status": None, "note": None, "sources": [{"result_id": rid, "service": "whois", "method": "lookup_whois",
                                                   "role": "found", "path": "x"}]}
    service._save_entities(UUID(investigation), entities)
    client.patch(f"/api/investigations/{investigation}/entities",
                 json={"key": "email:wrong@quiet.test", "status": "false_positive"})

    data, nodes, _ = _graph(client, investigation)
    assert "e:email:real@quiet.test" in nodes
    assert "e:email:abuse@quiet.test" not in nodes and "e:email:wrong@quiet.test" not in nodes
    assert data["stats"]["noise"] == 1 and data["stats"]["false_positive"] == 1

    _, nodes, _ = _graph(client, investigation, noise=1)
    assert {"e:email:abuse@quiet.test", "e:email:wrong@quiet.test"} <= set(nodes)


def test_node_budget_closes_the_deepest_lookups_first(client, investigation):
    rid = _save(investigation, "username", "lookup_username", {"username": "deep"}, _sites("deep", 8))
    for i in range(3):
        _save(investigation, "whois", "lookup_whois", {"url": f"https://site{i}.test/deep"},
              {"emails": [f"person{i}.{n}@deep.test" for n in range(6)]}, parent=rid)
    full = _service().get_graph(UUID(investigation))
    # the username, 4 lookups, 8 sites, 18 emails and deep.test (found by all three WHOIS lookups)
    assert full["stats"]["nodes"] == 1 + 4 + 8 + 18 + 1 and not full["stats"]["over_budget"]

    small = _service().get_graph(UUID(investigation), budget=20)
    nodes = {n["id"]: n for n in small["nodes"]}
    assert small["stats"]["nodes"] <= 20
    # the username search (closer to the root) stays open; the WHOIS lookups under it fold
    assert nodes[f"r:{rid}"]["open"] is True
    folded = [n for n in nodes.values() if n["kind"] == "lookup" and n["service"] == "whois" and not n["open"]]
    # six emails and deep.test, which no longer fits on its own
    assert folded and all(n["hidden"] == 7 for n in folded)
    assert all(e["source"] in nodes and e["target"] in nodes for e in small["edges"])


def test_ids_stay_the_same_when_the_case_grows(client, investigation):
    _save(investigation, "username", "lookup_username", {"username": "stable"}, _sites("stable", 20))
    _, before, _ = _graph(client, investigation)
    _save(investigation, "whois", "lookup_whois", {"domain": "stable.test"}, {"email": "x@stable.test"})
    _, after, _ = _graph(client, investigation)
    assert set(before) < set(after)


def test_graph_follows_changes_to_the_case(client, investigation):
    _save(investigation, "whois", "lookup_whois", {"domain": "fresh.test"}, {"email": "a@fresh.test"})
    _, nodes, _ = _graph(client, investigation)
    assert nodes["e:email:a@fresh.test"]["status"] is None
    client.patch(f"/api/investigations/{investigation}/entities",
                 json={"key": "email:a@fresh.test", "status": "important"})
    _, nodes, _ = _graph(client, investigation)
    assert nodes["e:email:a@fresh.test"]["status"] == "important"


def test_expand_unknown_node(client, investigation):
    response = client.get(f"/api/investigations/{investigation}/graph/expand", params={"node": "r:nope"})
    assert response.status_code == 404
    assert client.get("/api/investigations/00000000-0000-4000-8000-000000000000/graph").status_code == 404


@pytest.mark.parametrize("path", ["graph", "graph/expand?node=r:x", "graph/node?node=r:x"])
def test_graph_needs_login_and_this_site(anon, client, investigation, path):
    assert anon.get(f"/api/investigations/{investigation}/{path}").status_code == 401
    assert client.get(f"/api/investigations/{investigation}/{path}",
                      headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403


def test_a_case_with_5000_identifiers_opens_quickly(client, investigation):
    for batch in range(10):
        _save(investigation, "whois", "lookup_whois", {"domain": f"big{batch}.test"},
              {"emails": [f"user{batch}.{n}@big.test" for n in range(470)]})
    _save(investigation, "username", "lookup_username", {"username": "bigone"}, _sites("bigone", 300))
    assert len(_service().get_entities(UUID(investigation))) >= 5000

    started = time.perf_counter()
    data, _, _ = _graph(client, investigation)
    cold = time.perf_counter() - started
    started = time.perf_counter()
    _graph(client, investigation)
    warm = time.perf_counter() - started
    assert data["stats"]["nodes"] < 60
    assert cold < 0.3 and warm < 0.1, (cold, warm)


def test_node_details_for_the_side_panel(client):
    def new(name):
        data = client.post("/api/investigations/create", data={"name": name}).json()
        return data.get("investigation_id") or data["investigation"]["investigation_id"]
    inv, other = new("Panel case"), new("Panel other")
    rid = _save(inv, "username", "lookup_username", {"username": "panel"},
                {"username": "panel", "results": [{"site_name": "S", "url": "https://s.test/panel", "category": "social",
                                                   "profile_data": {"email": "panel@mail.test"}}]})
    _save(inv, "ghunt", "lookup_ghunt_email", {"email": "panel@mail.test"}, {"gaia_id": "123456789012345678901"},
          parent=rid)
    _save(other, "whois", "lookup_whois", {"domain": "o.test"}, {"email": "panel@mail.test"})

    def node(node_id):
        response = client.get(f"/api/investigations/{inv}/graph/node", params={"node": node_id})
        assert response.status_code == 200
        return response.json()

    email = node("e:email:panel@mail.test")
    assert email["node"]["kind"] == "identifier"
    assert [lk["service"] for lk in email["found_in"]] == ["username"]
    assert [lk["service"] for lk in email["searched_in"]] == ["ghunt"]
    assert [place["name"] for place in email["elsewhere"]] == ["Panel other"]

    lookup = node(email["searched_in"][0]["id"])
    # drawn under the email; saved as a follow-up of the username search
    assert lookup["node"]["service"] == "ghunt" and lookup["parent"]["id"] == f"r:{rid}"

    many = _save(inv, "username", "lookup_username", {"username": "crowded"}, _sites("crowded", 20))
    group = next(n for n in _graph(client, inv)[0]["nodes"] if n["kind"] == "group")
    details = node(group["id"])
    assert details["node"]["count"] == 10 and details["lookup"]["id"] == f"r:{many}"

    assert client.get(f"/api/investigations/{inv}/graph/node", params={"node": "e:email:nobody@x.test"}).status_code == 404


def test_account_pictures_are_shown_unless_they_are_stand_ins(client, investigation):
    from services.investigations.graph import profile_picture
    site = {"url": "https://site.test/u/pic"}
    assert profile_picture({**site, "profile_data": {"avatar": "/img/me.png"}}) == "https://site.test/img/me.png"
    assert profile_picture({**site, "profile_data": {"profile_pic": {"url": "https://cdn.test/a.jpg"}}}) == "https://cdn.test/a.jpg"
    assert profile_picture({**site, "profile_data": {"avatar": "https://site.test/default_avatar.png"}}) is None
    assert profile_picture({**site, "profile_data": {"avatar": "javascript:alert(1)"}}) is None
    assert profile_picture(site) is None

    _save(investigation, "username", "lookup_username", {"username": "pic"}, {"username": "pic", "results": [
        {"site_name": "A", "url": "https://a.test/pic", "category": "social", "profile_data": {"avatar": "https://a.test/me.png"}},
        {"site_name": "B", "url": "https://b.test/pic", "category": "social", "profile_data": {"avatar": "https://b.test/placeholder.png"}},
    ]})
    _, nodes, _ = _graph(client, investigation)
    assert nodes["e:url:https://a.test/pic"]["image"] == "https://a.test/me.png"
    assert nodes["e:url:https://b.test/pic"]["image"] is None


def test_graph_tab_and_full_screen_page(client, investigation):
    page = client.get(f"/api/investigations/{investigation}/view").text
    assert 'data-tab="graph"' in page and 'id="graphRoot"' in page
    assert '<script type="module" src="/static/js/graph/index.js"></script>' in page
    for vendored in ("/static/vendor/cytoscape/cytoscape.min.js", "/static/vendor/d3-hierarchy/d3-hierarchy.min.js"):
        assert vendored in page
        assert client.get(vendored).status_code == 200

    full = client.get(f"/investigations/{investigation}/graph")
    assert full.status_code == 200 and 'data-fullscreen="true"' in full.text
    assert "script-src 'self'" in full.headers["content-security-policy"]
    missing = client.get("/investigations/00000000-0000-4000-8000-000000000000/graph", headers={"Accept": "text/html"})
    assert missing.status_code == 404


def test_full_screen_page_needs_login(anon, investigation):
    response = anon.get(f"/investigations/{investigation}/graph", follow_redirects=False)
    assert response.status_code in (302, 303, 307)


# ---------------------------------------------------------------------------
# The saved view (graph.json)
# ---------------------------------------------------------------------------
M1, M2 = "m:" + "a" * 32, "m:" + "b" * 32


def _state(**changes):
    state = {
        "positions": {"e:email:x@y.test": [10.4, -20.6], M1: [100, 200]},
        "expanded": ["g:r:1:type:url"], "collapsed": ["r:2"], "hidden": ["e:url:https://a.test/"], "removed": [],
        "manual_nodes": [{"id": M1, "type": "person", "label": "John", "note": "met at the conference",
                          "url": "https://example.test/john", "color": "#f472b6"},
                         {"id": M2, "type": "email", "label": "j@x.test"}],
        "manual_edges": [{"id": "l:" + "c" * 32, "source": M1, "target": "e:email:x@y.test", "label": "same person"}],
        "viewport": {"zoom": 0.8, "x": 12.5, "y": -40},
        "filters": {"types": ["email"], "shared_only": True},
        "layout": "tree",
    }
    state.update(changes)
    return state


def test_graph_view_is_saved_and_comes_back(client, investigation):
    url = f"/api/investigations/{investigation}/graph/state"
    assert client.get(url).json() == {}
    response = client.put(url, json=_state())
    assert response.status_code == 200 and response.json()["updated_at"]
    saved = client.get(url).json()
    assert saved["positions"] == {"e:email:x@y.test": [10, -21], M1: [100, 200]}     # whole pixels
    assert saved["manual_nodes"][0]["label"] == "John" and saved["manual_nodes"][1].get("url") is None
    assert saved["manual_edges"][0]["label"] == "same person"
    assert saved["collapsed"] == ["r:2"] and saved["filters"]["shared_only"] is True
    assert "pinned" not in saved          # an older view: every position was a moved node
    client.put(url, json=_state(pinned=["e:email:x@y.test"]))
    assert client.get(url).json()["pinned"] == ["e:email:x@y.test"]
    client.put(url, json=_state(version=2))
    assert client.get(url).json()["version"] == 2
    # the first view comes with it
    assert client.get(f"/api/investigations/{investigation}/graph").json()["state"]["hidden"] == ["e:url:https://a.test/"]


@pytest.mark.parametrize("change", [
    {"surprise": 1},                                                                  # unknown key
    {"positions": {f"e:x{i}": [0, 0] for i in range(5001)}},                          # too many
    {"manual_nodes": [{"id": M1, "type": "person", "label": "x" * 201}]},             # label too long
    {"manual_nodes": [{"id": M1, "type": "person", "label": "x", "url": "javascript:alert(1)"}]},
    {"manual_nodes": [{"id": M1, "type": "person", "label": "x", "image": "../../.env"}]},
    {"manual_nodes": [{"id": "m:../x", "type": "person", "label": "x"}]},
    {"manual_nodes": [{"id": M1, "type": "spaceship", "label": "x"}]},
    {"manual_nodes": [{"id": M1, "type": "person", "label": "x", "color": "red; background:url(x)"}]},
    {"manual_nodes": [{"id": M1, "type": "person", "label": "x", "onclick": "alert(1)"}]},
    {"manual_edges": [{"id": "l:" + "c" * 32, "source": M1, "target": "x" * 1001}]},
    {"viewport": {"zoom": 0.8, "x": 0, "y": 0, "extra": 1}},
    {"layout": "spiral"},
    {"hidden": ["e:x"] * 5001},
    {"pinned": ["e:x"] * 5001},
    {"version": -1},
])
def test_graph_view_is_checked(client, investigation, change):
    response = client.put(f"/api/investigations/{investigation}/graph/state", json=_state(**change))
    assert response.status_code == 422, response.text
    assert client.get(f"/api/investigations/{investigation}/graph/state").json() == {}


def test_graph_view_rejects_bad_numbers_and_huge_bodies(client, investigation):
    url = f"/api/investigations/{investigation}/graph/state"
    body = '{"positions": {"e:a": [NaN, 1]}}'
    assert client.put(url, content=body, headers={"Content-Type": "application/json"}).status_code == 422
    huge = '{"hidden": ["' + "x" * (3 * 1024 * 1024) + '"]}'
    assert client.put(url, content=huge, headers={"Content-Type": "application/json"}).status_code == 413


def test_graph_view_needs_login_and_this_site(anon, client, investigation):
    url = f"/api/investigations/{investigation}/graph/state"
    assert anon.get(url).status_code == 401
    assert anon.put(url, json={}).status_code == 401
    assert client.put(url, json={}, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.get(url, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.put("/api/investigations/00000000-0000-4000-8000-000000000000/graph/state", json={}).status_code == 404


# ---------------------------------------------------------------------------
# Search, export and the picture in the report
# ---------------------------------------------------------------------------
def test_search_finds_what_is_folded_and_says_how_to_reach_it(client, investigation):
    rid = _save(investigation, "username", "lookup_username", {"username": "seek"}, _sites("seek", 60))
    whois = _save(investigation, "whois", "lookup_whois", {"domain": "seek.test"}, {"email": "owner@seek.test"})
    url = f"/api/investigations/{investigation}/graph/search"

    found = client.get(url, params={"q": "site45.TEST"}).json()
    assert found["total"] == 1
    match = found["matches"][0]
    assert match["id"] == "e:url:https://site45.test/seek"
    group = match["reveal"]["group"]
    assert match["reveal"]["lookup"] == f"r:{rid}" and group.startswith(f"g:r:{rid}:category:")
    # its place in the group: the expand page that has it
    page = client.get(f"/api/investigations/{investigation}/graph/expand",
                      params={"node": group, "offset": match["reveal"]["offset"], "limit": 1}).json()
    assert page["nodes"][0]["id"] == match["id"]

    shown = client.get(url, params={"q": "owner@seek"}).json()["matches"][0]
    # few findings: under its lookup (opened if the analyst folded it)
    assert shown["id"] == "e:email:owner@seek.test" and shown["reveal"] == {"lookup": f"r:{whois}"}
    assert client.get(url, params={"q": "s"}).json() == {"matches": [], "total": 0}
    assert client.get(url, params={"q": "seek"}).json()["total"] > 30
    assert len(client.get(url, params={"q": "seek"}).json()["matches"]) == 30


def test_whole_graph_exports_as_json_and_gexf(client, investigation):
    _save(investigation, "username", "lookup_username", {"username": "out"}, _sites("out", 20))
    _save(investigation, "manual", "upload", {"title": "x"}, {"kind": "manual", "text": "a <b>&</b> \x07 b@c.test"})
    client.put(f"/api/investigations/{investigation}/graph/state", json={
        "manual_nodes": [{"id": M1, "type": "person", "label": "Jo <\"&'>"}],
        "manual_edges": [{"id": "l:" + "d" * 32, "source": M1, "target": "e:username:out", "label": "is"}]})
    url = f"/api/investigations/{investigation}/graph/export"

    data = client.get(url).json()
    ids = {n["id"] for n in data["nodes"]}
    assert {"e:username:out", "e:url:https://site19.test/out", M1} <= ids            # nothing folded
    assert not any(n["id"].startswith("g:") for n in data["nodes"])
    assert {"source": M1, "target": "e:username:out"}.items() <= next(e for e in data["edges"] if e["kind"] == "manual").items()

    gexf = client.get(url, params={"format": "gexf"})
    assert gexf.status_code == 200 and gexf.headers["content-type"].startswith("application/gexf+xml")
    assert "attachment" in gexf.headers["content-disposition"]
    from xml.etree import ElementTree
    root = ElementTree.fromstring(gexf.content)        # well formed, whatever was in the values
    ns = {"g": "http://gexf.net/1.3"}
    labels = {n.get("label") for n in root.iterfind(".//g:node", ns)}
    assert "Jo <\"&'>" in labels and "https://site19.test/out" in labels
    assert len(root.findall(".//g:edge", ns)) == len(data["edges"])


def test_graph_picture_goes_in_the_report(client, investigation):
    from conftest import png
    url = f"/api/investigations/{investigation}/graph/image"
    assert client.get(url).status_code == 404
    assert "The investigation graph" not in client.get(f"/api/investigations/{investigation}/report").text
    assert client.put(url, content=b"<svg onload=alert(1)>").status_code == 400
    assert client.put(url, content=png((300, 200)), headers={"Content-Type": "image/png"}).status_code == 200
    image = client.get(url)
    assert image.status_code == 200 and image.content[:4] == b"RIFF" and image.content[8:12] == b"WEBP"
    report = client.get(f"/api/investigations/{investigation}/report").text
    assert 'alt="The investigation graph"' in report and 'src="data:image/webp;base64,' in report


@pytest.mark.parametrize("method,path", [("get", "graph/search?q=ab"), ("get", "graph/export"),
                                         ("get", "graph/export?format=gexf"), ("get", "graph/image"),
                                         ("put", "graph/image")])
def test_new_graph_endpoints_need_login_and_this_site(anon, client, investigation, method, path):
    url = f"/api/investigations/{investigation}/{path}"
    assert getattr(anon, method)(url).status_code == 401
    assert getattr(client, method)(url, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403


def test_an_identifier_keeps_the_lookup_that_found_it_first_as_its_home(client, investigation):
    first = _save(investigation, "whois", "lookup_whois", {"domain": "home.test"}, {"registrant_phone": "+14155550123"})
    # later, a lookup that searched nothing (a root) finds it too
    later = _save(investigation, "manual", "upload", {"title": "later"}, {"kind": "manual", "text": "call +14155550123"})
    _, nodes, edges = _graph(client, investigation)
    phone = nodes["e:phone:+14155550123"]
    assert phone["home"] == f"r:{first}" and phone["found_by"] == 2
    assert (f"r:{later}", "e:phone:+14155550123") in edges
    assert nodes["e:domain:home.test"]["home"] is None      # typed, found by nothing
