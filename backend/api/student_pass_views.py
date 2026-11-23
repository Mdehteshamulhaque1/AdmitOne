"""Admin API for 6-month student passes (``/api/student-passes/``).

Admins only (``manage_student_passes``). Guards never use these endpoints: they
scan student passes through the normal gate scanner (``/api/visits/scan/``).
"""

from datetime import date, timedelta

from django.db import transaction
from django.db.models import Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.permissions import IsTenantMember, require_permission
from accounts.utils import client_ip, org_localdate
from visits import student_passes as svc
from visits.models import StudentPass, StudentPassScan
from visits.services import get_or_create_visitor

from .student_pass_serializers import StudentPassCreateSerializer, StudentPassScanSerializer, StudentPassSerializer

EXPIRING_SOON_DAYS = 15


def inside_now(org, today):
    """Students whose last scan today was IN (i.e. still on campus)."""
    last = {}
    for pass_id, direction in (
        StudentPassScan.objects.filter(organization=org, scan_date=today).order_by("scanned_at").values_list("student_pass_id", "direction")
    ):
        last[pass_id] = direction
    return sum(1 for d in last.values() if d == StudentPassScan.Direction.IN)


class StudentPassViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated, IsTenantMember, require_permission("manage_student_passes")]

    def _org(self, request):
        return request.user.organization

    def _queryset(self, request):
        return StudentPass.objects.filter(organization=self._org(request)).select_related("visitor", "organization", "issued_by")

    def _get(self, request, pk):
        sp = self._queryset(request).filter(pk=pk).first()
        if sp is None:
            raise NotFound("Student pass not found.")
        return sp

    def _out(self, request, sp, **extra):
        return {**StudentPassSerializer(sp, context={"request": request}).data, **extra}

    def list(self, request):
        org = self._org(request)
        today = org_localdate(org)
        qs = self._queryset(request)
        q = (request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(admission_number__icontains=q) | Q(visitor__full_name__icontains=q)
                | Q(visitor__phone__icontains=q) | Q(course__icontains=q) | Q(batch__icontains=q)
            )
        counts = {
            "ACTIVE": qs.filter(status=StudentPass.Status.ACTIVE, valid_from__lte=today, valid_until__gte=today).count(),
            "EXPIRING": qs.filter(status=StudentPass.Status.ACTIVE, valid_from__lte=today, valid_until__gte=today,
                                  valid_until__lte=today + timedelta(days=EXPIRING_SOON_DAYS)).count(),
            "EXPIRED": qs.filter(status=StudentPass.Status.ACTIVE, valid_until__lt=today).count(),
            "REVOKED": qs.filter(status=StudentPass.Status.REVOKED).count(),
            "INSIDE": inside_now(org, today),
        }
        state = (request.query_params.get("status") or "").upper()
        if state == "ACTIVE":
            qs = qs.filter(status=StudentPass.Status.ACTIVE, valid_from__lte=today, valid_until__gte=today)
        elif state == "EXPIRING":
            qs = qs.filter(status=StudentPass.Status.ACTIVE, valid_from__lte=today, valid_until__gte=today,
                           valid_until__lte=today + timedelta(days=EXPIRING_SOON_DAYS))
        elif state == "EXPIRED":
            qs = qs.filter(status=StudentPass.Status.ACTIVE, valid_until__lt=today)
        elif state == "REVOKED":
            qs = qs.filter(status=StudentPass.Status.REVOKED)
        data = StudentPassSerializer(qs[:500], many=True, context={"request": request}).data
        return Response({"results": data, "counts": counts, "expiring_soon_days": EXPIRING_SOON_DAYS})

    def create(self, request):
        org = self._org(request)
        ser = StudentPassCreateSerializer(data=request.data, context={"organization": org, "request": request})
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        with transaction.atomic():
            visitor, _ = get_or_create_visitor(org, full_name=d["full_name"], phone=d["phone"])
            if visitor.is_blacklisted:
                return Response({"detail": "This person is on the blacklist. Lift the blacklist before issuing a pass."},
                                status=status.HTTP_400_BAD_REQUEST)
            existing = StudentPass.objects.filter(organization=org, visitor=visitor, status=StudentPass.Status.ACTIVE,
                                                  valid_until__gte=org_localdate(org)).first()
            if existing:
                return Response({"detail": f"This student already has an active pass (admission {existing.admission_number}). Renew it instead."},
                                status=status.HTTP_400_BAD_REQUEST)
            # The admission record is the student's identity from now on.
            visitor.full_name = d["full_name"]
            if d.get("email"):
                visitor.email = d["email"]
            visitor.category = "STUDENT"
            visitor.document_type = d["document_type"]
            visitor.document_number = d["document_number"]
            visitor.photo = d["photo"]
            visitor.save()
            sp = svc.issue_pass(
                org, visitor=visitor, admission_number=d["admission_number"], course=d["course"], batch=d["batch"],
                valid_from=d.get("valid_from"), issued_by=request.user, ip=client_ip(request),
            )
        emailed = svc.email_pass(sp)
        return Response(self._out(request, sp, emailed=bool(emailed.sent)), status=status.HTTP_201_CREATED)

    def retrieve(self, request, pk=None):
        sp = self._get(request, pk)
        scans = StudentPassScanSerializer(sp.scans.all()[:30], many=True).data
        return Response(self._out(request, sp, recent_scans=scans))

    @action(detail=True, methods=["post"])
    def renew(self, request, pk=None):
        sp = svc.renew_pass(self._get(request, pk), user=request.user, ip=client_ip(request))
        return Response(self._out(request, sp, detail=f"Renewed until {sp.valid_until:%d %b %Y}."))

    @action(detail=True, methods=["post"])
    def revoke(self, request, pk=None):
        sp = self._get(request, pk)
        if sp.status == StudentPass.Status.REVOKED:
            return Response({"detail": "This pass is already revoked."}, status=status.HTTP_400_BAD_REQUEST)
        sp = svc.revoke_pass(sp, user=request.user, reason=request.data.get("reason", ""), ip=client_ip(request))
        return Response(self._out(request, sp, detail="Pass revoked. It no longer opens the gate."))

    @action(detail=True, methods=["post"], url_path="send-email")
    def send_email(self, request, pk=None):
        sp = self._get(request, pk)
        result = svc.email_pass(sp)
        if result.skipped:
            return Response({"detail": "This student has no email address on file."}, status=status.HTTP_400_BAD_REQUEST)
        if not result.sent:
            return Response({"detail": "The email couldn't be sent. Check the email settings and try again."},
                            status=status.HTTP_502_BAD_GATEWAY)
        return Response({"detail": f"Pass emailed to {sp.visitor.email}."})

    @action(detail=False, methods=["get"])
    def attendance(self, request):
        """Every IN/OUT scan on one day (default today), newest first."""
        org = self._org(request)
        raw = (request.query_params.get("date") or "").strip()
        try:
            day = date.fromisoformat(raw) if raw else org_localdate(org)
        except ValueError:
            return Response({"detail": "Invalid date. Use YYYY-MM-DD."}, status=status.HTTP_400_BAD_REQUEST)
        scans = (
            StudentPassScan.objects.filter(organization=org, scan_date=day)
            .select_related("student_pass__visitor", "scanned_by")
            .order_by("-scanned_at")[:1000]
        )
        return Response({"date": day.isoformat(), "scans": StudentPassScanSerializer(scans, many=True).data})


