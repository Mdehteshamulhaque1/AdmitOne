"""
Core visitor workflow operations.

Registered -> Pending -> Approved/Rejected -> QR issued -> Checked In -> Checked Out -> Archived

Kept in a service layer so both the server-rendered views and the DRF API
call the exact same logic (single source of truth).  All state transitions
are serialized with ``select_for_update`` inside a transaction so concurrent
scans/actions cannot corrupt the workflow or double-use a QR pass.
"""

import logging
from datetime import date, datetime, time as time_class

from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts.models import User
from accounts.utils import org_localdate
from organizations.models import AuditLog, Building, Department, Employee, Floor
from visits.models import QRPass, Visit, VisitSource, VisitStatus, VisitType, Visitor

from .availability import host_blocks_for, intervals_overlap, validate_booking_slot
from .emails import send_qr_pass_email
from .purposes import OTHER_LABEL, PURPOSE_OTHER_MAX, purposes_for, purposes_for_category
from .reminders import (
    cancel_visit_reminders,
    reschedule_visit_reminders,
    schedule_visit_reminders,
)

logger = logging.getLogger(__name__)


def _notify_host(visit, event):
    """Best-effort host e-mail for a visit event; never raises into the workflow.

    Imported lazily because ``notifications`` imports ``emails`` which imports
    this module's models; keeping the edge lazy avoids an import cycle.
    """
    from .notifications import notify_host_about_visit_event

    try:
        delivered, note = notify_host_about_visit_event(visit, event)
    except Exception:  # pragma: no cover - provider bug must not break the visit
        logger.exception("host notification crashed", extra={"event": event})
        return
    if not delivered:
        AuditLog.log(
            None,
            f"Host {event} notification not delivered",
            entity_type="Visit",
            entity_id=str(visit.visit_id),
            details=f"{visit.visitor.full_name} | {visit.purpose} | {note}",
            organization_id=visit.organization_id,
        )

_VISITOR_WRITABLE = {
    # ``organization`` is deliberately excluded: the tenant key is never
    # client-writable, it is always derived from the acting user's org.
    f.name
    for f in Visitor._meta.get_fields()
    if f.concrete and f.editable and not f.primary_key and f.name != "organization"
}


def log_visit_event(user, action, visit, extra="", ip=None):
    """Append the audit row for a visit mutation.

    Callers must invoke this *inside* the same ``transaction.atomic()`` block
    that made the change, so the entry and the mutation commit or roll back
    together.  Logging after the block is what made a rollback leave a record of
    a state change that never happened.
    """
    AuditLog.log(
        user=user,
        action=action,
        entity_type="Visit",
        entity_id=str(visit.visit_id),
        details=f"{visit.visitor.full_name} | {visit.purpose} {extra}".strip(),
        ip_address=ip,
        # the actor may be a portal/session-less caller, and a visit belongs to
        # exactly one workspace: take the tenant from the visit itself.
        organization_id=visit.organization_id,
    )


def _user_allowed(user, visit):
    """Cross-tenant guard: the acting user must belong to the visit's org."""
    if user is None or getattr(user, "is_superuser", False):
        return True
    org = getattr(user, "organization", None)
    if org is None:
        return False
    return org.pk == visit.organization_id


def _time_or_none(value):
    """Normalize ``%H:%M`` strings / time objects to a ``datetime.time``."""
    if isinstance(value, time_class):
        return value
    if isinstance(value, str):
        try:
            hour, minute = value.strip().split(":")
            return time_class(int(hour), int(minute))
        except (ValueError, TypeError):
            return None
    return None


def approve_visit(visit, approver):
    if not _user_allowed(approver, visit):
        return False, "You do not have access to this visit."
    with transaction.atomic():
        locked = Visit.objects.select_for_update().get(pk=visit.pk)
        if locked.status != VisitStatus.PENDING:
            return False, f"Cannot approve: visit is {locked.status}."
        if locked.visitor.is_blacklisted:
            return False, "Visitor is blacklisted. Approval blocked."
        locked.status = VisitStatus.APPROVED
        locked.approved_at = timezone.now()
        locked.save(update_fields=["status", "approved_at"])
        QRPass.issue(locked)
        log_visit_event(approver, "Visit approved", locked)
    emailed = send_qr_pass_email(locked)
    # WhatsApp is an extra channel: it never blocks or fails an approval.
    from .whatsapp import send_qr_pass_whatsapp

    whatsapp = send_qr_pass_whatsapp(locked)
    if whatsapp == "sent":
        if emailed.sent:
            return True, "Visit approved. QR pass generated, emailed and sent on WhatsApp."
        return True, "Visit approved. QR pass generated and sent to the visitor on WhatsApp."
    if emailed.sent:
        return True, "Visit approved. QR pass generated and emailed to the visitor."
    if emailed.skipped:
        return True, (
            "Visit approved. QR pass generated, but the visitor has no email "
            "address on file, so it was not sent."
        )
    # The pass exists and is valid, but the only automatic delivery channel did
    # not work. Saying so is the difference between a visitor at the desk with
    # no way in and someone who prints the pass or rings the visitor.
    logger.warning(
        "QR pass generated but not emailed",
        extra={
            "event": "email.qr_pass.approval_report",
            "reference": str(locked.visit_id),
            "error_type": emailed.error_type,
            "outcome": "failed",
        },
    )
    return (
        True,
        "Visit approved. QR pass generated, but emailing it FAILED. "
        "Print the pass or contact the visitor another way.",
    )


