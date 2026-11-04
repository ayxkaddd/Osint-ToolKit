"""Results added by hand: text, identifiers, a date and files from outside the toolkit."""
import hashlib
from pathlib import Path
from uuid import UUID

import pytest

from conftest import png


def _add(client, inv, files=(), **fields):
    data = {"title": "Bot answer", **fields}
    return client.post(f"/api/investigations/{inv}/manual", data=data,
                       files=[("files", f) for f in files] or None)


def _record(client, inv, result_id):
    return client.get(f"/api/investigations/{inv}/results/{result_id}").json()["result"]


def _entities(client, inv):
    return {e["key"] for e in client.get(f"/api/investigations/{inv}/entities").json()["entities"]}


def test_text_identifiers_and_date_are_saved(client, investigation):
    response = _add(client, investigation, source="Leak site", url="https://example.test/page", date="2021-06-15",
                    text="Seen with backup.person@mail.test", identifiers="someone@mail.test\n+14155552671\n??\n")
    assert response.status_code == 201, response.text
    assert response.json()["skipped"] == ["??"]
    record = _record(client, investigation, response.json()["result_id"])
    assert record["service_name"] == "manual" and record["result"]["date"] == "2021-06-15"
    assert {"email:someone@mail.test", "phone:+14155552671", "email:backup.person@mail.test"} <= _entities(client, investigation)
    summary = client.get(f"/api/investigations/{investigation}/results").json()["results"][0]
    assert summary["target"] == "Bot answer" and summary["summary"] == "text · 2 identifiers"
    events = client.get(f"/api/investigations/{investigation}/events").json()["events"]
    assert [(e["date"], e["label"]) for e in events] == [("2021-06-15", "Bot answer")]


def test_pasted_json_is_kept_as_data(client, investigation):
    result_id = _add(client, investigation, text='{"profile": {"email": "json.person@mail.test"}}').json()["result_id"]
    result = _record(client, investigation, result_id)["result"]
    assert result["data"] == {"profile": {"email": "json.person@mail.test"}} and result["text"] is None
    assert "email:json.person@mail.test" in _entities(client, investigation)


def test_files_are_stored_with_their_hash(client, investigation):
    image = png()
    response = _add(client, investigation, files=[("shot.png", image, "image/png"),
                                                  ("dump.txt", b"contact: file.person@mail.test", "text/plain")])
    files = _record(client, investigation, response.json()["result_id"])["result"]["files"]
    assert [f["name"] for f in files] == ["shot.png", "dump.txt"]
    assert files[0]["sha256"] == hashlib.sha256(image).hexdigest() and files[0]["size"] == len(image)
    assert "email:file.person@mail.test" in _entities(client, investigation)
    served = client.get(f"/api/investigations/{investigation}/files/{files[0]['stored']}")
    assert served.content == image and served.headers["content-type"] == "image/png"
    assert served.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize("name", ["page.html", "drawing.svg", "tool.exe", "noext"])
def test_other_files_are_only_downloaded(client, investigation, name):
    response = _add(client, investigation, files=[(name, b"<script>alert(1)</script>", "text/html")])
    stored = _record(client, investigation, response.json()["result_id"])["result"]["files"][0]["stored"]
    served = client.get(f"/api/investigations/{investigation}/files/{stored}")
    assert served.headers["content-type"] == "application/octet-stream"
    assert served.headers["content-disposition"].startswith("attachment")
    assert "sandbox" in served.headers["content-security-policy"]


def test_download_keeps_the_original_name(client, investigation):
    response = _add(client, investigation, files=[("report 2021.pdf", b"%PDF-1.4", "application/pdf")])
    stored = _record(client, investigation, response.json()["result_id"])["result"]["files"][0]["stored"]
    served = client.get(f"/api/investigations/{investigation}/files/{stored}",
                        params={"download": 1, "filename": 'report 2021.pdf"; x="../evil'})
    disposition = served.headers["content-disposition"]
    assert disposition.startswith("attachment") and "report" in disposition
    assert 'x="' not in disposition and "/" not in disposition.replace("%2F", "/").split("filename", 1)[1]


@pytest.mark.parametrize("name", ["../../index.json", "a" * 32, "a" * 32 + ".png.tmp", "x" * 32 + ".png"])
def test_reading_other_files_is_refused(client, investigation, name):
    response = client.get(f"/api/investigations/{investigation}/files/{name}")
    assert response.status_code in (404, 422) and b"result_id" not in response.content


def test_uploaded_names_are_never_paths(client, investigation):
    response = _add(client, investigation, files=[("../../../evil.png", png(), "image/png")])
    files = _record(client, investigation, response.json()["result_id"])["result"]["files"]
    assert files[0]["name"] == "evil.png" and not [p for p in Path(".").rglob("evil*")]


@pytest.mark.parametrize("fields, message", [
    ({"title": ""}, "title"),
    ({}, "Add some"),
    ({"text": "x", "url": "javascript:alert(1)"}, "http"),
    ({"text": "x", "date": "sometime"}, "date"),
])
def test_bad_input_is_refused(client, investigation, fields, message):
    response = _add(client, investigation, **fields)
    assert response.status_code == 400 and message in response.json()["detail"]


def test_files_need_login(anon, client, investigation):
    response = _add(client, investigation, files=[("shot.png", png(), "image/png")])
    stored = _record(client, investigation, response.json()["result_id"])["result"]["files"][0]["stored"]
    assert anon.get(f"/api/investigations/{investigation}/files/{stored}").status_code == 401
    assert anon.post(f"/api/investigations/{investigation}/manual", data={"title": "x", "text": "y"}).status_code == 401


def test_deleting_removes_files_unless_a_note_keeps_a_snapshot(client, investigation):
    from services.investigation_service import investigation_service as service
    inv = UUID(investigation)
    kept, gone = (_add(client, investigation, files=[("a.png", png(), "image/png")]).json()["result_id"] for _ in range(2))
    path = {rid: service.get_file_path(inv, _record(client, investigation, rid)["result"]["files"][0]["stored"])
            for rid in (kept, gone)}
    service.create_snapshot(inv, kept)
    client.post(f"/api/investigations/{investigation}/results/bulk", json={"action": "delete", "result_ids": [kept, gone]})
    assert path[kept].exists() and not path[gone].exists()


def test_moving_takes_the_files_along(client, investigation):
    from services.investigation_service import investigation_service as service
    other = client.post("/api/investigations/create", data={"name": "Other"}).json()
    other = other.get("investigation_id") or other["investigation"]["investigation_id"]
    result_id = _add(client, investigation, files=[("a.png", png(), "image/png")]).json()["result_id"]
    stored = _record(client, investigation, result_id)["result"]["files"][0]["stored"]
    client.post(f"/api/investigations/{investigation}/results/bulk",
                json={"action": "move", "result_ids": [result_id], "target_investigation_id": other})
    assert service.get_file_path(UUID(investigation), stored) is None
    assert client.get(f"/api/investigations/{other}/files/{stored}").status_code == 200


def test_added_under_another_result(client, investigation):
    from services.investigation_service import investigation_service as service
    parent = service.save_investigation_result(UUID(investigation), "whois", "lookup", {"domain": "p.test"}, {})
    for title in ("First", "Second"):
        response = _add(client, investigation, title=title, text="note", parent_result_id=parent)
        assert response.json()["result_id"] == parent
    children = _record(client, investigation, parent)["children"]
    assert [c["parameters"]["title"] for c in children] == ["First", "Second"]
