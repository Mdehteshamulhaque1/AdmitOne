"""Automatic visit reminders (Feature #5).

Background worker entry point: ``python manage.py send_visit_reminders``.

This project does NOT run Celery/Redis — those packages exist in the venv but
are not wired into settings, there is no broker URL and no beat schedule. The
deployment is a plain WSGI host (``config/wsgi.py``), so the simplest
production-appropriate scheduler is cron / a systemd timer invoking the
management command on an interval smaller than the reminder tolerance.
Nothing here depends on a broker, so the exact scheduling cadence is an
operations choice and can be switched to Celery beat later without changing
``send_due_visit_reminders()``.

Design notes
------------
* Reminder timing is configuration on ``Organization.visitor_policies``
  (key ``reminder_offsets_hours``), defaulting to (24, 1). It is never
  hardcoded at a call site.
* Rows are created at booking time via ``schedule_visit_reminders``, one per
  offset, and consumed by the sweep. The unique (visit, offset_hours)
  constraint prevents duplicate delivery.
* All time math is done in the organization's own timezone
  (``accounts.utils.org_timezone``).
* Only active, future, pre-booked visits that are still pending or approved
  are eligible. Rejected / cancelled / checked-out visits are never
  reminded, and an already checked-in visit is skipped.
* Provider failures are caught and written to the reminder row + audit log:
  a bad SMTP day never corrupts the visit workflow or crashes the sweep.
"""

from datetime import datetime

from django.conf import settings
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.utils import timezone

from accounts.utils import org_timezone
from organizations.models import AuditLog

from .emails import EVENT_REMINDER, EmailDeliveryError, deliver, scrub_text
from .models import VisitStatus, VisitReminder

DEFAULT_REMINDER_OFFSETS = (24, 1)
#: A reminder is sent when its trigger time has passed. The sweep must run at
#: least as often as this window for the "1 hour before" reminder to arrive in
#: time; 120 minutes is generous enough for a cron every 5-30 minutes.
REMINDER_SWEEP_WINDOW_HOURS = 2

_ELIGIBLE_REMINDER_STATUSES = (VisitStatus.PENDING, VisitStatus.APPROVED)


def reminder_offsets(org):
    """Configured reminder offsets (hours before start) for an organization.

    Reads ``Organization.visitor_policies["reminder_offsets_hours"]`` so timing
    is data-driven; malformed / missing config falls back to the module
    default reproducibly.
    """
    raw = (getattr(org, "visitor_policies", None) or {}).get(
        "reminder_offsets_hours", DEFAULT_REMINDER_OFFSETS
    )
    try:
        values = [abs(int(h)) for h in raw]
    except (TypeError, ValueError):
        values = list(DEFAULT_REMINDER_OFFSETS)
    values = [h for h in values if h > 0]
    return sorted(set(values)) or list(DEFAULT_REMINDER_OFFSETS)


def visit_slot_start(visit, org=None):
    """Start of the visit appointment as an aware datetime in org local time."""
    org = org or visit.organization
    tz = org_timezone(org)
    return datetime.combine(visit.visit_date, visit.expected_arrival, tzinfo=tz)


def schedule_visit_reminders(visit, now=None):
    """Create PENDING reminder rows for a newly booked visit.

    Idempotent: the unique (visit, offset_hours) constraint means re-running
    (e.g. after a reschedule) updates the trigger instead of duplicating.
    Offsets whose trigger time has already passed are skipped — a reminder
    created ten minutes before arrival must never fire.
    """
    org = visit.organization
    slot_start = visit_slot_start(visit, org)
    now = now or timezone.now()
    for offset in reminder_offsets(org):
        trigger = slot_start - timezone.timedelta(hours=offset)
        if trigger < now:
            continue
        VisitReminder.objects.update_or_create(
            visit=visit,
            offset_hours=offset,
            defaults={"trigger_at": trigger},
        )


def reschedule_visit_reminders(visit, now=None):
    """Re-anchor reminder rows after a visit is rescheduled."""
    VisitReminder.objects.filter(visit=visit).delete()
    schedule_visit_reminders(visit, now=now)


def cancel_visit_reminders(visit):
    """Mark scheduled reminders as skipped when the visit is cancelled."""
    VisitReminder.objects.filter(visit=visit, status=VisitReminder.Status.PENDING).update(
        status=VisitReminder.Status.SKIPPED, error="Visit cancelled."
    )


