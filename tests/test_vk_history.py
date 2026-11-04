"""VK profile history: the bot's answers are streamed as they arrive and saved when it finishes."""
import json
from types import SimpleNamespace

import pytest

ENTRY_2019 = "🌐 История профиля ВКонтакте 05.2019 год\n🆔 id ВКонтакте: 123\n👤 Ф.И.: Ivan Petrov\n🏡 Город: Kazan"
ENTRY_2021 = "🌐 История профиля ВКонтакте 2021 год\n👤 Ф.И.: Ivan Sidorov\n👥 Фолловеры: 42"
PHOTOS = "🏞 Связанные с профилем фото\n▪️ sun9.userapi.com/a.jpg\n▪️ https://sun9.userapi.com/b.jpg"
DONE = "✅ Поиск завершён!"


class FakeBot:
    """Telethon client stand-in: each get_messages call returns the next batch."""

    def __init__(self, batches, fail=None):
        self.batches = [[SimpleNamespace(id=i + 2 + 10 * n, text=t) for i, t in enumerate(batch)]
                        for n, batch in enumerate(batches)]
        self.fail = fail
        self.sent = []

    async def get_entity(self, name):
        if self.fail:
            raise self.fail
        return name

    async def send_message(self, entity, text):
        self.sent.append(text)
        return SimpleNamespace(id=1)

    async def get_messages(self, entity, min_id, reverse):
        return self.batches.pop(0) if self.batches else []


@pytest.fixture
def vk(monkeypatch):
    from routes import telegram_routes
    service = telegram_routes.vk_history_service

    def use(bot):
        async def connect():
            service.client = bot
        monkeypatch.setattr(service, "ensure_client", connect)
        monkeypatch.setattr(service, "poll_interval", 0)
        return bot
    return use


def _stream(client, investigation, user_id="https://vk.com/id123"):
    response = client.get("/api/telegram/search/stream", params={"user_id": user_id, "investigation_id": investigation})
    events = [json.loads(line[5:]) for line in response.text.splitlines() if line.startswith("data:")]
    return response, events


def _saved(client, investigation):
    return [r for r in client.get(f"/api/investigations/{investigation}/results").json()["results"]
            if r["service_name"] == "vk_profile"]


def test_answers_are_streamed_in_order_and_saved(client, investigation, vk):
    bot = vk(FakeBot([[ENTRY_2019], [], ["Daily limit: 2 of 3 left", PHOTOS], [ENTRY_2021, DONE]]))
    response, events = _stream(client, investigation)
    assert response.headers["content-type"].startswith("text/event-stream")
    assert bot.sent == ["123"]
    assert [e["event"] for e in events] == ["started", "entry", "notice", "photos", "entry", "done"]
    assert events[1]["entry"]["full_name"] == "Ivan Petrov" and events[1]["entry"]["year_month"] == "05.2019"
    assert events[3]["photos"] == ["https://sun9.userapi.com/a.jpg", "https://sun9.userapi.com/b.jpg"]
    assert events[-1] == {"event": "done", "complete": True, "count": 2}

    saved = _saved(client, investigation)
    assert len(saved) == 1 and saved[0]["method_name"] == "lookup_vk_profile" and not saved[0]["partial"]
    record = client.get(f"/api/investigations/{investigation}/results/{saved[0]['result_id']}").json()["result"]
    result = record["result"]
    assert [e["full_name"] for e in result["entries"]] == ["Ivan Petrov", "Ivan Sidorov"]
    assert result["entries"][1]["followers"] == 42
    assert result["notices"] == ["Daily limit: 2 of 3 left"] and result["complete"] is True
    assert response.headers["x-investigation-result-id"] == saved[0]["result_id"]


def test_timeout_is_reported_and_kept(client, investigation, vk, monkeypatch):
    from routes import telegram_routes
    monkeypatch.setattr(telegram_routes.vk_history_service, "timeout", 0.2)
    vk(FakeBot([[ENTRY_2019]]))
    _, events = _stream(client, investigation)
    assert events[-1] == {"event": "done", "complete": False, "count": 1}
    result = client.get(f"/api/investigations/{investigation}/results/{_saved(client, investigation)[0]['result_id']}").json()
    assert result["result"]["result"]["complete"] is False


