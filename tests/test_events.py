"""Timeline: dates found inside results."""
from uuid import UUID

import pytest

from services.events import extract_events, parse_date


@pytest.mark.parametrize("value, key, expected", [
    ("2019-03-05T00:00:00Z", "created", ("2019-03-05", "day")),
    ("2019-03-05T10:11:12+02:00", "created", ("2019-03-05T08:11:12", "time")),
    (1551780000, "created_at", ("2019-03-05T10:00:00", "time")),
    (1551780000000, "created_at", ("2019-03-05T10:00:00", "time")),
    ("05.03.2019", "date", ("2019-03-05", "day")),
    ("Mar 5, 2019", "date", ("2019-03-05", "day")),
    ("Tue, 05 Mar 2019 10:00:00 GMT", "date", ("2019-03-05T10:00:00", "time")),
    ("2019-03", "date", ("2019-03", "month")),
    ("1990", "birth_year", ("1990", "year")),
    (1990, "birth_year", ("1990", "year")),
])
def test_dates_are_recognised(value, key, expected):
    assert parse_date(value, key) == expected


@pytest.mark.parametrize("value, key", [
    ("hello", "date"), ("2019-13-01", "date"), (42, "created"), (True, "created"), ("1990", "date"),
    (12345, "birth_year"), ("0001-01-01", "date"),
])
def test_non_dates_are_ignored(value, key):
    assert parse_date(value, key) is None


def test_events_have_context_and_skip_lookup_times():
    result = {"accounts": [{"site": "GitHub", "created_at": "2015-06-01T12:00:00Z",
                            "checked_at": "2026-01-01T10:00:00", "search_time_seconds": 1700000000}],
              "first_name": "2019-01-01"}
    events = extract_events(result, "username")
    assert [(e["date"], e["label"], e["context"]) for e in events] == [
        ("2015-06-01T12:00:00", "Created at", {"key": "site", "value": "GitHub"})]
    assert events[0]["section"] == "Accounts"


def test_the_lookup_moment_is_not_an_event():
    events = extract_events({"updated": "2026-01-01T10:00:30"}, "x", lookup_time="2026-01-01T10:00:00")
    assert events == []


def test_many_dates_in_one_list_become_a_series():
    messages = [{"date": f"2020-01-{day:02d}T10:00:00", "text": "hi"} for day in range(1, 29)]
    names = [{"name": "Old name", "date": "2018-05-01"}, {"name": "New name", "date": "2021-07-01"}]
    events = extract_events({"messages": messages, "names_history": names}, "funstat")
    series = [e for e in events if e.get("count")]
    assert len(series) == 1 and series[0]["count"] == 28
    assert (series[0]["date"], series[0]["end"]) == ("2020-01-01T10:00:00", "2020-01-28T10:00:00")
    assert [e["context"]["value"] for e in events if not e.get("count")] == ["Old name", "New name"]


def test_timeline_endpoint_follows_new_follow_ups(client, investigation):
    from services.investigation_service import investigation_service as service
    inv = UUID(investigation)
    result_id = service.save_investigation_result(inv, "whois", "lookup_whois", {"domain": "dated.test"},
                                                  {"creation_date": "2011-02-03", "registrar": "Example Registrar"})
    events = client.get(f"/api/investigations/{investigation}/events").json()["events"]
    assert [(e["date"], e["result_id"], e["target"]) for e in events] == [("2011-02-03", result_id, "dated.test")]
    assert events[0]["context"] == {"key": "registrar", "value": "Example Registrar"}

    service.save_investigation_result(inv, "whois", "lookup_whois_history", {"domain": "dated.test"},
                                      {"records": [{"updatedDate": "2015-04-05"}]}, parent_result_id=result_id)
    events = client.get(f"/api/investigations/{investigation}/events").json()["events"]
    assert [e["date"] for e in events] == ["2015-04-05", "2011-02-03"]
    assert events[0]["child_id"]

    service.delete_result(inv, result_id)
    assert client.get(f"/api/investigations/{investigation}/events").json()["events"] == []


def test_context_comes_from_the_entry_around_the_date():
    result = {"results": [{"site": "GitHub", "profile_data": {"username": "someone", "created_at": "2014-07-09"}},
                          {"site": "Reddit", "profile_data": {"created": 1500000000}}]}
    assert [e["context"]["value"] for e in extract_events(result, "username")] == ["GitHub", "Reddit"]
