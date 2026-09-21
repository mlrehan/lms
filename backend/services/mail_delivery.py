"""Emailing the copies of a message that has already been delivered inside the LMS.

This runs *after* the message is committed and never inside the request that sent it, so a slow, refusing or
absent mail server cannot fail or delay sending. Each recipient's outcome is written back onto their own
recipient row (SENT, FAILED with a short reason, or SKIPPED), and the sender can see the tally.

What an email contains -- and does not:

* one email per recipient, addressed to that person only (a Bcc'd person's email looks like everybody else's,
  and nobody's email reveals who was Bcc'd);
* the sender's *name*, and the names of the To and Cc people; **no email addresses** anywhere in the body or
  headers, and no Reply-To -- replying happens in the LMS;
* the sanitised body, and the attachments when they fit in one email (otherwise a note that they are in the LMS);
* optionally a copy to the sender's own address.
"""

from __future__ import annotations

import html
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.core.config import MailSettings, get_settings
from backend.core.logging import get_logger
from backend.integrations.smtp import OutgoingAttachment, SmtpMailer, build_email
from backend.models.mail import MailMessage
from backend.services.mail_audience import display_name
from backend.storage import get_storage

logger = get_logger(__name__)

# Above this the attachments stay in the LMS: mail providers refuse large messages, and one refusal would lose the text too.
MAX_EMAIL_ATTACHMENT_BYTES = 8 * 1024 * 1024
_OFF = "Email delivery is switched off."


def _looks_like_address(value: str | None) -> bool:
    return bool(value) and "@" in value and " " not in value and "\n" not in value and "\r" not in value  # type: ignore[operator]


def _names(users) -> str:  # noqa: ANN001
    return ", ".join(display_name(u) for u in users)


def _bodies(message: MailMessage, *, headline: str, recipients_note: str, app_url: str, attachment_note: str) -> tuple[str, str]:
    link = f"{app_url.rstrip('/')}/messages" if app_url else ""
    reply_text = "Reply in the LMS" + (f": {link}" if link else ".") + " Please do not reply to this email."
    text_parts = [headline, recipients_note, "", message.body_text]
    if attachment_note:
        text_parts += ["", attachment_note]
    text_parts += ["", "--", reply_text]

    reply_html = "Reply in the LMS" + (f': <a href="{html.escape(link)}">{html.escape(link)}</a>' if link else ".") + " Please do not reply to this email."
    note_html = f'<p style="color:#666;font-size:12px">{html.escape(attachment_note)}</p>' if attachment_note else ""
    notes = html.escape(recipients_note).replace("\n", "<br>")
    body_html = (
        '<div style="font-family:Arial,sans-serif;font-size:14px;color:#111">'
        f'<p style="margin:0 0 4px 0"><strong>{html.escape(headline)}</strong></p>'
        f'<p style="margin:0 0 16px 0;color:#666;font-size:12px">{notes}</p>'
        f'{message.body_html}{note_html}<hr><p style="color:#666;font-size:12px">{reply_html}</p></div>'
    )
    return "\n".join(text_parts), body_html


async def deliver_message(
    session_factory: async_sessionmaker[AsyncSession], message_public_id, *, settings: MailSettings | None = None, mailer: SmtpMailer | None = None,  # noqa: ANN001
) -> None:
    """Email every recipient (and the sender, if they asked). Never raises: a failure is recorded and logged."""
    settings = settings or get_settings().mail
    mailer = mailer or SmtpMailer(settings)
    try:
        async with session_factory.begin() as session:
            await _deliver(session, message_public_id, settings=settings, mailer=mailer)
    except Exception:  # noqa: BLE001
        logger.exception("Mail delivery crashed")


async def _deliver(session: AsyncSession, message_public_id, *, settings: MailSettings, mailer: SmtpMailer) -> None:  # noqa: ANN001
    message = (await session.execute(select(MailMessage).where(MailMessage.public_id == message_public_id))).scalar_one_or_none()
    if message is None or message.is_draft:
        return
    now = datetime.now(timezone.utc)
    sender = message.sender

    if not mailer.enabled:
        for r in message.recipients:
            if r.email_status == "PENDING":
                r.email_status, r.email_error = "SKIPPED", _OFF
        if message.email_copy_requested:
            message.email_copy_status = "SKIPPED"
        return

    # Attachments travel in the email only when they all fit.
    attachments: list[OutgoingAttachment] = []
    attachment_note = ""
    if message.attachments:
        if sum(a.size for a in message.attachments) <= MAX_EMAIL_ATTACHMENT_BYTES:
            for a in message.attachments:
                data = b"".join([chunk async for chunk in await get_storage().open_stream(a.storage_key)])
                attachments.append(OutgoingAttachment(a.filename, a.content_type, data))
        else:
            attachment_note = f"{len(message.attachments)} attachment(s) were too large to email. Open the message in the LMS to download them."

    visible = [r for r in message.recipients if r.kind == "TO"], [r for r in message.recipients if r.kind == "CC"]
    recipients_note = f"To: {_names(r.user for r in visible[0]) or '—'}" + (f"\nCc: {_names(r.user for r in visible[1])}" if visible[1] else "")
    subject = message.subject or "(no subject)"

    outgoing = []  # (recipient row or None for the sender's copy, EmailMessage)
    for r in message.recipients:
        if r.email_status != "PENDING":
            continue
        address = r.user.email
        if not _looks_like_address(address):
            r.email_status, r.email_error = "SKIPPED", "No email address on file."
            continue
        text, body = _bodies(message, headline=f"{display_name(sender)} sent you a message on the LMS", recipients_note=recipients_note,
                             app_url=settings.app_url, attachment_note=attachment_note)
        outgoing.append((r, build_email(from_name=mailer.from_name, from_address=mailer.from_address, to_name=display_name(r.user), to_address=address,
                                        subject=subject, text_body=text, html_body=body, attachments=attachments)))

    copy_row = None
    if message.email_copy_requested and message.email_copy_status is None:  # not already sent, failed or skipped
        if _looks_like_address(sender.email):
            everyone = f"To: {_names(r.user for r in message.recipients if r.kind == 'TO') or '—'}"
            cc = [r for r in message.recipients if r.kind == "CC"]
            bcc = [r for r in message.recipients if r.kind == "BCC"]
            recipients_for_copy = everyone + (f"\nCc: {_names(r.user for r in cc)}" if cc else "") + (f"\nBcc: {_names(r.user for r in bcc)}" if bcc else "")
            text, body = _bodies(message, headline="A copy of the message you sent on the LMS", recipients_note=recipients_for_copy,
                                 app_url=settings.app_url, attachment_note=attachment_note)
            copy_row = build_email(from_name=mailer.from_name, from_address=mailer.from_address, to_name=display_name(sender), to_address=sender.email,
                                   subject=f"Copy: {subject}", text_body=text, html_body=body, attachments=attachments)
        else:
            message.email_copy_status = "SKIPPED"

    batch = [m for _, m in outgoing] + ([copy_row] if copy_row is not None else [])
    results = await mailer.send_all(batch)
    for (row, _), reason in zip(outgoing, results[: len(outgoing)], strict=True):
        row.emailed_at = now
        row.email_status, row.email_error = ("SENT", None) if reason is None else ("FAILED", reason)
    if copy_row is not None:
        message.email_copy_status = "SENT" if results[-1] is None else "FAILED"
