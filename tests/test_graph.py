"""The investigation graph: identifiers, the cards between them, groups, the node budget and paging."""
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


# ---------------------------------------------------------------------------
# Cards between identifiers
# ---------------------------------------------------------------------------
def _card(username, i):
    return f"c:account:site{i}:{username}"


def test_cards_sit_between_what_was_searched_and_what_it_exposed(client, investigation):
    rid = _save(investigation, "username", "lookup_username", {"username": "jdoe"},
                {"username": "jdoe", "results": [
                    {"site_name": "GitHub", "url": "https://github.com/jdoe", "category": "coding", "searched": "jdoe",
                     "profile_data": {"email": "jdoe@mail.test", "fullname": "John Doe"}}]})
    _save(investigation, "ghunt", "lookup_ghunt_email", {"email": "jdoe@mail.test"},
          {"gaia_id": "123456789012345678901"}, parent=rid)

    data, nodes, edges = _graph(client, investigation)
    card = "c:account:github:jdoe"
    assert nodes["e:username:jdoe"]["root"] is True
    assert nodes[card]["kind"] == "card" and nodes[card]["card"] == "account"
    assert nodes[card]["title"] == "GitHub" and nodes[card]["subtitle"] == "John Doe"
    assert nodes[card]["services"] == ["username"] and nodes[card]["home"] == "e:username:jdoe"
    assert edges[("e:username:jdoe", card)]["kind"] == "card" and edges[("e:username:jdoe", card)]["label"] == "account"
    # the account's own address is the card, not a node of its own
    assert "e:url:https://github.com/jdoe" not in nodes
    # what the profile holds hangs under the card; the email's lookups grow from it
    assert edges[(card, "e:email:jdoe@mail.test")]["kind"] == "exposes"
    assert nodes["e:email:jdoe@mail.test"]["home"] == card
    # GHunt answered nothing a card is made of: what it found hangs under what it looked up
    found = edges[("e:email:jdoe@mail.test", "e:gaia_id:123456789012345678901")]
    assert found["kind"] == "found" and found["service"] == "ghunt"
    assert not any(n["kind"] == "lookup" for n in nodes.values())
    assert all(e["source"] in nodes and e["target"] in nodes for e in data["edges"])
    assert data["state"] == {}


def test_an_identifier_found_twice_is_one_node(client, investigation):
    _save(investigation, "whois", "lookup_whois", {"domain": "one.test"}, {"email": "owner@mail.test"})
    _save(investigation, "whois", "lookup_whois", {"domain": "two.test"}, {"email": "owner@mail.test"})
    _, nodes, edges = _graph(client, investigation)
    assert nodes["e:email:owner@mail.test"]["found_by"] == 2
    assert nodes["e:email:owner@mail.test"]["home"] == "e:domain:one.test"
    assert ("e:domain:one.test", "e:email:owner@mail.test") in edges
    assert edges[("e:domain:two.test", "e:email:owner@mail.test")]["cross"] is True
    assert [n["id"] for n in nodes.values()].count("e:email:owner@mail.test") == 1


def test_the_same_account_found_by_two_modules_is_one_card(client, investigation):
    _save(investigation, "username", "lookup_username", {"username": "jdoe"}, {"username": "jdoe", "results": [
        {"site_name": "GitHub", "url": "https://github.com/jdoe", "category": "coding", "searched": "jdoe"}]})
    _save(investigation, "oi", "lookup_oi", {"query": "jdoe@mail.test"}, {"modules": [
        {"module": "github", "domain": "github.com", "username": "jdoe", "location": "Kyiv",
         "profile_url": "https://github.com/jdoe"},
        {"module": "linkedin", "breach": True, "name": "LinkedIn", "domain": "linkedin.com", "created": "2012-05-05",
         "fields": [{"label": "Data classes", "value": "Passwords"}]}]})
    _, nodes, edges = _graph(client, investigation)
    card = nodes["c:account:github:jdoe"]
    assert card["found_by"] == 2 and card["services"] == ["username", "oi"]
    assert ["Location", "Kyiv"] in client.get(f"/api/investigations/{investigation}/graph/node",
                                              params={"node": card["id"]}).json()["node"]["facts"]
    # hangs under the username (first), and the email OI searched links to it too
    assert card["home"] == "e:username:jdoe" and edges[("e:email:jdoe@mail.test", card["id"])]["cross"] is True
    breach = nodes["c:breach:linkedin:email:jdoe@mail.test"]
    assert breach["card"] == "breach" and breach["date"] == "2012-05-05" and "password" in breach["flags"]
    assert edges[("e:email:jdoe@mail.test", breach["id"])]["label"] == "in breach"


