import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone

from . import signing
from .storage import DocumentFileField, private_document_storage
from .validators import validate_document_upload, validate_image_upload


class DocumentType(models.TextChoices):
    AADHAAR = "AADHAAR", "Aadhaar"
    PASSPORT = "PASSPORT", "Passport"
    PAN = "PAN", "PAN Card"
    DRIVING_LICENSE = "DRIVING_LICENSE", "Driving License"
    COMPANY_ID = "COMPANY_ID", "Company ID"


class VehicleType(models.TextChoices):
    CAR = "CAR", "Car"
    BIKE = "BIKE", "Bike"
    TRUCK = "TRUCK", "Truck"
    VAN = "VAN", "Van"
    OTHER = "OTHER", "Other"


class VisitStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"
    CHECKED_IN = "CHECKED_IN", "Checked In"
    CHECKED_OUT = "CHECKED_OUT", "Checked Out"
    CANCELLED = "CANCELLED", "Cancelled"
    ARCHIVED = "ARCHIVED", "Archived"


class VisitType(models.TextChoices):
    BUSINESS_MEETING = "BUSINESS_MEETING", "Business Meeting"
    INTERVIEW = "INTERVIEW", "Interview"
    CAMPUS_PLACEMENT = "CAMPUS_PLACEMENT", "Campus / Placement"
    CLIENT_MEETING = "CLIENT_MEETING", "Client Meeting"
    VENDOR_DELIVERY = "VENDOR_DELIVERY", "Vendor / Delivery"
    TRAINING_WORKSHOP = "TRAINING_WORKSHOP", "Training / Workshop"
    GUEST = "GUEST", "Guest"
    OTHER = "OTHER", "Other"


class VisitSource(models.TextChoices):
    """How a visit entered the system.

    ``STAFF`` = registered by a receptionist/admin from the desk portal,
    ``WALK_IN`` = registered on the spot and instantly approved by staff,
    ``PUBLIC_BOOKING`` = pre-booked by the visitor through the public form.
    """

    STAFF = "STAFF", "Desk registration"
    WALK_IN = "WALK_IN", "Walk-in"
    PUBLIC_BOOKING = "PUBLIC_BOOKING", "Pre-booked"


class BlacklistReason(models.TextChoices):
    SECURITY_CONCERN = "SECURITY_CONCERN", "Security Concern"
    FAKE_DOCUMENTS = "FAKE_DOCUMENTS", "Fake Documents"
    MISCONDUCT = "MISCONDUCT", "Misconduct"
    PERMANENT_BAN = "PERMANENT_BAN", "Permanent Ban"


class Room(models.Model):
    """A bookable space inside a building: a lab, classroom, interview cabin,
    placement hall. Staff assign a room to a visit on approval; trainers scan
    passes at the room door for attendance.
    """

    class RoomType(models.TextChoices):
        CLASSROOM = "CLASSROOM", "Classroom"
        LAB = "LAB", "Lab"
        INTERVIEW_CABIN = "INTERVIEW_CABIN", "Interview cabin"
        PLACEMENT_HALL = "PLACEMENT_HALL", "Placement hall"
        GROOMING_ROOM = "GROOMING_ROOM", "Grooming room"
        SEMINAR_HALL = "SEMINAR_HALL", "Seminar hall"
        MEETING_ROOM = "MEETING_ROOM", "Meeting room"
        RECEPTION = "RECEPTION", "Reception / counselling"
        OFFICE = "OFFICE", "Office"
        OTHER = "OTHER", "Other"

    building = models.ForeignKey("organizations.Building", on_delete=models.CASCADE, related_name="rooms")
    floor = models.ForeignKey(
        "organizations.Floor", on_delete=models.SET_NULL, null=True, blank=True, related_name="rooms"
    )
    number = models.CharField(max_length=30, help_text="Door number or code, e.g. 301 or L-2")
    name = models.CharField(max_length=120, blank=True, help_text="Friendly name, e.g. Java Lab")
    room_type = models.CharField(max_length=20, choices=RoomType.choices, default=RoomType.CLASSROOM)
    capacity = models.PositiveIntegerField(default=0, help_text="0 = not tracked")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["building__name", "floor__level", "number"]
        constraints = [
            models.UniqueConstraint(fields=["building", "number"], name="uniq_room_number_per_building"),
        ]

    def __str__(self):
        return self.label

    @property
    def label(self):
        base = f"{self.number} {self.name}".strip() if self.name else self.number
        return f"{base} ({self.get_room_type_display()})"


