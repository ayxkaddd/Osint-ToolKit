"""Identifiers that appear in more than one investigation."""
from uuid import UUID, uuid4


def _new(client, name):
    data = client.post("/api/investigations/create", data={"name": name}).json()
    return data.get("investigation_id") or data["investigation"]["investigation_id"]


def _seed(inv, email):
    from services.investigation_service import investigation_service as service
    service.save_investigation_result(UUID(inv), "whois", "lookup", {"domain": f"{inv}.test"}, {"email": email})


def test_identifier_in_another_case_is_reported(client):
    domain = f"{uuid4().hex[:8]}.test"   # other tests' cases must not share it
    first, second, third = _new(client, "First case"), _new(client, "Second case"), _new(client, "Third case")
    _seed(first, f"shared.person@{domain}")
    _seed(second, f"shared.person@{domain}")
    _seed(third, f"only.here@other-{domain}")

    response = client.post("/api/entities/elsewhere", json={"exclude": first, "items": [
        {"type": "email", "value": f"Shared.Person@{domain}"},
        {"type": "email", "value": f"only.here@other-{domain}"},
        {"type": "email", "value": "not an email"},
    ]})
    matches = response.json()["matches"]
    assert list(matches) == [f"email:Shared.Person@{domain}"]
    assert [(m["investigation_id"], m["name"]) for m in matches[f"email:Shared.Person@{domain}"]] == [(second, "Second case")]

    # the email and its domain
    entities = client.get(f"/api/investigations/{first}/entities", params={"shared": 1}).json()
    assert entities["shared_count"] == 2
    assert sorted((e["value"], [m["name"] for m in e["elsewhere"]]) for e in entities["entities"]) == [
        (domain, ["Second case"]), (f"shared.person@{domain}", ["Second case"])]
    assert client.get(f"/api/investigations/{third}/entities").json()["shared_count"] == 0


def test_false_positives_dont_count(client):
    first, second = _new(client, "A"), _new(client, "B")
    _seed(first, "fp.person@mail.test")
    _seed(second, "fp.person@mail.test")
    client.patch(f"/api/investigations/{second}/entities", json={"key": "email:fp.person@mail.test",
                                                                  "status": "false_positive"})
    response = client.post("/api/entities/elsewhere", json={"exclude": first, "items": [
        {"type": "email", "value": "fp.person@mail.test"}]})
    assert response.json()["matches"] == {}