def test_a_password_two_records_share_links_them(client, investigation):
    _save(investigation, "oathnet", "run", {"plugin_id": "oathnet", "value": "jdoe@mail.test"}, {
        "kind": "plugin_result", "plugin": "oathnet", "name": "OathNet", "items": [
            {"title": "jdoe@mail.test", "fields": [["Dbname", "one.test"], ["Password", "hunter22"]]},
            {"title": "jdoe@mail.test", "fields": [["Dbname", "two.test"], ["Password", "hunter22"]]},
            {"title": "jdoe@mail.test", "fields": [["Dbname", "three.test"], ["Password", "other"]]}]})
    _, nodes, edges = _graph(client, investigation)
    facts = [n for n in nodes.values() if n["kind"] == "fact"]
    assert len(facts) == 1 and facts[0]["fact"] == "password" and facts[0]["count"] == 2
    assert "hunter22" not in str(facts) and facts[0]["label"].startswith("h")
    one, two = "c:breach:one:email:jdoe@mail.test", "c:breach:two:email:jdoe@mail.test"
    assert (one, facts[0]["id"]) in edges and edges[(two, facts[0]["id"])]["cross"] is True
    assert nodes[one]["shares"] == 1 and nodes["c:breach:three:email:jdoe@mail.test"]["shares"] == 0


def test_big_results_are_grouped_and_open_a_page_at_a_time(client, investigation):
    _save(investigation, "username", "lookup_username", {"username": "many"}, _sites("many", 50))
    data, nodes, edges = _graph(client, investigation)
    groups = {n["key"]: n for n in nodes.values() if n["kind"] == "group"}
    assert {k: g["count"] for k, g in groups.items()} == {"card:account:social": 25, "card:account:coding": 25}
    assert groups["card:account:social"]["label"] == "Accounts · social"
    assert groups["card:account:social"]["owner"] == "e:username:many"
    assert not any(n["kind"] == "card" for n in nodes.values())
    assert data["stats"]["cards"] == 50 and data["stats"]["groups"] == 2

    group = groups["card:account:social"]["id"]
    page = client.get(f"/api/investigations/{investigation}/graph/expand",
                      params={"node": group, "limit": 10}).json()
    assert page["total"] == 25
    assert [n["kind"] for n in page["nodes"]] == ["card"] * 10 + ["more"]
    more = page["nodes"][-1]
    assert {k: more[k] for k in ("id", "kind", "parent", "offset", "count")} == {
        "id": f"more:{group}:10", "kind": "more", "parent": group, "offset": 10, "count": 15}
    assert all(e["source"] == group for e in page["edges"])

    rest = client.get(f"/api/investigations/{investigation}/graph/expand",
                      params={"node": more["id"], "limit": 40}).json()
    assert len(rest["nodes"]) == 15 and rest["offset"] == 10
    assert not {n["id"] for n in rest["nodes"]} & {n["id"] for n in page["nodes"]}

    # opening the username gives its groups
    opened = client.get(f"/api/investigations/{investigation}/graph/expand", params={"node": "e:username:many"}).json()
    assert sorted(n["id"] for n in opened["nodes"]) == sorted(g["id"] for g in groups.values())


def test_few_findings_are_shown_as_they_are(client, investigation):
    _save(investigation, "username", "lookup_username", {"username": "few"}, _sites("few", 8))
    _, nodes, _ = _graph(client, investigation)
    assert sum(1 for n in nodes.values() if n["kind"] == "card") == 8
    assert nodes["e:username:few"]["hidden"] == 0 and nodes["e:username:few"]["open"] is True


