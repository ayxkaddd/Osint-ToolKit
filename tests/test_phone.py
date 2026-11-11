"""Phone analysis runs in a helper process, so the server never loads the location tables."""
import subprocess
import sys


def test_lookup(client):
    response = client.get("/api/phone/info", params={"phone": "+380501234567"})
    assert response.status_code == 200
    data = response.json()
    assert data["e164"] == "+380501234567" and data["carrier"] and data["location"] == "Ukraine"


def test_invalid_numbers(client):
    for value in ["abc", "$(touch /tmp/pwned)", "--help", "+0000000"]:
        assert client.get("/api/phone/info", params={"phone": value}).status_code == 400


def test_server_does_not_load_location_tables():
    code = ("import sys; sys.path.insert(0, '.');"
            "from services.phone_service import search_formats;"
            "assert search_formats('+380501234567');"
            "assert 'phonenumbers.geocoder' not in sys.modules")
    from conftest import REPO
    subprocess.run([sys.executable, "-c", code], cwd=REPO, check=True)


def test_number_without_country_code_is_not_guessed(client):
    """415 555 2671 used to be read as +41 55552671 (Switzerland)."""
    for value in ["4155552671", "(415) 555-2671", "415-555-2671"]:
        response = client.get("/api/phone/info", params={"phone": value})
        assert response.status_code == 400, value
        detail = response.json()["detail"]
        assert "no country code" in detail and "+1 415-555-2671 (United States / Canada)" in detail


def test_number_without_country_code_offers_the_readers_country_first(client):
    response = client.get("/api/phone/info", params={"phone": "0501234567"}, headers={"Accept-Language": "uk-UA"})
    assert response.json()["detail"].startswith("This number has no country code - it could be +380 50 123 4567 (Ukraine)")


def test_full_number_without_plus_is_analyzed(client):
    for value in ["380501234567", "00380501234567", "+380 (50) 123-45-67"]:
        response = client.get("/api/phone/info", params={"phone": value})
        assert response.status_code == 200 and response.json()["e164"] == "+380501234567", value


def test_refused_number_is_not_saved(client, investigation):
    client.post("/api/investigations/set", data={"investigation_id": investigation})
    before = client.get(f"/api/investigations/{investigation}/results").json()["results_count"]
    assert client.get("/api/phone/info", params={"phone": "4155552671"}).status_code == 400
    assert client.get(f"/api/investigations/{investigation}/results").json()["results_count"] == before
