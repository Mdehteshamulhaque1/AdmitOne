from django.db import models


class Organization(models.Model):
    """Multi-tenant company. Everything in SecureGate hangs off this."""

    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    logo = models.ImageField(upload_to="org_logos/", blank=True, null=True)
    tagline = models.CharField(max_length=255, blank=True)
    address = models.TextField(blank=True)
    city = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100, blank=True)
    timezone = models.CharField(max_length=80, default="UTC")
    working_hours_start = models.TimeField(default="09:00")
    working_hours_end = models.TimeField(default="18:00")
    security_policies = models.JSONField(default=dict, blank=True)
    visitor_policies = models.JSONField(default=dict, blank=True)

    # Per-weekday working windows used by the appointment-slot engine.
    # Shape: {"0".."6"} weekday ints (Monday=0..Sunday=6) mapping to either
    #   None/[]            -> closed that day
    #   [{"start","end"}]  -> one or more working windows (breaks between)
    # An empty dict falls back to the plain daily ``working_hours_start`` /
    # ``working_hours_end`` for every weekday (legacy organizations).
    weekly_working_hours = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def building_count(self):
        return self.buildings.count()


class Building(models.Model):
    """A physical location within an organization."""

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="buildings"
    )
    name = models.CharField(max_length=200)
    address = models.TextField(blank=True)
    floors = models.PositiveIntegerField(default=1)
    entry_gates = models.PositiveIntegerField(default=1)
    exit_gates = models.PositiveIntegerField(default=1)
    has_reception_desk = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.organization.name} / {self.name}"


class Floor(models.Model):
    building = models.ForeignKey(
        Building, on_delete=models.CASCADE, related_name="floor_set"
    )
    name = models.CharField(max_length=100)  # e.g. "1st Floor"
    level = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["level"]

    def __str__(self):
        return f"{self.building.name} - {self.name}"


class Gate(models.Model):
    class GateType(models.TextChoices):
        ENTRY = "ENTRY", "Entry"
        EXIT = "EXIT", "Exit"

    building = models.ForeignKey(
        Building, on_delete=models.CASCADE, related_name="gates"
    )
    name = models.CharField(max_length=100)
    gate_type = models.CharField(max_length=10, choices=GateType.choices)

    def __str__(self):
        return f"{self.building.name} / {self.name} ({self.gate_type})"


class Department(models.Model):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="departments"
    )
    name = models.CharField(max_length=150)
    code = models.CharField(max_length=20, blank=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            # A short code identifies a department inside its workspace, so
            # two departments of the same organisation cannot share one.
            # Blank codes are exempt (several departments may have none).
            models.UniqueConstraint(
                fields=["organization", "code"],
                condition=~models.Q(code=""),
                name="uniq_department_code_per_org",
            ),
        ]

    def __str__(self):
        return self.name


class Employee(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        INACTIVE = "INACTIVE", "Inactive"
        ON_LEAVE = "ON_LEAVE", "On Leave"

    user = models.OneToOneField(
        "accounts.User", on_delete=models.CASCADE, related_name="employee_profile"
    )
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="employees"
    )
    employee_id = models.CharField(max_length=50, unique=True)
    department = models.ForeignKey(
        Department,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employees",
    )
    building = models.ForeignKey(
        Building,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employees",
    )
    designation = models.CharField(max_length=150, blank=True)
    office_location = models.CharField(max_length=150, blank=True)
    joining_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)

    class Meta:
        ordering = ["employee_id"]

    def __str__(self):
        return f"{self.user.full_name} ({self.employee_id})"


class AuditLog(models.Model):
    """Append-only trail of every meaningful action on the platform.

    **Immutable at the database level.** Migration
    ``organizations.0006_auditlog_immutability_triggers`` installs a trigger
    that aborts any ``UPDATE`` changing the recorded facts (``action``,
    ``entity_type``, ``entity_id``, ``details``, ``ip_address``,
    ``created_at``) on both PostgreSQL and SQLite, and on PostgreSQL (the
    production database) also aborts any ``DELETE``. The only writes allowed
    after insert are the ``SET_NULL`` cascades on ``user`` and
    ``organization`` when an actor or workspace is removed, so the trail
    survives their deletion. Application code never updates or deletes a row,
    there is no serializer or API route for writing one, and ``AuditLogAdmin``
    denies add/change/delete. Retention therefore has to be an explicit,
    privileged operation (``TRUNCATE``, which row triggers ignore, or dropping
    the trigger first), which is the point: nobody alters history by accident
    or through an ordinary bug.

    ``organization`` is the tenant key, stored on the row rather than derived
    from ``user``, because several audited actions have no human actor at all
    (the public booking form, the visitor portal, the nightly archive job) and
    because filtering by ``user__organization`` both lost those rows and, for a
    caller with no workspace, compiled to ``IS NULL`` and exposed every
    unassigned actor's entries (the same trap as finding F4).
    """

    user = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
        help_text=(
            "Tenant the action belongs to. NULL for a platform-level action, or "
            "for a row written before this column existed whose tenant cannot be "
            "determined without guessing."
        ),
    )
    action = models.CharField(max_length=120)
    entity_type = models.CharField(max_length=80, blank=True)
    # Wide enough for the longest key actually stored here: Visit.visit_id is a
    # UUID (36 chars) and Employee.employee_id is up to 50.  Free text -- names,
    # e-mail addresses, purposes -- belongs in ``details``.
    entity_id = models.CharField(max_length=64, blank=True)
    details = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at"], name="audit_user_created_idx"),
            models.Index(
                fields=["organization", "-created_at"], name="audit_org_created_idx"
            ),
        ]

    def __str__(self):
        return f"{self.action} @ {self.created_at:%Y-%m-%d %H:%M}"

    @staticmethod
    def log(
        user, action, entity_type="", entity_id="", details="", ip_address=None,
        organization_id=None,
    ):
        """Append one audit row.

        ``organization_id`` defaults to the actor's workspace so the ordinary
        call sites are tenant-addressable without changes.  Actions performed by
        nobody on a tenant's behalf -- a public booking, a portal session, the
        archive job -- pass it explicitly, because there is no actor to inherit
        it from.  A bare id is accepted rather than an ``Organization``
        instance because most callers already hold one (and it keeps the call
        sites inside a service from needing a ``.organization`` fetch).
        """
        if organization_id is None and user is not None:
            organization_id = getattr(user, "organization_id", None)
        return AuditLog.objects.create(
            user=user,
            organization_id=organization_id,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id or "")[:64],
            details=details,
            ip_address=ip_address,
        )