def test_identifiers_that_matter_are_shown_outside_their_group(client, investigation):
    _save(investigation, "username", "lookup_username", {"username": "pinned"}, _sites("pinned", 30))
    client.patch(f"/api/investigations/{investigation}/entities",
                 json={"key": "url:https://site3.test/pinned", "status": "confirmed"})
    _, nodes, _ = _graph(client, investigation)
    # assessed, the account's address is drawn, and its card with it
    assert nodes["e:url:https://site3.test/pinned"]["status"] == "confirmed"
    assert nodes["e:url:https://site3.test/pinned"]["home"] == _card("pinned", 3) in nodes
    group = next(n for n in nodes.values() if n["kind"] == "group" and n["key"] == "card:account:coding")
    assert group["count"] == 14

    # and first among the username's children
    opened = client.get(f"/api/investigations/{investigation}/graph/expand", params={"node": "e:username:pinned"}).json()
    assert opened["nodes"][0]["id"] == _card("pinned", 3)


def test_shared_identifiers_are_shown_with_how_many_cases(client):
    def new(name):
        data = client.post("/api/investigations/create", data={"name": name}).json()
        return data.get("investigation_id") or data["investigation"]["investigation_id"]
    first, second = new("Graph A"), new("Graph B")
    sites = _sites("sharer", 20)
    sites["results"][7]["profile_data"] = {"email": "sharer@mail.test"}
    _save(first, "username", "lookup_username", {"username": "sharer"}, sites)
    _save(second, "whois", "lookup_whois", {"domain": "sharer.test"}, {"email": "sharer@mail.test"})
    _, nodes, _ = _graph(client, first)
    # drawn outside the groups, with the way to it
    assert nodes["e:email:sharer@mail.test"]["shared"] == 1 and _card("sharer", 7) in nodes
    assert nodes["e:username:sharer"]["shared"] == 0


def test_running_a_lookup_again_is_one_lookup_with_several_runs(client, investigation):
    first = _save(investigation, "username", "lookup_username", {"username": "again"}, _sites("again", 20))
    second = _save(investigation, "username", "lookup_username", {"username": "again"},
                   {**_sites("again", 21), "stats": {"completed": True}})
    _, nodes, _ = _graph(client, investigation)
    groups = sorted((g["key"], g["count"]) for g in nodes.values() if g["kind"] == "group")
    assert groups == [("card:account:coding", 10), ("card:account:social", 11)]
    # a site found by both runs is one card, found by one lookup
    details = client.get(f"/api/investigations/{investigation}/graph/node", params={"node": _card("again", 0)}).json()
    assert details["node"]["found_by"] == 1 and sorted(details["node"]["result_ids"]) == sorted([first, second])
    lookup = details["lookups"][0]
    # the first run's id, the latest run's result
    assert lookup["id"] == f"r:{first}" and lookup["rerun"] is True and lookup["result_id"] == second
    assert [run["result_id"] for run in lookup["runs"]] == [second, first]
    # any run is the lookup
    by_later_run = client.get(f"/api/investigations/{investigation}/graph/node", params={"node": f"r:{second}"})
    assert by_later_run.json()["node"]["id"] == f"r:{first}"


def test_followups_of_reruns_are_merged_too(client, investigation):
    first = _save(investigation, "funstat", "lookup_user", {"id": "777000111"}, [{"id": 777000111, "first_name": "A"}])
    _save(investigation, "funstat", "stats_min", {"id": "777000111"}, {"total_msg_count": 5}, parent=first)
    second = _save(investigation, "funstat", "lookup_user", {"id": "777000111"}, [{"id": 777000111, "first_name": "A"}])
    _save(investigation, "funstat", "stats_min", {"id": "777000111"}, {"total_msg_count": 6}, parent=second)
    lookups = _service()._graph_model(UUID(investigation))["lookups"]
    assert sorted((n["method"], len(n["runs"])) for n in lookups.values()) == [("lookup_user", 2), ("stats_min", 2)]
    # the user's card has the stats of both runs
    _, nodes, _ = _graph(client, investigation)
    card = client.get(f"/api/investigations/{investigation}/graph/node",
                      params={"node": "c:account:telegram:777000111"}).json()["node"]
    assert {"5", "6"} <= {value for label, value in card["facts"] if label == "Messages"}