def scan_student_pass_response(request, raw, dry_run=False):
    """Gate scan of a student pass (called from ``/api/visits/scan/``).

    Same response shape as a visitor scan (``ok``, ``detail``) plus
    ``kind="student"``, ``direction`` and ``student_pass`` so the gate screen
    can show the student's photo and course.
    """
    from organizations.models import AuditLog

    org = request.user.organization
    ok, msg, sp = svc.verify(org, raw)
    data = StudentPassSerializer(sp, context={"request": request}).data if sp is not None else None
    if not ok:
        AuditLog.log(request.user, "Student pass scan rejected", "StudentPass", sp.pk if sp else "", msg,
                     ip_address=client_ip(request), organization_id=org.pk)
        return Response({"ok": False, "kind": "student", "detail": msg, "visit": None, "student_pass": data},
                        status=status.HTTP_400_BAD_REQUEST)
    ok, msg, direction, _ = svc.scan(org, sp, user=request.user, dry_run=dry_run, ip=client_ip(request))
    data = StudentPassSerializer(sp, context={"request": request}).data
    return Response(
        {"ok": ok, "kind": "student", "detail": msg, "direction": direction, "visit": None, "student_pass": data},
        status=status.HTTP_200_OK if ok else status.HTTP_400_BAD_REQUEST,
    )
