from django.db import IntegrityError, transaction
from django.utils.text import slugify
from rest_framework import serializers

from accounts.models import Role, User
from organizations.models import Building, Department, Floor, Organization
from visits.models import QRPass, Visit, VisitType, Visitor
from visits.arrival import can_mark_arriving, mask_phone
from visits.services import visit_can_be_cancelled, visit_can_be_rescheduled

# How many slug candidates to try before reporting a naming collision. Two
# simultaneous signups can collide once; a small bound is plenty, and failing
# with a 400 beats looping.
SLUG_COLLISION_ATTEMPTS = 5


class RegisterSerializer(serializers.ModelSerializer):
    """Public self-service signup.

    Creates a **non-operational** account: least-privilege role, no workspace.
    That is enough to hold a JWT and reach ``POST /api/organizations/``, which
    is where the caller creates their own workspace and becomes its ADMIN. The
    console and every tenant-scoped read stay closed until then, because
    ``accounts.permissions.has_tenant`` is false for a tenantless account.

    ``role`` and ``organization`` are rejected rather than ignored. DRF drops
    unlisted fields silently, so a caller sending ``role=ADMIN`` would get a
    ``201`` and reasonably assume it worked -- a false confirmation of a
    privilege grant is its own kind of bug, and it hides the attempt from
    anyone reviewing the payload. An explicit 400 makes the request visible.
    """

    password = serializers.CharField(write_only=True, min_length=8)

    #: Never client-assignable. Authority and tenancy are server decisions.
    PROTECTED_FIELDS = frozenset(
        {
            "role",
            "organization",
            "is_staff",
            "is_superuser",
            "is_active",
            "failed_login_attempts",
            "locked_until",
            "id",
        }
    )

    class Meta:
        model = User
        fields = ["email", "full_name", "phone", "password"]

    def validate(self, attrs):
        if not isinstance(self.initial_data, dict):
            # e.g. a list or string body: nothing to inspect key-wise, and
            # DRF would reject it below anyway.
            return attrs
        attempted = sorted(self.PROTECTED_FIELDS & set(self.initial_data))
        if attempted:
            raise serializers.ValidationError(
                {
                    field: "This field is not assignable during registration."
                    for field in attempted
                }
            )
        return attrs

    def validate_email(self, value):
        # Lower-case the domain *and* the local part: the authentication
        # backend looks accounts up case-insensitively, so two accounts that
        # differ only in case would be ambiguous at login.
        return (value or "").strip().lower()

    def validate_password(self, value):
        # Run the full Django validator chain (length, common passwords,
        # numeric-only, similarity to the user's own attributes), not just the
        # eight-character minimum (audit finding "registration password
        # validators are incomplete").
        from django.contrib.auth.password_validation import validate_password
        from django.core.exceptions import ValidationError as DjangoValidationError

        probe = User(
            email=self.initial_data.get("email", "") if isinstance(self.initial_data, dict) else "",
            full_name=self.initial_data.get("full_name", "") if isinstance(self.initial_data, dict) else "",
        )
        try:
            validate_password(value, user=probe)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages))
        return value

    def create(self, validated_data):
        password = validated_data.pop("password")
        # State the role rather than inheriting it from the model default, so
        # the least-privilege guarantee is visible at the point of creation and
        # survives a future change to that default.
        validated_data["role"] = Role.RECEPTIONIST
        validated_data["organization"] = None
        return User.objects.create_user(**validated_data, password=password)


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "email", "full_name", "phone", "role", "organization"]


class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ["id", "name", "slug", "tagline", "timezone", "working_hours_start", "working_hours_end"]