def test_things_added_by_hand_are_never_merged(client, investigation):
    for _ in range(2):
        _save(investigation, "manual", "upload", {"title": "Same title"}, {"kind": "manual", "title": "Same title",
                                                                           "text": "x@hand.test"})
    _, nodes, _ = _graph(client, investigation)
    assert sum(1 for n in nodes.values() if n["kind"] == "card" and n["card"] == "document") == 2


def test_the_budget_folds_what_does_not_fit(client, investigation):
    sites = _sites("crowd", 40)
    for i in (4, 9):        # two accounts name the same email: it links them
        sites["results"][i]["profile_data"] = {"email": "both@crowd.test"}
    _save(investigation, "username", "lookup_username", {"username": "crowd"}, sites)

    tight = _service().get_graph(UUID(investigation), budget=6)
    nodes = {n["id"]: n for n in tight["nodes"]}
    edges = {(e["source"], e["target"]) for e in tight["edges"]}
    # what links records is drawn first, with the way to it, and the other record that holds
    # it beside the groups; the rest is in the two groups
    assert "e:email:both@crowd.test" in nodes and _card("crowd", 4) in nodes and _card("crowd", 9) in nodes
    assert (_card("crowd", 9), "e:email:both@crowd.test") in edges
    assert {n["key"]: n["count"] for n in nodes.values() if n["kind"] == "group"} == {
        "card:account:social": 19, "card:account:coding": 19}
    assert len(nodes) == 6
    group = next(n["id"] for n in nodes.values() if n["kind"] == "group" and n["key"] == "card:account:coding")
    page = _service().expand_graph_node(UUID(investigation), group, budget=6)
    assert len(page["nodes"]) == 19 and all(n["kind"] == "card" for n in page["nodes"])


def test_many_kinds_of_site_are_one_group_of_accounts(client, investigation):
    sites = _sites("wide", 30, categories=("a", "b", "c", "d", "e", "f"))
    sites["results"][5]["profile_data"] = {"image": "https://site5.test/me.png"}
    _save(investigation, "username", "lookup_username", {"username": "wide"}, sites)
    _, nodes, _ = _graph(client, investigation)
    groups = [n for n in nodes.values() if n["kind"] == "group"]
    assert [(g["key"], g["label"], g["count"]) for g in groups] == [("card:account", "Accounts", 29)]
    # the account with a picture is shown on its own
    assert nodes[_card("wide", 5)]["picture"] == "https://site5.test/me.png"


def test_node_budget_closes_the_deepest_first(client, investigation):
    rid = _save(investigation, "username", "lookup_username", {"username": "deep"}, _sites("deep", 8))
    for i in range(3):
        _save(investigation, "whois", "lookup_whois", {"url": f"https://site{i}.test/deep"},
              {"emails": [f"person{i}.{n}@deep.test" for n in range(6)]}, parent=rid)
    full = _service().get_graph(UUID(investigation))
    # the username, 8 accounts, the 3 addresses looked up, 18 emails and deep.test (found by all three)
    assert full["stats"]["nodes"] == 1 + 8 + 3 + 18 + 1

    small = _service().get_graph(UUID(investigation), budget=20)
    nodes = {n["id"]: n for n in small["nodes"]}
    assert small["stats"]["nodes"] <= 20
    # the username (closer to the root) stays open; the addresses looked up later fold
    assert nodes["e:username:deep"]["open"] is True
    folded = [n for n in nodes.values() if n["kind"] == "identifier" and n["type"] == "url" and not n["open"]]
    assert folded and all(n["hidden"] == 6 for n in folded)
    assert all(e["source"] in nodes and e["target"] in nodes for e in small["edges"])


