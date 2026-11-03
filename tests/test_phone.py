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
