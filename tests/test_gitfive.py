"""GitFive results: only what GitFive proved is the target's becomes an identifier."""
from uuid import UUID


def _result(generated=500):
    contributor = {"names": {"Someone Else": {"repos": ["r1"]}}, "handle": "x", "domain": "other.test"}
    return {
        "username": "target", "name": "Tar Get", "id": 1, "is_site_admin": False, "is_hireable": False,
        "nb_public_repos": 1, "nb_followers": 0, "nb_following": 0, "created_at": "2020-01-01 00:00:00",
        "updated_at": "2020-01-01 00:00:00", "avatar_url": "https://avatars.test/u/1", "is_default_avatar": False,
        "nb_ext_contribs": 1, "potential_friends": {}, "repos": [], "languages_stats": {}, "usernames": ["target"],
        "domains": [], "ssh_keys": [], "usernames_history": {}, "type": "User",
        # proved: commits made with it land on the target's account
        "emails": ["proven@target.test"],
        "registered_emails": {
            "proven@target.test": {"avatar": "", "full_name": "Tar Get", "username": "target", "is_target": True},
            "guess.taken@gmail.test": {"avatar": "", "full_name": "Not Them", "username": "notthem", "is_target": False},
        },
        # the target's own commits to other people's repositories
        "ext_contribs": {"work@target.test": {**contributor, "domain": "target.test"}},
        # not the target's
        "generated_emails": [f"guess{i}@gmail.test" for i in range(generated)],
        "all_contribs": {f"dev{i}@contributors.test": contributor for i in range(30)},
        "internal_contribs": {"all": {"colleague@corp.test": contributor}, "no_github": {"colleague@corp.test": contributor}},
        "near_names": {"tar": {"related_data": {"near@names.test": {"names": {}, "handle": "near", "domain": "names.test"}}}},
    }


def test_only_proven_addresses_are_identifiers():
    from services.entities import extract_entities
    emails = sorted(e.value for e, _ in extract_entities(_result(), "gitfive") if e.type == "email")
    assert emails == ["proven@target.test", "work@target.test"]
    usernames = {e.value for e, _ in extract_entities(_result(), "gitfive") if e.type == "username"}
    assert "notthem" not in usernames


def test_a_lookup_saves_no_guesses(client, investigation, monkeypatch):
    from routes import gitfive_routes
    from services.investigation_service import investigation_service as service

    async def fake_run(username, refresh=False):
        return _result(), False
    monkeypatch.setattr(gitfive_routes.gitfive_service, "run_gitfive", fake_run)
    client.post("/api/investigations/set", data={"investigation_id": investigation})
    response = client.get("/api/gitfive/query", params={"username": "target"})
    assert response.status_code == 200
    # the module page still gets everything GitFive found
    assert len(response.json()["generated_emails"]) == 500

    record = service.get_result(UUID(investigation), response.headers["X-Investigation-Result-ID"])
    assert "generated_emails" not in record["result"] and record["result"]["generated_emails_count"] == 500
    assert "colleague@corp.test" in record["result"]["internal_contribs"]["all"]      # still shown on the page
    keys = {e["key"] for e in service.get_entities(UUID(investigation)) if e["type"] == "email"}
    assert keys == {"email:proven@target.test", "email:work@target.test"}
    assert client.get(f"/api/investigations/{investigation}/graph").json()["stats"]["identifiers"] < 10


def test_results_saved_before_keep_only_proven_addresses(client, investigation):
    """A GitFive result saved before (with the generated addresses in it) gives the same identifiers."""
    from services.investigation_service import investigation_service as service
    service.save_investigation_result(UUID(investigation), "gitfive", "lookup_gitfive", {"username": "target"}, _result())
    keys = {e["key"] for e in service.get_entities(UUID(investigation)) if e["type"] == "email"}
    assert keys == {"email:proven@target.test", "email:work@target.test"}