def test_node_details_for_the_side_panel(client):
    def new(name):
        data = client.post("/api/investigations/create", data={"name": name}).json()
        return data.get("investigation_id") or data["investigation"]["investigation_id"]
    inv, other = new("Panel case"), new("Panel other")
    rid = _save(inv, "username", "lookup_username", {"username": "panel"},
                {"username": "panel", "results": [{"site_name": "S", "url": "https://s.test/panel", "category": "social",
                                                   "profile_data": {"email": "panel@mail.test", "bio": "hi"}}]})
    _save(inv, "ghunt", "lookup_ghunt_email", {"email": "panel@mail.test"}, {"gaia_id": "123456789012345678901"},
          parent=rid)
    _save(other, "whois", "lookup_whois", {"domain": "o.test"}, {"email": "panel@mail.test"})

    def node(node_id):
        response = client.get(f"/api/investigations/{inv}/graph/node", params={"node": node_id})
        assert response.status_code == 200
        return response.json()

    email = node("e:email:panel@mail.test")
    assert email["node"]["kind"] == "identifier"
    assert [c["id"] for c in email["cards"]] == ["c:account:s:panel"]
    assert [lk["service"] for lk in email["found_in"]] == ["username"]
    assert [lk["service"] for lk in email["searched_in"]] == ["ghunt"]
    assert [place["name"] for place in email["elsewhere"]] == ["Panel other"]

    card = node("c:account:s:panel")
    assert card["node"]["facts"] == [["Email", "panel@mail.test"], ["Bio", "hi"]]
    # with the email's domain (a company's or someone's own, unless a mail provider's)
    assert [x["id"] for x in card["exposed"]] == ["e:email:panel@mail.test", "e:domain:mail.test"]
    assert [x["id"] for x in card["subject"]] == ["e:username:panel"]
    assert {"type": "url", "value": "https://s.test/panel"} in card["identifiers"]
    assert card["lookups"][0]["id"] == f"r:{rid}" and card["node"]["runs"][0]["result_id"] == rid

    lookup = node(email["searched_in"][0]["id"])
    # saved as a follow-up of the username search
    assert lookup["node"]["service"] == "ghunt" and lookup["parent"]["id"] == f"r:{rid}"

    _save(inv, "username", "lookup_username", {"username": "crowded"}, _sites("crowded", 20))
    group = next(n for n in _graph(client, inv)[0]["nodes"] if n["kind"] == "group")
    details = node(group["id"])
    assert details["node"]["count"] == 10 and details["owner"]["id"] == "e:username:crowded"
    assert len(details["members"]) == 10

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
    assert nodes["c:account:a:pic"]["picture"] == "https://a.test/me.png"
    assert nodes["c:account:b:pic"]["picture"] is None
    # the username shows its first account's picture
    assert nodes["e:username:pic"]["image"] == "https://a.test/me.png"


