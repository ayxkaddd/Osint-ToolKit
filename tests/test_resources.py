"""The external resources list (resources.json): categories, identifier types and search addresses."""
from services.entities import ENTITY_TYPES

CATEGORIES = {"breaches", "accounts", "domains", "infrastructure", "images", "telegram", "companies", "crypto",
              "archives", "other"}


def test_external_resources_are_well_formed(client):
    resources = client.get("/api/resources/").json()["ext_res"]
    assert len(resources) >= 30
    names = [r["name"] for r in resources]
    assert len(names) == len(set(names))
    for r in resources:
        assert r["url"].startswith("https://"), r["name"]
        assert r["category"] in CATEGORIES, r["name"]
        assert r["cost"] in (None, "free", "freemium", "paid"), r["name"]
        assert set(r["types"]) <= set(ENTITY_TYPES), r["name"]
        for kind, address in r["search"].items():
            # opens the site on the identifier: https, with the value in it, for a type it takes
            assert kind in r["types"] and address.startswith("https://") and "{value}" in address, r["name"]


def test_resources_offered_for_common_identifiers(client):
    resources = client.get("/api/resources/").json()["ext_res"]
    offered = {kind for r in resources for kind in r["search"]}
    assert {"domain", "ip", "email", "telegram_username", "crypto_btc", "crypto_eth"} <= offered
