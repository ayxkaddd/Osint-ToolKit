"""Funstat message analysis."""
from services.message_analyzer import MessageAnalyzer


def test_finds_identifiers():
    result = MessageAnalyzer().analyze_message("write me at someone.real@gmail.com or @real_handle_x")
    data = result["extracted_data"]
    assert "someone.real@gmail.com" in data["email"]
    assert "@real_handle_x" in data["telegram_username"]


def test_plain_message_has_no_data():
    assert not MessageAnalyzer().analyze_message("just a normal message")["has_sensitive_data"]


def test_repeated_messages_are_counted_once_each():
    messages = [{"text": "mail me at someone.real@gmail.com", "messageId": i} for i in range(3)]
    result = MessageAnalyzer().analyze_conversation(messages)
    assert result["messages_with_sensitive_data"] == 3
    assert [m["message_id"] for m in result["message_analyses"]] == [0, 1, 2]