class OrganizationCreateSerializer(serializers.ModelSerializer):
    """Create a workspace and (optionally) a default building with it."""

    building_name = serializers.CharField(
        required=False, allow_blank=True, max_length=200,
        help_text="Name of the default building to create for the workspace.",
    )

    class Meta:
        model = Organization
        fields = [
            "name", "tagline", "address", "city", "country", "timezone",
            "working_hours_start", "working_hours_end", "building_name",
        ]

    def validate_name(self, value):
        if not value.strip():
            raise serializers.ValidationError("Workspace name is required.")
        return value.strip()

    def validate_timezone(self, value):
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        value = (value or "").strip() or "UTC"
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise serializers.ValidationError("Unknown IANA timezone (e.g. Asia/Kolkata).")
        return value

    def create(self, validated_data):
        validated_data.pop("building_name", None)
        base = slugify(validated_data["name"]) or "workspace"

        # Slug assignment is a check-then-act if done the obvious way: pick the
        # first slug that is not taken, then INSERT it. Two people signing up a
        # workspace with the same name at the same moment can both observe the
        # same free slug, and Organization.slug being unique then raises
        # IntegrityError -- surfacing as a 500 for what is really a naming
        # collision, on a request that would otherwise have succeeded.
        #
        # So the database is allowed to be the arbiter: try the candidate, and
        # on a collision move to the next one. There is no pre-check, because a
        # pre-check is precisely the part that races.
        for attempt in range(SLUG_COLLISION_ATTEMPTS):
            candidate = base if attempt == 0 else f"{base}-{attempt + 1}"
            validated_data["slug"] = candidate
            try:
                # The savepoint is load-bearing rather than defensive: an
                # IntegrityError aborts the enclosing transaction, so without
                # one the retry could not run a single query before failing with
                # TransactionManagementError instead.
                with transaction.atomic():
                    return Organization.objects.create(**validated_data)
            except IntegrityError:
                # Retry only an actual slug collision. Any other IntegrityError
                # -- a duplicate code, a dangling foreign key -- is a real
                # error and must surface as itself instead of being retried five
                # times and then reported as a name collision.
                if not Organization.objects.filter(slug=candidate).exists():
                    raise

        raise serializers.ValidationError(
            {"name": "A workspace with a similar name already exists."}
        )


class DepartmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Department
        fields = ["id", "name", "code"]


class VisitorSerializer(serializers.ModelSerializer):
    """Visitor profile as exposed to the console.

    ``is_blacklisted`` prefers the ``is_blacklisted_flag`` annotation that the
    list endpoints attach (one EXISTS per row inside the main query) and only
    falls back to the model property -- which is a query per visitor -- for
    callers that serialize a bare instance.
    """

    is_blacklisted = serializers.SerializerMethodField()
    blacklist_reason = serializers.SerializerMethodField()
    visit_count = serializers.IntegerField(read_only=True, required=False)
    last_visit_at = serializers.DateTimeField(read_only=True, required=False)

    class Meta:
        model = Visitor
        fields = [
            "id", "full_name", "phone", "email", "company", "designation", "address",
            "photo", "document_type", "document_number", "vehicle_number", "vehicle_type",
            "emergency_contact", "emergency_phone", "special_notes", "is_blacklisted",
            "blacklist_reason", "visit_count", "last_visit_at", "created_at",
        ]
        read_only_fields = ["created_at", "photo"]

    #: Fields only shown to callers holding the named capability. Stripped in
    #: ``to_representation`` so every endpoint that nests this serializer gets
    #: the same least-privilege shape without remembering to opt in.
    PII_FIELDS = ("address", "emergency_contact", "emergency_phone")
    DOCUMENT_FIELDS = ("document_type", "document_number")

    def to_representation(self, instance):
        data = super().to_representation(instance)
        from accounts.permissions import has_perm

        request = self.context.get("request")
        user = getattr(request, "user", None)
        if not (user and user.is_authenticated and has_perm(user, "view_visitor_pii")):
            for f in self.PII_FIELDS:
                data.pop(f, None)
        if not (user and user.is_authenticated and has_perm(user, "view_visitor_documents")):
            for f in self.DOCUMENT_FIELDS:
                data.pop(f, None)
        return data

    def get_is_blacklisted(self, obj):
        flag = getattr(obj, "is_blacklisted_flag", None)
        if flag is not None:
            return bool(flag)
        return obj.is_blacklisted

    def get_blacklist_reason(self, obj):
        if not self.get_is_blacklisted(obj):
            return ""
        reason = getattr(obj, "blacklist_reason_flag", None)
        if reason is not None:
            return reason or ""
        return obj.blacklist_reason

    def validate_phone(self, value):
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("Phone is required.")
        return value

    def validate_full_name(self, value):
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("Full name is required.")
        return value


