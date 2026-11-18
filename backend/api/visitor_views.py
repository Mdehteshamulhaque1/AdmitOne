"""Self-service visitor account API (``/api/visitor/``).

Sign up → sign in → pick an organisation → book → manage bookings, all on
visitor-account sessions that are never staff users. Booking and management
go through the shared domain services, so a visitor can only ever reach
visits whose ``Visitor`` record their account owns.
"""

from datetime import date

from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.utils import client_ip, org_localdate
from organizations.models import AuditLog, Organization
from visits.availability import get_host_availability, organization_slot_duration
from visits.arrival import mark_visitor_arriving
from visits.services import cancel_visit, reschedule_visit
from visits.visitor_accounts import (
    account_payload,
    account_visit,
    account_visits,
    authenticate_account,
    book_visit_for_account,
    create_session,
    register_account,
    revoke_session,
    scope_for_visit,
    search_organizations,
)

from .authentication import IsVisitorAccount, VisitorAccountAuthentication
from .throttles import PublicBookingRateThrottle, VisitorAuthThrottle
from .views import build_public_booking_context
from .visitor_serializers import (
    OrganizationSearchSerializer,
    VisitorAccountVisitSerializer,
    VisitorBookingSerializer,
    VisitorChangePasswordSerializer,
    VisitorLoginSerializer,
    VisitorProfileSerializer,
    VisitorRegisterSerializer,
)


def _session_response(account, raw, created=False):
    return Response(
        {"token": raw, "account": account_payload(account)},
        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
    )


class VisitorRegisterView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [VisitorAuthThrottle]

    def post(self, request):
        ser = VisitorRegisterSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        account, ok, msg = register_account(audit_ip=client_ip(request), **ser.validated_data)
        if not ok:
            return Response(msg, status=status.HTTP_400_BAD_REQUEST)
        account.last_login = account.created_at
        account.save(update_fields=["last_login"])
        _, raw = create_session(account, request.headers.get("User-Agent", ""))
        return _session_response(account, raw, created=True)


class VisitorLoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [VisitorAuthThrottle]

    def post(self, request):
        ser = VisitorLoginSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        account, msg = authenticate_account(ser.validated_data["email"], ser.validated_data["password"])
        if account is None:
            AuditLog.log(
                None, "Visitor sign-in failed", "VisitorAccount", "",
                f"{ser.validated_data['email']} from {client_ip(request)}",
                ip_address=client_ip(request),
            )
            return Response({"detail": msg}, status=status.HTTP_400_BAD_REQUEST)
        _, raw = create_session(account, request.headers.get("User-Agent", ""))
        return _session_response(account, raw)


class _VisitorView(APIView):
    authentication_classes = [VisitorAccountAuthentication]
    permission_classes = [IsVisitorAccount]


class VisitorLogoutView(_VisitorView):
    def post(self, request):
        header = request.headers.get("Authorization") or ""
        revoke_session(header.partition(" ")[2].strip())
        return Response({"detail": "Signed out."})


