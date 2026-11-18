"""Email delivery for the QR pass flow (single-use, signed QR)."""

import io
import logging
import re
from dataclasses import dataclass

from django.conf import settings
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from email.mime.image import MIMEImage

import qrcode

from .qrcodes import qr_payload

logger = logging.getLogger(__name__)

# Stable identifiers so log aggregation can alert on a rate without parsing
# free text. These are the event names every delivery failure is tagged with.
EVENT_QR_PASS = "email.qr_pass"
EVENT_REMINDER = "email.reminder"
EVENT_NOTIFICATION = "email.notification"

# Mailer failures are the one place in this codebase where a string we do not
# control ends up in our logs. SMTP error text is written by the remote server
# and routinely echoes the recipient address back, and a misconfiguration
# produces text containing the password. Both patterns are stripped at the
# source rather than relying on log level, because a debug-level logger turned
# on during an incident is exactly when the leak would land.
_EMAIL_IN_TEXT = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_SECRET_IN_TEXT = re.compile(
    r"(?i)\b(pw|pass|password|secret|token|api[-_]?key|authorization)\s*[=:]\s*\S+"
)


def scrub_text(text, limit=300):
    """Remove e-mail addresses and secret-looking pairs from untrusted text."""
    text = _EMAIL_IN_TEXT.sub("[redacted-email]", str(text))
    text = _SECRET_IN_TEXT.sub(r"\1=[redacted]", text)
    return text[:limit]


class EmailDeliveryError(RuntimeError):
    """A message was not delivered.

    Raised by callers that need an exception to drive their own failure
    bookkeeping (the reminder scheduler writes a row per attempt), wrapping the
    backend's error so the original text is still available.
    """


@dataclass(frozen=True)
class DeliveryResult:
    """What happened to one message.

    ``skipped`` separates "there was nothing to send" from "the send failed",
    which a plain bool cannot. Approval reports a different instruction to
    reception depending on which it was, so collapsing them would lose the one
    case that needs a human.
    """

    sent: bool = False
    skipped: bool = False
    reason: str = ""
    error: BaseException | None = None

    @property
    def error_type(self):
        return type(self.error).__name__ if self.error is not None else ""

    def as_exception(self):
        """Re-raise the outcome as ``EmailDeliveryError`` for caller bookkeeping.

        The message is scrubbed because this exception is the string callers
        persist (the reminder scheduler writes it to the reminder row), and the
        underlying error text is attacker- or server-controlled.
        """
        if self.sent or self.skipped:
            return None
        detail = scrub_text(self.error) if self.error else self.reason
        return EmailDeliveryError(f"{self.error_type or 'DeliveryFailed'}: {detail}")


def deliver(message, *, event, reference=""):
    """Send one message and make the outcome observable.

    Never raises. A mailer outage must not take down the workflow that
    triggered the mail; callers that need a failure on the stack use
    ``result.as_exception()``.

    Two outcomes count as failure, and the second is the one that used to slip
    through:

    1. the backend raised, or
    2. ``send()`` returned ``0`` -- accepted by the backend, delivered to
       nobody. Every non-delivering backend Django ships (console, locmem,
       filebased, dummy) does exactly this, so a deployment that fell back to
       the console backend reported success for every message it never sent.

    The failure log carries the event name, the caller's reference and the
    exception *type*. The message is withheld from the WARNING record because
    SMTP error text is written by the remote server and routinely echoes the
    recipient address back; a DEBUG record carries it scrubbed, since
    addresses and secret-looking pairs are stripped at the source rather than
    trusted not to be logged.
    """
    try:
        sent = message.send()
    except Exception as exc:  # noqa: BLE001 - deliberately broad
        logger.warning(
            "email delivery failed",
            extra={
                "event": event,
                "reference": str(reference),
                "error_type": type(exc).__name__,
                "outcome": "failed",
            },
        )
        logger.debug(
            "email delivery error detail: %s", scrub_text(exc)
        )
        return DeliveryResult(error=exc, reason="smtp_error")

    if not sent:
        # No exception, no delivery: the backend swallowed it.
        logger.warning(
            "email accepted but not delivered",
            extra={
                "event": event,
                "reference": str(reference),
                "error_type": "ZeroMessagesSent",
                "outcome": "failed",
                "backend": settings.EMAIL_BACKEND,
            },
        )
        return DeliveryResult(reason="not_delivered")

    logger.info(
        "email delivered",
        extra={"event": event, "reference": str(reference), "outcome": "sent"},
    )
    return DeliveryResult(sent=True)


def qr_pass_png_bytes(visit, box_size=8):
    """Render the visit's signed QR pass as a PNG image (bytes)."""
    img = qrcode.make(qr_payload(visit.qr_pass), box_size=box_size)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def send_qr_pass_email(visit):
    """Email the QR pass to the visitor's address, if one is known.

    Returns a ``DeliveryResult`` that separates "there was nothing to send"
    from "the send failed". This used to raise on SMTP failure and treated
    ``send() == 0`` as success; both are failures that must not look like
    success, because approval mints a single-use pass whose only delivery
    channel is this message. A silent no-op means a visitor standing at
    reception with no way in.
    """
    visitor = visit.visitor
    if not visitor.email:
        return DeliveryResult(skipped=True, reason="no_recipient")
    if not hasattr(visit, "qr_pass"):
        return DeliveryResult(skipped=True, reason="no_qr_pass")

    subject = f"Your SecureGate QR pass for {visit.visit_date}"
    html = render_to_string("visits/qr_pass_email.html", {"visit": visit})

    message = EmailMessage(
        subject=subject,
        body=html,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[visitor.email],
    )
    message.content_subtype = "html"

    image = MIMEImage(qr_pass_png_bytes(visit))
    image.add_header("Content-ID", "<qr_pass>")
    image["Content-Disposition"] = "inline; filename=qr-pass.png"
    message.attach(image)
    return deliver(message, event=EVENT_QR_PASS, reference=visit.visit_id)
