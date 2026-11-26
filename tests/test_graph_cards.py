"""Cards: what each lookup found, one per account / breach record / registration..."""
from uuid import UUID

from services.entities import extract_entities
from services.investigations.cards import build_cards, day, mask, site_id, traits_of


def _record(service, method, parameters, result, children=()):
    return {"result_id": "r1", "service_name": service, "method_name": method, "parameters": parameters,
            "result": result, "timestamp": "2026-01-01T10:00:00", "children": list(children)}



def test_a_username_search_is_one_account_card_per_site_with_what_its_profile_says():
    cards = build_cards(_record("username", "lookup_username", {"username": "jdoe"}, {
        "username": "jdoe",
        "results": [
            {"site_name": "GitHub", "url": "https://github.com/jdoe", "category": "coding", "searched": "jdoe",
             "profile_data": {"fullname": "John Doe", "location": "Kyiv", "email": "jdoe@corp.test",
                              "image": "https://avatars.test/u/1.png"}},
            {"site_name": "Reddit", "url": "https://reddit.com/u/jdoe", "category": "social", "searched": "jdoe"},
        ],
        "mailboxes": [{"provider": "Gmail", "email": "jdoe@gmail.com", "status": "found"}],
        "mailbox_checks": {"not_found": [{"provider": "Yahoo", "domain": "yahoo-not-the-target.test"}]},
    }))
    github, reddit, gmail = cards
    assert github["kind"] == "account" and github["title"] == "GitHub" and github["subtitle"] == "John Doe"
    assert github["key"] == "account:github:jdoe" and github["category"] == "coding"
    assert github["picture"] == "https://avatars.test/u/1.png"
    assert ["Location", "Kyiv"] in github["facts"]
    # what the profile holds is exposed by that account, the account's own address is the card itself
    assert "email:jdoe@corp.test" in github["exposed"] and "url:https://github.com/jdoe" in github["own"]
    assert "email:jdoe@corp.test" not in reddit["exposed"]
    assert github["subject"] == ["username:jdoe"] and "username:jdoe" not in github["exposed"]
    assert gmail["title"] == "Gmail" and gmail["exposed"] == ["email:jdoe@gmail.com"]
    # the providers where nothing was found are not leads
    keys = {e.key for e, _ in extract_entities(_record("username", "", {}, {
        "mailbox_checks": {"not_found": [{"domain": "yahoo-not-the-target.test"}]}})["result"], "username")}
    assert "domain:yahoo-not-the-target.test" not in keys


def test_accounts_found_for_a_followed_username_hang_under_it():
    cards = build_cards(_record("username", "lookup_username", {"username": "jdoe"}, {
        "username": "jdoe", "followed": [{"username": "jd_alt", "depth": 1}],
        "results": [
            {"site_name": "GitHub", "url": "https://github.com/jdoe", "searched": "jdoe",
             "clues": [{"value": "jd_alt", "kind": "username", "strength": "strong"}]},
            {"site_name": "GitLab", "url": "https://gitlab.com/jd_alt", "searched": "jd_alt"},
        ]}))
    github, gitlab = cards
    assert "username:jd_alt" in github["exposed"]
    assert gitlab["under"] == "username:jd_alt" and "under" not in github


def test_oi_splits_accounts_from_breaches_and_the_same_account_has_the_same_key():
    cards = build_cards(_record("oi", "lookup_oi", {"query": "jdoe@corp.test"}, {"modules": [
        {"module": "github", "category": "coding", "domain": "github.com", "username": "jdoe",
         "profile_url": "https://github.com/jdoe", "created": "2015-03-02 10:00"},
        {"module": "linkedin", "breach": True, "name": "LinkedIn", "domain": "linkedin.com", "created": "2012-05-05",
         "fields": [{"label": "Data classes", "value": "Email addresses, Passwords"}]},
        {"module": "spotify", "registered": False},
    ]}))
    account, breach = cards
    assert account["key"] == "account:github:jdoe" and account["date"] == "2015-03-02"
    assert breach["kind"] == "breach" and breach["title"] == "LinkedIn" and breach["date"] == "2012-05-05"
    assert "password" in breach["flags"]
    # the same GitHub account the username search found
    username = build_cards(_record("username", "lookup_username", {"username": "jdoe"}, {
        "username": "jdoe", "results": [{"site_name": "GitHub", "url": "https://github.com/jdoe", "searched": "jdoe"}]}))
    assert username[0]["key"] == account["key"]


