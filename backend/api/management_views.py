"""Workspace-management endpoints for the SPA (settings, team, audit, blacklist).

Every view here is tenant-scoped through ``request.user.organization`` and
guarded by ``IsTenantMember`` so a tenantless account (fresh signup, deleted
workspace) can never reach another workspace's rows.  Mutations write an
``AuditLog`` row inside the same transaction as the change.
"""

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import Role
from accounts.permissions import IsTenantMember, require_permission
from accounts.utils import client_ip
from organizations.models import AuditLog, Building, Department, Employee, Floor
from reports.services import audit_csv_export
from visits.models import Blacklist, Room, RoomAttendance

from .management_serializers import (
    AuditLogSerializer,
    BlacklistEntrySerializer,
    BuildingWriteSerializer,
    ChangePasswordSerializer,
    DepartmentWriteSerializer,
    OrganizationDetailSerializer,
    ProfileUpdateSerializer,
    RoomAttendanceSerializer,
    RoomSerializer,
    TeamMemberCreateSerializer,
    TeamMemberSerializer,
    TeamMemberUpdateSerializer,
)
from .serializers import UserSerializer

User = get_user_model()


def _parse_date(raw):
    from datetime import date

    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


# --------------------------------------------------------------- organization


class OrganizationMeView(APIView):
    """``GET`` the caller's workspace profile; ``PATCH`` it (ADMIN only)."""

    permission_classes = [IsAuthenticated, IsTenantMember]

    def get(self, request):
        return Response(OrganizationDetailSerializer(request.user.organization).data)

    def patch(self, request):
        if not require_permission("manage_org")().has_permission(request, self):
            raise PermissionDenied("Only workspace admins can change settings.")
        org = request.user.organization
        serializer = OrganizationDetailSerializer(org, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            serializer.save()
            changed = ", ".join(sorted(serializer.validated_data.keys())) or "nothing"
            AuditLog.log(
                request.user, "Organization updated", "Organization", org.pk,
                f"Updated: {changed}", ip_address=client_ip(request),
                organization_id=org.pk,
            )
        return Response(OrganizationDetailSerializer(org).data)


# ------------------------------------------------------------------ buildings


class _TenantModelViewSet(viewsets.ModelViewSet):
    """Shared plumbing: org-scoped queryset, write permission, audit rows."""

    write_permission = ""
    entity_label = ""
    permission_classes = [IsAuthenticated, IsTenantMember]

    def get_permissions(self):
        perms = [IsAuthenticated(), IsTenantMember()]
        if self.action not in ("list", "retrieve"):
            perms.append(require_permission(self.write_permission)())
        return perms

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["organization"] = self.request.user.organization
        return ctx

    def perform_create(self, serializer):
        org = self.request.user.organization
        with transaction.atomic():
            obj = serializer.save(organization=org)
            AuditLog.log(
                self.request.user, f"{self.entity_label} created", self.entity_label,
                obj.pk, str(obj.name), ip_address=client_ip(self.request),
                organization_id=org.pk,
            )

    def perform_update(self, serializer):
        org = self.request.user.organization
        with transaction.atomic():
            obj = serializer.save()
            AuditLog.log(
                self.request.user, f"{self.entity_label} updated", self.entity_label,
                obj.pk, str(obj.name), ip_address=client_ip(self.request),
                organization_id=org.pk,
            )

    def perform_destroy(self, instance):
        org = self.request.user.organization
        with transaction.atomic():
            AuditLog.log(
                self.request.user, f"{self.entity_label} deleted", self.entity_label,
                instance.pk, str(instance.name), ip_address=client_ip(self.request),
                organization_id=org.pk,
            )
            instance.delete()


def _floor_name(level):
    if level == 1:
        return "Ground floor"
    n = level - 1
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix} floor"


def sync_floors(building):
    """Keep ``Floor`` rows in step with ``building.floors`` (the count).

    Levels 1..N exist after this call (named Ground, 1st, 2nd... on first
    creation; renamed floors are left alone). Levels above N are removed only
    when no room sits on them, so shrinking a building never orphans a room.
    """
    wanted = max(int(building.floors or 1), 1)
    existing = {f.level: f for f in building.floor_set.all()}
    for level in range(1, wanted + 1):
        if level not in existing:
            Floor.objects.create(building=building, level=level, name=_floor_name(level))
    for level, floor in existing.items():
        if level > wanted and not floor.rooms.exists():
            floor.delete()