def _due_reminders(now):
    return (
        VisitReminder.objects.filter(
            status=VisitReminder.Status.PENDING, trigger_at__lte=now
        )
        .select_related("visit__visitor", "visit__organization", "visit__host")
        .order_by("trigger_at")
    )


def _visit_still_eligible(visit, slot_start, now):
    """Reminder is only relevant while the visit is active and still ahead."""
    if visit.status not in _ELIGIBLE_REMINDER_STATUSES:
        return False
    if slot_start <= now:
        return False
    return True


def _audit(reminder, action, extra=""):
    visit = reminder.visit
    AuditLog.log(
        None,
        action,
        entity_type="Visit",
        entity_id=str(visit.visit_id),
        details=(
            f"{visit.visitor.full_name} | {visit.purpose} | "
            f"offset {reminder.offset_hours}h {extra}".strip()
        ),
        # reminder jobs have no actor; take the tenant from the visit
        organization_id=visit.organization_id,
    )


def _send_reminder_email(reminder, slot_start, org):
    visit = reminder.visit
    visitor = visit.visitor
    if not visitor.email:
        reminder.status = VisitReminder.Status.SKIPPED
        reminder.error = "No email address on file."
        reminder.save(update_fields=["status", "error"])
        return False

    subject = f"{org.name}: Reminder for your visit on {visit.visit_date}"
    html = render_to_string(
        "visits/reminder_email.html",
        {
            "visit": visit,
            "organization": org,
            "slot_start": slot_start,
            "offset_hours": reminder.offset_hours,
        },
    )
    message = EmailMessage(
        subject=subject,
        body=html,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[visitor.email],
    )
    message.content_subtype = "html"
    result = deliver(message, event=EVENT_REMINDER, reference=visit.visit_id)
    if not result.sent:
        # Re-raise so the existing caller records this reminder as FAILED with
        # the reason. deliver() deliberately does not raise, because the QR
        # approval path must not abort; here a row per attempt is the audit
        # trail, so a failed send has to reach it.
        raise result.as_exception() or EmailDeliveryError("not delivered")
    reminder.status = VisitReminder.Status.SENT
    reminder.sent_at = timezone.now()
    reminder.error = ""
    reminder.save(update_fields=["status", "sent_at", "error"])
    return True


def _safe_error_text(exc, limit=300):
    """The exception's type and message, with anything sensitive removed.

    The reason a send failed is the whole point of the column, so the message
    is kept -- but SMTP servers frequently echo the recipient address back in
    their reply, and this string is persisted on the reminder row. The scrubbing
    is shared with ``visits.emails`` so there is one implementation, and it runs
    even though ``EmailDeliveryError`` is already scrubbed, because a caller
    could raise something else.
    """
    return scrub_text(f"{type(exc).__name__}: {exc}", limit=limit)


def send_due_visit_reminders(now=None, dry_run=False):
    """Send every pending reminder whose trigger time has passed.

    Returns ``{"attempted", "sent", "skipped", "failed", "ineligible"}``. With
    ``dry_run=True`` reports what would be sent without touching any state.
    Provider failures never raise out of this function.
    """
    now = now or timezone.now()
    summary = {"attempted": 0, "sent": 0, "skipped": 0, "failed": 0, "ineligible": 0}

    for reminder in _due_reminders(now):
        visit = reminder.visit
        org = visit.organization
        slot_start = visit_slot_start(visit, org)
        if not _visit_still_eligible(visit, slot_start, now):
            summary["ineligible"] += 1
            continue

        summary["attempted"] += 1
        if dry_run:
            summary["sent"] += 1
            continue

        try:
            sent = _send_reminder_email(reminder, slot_start, org)
        except Exception as exc:  # pragma: no cover - provably caught below
            reminder.status = VisitReminder.Status.FAILED
            reminder.error = _safe_error_text(exc)
            reminder.save(update_fields=["status", "error"])
            _audit(reminder, "Visit reminder failed")
            summary["failed"] += 1
            continue

        if sent:
            # The visit reference, not the address. A remote SMTP server
            # chooses what its error text says and commonly echoes the
            # recipient back, so writing the address into a log table would
            # spread visitor PII into a second store.
            _audit(
                reminder,
                "Visit reminder sent",
                f"| reference {visit.visit_id}",
            )
            summary["sent"] += 1
        else:
            summary["skipped"] += 1

    return summary