def reject_visit(visit, approver, reason="Not specified"):
    if not _user_allowed(approver, visit):
        return False, "You do not have access to this visit."
    reason = str(reason or "").strip()
    if len(reason) > 300:
        return False, "Rejection reason is too long (maximum 300 characters)."
    if not reason:
        reason = "Not specified"
    with transaction.atomic():
        locked = Visit.objects.select_for_update().get(pk=visit.pk)
        if locked.status != VisitStatus.PENDING:
            return False, f"Cannot reject: visit is {locked.status}."
        if locked.visitor.is_blacklisted:
            return False, "Visitor is blacklisted. Rejection request blocked."
        locked.status = VisitStatus.REJECTED
        locked.rejected_at = timezone.now()
        locked.rejection_reason = reason or ""
        locked.save(update_fields=["status", "rejected_at", "rejection_reason"])
        log_visit_event(approver, "Visit rejected", locked, extra=f"| reason: {reason}")
    return True, "Visit rejected."


def check_in(visit, officer, via_qr=False):
    if not _user_allowed(officer, visit):
        return False, "You do not have access to this visit."
    with transaction.atomic():
        locked = Visit.objects.select_for_update().get(pk=visit.pk)
        if via_qr:
            # A passed QR gate is the automated admission control: only
            # host-approved visits may enter on a pass (a badge must never
            # admit visitors whose visit is still PENDING).
            if locked.status != VisitStatus.APPROVED:
                return False, f"Cannot check in via QR: visit is {locked.status}, not APPROVED."
        elif locked.status not in (VisitStatus.APPROVED, VisitStatus.PENDING):
            return False, f"Cannot check in: visit is {locked.status}."
        if locked.visitor.is_blacklisted:
            return False, "Visitor is blacklisted - entry denied."
        qr = None
        now = timezone.now()
        if via_qr:
            # Re-verify the pass under the lock so two concurrent scans cannot
            # both consume the same single-use pass.
            qr = QRPass.objects.select_for_update().filter(visit=locked).first()
            if qr is None:
                return False, "No QR pass issued for this visit. Check in via desk instead."
            # The claim itself is a single conditional UPDATE, and *that* is the
            # guarantee -- not the row lock above. ``select_for_update()`` is a
            # silent no-op on SQLite (``has_select_for_update`` is False), so on
            # that backend the lock protects nothing and two simultaneous scans
            # would both read is_used=False and both admit the visitor. The
            # WHERE clause is re-evaluated when the write is applied, so exactly
            # one concurrent transaction can flip is_used False -> True; the
            # loser updates 0 rows and is rejected. This holds on every backend
            # we support, and the row lock is then only an optimisation that
            # avoids the wasted UPDATE.
            #
            # expires_at is in the predicate too, so a pass that lapses between
            # the read and the write cannot be consumed in the gap.
            if qr.is_used:
                return False, "This pass has already been used - duplicate entry blocked."
            if qr.is_expired:
                return False, "This pass has expired. Reapprove the visit to issue a fresh pass."
            claimed = QRPass.objects.filter(
                pk=qr.pk, is_used=False, expires_at__gt=now
            ).update(is_used=True, used_at=now)
            if claimed != 1:
                # Re-read to say *why* it failed; the row is locked so this is
                # the post-race state.
                qr.refresh_from_db()
                if qr.is_used:
                    return False, "This pass has already been used - duplicate entry blocked."
                if qr.is_expired:
                    return False, "This pass has expired. Reapprove the visit to issue a fresh pass."
                return False, "This pass could not be redeemed - please scan again."
        locked.status = VisitStatus.CHECKED_IN
        locked.checked_in_at = now
        locked.checked_in_by = officer
        locked.save(update_fields=["status", "checked_in_at", "checked_in_by"])
        log_visit_event(officer, "Visitor checked in", locked)
    return True, "Visitor checked in."


def check_out(visit, officer):
    if not _user_allowed(officer, visit):
        return False, "You do not have access to this visit."
    with transaction.atomic():
        locked = Visit.objects.select_for_update().get(pk=visit.pk)
        if locked.status != VisitStatus.CHECKED_IN:
            return False, f"Cannot check out: visit is {locked.status}."
        locked.status = VisitStatus.CHECKED_OUT
        locked.checked_out_at = timezone.now()
        locked.checked_out_by = officer
        locked.save(update_fields=["status", "checked_out_at", "checked_out_by"])
        log_visit_event(officer, "Visitor checked out", locked)
    return True, "Visitor checked out."