def test_failure_before_any_answer_is_not_saved(client, investigation, vk):
    vk(FakeBot([], fail=ValueError("No user has \"VKInfoRobot\" as username")))
    _, events = _stream(client, investigation)
    assert events[-1]["event"] == "error" and "VKInfoRobot" in events[-1]["detail"]
    assert _saved(client, investigation) == []


def test_bad_target_and_missing_login_get_a_status_code(client, investigation, vk, monkeypatch):
    from routes import telegram_routes
    from utils.telegram_client import TelegramNotAuthorized
    assert _stream(client, investigation, user_id="@")[0].status_code == 400

    async def not_logged_in():
        raise TelegramNotAuthorized("Telegram is not logged in")
    monkeypatch.setattr(telegram_routes.vk_history_service, "ensure_client", not_logged_in)
    response, _ = _stream(client, investigation)
    assert response.status_code == 503 and "not logged in" in response.json()["detail"]
    assert _saved(client, investigation) == []


def test_reducer_marks_a_stopped_search():
    from utils.stream_reducers import reduce_vk_history
    result = reduce_vk_history([{"event": "started"}, {"event": "entry", "entry": {"full_name": "A"}}])
    assert result["stopped"] is True and result["entries"] == [{"full_name": "A"}] and result["complete"] is False
    assert "stopped" not in reduce_vk_history([{"event": "done", "complete": True, "count": 0}])


def test_each_answer_is_sent_before_the_bot_finishes(vk):
    """The stream doesn't wait for the bot: an entry comes out after one poll."""
    import asyncio
    from routes import telegram_routes
    service = telegram_routes.vk_history_service
    bot = vk(FakeBot([[ENTRY_2019], [ENTRY_2021], [DONE]]))
    polls_at_event = []
    calls = {"n": 0}
    get_messages = bot.get_messages

    async def counting(*args, **kwargs):
        calls["n"] += 1
        return await get_messages(*args, **kwargs)
    bot.get_messages = counting

    async def run():
        await service.ensure_client()
        async for event in service.stream_request("123"):
            polls_at_event.append((event["event"], calls["n"]))
    asyncio.run(run())
    assert polls_at_event == [("started", 0), ("entry", 1), ("entry", 2), ("done", 3)]


@pytest.mark.parametrize("events, summary", [
    ([{"event": "started"}, {"event": "entry"}, {"event": "entry"}, {"event": "done", "complete": True, "count": 2}],
     "2 results"),
    ([{"event": "started"}, {"event": "notice", "text": "Daily limit reached"}, {"event": "done", "complete": True, "count": 0}],
     "Daily limit reached"),
    ([{"event": "started"}, {"event": "entry"}, {"event": "done", "complete": False, "count": 1}],
     "1 result (the bot didn't finish in time)"),
])
def test_background_job_progress(events, summary):
    import asyncio
    import httpx
    from services.job_manager import Job, JobManager
    body = "".join(f"data: {json.dumps(e)}\n\n" for e in events)
    transport = httpx.MockTransport(lambda request: httpx.Response(
        200, text=body, headers={"content-type": "text/event-stream", "X-Investigation-Result-ID": "r1"}))
    job = Job(id="j", module_id="vk_profile", module_name="VK", entity_type="vk", value="123", investigation_id="i")

    async def run():
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            await JobManager()._run_stream(client, job, "GET", "/api/telegram/search/stream", {}, {})
    asyncio.run(run())
    assert (job.status, job.summary, job.result_id) == ("done", summary, "r1")