class QRPassSerializer(serializers.ModelSerializer):
    """Pass status for everyone; the raw credential only for ``badge_print``.

    ``token`` + ``signature`` *is* the admission credential. The gate scans
    it from the visitor's phone or printout and never needs to render it, so
    roles without ``badge_print`` (SECURITY) get the status fields only.
    """

    class Meta:
        model = QRPass
        fields = ["token", "signature", "expires_at", "is_used", "is_valid"]
        read_only_fields = fields

    def to_representation(self, instance):
        data = super().to_representation(instance)
        from accounts.permissions import has_perm

        user = getattr(self.context.get("request"), "user", None)
        if not (user and user.is_authenticated and has_perm(user, "badge_print")):
            data.pop("token", None)
            data.pop("signature", None)
        return data


class VisitSerializer(serializers.ModelSerializer):
    """Read-only representation of a visit.

    Every field is read-only on purpose (finding F2).  This serializer used to
    accept a write-only ``visitor_id`` plus ``host``/``building`` and persist
    the row itself in ``create()``, which wrote ``organization`` and
    ``created_by`` outside the service layer and so bypassed ``create_visitor``,
    the registration throttle, ``register_visit``'s validation and the audit
    trail.  Creation now happens only in ``RegisterVisitView`` /
    ``WalkInRegistrationView`` via ``visits.services.register_visit``; the
    corresponding rows are re-read from the database and rendered here.
    """

    visitor = VisitorSerializer(read_only=True)
    host_name = serializers.CharField(source="host.full_name", read_only=True, default="")
    building_name = serializers.CharField(source="building.name", read_only=True, default="")
    department_name = serializers.CharField(source="department.name", read_only=True, default="")
    created_by_name = serializers.CharField(source="created_by.full_name", read_only=True, default="")
    checked_in_by_name = serializers.CharField(source="checked_in_by.full_name", read_only=True, default="")
    checked_out_by_name = serializers.CharField(source="checked_out_by.full_name", read_only=True, default="")
    visit_type_label = serializers.CharField(source="get_visit_type_display", read_only=True)
    qr = QRPassSerializer(source="qr_pass", read_only=True)
    duration_minutes = serializers.IntegerField(read_only=True)

    class Meta:
        model = Visit
        fields = [
            "id", "visit_id", "visitor", "host", "host_name",
            "building", "building_name", "department_name", "purpose",
            "visit_type", "visit_type_label", "source", "visit_date",
            "expected_arrival", "expected_exit", "status", "qr", "duration_minutes",
            "registered_at", "approved_at", "rejected_at", "rejection_reason",
            "checked_in_at", "checked_out_at", "cancelled_at", "cancelled_reason",
            "arriving_at", "created_by_name", "checked_in_by_name",
            "checked_out_by_name", "notes",
        ]
        read_only_fields = fields

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # A OneToOne reverse accessor raises RelatedObjectDoesNotExist rather
        # than returning None when no pass exists; DRF's ``source=`` handling
        # already copes with that, but be explicit so the SPA always sees a key.
        data.setdefault("qr", None)
        return data


class DashboardSummarySerializer(serializers.Serializer):
    today = serializers.IntegerField()
    week = serializers.IntegerField()
    month = serializers.IntegerField()
    inside = serializers.IntegerField()
    pending = serializers.IntegerField()
    approved = serializers.IntegerField()
    avg_duration_minutes = serializers.IntegerField()
    checked_out = serializers.IntegerField()
    rejected = serializers.IntegerField()
    trend = serializers.IntegerField()


# ---------------------------------------------------------------------------
# Public pre-booking (anonymous visitors) — read-only option sets + submit.
# ---------------------------------------------------------------------------


class FloorPublicSerializer(serializers.ModelSerializer):
    class Meta:
        model = Floor
        fields = ["id", "name", "level"]


class PublicBuildingSerializer(serializers.ModelSerializer):
    floors = FloorPublicSerializer(source="floor_set", many=True, read_only=True)

    class Meta:
        model = Building
        fields = ["id", "name", "address", "floors"]


class PublicHostSerializer(serializers.Serializer):
    """A Book-a-Visit 'person to meet' option (an active org employee).

    ``id`` is the account/user id so the host FK can be referenced directly.
    """

    id = serializers.IntegerField()
    name = serializers.CharField()
    designation = serializers.CharField()
    department = serializers.IntegerField(required=False, allow_null=True)


