"""6-month student passes for admitted students: issue, verify, gate scans.

Rules (agreed with the institute):

* Only admins issue a pass, at admission. It is valid for 6 months from its
  start date and can be renewed for another 6 months or revoked at any time.
* At the gate the pass is scanned every day. The first scan of a day is IN,
  the next OUT, alternating. Entering (IN) is allowed only on working days,
  from 30 minutes before opening until closing; leaving (OUT) is always
  allowed. Two scans within 60 seconds are treated as an accidental double
  scan and refused, so one swipe can't flip IN to OUT.
* A blacklisted student, a revoked or expired pass, a pass from another
  workspace or a tampered QR is refused with a plain reason.
"""

import calendar
import io
import uuid
from datetime import date, timedelta

import qrcode
from django.conf import settings
from django.core.mail import EmailMessage
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone

from accounts.utils import org_localdate, org_timezone
from organizations.models import AuditLog

from . import signing
from .availability import weekly_windows
from .emails import deliver
from .models import StudentPass, StudentPassScan

VALID_MONTHS = 6
EARLY_ENTRY_MINUTES = 30
DOUBLE_SCAN_SECONDS = 60
EVENT_STUDENT_PASS = "email.student_pass"


def add_months(d, months):
    """``d`` plus ``months`` calendar months, clamped to the month's last day."""
    month_index = d.month - 1 + months
    year, month = d.year + month_index // 12, month_index % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def end_of_term(start):
    """Last valid day of a 6-month pass that starts on ``start``."""
    return add_months(start, VALID_MONTHS) - timedelta(days=1)


def effective_status(sp, today=None):
    """ACTIVE / UPCOMING / EXPIRED / REVOKED, as staff and students see it."""
    if sp.status == StudentPass.Status.REVOKED:
        return "REVOKED"
    today = today or org_localdate(sp.organization)
    if today < sp.valid_from:
        return "UPCOMING"
    if today > sp.valid_until:
        return "EXPIRED"
    return "ACTIVE"


# ------------------------------------------------------------------- issue


def issue_pass(org, *, visitor, admission_number, course, batch="", valid_from=None, issued_by=None, ip=None):
    start = valid_from or org_localdate(org)
    with transaction.atomic():
        sp = StudentPass(
            organization=org,
            visitor=visitor,
            admission_number=admission_number,
            course=course,
            batch=batch,
            valid_from=start,
            valid_until=end_of_term(start),
            issued_by=issued_by,
            token=uuid.uuid4(),
        )
        sp.sign()
        sp.save()
        AuditLog.log(
            issued_by, "Student pass issued", "StudentPass", sp.pk,
            f"{admission_number} | {visitor.full_name} | {sp.valid_from} to {sp.valid_until}",
            ip_address=ip, organization_id=org.pk,
        )
    return sp


def renew_pass(sp, *, user=None, ip=None):
    """Extend by 6 months from the later of today and the current end date."""
    today = org_localdate(sp.organization)
    start = max(sp.valid_until + timedelta(days=1), today)
    with transaction.atomic():
        sp.valid_until = add_months(start, VALID_MONTHS) - timedelta(days=1)
        sp.status = StudentPass.Status.ACTIVE
        sp.revoked_at = None
        sp.revoked_reason = ""
        sp.renewed_count += 1
        sp.save(update_fields=["valid_until", "status", "revoked_at", "revoked_reason", "renewed_count"])
        AuditLog.log(user, "Student pass renewed", "StudentPass", sp.pk, f"{sp.admission_number} | valid until {sp.valid_until}",
                     ip_address=ip, organization_id=sp.organization_id)
    return sp


def revoke_pass(sp, *, user=None, reason="", ip=None):
    with transaction.atomic():
        sp.status = StudentPass.Status.REVOKED
        sp.revoked_at = timezone.now()
        sp.revoked_reason = (reason or "").strip()[:200]
        sp.save(update_fields=["status", "revoked_at", "revoked_reason"])
        AuditLog.log(user, "Student pass revoked", "StudentPass", sp.pk, f"{sp.admission_number} | {sp.revoked_reason}",
                     ip_address=ip, organization_id=sp.organization_id)
    return sp


# ------------------------------------------------------------------- verify


def is_student_payload(token_part):
    return (token_part or "").strip().upper() == "SP"