# The bot's real formats (from a lookup), with made-up values
SNAPSHOT_OLD = """🌐 История профиля ВКонтакте 2012 год:
🆔 id ВКонтакте: 100200300
👤 Имя: Пётр pit
👤 Фамилия: Иванов
📧 Контактная эл. почта (был указан в профиле): petr.ivanov@mail.test
📱 Мобильный телефон (был указан в профиле): nokia 3310
☎️ Домашний телефон (был указан в профиле): ----
🟢 ICQ: 123456789
✔️ Контакты (были указаны в профиле): 3310; 123456789"""
SNAPSHOT_2015 = """🌐 История профиля ВКонтакте 2015 год:
👩‍❤️‍👨 Пол: М
ℹ️ Aka: pit
🔗 UserName ВК: petr_test
🗺 Регион: Тестовая область
🔗 WWW: ----
🔗 Домашняя страница: Тестоград
❇️ Интересы: спать
🖥 Фильмы: Фильм один, Фильм два
🏞 Фото: http://cs1.vk.me/a.jpg;http://cs1.vk.me/b.jpg;http://cs1.vk.me/a.jpg;
🦄 Новое поле: что-то"""
SNAPSHOT_2018 = """🌐 История профиля ВКонтакте 03.2018 год:
🔗 URL: vk.com/petr_test
✔️ Фолловеры: 51
🛠 Факультет: Экономический
👨🏻‍💻 Карьера: ООО Тест(Работает в н.в.)
👩‍❤️‍👨 Семья: сын/дочь-Анна;
📆 Последний визит: 16.02.2017 23:08:52(Iphone)"""


def test_every_field_of_a_snapshot_is_kept():
    from services.vk_history_service import VkHistoryService
    parse = VkHistoryService().parse_profile_entry
    old = parse(SNAPSHOT_OLD)
    assert (old.year_month, old.vk_id, old.first_name, old.last_name) == ("2012", "100200300", "Пётр pit", "Иванов")
    assert (old.email, old.mobile_phone, old.icq, old.contacts) == ("petr.ivanov@mail.test", "nokia 3310", "123456789", "3310; 123456789")
    assert old.home_phone is None   # "----" means nothing

    mid = parse(SNAPSHOT_2015)
    assert (mid.gender, mid.aka, mid.username, mid.region, mid.homepage) == ("М", "pit", "petr_test", "Тестовая область", "Тестоград")
    assert mid.website is None and (mid.interests, mid.movies) == ("спать", "Фильм один, Фильм два")
    assert mid.photos == ["http://cs1.vk.me/a.jpg", "http://cs1.vk.me/b.jpg"] and mid.avatar == "http://cs1.vk.me/a.jpg"
    assert mid.other == {"Новое поле": "что-то"}   # labels the parser doesn't know aren't lost

    new = parse(SNAPSHOT_2018)
    assert (new.year_month, new.url, new.followers, new.faculty) == ("03.2018", "https://vk.com/petr_test", 51, "Экономический")
    assert (new.career, new.family) == ("ООО Тест(Работает в н.в.)", "сын/дочь-Анна;")
    assert (new.last_visit, new.device) == ("16.02.2017 23:08:52", "Iphone")


def test_bot_status_lines_are_sorted_out(client, investigation, vk):
    vk(FakeBot([["🕓 Поиск займёт некоторое время...", "✅🚫🤖 Профиль не числится как бот!", SNAPSHOT_OLD,
                 "❌ По этому профилю в 04.2022 году ничего не найдено!", "❌ По этому профилю в 2010 году ничего не найдено!",
                 "❌ По этому профилю объявлений не найдено!", DONE]]))
    _, events = _stream(client, investigation)
    assert [e["event"] for e in events] == ["started", "notice", "entry", "nothing_for", "nothing_for", "notice", "done"]
    saved = _saved(client, investigation)[0]
    result = client.get(f"/api/investigations/{investigation}/results/{saved['result_id']}").json()["result"]["result"]
    assert result["empty_periods"] == ["04.2022", "2010"]
    assert result["notices"] == ["✅🚫🤖 Профиль не числится как бот!", "❌ По этому профилю объявлений не найдено!"]
    keys = {e["key"] for e in client.get(f"/api/investigations/{investigation}/entities").json()["entities"]}
    assert "email:petr.ivanov@mail.test" in keys   # the old profile email is an identifier now
