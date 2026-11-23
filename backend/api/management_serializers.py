"""Serializers for the workspace-management surface of the REST API.

These back the SPA's Settings / Team / Blacklist / Audit pages.  They are kept
apart from ``api.serializers`` (visitor workflow) so the two surfaces can
evolve independently; nothing here is reachable by a tenantless account.
"""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from accounts.models import Role, User
from organizations.models import AuditLog, Building, Department, Employee, Floor, Organization
from visits.models import Blacklist, BlacklistReason, Room, RoomAttendance, Visitor
from visits.purposes import catalogue_for, validate_catalogue


# --------------------------------------------------------------- organization


MAX_PUBLIC_NOTICES = 20


def clean_public_notices(notices):
    """Validate the admin-written notices shown on the public Public Notice page.

    Each notice: ``title`` (<=120), ``body`` (<=1000), ``published_on`` and an
    optional ``until`` date (YYYY-MM-DD) after which it is hidden.
    """
    from datetime import date as _date

    if not isinstance(notices, list):
        raise serializers.ValidationError({"public_notices": "Notices must be a list."})
    if len(notices) > MAX_PUBLIC_NOTICES:
        raise serializers.ValidationError({"public_notices": f"Keep at most {MAX_PUBLIC_NOTICES} notices."})
    cleaned = []
    for n in notices:
        if not isinstance(n, dict):
            raise serializers.ValidationError({"public_notices": "Each notice must be an object."})
        title = str(n.get("title", "")).strip()
        body = str(n.get("body", "")).strip()
        if not title:
            raise serializers.ValidationError({"public_notices": "Every notice needs a title."})
        if len(title) > 120 or len(body) > 1000:
            raise serializers.ValidationError({"public_notices": "Titles are limited to 120 characters and details to 1000."})
        dates = {}
        for key in ("published_on", "until"):
            raw = str(n.get(key) or "").strip()
            if raw:
                try:
                    dates[key] = _date.fromisoformat(raw).isoformat()
                except ValueError:
                    raise serializers.ValidationError({"public_notices": f"{key} must be a date (YYYY-MM-DD)."})
        cleaned.append({
            "title": title,
            "body": body,
            "published_on": dates.get("published_on") or _date.today().isoformat(),
            "until": dates.get("until", ""),
        })
    return cleaned


