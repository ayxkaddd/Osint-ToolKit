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


@pytest.mark.parametrize("path", ["graph", "graph/expand?node=r:x"])
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