def get_or_create_visitor(org, *, full_name=None, phone="", **fields):
    """Tenant-scoped visitor dedup by phone: reuse the org's existing record.

    Identity is ``(organization, phone)`` -- the tenant key is part of the
    lookup, so a visitor registered by one workspace is never handed to
    another.  When that org already holds a record for ``phone`` its blank
    contact fields are backfilled from the new registration, avoiding
    duplicate visitor rows.
    """
    phone = (phone or "").strip()
    full_name = (full_name or "").strip()
    existing = None
    if phone and org is not None:
        existing = (
            Visitor.objects.filter(organization=org)
            .filter(phone=phone)
            .order_by("id")
            .first()
        )
    if existing is not None:
        changed = False
        if full_name and not existing.full_name:
            existing.full_name = full_name
            changed = True
        for key, value in fields.items():
            if key in _VISITOR_WRITABLE and value and not getattr(existing, key):
                setattr(existing, key, value)
                changed = True
        if changed:
            existing.save()
        return existing, False
    create_data = {
        "organization": org,
        "full_name": full_name or "Visitor",
        "phone": phone,
    }
    create_data.update(
        {k: v for k, v in fields.items() if k in _VISITOR_WRITABLE}
    )
    try:
        # Savepoint, so the rollback below cannot poison an outer transaction.
        with transaction.atomic():
            return Visitor.objects.create(**create_data), True
    except IntegrityError:
        # Two concurrent registrations for the same (organization, phone) --
        # the uniq_visitor_org_phone constraint turns the loser's insert into
        # an error, so hand back the row the winner just created.
        existing = (
            Visitor.objects.filter(organization=org, phone=phone).order_by("id").first()
        )
        if existing is None:
            raise
        return existing, False


def register_visit(
    actor,
    *,
    visitor=None,
    visitor_data=None,
    purpose="",
    host_id=None,
    building_id=None,
    expected_arrival="10:00",
    expected_exit="17:00",
    visit_date=None,
    notes="",
    walkin=False,
    audit=True,
    audit_ip=None,
):
    """Create a visitor (with dedup) and a PENDING visit atomically.

    Single registration path shared by the REST API and the operations
    console. ``walkin=True`` auto-approves to issue the QR pass immediately.
    Returns ``(visit, ok, msg)``; ``msg`` is a dict payload for API clients
    and a plain string for the console on success.
    """
    org = getattr(actor, "organization", None)
    purpose = str(purpose or "").strip()
    if org is None:
        return None, False, {"detail": "Your account is not assigned to an organization."}
    if not purpose:
        return None, False, {"detail": {"purpose": ["Purpose is required."]}}
    if len(purpose) > 200:
        return None, False, {
            "detail": {"purpose": ["Purpose is too long (maximum 200 characters)."]}
        }
    notes = str(notes or "")

    if visitor is None:
        visitor_data = visitor_data or {}
        full_name = (visitor_data.get("full_name") or "").strip()
        phone = (str(visitor_data.get("phone") or "")).strip()
        if not full_name or not phone:
            return None, False, {
                "detail": {"visitor": ["full_name and phone are required."]}
            }
        fields = {
            k: v
            for k, v in visitor_data.items()
            if k in _VISITOR_WRITABLE and k not in ("full_name", "phone")
        }
        visitor, _ = get_or_create_visitor(
            org, full_name=full_name, phone=phone, **fields
        )

    host = None
    if host_id:
        host = User.objects.filter(pk=host_id, organization_id=org.pk).first()
        if host is None:
            return None, False, {
                "detail": {"host": ["Host must belong to your organization."]}
            }
    building = None
    if building_id:
        building = Building.objects.filter(pk=building_id, organization_id=org.pk).first()
        if building is None:
            return None, False, {
                "detail": {"building": ["Building must belong to your organization."]}
            }

    arrival = _time_or_none(expected_arrival or "10:00")
    exit_time = _time_or_none(expected_exit or "17:00")
    if arrival is None or exit_time is None:
        return None, False, {
            "detail": {"visit": ["Invalid expected arrival/exit times."]}
        }
    if exit_time <= arrival:
        return None, False, {
            "detail": {"visit": ["Expected exit must be later than expected arrival."]}
        }

    if isinstance(visit_date, str) and visit_date.strip():
        try:
            visit_date = datetime.strptime(visit_date.strip(), "%Y-%m-%d").date()
        except ValueError:
            return None, False, {
                "detail": {"visit": ["Invalid visit date. Use YYYY-MM-DD."]}
            }
    elif not isinstance(visit_date, date):
        visit_date = None
    visit_date = visit_date or org_localdate(actor)

    resolved_host = host or (actor if getattr(actor, "is_authenticated", False) else None)

    # Staff pre-registration checks the host's calendar with the same overlap
    # rule the public booking form enforces (audit finding "host slot
    # validation not shared by staff registration"). For staff it is a
    # *warning*, not a refusal: reception knowingly books panel interviews and
    # group deliveries, and a hard block would only push them to lie about the
    # time. Walk-ins are exempt -- the visitor is already standing there.
    schedule_warnings = []
    if resolved_host is not None and not walkin:
        for b_start, b_end in host_blocks_for(org, resolved_host, visit_date):
            if intervals_overlap(arrival, exit_time, b_start, b_end):
                schedule_warnings.append(
                    f"{resolved_host.full_name} already has a visitor between "
                    f"{b_start:%H:%M} and {b_end:%H:%M} on {visit_date:%d %b}."
                )

    with transaction.atomic():
        visit = Visit.objects.create(
            visitor=visitor,
            organization=org,
            created_by=actor if getattr(actor, "is_authenticated", False) else None,
            host=resolved_host,
            building=building,
            purpose=purpose,
            notes=notes,
            visit_date=visit_date,
            expected_arrival=arrival,
            expected_exit=exit_time,
            # Reporting by source must be able to tell a walk-in from a desk
            # pre-registration (audit finding "walk-in source classification").
            source=VisitSource.WALK_IN if walkin else VisitSource.STAFF,
        )
        if audit:
            log_visit_event(actor, "Visit registered", visit, ip=audit_ip)
        if walkin:
            ok, msg = approve_visit(visit, actor)
            if not ok:
                return visit, False, {"detail": msg}
            # approve_visit re-fetches the row (select_for_update), so the
            # original instance is stale; reload it so callers (e.g. the API
            # walk-in view) serialize APPROVED + the issued pass, not PENDING.
            visit.refresh_from_db()
    # Surfaced by the API as ``warnings`` so the desk can see the clash.
    visit.schedule_warnings = schedule_warnings
    return visit, True, "Visit registered successfully."


