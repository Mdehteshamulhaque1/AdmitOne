"""Visitor-facing helpers: phone masking and the "I'm arriving" signal.

The arrival signal is a notification only. It never checks a visitor in;
entry still goes through the signed-QR gate flow.
"""

from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

from accounts.utils import org_timezone
from organizations.models import AuditLog

from visits.models import Visit, VisitStatus

from .notifications import notify_host_about_visit_event

#: Default "I'm Arriving" window: a visitor may announce arrival from this many
#: minutes before the appointment time up to (and including) the appointment
#: time itself. Configurable per organization via
#: ``Organization.visitor_policies["arriving_window_minutes_before"]``.
DEFAULT_ARRIVING_WINDOW_MINUTES = 60


def mask_phone(phone):
    """Mask a phone for visitor-facing display (e.g. ``******1234``)."""
    phone = (phone or "").strip()
    if len(phone) <= 4:
        return "****"
    return "*" * (len(phone) - 4) + phone[-4:]



def arriving_window_minutes(org):
    """Configured "I'm Arriving" window (minutes before the appointment)."""
    raw = (getattr(org, "visitor_policies", None) or {}).get(
        "arriving_window_minutes_before", DEFAULT_ARRIVING_WINDOW_MINUTES
    )
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return DEFAULT_ARRIVING_WINDOW_MINUTES


def can_mark_arriving(visit, when=None):
    """Server-side eligibility for the "I'm Arriving" action.

    Returns ``(allowed, message)``. Mirrored by the portal serializer so the
    UI never has to guess, but enforcement lives HERE (never on the client).
    """
    when = when or timezone.now()
    if visit.status != VisitStatus.APPROVED:
        return False, "Only approved visits can announce arrival."
    if visit.arriving_at is not None:
        return False, "Arrival notification already sent."
    slot_start = datetime.combine(
        visit.visit_date, visit.expected_arrival, tzinfo=org_timezone(visit.organization)
    )
    window = arriving_window_minutes(visit.organization)
    if when < slot_start - timedelta(minutes=window):
        return False, "Too early to announce your arrival."
    if when > slot_start:
        return False, "The arrival window has passed."
    return True, ""


def mark_visitor_arriving(session, visit, *, now=None, audit_ip=None):
    """Visitor announces "I'm Arriving" for one of their own visits.

    Serialized under a row lock so concurrent taps can never record the
    signal twice. This is a notification/status signal ONLY — it does NOT
    check the visitor in; entry still goes through the existing QR security
    flow. Notifies the internal host through the shared notification service.
    Returns ``(visit, ok, message)``.
    """
    now = now or timezone.now()
    if visit.organization_id != session.organization_id:
        return None, False, "Unable to access this visit."
    if visit.visitor_id != session.visitor_id:
        return None, False, "Unable to access this visit."

    allowed, message = can_mark_arriving(visit, now)
    if not allowed:
        return None, False, message

    with transaction.atomic():
        locked = Visit.objects.select_for_update().get(pk=visit.pk)
        # Re-validate under the lock — status/flag could have changed meanwhile.
        allowed, message = can_mark_arriving(locked, now)
        if not allowed:
            return None, False, message
        locked.arriving_at = now
        locked.arriving_source = "PORTAL"
        locked.save(update_fields=["arriving_at", "arriving_source"])
        AuditLog.log(
            None,
            "Visitor marked arriving",
            entity_type="Visit",
            entity_id=str(locked.visit_id),
            details=(
                f"{locked.visitor.full_name} | {locked.purpose} | "
                f"expected {locked.visit_date} {locked.expected_arrival:%H:%M}"
            ),
            ip_address=audit_ip,
            # portal session, no application user; tenant comes from the visit
            organization_id=locked.organization_id,
        )

    delivered, note = notify_host_about_visit_event(locked, "arriving")
    if not delivered:
        AuditLog.log(
            None,
            "Host arriving notification not delivered",
            entity_type="Visit",
            entity_id=str(locked.visit_id),
            details=f"{locked.visitor.full_name} | {locked.purpose} | {note}",
            organization_id=locked.organization_id,
        )

    return locked, True, "Arrival notification sent."