"""Images added to notes: only real images, stored under generated names."""
import re
from pathlib import Path

import pytest

from conftest import png


def _upload(client, inv, data, name="a.png", kind="image/png"):
    return client.post(f"/api/investigations/{inv}/note-images", files={"image": (name, data, kind)})


@pytest.mark.parametrize("name", ["../../../evil.png", "/etc/passwd", "..\\..\\evil.png", ".htaccess", "x" * 300 + ".png"])
def test_upload_names_are_never_used(client, investigation, name):
    response = _upload(client, investigation, png(), name)
    assert response.status_code == 201
    assert re.fullmatch(rf"/api/investigations/{investigation}/note-images/[0-9a-f]{{32}}\.webp", response.json()["url"])
    assert not [p for p in Path(".").rglob("*evil*")] and not Path("/tmp/evil.png").exists()


@pytest.mark.parametrize("data", [
    b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
    b"<html><script>alert(1)</script></html>",
    b"",
])
def test_non_images_are_refused(client, investigation, data):
    assert _upload(client, investigation, data).status_code == 400


def test_payload_after_image_is_dropped(client, investigation):
    response = _upload(client, investigation, png() + b"<script>alert(1)</script>")
    image = client.get(response.json()["url"])
    assert image.headers["content-type"] == "image/webp" and b"script" not in image.content


@pytest.mark.parametrize("name", ["..%2f..%2findex.json", "../../index.json", "a" * 32 + ".webp", "x.webp.tmp"])
def test_reading_other_files_is_refused(client, investigation, name):
    response = client.get(f"/api/investigations/{investigation}/note-images/{name}")
    # the client may resolve "../" itself and reach another route: any refusal is fine, no file content
    assert response.status_code in (404, 422) and b"result_id" not in response.content


def test_images_need_login(anon, client, investigation):
    url = _upload(client, investigation, png()).json()["url"]
    assert anon.get(url).status_code == 401
