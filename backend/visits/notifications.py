"""Provider-based external notification delivery (Features #6, #7, #8).

Single notification system for the whole application:

* ``record_visit_notification`` / ``ensure_visit_notification`` persist one
  delivery row per (visit, event), which is what makes host notifications,
  arrival signals and QR emails idempotent — the same event can never email
  twice, even if approval or a sweep runs again.
* Providers behind a small interface. Email is the wired provider today.
  WhatsApp is deliberately NOT implemented (``WhatsAppProvider`` reports
  "not configured") so the system never claims to have sent a message through
  a channel that has no backend.
* No visitor-visible output here: recipients are internal (hosts) or the
  visitor's own address; nothing exposes employee private data.

Failure handling: provider exceptions are caught and recorded on the delivery
row as FAILED; the call never raises into the visit workflow.
"""

from django.conf import settings
from django.core.mail import EmailMessage

from .emails import EVENT_NOTIFICATION, EmailDeliveryError, deliver
from django.template.loader import render_to_string
from django.utils import timezone

from .models import VisitNotification


class NotificationSendError(Exception):
    """A provider was present but failed to deliver."""


class NotificationNotConfiguredError(Exception):
    """The requested channel has no configured backend."""


class EmailProvider:
    """Django mail delivery (console / SMTP per EMAIL_BACKEND)."""

    name = "email"

    def is_configured(self):
        """Whether this channel can put a message somewhere real.

        The old implementation ended with::

            or settings.EMAIL_BACKEND.startswith("django.core.mail.backends")

        which is a tautology -- every backend Django ships lives in that
        package, console and locmem included -- so this always returned True.
        A production deployment on the console backend therefore reported its
        email channel as healthy while delivering nothing.

        Now it answers the question honestly: a development console backend
        counts (the message lands in the terminal, which is the intended local
        workflow), and a backend that silently discards mail does not.
        """
        if settings.EMAIL_BACKEND in settings.NON_DELIVERING_EMAIL_BACKENDS:
            return settings.ENVIRONMENT != "production"
        return bool(settings.EMAIL_HOST or settings.DEFAULT_FROM_EMAIL)

    def send(self, *, to, subject, html, from_email=None):
        message = EmailMessage(
            subject=subject,
            body=html,
            from_email=from_email or settings.DEFAULT_FROM_EMAIL,
            to=[to],
        )
        message.content_subtype = "html"
        # Raises EmailDeliveryError on failure, which the caller already
        # records as a failed delivery row -- so a send that the backend
        # accepted but dropped is no longer reported as a success.
        result = deliver(message, event=EVENT_NOTIFICATION, reference=subject[:60])
        if not result.sent:
            raise result.as_exception() or EmailDeliveryError("not delivered")


class WhatsAppProvider:
    """WhatsApp channel abstraction.

    SecureGate ships WITHOUT a WhatsApp backend, so this provider is never
    "configured" — code that calls it must treat that as an explicit, safe
    "WhatsApp provider not configured" outcome instead of pretending a
    message was sent.
    """

    name = "whatsapp"

    def is_configured(self):
        return False

    def send(self, **kwargs):
        raise NotificationNotConfiguredError("WhatsApp provider not configured.")


def default_email_provider():
    configured = getattr(settings, "NOTIFICATION_EMAIL_PROVIDER", None)
    if configured == "whatsapp":
        return WhatsAppProvider()
    return EmailProvider()


def record_visit_notification(visit, event, *, recipient="", status, provider="", error=""):
    """Create a delivery row, ignoring a race that already created it."""
    row, created = VisitNotification.objects.get_or_create(
        visit=visit,
        event=event,
        defaults={
            "recipient": recipient,
            "status": status,
            "provider": provider,
            "error": error,
            "sent_at": timezone.now() if status == VisitNotification.Status.SENT else None,
        },
    )
    if not created:
        return row, False
    return row, True


def _has_notification(visit, event, terminal_statuses=None):
    """True when this (visit, event) was already handled terminally."""
    terminal_statuses = terminal_statuses or {
        VisitNotification.Status.SENT,
        VisitNotification.Status.NOT_CONFIGURED,
    }
    return VisitNotification.objects.filter(
        visit=visit, event=event, status__in=terminal_statuses
    ).exists()


def notify_host_about_visit_event(visit, event, *, now=None, provider=None):
    """Notify the internal host about a visit event (Features #6/#7).

    Returns ``(delivered: bool, note: str)``. Never raises. Deduplicated by
    (visit, event) so the same event processed twice cannot email twice.
    Reuses the existing Django mail stack; recipient is the host employee's
    real address from the database — nothing is hardcoded and no employee
    contact detail is exposed to visitors.
    """
    provider = provider or default_email_provider()
    host = visit.host
    if host is None or not getattr(host, "email", ""):
        return False, "No host assigned or host has no email address."

    if _has_notification(visit, event):
        return False, "Notification already delivered for this event."

    subject = _host_subject_for_event(visit, event)
    if subject is None:
        return False, f"Unknown host notification event: {event}"

    html = render_to_string(
        "visits/host_visit_event_email.html",
        {"visit": visit, "event": event, "subject": subject},
    )
    try:
        provider.send(to=host.email, subject=subject, html=html)
    except NotificationNotConfiguredError:
        record_visit_notification(
            visit, event,
            recipient=host.email,
            status=VisitNotification.Status.NOT_CONFIGURED,
            provider=provider.name,
        )
        return False, f"{provider.name} provider not configured."
    except Exception as exc:
        record_visit_notification(
            visit, event,
            recipient=host.email,
            status=VisitNotification.Status.FAILED,
            provider=provider.name,
            error=f"{type(exc).__name__}: {exc}",
        )
        return False, "Host notification delivery failed."

    record_visit_notification(
        visit, event,
        recipient=host.email,
        status=VisitNotification.Status.SENT,
        provider=provider.name,
    )
    return True, "Host notified."


def _host_subject_for_event(visit, event):
    org = visit.organization
    if event == "booking_submitted":
        return f"{org.name}: A visitor pre-booking needs your attention"
    if event == "approved":
        return f"{org.name}: Visit approved (visitor arrives {visit.visit_date})"
    if event == "arriving":
        return f"{org.name}: {visit.visitor.full_name} is arriving for your visit"
    if event == "cancelled":
        return f"{org.name}: A visit with you has been cancelled"
    if event == "rescheduled":
        return f"{org.name}: A visit with you has been rescheduled"
    return None