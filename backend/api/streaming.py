"""Serving stored bytes for playback, with seeking.

A `<video>` element does not download a file and play it. It asks for a range,
plays it, and asks for the next one -- and when it wants to jump to 40 minutes
in it asks for the bytes at 40 minutes. A server that answers every one of those
with `200` and the whole file makes the scrub bar a lie: the browser restarts
the download from zero each time, and a long recording becomes unwatchable.

So this module answers `Range` properly, and the headers around it are the same
ones `resources.py` documents for inline previews: the bytes are rendered by the
browser, never interpreted as a document at this origin.
"""

from __future__ import annotations

import re
from typing import AsyncIterator
from urllib.parse import quote

from fastapi import Request, Response, status
from fastapi.responses import StreamingResponse

from backend.storage import get_storage

_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")

#: Cap on a single ranged answer. A browser asking for `bytes=0-` means "the
#: rest of the file"; honouring that literally for a two-hour recording pins a
#: worker to one viewer for the whole download. Chunking it back is what the
#: protocol is for -- the player simply asks again.
_MAX_SPAN = 8 * 1024 * 1024

_PLAYBACK_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    # Same reasoning as the resource preview: an opaque origin with no scripts,
    # so a file that slipped past a type allowlist still cannot reach cookies
    # or call the API.
    "Content-Security-Policy": "sandbox; default-src 'none'; media-src 'self'; img-src 'self' data:",
    # Private, and short: the URL is permission-checked on every request, and a
    # shared or long-lived cache would outlive the access that earned it.
    "Cache-Control": "private, no-store",
}


def _parse(header: str | None, total: int) -> tuple[int, int] | None | bool:
    """`(start, end)` inclusive, `None` for no range, `False` for unsatisfiable."""
    if not header:
        return None
    match = _RANGE.match(header.strip())
    if match is None:
        # A multi-range or malformed header. Answering the whole file is the
        # behaviour every client copes with; refusing is not.
        return None

    raw_start, raw_end = match.group(1), match.group(2)
    if raw_start == "" and raw_end == "":
        return None

    if raw_start == "":
        # `bytes=-500` -- the last 500 bytes. Players use this to read a moov
        # atom at the end of an MP4, so it is not a curiosity.
        length = int(raw_end)
        if length <= 0:
            return False
        start = max(0, total - length)
        end = total - 1
    else:
        start = int(raw_start)
        end = int(raw_end) if raw_end else total - 1

    if start >= total or start > end:
        return False

    end = min(end, total - 1, start + _MAX_SPAN - 1)
    return start, end


async def stream_for_playback(
    request: Request,
    key: str,
    *,
    filename: str | None,
    mime_type: str | None,
) -> Response:
    """Serve a stored object inline, honouring `Range`.

    The permission check has already happened at the call site; nothing here
    re-authorises, and nothing here reveals the storage key.
    """
    storage = get_storage()
    total = await storage.size(key)
    safe = quote(filename or "recording")

    headers = dict(_PLAYBACK_HEADERS)
    headers["Accept-Ranges"] = "bytes"
    headers["Content-Disposition"] = f"inline; filename*=UTF-8''{safe}"

    span = _parse(request.headers.get("range"), total)

    if span is False:
        # 416 must state the real length, or the player cannot correct itself.
        return Response(
            status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE,
            headers={**headers, "Content-Range": f"bytes */{total}"},
        )

    if span is None:
        body: AsyncIterator[bytes] = await storage.open_stream(key)
        headers["Content-Length"] = str(total)
        return StreamingResponse(
            body, media_type=mime_type or "application/octet-stream", headers=headers
        )

    start, end = span
    headers["Content-Range"] = f"bytes {start}-{end}/{total}"
    headers["Content-Length"] = str(end - start + 1)
    return StreamingResponse(
        await storage.open_range(key, start, end),
        status_code=status.HTTP_206_PARTIAL_CONTENT,
        media_type=mime_type or "application/octet-stream",
        headers=headers,
    )
