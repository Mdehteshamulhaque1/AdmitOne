from datetime import date

from django.contrib.auth import authenticate, get_user_model
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.db.models import Count, Exists, Max, OuterRef, Q, Subquery
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import AuthenticationFailed, NotFound
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from accounts.models import Role, User
from accounts.permissions import (
    CanApproveVisit,
    CanBlacklist,
    CanCancelVisit,
    CanCheckIn,
    CanCheckOut,
    CanLiftBlacklist,
    CanRegisterVisitor,
    CanScanQR,
    require_permission,
    tenant_user_queryset,
    user_permissions,
)
from accounts.utils import client_ip, org_localdate
from organizations.models import AuditLog, Building, Department, Employee, Organization
from visits.availability import (
    get_host_availability,
    organization_slot_duration,
    resolve_booking_host,
)
from visits.models import Blacklist, QRPass, Visit, VisitStatus, VisitType, Visitor
from visits.services import (
    approve_visit,
    blacklist_visitor,
    cancel_visit_by_staff,
    check_in,
    check_out,
    create_pre_booking,
    register_visit,
    reject_visit,
    reissue_qr_pass,
    remove_blacklist,
)

from .management_serializers import (
    BlacklistCreateSerializer,
    BlacklistEntrySerializer,
    ScanSerializer,
    VisitCancelSerializer,
)
from .serializers import (
    BookingSubmitSerializer,
    DashboardSummarySerializer,
    DepartmentSerializer,
    OrganizationCreateSerializer,
    OrganizationSerializer,
    PublicBuildingSerializer,
    PublicHostSerializer,
    RegisterSerializer,
    UserSerializer,
    VisitSerializer,
    VisitorSerializer,
)
from .throttles import (
    LoginRateThrottle,
    PublicBookingRateThrottle,
    RegisterRateThrottle,
)


