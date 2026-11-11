"""What a module that can't run yet tells the user: the setting's name as the Settings
page shows it and what to do, never an environment variable name."""
import re

from services.module_registry import setting_label


def modules(client):
    return {m["id"]: m for m in client.get("/api/modules").json()["modules"]}


def test_settings_are_named_like_on_the_settings_page():
    assert setting_label("OSINT_INDUSTRIES_API_KEY") == "OSINT Industries API Key"
    assert setting_label("SERPAPI_KEY") == "SerpAPI Key"
    assert setting_label("GITFIVE_SCRIPT_PATH") == "GitFive Script Path"
    # notes in brackets ("(Optional)", a link) are not part of the name
    assert setting_label("TG_API_ID") == "Telegram API ID"
    assert setting_label("SECURITYTRAILS_API_KEY") == "Security Trails API Key"
    # a key nothing describes still reads as words
    assert setting_label("SOME_NEW_KEY") == "Some new key"


def test_problems_say_what_is_missing_in_words(client):
    blocked = [m for m in modules(client).values() if not m["ready"]]
    assert blocked, "the test setup has no API keys, so some modules need setup"
    for module in blocked:
        assert len(module["setup"]) == len(module["problems"]) > 0
        for fix in module["setup"]:
            assert fix["problem"] in module["problems"]
            assert fix["action"] and fix["href"].split("#")[0] in ("/settings", "/telegram_auth", "/plugins")
            for text in (fix["problem"], fix["action"]):
                assert not re.search(r"\b[A-Z][A-Z0-9]*_[A-Z0-9_]+\b", text), f"{module['id']}: {text}"


def test_missing_key_names_the_field_and_the_action(client):
    oi = modules(client)["oi"]
    assert oi["problems"] == ["OSINT Industries API Key is not set"]
    assert oi["setup"] == [{"problem": "OSINT Industries API Key is not set",
                            "action": "Add the OSINT Industries API Key",
                            "href": "/settings#OSINT_INDUSTRIES_API_KEY"}]


def test_ready_modules_have_nothing_to_set_up(client):
    ready = [m for m in modules(client).values() if m["ready"]]
    assert ready and all(m["setup"] == [] and m["problems"] == [] for m in ready)


def test_telegram_modules_point_to_the_right_page(client):
    vk = modules(client)["vk_profile"]
    assert vk["setup"][0] == {"problem": "The Telegram API ID and hash are not set",
                              "action": "Add the Telegram API ID and hash", "href": "/settings#TG_API_ID"}
