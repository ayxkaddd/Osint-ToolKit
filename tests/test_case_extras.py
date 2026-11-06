"""Notes that mention identifiers, what changed between runs, the .zip export and the report."""
import io
import json
import zipfile
from uuid import UUID, uuid4

from conftest import png


def _service():
    from services.investigation_service import investigation_service
    return investigation_service


def _entities(client, inv, q):
    return {e["value"]: e for e in client.get(f"/api/investigations/{inv}/entities", params={"q": q}).json()["entities"]}


def test_identifier_rows_list_the_notes_that_mention_them(client, investigation):
    service = _service()
    service.save_investigation_result(UUID(investigation), "whois", "lookup", {"kwargs": {"domain": "noted-site.test"}},
                                      {"email": "Noted.Person@gmail.com"})
    ref = service.create_note(UUID(investigation), "Lead", "Owner is [[email:NOTED.person@gmail.com|the owner]]")
    plain = service.create_note(UUID(investigation), "Domains", "Also check noted-site.test later")
    service.create_note(UUID(investigation), "Other", "nothing to see")
    rows = _entities(client, investigation, "noted")
    assert [n["note_id"] for n in rows["noted.person@gmail.com"]["notes"]] == [str(ref)]
    assert [n["title"] for n in rows["noted-site.test"]["notes"]] == ["Domains"] and str(plain)


def _changes(client, inv, result_id):
    return client.get(f"/api/investigations/{inv}/results/{result_id}/changes").json()["changes"]


def test_a_re_run_shows_what_changed(client, investigation):
    service, inv = _service(), UUID(investigation)
    params = {"kwargs": {"domain": "changing.test"}}
    first = service.save_investigation_result(inv, "whois", "lookup_whois", params, {
        "registrar": "Old Registrar", "emails": ["gone.person@gmail.com", "kept.person@gmail.com"],
        "name_servers": ["ns1.old.test", "ns2.old.test"], "checked_at": "2026-01-01T00:00:00"})
    assert _changes(client, investigation, first) is None   # nothing to compare with yet
    second = service.save_investigation_result(inv, "whois", "lookup_whois", params, {
        "registrar": "New Registrar", "emails": ["kept.person@gmail.com", "new.person@gmail.com"],
        "name_servers": ["ns1.new.test", "ns2.new.test", "ns3.new.test"], "checked_at": "2026-06-01T00:00:00"})
    other = service.save_investigation_result(inv, "whois", "lookup_whois", {"kwargs": {"domain": "unrelated.test"}}, {})
    assert _changes(client, investigation, other) is None   # another query isn't a re-run

    c = _changes(client, investigation, second)
    assert c["previous"]["result_id"] == first and not c["same"]
    assert [e["value"] for e in c["identifiers_added"] if e["type"] == "email"] == ["new.person@gmail.com"]
    assert [e["value"] for e in c["identifiers_removed"] if e["type"] == "email"] == ["gone.person@gmail.com"]
    assert sorted((f["label"], f["before"], f["after"]) for f in c["changed"]) == [
        ("Emails", "gone.person@gmail.com", "new.person@gmail.com"), ("Registrar", "Old Registrar", "New Registrar")]
    servers = next(entry for entry in c["lists"] if entry["path"] == "name_servers[]")
    assert servers["added"] == ["ns1.new.test", "ns2.new.test", "ns3.new.test"]
    assert servers["removed"] == ["ns1.old.test", "ns2.old.test"]
    assert not any("checked" in entry["path"] for entry in c["changed"] + c["lists"])   # lookup times don't count

    same = service.save_investigation_result(inv, "whois", "lookup_whois", params, {
        "registrar": "New Registrar", "emails": ["new.person@gmail.com", "kept.person@gmail.com"],
        "name_servers": ["ns3.new.test", "ns1.new.test", "ns2.new.test"], "checked_at": "2026-07-01T00:00:00"})
    assert _changes(client, investigation, same)["same"] is True   # order and lookup time aside


def test_export_zip_has_the_files(client, investigation):
    image = png()
    client.post(f"/api/investigations/{investigation}/manual", data={"title": "Screenshot"},
                files=[("files", ("shot.png", image, "image/png"))])
    note_image = client.post(f"/api/investigations/{investigation}/note-images",
                             files={"image": ("a.png", png(), "image/png")}).json()["url"].rsplit("/", 1)[1]
    response = client.get(f"/api/investigations/{investigation}/export", params={"format": "zip"})
    assert response.status_code == 200 and response.headers["content-type"] == "application/zip"
    assert response.headers["content-disposition"].startswith("attachment") and ".zip" in response.headers["content-disposition"]
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    names = archive.namelist()
    data = json.loads(archive.read("investigation.json"))
    stored = next(r for r in data["results"] if r["service_name"] == "manual")["result"]["files"][0]["stored"]
    assert archive.read(f"files/{stored}") == image
    assert f"notes/images/{note_image}" in names
    # the JSON export stays as it was
    assert client.get(f"/api/investigations/{investigation}/export").json()["investigation"]["investigation_id"] == investigation


def test_report_has_the_new_sections(client, investigation):
    service, inv = _service(), UUID(investigation)
    domain = f"{uuid4().hex[:8]}.test"
    service.save_investigation_result(inv, "whois", "lookup_whois", {"kwargs": {"domain": domain}},
                                      {"creation_date": "2011-02-03", "email": f"shared.person@{domain}"})
    other = client.post("/api/investigations/create", data={"name": "Another case"}).json()
    other = other.get("investigation_id") or other["investigation"]["investigation_id"]
    service.save_investigation_result(UUID(other), "whois", "lookup", {"kwargs": {"domain": "x.test"}},
                                      {"email": f"shared.person@{domain}"})
    service.save_investigation_result(inv, "dns_recon", "lookup_dns_recon", {"kwargs": {"domain": domain}}, {
        "domain": domain, "intel": {"tracking_ids": [{"kind": "google_analytics_ua", "label": "Google Analytics (UA)",
                                                      "id": "UA-7654321", "names": [f"shop.{domain}"]}]}})
    client.post(f"/api/investigations/{investigation}/manual", data={"title": "Bot answer", "date": "2020-05-01"},
                files=[("files", ("shot.png", png(), "image/png"))])

    page = client.get(f"/api/investigations/{investigation}/report").text
    assert "Shared with other investigations" in page and "Another case" in page
    assert "Added manually" in page and "Bot answer" in page and "shot.png" in page
    sha = next(r for r in client.get(f"/api/investigations/{investigation}/export").json()["results"]
               if r["service_name"] == "manual")["result"]["files"][0]["sha256"]
    assert sha in page
    assert "Tracking IDs" in page and "https://builtwith.com/relationships/tag/UA-7654321" in page
    assert "<h2>Timeline</h2>" in page and "3 Feb 2011" in page and "1 May 2020" in page
    assert "<h2>Lookup log</h2>" in page


def test_report_reads_note_references_and_names_whois(client, investigation):
    service = _service()
    service.save_investigation_result(UUID(investigation), "whois", "lookup_whois", {"kwargs": {"domain": "named.test"}}, {})
    service.create_note(UUID(investigation), "Ref", "Owner [[email:ref.person@gmail.com]] and [[result:abc|the WHOIS]]")
    page = client.get(f"/api/investigations/{investigation}/report", params={"include": "all"}).text
    assert "Owner ref.person@gmail.com and the WHOIS" in page and "[[" not in page
    assert "<b>WHOIS</b>" in page and "WHOIS history" not in page