class BuildingViewSet(_TenantModelViewSet):
    serializer_class = BuildingWriteSerializer
    write_permission = "manage_buildings"
    entity_label = "Building"
    pagination_class = None

    def get_queryset(self):
        return (
            Building.objects.filter(organization=self.request.user.organization)
            .prefetch_related("floor_set")
            .annotate(room_count=Count("rooms", distinct=True))
            .order_by("name")
        )

    def perform_create(self, serializer):
        super().perform_create(serializer)
        sync_floors(serializer.instance)

    def perform_update(self, serializer):
        super().perform_update(serializer)
        sync_floors(serializer.instance)

    def perform_destroy(self, instance):
        org = self.request.user.organization
        if Building.objects.filter(organization=org).count() <= 1:
            raise PermissionDenied("A workspace needs at least one building.")
        super().perform_destroy(instance)


class RoomViewSet(_TenantModelViewSet):
    """Rooms of the workspace's buildings (``/api/rooms/?building=<id>``).

    Read by anyone in the workspace (the approval dialog and the room
    scanner need the list); written with ``manage_buildings``.
    """

    serializer_class = RoomSerializer
    write_permission = "manage_buildings"
    entity_label = "Room"
    pagination_class = None

    def get_queryset(self):
        qs = (
            Room.objects.filter(building__organization=self.request.user.organization)
            .select_related("building", "floor")
            .order_by("building__name", "floor__level", "number")
        )
        building = (self.request.query_params.get("building") or "").strip()
        if building.isdigit():
            qs = qs.filter(building_id=int(building))
        if (self.request.query_params.get("active") or "").lower() in ("1", "true"):
            qs = qs.filter(is_active=True)
        return qs

    def perform_create(self, serializer):
        # Rooms hang off a building, not the organisation directly.
        with transaction.atomic():
            obj = serializer.save()
            AuditLog.log(
                self.request.user, "Room created", "Room", obj.pk, obj.label,
                ip_address=client_ip(self.request),
                organization_id=self.request.user.organization_id,
            )

    def perform_update(self, serializer):
        with transaction.atomic():
            obj = serializer.save()
            AuditLog.log(
                self.request.user, "Room updated", "Room", obj.pk, obj.label,
                ip_address=client_ip(self.request),
                organization_id=self.request.user.organization_id,
            )

    def perform_destroy(self, instance):
        with transaction.atomic():
            AuditLog.log(
                self.request.user, "Room deleted", "Room", instance.pk, instance.label,
                ip_address=client_ip(self.request),
                organization_id=self.request.user.organization_id,
            )
            instance.delete()


class AttendanceListView(ListAPIView):
    """Room attendance register: ``/api/attendance/?date=YYYY-MM-DD&room=<id>``.

    Defaults to today in the workspace's timezone. ``view_reports`` because
    it is a report across visitors, not a single visit's history.
    """

    serializer_class = RoomAttendanceSerializer
    permission_classes = [IsAuthenticated, IsTenantMember, require_permission("view_reports")]

    def get_queryset(self):
        from datetime import date as date_cls

        from accounts.utils import org_localdate

        org = self.request.user.organization
        qs = RoomAttendance.objects.filter(visit__organization=org).select_related(
            "room", "room__building", "scanned_by", "visit", "visit__visitor"
        )
        params = self.request.query_params
        raw = (params.get("date") or "").strip()
        day = None
        if raw:
            try:
                day = date_cls.fromisoformat(raw)
            except ValueError:
                day = None
        if day is None:
            day = org_localdate(org)
        qs = qs.filter(visit__visit_date=day)
        room = (params.get("room") or "").strip()
        if room.isdigit():
            qs = qs.filter(room_id=int(room))
        return qs.order_by("-scanned_at")


class DepartmentViewSet(_TenantModelViewSet):
    serializer_class = DepartmentWriteSerializer
    write_permission = "manage_departments"
    entity_label = "Department"
    pagination_class = None

    def get_queryset(self):
        return (
            Department.objects.filter(organization=self.request.user.organization)
            .annotate(member_count=Count("employees"))
            .order_by("name")
        )


# ----------------------------------------------------------------------- team


def _other_active_admins(org, exclude_user):
    return User.objects.filter(
        organization=org, role=Role.ADMIN, is_active=True
    ).exclude(pk=exclude_user.pk).exists()


