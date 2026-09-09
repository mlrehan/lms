"""Actually sending a webhook.

Kept apart from the service layer because this is the only code in the
platform that makes an **outbound** network call on behalf of institution
configuration, and the constraints are network constraints rather than
business ones.

**Redirects are not followed.** A receiver that answers `302 Location:
http://169.254.169.254/` would otherwise walk the request straight past
`assert_safe_url`, which validated the address the *original* URL resolved
to. Following redirects safely would mean re-validating each hop; refusing
them is simpler, and a webhook receiver has no legitimate reason to redirect.

**The response body is read but bounded and discarded.** The delivery is a
notification, not a request for data — nothing downstream consumes what the
receiver says. Only the status code and, on failure, a truncated first line
are kept, so a receiver returning a megabyte of HTML cannot turn an error
column into a storage problem.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

import httpx

from backend.core.logging import get_logger
from backend.integrations.signing import (
    DELIVERY_HEADER,
    EVENT_HEADER,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    signature_for,
)
from backend.integrations.url_safety import UrlRejected, assert_safe_url

logger = get_logger(__name__)

CONNECT_TIMEOUT = 5.0
READ_TIMEOUT = 10.0
MAX_RESPONSE_BYTES = 8192
USER_AGENT = "LMS-Webhook/1.0"


@dataclass(frozen=True)
class DeliveryResult:
    ok: bool
    status_code: int | None
    error: str | None = None

    @property
    def retryable(self) -> bool:
        """Whether trying again could plausibly succeed.

        A 4xx other than 408/429 means the receiver understood and refused;
        repeating it just spends both sides' resources on the same answer.
        A timeout, a connection failure or a 5xx is worth another go.
        """
        if self.ok:
            return False
        if self.status_code is None:
            return True  # transport failure
        if self.status_code in (408, 429):
            return True
        return self.status_code >= 500


async def deliver(
    *,
    url: str,
    secret: str,
    event: str,
    payload: dict,
    delivery_id: str,
) -> DeliveryResult:
    """POST one signed event. Never raises; the result is the report.

    The URL is re-validated here rather than trusted from the stored row:
    validation at save time proves something about the moment somebody
    clicked save, and a hostname's DNS can change afterwards.
    """
    try:
        safe_url = assert_safe_url(url)
    except UrlRejected as rejected:
        return DeliveryResult(ok=False, status_code=None, error=str(rejected)[:500])

    # `separators` pinned so the bytes signed are stable and byte-identical
    # to the bytes sent -- a re-serialisation with different spacing would
    # produce a body the signature does not cover.
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    timestamp = int(time.time())

    headers = {
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
        EVENT_HEADER: event,
        DELIVERY_HEADER: delivery_id,
        TIMESTAMP_HEADER: str(timestamp),
        SIGNATURE_HEADER: signature_for(secret=secret, timestamp=timestamp, body=body),
    }

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(READ_TIMEOUT, connect=CONNECT_TIMEOUT),
            follow_redirects=False,
            max_redirects=0,
        ) as client:
            response = await client.post(safe_url, content=body, headers=headers)
    except httpx.TimeoutException:
        return DeliveryResult(ok=False, status_code=None, error="Timed out.")
    except httpx.HTTPError as exc:
        return DeliveryResult(
            ok=False, status_code=None, error=f"{type(exc).__name__}: {exc}"[:500]
        )

    if 200 <= response.status_code < 300:
        return DeliveryResult(ok=True, status_code=response.status_code)

    detail = response.text[:MAX_RESPONSE_BYTES].strip().splitlines()
    return DeliveryResult(
        ok=False,
        status_code=response.status_code,
        error=(detail[0][:400] if detail else f"HTTP {response.status_code}"),
    )