def test_summary_of_what_we_know(client, investigation):
    sites = _sites("sum", 3)
    sites["results"][0]["profile_data"] = {"fullname": "John Doe", "location": "Kyiv",
                                           "image": "https://site0.test/me.png"}
    sites["results"][1]["profile_data"] = {"fullname": "John Doe", "city": "Kyiv"}
    _save(investigation, "username", "lookup_username", {"username": "sum"}, sites)
    _save(investigation, "oi", "lookup_oi", {"query": "sum@mail.test"}, {"modules": [
        {"module": "x", "breach": True, "name": "Big leak", "created": "2020-01-01",
         "fields": [{"label": "Data classes", "value": "Passwords"}]}]})
    summary = client.get(f"/api/investigations/{investigation}/graph/summary").json()
    assert summary["names"][0]["value"] == "John Doe" and summary["names"][0]["sources"] == 2
    assert summary["places"][0] == {"value": "Kyiv", "count": 2, "id": _card("sum", 0)}
    assert summary["photos"][0]["url"] == "https://site0.test/me.png"
    assert summary["accounts"] == {"coding": 1, "social": 2}
    assert summary["breaches"]["count"] == 1 and summary["breaches"]["passwords"] == 1
    assert summary["usernames"][0]["value"] == "sum" and summary["usernames"][0]["searched"] is True
    assert summary["counts"]["kinds"] == {"account": 3, "breach": 1}


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
    _save(investigation, "username", "lookup_username", {"username": "seek"}, _sites("seek", 60))
    _save(investigation, "whois", "lookup_whois", {"domain": "seek.test"}, {"email": "owner@seek.test"})
    url = f"/api/investigations/{investigation}/graph/search"

    found = client.get(url, params={"q": "site45.TEST"}).json()
    assert found["total"] == 1
    match = found["matches"][0]
    assert match["id"] == _card("seek", 45) and match["kind"] == "card"
    opened, step = match["steps"]
    assert opened == {"open": "e:username:seek"} and step["group"].startswith("g:e:username:seek:card:account:")
    # its place in the group: the expand page that has it
    page = client.get(f"/api/investigations/{investigation}/graph/expand",
                      params={"node": step["group"], "offset": step["offset"], "limit": 1}).json()
    assert page["nodes"][0]["id"] == match["id"]
    revealed = client.get(f"/api/investigations/{investigation}/graph/reveal", params={"node": match["id"]}).json()
    assert revealed["steps"] == match["steps"]

    shown = client.get(url, params={"q": "owner@seek"}).json()["matches"][0]
    # drawn already: nothing to open
    assert shown["id"] == "e:email:owner@seek.test" and shown["steps"] == []
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
    assert {"e:username:out", _card("out", 19), M1} <= ids            # nothing folded
    assert not any(n["id"].startswith("g:") for n in data["nodes"])
    assert next(n for n in data["nodes"] if n["id"] == _card("out", 19))["url"] == "https://site19.test/out"
    assert {"source": M1, "target": "e:username:out"}.items() <= next(e for e in data["edges"] if e["kind"] == "manual").items()

    gexf = client.get(url, params={"format": "gexf"})
    assert gexf.status_code == 200 and gexf.headers["content-type"].startswith("application/gexf+xml")
    assert "attachment" in gexf.headers["content-disposition"]
    from xml.etree import ElementTree
    root = ElementTree.fromstring(gexf.content)        # well formed, whatever was in the values
    ns = {"g": "http://gexf.net/1.3"}
    labels = {n.get("label") for n in root.iterfind(".//g:node", ns)}
    assert "Jo <\"&'>" in labels and "Site19" in labels
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


def test_an_identifier_hangs_under_the_record_that_holds_it(client, investigation):
    _save(investigation, "whois", "lookup_whois", {"domain": "home.test"}, {"registrant_phone": "+14155550123"})
    # later, something added by hand holds it too: a record, so it hangs there
    _save(investigation, "manual", "upload", {"title": "later"}, {"kind": "manual", "title": "Later",
                                                                   "text": "call +14155550123"})
    _, nodes, edges = _graph(client, investigation)
    phone = nodes["e:phone:+14155550123"]
    document = next(n for n in nodes.values() if n["kind"] == "card" and n["card"] == "document")
    assert phone["home"] == document["id"] and phone["found_by"] == 2
    assert edges[("e:domain:home.test", "e:phone:+14155550123")]["cross"] is True
    # a lookup that looked up no identifier is where its card starts
    assert document["home"].startswith("r:") and nodes[document["home"]]["root"] is True
    assert nodes["e:domain:home.test"]["home"] is None      # typed, found by nothing