class Visitor(models.Model):
    """A person who visits one organization, owned by that tenant.

    ``organization`` is the tenant boundary for every piece of PII on this
    row.  Access is filtered on it directly (never through a reverse join on
    ``visits``) so one workspace can never read another workspace's visitor
    identity documents, address, emergency contacts or notes -- even when the
    same human is a legitimate visitor to more than one organization, in which
    case each workspace keeps its own record.
    """

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="visitors",
        null=True,
        blank=True,
        help_text=(
            "Owning tenant. Legacy rows that cannot be attributed to exactly "
            "one organization stay NULL and are quarantined from every tenant."
        ),
    )
    # The self-service account (if any) that owns this per-tenant visitor
    # record. One account can hold one Visitor row per organisation it visits.
    account = models.ForeignKey(
        "visits.VisitorAccount",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="visitor_records",
    )
    full_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=20)
    email = models.EmailField(blank=True)
    company = models.CharField(max_length=150, blank=True)
    designation = models.CharField(max_length=150, blank=True)
    address = models.TextField(blank=True)

    # Who the visitor is (training-centre profile). ``category`` is one of the
    # workspace's configured visitor categories (``visits.purposes``); the rest
    # are free text chosen from dropdowns in the booking flow.
    category = models.CharField(max_length=40, blank=True, default="")
    state = models.CharField(max_length=60, blank=True, default="")
    university = models.CharField(max_length=150, blank=True, default="")
    qualification = models.CharField(max_length=60, blank=True, default="")
    passing_year = models.PositiveIntegerField(null=True, blank=True)

    photo = models.ImageField(
        upload_to="visitor_photos/",
        blank=True,
        null=True,
        validators=[validate_image_upload],
    )

    # Documents
    document_type = models.CharField(
        max_length=20, choices=DocumentType.choices, blank=True
    )
    document_number = models.CharField(max_length=60, blank=True)
    # Stored outside MEDIA_ROOT and served only by ``visits.views.document``.
    # The extension allowlist that used to sit here was the *only* check, and an
    # extension is attacker-controlled: ``passport.pdf`` was a free pass for any
    # bytes at all. ``validate_document_upload`` also sizes the file and sniffs
    # its content, so a renamed HTML or SVG payload is rejected at upload.
    document_file = DocumentFileField(
        upload_to="visitor_documents/",
        storage=private_document_storage,
        blank=True,
        null=True,
        validators=[validate_document_upload],
    )

    # Vehicle
    vehicle_number = models.CharField(max_length=30, blank=True)
    vehicle_type = models.CharField(
        max_length=10, choices=VehicleType.choices, blank=True
    )

    emergency_contact = models.CharField(max_length=100, blank=True)
    emergency_phone = models.CharField(max_length=20, blank=True)
    special_notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # One identity per phone number *per tenant*.  The same phone may
            # exist independently in different organizations; blank phones and
            # unattributed legacy rows are excluded so they never collide.
            models.UniqueConstraint(
                fields=["organization", "phone"],
                condition=Q(organization__isnull=False) & ~Q(phone=""),
                name="uniq_visitor_org_phone",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "-created_at"], name="visitor_org_created_idx"
            ),
        ]

    def __str__(self):
        return self.full_name

    @property
    def is_blacklisted(self):
        return self.blacklists.filter(is_active=True).exists()

    @property
    def blacklist_reason(self):
        entry = self.blacklists.filter(is_active=True).first()
        return entry.reason if entry else ""