def reissue_qr_pass(visit, actor):
    """Regenerate the QR pass for an approved visit (expired or used pass).

    Only staff with approval rights may trigger a re-issue and the visit must
    still be APPROVED. The old pass is invalidated atomically: the signature
    is rotated on the same row (OneToOne), so any artifact encoding the old
    token/signature pair is immediately rejected by ``QRPass.verify``.
    """
    if not _user_allowed(actor, visit):
        return False, "You do not have access to this visit."
    with transaction.atomic():
        locked = Visit.objects.select_for_update().get(pk=visit.pk)
        if locked.status != VisitStatus.APPROVED:
            return False, f"Cannot re-issue: visit is {locked.status}."
        QRPass.reissue(locked)
        log_visit_event(actor, "QR pass re-issued", locked)
    return True, "QR pass re-issued. The new pass is now valid."


def archive_old_visits(days=30, organization=None, actor=None):
    """Archive visits checked out more than ``days`` ago, with an audit row each.

    Scheduled on cron / a systemd timer.  Only visits that are already
    ``CHECKED_OUT`` and older than the cutoff are touched; in-progress and
    pending visits are never archived.

    This used to be a single bulk ``.update()``, which was invisible in the
    audit trail: a visitor's record could move from ``CHECKED_OUT`` to
    ``ARCHIVED`` with no entry explaining when or by whom.  It now walks the
    matching rows under ``select_for_update`` and appends one
    ``Visit archived`` entry per visit inside the same transaction as the
    status change, so a rollback cannot leave an archive record behind and a
    committed archive cannot be unrecorded.

    ``actor`` is normally ``None`` (the job has no human operator); it is
    accepted so an operator-initiated run can attribute the change.
    """
    cutoff = timezone.now() - timezone.timedelta(days=days)
    stale = (
        Visit.objects.filter(
            checked_out_at__lte=cutoff, status=VisitStatus.CHECKED_OUT
        )
        .order_by("pk")
    )
    if organization is not None:
        stale = stale.filter(organization=organization)

    archived = 0
    for visit in stale:
        with transaction.atomic():
            locked = Visit.objects.select_for_update().filter(
                pk=visit.pk, status=VisitStatus.CHECKED_OUT
            ).first()
            if locked is None:
                # status moved under us between the scan and the lock
                continue
            locked.status = VisitStatus.ARCHIVED
            locked.archived_at = timezone.now()
            locked.save(update_fields=["status", "archived_at"])
            log_visit_event(
                actor,
                "Visit archived",
                locked,
                extra=f"| checked out {locked.checked_out_at:%Y-%m-%d} (>{days}d)",
            )
        archived += 1
    return archived