class OrganizationDetailSerializer(serializers.ModelSerializer):
    """Full workspace profile; ``slug`` is read-only because it is the public
    booking URL and changing it would break every link already shared."""

    logo = serializers.ImageField(read_only=True)
    booking_path = serializers.SerializerMethodField()
    # The catalogue actually in force: the saved one, or the training-centre
    # defaults when the workspace has not customised it yet.
    visitor_catalogue = serializers.SerializerMethodField()

    class Meta:
        model = Organization
        fields = [
            "id", "name", "slug", "tagline", "logo", "address", "city", "country",
            "timezone", "working_hours_start", "working_hours_end", "weekly_working_hours",
            "visitor_policies", "security_policies", "visitor_catalogue", "booking_path",
            "created_at",
        ]
        read_only_fields = ["id", "slug", "logo", "created_at", "booking_path", "visitor_catalogue"]

    def get_visitor_catalogue(self, obj):
        return catalogue_for(obj)

    def validate_weekly_working_hours(self, value):
        """Per-weekday windows: ``{"0".."6": [{"start": "HH:MM", "end": "HH:MM"}, ...]}``.

        An empty list (or ``null``) closes that day; an empty dict falls back
        to the plain daily working hours. Windows must be ordered and must not
        overlap, because the slot engine walks them in sequence.
        """
        import re

        if value in (None, {}):
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError("weekly_working_hours must be an object keyed by weekday 0-6.")
        clock = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
        cleaned = {}
        for key, windows in value.items():
            if str(key) not in {"0", "1", "2", "3", "4", "5", "6"}:
                raise serializers.ValidationError(f"Unknown weekday key {key!r}; use 0 (Monday) to 6 (Sunday).")
            if windows in (None, []):
                cleaned[str(key)] = []
                continue
            if not isinstance(windows, list):
                raise serializers.ValidationError(f"Weekday {key}: expected a list of windows.")
            last_end = ""
            out = []
            for w in windows:
                start, end = (w or {}).get("start", ""), (w or {}).get("end", "")
                if not (clock.match(str(start)) and clock.match(str(end))):
                    raise serializers.ValidationError(f"Weekday {key}: times must be HH:MM.")
                if end <= start:
                    raise serializers.ValidationError(f"Weekday {key}: a window must end after it starts.")
                if start < last_end:
                    raise serializers.ValidationError(f"Weekday {key}: windows must be in order and must not overlap.")
                last_end = end
                out.append({"start": start, "end": end})
            cleaned[str(key)] = out
        return cleaned

    def get_booking_path(self, obj):
        return f"/book/{obj.slug}"

    def validate_name(self, value):
        value = (value or "").strip()
        if len(value) < 2:
            raise serializers.ValidationError("Workspace name must be at least 2 characters.")
        return value

    def validate_timezone(self, value):
        value = (value or "").strip() or "UTC"
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise serializers.ValidationError("Unknown IANA timezone (e.g. Asia/Kolkata).")
        return value

    def validate_visitor_policies(self, value):  # noqa: C901 - one branch per policy key
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError("visitor_policies must be an object.")
        offsets = value.get("reminder_offsets_hours")
        if offsets is not None:
            if not isinstance(offsets, list) or not all(
                isinstance(h, int) and 0 < h <= 24 * 14 for h in offsets
            ):
                raise serializers.ValidationError(
                    "reminder_offsets_hours must be a list of whole hours (1-336)."
                )
        slot = value.get("slot_duration_minutes")
        if slot is not None and (not isinstance(slot, int) or not 5 <= slot <= 480):
            raise serializers.ValidationError("slot_duration_minutes must be 5-480.")
        notices = value.get("public_notices")
        if notices is not None:
            value["public_notices"] = clean_public_notices(notices)
        catalogue = value.get("visitor_catalogue")
        if catalogue is not None:
            if catalogue == {} or catalogue == []:
                # Empty = "back to the defaults".
                value = {k: v for k, v in value.items() if k != "visitor_catalogue"}
            else:
                try:
                    value["visitor_catalogue"] = validate_catalogue(catalogue)
                except ValueError as exc:
                    raise serializers.ValidationError({"visitor_catalogue": str(exc)})
        return value

    def validate_security_policies(self, value):
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError("security_policies must be an object.")
        return value

    def validate(self, attrs):
        start = attrs.get("working_hours_start", getattr(self.instance, "working_hours_start", None))
        end = attrs.get("working_hours_end", getattr(self.instance, "working_hours_end", None))
        if start and end and end <= start:
            raise serializers.ValidationError(
                {"working_hours_end": "Working hours must end after they start."}
            )
        return attrs


# ------------------------------------------------------------------ buildings


class FloorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Floor
        fields = ["id", "name", "level"]


class BuildingWriteSerializer(serializers.ModelSerializer):
    """``floors`` is the count; ``floor_list`` the rows kept in sync with it
    by the viewset (so rooms can be placed on a floor)."""

    floor_list = FloorSerializer(source="floor_set", many=True, read_only=True)
    room_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Building
        fields = [
            "id", "name", "address", "floors", "entry_gates", "exit_gates",
            "has_reception_desk", "floor_list", "room_count", "created_at",
        ]
        read_only_fields = ["id", "created_at", "floor_list", "room_count"]

    def validate_name(self, value):
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("Building name is required.")
        return value

    def validate_floors(self, value):
        if value < 1 or value > 500:
            raise serializers.ValidationError("Floors must be between 1 and 500.")
        return value


# ---------------------------------------------------------------- departments


