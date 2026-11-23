"""Send the approved visitor their QR pass on WhatsApp (Meta WhatsApp Cloud API).

Off unless configured. WhatsApp only lets a business start a conversation with
a pre-approved *message template*, so the message is a template with:

* an IMAGE header -- the signed QR pass (the same PNG the email attaches), and
* five body variables, in this order::

      Hello {{1}}, your visit to {{2}} on {{3}} is approved.
      Meeting: {{4}}
      Reference: {{5}}
      Show this QR pass and your original ID at the gate.

Create that template in Meta Business Manager (category "Utility"), then set in
``backend/.env``::

    WHATSAPP_PROVIDER=meta
    WHATSAPP_ACCESS_TOKEN=...            # permanent system-user token
    WHATSAPP_PHONE_NUMBER_ID=...         # the sender number's ID, not the number
    WHATSAPP_TEMPLATE_NAME=visitor_pass_approved
    WHATSAPP_TEMPLATE_LANGUAGE=en

Delivery follows the rest of the notification system: one row per
(visit, "qr_pass_whatsapp") in ``VisitNotification`` so a pass is never sent
twice, failures are recorded instead of raised, and the access token never
appears in a log line or an error message.
"""

import json
import logging
import re
import urllib.error
import urllib.request
import uuid

from django.conf import settings
from django.utils import timezone

from .emails import qr_pass_png_bytes
from .models import VisitNotification

logger = logging.getLogger(__name__)

EVENT_QR_PASS_WHATSAPP = "qr_pass_whatsapp"
GRAPH_URL = "https://graph.facebook.com"
TIMEOUT_SECONDS = 15


def _cfg(name, default=""):
    return str(getattr(settings, name, "") or default).strip()


def whatsapp_configured():
    return (
        _cfg("WHATSAPP_PROVIDER").lower() == "meta"
        and bool(_cfg("WHATSAPP_ACCESS_TOKEN"))
        and bool(_cfg("WHATSAPP_PHONE_NUMBER_ID"))
        and bool(_cfg("WHATSAPP_TEMPLATE_NAME"))
    )


def normalise_phone(raw, country_code="91"):
    """A WhatsApp recipient (digits with country code) or ``None``.

    ``9876543210`` -> ``919876543210``; ``09876543210`` -> ``919876543210``;
    ``+44 7700 900123`` -> ``447700900123``. Anything too short is rejected.
    """
    raw = str(raw or "").strip()
    digits = re.sub(r"\D", "", raw)
    if raw.startswith("+") or raw.startswith("00"):
        digits = digits[2:] if raw.startswith("00") else digits
    elif len(digits) == 11 and digits.startswith("0"):
        digits = country_code + digits[1:]
    elif len(digits) == 10:
        digits = country_code + digits
    return digits if 11 <= len(digits) <= 15 else None


class WhatsAppError(Exception):
    """The Cloud API refused or could not be reached. Message is safe to store."""


class MetaCloudClient:
    """The two Cloud API calls needed: upload the QR image, send the template."""

    def __init__(self, opener=None):
        self.version = _cfg("WHATSAPP_API_VERSION", "v21.0")
        self.phone_number_id = _cfg("WHATSAPP_PHONE_NUMBER_ID")
        self._token = _cfg("WHATSAPP_ACCESS_TOKEN")
        self._open = opener or urllib.request.urlopen

    def _call(self, path, body, content_type):
        req = urllib.request.Request(
            f"{GRAPH_URL}/{self.version}/{self.phone_number_id}/{path}",
            data=body,
            method="POST",
            headers={"Authorization": f"Bearer {self._token}", "Content-Type": content_type},
        )
        try:
            with self._open(req, timeout=TIMEOUT_SECONDS) as resp:
                return json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read() or b"{}").get("error", {}).get("message", "")
            except ValueError:
                detail = ""
            raise WhatsAppError(f"WhatsApp API {exc.code}: {detail or exc.reason}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise WhatsAppError(f"WhatsApp API unreachable: {getattr(exc, 'reason', exc)}") from None

    def upload_png(self, png):
        boundary = uuid.uuid4().hex
        parts = [
            f'--{boundary}\r\nContent-Disposition: form-data; name="messaging_product"\r\n\r\nwhatsapp\r\n'.encode(),
            f'--{boundary}\r\nContent-Disposition: form-data; name="type"\r\n\r\nimage/png\r\n'.encode(),
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="qr-pass.png"\r\nContent-Type: image/png\r\n\r\n'.encode(),
            png,
            f"\r\n--{boundary}--\r\n".encode(),
        ]
        data = self._call("media", b"".join(parts), f"multipart/form-data; boundary={boundary}")
        media_id = data.get("id")
        if not media_id:
            raise WhatsAppError("WhatsApp API did not return a media id for the QR image.")
        return media_id

    def send_template(self, to, media_id, body_values):
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {
                "name": _cfg("WHATSAPP_TEMPLATE_NAME"),
                "language": {"code": _cfg("WHATSAPP_TEMPLATE_LANGUAGE", "en")},
                "components": [
                    {"type": "header", "parameters": [{"type": "image", "image": {"id": media_id}}]},
                    {"type": "body", "parameters": [{"type": "text", "text": v} for v in body_values]},
                ],
            },
        }
        data = self._call("messages", json.dumps(payload).encode(), "application/json")
        if not data.get("messages"):
            raise WhatsAppError("WhatsApp API accepted the request but returned no message id.")
        return data["messages"][0].get("id", "")