def create_pre_booking(
    org,
    *,
    visitor_data,
    visit_type="",
    department_id=None,
    building_id=None,
    floor_id=None,
    host_id=None,
    visit_date=None,
    expected_arrival=None,
    expected_exit=None,
    purpose="",
    purpose_other="",
    notes="",
    audit_ip=None,
    category=None,
):
    """Public, pre-arrival booking for an anonymous visitor.

    Two ways to describe the visit:

    * ``category`` + ``purpose`` -- the workspace catalogue
      (``visits.purposes.catalogue_for``): the visitor picks who they are and
      what they are coming for from dropdowns; ``visit_type`` is derived from
      the chosen purpose.
    * ``visit_type`` + ``purpose`` -- the legacy static lists.

    Creates a ``PENDING``, ``PUBLIC_BOOKING`` visit (never auto-approved, no
    QR issued). Every relationship is validated org-scoped server-side — a
    department/host/building/floor from another organization is rejected even
    if the client supplies its ID. Reuses the existing visitor dedup logic so
    nobody is duplicated. Returns ``(visit, ok, msg)``.
    """
    org_id = getattr(org, "pk", None)
    if org_id is None:
        return None, False, {"detail": "Organization not found."}

    purpose = str(purpose or "").strip()
    category_key = str(category or "").strip().upper()
    if category_key:
        # Catalogue path: the (category, purpose) pair must exist for this
        # workspace; the visit type comes from the catalogue entry.
        from .purposes import resolve_purpose

        entry = resolve_purpose(org, category_key, purpose)
        if entry is None:
            if purposes_for_category(org, category_key) is None:
                return None, False, {
                    "detail": {"category": ["Please choose a valid visitor category."]}
                }
            return None, False, {
                "detail": {"purpose": ["Purpose is not valid for the selected visitor category."]}
            }
        visit_type = entry["visit_type"]
        allowed_purposes = [p["label"] for p in purposes_for_category(org, category_key)]
    else:
        visit_type = str(visit_type or "").strip()
        if visit_type not in VisitType.values:
            return None, False, {
                "detail": {"visit_type": ["Please choose a valid visit type."]}
            }
        allowed_purposes = purposes_for(visit_type)

    if purpose == OTHER_LABEL:
        purpose_text = str(purpose_other or "").strip()
        if not purpose_text:
            return None, False, {
                "detail": {
                    "purpose_other": ["Please describe the purpose of your visit."]
                }
            }
        if len(purpose_text) > PURPOSE_OTHER_MAX:
            return None, False, {
                "detail": {
                    "purpose_other": [
                        f"Purpose is too long (maximum {PURPOSE_OTHER_MAX} characters)."
                    ]
                }
            }
    elif purpose in allowed_purposes:
        purpose_text = purpose
    else:
        return None, False, {
            "detail": {
                "purpose": ["Purpose is not valid for the selected visit type."]
            }
        }
    if len(purpose_text) > 200:
        return None, False, {
            "detail": {"purpose": ["Purpose is too long (maximum 200 characters)."]}
        }

    department = None
    if department_id:
        department = Department.objects.filter(
            pk=department_id, organization_id=org_id
        ).first()
        if department is None:
            return None, False, {
                "detail": {"department": ["Department is not valid for this organization."]}
            }

    building = None
    if building_id:
        building = Building.objects.filter(pk=building_id, organization_id=org_id).first()
        if building is None:
            return None, False, {
                "detail": {"building": ["Building is not valid for this organization."]}
            }

    floor = None
    if floor_id:
        floor = Floor.objects.select_related("building").filter(pk=floor_id).first()
        if floor is None or floor.building.organization_id != org_id:
            return None, False, {
                "detail": {"floor": ["Floor is not valid for this organization."]}
            }
        if building is not None and floor.building_id != building.pk:
            return None, False, {
                "detail": {"floor": ["Floor does not belong to the selected building."]}
            }

    host = None
    if host_id:
        host = User.objects.filter(pk=host_id, organization_id=org_id, is_active=True).first()
        if host is None:
            return None, False, {
                "detail": {"host": ["Person to meet is not available at this organization."]}
            }
        employee = getattr(host, "employee_profile", None)
        if department is not None:
            if (
                employee is None
                or employee.organization_id != org_id
                or employee.status != Employee.Status.ACTIVE
                or employee.department_id != department.pk
            ):
                return None, False, {
                    "detail": {"host": ["Person to meet is not available in the selected department."]}
                }
        elif employee is not None and employee.status == Employee.Status.INACTIVE:
            return None, False, {
                "detail": {"host": ["Person to meet is not available."]}
            }

    arrival = _time_or_none(expected_arrival) if expected_arrival else None
    exit_time = _time_or_none(expected_exit) if expected_exit else None
    if (
        expected_arrival is None
        or expected_exit is None
        or str(expected_arrival or "").strip() == ""
        or str(expected_exit or "").strip() == ""
        or arrival is None
        or exit_time is None
    ):
        return None, False, {
            "detail": {"visit": ["Arrival and exit times are required (HH:MM)."]}
        }
    if exit_time <= arrival:
        return None, False, {
            "detail": {"visit": ["Expected exit must be later than expected arrival."]}
        }

    if isinstance(visit_date, str) and visit_date.strip():
        try:
            visit_date = datetime.strptime(visit_date.strip(), "%Y-%m-%d").date()
        except ValueError:
            return None, False, {
                "detail": {"visit_date": ["Invalid visit date. Use YYYY-MM-DD."]}
            }
    elif not isinstance(visit_date, date):
        return None, False, {
            "detail": {"visit_date": ["Visit date is required (YYYY-MM-DD)."]}
        }
    if visit_date < org_localdate(org):
        return None, False, {
            "detail": {"visit_date": ["Visit date cannot be in the past."]}
        }

    # Schedule check (working windows/breaks) + conflict check against the
    # host's existing active visits. Run twice: here for a fast, lock-free
    # rejection and again inside the transaction below once the host row is
    # locked, so two simultaneous submissions cannot both slip in.
    slot_ok, slot_reason = validate_booking_slot(
        org, host, visit_date, arrival, exit_time
    )
    if not slot_ok:
        return None, False, {"detail": {"visit": [slot_reason]}}

    visitor_data = visitor_data or {}
    full_name = str(visitor_data.get("full_name") or "").strip()
    phone = str(visitor_data.get("phone") or "").strip()
    if not full_name or not phone:
        return None, False, {
            "detail": {"visitor": ["Full name and phone are required."]}
        }
    if len(full_name) > 150:
        return None, False, {
            "detail": {"visitor": ["Full name is too long (maximum 150 characters)."]}
        }
    if len(phone) > 20:
        return None, False, {
            "detail": {"visitor": ["Phone number is too long (maximum 20 characters)."]}
        }
    fields = {
        k: v
        for k, v in visitor_data.items()
        if k in _VISITOR_WRITABLE and k not in ("full_name", "phone")
    }

    with transaction.atomic():
        if host is not None:
            # Serialize concurrent pre-bookings for this host: the second
            # waiter re-reads the freshest committed state and sees the first
            # booking, so at most one of two simultaneous submissions wins.
            User.objects.select_for_update().get(pk=host.pk)
            slot_ok, slot_reason = validate_booking_slot(
                org, host, visit_date, arrival, exit_time
            )
            if not slot_ok:
                return None, False, {"detail": {"visit": [slot_reason]}}

        visitor, _ = get_or_create_visitor(
            org, full_name=full_name, phone=phone, **fields
        )
        visit = Visit.objects.create(
            visitor=visitor,
            organization=org,
            host=host,
            building=building,
            floor=floor,
            department=department,
            visit_type=visit_type,
            visitor_category=category_key,
            source=VisitSource.PUBLIC_BOOKING,
            purpose=purpose_text,
            notes=str(notes or ""),
            visit_date=visit_date,
            expected_arrival=arrival,
            expected_exit=exit_time,
        )
        AuditLog.log(
            None,
            "Pre-booking submitted",
            entity_type="Visit",
            entity_id=str(visit.visit_id),
            details=(
                f"{visit.visitor.full_name} | {visit.purpose} | "
                f"visit_type {visit.get_visit_type_display()} | phone {visit.visitor.phone}"
            ),
            ip_address=audit_ip,
            # submitted anonymously against a public booking link, so the actor
            # is None; the tenant comes from the visit.
            organization_id=visit.organization_id,
        )
        schedule_visit_reminders(visit)
    return visit, True, "Booking submitted successfully."


