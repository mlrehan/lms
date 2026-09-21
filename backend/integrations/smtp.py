"""Sending an email over SMTP (Postmark, in this deployment), built from `MAIL_*` settings.

`smtplib` runs in a worker thread so a slow server never blocks the event loop. Sending is opt-in: unless
`MAIL_ENABLED` is true, `MAIL_SUPPRESS_SEND` is false and a server and sender are configured, `enabled` is false
and callers record the email as skipped rather than pretending to have sent it.

Each recipient gets their own email, addressed to them alone. The sender's *email address* is never put in it:
the From is the platform's configured address, there is no Reply-To, and the body carries names only.
"""

from __future__ import annotations

import asyncio
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr
from typing import Sequence

from backend.core.config import MailSettings

_SMTP_TIMEOUT = 20


@dataclass(frozen=True)
class OutgoingAttachment:
    filename: str
    content_type: str
    data: bytes


def _line(value: str) -> str:
    """A header value on one line: a stray newline in a name or subject must never become a second header."""
    return " ".join((value or "").replace("\r", " ").replace("\n", " ").split())


def build_email(
    *,
    from_name: str,
    from_address: str,
    to_name: str,
    to_address: str,
    subject: str,
    text_body: str,
    html_body: str,
    attachments: Sequence[OutgoingAttachment] = (),
) -> EmailMessage:
    message = EmailMessage()
    message["From"] = formataddr((_line(from_name), from_address))
    message["To"] = formataddr((_line(to_name), to_address))
    message["Subject"] = _line(subject) or "(no subject)"
    message.set_content(text_body or " ")
    message.add_alternative(html_body or "<p></p>", subtype="html")
    for item in attachments:
        maintype, _, subtype = (item.content_type or "application/octet-stream").partition("/")
        message.add_attachment(item.data, maintype=maintype or "application", subtype=subtype or "octet-stream", filename=item.filename)
    return message


class SmtpMailer:
    def __init__(self, settings: MailSettings) -> None:
        self.settings = settings

    @property
    def enabled(self) -> bool:
        s = self.settings
        return bool(s.enabled and not s.suppress_send and s.server and s.from_email)

    @property
    def from_address(self) -> str:
        return self.settings.from_email

    @property
    def from_name(self) -> str:
        return self.settings.from_name

    def _open(self) -> smtplib.SMTP:
        s = self.settings
        if s.ssl:
            client: smtplib.SMTP = smtplib.SMTP_SSL(s.server, s.port, timeout=_SMTP_TIMEOUT, context=ssl.create_default_context())
        else:
            client = smtplib.SMTP(s.server, s.port, timeout=_SMTP_TIMEOUT)
            client.ehlo()
            if s.tls:
                client.starttls(context=ssl.create_default_context())
                client.ehlo()
        if s.username:
            client.login(s.username, s.password.get_secret_value())
        return client

    def _send_all_sync(self, messages: Sequence[EmailMessage]) -> list[str | None]:
        """One connection for the whole batch. Each entry is None on success or a short reason on failure."""
        results: list[str | None] = [None] * len(messages)
        try:
            client = self._open()
        except (OSError, smtplib.SMTPException) as exc:
            return [_reason(exc)] * len(messages)
        try:
            for i, message in enumerate(messages):
                try:
                    client.send_message(message)
                except smtplib.SMTPRecipientsRefused:
                    results[i] = "The address was refused by the mail server."
                except (OSError, smtplib.SMTPException) as exc:
                    results[i] = _reason(exc)
        finally:
            try:
                client.quit()
            except (OSError, smtplib.SMTPException):
                pass
        return results

    async def send_all(self, messages: Sequence[EmailMessage]) -> list[str | None]:
        if not messages:
            return []
        return await asyncio.to_thread(self._send_all_sync, list(messages))


def _reason(exc: Exception) -> str:
    """A short, safe reason: the exception type and SMTP code, never a message that might carry credentials."""
    code = getattr(exc, "smtp_code", None)
    return f"{type(exc).__name__}{f' ({code})' if code else ''}"[:200]