def test_followed_clues_hang_under_the_account_that_named_them(client, investigation):
    """alexmoon's GitHub links x.com/moon_dev: moon_dev hangs under that account, its accounts
    under it, the same as in the username page's tree."""
    moon_accounts = [{"site_name": f"Moon{i}", "url": f"https://moon{i}.test/moon_dev", "category": "social",
                      "searched": "moon_dev"} for i in range(12)]
    _save(investigation, "username", "lookup_username", {"username": "alexmoon"}, {
        "username": "alexmoon",
        "results": [
            {"site_name": "GitHub", "url": "https://github.com/alexmoon", "category": "coding", "searched": "alexmoon",
             "clues": [{"value": "moon_dev", "kind": "link", "strength": "strong", "field": "links",
                        "link": "https://x.com/moon_dev", "site": "X", "action": "follow"}]},
            {"site_name": "Reddit", "url": "https://reddit.com/user/alexmoon", "category": "social",
             "searched": "alexmoon"},
            *moon_accounts],
        "followed": [{"username": "moon_dev", "depth": 1, "found": 12, "checked": 600,
                      "via": {"username": "alexmoon", "site_name": "GitHub", "url": "https://github.com/alexmoon"}}]})
    data, nodes, edges = _graph(client, investigation)
    github, moon = "c:account:github:alexmoon", "e:username:moon_dev"
    assert github in nodes and moon in nodes and nodes[moon]["home"] == github
    assert edges[(github, moon)]["kind"] == "exposes" and edges[(github, moon)]["label"] == "named in profile"
    assert ("e:username:alexmoon", moon) not in edges
    # moon_dev's 12 accounts are folded under moon_dev, not under alexmoon
    group = next(n for n in nodes.values() if n["kind"] == "group")
    assert group["owner"] == moon and group["count"] == 12 and (moon, group["id"]) in edges
    page = client.get(f"/api/investigations/{investigation}/graph/expand", params={"node": group["id"]}).json()
    assert page["total"] == 12 and all(e["source"] == group["id"] for e in page["edges"] if e["kind"] != "more")
    assert all(e["source"] in nodes and e["target"] in nodes for e in data["edges"])


def test_links_drawn_to_a_lookup_go_to_what_it_looked_up(client, investigation):
    rid = _save(investigation, "whois", "lookup_whois", {"domain": "drawn.test"}, {"email": "a@drawn.test"})
    client.put(f"/api/investigations/{investigation}/graph/state", json={
        "manual_nodes": [{"id": M1, "type": "person", "label": "Jo"}],
        "manual_edges": [{"id": "l:" + "e" * 32, "source": M1, "target": f"r:{rid}", "label": "owns"}]})
    data, _, _ = _graph(client, investigation)
    assert data["state"]["manual_edges"][0]["target"] == "e:domain:drawn.test"


def test_dns_recon_is_in_the_sections_of_its_page(client, investigation):
    _save(investigation, "dns_recon", "lookup_dns_recon", {"domain": "corp.test"}, {
        "domain": "corp.test",
        "whois_info": {"registrar": "Reg", "registrant": "Corp Ltd", "emails": ["admin@corp.test"]},
        "hosting": [{"ip": "93.184.216.34", "asn": "AS1", "as_name": "Host Inc", "country": "US"}],
        "subdomains": [{"name": f"s{i}.corp.test", "ips": ["93.184.216.34"], "resolves": True} for i in range(3)],
        "dns_history": {"virustotal_resolutions": [{"ip": "8.8.4.4", "last_resolved": "2020-01-01"}]},
        "dns_records": {"A": ["93.184.216.35"], "NS": ["ns1.dnshost.test"]},
    })
    _, nodes, edges = _graph(client, investigation)
    sections = {n["label"]: n for n in sorted(nodes.values(), key=lambda n: n.get("rank", 0))
                if n["kind"] == "group" and n.get("section")}
    assert list(sections) == ["Who runs it", "Name servers", "Hosting", "Subdomains", "DNS history",
                              "Current DNS records"]
    assert all(g["owner"] == "e:domain:corp.test" and ("e:domain:corp.test", g["id"]) in edges for g in sections.values())
    assert sections["Subdomains"]["count"] == 3 and sections["Subdomains"]["card"] == "network"
    assert sections["Hosting"]["count"] == 1      # a group even of one: it can be opened, hidden or removed
    # folded: what is in them is not drawn until opened
    assert "e:ip:8.8.4.4" not in nodes
    page = client.get(f"/api/investigations/{investigation}/graph/expand",
                      params={"node": sections["DNS history"]["id"]}).json()
    assert [n["id"] for n in page["nodes"]] == ["e:ip:8.8.4.4"]
    assert page["nodes"][0]["home"] == sections["DNS history"]["id"]
    details = client.get(f"/api/investigations/{investigation}/graph/node",
                         params={"node": sections["Who runs it"]["id"]}).json()
    assert details["node"]["section"] is True and details["lookup"]["service"] == "dns_recon"