class Visit(models.Model):
    """One visit of a visitor to an organization, following the approval workflow."""

    visit_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    visitor = models.ForeignKey(
        Visitor, on_delete=models.CASCADE, related_name="visits"
    )
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="visits"
    )
    building = models.ForeignKey(
        "organizations.Building",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="visits",
    )
    floor = models.ForeignKey(
        "organizations.Floor",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="visits",
    )
    department = models.ForeignKey(
        "organizations.Department",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="visits",
    )
    host = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="hosted_visits",
        verbose_name="Host employee",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_visits",
    )

    # Assigned by staff on approval ("report to Lab 301, 3rd floor"). Trainers
    # record attendance against this room by scanning the visitor's pass.
    room = models.ForeignKey(
        "visits.Room",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="visits",
    )
    visitor_category = models.CharField(max_length=40, blank=True, default="")

    visit_type = models.CharField(
        max_length=30, choices=VisitType.choices, blank=True, default=""
    )
    source = models.CharField(
        max_length=20, choices=VisitSource.choices, default=VisitSource.STAFF
    )
    purpose = models.CharField(max_length=200)
    notes = models.TextField(blank=True)

    visit_date = models.DateField(default=timezone.localdate)
    expected_arrival = models.TimeField(default="10:00")
    expected_exit = models.TimeField(default="17:00")

    status = models.CharField(
        max_length=20, choices=VisitStatus.choices, default=VisitStatus.PENDING
    )

    # Timestamps for the workflow
    registered_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.CharField(max_length=300, blank=True)
    checked_in_at = models.DateTimeField(null=True, blank=True)
    checked_out_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_reason = models.CharField(max_length=120, blank=True)

    # "I'm Arriving" signal: the visitor announces they are on their way. This
    # is a status SIGNAL only — real entry still goes through the QR/check-in
    # security flow and arriving_at never implies CHECKED_IN.
    arriving_at = models.DateTimeField(null=True, blank=True)
    arriving_source = models.CharField(max_length=20, blank=True, default="")
    checked_in_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="checkins",
    )
    checked_out_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="checkouts",
    )

    class Meta:
        ordering = ["-registered_at"]
        indexes = [
            models.Index(fields=["status", "visit_date"]),
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["organization", "-registered_at"], name="visit_org_registered_idx"),
            models.Index(
                fields=["host", "visit_date", "status"],
                name="visit_host_date_status_idx",
            ),
        ]

    def __str__(self):
        return f"{self.visitor.full_name} → {self.purpose} ({self.status})"

    @property
    def duration_minutes(self):
        if self.checked_in_at and self.checked_out_at:
            delta = self.checked_out_at - self.checked_in_at
            return int(delta.total_seconds() // 60)
        return 0


class QRPass(models.Model):
    """Cryptographically signed QR pass bound to one visit and one workspace.

    The QR encodes ``{token}|{signature}`` and nothing else.  The signature is
    an HMAC-SHA256 over ``sg-qr-v1|{visit_id}|{organization_id}|{token}`` under a
    **dedicated** signing key (see :mod:`visits.signing`), so:

    * a pass cannot be forged or edited without the server key;
    * the workspace is inside the signed message, so a pass minted for one
      tenant can never validate against another tenant's visit;
    * verification accepts a key ring, so the signing key can be rotated
      without invalidating passes that are still inside their validity window.

    ``signing_key_id`` records which key minted the pass, for rotation
    diagnostics.  The pass is also single-use and time-boxed; both are enforced
    at redemption, not just here.
    """

    visit = models.OneToOneField(Visit, on_delete=models.CASCADE, related_name="qr_pass")
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    signature = models.CharField(max_length=64, editable=False)
    signing_key_id = models.CharField(max_length=32, blank=True, default="", editable=False)
    generated_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    used_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"QRPass {self.token}"

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at

    @property
    def is_valid(self):
        return not self.is_used and not self.is_expired

    @classmethod
    def _valid_minutes(cls, valid_minutes=None):
        if valid_minutes is not None:
            return int(valid_minutes)
        return int(getattr(settings, "QR_PASS_VALID_MINUTES", 120))

    @classmethod
    def issue(cls, visit, valid_minutes=None):
        """Generate and persist a signed QR pass for an approved visit."""
        token = uuid.uuid4()
        signature = signing.sign(visit.visit_id, visit.organization_id, token)
        return cls.objects.create(
            visit=visit,
            token=token,
            signature=signature,
            signing_key_id=signing.active_key_id(),
            expires_at=timezone.now()
            + timezone.timedelta(minutes=cls._valid_minutes(valid_minutes)),
        )

    @classmethod
    def reissue(cls, visit, valid_minutes=None):
        """Regenerate the signed pass for an approved visit.

        A visit owns at most one pass (OneToOne), so this rotates the token,
        signature, key id and validity window on the existing row (or creates
        the pass if none exists yet).  The previous pass stops working
        immediately: its token is gone from the table, so a scan of the old
        artifact resolves to no row at all.  Any QR image already printed or
        e-mailed is therefore dead the moment this returns.
        """
        token = uuid.uuid4()
        signature = signing.sign(visit.visit_id, visit.organization_id, token)
        expires_at = timezone.now() + timezone.timedelta(
            minutes=cls._valid_minutes(valid_minutes)
        )
        qr, created = cls.objects.get_or_create(
            visit=visit,
            defaults={
                "token": token,
                "signature": signature,
                "signing_key_id": signing.active_key_id(),
                "expires_at": expires_at,
                "is_used": False,
                "used_at": None,
            },
        )
        if not created:
            qr.token = token
            qr.signature = signature
            qr.signing_key_id = signing.active_key_id()
            qr.expires_at = expires_at
            qr.is_used = False
            qr.used_at = None
            qr.save(
                update_fields=[
                    "token",
                    "signature",
                    "signing_key_id",
                    "expires_at",
                    "is_used",
                    "used_at",
                ]
            )
        return qr

    @classmethod
    def verify(cls, raw_token, raw_signature):
        """Validate a scanned QR artifact.

        Checks, in order: payload present, token well-formed and registered,
        signature valid under any currently accepted key, not already redeemed,
        not expired.  Returns ``(ok, message, qr)``.

        ``qr`` is ``None`` on **every** failure path.  Returning the row on a
        failed check is a trap: the scan view only reads it when ``ok`` is
        true, but any caller that reads it unconditionally would be handed a
        pass it just failed to authenticate, and the pass carries a visitor id
        and a workspace -- enough to cross a tenant boundary.  Callers that
        want to know *why* a scan failed read the message, not the row.
        """
        if not raw_token or not raw_signature:
            return False, "Invalid QR payload", None
        try:
            qr = cls.objects.select_related("visit").get(token=raw_token)
        except (cls.DoesNotExist, ValidationError, ValueError):
            # DoesNotExist: fresh/unknown pass. ValidationError/ValueError:
            # the token is not even a well-formed UUID - treat as unknown
            # rather than crashing the scanning endpoint with a 500.
            return False, "Unknown pass - not registered in system", None

        if signing.verify(qr.visit.visit_id, qr.visit.organization_id, qr.token, raw_signature) is None:
            return False, "Signature mismatch - pass looks tampered with", None
        if qr.is_used:
            return False, "Pass already used - duplicate entry blocked", None
        if qr.is_expired:
            return False, "Pass has expired", None
        return True, "Pass valid - proceed with check-in", qr



class VisitReminder(models.Model):
    """One scheduled notification for a pre-booked visit (per offset).

    Offsets are defined per organization (hours before the visit start) so
    reminder timing is configuration, not a hardcoded value. A row is created
    at booking time and consumed by ``send_due_visit_reminders``; the unique
    (visit, offset_hours) constraint makes duplicate delivery impossible even
    if the same sweep runs twice or the booking is re-scheduled.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        SENT = "SENT", "Sent"
        FAILED = "FAILED", "Failed"
        SKIPPED = "SKIPPED", "Skipped"

    visit = models.ForeignKey(
        Visit, on_delete=models.CASCADE, related_name="reminders"
    )
    offset_hours = models.PositiveIntegerField()
    trigger_at = models.DateTimeField()
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ["offset_hours"]
        constraints = [
            models.UniqueConstraint(
                fields=["visit", "offset_hours"],
                name="visit_reminder_unique_offset",
            ),
        ]

    def __str__(self):
        return (
            f"Reminder {self.offset_hours}h before visit "
            f"{self.visit_id} ({self.status})"
        )


class VisitNotification(models.Model):
    """Delivery record for one external notification event on a visit.

    One row per (visit, event) — the unique constraint is what makes
    notification delivery idempotent, so re-running an approval or a reminder
    sweep can never email twice for the same event. Status keeps a failed
    delivery visible without ever corrupting the visit transaction.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        SENT = "SENT", "Sent"
        FAILED = "FAILED", "Failed"
        NOT_CONFIGURED = "NOT_CONFIGURED", "Provider not configured"

    visit = models.ForeignKey(
        Visit, on_delete=models.CASCADE, related_name="notifications"
    )
    event = models.CharField(max_length=40)
    recipient = models.CharField(max_length=255, blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    provider = models.CharField(max_length=40, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["visit", "event"], name="visit_notification_unique_event"
            ),
        ]

    def __str__(self):
        return f"Notification {self.event} on visit {self.visit_id} ({self.status})"


class Blacklist(models.Model):
    visitor = models.ForeignKey(
        Visitor, on_delete=models.CASCADE, related_name="blacklists"
    )
    reason = models.CharField(max_length=30, choices=BlacklistReason.choices)
    comment = models.TextField(blank=True)
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            # At most one *active* ban per visitor. Lifted entries stay as
            # history, so the condition keeps the constraint off those rows.
            models.UniqueConstraint(
                fields=["visitor"],
                condition=Q(is_active=True),
                name="uniq_active_blacklist_per_visitor",
            ),
        ]

    def __str__(self):
        return f"{self.visitor.full_name} - {self.reason}"