class HealthCheckView(APIView):
    """Public liveness + readiness probe used by Render's health check.

    Returns 200 ``{"status": "ok", "database": "ok"}`` when the database
    answers, and 503 ``{"status": "degraded", ...}`` when it does not, so the
    platform stops routing traffic to an instance that cannot serve requests
    instead of reporting a green check over a dead connection.
    """

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = []

    def get(self, request):
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
        except DatabaseError:
            return Response(
                {"status": "degraded", "database": "error"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response({"status": "ok", "database": "ok"})


class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        refresh = RefreshToken.for_user(user)
        return Response(
            {
                "user": UserSerializer(user).data,
                "refresh": str(refresh),
                "access": str(refresh.access_token),
            },
            status=status.HTTP_201_CREATED,
        )


class VisitorViewSet(viewsets.ReadOnlyModelViewSet):
    """List / retrieve / edit visitors.  Creation is handled via /visits/register/.

    List rows carry ``is_blacklisted_flag`` / ``visit_count`` / ``last_visit_at``
    annotations so the directory renders without a query per row.
    """

    serializer_class = VisitorSerializer

    def get_queryset(self):
        org = self.request.user.organization
        # Tenant key, not a join: a visitor row belongs to exactly one
        # organization, and an orgless user sees no visitor data at all.
        qs = Visitor.objects.filter(organization=org) if org else Visitor.objects.none()
        active_ban = Blacklist.objects.filter(visitor=OuterRef("pk"), is_active=True)
        qs = qs.annotate(
            is_blacklisted_flag=Exists(active_ban),
            blacklist_reason_flag=Subquery(active_ban.order_by("-created_at").values("reason")[:1]),
            visit_count=Count("visits", distinct=True),
            last_visit_at=Max("visits__registered_at"),
        )
        params = self.request.query_params
        q = (params.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(full_name__icontains=q)
                | Q(phone__icontains=q)
                | Q(company__icontains=q)
                | Q(email__icontains=q)
            )
        blacklisted = (params.get("blacklisted") or "").lower()
        if blacklisted in ("1", "true"):
            qs = qs.filter(is_blacklisted_flag=True)
        elif blacklisted in ("0", "false"):
            qs = qs.filter(is_blacklisted_flag=False)
        ordering = (params.get("ordering") or "").strip()
        allowed = {"full_name", "-full_name", "created_at", "-created_at",
                   "visit_count", "-visit_count", "last_visit_at", "-last_visit_at"}
        if ordering in allowed:
            qs = qs.order_by(ordering, "-id")
        else:
            qs = qs.order_by("-created_at")
        return qs

    def partial_update(self, request, pk=None):
        """Edit a visitor's profile (``create_visitor`` capability)."""
        if not CanRegisterVisitor().has_permission(request, self):
            return Response(
                {"detail": "You do not have permission to edit visitors."},
                status=status.HTTP_403_FORBIDDEN,
            )
        visitor = self.get_object()
        serializer = self.get_serializer(visitor, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                serializer.save()
                AuditLog.log(
                    request.user, "Visitor updated", "Visitor", visitor.pk,
                    f"{visitor.full_name} | fields: "
                    + ", ".join(sorted(serializer.validated_data.keys())),
                    ip_address=client_ip(request), organization_id=visitor.organization_id,
                )
        except IntegrityError:
            return Response(
                {"detail": {"phone": ["Another visitor already uses this phone number."]}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(self.get_serializer(self.get_queryset().get(pk=visitor.pk)).data)

    @action(detail=True, methods=["get"])
    def visits(self, request, pk=None):
        """The visitor's visit history inside the caller's workspace."""
        visitor = self.get_object()
        qs = (
            Visit.objects.filter(visitor=visitor, organization=request.user.organization)
            .select_related(
                "visitor", "host", "building", "department", "created_by",
                "checked_in_by", "checked_out_by", "qr_pass",
            )
            .order_by("-visit_date", "-registered_at")[:100]
        )
        return Response(VisitSerializer(qs, many=True, context={"request": request}).data)

    @action(detail=True, methods=["post", "delete"], url_path="blacklist")
    def blacklist(self, request, pk=None):
        """``POST`` bans the visitor (SECURITY/ADMIN); ``DELETE`` lifts the ban (ADMIN)."""
        visitor = self.get_object()
        if request.method.upper() == "POST":
            if not CanBlacklist().has_permission(request, self):
                return Response(
                    {"detail": "You do not have permission to blacklist visitors."},
                    status=status.HTTP_403_FORBIDDEN,
                )
            ser = BlacklistCreateSerializer(data=request.data)
            ser.is_valid(raise_exception=True)
            entry, ok, msg = blacklist_visitor(
                visitor, request.user,
                reason=ser.validated_data["reason"],
                comment=ser.validated_data.get("comment", ""),
                audit_ip=client_ip(request),
            )
            if not ok:
                return Response({"detail": msg}, status=status.HTTP_400_BAD_REQUEST)
            return Response(
                {"detail": msg, "entry": BlacklistEntrySerializer(entry).data},
                status=status.HTTP_201_CREATED,
            )
        if not CanLiftBlacklist().has_permission(request, self):
            return Response(
                {"detail": "Only a workspace admin can lift a blacklist entry."},
                status=status.HTTP_403_FORBIDDEN,
            )
        ok, msg = remove_blacklist(visitor, request.user, audit_ip=client_ip(request))
        if not ok:
            return Response({"detail": msg}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"detail": msg})


class VisitViewSet(viewsets.ReadOnlyModelViewSet):
    """List / retrieve visits and run approval/check-in/out actions.

    Visits are deliberately **not** creatable through this viewset (finding
    F2).  A generic ``POST /api/visits/`` used to persist a visit straight from
    ``VisitSerializer.create``, which wrote ``organization``/``created_by``
    itself and therefore skipped the ``create_visitor`` permission, the
    10/min ``RegisterRateThrottle``, the ``register_visit`` business rules
    (org/host/building ownership, purpose, time windows) and the ``AuditLog``
    trail.  Creation now lives only in the two domain endpoints, both of which
    go through ``visits.services.register_visit``:

    * ``POST /api/visits/register/`` - pre-registration (PENDING)
    * ``POST /api/visits/walkin/``   - gate walk-in (APPROVED + QR pass)

    ``create()`` is not defined, so the router does not publish a POST route at
    all; ``http_method_not_allowed()`` below answers instead, keeping the
    ``Allow`` header honest while telling the caller where to go.
    """

    serializer_class = VisitSerializer

    def get_queryset(self):
        org = self.request.user.organization
        qs = Visit.objects.filter(organization=org) if org else Visit.objects.none()
        params = self.request.query_params

        # ?status=APPROVED or ?status=PENDING,APPROVED
        raw_status = (params.get("status") or "").strip()
        if raw_status:
            wanted = [s for s in raw_status.upper().split(",") if s in VisitStatus.values]
            if wanted:
                qs = qs.filter(status__in=wanted)
            else:
                qs = qs.none()

        q = (params.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(visitor__full_name__icontains=q)
                | Q(visitor__phone__icontains=q)
                | Q(visitor__company__icontains=q)
                | Q(purpose__icontains=q)
                | Q(host__full_name__icontains=q)
            )

        # ?date=today | YYYY-MM-DD ; ?date_from= ; ?date_to= (organisation-local)
        raw_date = (params.get("date") or "").strip().lower()
        if raw_date == "today":
            qs = qs.filter(visit_date=org_localdate(self.request.user))
        elif raw_date:
            try:
                qs = qs.filter(visit_date=date.fromisoformat(raw_date))
            except ValueError:
                qs = qs.none()
        for key, lookup in (("date_from", "visit_date__gte"), ("date_to", "visit_date__lte")):
            raw = (params.get(key) or "").strip()
            if raw:
                try:
                    qs = qs.filter(**{lookup: date.fromisoformat(raw)})
                except ValueError:
                    qs = qs.none()

        for key in ("visitor", "host", "building"):
            raw = (params.get(key) or "").strip()
            if raw.isdigit():
                qs = qs.filter(**{f"{key}_id": int(raw)})

        if (params.get("inside") or "").lower() in ("1", "true"):
            qs = qs.filter(status=VisitStatus.CHECKED_IN)
        if (params.get("upcoming") or "").lower() in ("1", "true"):
            qs = qs.filter(
                visit_date__gte=org_localdate(self.request.user),
                status__in=[VisitStatus.PENDING, VisitStatus.APPROVED],
            )

        ordering = (params.get("ordering") or "").strip()
        allowed = {
            "registered_at", "-registered_at", "visit_date", "-visit_date",
            "expected_arrival", "-expected_arrival", "checked_in_at", "-checked_in_at",
        }
        if ordering in allowed:
            qs = qs.order_by(ordering, "-id")
        else:
            qs = qs.order_by("-registered_at")
        return qs.select_related(
            "visitor", "host", "building", "department", "created_by",
            "checked_in_by", "checked_out_by", "qr_pass",
        )

    @action(detail=False, methods=["post"], permission_classes=[CanScanQR])
    def scan(self, request):
        """Verify a scanned QR pass and (unless ``dry_run``) check the visitor in.

        The pass must belong to the officer's own workspace: ``QRPass.verify``
        resolves tokens globally, so the tenant check here is what stops a
        pass minted by one organisation from opening another's gate.  A foreign
        or unknown pass is reported identically ("Unknown pass") so the
        endpoint cannot be used to probe for other tenants' tokens.
        """
        ser = ScanSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        token = ser.validated_data["token"]
        signature = ser.validated_data["signature"]
        dry_run = ser.validated_data.get("dry_run", False)

        ok, msg, qr = QRPass.verify(token, signature)
        visit = None
        if ok and qr is not None:
            if qr.visit.organization_id != request.user.organization_id:
                ok, msg, qr = False, "Unknown pass - not registered in system", None
            else:
                visit = qr.visit
        if not ok:
            # Surface the visit (if it is ours) so the gate screen can explain
            # *why* -- an expired pass still names a real visitor. Never for a
            # pass that belongs to another tenant.
            known = (
                QRPass.objects.select_related("visit")
                .filter(token=token, visit__organization_id=request.user.organization_id)
                .first()
                if _looks_like_uuid(token)
                else None
            )
            payload = {"ok": False, "detail": msg, "visit": None}
            if known is not None and known.visit is not None:
                payload["visit"] = self.get_serializer(
                    self.get_queryset().filter(pk=known.visit_id).first() or known.visit
                ).data
            AuditLog.log(
                request.user, "QR scan rejected", "QRPass", token[:64], msg,
                ip_address=client_ip(request),
            )
            return Response(payload, status=status.HTTP_400_BAD_REQUEST)

        if dry_run:
            return Response(
                {"ok": True, "detail": msg, "dry_run": True,
                 "visit": self.get_serializer(self.get_queryset().get(pk=visit.pk)).data}
            )

        done, message = check_in(visit, request.user, via_qr=True)
        fresh = self.get_queryset().filter(pk=visit.pk).first() or visit
        if not done:
            return Response(
                {"ok": False, "detail": message, "visit": self.get_serializer(fresh).data},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({"ok": True, "detail": message, "visit": self.get_serializer(fresh).data})

    @action(detail=True, methods=["post"], permission_classes=[CanCancelVisit])
    def cancel(self, request, pk=None):
        visit = self.get_object()
        ser = VisitCancelSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        ok, msg = cancel_visit_by_staff(
            visit, request.user,
            reason=ser.validated_data.get("reason", ""),
            audit_ip=client_ip(request),
        )
        return self._respond(ok, msg, visit)

    def http_method_not_allowed(self, request, *args, **kwargs):
        if request.method.upper() == "POST":
            return Response(
                {
                    "detail": (
                        "POST /api/visits/ is not supported. Visits are created by "
                        "POST /api/visits/register/ (pre-registration) or "
                        "POST /api/visits/walkin/ (gate walk-in); both apply the "
                        "create_visitor permission, rate limiting and auditing."
                    )
                },
                status=status.HTTP_405_METHOD_NOT_ALLOWED,
            )
        return super().http_method_not_allowed(request, *args, **kwargs)

    @action(detail=True, methods=["post"], permission_classes=[CanApproveVisit])
    def approve(self, request, pk=None):
        visit = self.get_object()
        ok, msg = approve_visit(visit, request.user)
        return self._respond(ok, msg, visit)

    @action(detail=True, methods=["post"], permission_classes=[CanApproveVisit])
    def reject(self, request, pk=None):
        visit = self.get_object()
        reason = request.data.get("reason", "Declined")
        ok, msg = reject_visit(visit, request.user, reason)
        return self._respond(ok, msg, visit)

    @action(detail=True, methods=["post"], permission_classes=[CanCheckIn])
    def checkin(self, request, pk=None):
        visit = self.get_object()
        ok, msg = check_in(visit, request.user)
        return self._respond(ok, msg, visit)

    @action(detail=True, methods=["post"], permission_classes=[CanCheckOut])
    def checkout(self, request, pk=None):
        visit = self.get_object()
        ok, msg = check_out(visit, request.user)
        return self._respond(ok, msg, visit)

    @action(detail=True, methods=["post"], permission_classes=[CanApproveVisit])
    def reissue(self, request, pk=None):
        """Regenerate the signed QR pass for an approved visit whose pass
        has expired or already been used."""
        visit = self.get_object()
        ok, msg = reissue_qr_pass(visit, request.user)
        return self._respond(ok, msg, visit)

    def _respond(self, ok, msg, visit):
        if not ok:
            return Response({"detail": msg}, status=status.HTTP_400_BAD_REQUEST)
        # The service layer mutates a freshly locked row, not the instance the
        # view holds, so re-read it: the SPA renders the returned visit
        # directly (new status, issued pass) without a second round-trip.
        fresh = self.get_queryset().filter(pk=visit.pk).first() or visit
        return Response({"detail": msg, "visit": self.get_serializer(fresh).data})


def _looks_like_uuid(value):
    import uuid

    try:
        uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return False
    return True


# The subset of the console's KPI dict that crosses the API boundary. The
# console also computes repeat, first_time and total, which the SPA does not
# use.
#
# Naming the keys once, here, is the fix for the drift that made this view
# rename a key by hand: it used to copy all ten fields field-by-field and
# translate ``avg_duration`` into ``avg_duration_minutes`` in the process, so
# the service and the API could disagree and nothing would notice. Now a rename
# on either side shows up immediately as a KeyError.
DASHBOARD_SUMMARY_KEYS = (
    "today",
    "week",
    "month",
    "inside",
    "pending",
    "approved",
    "avg_duration_minutes",
    "checked_out",
    "rejected",
    "trend",
)


class DashboardSummaryView(APIView):
    """KPI summary plus chart-ready series (``analytics``) for the SPA.

    The KPI keys are the contract listed in ``DASHBOARD_SUMMARY_KEYS``;
    ``analytics`` is computed by ``reports.services.dashboard_analytics`` with
    database-side aggregates. Guarded by the same ``view_reports`` capability
    as the CSV export, so dashboard and report authorization cannot drift.
    """

    permission_classes = [IsAuthenticated, require_permission("view_reports")]

    def get(self, request):
        from reports.services import build_dashboard_data, dashboard_analytics

        kpis, _ = build_dashboard_data(request.user)
        data = DashboardSummarySerializer(
            {key: kpis[key] for key in DASHBOARD_SUMMARY_KEYS}
        ).data
        data["total"] = kpis.get("total", 0)
        data["repeat_visitors"] = kpis.get("repeat", 0)
        data["first_time_visitors"] = kpis.get("first_time", 0)
        data["analytics"] = dashboard_analytics(request.user)
        return Response(data)


class ReportExportView(APIView):
    """JWT-protected CSV export of real report data.

    Reuses the shared report queryset + CSV builder so the file the SPA
    downloads is identical to the console's export.
    """

    permission_classes = [require_permission("view_reports")]

    def get(self, request):
        from reports.services import report_queryset, visit_csv_export

        period = request.query_params.get("period", "daily")
        if period not in {"daily", "weekly", "monthly", "all"}:
            period = "daily"
        dept = (request.query_params.get("dept") or "").strip()
        visits = report_queryset(request.user, period, dept)
        return visit_csv_export(visits, period)


class LockoutTokenObtainSerializer(TokenObtainPairSerializer):
    """JWT login. Attempt counting & the lock itself live in LockoutBackend,
    so every auth path (API + session) shares the same lockout state."""

    def validate(self, attrs):
        request = self.context["request"]
        username_key = get_user_model().USERNAME_FIELD
        identifier = (attrs.get(username_key) or "").strip()
        user = User.objects.filter(email__iexact=identifier).first()

        if user is not None and user.is_locked:
            raise AuthenticationFailed(
                "Account temporarily locked due to too many failed attempts. "
                "Please try again later."
            )

        authenticated = authenticate(
            request=request, username=identifier, password=attrs["password"]
        )
        if authenticated is None:
            raise AuthenticationFailed(
                "Unable to log in with the provided credentials."
            )

        refresh = RefreshToken.for_user(authenticated)
        return {
            "refresh": str(refresh),
            "access": str(refresh.access_token),
        }


class LockoutTokenObtainPairView(TokenObtainPairView):
    serializer_class = LockoutTokenObtainSerializer
    throttle_classes = [LoginRateThrottle]


class LogoutView(APIView):
    """Invalidate a refresh token by blacklisting it.

    Post-logout the bearer access token is still live until it expires;
    SimpleJWT has no way to revoke an access token client-side, so the SPA
    also discards it locally. Refresh rotation is already enforced
    (``ROTATE_REFRESH_TOKENS`` + ``BLACKLIST_AFTER_ROTATION``), which stops
    this endpoint from being used to prolong a session.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        raw = (request.data.get("refresh") or "").strip()
        if not raw:
            return Response(
                {"detail": "A refresh token is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            token = RefreshToken(raw)
            token.blacklist()
        except (TokenError, AttributeError):
            return Response(
                {"detail": "Invalid or already blacklisted refresh token."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            {"detail": "Logged out."}, status=status.HTTP_205_RESET_CONTENT
        )


class CurrentUserView(APIView):
    """Current user, their capabilities, and their organization (read-only).

    ``permissions`` is the caller's own effective permission set, computed by
    :func:`accounts.permissions.user_permissions` -- the same function every
    backend check uses.  It exists so the SPA can decide what to *render*
    without keeping a second, hand-maintained copy of the role matrix.

    It is a **UI hint, not an authorization input**.  Nothing on the server
    reads it, and every endpoint re-derives the caller's permissions from their
    role.  If this list were wrong, tampered with, or simply absent, the result
    would be a page that shows the wrong links -- never access to data.  A
    client that wants to prove anything must make the request and be judged on
    what the server does.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        org = request.user.organization
        return Response(
            {
                "user": UserSerializer(request.user).data,
                "organization": OrganizationSerializer(org).data if org else None,
                "permissions": sorted(user_permissions(request.user)),
            }
        )


class RegisterVisitView(APIView):
    """Atomic visitor + visit creation for the SPA pre-registration flow."""

    permission_classes = [IsAuthenticated, CanRegisterVisitor]
    throttle_classes = [RegisterRateThrottle]

    def post(self, request):
        visitor_ser = VisitorSerializer(data=request.data.get("visitor", {}))
        visitor_ser.is_valid(raise_exception=True)

        visit_data = request.data.get("visit", {})
        visit, ok, msg = register_visit(
            request.user,
            visitor_data=visitor_ser.validated_data,
            purpose=visit_data.get("purpose"),
            host_id=visit_data.get("host") or None,
            building_id=visit_data.get("building") or None,
            expected_arrival=visit_data.get("expected_arrival"),
            expected_exit=visit_data.get("expected_exit"),
            visit_date=visit_data.get("visit_date"),
            notes=visit_data.get("notes"),
            audit_ip=client_ip(request),
        )
        if not ok:
            return Response(msg, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {
                "visitor": VisitorSerializer(visit.visitor, context={"request": request}).data,
                "visit": VisitSerializer(visit, context={"request": request}).data,
                "warnings": getattr(visit, "schedule_warnings", []),
            },
            status=status.HTTP_201_CREATED,
        )


class WalkInRegistrationView(APIView):
    """Register a visitor who has already arrived and issue an instant pass.

    Unlike pre-registration (PENDING), a walk-in is approved immediately by the
    receptionist â€” the visit is created APPROVED with a signed, single-use QR
    pass so the visitor can go straight to the gate.
    """

    permission_classes = [IsAuthenticated, CanRegisterVisitor]
    throttle_classes = [RegisterRateThrottle]

    def post(self, request):
        visitor_ser = VisitorSerializer(data=request.data.get("visitor", {}))
        visitor_ser.is_valid(raise_exception=True)

        visit_data = request.data.get("visit", {})
        visit, ok, msg = register_visit(
            request.user,
            visitor_data=visitor_ser.validated_data,
            purpose=visit_data.get("purpose"),
            host_id=visit_data.get("host") or None,
            building_id=visit_data.get("building") or None,
            expected_arrival=visit_data.get("expected_arrival"),
            expected_exit=visit_data.get("expected_exit"),
            visit_date=visit_data.get("visit_date"),
            notes=visit_data.get("notes"),
            walkin=True,
            audit_ip=client_ip(request),
        )
        if not ok:
            return Response(msg, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {
                "visitor": VisitorSerializer(visit.visitor, context={"request": request}).data,
                "visit": VisitSerializer(visit, context={"request": request}).data,
                "warnings": getattr(visit, "schedule_warnings", []),
            },
            status=status.HTTP_201_CREATED,
        )


class OrganizationCreateView(APIView):
    """Create a workspace and attach the current user as its ADMIN.

    Also creates a default building (so the visit-registration form has
    something to select) and an Employee profile for the creator.
    """

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        # Lock the caller's own row first: two concurrent onboarding requests
        # from the same tenantless account would otherwise both pass the
        # "no workspace yet" check and create two workspaces (audit finding
        # "OrganizationCreateView does not lock the user row").
        user = User.objects.select_for_update().get(pk=request.user.pk)
        if user.organization_id is not None:
            return Response(
                {"detail": "You already belong to a workspace."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = OrganizationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        org = serializer.save()

        user.organization = org
        user.role = Role.ADMIN
        user.save(update_fields=["organization", "role"])

        building_name = (request.data.get("building_name") or "").strip() or "Head Office"
        Building.objects.create(organization=org, name=building_name)

        Employee.objects.get_or_create(
            user=user,
            defaults={
                "organization": org,
                "employee_id": f"EMP-{org.pk:04d}",
                "designation": "Workspace Admin",
            },
        )

        AuditLog.log(
            user, "org_created", "Organization", org.pk,
            f"Created workspace {org.name}", ip_address=client_ip(request),
            organization_id=org.pk,
        )

        return Response(
            {
                "organization": OrganizationSerializer(org).data,
                "user": UserSerializer(user).data,
            },
            status=status.HTTP_201_CREATED,
        )


class HostListView(APIView):
    """Active users in the org that can be chosen as a visit host.

    Scoped with ``tenant_user_queryset`` rather than a bare
    ``filter(organization=request.user.organization)`` (F4): for a user who has
    not onboarded, that filter compiles to ``IS NULL`` and returned the e-mail
    address and phone number of *every* unassigned account in the deployment.
    An org-less caller now gets an empty list.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        # An employee profile that is INACTIVE or ON_LEAVE must not be
        # offered as a host (audit finding "on-leave host availability");
        # accounts without a profile (e.g. the workspace creator before one
        # is added) stay eligible.
        users = (
            tenant_user_queryset(request.user)
            .filter(is_active=True)
            .filter(
                Q(employee_profile__isnull=True)
                | Q(employee_profile__status=Employee.Status.ACTIVE)
            )
            .order_by("full_name")
        )
        return Response(UserSerializer(users, many=True).data)


def build_public_booking_context(org):
    """Read-only option sets for a booking form (shared by the anonymous
    booking endpoint and the signed-in visitor flow)."""
    from visits.purposes import VISIT_TYPE_LABELS, purposes_for

    departments = Department.objects.filter(organization=org)
    buildings = Building.objects.filter(organization=org).prefetch_related("floor_set")
    return {
        "organization": {
            "id": org.pk,
            "name": org.name,
            "slug": org.slug,
            "tagline": org.tagline,
            "address": org.address,
            "city": org.city,
            "country": org.country,
            "timezone": org.timezone,
            "working_hours_start": (
                org.working_hours_start.strftime("%H:%M") if org.working_hours_start else "09:00"
            ),
            "working_hours_end": (
                org.working_hours_end.strftime("%H:%M") if org.working_hours_end else "18:00"
            ),
        },
        "departments": DepartmentSerializer(departments, many=True).data,
        "buildings": PublicBuildingSerializer(buildings, many=True).data,
        "visit_types": [
            {"value": code, "label": label}
            for code, label in VISIT_TYPE_LABELS.items()
            if code in VisitType.values
        ],
        "purposes": {code: purposes_for(code) for code in VisitType.values},
    }


class PublicBookingView(APIView):
    """Anonymous 'Book a Visit' endpoint for a specific organization.

    Only reachable by organization slug â€” never enumerates organizations.

    ``GET``  returns read-only booking context: org info, departments,
    buildings (with floors) and the static visit-type/purpose option sets.
    ``POST`` submits the booking and creates a PENDING, pre-booked visit
    (never auto-approved, never issues a QR at this stage).
    """

    permission_classes = [AllowAny]
    throttle_classes = [PublicBookingRateThrottle]

    def get(self, request, slug):
        org = Organization.objects.filter(slug=slug).first()
        if org is None:
            raise NotFound("Organization not found. Check the booking link you were given.")
        return Response(build_public_booking_context(org))

    def post(self, request, slug):
        org = Organization.objects.filter(slug=slug).first()
        if org is None:
            raise NotFound("Organization not found. Check the booking link you were given.")

        serializer = BookingSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        visit, ok, msg = create_pre_booking(
            org,
            visitor_data=data["visitor"],
            visit_type=data["visit_type"],
            department_id=data.get("department"),
            building_id=data.get("building"),
            floor_id=data.get("floor"),
            host_id=data.get("host"),
            visit_date=data["visit_date"],
            expected_arrival=data["expected_arrival"],
            expected_exit=data["expected_exit"],
            purpose=data["purpose"],
            purpose_other=data.get("purpose_other", ""),
            notes=data.get("notes", ""),
            audit_ip=client_ip(request),
        )
        if not ok:
            return Response(msg, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "message": msg,
                "booking": {
                    "visit_id": visit.visit_id,
                    "status": visit.status,
                    "source": visit.source,
                    "visit_type": visit.visit_type,
                    "visit_date": visit.visit_date.isoformat(),
                    "expected_arrival": visit.expected_arrival.strftime("%H:%M"),
                    "expected_exit": visit.expected_exit.strftime("%H:%M"),
                    "visitor": {
                        "id": visit.visitor.pk,
                        "full_name": visit.visitor.full_name,
                        "phone": visit.visitor.phone,
                    },
                    "organization": {"id": org.pk, "name": org.name, "slug": org.slug},
                },
            },
            status=status.HTTP_201_CREATED,
        )


class PublicBookingHostsView(APIView):
    """Active hosts for the public booking flow.

    Optionally filtered by ``?department=<id>``. Only ACTIVE employees with
    active accounts are returned, so a PENDING appointment never points at a
    departed/inactive staff member.
    """

    permission_classes = [AllowAny]
    throttle_classes = [PublicBookingRateThrottle]

    def get(self, request, slug):
        org = Organization.objects.filter(slug=slug).first()
        if org is None:
            raise NotFound("Organization not found. Check the booking link you were given.")

        employees = Employee.objects.filter(
            organization=org,
            status=Employee.Status.ACTIVE,
            user__is_active=True,
        ).select_related("user", "department")

        department_id = (request.query_params.get("department") or "").strip()
        if department_id:
            try:
                employees = employees.filter(department_id=int(department_id))
            except ValueError:
                employees = employees.none()

        hosts = [
            {
                "id": e.user_id,
                "name": e.user.full_name,
                "designation": e.designation,
                "department": e.department_id,
            }
            for e in employees.order_by("user__full_name")
        ]
        return Response(PublicHostSerializer(hosts, many=True).data)


class PublicBookingAvailabilityView(APIView):
    """Available appointment slots for one host on one date (public flow).

    Scoped by the organization slug and throttled like the other public
    booking endpoints. Only returns slots that are inside the org's working
    windows and do not overlap an existing active visit of that host.
    """

    permission_classes = [AllowAny]
    throttle_classes = [PublicBookingRateThrottle]

    def get(self, request, slug):
        org = Organization.objects.filter(slug=slug).first()
        if org is None:
            raise NotFound("Organization not found. Check the booking link you were given.")

        raw_host = (request.query_params.get("host") or "").strip()
        raw_date = (request.query_params.get("date") or "").strip()
        raw_department = (request.query_params.get("department") or "").strip()
        if not raw_host or not raw_date:
            return Response(
                {"detail": "host and date query parameters are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            host_id = int(raw_host)
        except ValueError:
            return Response(
                {"detail": "host must be a valid host id."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            day = date.fromisoformat(raw_date)
        except ValueError:
            return Response(
                {"detail": "Invalid date. Use YYYY-MM-DD."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if day < org_localdate(org):
            return Response(
                {"detail": "Visit date cannot be in the past."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        department_id = None
        if raw_department:
            try:
                department_id = int(raw_department)
            except ValueError:
                return Response(
                    {"detail": "Invalid department."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        host = resolve_booking_host(org, host_id, department_id)
        if host is None:
            return Response(
                {"detail": "This host is not available for booking."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        slots = get_host_availability(org, host, day, department=department_id)
        return Response(
            {
                "date": day.isoformat(),
                "host": {"id": host.pk, "name": host.full_name},
                "slot_duration_minutes": organization_slot_duration(org),
                "slots": slots,
            }
        )
