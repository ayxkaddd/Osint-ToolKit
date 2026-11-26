"""People's names as identifiers: found in results (by field), typed in the lookup box."""
import pytest

from services.entities import extract_entities, make_entity, norm_name


def names(result, service=""):
    return {e.value for e, _ in extract_entities(result, service) if e.type == "name"}


@pytest.mark.parametrize("value,expected", [
    ("John Smith", "John Smith"),
    ("ПЕТРЕНКО Олександр Іванович", "Петренко Олександр Іванович"),
    ("Ім'я Коваль", "Ім'я Коваль"),
    ("Анна-Марія Ковальчук", "Анна-Марія Ковальчук"),
    ("O'BRIEN Sean", "O'Brien Sean"),
    ("Ludwig van Beethoven", "Ludwig van Beethoven"),
    ("J. R. Tolkien", None),               # one full word
    ("Ivan", None),                        # one word
    ("Ivan Petrov 2", None),
    ("Ivаn Petrov", None),                 # a Cyrillic "а" inside a Latin name
    ("Redacted For Privacy", None),
    ("Acme Holdings LLC", None),
    ("ТОВ Ромашка", None),
])
def test_found_names(value, expected):
    assert norm_name(value) == expected


def test_typed_names_only_need_the_shape():
    assert make_entity("name", "redacted for privacy", typed=True).value == "Redacted For Privacy"
    assert make_entity("name", "Redacted For Privacy") is None


def test_names_from_fields():
    assert names({"registrant": {"name": "John Smith", "email": "j@acme.io"},
                  "registrars": [{"name": "Godaddy Com Llc", "first_seen": "2020"}],
                  "tech": {"name": "REDACTED FOR PRIVACY", "email": "x@acme.io"}}, "whois") == {"John Smith"}
    assert names({"id": 123456789, "first_name": "Иван", "last_name": "Петров"}, "funstat") == {"Иван Петров"}
    assert names({"profile": {"names": {"PROFILE": {"fullname": "Jane Doe"}}}}, "ghunt") == {"Jane Doe"}
    assert names({"full_name": "linus torvalds"}, "gitfive") == {"Linus Torvalds"}


def test_a_name_field_alone_is_not_a_person():
    """Sites, registrars and plugins have names too: "name" counts next to a person's fields."""
    assert names({"items": [{"site_name": "Stack Overflow", "name": "Stack Overflow",
                             "url": "https://stackoverflow.com/u/x"}]}, "username") == set()
    assert names({"profile": {"name": "Олена Коваль", "bio": "hi"}}, "username") == {"Олена Коваль"}


def test_free_text_in_module_results_is_not_read_for_names():
    assert names({"bio": "John Smith\nworks at Acme"}, "username") == set()