class VisitorAccount(models.Model):
    """Self-service account for a visitor (NOT a staff ``accounts.User``).

    Visitors sign up once with an e-mail and password and can then book visits
    to any organisation, see their passes and manage their bookings. The
    account is deliberately a separate model: it has no role, no workspace and
    no path into the staff console, so a visitor credential can never be
    mistaken for an employee login by any permission check.  Per-organisation
    identity stays on ``Visitor`` (linked through ``Visitor.account``), so a
    tenant still only ever sees its own visitor record.
    """

    email = models.EmailField(unique=True)
    password = models.CharField(max_length=128)
    full_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=20)
    company = models.CharField(max_length=150, blank=True)
    designation = models.CharField(max_length=150, blank=True)
    # Training-centre profile, copied onto each per-organisation Visitor row
    # when the account books so staff see it without reaching the account.
    category = models.CharField(max_length=40, blank=True, default="")
    state = models.CharField(max_length=60, blank=True, default="")
    university = models.CharField(max_length=150, blank=True, default="")
    qualification = models.CharField(max_length=60, blank=True, default="")
    passing_year = models.PositiveIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    failed_login_attempts = models.PositiveIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    last_login = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # Sign-in is case-insensitive, so uniqueness must be too.
            models.UniqueConstraint(Lower("email"), name="uniq_visitor_account_email_ci"),
        ]

    def __str__(self):
        return f"{self.full_name} <{self.email}>"

    def set_password(self, raw_password):
        from django.contrib.auth.hashers import make_password

        self.password = make_password(raw_password)

    def check_password(self, raw_password):
        from django.contrib.auth.hashers import check_password

        return check_password(raw_password, self.password)

    @property
    def is_locked(self):
        return self.locked_until is not None and self.locked_until > timezone.now()