def _parse_iso_date(value):
    """Normalize a ``YYYY-MM-DD`` string / ``date`` to a ``datetime.date``."""
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            return None
    return None


# Statuses a visitor may still manage themselves (reschedule / cancel).
_VISITOR_MODIFIABLE_STATUSES = (VisitStatus.PENDING, VisitStatus.APPROVED)


def visit_can_be_rescheduled(visit):
    """May ``visit`` be rescheduled by the visitor? (server-side rule).

    Only future, pre-booked visits that are still pending or approved are
    eligible — never walk-ins, past/completed visits, or terminal states.
    """
    if visit.source != VisitSource.PUBLIC_BOOKING:
        return False
    if visit.status not in _VISITOR_MODIFIABLE_STATUSES:
        return False
    return visit.visit_date >= org_localdate(visit.organization)


def visit_can_be_cancelled(visit):
    """May ``visit`` be cancelled by the visitor? Same eligibility surface."""
    return visit_can_be_rescheduled(visit)


def reschedule_visit(
    session,
    visit_id,
    *,
    new_date,
    expected_arrival,
    expected_exit,
    audit_ip=None,
):
    """Visitor reschedules one of their own future pre-bookings.

    The host stays unchanged; only the appointment date/arrival/exit change.
    Availability is re-validated inside the transaction under a row lock on the
    host row (mirroring ``create_pre_booking``), so two simultaneous
    reschedules cannot both claim the same slot. Scoping (organization +
    visitor) is enforced on the locked row — a forged visit id or a token sent
    cross-tenant can never redirect the update. Returns ``(visit, ok, msg)``.
    """
    org = getattr(session, "organization", None)
    if org is None:
        return None, False, "Unable to access this visit."
    # Fast, indexed scoping pass; the authoritative check is repeated on the
    # locked row inside the transaction below.
    visit = (
        Visit.objects.filter(pk=visit_id, organization=org, visitor=session.visitor)
        .select_related("visitor", "organization", "host")
        .first()
    )
    if visit is None:
        return None, False, "Unable to access this visit."
    if not visit_can_be_rescheduled(visit):
        return None, False, "This visit cannot be rescheduled."

    chosen_date = _parse_iso_date(new_date)
    if chosen_date is None:
        return None, False, "Please choose a valid date."
    if chosen_date < org_localdate(org):
        return None, False, "Visit date cannot be in the past."
    arrival = _time_or_none(expected_arrival)
    exit_time = _time_or_none(expected_exit)
    if arrival is None or exit_time is None:
        return None, False, "Please choose a valid time."
    if exit_time <= arrival:
        return None, False, "Please choose a valid time slot."

    with transaction.atomic():
        if visit.host_id is not None:
            # Serialize concurrent reschedules/booking submissions for the
            # host: the second waiter re-reads committed state and sees the
            # first change, so at most one writer claims a given slot.
            User.objects.select_for_update().get(pk=visit.host_id)
        locked = (
            # Deliberately no select_related() on a select_for_update() query.
            # visit, visitor, organization and host are all nullable, so
            # select_related emits LEFT OUTER JOINs and PostgreSQL refuses
            # FOR UPDATE across the nullable side of one:
            #   NotSupportedError: FOR UPDATE cannot be applied to the
            #   nullable side of an outer join
            # That made this endpoint raise on every request against a real
            # PostgreSQL -- visitor self-service rescheduling was entirely
            # broken in production while passing on SQLite, which ignores
            # select_for_update completely. The row is locked; the related
            # objects are read lazily, which is three cheap primary-key lookups
            # inside a transaction that already holds the lock.
            Visit.objects.select_for_update().get(pk=visit.pk)
        )
        if (
            locked.organization_id != session.organization_id
            or locked.visitor_id != session.visitor_id
        ):
            return None, False, "Unable to access this visit."
        if not visit_can_be_rescheduled(locked):
            return None, False, "This visit cannot be rescheduled."
        slot_ok, slot_reason = validate_booking_slot(
            org,
            locked.host,
            chosen_date,
            arrival,
            exit_time,
            exclude_visit_pk=locked.pk,
        )
        if not slot_ok:
            return None, False, slot_reason

        old_date = locked.visit_date
        old_arrival = locked.expected_arrival
        old_exit = locked.expected_exit
        locked.visit_date = chosen_date
        locked.expected_arrival = arrival
        locked.expected_exit = exit_time
        locked.save(
            update_fields=["visit_date", "expected_arrival", "expected_exit"]
        )
        reschedule_visit_reminders(locked)
        log_visit_event(
            None,
            "Visit rescheduled",
            locked,
            f"| from {old_date} {old_arrival:%H:%M}-{old_exit:%H:%M} "
            f"to {chosen_date.isoformat()} {arrival:%H:%M}-{exit_time:%H:%M} "
            "(visitor portal)",
            ip=audit_ip,
        )
    # Outside the transaction: the host learns about the change, but a mail
    # failure can never roll back a committed reschedule.
    _notify_host(locked, "rescheduled")
    return locked, True, "Your visit has been rescheduled."