def verify(org, raw):
    """``(ok, message, pass)`` for the part after ``SP|`` (``token|signature``)."""
    token, _, signature = (raw or "").strip().partition("|")
    try:
        token_uuid = uuid.UUID(token.strip())
    except ValueError:
        return False, "Unknown pass - not registered in system", None
    sp = (
        StudentPass.objects.select_related("visitor", "organization")
        .filter(token=token_uuid, organization=org)
        .first()
    )
    # Another workspace's pass is reported exactly like an unknown one.
    if sp is None:
        return False, "Unknown pass - not registered in system", None
    if not signing.verify(StudentPass.signing_subject(sp.token), sp.organization_id, sp.token, signature.strip()):
        return False, "Invalid pass - the QR code has been tampered with", None
    state = effective_status(sp)
    if state == "REVOKED":
        return False, f"Pass revoked{': ' + sp.revoked_reason if sp.revoked_reason else ''}. Send the student to the office.", sp
    if state == "EXPIRED":
        return False, f"Pass expired on {sp.valid_until:%d %b %Y}. It needs to be renewed at the office.", sp
    if state == "UPCOMING":
        return False, f"Pass starts on {sp.valid_from:%d %b %Y}.", sp
    if sp.visitor.is_blacklisted:
        return False, "Student is blacklisted. Entry not allowed.", sp
    return True, "Valid student pass", sp


def _entry_window_problem(org, local_now):
    windows = weekly_windows(org, local_now.date())
    if not windows:
        return "Today is not a working day. Entry is closed."
    now_min = local_now.hour * 60 + local_now.minute
    for start, end in windows:
        # Compare minutes since midnight: subtracting the early allowance from
        # an opening time before 00:30 must not wrap round to late evening.
        early_min = max(start.hour * 60 + start.minute - EARLY_ENTRY_MINUTES, 0)
        if early_min <= now_min <= end.hour * 60 + end.minute:
            return None
    opens = ", ".join(f"{s:%H:%M}-{e:%H:%M}" for s, e in windows)
    return f"Entry is allowed only during institute hours ({opens})."


def scan(org, sp, *, user=None, dry_run=False, now=None, ip=None):
    """Record IN or OUT. Returns ``(ok, message, direction, scan_row)``."""
    now = now or timezone.now()
    local_now = timezone.localtime(now, org_timezone(org))
    today = local_now.date()
    with transaction.atomic():
        # Serialise scans of the same pass so two gates can't both record IN.
        StudentPass.objects.select_for_update().filter(pk=sp.pk).first()
        last = StudentPassScan.objects.filter(student_pass=sp, scan_date=today).order_by("-scanned_at").first()
        direction = StudentPassScan.Direction.OUT if last and last.direction == StudentPassScan.Direction.IN else StudentPassScan.Direction.IN
        if last and (now - last.scanned_at).total_seconds() < DOUBLE_SCAN_SECONDS:
            return False, f"Already scanned {last.get_direction_display().upper()} a moment ago.", last.direction, None
        if direction == StudentPassScan.Direction.IN:
            problem = _entry_window_problem(org, local_now)
            if problem:
                return False, problem, direction, None
        if dry_run:
            return True, f"Valid. Next scan records {direction}.", direction, None
        row = StudentPassScan.objects.create(
            student_pass=sp, organization=org, direction=direction, scan_date=today, scanned_at=now, scanned_by=user,
        )
    AuditLog.log(user, f"Student {direction}", "StudentPass", sp.pk, f"{sp.admission_number} | {sp.visitor.full_name}",
                 ip_address=ip, organization_id=org.pk)
    return True, ("Entry recorded. Welcome!" if direction == "IN" else "Exit recorded. See you tomorrow!"), direction, row


# ------------------------------------------------------------------- email


def pass_png_bytes(sp, box_size=8):
    img = qrcode.make(sp.payload, box_size=box_size)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def email_pass(sp):
    """Email the pass (QR inline) to the student. Returns a ``DeliveryResult``."""
    from email.mime.image import MIMEImage

    from .emails import DeliveryResult

    student = sp.visitor
    if not student.email:
        return DeliveryResult(skipped=True, reason="no_recipient")
    html = render_to_string("visits/student_pass_email.html", {"sp": sp, "student": student, "org": sp.organization})
    message = EmailMessage(
        subject=f"Your {sp.organization.name} student pass (valid till {sp.valid_until:%d %b %Y})",
        body=html,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[student.email],
    )
    message.content_subtype = "html"
    image = MIMEImage(pass_png_bytes(sp))
    image.add_header("Content-ID", "<student_pass>")
    image["Content-Disposition"] = "inline; filename=student-pass.png"
    message.attach(image)
    return deliver(message, event=EVENT_STUDENT_PASS, reference=sp.admission_number)