class VisitorAccountSession(models.Model):
    """Bearer session for a ``VisitorAccount`` (hash stored, raw token shown once)."""

    account = models.ForeignKey(
        VisitorAccount, on_delete=models.CASCADE, related_name="sessions"
    )
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    user_agent = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["expires_at"], name="visitor_acct_sess_exp_idx"),
        ]

    @property
    def is_expired(self):
        return timezone.now() >= self.expires_at

    def __str__(self):
        return f"VisitorAccountSession #{self.pk} ({self.account.email})"


class RoomAttendance(models.Model):
    """One scan of a visitor's pass at a room door (attendance / room entry).

    Distinct from the gate check-in: the gate scan is single-use and admits
    the visitor to the building; room scans may repeat (a student attends a
    class, then an interview, then the placement hall). A room scan requires
    the visit to be CHECKED_IN, so nobody can be "in a classroom" who never
    passed the gate.
    """

    visit = models.ForeignKey(Visit, on_delete=models.CASCADE, related_name="attendance")
    room = models.ForeignKey(
        "visits.Room", on_delete=models.CASCADE, related_name="attendance"
    )
    scanned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    scanned_at = models.DateTimeField(auto_now_add=True)
    note = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        ordering = ["-scanned_at"]
        indexes = [
            models.Index(fields=["room", "-scanned_at"], name="attendance_room_time_idx"),
            models.Index(fields=["visit", "-scanned_at"], name="attendance_visit_time_idx"),
        ]

    def __str__(self):
        return f"{self.visit.visitor.full_name} @ {self.room.number} {self.scanned_at:%H:%M}"