class VisitorFacingVisitSerializer(serializers.ModelSerializer):
    """Visitor-facing read-only shape for a visit.

    Deliberately excludes everything a visitor must not see (document
    numbers, internal notes, audit data, employee contact details). Phone is
    masked and the booking reference is the visit UUID, matching what the
    visitor was shown after submitting.
    """

    reference = serializers.SerializerMethodField()
    visit_type_label = serializers.SerializerMethodField()
    expected_arrival = serializers.SerializerMethodField()
    expected_exit = serializers.SerializerMethodField()
    host_name = serializers.CharField(source="host.full_name", read_only=True, default="")
    host_designation = serializers.SerializerMethodField()
    department_name = serializers.CharField(source="department.name", read_only=True, default="")
    building_name = serializers.CharField(source="building.name", read_only=True, default="")
    floor_name = serializers.CharField(source="floor.name", read_only=True, default="")
    organization_name = serializers.CharField(source="organization.name", read_only=True, default="")
    phone_masked = serializers.SerializerMethodField()
    qr = serializers.SerializerMethodField()
    can_reschedule = serializers.SerializerMethodField()
    can_cancel = serializers.SerializerMethodField()
    can_arrive = serializers.SerializerMethodField()
    arriving_at = serializers.DateTimeField(read_only=True)

    class Meta:
        model = Visit
        fields = [
            "id",
            "reference",
            "status",
            "source",
            "visit_type",
            "visit_type_label",
            "purpose",
            "visit_date",
            "expected_arrival",
            "expected_exit",
            "organization_name",
            "department_name",
            "building_name",
            "floor_name",
            "host_name",
            "host_designation",
            "phone_masked",
            "rejection_reason",
            "cancelled_at",
            "cancelled_reason",
            "registered_at",
            "approved_at",
            "rejected_at",
            "checked_in_at",
            "checked_out_at",
            "qr",
            "can_reschedule",
            "can_cancel",
            "can_arrive",
            "arriving_at",
        ]

    def get_reference(self, obj):
        return str(obj.visit_id).upper()

    def get_visit_type_label(self, obj):
        return obj.get_visit_type_display()

    def get_expected_arrival(self, obj):
        return obj.expected_arrival.strftime("%H:%M") if obj.expected_arrival else ""

    def get_expected_exit(self, obj):
        return obj.expected_exit.strftime("%H:%M") if obj.expected_exit else ""

    def get_host_designation(self, obj):
        if obj.host is None:
            return ""
        employee = getattr(obj.host, "employee_profile", None)
        return getattr(employee, "designation", "") or ""

    def get_phone_masked(self, obj):
        return mask_phone(obj.visitor.phone)

    def get_qr(self, obj):
        qr = getattr(obj, "qr_pass", None)
        if qr is None:
            return None
        return {
            "token": str(qr.token),
            "signature": qr.signature,
            "is_valid": qr.is_valid,
        }

    def get_can_reschedule(self, obj):
        return visit_can_be_rescheduled(obj)

    def get_can_cancel(self, obj):
        return visit_can_be_cancelled(obj)

    def get_can_arrive(self, obj):
        allowed, _ = can_mark_arriving(obj)
        return allowed


class BookingVisitorSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=150)
    phone = serializers.CharField(max_length=20)
    email = serializers.EmailField(required=False, allow_blank=True)
    company = serializers.CharField(required=False, allow_blank=True, max_length=150)
    designation = serializers.CharField(
        required=False, allow_blank=True, max_length=150
    )


class BookingSubmitSerializer(serializers.Serializer):
    """Shape/type validation for the public booking POST.

    Business rules (org-scoped relationships, working hours, date rules, host
    suitability) are enforced in ``visits.services.create_pre_booking``.
    """

    visitor = BookingVisitorSerializer()
    visit_type = serializers.ChoiceField(choices=VisitType.choices)
    department = serializers.IntegerField(required=False, allow_null=True)
    building = serializers.IntegerField(required=False, allow_null=True)
    floor = serializers.IntegerField(required=False, allow_null=True)
    host = serializers.IntegerField(required=False, allow_null=True)
    visit_date = serializers.DateField()
    expected_arrival = serializers.RegexField(r"^\d{2}:\d{2}$", max_length=5)
    expected_exit = serializers.RegexField(r"^\d{2}:\d{2}$", max_length=5)
    purpose = serializers.CharField(allow_blank=False, max_length=200)
    purpose_other = serializers.CharField(
        required=False, allow_blank=True, max_length=120
    )
    notes = serializers.CharField(required=False, allow_blank=True, max_length=1000)