def cancel_visit(session, visit_id, *, reason="", audit_ip=None):
    """Visitor cancels one of their own future pre-bookings.

    The visit is NOT deleted — it transitions to ``CANCELLED`` so the decision
    stays visible in history, reports and audits. Because ``CANCELLED`` is not
    in the availability blocking statuses, the freed slot immediately becomes
    bookable again, and any issued QR pass is voided so it can never be scanned
    at the gate. Returns ``(visit, ok, msg)``.
    """
    org = getattr(session, "organization", None)
    if org is None:
        return None, False, "Unable to access this visit."
    visit = (
        Visit.objects.filter(pk=visit_id, organization=org, visitor=session.visitor)
        .select_related("visitor", "organization", "host")
        .first()
    )
    if visit is None:
        return None, False, "Unable to access this visit."
    if not visit_can_be_cancelled(visit):
        return None, False, "This visit cannot be cancelled."
    reason = str(reason or "").strip()
    if len(reason) > 120:
        return None, False, (
            "Cancellation reason is too long (maximum 120 characters)."
        )

    with transaction.atomic():
        locked = (
            # Same reason as in reschedule_visit(): select_related() here would
            # make PostgreSQL reject FOR UPDATE on the outer join, so visitor
            # self-service cancellation raised NotSupportedError on every call.
            Visit.objects.select_for_update().get(pk=visit.pk)
        )
        if (
            locked.organization_id != session.organization_id
            or locked.visitor_id != session.visitor_id
        ):
            return None, False, "Unable to access this visit."
        if not visit_can_be_cancelled(locked):
            return None, False, "This visit cannot be cancelled."
        locked.status = VisitStatus.CANCELLED
        locked.cancelled_at = timezone.now()
        locked.cancelled_reason = reason
        locked.save(
            update_fields=["status", "cancelled_at", "cancelled_reason"]
        )
        cancel_visit_reminders(locked)
        # Void any issued pass so a cancelled visit can never enter the gate;
        # a scan then reports "Unknown pass". The visit row itself is kept for
        # history/reporting/audit traceability.
        QRPass.objects.filter(visit=locked).delete()
        log_visit_event(
            None,
            "Visit cancelled",
            locked,
            f"| reason: {reason or 'Not provided'} (visitor portal)",
            ip=audit_ip,
        )
    _notify_host(locked, "cancelled")
    return locked, True, "Your visit has been cancelled."


# ---------------------------------------------------------------------------
# Staff-side operations exposed through the REST API (SPA console).
# ---------------------------------------------------------------------------

_STAFF_CANCELLABLE_STATUSES = (VisitStatus.PENDING, VisitStatus.APPROVED)


def cancel_visit_by_staff(visit, actor, *, reason="", audit_ip=None):
    """Staff cancels a visit that has not yet reached the gate.

    Mirrors the visitor-portal ``cancel_visit`` but is driven by an employee
    account: the actor must belong to the visit's workspace, only PENDING or
    APPROVED visits can be cancelled, the row moves to ``CANCELLED`` (never
    deleted), reminders are dropped and any issued pass is voided so it can no
    longer be scanned.  Returns ``(ok, message)``.
    """
    if not _user_allowed(actor, visit):
        return False, "You do not have access to this visit."
    reason = str(reason or "").strip()
    if len(reason) > 120:
        return False, "Cancellation reason is too long (maximum 120 characters)."
    with transaction.atomic():
        locked = Visit.objects.select_for_update().get(pk=visit.pk)
        if locked.status not in _STAFF_CANCELLABLE_STATUSES:
            return False, f"Cannot cancel: visit is {locked.status}."
        locked.status = VisitStatus.CANCELLED
        locked.cancelled_at = timezone.now()
        locked.cancelled_reason = reason
        locked.save(update_fields=["status", "cancelled_at", "cancelled_reason"])
        cancel_visit_reminders(locked)
        QRPass.objects.filter(visit=locked).delete()
        log_visit_event(
            actor,
            "Visit cancelled",
            locked,
            f"| reason: {reason or 'Not provided'} (staff)",
            ip=audit_ip,
        )
    return True, "Visit cancelled."