class StudentPass(models.Model):
    """A long-term (6-month) gate pass for a student admitted to the institute.

    Unlike ``QRPass`` (one visit, one scan) this pass is scanned every day:
    the first scan of a day records IN, the next OUT, and so on. Identity
    (name, contact number, photo, ID proof) lives on the student's ``Visitor``
    record, so the same privacy rules apply. The QR encodes
    ``SP|{token}|{signature}``; the signature is the workspace's QR signing key
    over ``SP:{token}``, so a student pass can never be replayed as a visitor
    pass (or the other way round) and is bound to one workspace.
    """

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        REVOKED = "REVOKED", "Revoked"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="student_passes"
    )
    visitor = models.ForeignKey(Visitor, on_delete=models.CASCADE, related_name="student_passes")
    admission_number = models.CharField(max_length=40)
    course = models.CharField(max_length=120)
    batch = models.CharField(max_length=60, blank=True)
    valid_from = models.DateField()
    valid_until = models.DateField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    signature = models.CharField(max_length=64, editable=False)
    signing_key_id = models.CharField(max_length=32, blank=True, default="", editable=False)
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    issued_at = models.DateTimeField(auto_now_add=True)
    renewed_count = models.PositiveIntegerField(default=0)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_reason = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-issued_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "admission_number"], name="uniq_student_admission_per_org"
            ),
        ]
        indexes = [models.Index(fields=["organization", "status", "valid_until"], name="studentpass_org_status_idx")]

    def __str__(self):
        return f"{self.admission_number} {self.visitor.full_name} ({self.valid_from} - {self.valid_until})"

    @staticmethod
    def signing_subject(token):
        return f"SP:{token}"

    def sign(self):
        self.signature = signing.sign(self.signing_subject(self.token), self.organization_id, self.token)
        self.signing_key_id = signing.active_key_id()

    @property
    def payload(self):
        return f"SP|{self.token}|{self.signature}"


class StudentPassScan(models.Model):
    """One gate scan of a student pass: entry (IN) or exit (OUT)."""

    class Direction(models.TextChoices):
        IN = "IN", "In"
        OUT = "OUT", "Out"

    student_pass = models.ForeignKey(StudentPass, on_delete=models.CASCADE, related_name="scans")
    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="+")
    direction = models.CharField(max_length=3, choices=Direction.choices)
    scan_date = models.DateField()
    scanned_at = models.DateTimeField(default=timezone.now)
    scanned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["-scanned_at"]
        indexes = [
            models.Index(fields=["organization", "scan_date"], name="studentscan_org_date_idx"),
            models.Index(fields=["student_pass", "-scanned_at"], name="studentscan_pass_time_idx"),
        ]

    def __str__(self):
        return f"{self.student_pass.admission_number} {self.direction} {self.scanned_at:%Y-%m-%d %H:%M}"
