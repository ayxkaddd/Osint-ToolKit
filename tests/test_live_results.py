"""A streamed lookup can be opened while it runs (a background job), before it is saved."""
import asyncio
import json
from typing import Optional

from starlette.responses import StreamingResponse

from utils.investigation_decorator import RESULT_ID_HEADER, save_investigation


def _route(events, skip_if=None):
    @save_investigation(service_name="test_stream", method_name="lookup",
                        stream_reducer=lambda evs: {"items": [e["n"] for e in evs if isinstance(e, dict)]},
                        skip_if=skip_if)
    async def route(value: str, investigation_id: Optional[str] = None):
        async def gen():
            for event in events:
                yield f"data: {json.dumps(event)}\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream")
    return route


def _get(client, investigation, result_id):
    return client.get(f"/api/investigations/{investigation}/results/{result_id}")


def test_running_stream_can_be_opened_and_then_is_saved(client, investigation):
    seen = []

    async def run():
        response = await _route([{"n": 1}, {"n": 2}, {"n": 3}])(value="x", investigation_id=investigation,
                                                              _investigation_request=None, _investigation_response=None)
        result_id = response.headers[RESULT_ID_HEADER]
        before = _get(client, investigation, result_id).json()["result"]   # nothing streamed yet
        assert (before["result"]["items"], before["running"]) == ([], True)
        async for _chunk in response.body_iterator:
            record = _get(client, investigation, result_id).json()["result"]
            seen.append((record["result"]["items"], record.get("running"), record["partial"]))
        return result_id

    result_id = asyncio.run(run())
    assert seen == [([1], True, True), ([1, 2], True, True), ([1, 2, 3], True, True)]
    saved = _get(client, investigation, result_id).json()["result"]
    assert saved["result"]["items"] == [1, 2, 3] and "running" not in saved and saved["partial"] is False
    assert saved["service_name"] == "test_stream" and saved["parameters"]["kwargs"] == {"value": "x"}


def test_running_stream_of_another_investigation_is_not_shown(client, investigation):
    other = client.post("/api/investigations/create", data={"name": "Other"}).json()
    other = other.get("investigation_id") or other["investigation"]["investigation_id"]

    async def run():
        response = await _route([{"n": 1}, {"n": 2}])(value="x", investigation_id=investigation,
                                                      _investigation_request=None, _investigation_response=None)
        result_id = response.headers[RESULT_ID_HEADER]
        async for _chunk in response.body_iterator:
            assert _get(client, other, result_id).status_code == 404
            break
        await response.body_iterator.aclose()
    asyncio.run(run())


def test_stream_with_nothing_to_keep_disappears(client, investigation):
    async def run():
        response = await _route([{"n": 1}], skip_if=lambda result: True)(
            value="x", investigation_id=investigation, _investigation_request=None, _investigation_response=None)
        result_id = response.headers[RESULT_ID_HEADER]
        async for _chunk in response.body_iterator:
            assert _get(client, investigation, result_id).json()["result"]["running"] is True
        return result_id
    assert _get(client, investigation, asyncio.run(run())).status_code == 404


def test_routes_with_generic_parameters_can_be_recorded():
    """list[str] passes isinstance(.., type) on Python 3.10; the decorator must not call issubclass on it."""
    from starlette.requests import Request

    @save_investigation(service_name="t", method_name="m")
    async def route(links: list[str], options: dict[str, int], request: Request):
        return {}

    assert "request" in route.__signature__.parameters and "_investigation_request" not in route.__signature__.parameters