def pass_body_values(visit):
    """The five template variables, each kept short and never empty."""
    when = f"{visit.visit_date:%d %b %Y}, {visit.expected_arrival:%H:%M}-{visit.expected_exit:%H:%M}"
    meeting = visit.host.full_name if visit.host_id else "Reception"
    room = getattr(visit.room, "label", "") if getattr(visit, "room_id", None) else ""
    if room:
        meeting = f"{meeting}, room {room}"
    return [
        (visit.visitor.full_name or "Visitor")[:60],
        (visit.organization.name or "the organisation")[:60],
        when,
        meeting[:80],
        str(visit.visit_id)[:8].upper(),
    ]


def _record(visit, status, recipient="", error=""):
    VisitNotification.objects.update_or_create(
        visit=visit,
        event=EVENT_QR_PASS_WHATSAPP,
        defaults={
            "status": status,
            "recipient": recipient,
            "provider": "whatsapp-meta",
            "error": error[:500],
            "sent_at": timezone.now() if status == VisitNotification.Status.SENT else None,
        },
    )


def send_qr_pass_whatsapp(visit, *, client=None):
    """Send the QR pass on WhatsApp. Returns one of: ``"sent"``, ``"already_sent"``,
    ``"not_configured"``, ``"no_phone"``, ``"no_pass"``, ``"failed"``. Never raises."""
    if not whatsapp_configured():
        return "not_configured"
    if VisitNotification.objects.filter(
        visit=visit, event=EVENT_QR_PASS_WHATSAPP, status=VisitNotification.Status.SENT
    ).exists():
        return "already_sent"
    if not hasattr(visit, "qr_pass"):
        return "no_pass"
    to = normalise_phone(visit.visitor.phone, _cfg("WHATSAPP_DEFAULT_COUNTRY_CODE", "91"))
    if not to:
        _record(visit, VisitNotification.Status.FAILED, error="No valid phone number for WhatsApp.")
        return "no_phone"
    try:
        client = client or MetaCloudClient()
        media_id = client.upload_png(qr_pass_png_bytes(visit))
        client.send_template(to, media_id, pass_body_values(visit))
    except WhatsAppError as exc:
        _record(visit, VisitNotification.Status.FAILED, recipient=to, error=str(exc))
        logger.warning("whatsapp qr pass not sent", extra={"event": "whatsapp.qr_pass", "reference": str(visit.visit_id), "outcome": "failed"})
        return "failed"
    except Exception:  # noqa: BLE001 - delivery must never break approval
        logger.exception("whatsapp qr pass crashed", extra={"event": "whatsapp.qr_pass", "reference": str(visit.visit_id)})
        _record(visit, VisitNotification.Status.FAILED, recipient=to, error="Unexpected error while sending.")
        return "failed"
    _record(visit, VisitNotification.Status.SENT, recipient=to)
    logger.info("whatsapp qr pass sent", extra={"event": "whatsapp.qr_pass", "reference": str(visit.visit_id), "outcome": "sent"})
    return "sent"
