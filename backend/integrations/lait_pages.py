"""Fetching the public course pages.

Deliberately a *separate* HTTP client from `LaitClient`:

* **It never carries the LAIT API key.** The key authorises the API, not the
  website, and a page URL is data from an external payload -- attaching a
  credential to a request whose target that payload chose is how a key leaks.
* **Only https URLs on the allowed hosts are fetched** (`host_allowed`), so a
  poisoned `course_url` cannot make the worker connect to an internal address.
* **Redirects are not followed**, so an allowed host cannot bounce the worker
  elsewhere, and **the body is size-capped**, so a hostile page cannot exhaust
  memory.
"""

from __future__ import annotations

import httpx

from backend.integrations.lait_academic import host_allowed

MAX_PAGE_BYTES = 3 * 1024 * 1024
_USER_AGENT = "lms-lait-sync/1.0 (+course pages)"


class PageFetcher:
    def __init__(
        self,
        allowed_hosts: tuple[str, ...],
        *,
        timeout: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._allowed = allowed_hosts
        self._http = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            transport=transport,
            headers={"User-Agent": _USER_AGENT, "Accept": "text/html"},
        )

    async def __aenter__(self) -> "PageFetcher":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def fetch(self, url: str) -> str | None:
        """The page's HTML, or None for anything that is not a plain 200 from an allowed host."""
        if not host_allowed(url, self._allowed):
            return None
        try:
            async with self._http.stream("GET", url) as response:
                if response.status_code != 200:
                    return None
                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > MAX_PAGE_BYTES:
                        return None
                    chunks.append(chunk)
                return b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")
        except httpx.HTTPError:
            return None