class DepartmentWriteSerializer(serializers.ModelSerializer):
    member_count = serializers.IntegerField(read_only=True, required=False)

    class Meta:
        model = Department
        fields = ["id", "name", "code", "member_count"]
        read_only_fields = ["id", "member_count"]

    def validate_name(self, value):
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("Department name is required.")
        return value

    def validate_code(self, value):
        return (value or "").strip().upper()

    def validate(self, attrs):
        org = self.context.get("organization")
        name = attrs.get("name")
        if org is not None and name:
            qs = Department.objects.filter(organization=org, name__iexact=name)
            if self.instance is not None:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError({"name": "A department with this name already exists."})
        code = attrs.get("code")
        if org is not None and code:
            qs = Department.objects.filter(organization=org, code__iexact=code)
            if self.instance is not None:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError({"code": "Another department already uses this code."})
        return attrs


# ----------------------------------------------------------------------- team


class EmployeeProfileSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(source="department.name", read_only=True, default="")
    building_name = serializers.CharField(source="building.name", read_only=True, default="")

    class Meta:
        model = Employee
        fields = [
            "id", "employee_id", "designation", "office_location", "joining_date",
            "status", "department", "department_name", "building", "building_name",
        ]


class TeamMemberSerializer(serializers.ModelSerializer):
    """A workspace member: account + (optional) employee profile."""

    employee = EmployeeProfileSerializer(source="employee_profile", read_only=True)
    is_locked = serializers.BooleanField(read_only=True)
    last_login = serializers.DateTimeField(read_only=True)

    class Meta:
        model = User
        fields = [
            "id", "email", "full_name", "phone", "role", "is_active", "is_locked",
            "last_login", "created_at", "employee",
        ]
        read_only_fields = fields


def _validate_new_password(password, user=None):
    try:
        validate_password(password, user=user)
    except DjangoValidationError as exc:
        raise serializers.ValidationError(list(exc.messages))
    return password


class TeamMemberCreateSerializer(serializers.Serializer):
    """Admin creates a colleague's account inside the current workspace.

    The admin sets an initial password and shares it out-of-band; the new
    member can change it from their own profile.  No e-mail invitation flow
    exists in this project (see ``accounts.models.User`` for why), so this is
    the single supported way to add staff.
    """

    email = serializers.EmailField()
    full_name = serializers.CharField(max_length=120)
    phone = serializers.CharField(max_length=20, required=False, allow_blank=True)
    role = serializers.ChoiceField(choices=Role.choices)
    password = serializers.CharField(write_only=True, min_length=8, max_length=128)
    designation = serializers.CharField(max_length=150, required=False, allow_blank=True)
    employee_id = serializers.CharField(max_length=50, required=False, allow_blank=True)
    department = serializers.IntegerField(required=False, allow_null=True)
    building = serializers.IntegerField(required=False, allow_null=True)

    def validate_email(self, value):
        value = User.objects.normalize_email((value or "").strip())
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("An account with this e-mail already exists.")
        return value

    def validate_full_name(self, value):
        value = (value or "").strip()
        if len(value) < 2:
            raise serializers.ValidationError("Full name is required.")
        return value

    def validate_password(self, value):
        return _validate_new_password(value)

    def validate_employee_id(self, value):
        value = (value or "").strip()
        if value and Employee.objects.filter(employee_id=value).exists():
            raise serializers.ValidationError("This employee ID is already in use.")
        return value

    def validate(self, attrs):
        org = self.context["organization"]
        dept = attrs.get("department")
        if dept is not None and not Department.objects.filter(pk=dept, organization=org).exists():
            raise serializers.ValidationError({"department": "Unknown department."})
        bld = attrs.get("building")
        if bld is not None and not Building.objects.filter(pk=bld, organization=org).exists():
            raise serializers.ValidationError({"building": "Unknown building."})
        return attrs


class TeamMemberUpdateSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=120, required=False)
    phone = serializers.CharField(max_length=20, required=False, allow_blank=True)
    role = serializers.ChoiceField(choices=Role.choices, required=False)
    is_active = serializers.BooleanField(required=False)
    designation = serializers.CharField(max_length=150, required=False, allow_blank=True)
    employee_id = serializers.CharField(max_length=50, required=False, allow_blank=True)
    office_location = serializers.CharField(max_length=150, required=False, allow_blank=True)
    department = serializers.IntegerField(required=False, allow_null=True)
    building = serializers.IntegerField(required=False, allow_null=True)
    status = serializers.ChoiceField(choices=Employee.Status.choices, required=False)
    password = serializers.CharField(write_only=True, min_length=8, max_length=128, required=False)

    def validate_full_name(self, value):
        value = (value or "").strip()
        if len(value) < 2:
            raise serializers.ValidationError("Full name is required.")
        return value

    def validate_password(self, value):
        return _validate_new_password(value)

    def validate(self, attrs):
        org = self.context["organization"]
        target = self.context["target"]
        dept = attrs.get("department")
        if dept is not None and not Department.objects.filter(pk=dept, organization=org).exists():
            raise serializers.ValidationError({"department": "Unknown department."})
        bld = attrs.get("building")
        if bld is not None and not Building.objects.filter(pk=bld, organization=org).exists():
            raise serializers.ValidationError({"building": "Unknown building."})
        eid = (attrs.get("employee_id") or "").strip()
        if eid:
            qs = Employee.objects.filter(employee_id=eid).exclude(user=target)
            if qs.exists():
                raise serializers.ValidationError({"employee_id": "This employee ID is already in use."})
        return attrs


# -------------------------------------------------------------------- account


class ProfileUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["full_name", "phone"]

    def validate_full_name(self, value):
        value = (value or "").strip()
        if len(value) < 2:
            raise serializers.ValidationError("Full name is required.")
        return value


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=8, max_length=128)

    def validate_current_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value

    def validate_new_password(self, value):
        return _validate_new_password(value, user=self.context["request"].user)

    def validate(self, attrs):
        if attrs["current_password"] == attrs["new_password"]:
            raise serializers.ValidationError(
                {"new_password": "New password must differ from the current one."}
            )
        return attrs


# ---------------------------------------------------------------------- audit


class AuditActorSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "full_name", "email", "role"]


class AuditLogSerializer(serializers.ModelSerializer):
    actor = AuditActorSerializer(source="user", read_only=True)

    class Meta:
        model = AuditLog
        fields = [
            "id", "action", "entity_type", "entity_id", "details", "ip_address",
            "created_at", "actor",
        ]
        read_only_fields = fields


# ------------------------------------------------------------------ blacklist


class BlacklistVisitorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Visitor
        fields = ["id", "full_name", "phone", "email", "company", "photo"]


class BlacklistEntrySerializer(serializers.ModelSerializer):
    visitor = BlacklistVisitorSerializer(read_only=True)
    reason_label = serializers.CharField(source="get_reason_display", read_only=True)
    added_by_name = serializers.CharField(source="added_by.full_name", read_only=True, default="")

    class Meta:
        model = Blacklist
        fields = [
            "id", "visitor", "reason", "reason_label", "comment", "added_by_name",
            "is_active", "created_at",
        ]
        read_only_fields = fields


class BlacklistCreateSerializer(serializers.Serializer):
    reason = serializers.ChoiceField(choices=BlacklistReason.choices)
    comment = serializers.CharField(required=False, allow_blank=True, max_length=1000)


# ---------------------------------------------------------------------- scan


class ScanSerializer(serializers.Serializer):
    """Payload for ``POST /api/visits/scan/``.

    Accepts either the raw QR string (``token|signature``) in ``payload`` or
    the two parts separately.  ``dry_run`` verifies without redeeming the
    pass, so a gate screen can show who is about to enter before confirming.
    """

    payload = serializers.CharField(required=False, allow_blank=True, max_length=400)
    token = serializers.CharField(required=False, allow_blank=True, max_length=64)
    signature = serializers.CharField(required=False, allow_blank=True, max_length=128)
    dry_run = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        token = (attrs.get("token") or "").strip()
        signature = (attrs.get("signature") or "").strip()
        payload = (attrs.get("payload") or "").strip()
        if payload and not (token and signature):
            token, _, signature = payload.partition("|")
            token, signature = token.strip(), signature.strip()
        if not token or not signature:
            raise serializers.ValidationError(
                {"payload": "Scan an AdmitOne QR pass (token|signature)."}
            )
        attrs["token"] = token
        attrs["signature"] = signature
        return attrs


class VisitCancelSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, max_length=120)


# --------------------------------------------------------------------- rooms


class RoomSerializer(serializers.ModelSerializer):
    """A room inside one of the workspace's buildings (``/api/rooms/``)."""

    building_name = serializers.CharField(source="building.name", read_only=True)
    floor_name = serializers.CharField(source="floor.name", read_only=True, default="")
    room_type_label = serializers.CharField(source="get_room_type_display", read_only=True)
    label = serializers.CharField(read_only=True)

    class Meta:
        model = Room
        fields = [
            "id", "building", "building_name", "floor", "floor_name", "number", "name",
            "room_type", "room_type_label", "capacity", "is_active", "label", "created_at",
        ]
        read_only_fields = ["id", "created_at", "label", "building_name", "floor_name", "room_type_label"]
        # The DB constraint is case-sensitive and DRF would report it as a
        # non-field error; ``validate`` below does a friendlier, case-
        # insensitive check attached to ``number``.
        validators = []

    def _org(self):
        return self.context["request"].user.organization_id

    def validate_building(self, value):
        if value.organization_id != self._org():
            raise serializers.ValidationError("Choose a building in your workspace.")
        return value

    def validate_number(self, value):
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("Enter the room number or door code.")
        return value

    def validate(self, attrs):
        building = attrs.get("building", getattr(self.instance, "building", None))
        floor = attrs.get("floor", getattr(self.instance, "floor", None))
        if floor is not None and building is not None and floor.building_id != building.pk:
            raise serializers.ValidationError({"floor": "That floor is not in the chosen building."})
        number = attrs.get("number", getattr(self.instance, "number", None))
        if building is not None and number:
            clash = Room.objects.filter(building=building, number__iexact=number)
            if self.instance is not None:
                clash = clash.exclude(pk=self.instance.pk)
            if clash.exists():
                raise serializers.ValidationError(
                    {"number": f"Room {number} already exists in {building.name}."}
                )
        return attrs


class RoomAttendanceSerializer(serializers.ModelSerializer):
    """One room scan, for the visit drawer and the attendance report."""

    visit_id = serializers.IntegerField(source="visit.pk", read_only=True)
    visit_reference = serializers.CharField(source="visit.visit_id", read_only=True)
    visitor_name = serializers.CharField(source="visit.visitor.full_name", read_only=True)
    visitor_category = serializers.CharField(source="visit.visitor_category", read_only=True)
    purpose = serializers.CharField(source="visit.purpose", read_only=True)
    room_label = serializers.CharField(source="room.label", read_only=True)
    room_number = serializers.CharField(source="room.number", read_only=True)
    building_name = serializers.CharField(source="room.building.name", read_only=True)
    scanned_by_name = serializers.CharField(source="scanned_by.full_name", read_only=True, default="")

    class Meta:
        model = RoomAttendance
        fields = [
            "id", "visit_id", "visit_reference", "visitor_name", "visitor_category", "purpose",
            "room", "room_label", "room_number", "building_name", "scanned_by_name",
            "scanned_at", "note",
        ]
        read_only_fields = fields


class RoomScanSerializer(ScanSerializer):
    """Payload for ``POST /api/visits/room_scan/``: a pass plus the room."""

    room = serializers.IntegerField()
    note = serializers.CharField(required=False, allow_blank=True, max_length=200)


class RoomAssignSerializer(serializers.Serializer):
    """``room`` may be null to clear the assignment."""

    room = serializers.IntegerField(required=False, allow_null=True)
