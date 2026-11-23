"""Errors tell the browser what went wrong, never the request URL (with its API key) or paths."""
import httpx
import pytest
from fastapi import HTTPException

from utils.errors import describe, fail

KEYED_URL = "https://api.example.test/search?api_key=SECRET-KEY-123&q=x"


def _status_error(code=401):
    request = httpx.Request("GET", KEYED_URL)
    return httpx.HTTPStatusError("boom " + KEYED_URL, request=request, response=httpx.Response(code, request=request))


def test_describe_leaves_out_urls_and_keys():
    assert describe(_status_error(401)) == "the service answered HTTP 401"
    assert describe(httpx.ConnectError("x " + KEYED_URL, request=httpx.Request("GET", KEYED_URL))) == \
        "could not reach api.example.test"
    assert describe(httpx.ReadTimeout("slow")) == "no answer in time"
    assert "SECRET" not in describe(OSError(f"cannot open /srv/{KEYED_URL}"))


def test_fail_keeps_messages_meant_for_the_user():
    meant = HTTPException(status_code=401, detail="Add the API key in Settings")
    with pytest.raises(HTTPException) as raised:
        fail("Lookup failed", meant)
    assert raised.value is meant


def test_fail_logs_the_details(caplog):
    try:
        raise _status_error(403)
    except httpx.HTTPStatusError as e:
        with pytest.raises(HTTPException) as raised:
            fail("Lookup failed", e, 502)
    assert raised.value.status_code == 502
    assert raised.value.detail == "Lookup failed: the service answered HTTP 403"
    assert "SECRET-KEY-123" in caplog.text  # the whole error is in the server log


def test_a_failing_lookup_does_not_show_the_key(client, monkeypatch):
    from routes import whois_routes

    async def broken(domain):
        raise _status_error(401)

    monkeypatch.setattr(whois_routes.whois_service, "lookup_whois", broken)
    response = client.get("/api/domain/whois", params={"domain": "example.test"})
    assert response.status_code == 500
    assert "SECRET" not in response.text and "api.example.test" not in response.text
    assert response.json()["detail"] == "WHOIS lookup failed: the service answered HTTP 401"