def test_ns_domains_are_in_the_same_owner_groups_of_its_page(client, investigation):
    domains = ["a.test", "b.test", "c.test", "d.test", "e.test"]
    rid = _save(investigation, "ns", "lookup_ns", {"ns1": "ns1.host.test", "ns2": "ns2.host.test"}, domains)
    _save(investigation, "ns", "whois_analysis", {"body": {"domains": domains}}, {"domains": {
        "a.test": {"registrant": "Jo Owner", "email": "jo@owner.test"},
        "b.test": {"registrant": "Jo Owner", "email": "jo@owner.test"},
        "c.test": {"registrant": "Privacy service", "email": None},
    }}, parent=rid)
    _save(investigation, "ns", "fingerprint", {"body": {"domains": domains}}, {"domains": {
        "c.test": {"domain": "c.test", "trackers": {"google_analytics": ["G-ABCDEFGH12"]}},
        "d.test": {"domain": "d.test", "trackers": {"google_analytics": ["G-ABCDEFGH12"]}},
    }}, parent=rid)
    _, nodes, _ = _graph(client, investigation)
    groups = sorted((n["label"], n["count"], n.get("confidence")) for n in nodes.values()
                    if n["kind"] == "group" and n.get("section"))
    assert groups == [("Domains", 1, None), ("Group 1 · high same owner", 2, "high"),
                      ("Group 2 · likely same owner", 2, "likely")]
    owner = next(n for n in nodes.values() if n.get("label") == "Group 1 · high same owner")
    assert owner["owner"] == "e:domain:ns1.host.test"
    assert ["WHOIS contact email", "jo@owner.test"] in owner["reasons"]
    page = client.get(f"/api/investigations/{investigation}/graph/expand", params={"node": owner["id"]}).json()
    assert sorted(n["id"] for n in page["nodes"]) == ["e:domain:a.test", "e:domain:b.test"]
    # a domain's WHOIS hangs under it
    domain = client.get(f"/api/investigations/{investigation}/graph/expand", params={"node": "e:domain:a.test"}).json()
    assert [n["card"] for n in domain["nodes"]] == ["registration"]


def test_ns_grouping_is_the_pages():
    """The server's copy of the NS page's grouping (static/js/services/ns_attribution.js)."""
    from services.ns_attribution import build_signals, clusters, parse_whois
    whois = {d: parse_whois({"registrant": "Jo", "email": "jo@x.test"}) for d in ("a.test", "b.test")}
    whois["c.test"] = parse_whois({"error": "timeout"})
    web = {"c.test": {"title": "Shop"}, "d.test": {"title": "Shop"}, "e.test": {"title": "404 Not Found"},
           "f.test": {"title": "404 Not Found"}}
    groups = clusters(build_signals(whois, web))
    assert [(g["domains"], g["confidence"]) for g in groups] == [(["a.test", "b.test"], "high"),
                                                                (["c.test", "d.test"], "possible")]


def test_sections_are_never_folded_into_other_groups(client, investigation):
    # a DNS recon that looked up no identifier, with sections and many other findings beside them
    _save(investigation, "dns_recon", "lookup_dns_recon", {"body": {"x": 1}}, {
        "hosting": [{"ip": f"93.184.216.{i}", "as_name": f"Host {i}"} for i in range(3)],
        "found": [f"user{i}@many.test" for i in range(12)],
    })
    data, nodes, _ = _graph(client, investigation)
    assert [n["label"] for n in nodes.values() if n.get("section")] == ["Hosting"]