def test_a_breach_plugin_card_per_record_with_its_database_and_what_two_records_share():
    result = {"kind": "plugin_result", "plugin": "oathnet", "name": "OathNet", "items": [
        {"title": "jdoe@corp.test", "site": "oathnet.org",
         "fields": [["Dbname", "myfitnesspal.com"], ["Password", "hunter22"], ["City", "Kyiv"],
                    ["Phone number", "+380671234567"]],
         "entities": {"email": ["jdoe@corp.test"], "phone": ["+380671234567"]}},
        {"title": "jdoe@corp.test", "site": "oathnet.org",
         "fields": [["Dbname", "deezer.com"], ["Password", "hunter22"]], "entities": {"email": ["jdoe@corp.test"]}},
        # the answer's own bookkeeping, not a record
        {"title": "OathNet", "site": "oathnet.org", "fields": [["Success", True], ["Plan", "free"]]},
    ]}
    cards = build_cards(_record("oathnet", "run", {"plugin_id": "oathnet", "value": "jdoe@corp.test"}, result))
    assert len(cards) == 2
    fitness, deezer = cards
    assert fitness["kind"] == "breach" and fitness["title"] == "myfitnesspal.com"
    assert fitness["key"] == "breach:myfitnesspal:email:jdoe@corp.test"
    assert fitness["exposed"] == ["phone:+380671234567"]          # the email was what was searched
    assert "password" in fitness["flags"]
    password = [t for t in fitness["traits"] if t[0] == "password"]
    assert password and password == [t for t in deezer["traits"] if t[0] == "password"]
    assert "hunter22" not in str(password) and password[0][2] == mask("hunter22")


def test_a_follow_up_adds_to_the_card_it_follows():
    record = _record("funstat", "lookup_user", {"id": "123456789"},
                     [{"id": 123456789, "username": "jdoe", "first_name": "John", "is_active": True}],
                     children=[{"child_id": "c1", "service_name": "funstat", "method_name": "stats_min",
                                "parameters": {"id": "123456789"}, "timestamp": "2026-01-02T10:00:00",
                                "result": {"first_msg_date": "2019-01-01", "total_msg_count": 50}}])
    user, stats = build_cards(record)
    assert user["key"] == "account:telegram:123456789" and stats["key"] == user["key"]
    assert stats["child_id"] == "c1" and ["Messages", "50"] in stats["facts"]


def test_a_module_without_a_reader_has_no_cards():
    assert build_cards(_record("lookup_ns_whatever", "x", {}, {"domains": ["a.test"]})) == []


def test_cards_follow_the_case(client, investigation):
    from services.investigation_service import investigation_service as service
    inv = UUID(investigation)
    rid = service.save_investigation_result(inv, "username", "lookup_username", {"username": "jdoe"}, {
        "username": "jdoe", "results": [{"site_name": "GitHub", "url": "https://github.com/jdoe", "searched": "jdoe"}]})
    assert [c["key"] for c in service._load_cards(inv)[rid]] == ["account:github:jdoe"]
    service.delete_result(inv, rid)
    assert rid not in service._load_cards(inv)


def test_helpers():
    assert site_id("github.com") == site_id("GitHub") == site_id("https://www.github.com/x") == "github"
    assert site_id("t.me") == "telegram" and site_id("bbc.co.uk") == "bbc"
    assert day("2015-03-02T10:00:00") == "2015-03-02" and day("02.03.2015") == "2015-03-02" and day("abc") is None
    assert traits_of([["Address street", "1 Main St"], ["Hash", "abc"]])[0][0] == "address"


def test_phone_hints_are_words_not_parts_of_words():
    keys = {e.key for e, _ in extract_entities({"telegram": "380671234567", "tel": "+380671234568"})}
    assert keys == {"phone:+380671234568"}


def test_a_privacy_service_is_not_who_registered_a_domain():
    cards = build_cards(_record("ns", "whois_analysis", {"domains": ["a.test", "b.test"]}, {"domains": {
        "a.test": {"registrant": "Privacy service provided by Withheld for Privacy ehf",
                   "email": "a.test@withheldforprivacy.com"},
        "b.test": {"registrant": "John Doe", "email": "john@b.test", "registrar": "Reg"},
    }}))
    assert [(c["title"], c["under"]) for c in cards] == [("John Doe", "domain:b.test")]