class TeamViewSet(viewsets.ViewSet):
    """Members of the caller's workspace (ADMIN only).

    ``destroy`` deactivates rather than deletes: visits, audit rows and
    check-in attributions all point at the account, and the trail must survive
    the departure of the person who created it.
    """

    permission_classes = [IsAuthenticated, IsTenantMember, require_permission("manage_users")]

    def _queryset(self, request):
        return (
            User.objects.filter(organization=request.user.organization)
            .select_related("employee_profile__department", "employee_profile__building")
            .order_by("-is_active", "full_name")
        )

    def list(self, request):
        qs = self._queryset(request)
        q = (request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(full_name__icontains=q)
                | Q(email__icontains=q)
                | Q(employee_profile__employee_id__icontains=q)
                | Q(employee_profile__designation__icontains=q)
            )
        role = (request.query_params.get("role") or "").strip().upper()
        if role in Role.values:
            qs = qs.filter(role=role)
        return Response(TeamMemberSerializer(qs, many=True).data)

    def retrieve(self, request, pk=None):
        member = self._queryset(request).filter(pk=pk).first()
        if member is None:
            raise NotFound("Member not found.")
        return Response(TeamMemberSerializer(member).data)

    def create(self, request):
        org = request.user.organization
        serializer = TeamMemberCreateSerializer(data=request.data, context={"organization": org})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            with transaction.atomic():
                user = User.objects.create_user(
                    email=data["email"],
                    password=data["password"],
                    full_name=data["full_name"],
                    phone=data.get("phone", "") or "",
                    role=data["role"],
                    organization=org,
                )
                employee_id = data.get("employee_id") or f"EMP-{org.pk:04d}-{user.pk}"
                Employee.objects.create(
                    user=user,
                    organization=org,
                    employee_id=employee_id,
                    designation=data.get("designation", "") or "",
                    department_id=data.get("department"),
                    building_id=data.get("building"),
                )
                AuditLog.log(
                    request.user, "Team member added", "User", user.pk,
                    f"{user.email} | {user.role}", ip_address=client_ip(request),
                    organization_id=org.pk,
                )
        except IntegrityError:
            return Response(
                {"detail": "That e-mail or employee ID is already in use."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        member = self._queryset(request).get(pk=user.pk)
        return Response(TeamMemberSerializer(member).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, pk=None):
        org = request.user.organization
        target = self._queryset(request).filter(pk=pk).first()
        if target is None:
            raise NotFound("Member not found.")
        serializer = TeamMemberUpdateSerializer(
            data=request.data, context={"organization": org, "target": target}
        )
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        is_self = target.pk == request.user.pk
        new_role = data.get("role")
        new_active = data.get("is_active")
        if is_self and new_role is not None and new_role != target.role:
            return Response(
                {"detail": "You cannot change your own role."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if is_self and new_active is False:
            return Response(
                {"detail": "You cannot deactivate your own account."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        demoting_admin = target.role == Role.ADMIN and (
            (new_role is not None and new_role != Role.ADMIN) or new_active is False
        )
        if demoting_admin and not _other_active_admins(org, target):
            return Response(
                {"detail": "A workspace must keep at least one active admin."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        changes = []
        with transaction.atomic():
            user_fields = []
            for field in ("full_name", "phone", "role", "is_active"):
                if field in data and getattr(target, field) != data[field]:
                    changes.append(f"{field}: {getattr(target, field)} -> {data[field]}")
                    setattr(target, field, data[field])
                    user_fields.append(field)
            if "password" in data:
                target.set_password(data["password"])
                user_fields.append("password")
                changes.append("password reset")
            if user_fields:
                target.save(update_fields=user_fields)

            employee, _ = Employee.objects.get_or_create(
                user=target,
                defaults={
                    "organization": org,
                    "employee_id": f"EMP-{org.pk:04d}-{target.pk}",
                },
            )
            emp_fields = []
            for field in ("designation", "office_location", "status"):
                if field in data and getattr(employee, field) != data[field]:
                    setattr(employee, field, data[field])
                    emp_fields.append(field)
                    changes.append(f"{field} updated")
            if "employee_id" in data and data["employee_id"]:
                if employee.employee_id != data["employee_id"]:
                    employee.employee_id = data["employee_id"]
                    emp_fields.append("employee_id")
                    changes.append("employee_id updated")
            for field in ("department", "building"):
                if field in data:
                    attr = f"{field}_id"
                    if getattr(employee, attr) != data[field]:
                        setattr(employee, attr, data[field])
                        emp_fields.append(field)
                        changes.append(f"{field} updated")
            if emp_fields:
                employee.save(update_fields=emp_fields)

            if changes:
                AuditLog.log(
                    request.user, "Team member updated", "User", target.pk,
                    f"{target.email} | " + "; ".join(changes),
                    ip_address=client_ip(request), organization_id=org.pk,
                )
        member = self._queryset(request).get(pk=target.pk)
        return Response(TeamMemberSerializer(member).data)

    def destroy(self, request, pk=None):
        org = request.user.organization
        target = self._queryset(request).filter(pk=pk).first()
        if target is None:
            raise NotFound("Member not found.")
        if target.pk == request.user.pk:
            return Response(
                {"detail": "You cannot deactivate your own account."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if target.role == Role.ADMIN and target.is_active and not _other_active_admins(org, target):
            return Response(
                {"detail": "A workspace must keep at least one active admin."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        with transaction.atomic():
            target.is_active = False
            target.save(update_fields=["is_active"])
            Employee.objects.filter(user=target).update(status=Employee.Status.INACTIVE)
            AuditLog.log(
                request.user, "Team member deactivated", "User", target.pk,
                target.email, ip_address=client_ip(request), organization_id=org.pk,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)


# -------------------------------------------------------------------- account


class ProfileView(APIView):
    """``PATCH /api/auth/me/profile/`` - the caller edits their own name/phone."""

    permission_classes = [IsAuthenticated]

    def patch(self, request):
        serializer = ProfileUpdateSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(UserSerializer(request.user).data)


class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = request.user
        with transaction.atomic():
            user.set_password(serializer.validated_data["new_password"])
            user.save(update_fields=["password"])
            AuditLog.log(
                user, "Password changed", "User", user.pk, "Self-service password change",
                ip_address=client_ip(request),
            )
        return Response({"detail": "Password updated. Sign in again on other devices."})


# ---------------------------------------------------------------------- audit


class AuditLogListView(ListAPIView):
    """Paginated, filterable audit trail for the caller's workspace.

    ``?export=csv`` streams the filtered set as CSV instead of paginating.
    """

    serializer_class = AuditLogSerializer
    permission_classes = [IsAuthenticated, IsTenantMember, require_permission("view_audit_logs")]

    def get_queryset(self):
        qs = (
            AuditLog.objects.select_related("user")
            .filter(organization=self.request.user.organization)
            # ``-id`` breaks ties between rows written in the same second so
            # pagination is stable and "latest first" is actually latest.
            .order_by("-created_at", "-id")
        )
        params = self.request.query_params
        q = (params.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(action__icontains=q)
                | Q(details__icontains=q)
                | Q(entity_id__icontains=q)
                | Q(user__full_name__icontains=q)
                | Q(user__email__icontains=q)
            )
        action = (params.get("action") or "").strip()
        if action:
            qs = qs.filter(action__iexact=action)
        entity = (params.get("entity_type") or "").strip()
        if entity:
            qs = qs.filter(entity_type__iexact=entity)
        actor = (params.get("actor") or "").strip()
        if actor.isdigit():
            qs = qs.filter(user_id=int(actor))
        date_from = _parse_date(params.get("date_from"))
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)
        date_to = _parse_date(params.get("date_to"))
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)
        return qs

    def list(self, request, *args, **kwargs):
        if (request.query_params.get("export") or "").lower() == "csv":
            return audit_csv_export(self.get_queryset()[:50000], "filtered")
        return super().list(request, *args, **kwargs)


class AuditActionsView(APIView):
    """Distinct action names seen in this workspace (for filter dropdowns)."""

    permission_classes = [IsAuthenticated, IsTenantMember, require_permission("view_audit_logs")]

    def get(self, request):
        actions = (
            AuditLog.objects.filter(organization=request.user.organization)
            .values_list("action", flat=True)
            .distinct()
            .order_by("action")
        )
        return Response(list(actions))


# ------------------------------------------------------------------ blacklist


class BlacklistListView(ListAPIView):
    serializer_class = BlacklistEntrySerializer
    permission_classes = [IsAuthenticated, IsTenantMember]

    def get_queryset(self):
        qs = (
            Blacklist.objects.select_related("visitor", "added_by")
            .filter(visitor__organization=self.request.user.organization)
            .order_by("-created_at")
        )
        include_inactive = (self.request.query_params.get("include_inactive") or "") in ("1", "true")
        if not include_inactive:
            qs = qs.filter(is_active=True)
        q = (self.request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(visitor__full_name__icontains=q)
                | Q(visitor__phone__icontains=q)
                | Q(visitor__company__icontains=q)
                | Q(comment__icontains=q)
            )
        return qs


class ServerTimeView(APIView):
    """Organisation-local 'now', so the SPA agrees with the server on 'today'."""

    permission_classes = [IsAuthenticated, IsTenantMember]

    def get(self, request):
        from accounts.utils import org_localdate, org_timezone

        tz = org_timezone(request.user)
        now = timezone.localtime(timezone.now(), timezone=tz)
        return Response(
            {
                "now": now.isoformat(),
                "today": org_localdate(request.user).isoformat(),
                "timezone": str(tz),
            }
        )
