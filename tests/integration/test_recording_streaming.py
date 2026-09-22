"""Serving a recording: the bytes, the status and the headers.

`tests/unit/test_range_requests.py` proves the header is parsed. This proves the
response built from it is the one a player needs -- a 206 with a correct
`Content-Range` and exactly the requested bytes -- because a parser that is
right and a response that is wrong look identical from the parser's own tests.

Driven through a real ASGI app over real files on disk, not a mock storage:
seeking is a property of the whole path, and `LocalStorage.open_range` is half
of it.
"""

from __future__ import annotations

import asyncio
import selectors
from pathlib import Path

import pytest
from fastapi import FastAPI, Request, Response
from httpx import ASGITransport, AsyncClient

from backend.api.streaming import stream_for_playback
from backend.storage import factory

PAYLOAD = bytes(range(256)) * 8  # 2048 bytes, every value, so a slice is checkable
KEY = "recordings/sample.bin"


@pytest.fixture()
def client(tmp_path: Path):
    from backend.storage.local import LocalStorage

    storage = LocalStorage(tmp_path)
    (tmp_path / "recordings").mkdir(parents=True, exist_ok=True)
    (tmp_path / KEY).write_bytes(PAYLOAD)

    # The route is a stand-in for `/sessions/{id}/recording/stream`; the
    # authorisation it does is not what is under test here.
    app = FastAPI()

    @app.get("/play")
    async def play(request: Request) -> Response:  # noqa: ANN202
        return await stream_for_playback(request, KEY, filename="class.mp4", mime_type="video/mp4")

    previous = factory.get_storage
    factory.get_storage = lambda: storage  # type: ignore[assignment]
    import backend.api.streaming as streaming
    streaming.get_storage = lambda: storage  # type: ignore[assignment]

    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())

    def call(headers: dict[str, str] | None = None):  # noqa: ANN202
        async def go():  # noqa: ANN202
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
                return await c.get("/play", headers=headers or {})
        return loop.run_until_complete(go())

    try:
        yield call
    finally:
        factory.get_storage = previous  # type: ignore[assignment]
        streaming.get_storage = previous  # type: ignore[assignment]
        loop.close()


def test_no_range_serves_the_whole_file_and_advertises_seeking(client) -> None:
    """`Accept-Ranges` on the first response is how a player learns it may seek
    at all; without it Chrome disables the scrub bar entirely."""
    response = client()
    assert response.status_code == 200
    assert response.headers["accept-ranges"] == "bytes"
    assert response.content == PAYLOAD


def test_a_range_returns_206_and_exactly_those_bytes(client) -> None:
    response = client({"Range": "bytes=100-199"})
    assert response.status_code == 206
    assert response.headers["content-range"] == f"bytes 100-199/{len(PAYLOAD)}"
    assert response.content == PAYLOAD[100:200]


def test_the_tail_request_a_player_makes_to_read_an_index(client) -> None:
    response = client({"Range": "bytes=-64"})
    assert response.status_code == 206
    assert response.content == PAYLOAD[-64:]


def test_an_impossible_range_is_416_and_states_the_real_length(client) -> None:
    """A 416 without the total leaves the player with no way to correct itself,
    so it retries the same bad range forever."""
    response = client({"Range": "bytes=999999-"})
    assert response.status_code == 416
    assert response.headers["content-range"] == f"bytes */{len(PAYLOAD)}"


def test_the_response_is_displayed_not_downloaded_and_not_sniffed(client) -> None:
    """`inline` is what plays it in the page; `nosniff` and the sandbox CSP are
    what stop a file that slipped past a type check being run at this origin."""
    headers = client().headers
    assert headers["content-disposition"].startswith("inline")
    assert headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in headers["content-security-policy"]
    # Permission is re-checked per request, so a cached copy would outlive it.
    assert "no-store" in headers["cache-control"]
