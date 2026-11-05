"""Results in investigations: bulk delete, move and assessment."""
from uuid import UUID

import pytest


@pytest.fixture
def service():
    from routes.investigation_routes import investigation_service
    return investigation_service


def _results(client, inv):
    return {r["result_id"]: r for r in client.get(f"/api/investigations/{inv}/results").json()["results"]}


def _seed(service, inv, n=4):
    return [service.save_investigation_result(UUID(inv), "whois", "lookup", {"domain": f"site{i}.test"},
                                              {"email": f"owner.name{i}@gmail.com"}) for i in range(n)]


def test_bulk_assessment_keeps_notes(client, service, investigation):
    ids = _seed(service, investigation)
    service.set_result_triage(UUID(investigation), ids[0], None, "keep this note")
    response = client.post(f"/api/investigations/{investigation}/results/bulk",
                           json={"action": "triage", "result_ids": ids[:2], "status": "confirmed"})
    assert response.status_code == 200 and sorted(response.json()["done"]) == sorted(ids[:2])
    results = _results(client, investigation)
    assert results[ids[0]]["triage"]["status"] == "confirmed"
    assert results[ids[0]]["triage"]["note"] == "keep this note"
    assert results[ids[2]]["triage"] is None


def test_bulk_move(client, service, investigation):
    other = client.post("/api/investigations/create", data={"name": "Other"}).json()
    other = other.get("investigation_id") or other["investigation"]["investigation_id"]
    ids = _seed(service, investigation)
    response = client.post(f"/api/investigations/{investigation}/results/bulk",
                           json={"action": "move", "result_ids": ids[:2] + ["nope"], "target_investigation_id": other})
    assert sorted(response.json()["done"]) == sorted(ids[:2])
    assert set(ids[:2]) <= set(_results(client, other)) and not set(ids[:2]) & set(_results(client, investigation))
    # identifiers follow the results
    moved_email = {e["value"] for e in client.get(f"/api/investigations/{other}/entities").json()["entities"]}
    assert "owner.name0@gmail.com" in moved_email


def test_move_to_same_investigation_is_refused(client, service, investigation):
    ids = _seed(service, investigation, 1)
    response = client.post(f"/api/investigations/{investigation}/results/bulk",
                           json={"action": "move", "result_ids": ids, "target_investigation_id": investigation})
    assert response.status_code == 400


def test_bulk_delete_ignores_bad_ids(client, service, investigation):
    ids = _seed(service, investigation)
    response = client.post(f"/api/investigations/{investigation}/results/bulk",
                           json={"action": "delete", "result_ids": ids[:2] + ["../x", "nope", ids[0]]})
    assert sorted(response.json()["done"]) == sorted(ids[:2])
    assert set(_results(client, investigation)) == set(ids[2:])


def test_identifier_lists_follow_new_results(client, service, investigation):
    first = _seed(service, investigation, 1)[0]
    url = f"/api/investigations/{investigation}/entities"
    before = {e["value"] for e in client.get(url).json()["entities"]}
    second = service.save_investigation_result(UUID(investigation), "whois", "lookup", {"domain": "later.test"},
                                               {"email": "later.person@gmail.com"})
    after = {e["value"] for e in client.get(url).json()["entities"]}
    assert "later.person@gmail.com" in after - before
    one = client.get(f"/api/investigations/{investigation}/results/{second}/entities").json()["entities"]
    assert "later.person@gmail.com" in {e["value"] for e in one}
    assert "later.person@gmail.com" not in {
        e["value"] for e in client.get(f"/api/investigations/{investigation}/results/{first}/entities").json()["entities"]}


def test_a_result_says_what_was_looked_up(client, service, investigation):
    result_id = service.save_investigation_result(UUID(investigation), "whois", "lookup", {"kwargs": {"domain": "asked.test"}},
                                                  {"email": "found.person@gmail.com"})
    record = client.get(f"/api/investigations/{investigation}/results/{result_id}").json()["result"]
    assert record["target"] == "asked.test"


def test_identifiers_say_which_results_they_are_in(client, service, investigation):
    result_id = service.save_investigation_result(UUID(investigation), "whois", "lookup", {"kwargs": {"domain": "src.test"}},
                                                  {"email": "source.person@gmail.com"})
    entities = client.get(f"/api/investigations/{investigation}/entities", params={"q": "source.person"}).json()["entities"]
    assert [(s["result_id"], s["role"], s["target"]) for s in entities[0]["sources"]] == [(result_id, "found", "src.test")]


def test_earlier_lookups_of_an_identifier(client, service, investigation):
    result_id = service.save_investigation_result(UUID(investigation), "whois", "lookup", {"kwargs": {"domain": "Looked.test"}}, {})
    lookups = client.get(f"/api/investigations/{investigation}/entities/lookups",
                         params={"type": "domain", "value": "looked.test"}).json()["lookups"]
    assert [(p["result_id"], p["service"]) for p in lookups] == [(result_id, "whois")]
    assert client.get(f"/api/investigations/{investigation}/entities/lookups",
                      params={"type": "domain", "value": "never.test"}).json()["lookups"] == []
    assert client.get(f"/api/investigations/{investigation}/entities/lookups",
                      params={"type": "email", "value": "not an email"}).json()["lookups"] == []