def blacklist_visitor(visitor, actor, *, reason, comment="", audit_ip=None):
    """Add ``visitor`` to the workspace blacklist (idempotent).

    The ban row and its audit entry commit together.  A visitor who is already
    actively blacklisted is left untouched and reported as such.  Returns
    ``(entry_or_None, ok, message)``.
    """
    from visits.models import Blacklist, BlacklistReason

    org_id = getattr(actor, "organization_id", None)
    if not getattr(actor, "is_superuser", False) and (
        org_id is None or visitor.organization_id != org_id
    ):
        return None, False, "You do not have access to this visitor."
    if reason not in BlacklistReason.values:
        return None, False, "Choose a valid blacklist reason."
    comment = str(comment or "").strip()
    if len(comment) > 1000:
        return None, False, "Comment is too long (maximum 1000 characters)."
    with transaction.atomic():
        existing = (
            Blacklist.objects.select_for_update()
            .filter(visitor=visitor, is_active=True)
            .first()
        )
        if existing is not None:
            return existing, False, "Visitor is already blacklisted."
        entry = Blacklist.objects.create(
            visitor=visitor, reason=reason, comment=comment, added_by=actor
        )
        AuditLog.log(
            actor,
            "Visitor blacklisted",
            "Visitor",
            visitor.pk,
            f"{visitor.full_name} | {reason}",
            ip_address=audit_ip,
            organization_id=visitor.organization_id,
        )
    return entry, True, f"{visitor.full_name} added to the blacklist."


def remove_blacklist(visitor, actor, *, audit_ip=None):
    """Lift every active ban on ``visitor``.  Returns ``(ok, message)``."""
    from visits.models import Blacklist

    org_id = getattr(actor, "organization_id", None)
    if not getattr(actor, "is_superuser", False) and (
        org_id is None or visitor.organization_id != org_id
    ):
        return False, "You do not have access to this visitor."
    with transaction.atomic():
        updated = Blacklist.objects.filter(visitor=visitor, is_active=True).update(
            is_active=False
        )
        if not updated:
            return False, "Visitor is not blacklisted."
        AuditLog.log(
            actor,
            "Visitor un-blacklisted",
            "Visitor",
            visitor.pk,
            visitor.full_name,
            ip_address=audit_ip,
            organization_id=visitor.organization_id,
        )
    return True, f"{visitor.full_name} removed from the blacklist."


# ---------------------------------------------------------------------------
# Rooms: assignment on approval and attendance scans at the door.
# ---------------------------------------------------------------------------

_ROOM_ASSIGNABLE_STATUSES = (VisitStatus.PENDING, VisitStatus.APPROVED, VisitStatus.CHECKED_IN)


def assign_room(visit, actor, room_id, *, audit_ip=None):
    """Point a visit at a room (and therefore its floor and building).

    ``room_id`` may be ``None`` to clear the assignment. The room must belong
    to the visit's workspace. Returns ``(ok, message)``.
    """
    from visits.models import Room

    if not _user_allowed(actor, visit):
        return False, "You do not have access to this visit."
    room = None
    if room_id:
        room = (
            Room.objects.select_related("building", "floor")
            .filter(pk=room_id, building__organization_id=visit.organization_id, is_active=True)
            .first()
        )
        if room is None:
            return False, "Choose a room that belongs to this workspace."
    with transaction.atomic():
        locked = Visit.objects.select_for_update().get(pk=visit.pk)
        if locked.status not in _ROOM_ASSIGNABLE_STATUSES:
            return False, f"Cannot assign a room: visit is {locked.status}."
        locked.room = room
        fields = ["room"]
        if room is not None:
            locked.building = room.building
            locked.floor = room.floor
            fields += ["building", "floor"]
        locked.save(update_fields=fields)
        log_visit_event(
            actor,
            "Room assigned" if room else "Room cleared",
            locked,
            extra=f"| room {room.label}" if room else "",
            ip=audit_ip,
        )
    return True, f"Room set to {room.label}." if room else "Room assignment cleared."


def record_room_attendance(visit, room, officer, *, note="", audit_ip=None):
    """Record that the visitor's pass was scanned at ``room``.

    Requires the visit to be CHECKED_IN (the visitor passed the gate today)
    and the room to belong to the same workspace. Repeated scans are allowed
    -- a student attends several rooms in a day -- but the same room within a
    minute is treated as a double tap and reported, not duplicated.
    Returns ``(attendance_or_None, ok, message)``.
    """
    from visits.models import RoomAttendance

    if not _user_allowed(officer, visit):
        return None, False, "You do not have access to this visit."
    if room.building.organization_id != visit.organization_id:
        return None, False, "That room belongs to another workspace."
    if not room.is_active:
        return None, False, "That room is not in use."
    if visit.status != VisitStatus.CHECKED_IN:
        return None, False, (
            f"Visit is {visit.status}, not checked in. The visitor must pass the gate first."
        )
    now = timezone.now()
    recent = (
        RoomAttendance.objects.filter(visit=visit, room=room, scanned_at__gte=now - timezone.timedelta(minutes=1))
        .first()
    )
    if recent is not None:
        return recent, False, f"Already recorded at {room.label} a moment ago."
    with transaction.atomic():
        entry = RoomAttendance.objects.create(
            visit=visit, room=room, scanned_by=officer, note=str(note or "")[:200]
        )
        log_visit_event(
            officer,
            "Room attendance recorded",
            visit,
            extra=f"| room {room.label}",
            ip=audit_ip,
        )
    return entry, True, f"{visit.visitor.full_name} recorded at {room.label}."