class VisitorMeView(_VisitorView):
    def get(self, request):
        return Response(account_payload(request.visitor_account))

    def patch(self, request):
        ser = VisitorProfileSerializer(data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        account = request.visitor_account
        for field, value in ser.validated_data.items():
            setattr(account, field, value)
        account.save(update_fields=list(ser.validated_data.keys()) or None)
        return Response(account_payload(account))


class VisitorChangePasswordView(_VisitorView):
    def post(self, request):
        ser = VisitorChangePasswordSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        account = request.visitor_account
        if not account.check_password(ser.validated_data["current_password"]):
            return Response({"current_password": ["Current password is incorrect."]}, status=400)
        account.set_password(ser.validated_data["new_password"])
        account.save(update_fields=["password"])
        return Response({"detail": "Password updated."})


class VisitorOrganizationSearchView(_VisitorView):
    """The booking directory: every organisation with its buildings and
    floors (filtered by ``?q=``). Requires a signed-in visitor, so it is not
    an anonymous enumeration surface."""

    def get(self, request):
        q = (request.query_params.get("q") or "").strip()
        return Response(OrganizationSearchSerializer(search_organizations(q), many=True).data)


class VisitorOrganizationContextView(_VisitorView):
    def get(self, request, slug):
        org = Organization.objects.filter(slug=slug).first()
        if org is None:
            raise NotFound("We couldn't find that organisation.")
        return Response(build_public_booking_context(org))


class VisitorBookingsView(_VisitorView):
    throttle_classes = [PublicBookingRateThrottle]

    def get(self, request):
        visits = account_visits(request.visitor_account)
        return Response({"visits": VisitorAccountVisitSerializer(visits, many=True).data})

    def post(self, request):
        ser = VisitorBookingSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = dict(ser.validated_data)
        org = Organization.objects.filter(slug=data.pop("organization")).first()
        if org is None:
            raise NotFound("We couldn't find that organisation.")
        visit, ok, msg = book_visit_for_account(
            request.visitor_account,
            org,
            audit_ip=client_ip(request),
            visit_type=data.get("visit_type", ""),
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
            **({"category": data["category"]} if data.get("category") else {}),
        )
        if not ok:
            return Response(msg, status=status.HTTP_400_BAD_REQUEST)
        fresh = account_visit(request.visitor_account, visit.pk) or visit
        return Response(
            {"message": msg if isinstance(msg, str) else "Booking submitted.",
             "visit": VisitorAccountVisitSerializer(fresh).data},
            status=status.HTTP_201_CREATED,
        )


class VisitorBookingDetailView(_VisitorView):
    def get(self, request, pk):
        visit = account_visit(request.visitor_account, pk)
        if visit is None:
            raise NotFound("Unable to access this visit.")
        return Response(VisitorAccountVisitSerializer(visit).data)


class VisitorBookingAvailabilityView(_VisitorView):
    def get(self, request, pk):
        visit = account_visit(request.visitor_account, pk)
        if visit is None:
            raise NotFound("Unable to access this visit.")
        try:
            chosen = date.fromisoformat(request.query_params.get("date", "") or "")
        except ValueError:
            return Response({"detail": "Please choose a valid date."}, status=400)
        if chosen < org_localdate(visit.organization):
            return Response({"detail": "Visit date cannot be in the past."}, status=400)
        return Response(
            {
                "date": chosen.isoformat(),
                "slot_duration_minutes": organization_slot_duration(visit.organization),
                "slots": get_host_availability(visit.organization, visit.host, chosen),
            }
        )


class VisitorBookingRescheduleView(_VisitorView):
    def post(self, request, pk):
        visit = account_visit(request.visitor_account, pk)
        if visit is None:
            raise NotFound("Unable to access this visit.")
        updated, ok, message = reschedule_visit(
            scope_for_visit(visit), pk,
            new_date=request.data.get("visit_date"),
            expected_arrival=request.data.get("expected_arrival"),
            expected_exit=request.data.get("expected_exit"),
            audit_ip=client_ip(request),
        )
        if not ok:
            return Response({"detail": message}, status=400)
        return Response({"detail": message, "visit": VisitorAccountVisitSerializer(account_visit(request.visitor_account, pk) or updated).data})


class VisitorBookingCancelView(_VisitorView):
    def post(self, request, pk):
        visit = account_visit(request.visitor_account, pk)
        if visit is None:
            raise NotFound("Unable to access this visit.")
        updated, ok, message = cancel_visit(
            scope_for_visit(visit), pk, reason=request.data.get("reason", ""), audit_ip=client_ip(request)
        )
        if not ok:
            return Response({"detail": message}, status=400)
        return Response({"detail": message, "visit": VisitorAccountVisitSerializer(account_visit(request.visitor_account, pk) or updated).data})


class VisitorBookingArrivingView(_VisitorView):
    def post(self, request, pk):
        visit = account_visit(request.visitor_account, pk)
        if visit is None:
            raise NotFound("Unable to access this visit.")
        updated, ok, message = mark_visitor_arriving(scope_for_visit(visit), visit, audit_ip=client_ip(request))
        if not ok:
            return Response({"detail": message}, status=400)
        return Response({"detail": message, "visit": VisitorAccountVisitSerializer(account_visit(request.visitor_account, pk) or updated).data})
