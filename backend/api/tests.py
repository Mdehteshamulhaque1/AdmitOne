import importlib
import re
import shutil
import tempfile
import threading
from datetime import datetime, timedelta
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch

import config.urls as config_urls
from django.core.cache import cache
from django.core.exceptions import SuspiciousFileOperation
from django.db import IntegrityError, connection, connections, transaction
from django.http import Http404, HttpResponse
from django.test import RequestFactory, TestCase, TransactionTestCase, override_settings
from django.urls import resolve, Resolver404
from django.utils import timezone
from django.views.static import serve
from rest_framework.test import APIClient, APITestCase

from accounts.models import Role, User
from accounts.utils import client_ip
from api.serializers import OrganizationCreateSerializer, VisitSerializer
from config.middleware import ContentSecurityPolicyMiddleware
from organizations.models import AuditLog, Building, Department, Employee, Floor, Organization
from visits.availability import get_host_availability, validate_booking_slot
from visits.models import (
    QRPass,
    Visit,
    VisitSource,
    VisitStatus,
    VisitType,
    Visitor,
)
from visits.services import approve_visit, create_pre_booking, reschedule_visit


class AuthApiTests(APITestCase):
    """Auth endpoints used by the SPA signup/login flow."""

    def test_register_returns_tokens_and_creates_user(self):
        resp = self.client.post(
            "/api/auth/register/",
            {
                "email": "new@example.com",
                "full_name": "New Person",
                "phone": "9876543210",
                "password": "Str0ng!Pass",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertIn("access", resp.data)
        self.assertIn("refresh", resp.data)
        self.assertEqual(resp.data["user"]["email"], "new@example.com")
        self.assertTrue(User.objects.filter(email="new@example.com").exists())

    def test_register_rejects_duplicate_email(self):
        User.objects.create_user(email="dup@example.com", password="Str0ng!Pass", full_name="Dup")
        resp = self.client.post(
            "/api/auth/register/",
            {"email": "dup@example.com", "full_name": "Dup", "password": "Str0ng!Pass"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_token_endpoint_returns_access_and_refresh(self):
        User.objects.create_user(email="a@example.com", password="Str0ng!Pass", full_name="A")
        resp = self.client.post(
            "/api/auth/token/", {"email": "a@example.com", "password": "Str0ng!Pass"}, format="json"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("access", resp.data)
        self.assertIn("refresh", resp.data)

    def test_token_endpoint_rejects_bad_password(self):
        User.objects.create_user(email="a@example.com", password="Str0ng!Pass", full_name="A")
        resp = self.client.post(
            "/api/auth/token/", {"email": "a@example.com", "password": "Wrong!Pass"}, format="json"
        )
        self.assertEqual(resp.status_code, 401)

    def test_me_endpoint_with_bearer_token(self):
        User.objects.create_user(
            email="a@example.com", password="Str0ng!Pass", full_name="A", role=Role.ADMIN
        )
        resp = self.client.post(
            "/api/auth/token/", {"email": "a@example.com", "password": "Str0ng!Pass"}, format="json"
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")
        resp = self.client.get("/api/auth/me/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["user"]["email"], "a@example.com")

    def test_me_endpoint_requires_auth(self):
        resp = self.client.get("/api/auth/me/")
        self.assertEqual(resp.status_code, 401)


class VisitApiTests(APITestCase):
    """Visit-registration flow used by the SPA pre-registration page."""

    def setUp(self):
        self.org = Organization.objects.create(name="Test Org", slug="test-org")
        self.user = User.objects.create_user(
            email="e@example.com", password="Str0ng!Pass", full_name="E",
            role=Role.ADMIN, organization=self.org,
        )
        resp = self.client.post(
            "/api/auth/token/", {"email": "e@example.com", "password": "Str0ng!Pass"}, format="json"
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")

    def test_register_visit_creates_pending_visit(self):
        resp = self.client.post(
            "/api/visits/register/",
            {
                "visitor": {"full_name": "Guest", "phone": "9999999999"},
                "visit": {"purpose": "Client meeting", "host": self.user.pk},
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        visit = Visit.objects.get(pk=resp.data["visit"]["id"])
        self.assertEqual(visit.status, VisitStatus.PENDING)
        self.assertEqual(visit.organization, self.org)
        self.assertEqual(visit.visitor.full_name, "Guest")

    def test_register_visit_requires_purpose(self):
        resp = self.client.post(
            "/api/visits/register/",
            {"visitor": {"full_name": "Guest", "phone": "9999999999"}, "visit": {}},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_register_visit_rate_limited_per_ip(self):
        cache.clear()
        payload = {
            "visitor": {"full_name": "Guest", "phone": "9999999999"},
            "visit": {"purpose": "Client meeting", "host": self.user.pk},
        }
        for _ in range(10):
            self.client.post("/api/visits/register/", payload, format="json")
        resp = self.client.post("/api/visits/register/", payload, format="json")
        self.assertEqual(resp.status_code, 429)
        cache.clear()

    def test_walkin_creates_approved_visit_with_live_pass(self):
        resp = self.client.post(
            "/api/visits/walkin/",
            {
                "visitor": {"full_name": "Walkin Guest", "phone": "9888888888"},
                "visit": {"purpose": "Site visit", "host": self.user.pk},
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        visit = Visit.objects.get(pk=resp.data["visit"]["id"])
        self.assertEqual(visit.status, VisitStatus.APPROVED)
        self.assertEqual(
            resp.data["visit"]["status"],
            VisitStatus.APPROVED,
            "Walk-in API must not return the stale pre-approval status",
        )
        self.assertIsNotNone(visit.qr_pass, "Walk-in must issue a QR pass immediately")
        qr = resp.data["visit"]["qr"]
        self.assertTrue(qr["is_valid"])
        self.assertFalse(qr["is_used"])
        self.assertTrue(
            AuditLog.objects.filter(action="Visit approved").exists(),
            "Instant approval must be audited",
        )

    def test_walkin_pass_verifies_at_the_gate(self):
        resp = self.client.post(
            "/api/visits/walkin/",
            {
                "visitor": {"full_name": "Gate Walkin", "phone": "9777777777"},
                "visit": {"purpose": "Delivery", "host": self.user.pk},
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        qr = resp.data["visit"]["qr"]
        from visits.models import QRPass

        ok, msg, scanned = QRPass.verify(qr["token"], qr["signature"])
        self.assertTrue(ok, msg)
        self.assertEqual(scanned.visit_id, resp.data["visit"]["id"])

    def test_walkin_returns_structured_validation_errors(self):
        resp = self.client.post(
            "/api/visits/walkin/",
            {"visitor": {"full_name": "No Phone"}, "visit": {"purpose": "x"}},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        resp = self.client.post(
            "/api/visits/walkin/",
            {
                "visitor": {"full_name": "G", "phone": "9999999999"},
                "visit": {"purpose": "x" * 300},
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_visit_list_is_org_scoped(self):
        other_org = Organization.objects.create(name="Other Org", slug="other-org")
        other_user = User.objects.create_user(
            email="other@example.com", password="Str0ng!Pass", full_name="O",
            role=Role.ADMIN, organization=other_org,
        )
        other_visitor = Visitor.objects.create(
            full_name="Stray", phone="1111111111", organization=other_org
        )
        Visit.objects.create(
            visitor=other_visitor, organization=other_org, host=other_user, purpose="Other"
        )
        resp = self.client.get("/api/visits/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data["results"]), 0)


class VisitorApiTests(APITestCase):
    """Pagination and search on the visitors list."""

    def setUp(self):
        self.org = Organization.objects.create(name="Test Org", slug="test-org")
        self.user = User.objects.create_user(
            email="e@example.com", password="Str0ng!Pass", full_name="E",
            role=Role.ADMIN, organization=self.org,
        )
        resp = self.client.post(
            "/api/auth/token/", {"email": "e@example.com", "password": "Str0ng!Pass"}, format="json"
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")

        for i in range(25):
            visitor = Visitor.objects.create(
                full_name=f"Ravi Kumar {i:02d}", phone=f"90000{i:05d}",
                organization=self.org,
            )
            Visit.objects.create(
                visitor=visitor, organization=self.org, host=self.user, purpose="Walkthrough"
            )

    def test_list_is_paginated_at_20(self):
        resp = self.client.get("/api/visitors/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["count"], 25)
        self.assertEqual(len(resp.data["results"]), 20)
        self.assertIsNotNone(resp.data["next"])

    def test_next_page_returns_remaining(self):
        resp = self.client.get("/api/visitors/?page=2")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data["results"]), 5)

    def test_search_filters_by_name_or_phone(self):
        resp = self.client.get("/api/visitors/?q=Ravi%20Kumar%2001")
        self.assertEqual(resp.status_code, 200)
        names = [v["full_name"] for v in resp.data["results"]]
        self.assertIn("Ravi Kumar 01", names)


class OrganizationApiTests(APITestCase):
    """Workspace onboarding: create a new org."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="org@example.com", password="Str0ng!Pass", full_name="Org User"
        )
        resp = self.client.post(
            "/api/auth/token/", {"email": "org@example.com", "password": "Str0ng!Pass"}, format="json"
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")

    def test_create_org_assigns_admin_building_and_employee(self):
        resp = self.client.post(
            "/api/organizations/",
            {"name": "New Workspace", "building_name": "Tower One"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        org = Organization.objects.get(slug="new-workspace")
        self.assertEqual(org.name, "New Workspace")
        self.assertEqual(org.buildings.count(), 1)
        self.assertEqual(org.buildings.first().name, "Tower One")

        user = User.objects.get(pk=self.user.pk)
        self.assertEqual(user.organization, org)
        self.assertEqual(user.role, Role.ADMIN)

    def test_create_org_second_gets_unique_slug(self):
        Organization.objects.create(name="New Workspace", slug="new-workspace")
        resp = self.client.post("/api/organizations/", {"name": "New Workspace"}, format="json")
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(Organization.objects.filter(slug="new-workspace-2").exists())

    def test_create_org_surfaces_a_non_slug_integrity_error(self):
        """The collision retry must not disguise an unrelated IntegrityError.

        OrganizationSerializer retries the insert when it loses a slug race.
        An IntegrityError from any other constraint is not a naming collision
        and has to propagate, or a genuine data bug would be reported to the
        caller as "a workspace with a similar name already exists".
        """
        serializer = OrganizationCreateSerializer(data={"name": "Solo"})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        with patch.object(
            Organization.objects,
            "create",
            side_effect=IntegrityError("duplicate key value violates unique constraint"),
        ), self.assertRaises(IntegrityError):
            serializer.save()

    def test_create_org_rejects_user_already_in_org(self):
        existing = Organization.objects.create(name="Existing", slug="existing")
        self.user.organization = existing
        self.user.save(update_fields=["organization"])
        resp = self.client.post("/api/organizations/", {"name": "New"}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_create_org_requires_auth(self):
        self.client.credentials()
        resp = self.client.post("/api/organizations/", {"name": "X"}, format="json")
        self.assertEqual(resp.status_code, 401)


class RBACApiTests(APITestCase):
    """Server-side enforcement of role permissions on DRF actions."""

    def setUp(self):
        self.org = Organization.objects.create(name="RBAC Co", slug="rbac-co")
        self.other_org = Organization.objects.create(name="Other RBAC", slug="other-rbac")
        self.admin = User.objects.create_user(
            email="admin@rbac.com", password="Str0ng!Pass",
            full_name="Admin", role=Role.ADMIN, organization=self.org,
        )
        self.reception = User.objects.create_user(
            email="rec@rbac.com", password="Str0ng!Pass",
            full_name="Rec", role=Role.RECEPTIONIST, organization=self.org,
        )
        self.security = User.objects.create_user(
            email="sec@rbac.com", password="Str0ng!Pass",
            full_name="Sec", role=Role.SECURITY, organization=self.org,
        )
        self.other_admin = User.objects.create_user(
            email="other@rbac.com", password="Str0ng!Pass",
            full_name="Other", role=Role.ADMIN, organization=self.other_org,
        )
        self.visitor = Visitor.objects.create(
            full_name="Guest", phone="9999999999", organization=self.org
        )

    def _login(self, user):
        resp = self.client.post(
            "/api/auth/token/",
            {"email": user.email, "password": "Str0ng!Pass"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        return resp.data["access"]

    def _visit(self, org=None):
        org = org or self.org
        return Visit.objects.create(
            visitor=self.visitor, organization=org, created_by=self.admin,
            purpose="Meeting", visit_date=timezone.localdate(),
        )

    def test_receptionist_cannot_approve_via_api(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._login(self.reception)}")
        visit = self._visit()
        resp = self.client.post(f"/api/visits/{visit.pk}/approve/")
        self.assertEqual(resp.status_code, 403)

    def test_security_cannot_approve_via_api(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._login(self.security)}")
        visit = self._visit()
        resp = self.client.post(f"/api/visits/{visit.pk}/approve/")
        self.assertEqual(resp.status_code, 403)

    def test_security_can_checkin_via_api(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._login(self.security)}")
        visit = self._visit()
        approve_visit(visit, self.admin)
        resp = self.client.post(f"/api/visits/{visit.pk}/checkin/")
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_receptionist_cannot_checkin_via_api(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._login(self.reception)}")
        visit = self._visit()
        resp = self.client.post(f"/api/visits/{visit.pk}/checkin/")
        self.assertEqual(resp.status_code, 403)

    def test_other_org_admin_cannot_touch_foreign_visit(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._login(self.other_admin)}")
        visit = self._visit()
        resp = self.client.post(f"/api/visits/{visit.pk}/approve/")
        self.assertEqual(resp.status_code, 404)

    def test_visit_write_methods_forbidden(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._login(self.admin)}")
        # POST /api/visits/ is NOT a creation endpoint (F2): creation goes
        # through /api/visits/register/ and /api/visits/walkin/. An otherwise
        # valid body is rejected by the view, not by serializer validation.
        before = Visit.objects.count()
        resp = self.client.post(
            "/api/visits/",
            {"visitor_id": 1, "purpose": "hack", "visit_date": "2026-08-06"},
            format="json",
        )
        self.assertEqual(resp.status_code, 405, resp.data)
        self.assertIn("/api/visits/register/", resp.data["detail"])
        self.assertEqual(Visit.objects.count(), before)
        visit = self._visit()
        resp = self.client.patch(
            f"/api/visits/{visit.pk}/", {"status": "CHECKED_OUT"}, format="json"
        )
        self.assertEqual(resp.status_code, 405)
        resp = self.client.delete(f"/api/visits/{visit.pk}/")
        self.assertEqual(resp.status_code, 405)

    def test_visitor_write_methods_forbidden(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._login(self.admin)}")
        resp = self.client.post(
            "/api/visitors/", {"full_name": "x", "phone": "1"}, format="json"
        )
        self.assertEqual(resp.status_code, 405)

    def test_register_visit_requires_create_visitor_perm(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._login(self.security)}")
        resp = self.client.post(
            "/api/visits/register/",
            {"visitor": {"full_name": "G", "phone": "999"}, "visit": {"purpose": "x"}},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_walkin_requires_create_visitor_perm(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._login(self.security)}")
        resp = self.client.post(
            "/api/visits/walkin/",
            {"visitor": {"full_name": "G", "phone": "999"}, "visit": {"purpose": "x"}},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_register_rejects_foreign_host(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._login(self.admin)}")
        resp = self.client.post(
            "/api/visits/register/",
            {
                "visitor": {"full_name": "G", "phone": "9999999999"},
                "visit": {"purpose": "Meeting", "host": self.other_admin.pk},
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_register_rejects_exit_before_arrival(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._login(self.admin)}")
        resp = self.client.post(
            "/api/visits/register/",
            {
                "visitor": {"full_name": "G", "phone": "9999999999"},
                "visit": {
                    "purpose": "Meeting",
                    "expected_arrival": "15:00",
                    "expected_exit": "09:00",
                },
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_register_deduplicates_visitor_by_phone(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._login(self.admin)}")
        payload = {
            "visitor": {"full_name": "Same Person", "phone": "7000000000"},
            "visit": {"purpose": "First"},
        }
        r1 = self.client.post("/api/visits/register/", payload, format="json")
        r2 = self.client.post("/api/visits/register/", payload, format="json")
        self.assertEqual(r1.status_code, 201)
        self.assertEqual(r2.status_code, 201)
        self.assertEqual(r1.json()["visitor"]["id"], r2.json()["visitor"]["id"])
        self.assertEqual(Visitor.objects.filter(phone="7000000000").count(), 1)

    def test_register_writes_audit_with_ip(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._login(self.admin)}")
        resp = self.client.post(
            "/api/visits/register/",
            {
                "visitor": {"full_name": "Aud Person", "phone": "7000000001"},
                "visit": {"purpose": "Audit me"},
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        logs = AuditLog.objects.filter(
            user=self.admin, entity_type="Visit", action__icontains="registered",
        ).order_by("-id")
        self.assertTrue(logs.exists())
        self.assertEqual(logs.first().ip_address, "127.0.0.1")

    def test_page_size_is_capped(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._login(self.admin)}")
        for i in range(1010):
            Visit.objects.create(
                visitor=self.visitor, organization=self.org, created_by=self.admin,
                purpose=f"Bulk {i}", visit_date=timezone.localdate(),
            )
        resp = self.client.get("/api/visits/?page_size=999999")
        self.assertEqual(resp.status_code, 200)
        self.assertLessEqual(len(resp.data["results"]), 1000)


class LockoutApiTests(APITestCase):
    """JWT login lockout: 5 failures -> temporary lock, success resets."""

    def setUp(self):
        # A workspace is required because the console login gate refuses
        # tenantless accounts (`accounts.views.ConsoleLoginView`). This test is
        # about the lockout counters, so the account is made legitimately
        # console-eligible rather than relying on the old ADMIN default.
        self.org = Organization.objects.create(
            name="Lockout Co", slug="lockout-co"
        )
        self.user = User.objects.create_user(
            email="lock@example.com",
            password="Str0ng!Pass",
            full_name="Locked One",
            organization=self.org,
        )

    def _login(self, password):
        return self.client.post(
            "/api/auth/token/",
            {"email": "lock@example.com", "password": password},
            format="json",
        )

    def test_login_is_locked_after_five_failures(self):
        for _ in range(5):
            resp = self._login("wrong-password")
            self.assertEqual(resp.status_code, 401)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_locked)
        resp = self._login("Str0ng!Pass")
        self.assertEqual(resp.status_code, 401)
        self.assertIn("locked", resp.data.get("detail", ""))

    def test_successful_login_resets_failed_attempts(self):
        self._login("wrong-password")
        self.user.refresh_from_db()
        self.assertEqual(self.user.failed_login_attempts, 1)
        resp = self._login("Str0ng!Pass")
        self.assertEqual(resp.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.failed_login_attempts, 0)
        self.assertIsNone(self.user.locked_until)

    @override_settings(ACCOUNT_LOCKOUT_MINUTES=15)
    def test_lock_clears_after_window(self):
        from datetime import timedelta

        for _ in range(5):
            self._login("wrong-password")
        self.user.refresh_from_db()
        self.user.locked_until = timezone.now() - timedelta(minutes=1)
        self.user.save(update_fields=["locked_until"])
        resp = self._login("Str0ng!Pass")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("access", resp.data)


class ThrottleApiTests(APITestCase):
    """POST /api/visits/register/ is rate-limited per IP (10/min)."""

    def setUp(self):
        cache.clear()
        self.org = Organization.objects.create(name="Throttle Co", slug="throttle-co")
        self.user = User.objects.create_user(
            email="throttle@example.com", password="Str0ng!Pass",
            full_name="Throttle", role=Role.ADMIN, organization=self.org,
        )
        resp = self.client.post(
            "/api/auth/token/",
            {"email": "throttle@example.com", "password": "Str0ng!Pass"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")

    def tearDown(self):
        cache.clear()

    def _register(self, phone):
        return self.client.post(
            "/api/visits/register/",
            {
                "visitor": {"full_name": "Throttled Guest", "phone": phone},
                "visit": {"purpose": "Rate limit"},
            },
            format="json",
        )

    def test_register_is_throttled_after_10_per_minute(self):
        for i in range(10):
            resp = self._register(f"68000000{i:02d}")
            self.assertEqual(resp.status_code, 201, resp.content)
        resp = self._register("6800000099")
        self.assertEqual(resp.status_code, 429)
        self.assertIn("Request was throttled", resp.data.get("detail", ""))


class RegisterValidationApiTests(APITestCase):
    """Invalid/malformed inputs must yield 400s, never 500s."""

    def setUp(self):
        self.org = Organization.objects.create(name="Validation Co", slug="validation-co")
        self.user = User.objects.create_user(
            email="val@example.com", password="Str0ng!Pass",
            full_name="Val", role=Role.ADMIN, organization=self.org,
        )
        resp = self.client.post(
            "/api/auth/token/",
            {"email": "val@example.com", "password": "Str0ng!Pass"},
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")

    def test_invalid_visit_date_returns_400(self):
        resp = self.client.post(
            "/api/visits/register/",
            {
                "visitor": {"full_name": "Bad Date", "phone": "7000000100"},
                "visit": {"purpose": "M", "visit_date": "not-a-date"},
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_oversized_purpose_returns_400(self):
        resp = self.client.post(
            "/api/visits/register/",
            {
                "visitor": {"full_name": "Big Purpose", "phone": "7000000101"},
                "visit": {"purpose": "A" * 5000},
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_non_string_notes_are_coerced(self):
        resp = self.client.post(
            "/api/visits/register/",
            {
                "visitor": {"full_name": "Array Notes", "phone": "7000000102"},
                "visit": {"purpose": "M", "notes": ["not", "a", "string"]},
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)


class SecurityConfigTests(APITestCase):
    """HTTP-layer security behavior: CSP emission and audit-IP attribution."""

    @override_settings(
        CONTENT_SECURITY_POLICY={
            "DIRECTIVES": {
                "default-src": ("'self'",),
                "script-src": ("'self'", "https://cdn.jsdelivr.net"),
            }
        }
    )
    def test_csp_middleware_emits_header_from_settings(self):
        middleware = ContentSecurityPolicyMiddleware(lambda request: HttpResponse())
        # A real request, not a bare object(): the middleware stores the nonce
        # on it, so it needs somewhere to put it.
        response = middleware(RequestFactory().get("/"))
        header = response["Content-Security-Policy"]
        # The middleware appends a per-request 'nonce-...' to script-src so the
        # console's inline scripts are authorised without 'unsafe-inline'.
        # Compare the remainder so this test still pins the directives coming
        # from settings; config/test_production_security.py pins the nonce.
        without_nonce = re.sub(r"\s*'nonce-[A-Za-z0-9_-]+'", "", header)
        self.assertEqual(
            without_nonce,
            "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net",
        )
        self.assertRegex(header, r"'nonce-[A-Za-z0-9_-]+'")


    def test_client_ip_ignores_attacker_xff_when_not_behind_proxy(self):
        request = type("R", (), {"META": {
            "REMOTE_ADDR": "8.8.8.8",  # public: no proxy, XFF must be ignored
            "HTTP_X_FORWARDED_FOR": "6.6.6.6",  # spoofed, no trusted proxy
        }})()
        self.assertEqual(client_ip(request), "8.8.8.8")

    def test_client_ip_trusts_rightmost_hop_behind_proxy(self):
        request = type("R", (), {"META": {
            "REMOTE_ADDR": "10.0.0.5",  # private: proxy terminates
            "HTTP_X_FORWARDED_FOR": "6.6.6.6, 203.0.113.77",
        }})()
        self.assertEqual(client_ip(request), "203.0.113.77")


class ReportDataApiTests(APITestCase):
    """Dashboard summary fields + JWT-protected CSV export of real data."""

    def setUp(self):
        self.org = Organization.objects.create(name="Report Co", slug="report-co")
        self.other_org = Organization.objects.create(name="Other Co", slug="other-co")
        self.admin = User.objects.create_user(
            email="rep@example.com", password="Str0ng!Pass",
            full_name="Admin", role=Role.ADMIN, organization=self.org,
        )
        self.other_admin = User.objects.create_user(
            email="other@example.com", password="Str0ng!Pass",
            full_name="Other", role=Role.ADMIN, organization=self.other_org,
        )
        self.reception = User.objects.create_user(
            email="rep-rec@example.com", password="Str0ng!Pass",
            full_name="Reception", role=Role.RECEPTIONIST, organization=self.org,
        )
        self.security = User.objects.create_user(
            email="rep-sec@example.com", password="Str0ng!Pass",
            full_name="Security", role=Role.SECURITY, organization=self.org,
        )
        self.guest = User.objects.create_user(
            email="guest@example.com", password="Str0ng!Pass", full_name="Guest",
        )
        # role="" maps to base perms only (no view_reports), so we can prove
        # the export is gated on the application permission, not auth alone.
        self.guest.role = ""
        self.guest.save()

    def _login(self, user):
        resp = self.client.post(
            "/api/auth/token/",
            {"email": user.email, "password": "Str0ng!Pass"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        return resp.data["access"]

    def _visit(self, visitor, org, status=VisitStatus.PENDING, visit_date=None,
               created_by=None, check_in=None, check_out=None):
        return Visit.objects.create(
            visitor=visitor,
            organization=org,
            created_by=created_by or self.admin,
            purpose="Meeting",
            status=status,
            visit_date=visit_date or timezone.localdate(),
            checked_in_at=check_in,
            checked_out_at=check_out,
        )

    def test_summary_exposes_all_kpis(self):
        v = Visitor.objects.create(
            full_name="Guest One", phone="7000000100", organization=self.org
        )
        today = timezone.localdate()
        self._visit(v, self.org, status=VisitStatus.CHECKED_IN, visit_date=today,
                    check_in=timezone.now() - timedelta(hours=2))
        self._visit(v, self.org, status=VisitStatus.CHECKED_OUT, visit_date=today,
                    check_in=timezone.now() - timedelta(hours=3),
                    check_out=timezone.now() - timedelta(hours=1))
        self._visit(v, self.org, status=VisitStatus.PENDING, visit_date=today)
        self._visit(v, self.org, status=VisitStatus.REJECTED,
                    visit_date=today - timedelta(days=1))
        self._visit(v, self.org, status=VisitStatus.APPROVED,
                    visit_date=today - timedelta(days=1))

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._login(self.admin)}")
        resp = self.client.get("/api/dashboard/summary/")
        self.assertEqual(resp.status_code, 200)
        data = resp.data
        for field in (
            "today", "week", "month", "inside", "pending", "approved",
            "avg_duration_minutes", "checked_out", "rejected", "trend",
        ):
            self.assertIn(field, data, f"summary missing {field}")
        self.assertEqual(data["today"], 3)
        self.assertEqual(data["inside"], 1)
        self.assertEqual(data["checked_out"], 1)
        self.assertEqual(data["rejected"], 1)
        self.assertEqual(data["trend"], 50)  # today 3 vs yesterday 2

    def test_summary_requires_auth(self):
        resp = self.client.get("/api/dashboard/summary/")
        self.assertEqual(resp.status_code, 401)

    def test_report_export_returns_real_csv(self):
        v = Visitor.objects.create(
            full_name="Export Guest", phone="7000000101", organization=self.org
        )
        self._visit(v, self.org, status=VisitStatus.CHECKED_OUT,
                    check_in=timezone.now() - timedelta(hours=2),
                    check_out=timezone.now() - timedelta(hours=1))

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._login(self.admin)}")
        resp = self.client.get("/api/reports/export/", {"period": "daily"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp["Content-Type"].startswith("text/csv"))
        self.assertIn("attachment; filename", resp["Content-Disposition"])
        body = resp.content.decode("utf-8-sig")
        self.assertIn("Visitor,Phone,Company", body)
        self.assertIn("Export Guest", body)

    def test_report_export_requires_view_reports_permission(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._login(self.guest)}")
        resp = self.client.get("/api/reports/export/")
        self.assertEqual(resp.status_code, 403)

    def test_report_export_available_to_report_roles(self):
        for user in (self.reception, self.security):
            self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._login(user)}")
            resp = self.client.get("/api/reports/export/")
            self.assertEqual(resp.status_code, 200, f"{user.role} should export")

    def test_report_export_requires_auth(self):
        resp = self.client.get("/api/reports/export/")
        self.assertEqual(resp.status_code, 401)

    def test_report_export_is_org_scoped(self):
        mine = Visitor.objects.create(
            full_name="Mine Guest", phone="7000000102", organization=self.org
        )
        theirs = Visitor.objects.create(
            full_name="Theirs Guest", phone="7000000103", organization=self.other_org
        )
        self._visit(mine, self.org)
        self._visit(theirs, self.other_org, created_by=self.other_admin)

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._login(self.admin)}")
        resp = self.client.get("/api/reports/export/")
        body = resp.content.decode("utf-8-sig")
        self.assertIn("Mine Guest", body)
        self.assertNotIn("Theirs Guest", body)

    def test_report_export_period_filters_window(self):
        v = Visitor.objects.create(
            full_name="Old Guest", phone="7000000104", organization=self.org
        )
        old = self._visit(v, self.org, visit_date=timezone.localdate() - timedelta(days=45))
        # backdate registration so it falls outside weekly/monthly windows too
        Visit.objects.filter(pk=old.pk).update(
            registered_at=timezone.now() - timedelta(days=45),
        )

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._login(self.admin)}")
        daily = self.client.get("/api/reports/export/", {"period": "daily"}).content
        weekly = self.client.get("/api/reports/export/", {"period": "weekly"}).content
        monthly = self.client.get("/api/reports/export/", {"period": "monthly"}).content
        for body in (daily, weekly, monthly):
            self.assertNotIn("Old Guest", body.decode("utf-8-sig"))
        full = self.client.get("/api/reports/export/", {"period": "all"}).content
        self.assertIn("Old Guest", full.decode("utf-8-sig"))

    def test_report_export_bad_period_falls_back_to_daily(self):
        v = Visitor.objects.create(
            full_name="Daily Guest", phone="7000000105", organization=self.org
        )
        self._visit(v, self.org)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._login(self.admin)}")
        resp = self.client.get("/api/reports/export/", {"period": "quarterly"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Daily Guest", resp.content.decode("utf-8-sig"))

    def test_report_export_neutralizes_formula_injection(self):
        malicious = Visitor.objects.create(
            full_name="=HYPERLINK(x)", phone="7000000106", organization=self.org
        )
        self._visit(malicious, self.org)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._login(self.admin)}")
        resp = self.client.get("/api/reports/export/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("'=HYPERLINK(x)", resp.content.decode("utf-8-sig"))


class PublicBookingTests(APITestCase):
    """Smart pre-visit booking (anonymous public flow)."""

    def setUp(self):
        cache.clear()
        self.org = Organization.objects.create(
            name="Acme Inc", slug="acme-hq", city="Mumbai", country="IN",
            working_hours_start="09:00", working_hours_end="18:00",
        )
        self.other_org = Organization.objects.create(name="Other Inc", slug="other-inc")

        self.dept_sales = Department.objects.create(organization=self.org, name="Sales")
        self.dept_eng = Department.objects.create(organization=self.org, name="Engineering")
        self.other_dept = Department.objects.create(organization=self.other_org, name="Legal")

        self.building = Building.objects.create(organization=self.org, name="Acme Tower")
        self.floor_1 = Floor.objects.create(building=self.building, name="Floor 1", level=1)
        self.floor_2 = Floor.objects.create(building=self.building, name="Floor 2", level=2)
        self.other_building = Building.objects.create(organization=self.other_org, name="Other Tower")
        self.other_floor = Floor.objects.create(building=self.other_building, name="Other Floor", level=1)

        def make_host(email, department, status=Employee.Status.ACTIVE, org=None):
            user = User.objects.create_user(
                email=email, password="Str0ng!Pass", full_name=email.split("@")[0],
                organization=org or self.org,
            )
            Employee.objects.create(
                user=user, organization=org or self.org,
                employee_id=f"EMP-{email[:5]}", department=department,
                designation="Manager", status=status,
            )
            return user

        self.host_sales = make_host("anita@acme.com", self.dept_sales)
        self.host_eng = make_host("rahul@acme.com", self.dept_eng)
        self.host_inactive = make_host(
            "gone@acme.com", self.dept_sales, status=Employee.Status.INACTIVE
        )
        self.host_other = make_host("eve@else.com", self.other_dept, org=self.other_org)

        self.admin = User.objects.create_user(
            email="boss@acme.com", password="Str0ng!Pass", full_name="Boss",
            role=Role.ADMIN, organization=self.org,
        )
        self.future_date = (timezone.localdate() + timedelta(days=2)).isoformat()
        self.past_date = (timezone.localdate() - timedelta(days=2)).isoformat()

    def _url(self, tail=""):
        return f"/api/public/booking/acme-hq/{tail}"

    def _payload(self, **overrides):
        payload = {
            "visitor": {
                "full_name": "Aisha Khan", "phone": "9000000001",
                "email": "aisha@example.com", "company": "Nova College",
                "designation": "Student",
            },
            "visit_type": VisitType.INTERVIEW,
            "department": self.dept_sales.pk,
            "building": self.building.pk,
            "floor": self.floor_1.pk,
            "host": self.host_sales.pk,
            "visit_date": self.future_date,
            "expected_arrival": "10:00",
            "expected_exit": "11:30",
            "purpose": "Technical Interview",
        }
        payload.update({k: v for k, v in overrides.items() if v is not None})
        for key, value in overrides.items():
            if value is None:
                payload.pop(key, None)
        return payload

    def _post_booking(self, **overrides):
        return self.client.post(self._url(), self._payload(**overrides), format="json")

    def test_context_returns_org_departments_buildings_and_option_sets(self):
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 200)
        data = resp.data
        self.assertEqual(data["organization"]["name"], "Acme Inc")
        self.assertEqual(data["organization"]["working_hours_start"], "09:00")
        names = {d["name"] for d in data["departments"]}
        self.assertEqual(names, {"Sales", "Engineering"})
        self.assertNotIn(
            "Legal",
            [d["name"] for d in data["departments"]],
            "Must not leak another organization's departments",
        )
        self.assertEqual(data["buildings"][0]["name"], "Acme Tower")
        self.assertEqual(
            {f["name"] for f in data["buildings"][0]["floors"]}, {"Floor 1", "Floor 2"}
        )
        types = {t["value"] for t in data["visit_types"]}
        self.assertIn(VisitType.INTERVIEW, types)
        self.assertIn("Technical Interview", data["purposes"][VisitType.INTERVIEW])
        self.assertEqual(data["purposes"][VisitType.INTERVIEW][-1], "Other")

    def test_context_unknown_slug_is_404(self):
        resp = self.client.get("/api/public/booking/nope/")
        self.assertEqual(resp.status_code, 404)

    def test_hosts_filtered_by_department(self):
        resp = self.client.get(self._url("hosts/"), {"department": self.dept_sales.pk})
        self.assertEqual(resp.status_code, 200)
        names = {h["name"] for h in resp.data}
        self.assertIn("anita", names)
        self.assertNotIn("rahul", names)
        self.assertNotIn("eve", names)

    def test_hosts_empty_for_unknown_department(self):
        resp = self.client.get(self._url("hosts/"), {"department": 99999})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data, [])

    def test_valid_booking_creates_pending_prebooked_visit(self):
        resp = self._post_booking()
        self.assertEqual(resp.status_code, 201, resp.data)
        visit = Visit.objects.get(visit_id=resp.data["booking"]["visit_id"])
        self.assertEqual(visit.status, VisitStatus.PENDING)
        self.assertEqual(visit.source, VisitSource.PUBLIC_BOOKING)
        self.assertEqual(visit.visit_type, VisitType.INTERVIEW)
        self.assertEqual(visit.organization, self.org)
        self.assertEqual(visit.department, self.dept_sales)
        self.assertEqual(visit.building, self.building)
        self.assertEqual(visit.floor, self.floor_1)
        self.assertEqual(visit.host, self.host_sales)
        self.assertEqual(visit.visitor.full_name, "Aisha Khan")
        self.assertEqual(visit.visitor.phone, "9000000001")
        self.assertEqual(visit.visitor.company, "Nova College")
        self.assertEqual(visit.purpose, "Technical Interview")
        with self.assertRaises(QRPass.DoesNotExist):
            visit.qr_pass
        self.assertTrue(
            AuditLog.objects.filter(
                action="Pre-booking submitted", entity_type="Visit"
            ).exists(),
            "Pre-booking must be audited",
        )

    def test_booking_returns_real_identifier(self):
        resp = self._post_booking()
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(str(resp.data["booking"]["visit_id"]))
        self.assertEqual(resp.data["booking"]["status"], "PENDING")

    def test_booking_reuses_existing_visitor_by_phone(self):
        first = self._post_booking()
        self.assertEqual(first.status_code, 201)
        # Second booking uses a different (non-conflicting) time so it can
        # succeed under the slot-conflict rules, but must reuse the visitor.
        second = self._post_booking(expected_arrival="12:00", expected_exit="13:30")
        self.assertEqual(second.status_code, 201)
        self.assertEqual(Visitor.objects.count(), 1)
        self.assertEqual(
            first.data["booking"]["visitor"]["id"],
            second.data["booking"]["visitor"]["id"],
            "Same phone must reuse the existing visitor, not duplicate",
        )

    def test_booking_requires_phone_and_name(self):
        resp = self._post_booking(
            visitor={"full_name": "", "phone": ""}, visit_type=VisitType.INTERVIEW
        )
        self.assertEqual(resp.status_code, 400)

    def test_booking_rejects_invalid_visit_type(self):
        resp = self._post_booking(visit_type="NOT_A_TYPE")
        self.assertEqual(resp.status_code, 400)

    def test_booking_rejects_purpose_not_valid_for_type(self):
        resp = self._post_booking(purpose="Bungee Jumping")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("purpose", resp.data.get("detail", {}))

    def test_booking_other_purpose_requires_narrative(self):
        resp = self._post_booking(purpose="Other", purpose_other="")
        self.assertEqual(resp.status_code, 400)

    def test_booking_other_purpose_stores_narrative(self):
        resp = self._post_booking(purpose="Other", purpose_other="College placement drive")
        self.assertEqual(resp.status_code, 201)
        visit = Visit.objects.get(visit_id=resp.data["booking"]["visit_id"])
        self.assertEqual(visit.purpose, "College placement drive")

    def test_cross_org_host_rejected(self):
        resp = self._post_booking(host=self.host_other.pk)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Visit.objects.count(), 0)

    def test_invalid_host_rejected(self):
        resp = self._post_booking(host=999999)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Visit.objects.count(), 0)

    def test_host_not_in_selected_department_rejected(self):
        resp = self._post_booking(host=self.host_eng.pk, department=self.dept_sales.pk)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Visit.objects.count(), 0)

    def test_inactive_host_rejected(self):
        resp = self._post_booking(host=self.host_inactive.pk)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Visit.objects.count(), 0)

    def test_cross_org_department_rejected(self):
        resp = self._post_booking(department=self.other_dept.pk)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Visit.objects.count(), 0)

    def test_cross_org_building_rejected(self):
        resp = self._post_booking(building=self.other_building.pk)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Visit.objects.count(), 0)

    def test_cross_org_floor_rejected(self):
        resp = self._post_booking(floor=self.other_floor.pk, building=None)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Visit.objects.count(), 0)

    def test_floor_must_belong_to_selected_building(self):
        resp = self._post_booking(floor=self.other_floor.pk, building=self.building.pk)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Visit.objects.count(), 0)

    def test_past_visit_date_rejected(self):
        resp = self._post_booking(visit_date=self.past_date)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Visit.objects.count(), 0)

    def test_bad_visit_date_rejected(self):
        resp = self._post_booking(visit_date="not-a-date")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Visit.objects.count(), 0)

    def test_missing_times_rejected(self):
        resp = self._post_booking(expected_arrival="", expected_exit="")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Visit.objects.count(), 0)

    def test_invalid_time_format_rejected(self):
        resp = self._post_booking(expected_arrival="25:99", expected_exit="26:00")
        self.assertEqual(resp.status_code, 400)

    def test_exit_before_arrival_rejected(self):
        resp = self._post_booking(expected_arrival="14:00", expected_exit="13:00")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Visit.objects.count(), 0)

    def test_outside_working_hours_rejected(self):
        before = self._post_booking(expected_arrival="08:00", expected_exit="09:30")
        self.assertEqual(before.status_code, 400)
        after = self._post_booking(expected_arrival="17:30", expected_exit="19:00")
        self.assertEqual(after.status_code, 400)
        self.assertEqual(Visit.objects.count(), 0)

    def test_public_booking_rate_limited(self):
        cache.clear()
        payload = self._payload()
        for _ in range(20):
            self.client.post(self._url(), payload, format="json")
        resp = self.client.post(self._url(), payload, format="json")
        self.assertEqual(resp.status_code, 429)
        cache.clear()

    def test_prebooked_visit_survives_existing_approval_workflow(self):
        resp = self._post_booking()
        self.assertEqual(resp.status_code, 201)
        visit = Visit.objects.get(visit_id=resp.data["booking"]["visit_id"])

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._login(self.admin)}")
        approved = self.client.post(f"/api/visits/{visit.pk}/approve/", {}, format="json")
        self.assertEqual(approved.status_code, 200, approved.data)
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.APPROVED)
        self.assertTrue(QRPass.objects.filter(visit=visit).exists())

        checked_in = self.client.post(f"/api/visits/{visit.pk}/checkin/", {}, format="json")
        self.assertEqual(checked_in.status_code, 200, checked_in.data)
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.CHECKED_IN)

        checked_out = self.client.post(f"/api/visits/{visit.pk}/checkout/", {}, format="json")
        self.assertEqual(checked_out.status_code, 200, checked_out.data)
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.CHECKED_OUT)
        self.client.credentials()

    def _login(self, user):
        resp = self.client.post(
            "/api/auth/token/",
            {"email": user.email, "password": "Str0ng!Pass"},
            format="json",
        )
        return resp.data["access"]


class HostAvailabilityTests(APITestCase):
    """Feature #2 — host availability, appointment slots, slot-safe booking."""

    def setUp(self):
        cache.clear()
        self.org = Organization.objects.create(
            name="Pulse Labs", slug="pulse-labs", city="Pune", country="IN",
            working_hours_start="09:00", working_hours_end="18:00",
        )
        self.other_org = Organization.objects.create(name="Other Inc", slug="other-inc")
        self.closed_org = Organization.objects.create(
            name="Closed Co", slug="closed-co",
            working_hours_start="09:00", working_hours_end="18:00",
            weekly_working_hours={
                str(day): ([{"start": "09:00", "end": "18:00"}] if day != 6 else None)
                for day in range(7)
            },
        )

        self.admin = User.objects.create_user(
            email="boss@pulse.com", password="Str0ng!Pass",
            full_name="Boss", role=Role.ADMIN, organization=self.org,
        )
        self.dept = Department.objects.create(organization=self.org, name="Advisory")
        self.dept2 = Department.objects.create(organization=self.org, name="Design")
        self.host = self._employee("amit@pulse.com", self.dept)
        self.host_dept2 = self._employee("priya@pulse.com", self.dept2)
        self.host_inactive = self._employee(
            "gone@pulse.com", self.dept, status=Employee.Status.INACTIVE
        )
        self.host_disabled = self._employee(
            "off@pulse.com", self.dept, user_active=False
        )
        self.other_host = User.objects.create_user(
            email="mira@other.com", password="Str0ng!Pass",
            full_name="Mira", organization=self.other_org, is_active=True,
        )
        self.closed_host = User.objects.create_user(
            email="sunday@closed.com", password="Str0ng!Pass",
            full_name="Sunny", organization=self.closed_org, is_active=True,
        )

        self.today = timezone.localdate()
        self.open_day = self.today + timedelta(days=2)
        self.sunday = self.today + timedelta(days=(6 - self.today.weekday()) % 7)

    def _employee(self, email, department, status=Employee.Status.ACTIVE, user_active=True):
        user = User.objects.create_user(
            email=email, password="Str0ng!Pass",
            full_name=email.split("@")[0], organization=self.org, is_active=user_active,
        )
        Employee.objects.create(
            user=user, organization=self.org, employee_id=f"E{abs(hash(email)):x}",
            department=department, designation="Manager", status=status,
        )
        return user

    @staticmethod
    def _t(value):
        return datetime.strptime(value, "%H:%M").time()

    @staticmethod
    def _min(value):
        hour, minute = value.split(":")
        return int(hour) * 60 + int(minute)

    def _avail(self, slug="pulse-labs", **params):
        qs = "&".join(f"{key}={value}" for key, value in params.items())
        return f"/api/public/booking/{slug}/availability/?{qs}"

    def _book(self, host, day, start, end, status=VisitStatus.PENDING, phone="7122000001"):
        visitor = Visitor.objects.create(
            full_name="Test Guest", phone=phone, organization=self.org
        )
        return Visit.objects.create(
            visitor=visitor,
            organization=self.org,
            host=host,
            visit_date=day,
            expected_arrival=self._t(start),
            expected_exit=self._t(end),
            status=status,
            purpose="Client sync",
        )

    def _payload(self, day, start, end, host=None, phone="7888100001", **overrides):
        payload = {
            "visitor": {"full_name": "Rohit Mehta", "phone": phone},
            "visit_type": VisitType.INTERVIEW,
            "department": self.dept.pk,
            "host": (host or self.host).pk,
            "visit_date": day.isoformat(),
            "expected_arrival": start,
            "expected_exit": end,
            "purpose": "Technical Interview",
        }
        payload.update({k: v for k, v in overrides.items() if v is not None})
        for key, value in overrides.items():
            if value is None:
                payload.pop(key, None)
        return payload

    def _post(self, day, start, end, host=None, phone="7888100001", **overrides):
        return self.client.post(
            "/api/public/booking/pulse-labs/",
            self._payload(day, start, end, host=host, phone=phone, **overrides),
            format="json",
        )

    def _login(self, user):
        resp = self.client.post(
            "/api/auth/token/",
            {"email": user.email, "password": "Str0ng!Pass"},
            format="json",
        )
        return resp.data["access"]

    # ---- Availability endpoint ----------------------------------------

    def test_availability_returns_structured_slots(self):
        resp = self.client.get(self._avail(host=self.host.pk, date=self.open_day.isoformat()))
        self.assertEqual(resp.status_code, 200, resp.data)
        data = resp.data
        self.assertEqual(data["date"], self.open_day.isoformat())
        self.assertEqual(data["host"]["name"], "amit")
        self.assertEqual(data["slot_duration_minutes"], 30)
        slots = data["slots"]
        self.assertEqual(len(slots), 18)  # 09:00-18:00 in 30-min blocks
        self.assertEqual(slots[0]["start"], "09:00")
        self.assertEqual(slots[0]["end"], "09:30")
        self.assertEqual(slots[-1]["start"], "17:30")
        self.assertEqual(slots[-1]["end"], "18:00")

    def test_availability_respects_working_hours(self):
        resp = self.client.get(self._avail(host=self.host.pk, date=self.open_day.isoformat()))
        self.assertEqual(resp.status_code, 200)
        for slot in resp.data["slots"]:
            start = self._min(slot["start"])
            end = self._min(slot["end"])
            self.assertEqual(end - start, 30)
            self.assertGreaterEqual(start, 9 * 60)
            self.assertLessEqual(end, 18 * 60)

    def test_non_working_day_returns_no_slots(self):
        resp = self.client.get(
            self._avail("closed-co", host=self.closed_host.pk, date=self.sunday.isoformat())
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["slots"], [])

        monday = self.sunday + timedelta(days=1)
        resp2 = self.client.get(
            self._avail("closed-co", host=self.closed_host.pk, date=monday.isoformat())
        )
        self.assertEqual(resp2.status_code, 200)
        self.assertGreater(len(resp2.data["slots"]), 0)

    def test_existing_booking_blocks_that_slot(self):
        self._book(self.host, self.open_day, "10:00", "10:30")
        resp = self.client.get(self._avail(host=self.host.pk, date=self.open_day.isoformat()))
        starts = {s["start"] for s in resp.data["slots"]}
        self.assertNotIn("10:00", starts)
        self.assertIn("09:30", starts)
        self.assertIn("10:30", starts)

    def test_adjacent_bookings_and_slots_remain_available(self):
        self._book(self.host, self.open_day, "09:00", "09:30")
        ok, _ = validate_booking_slot(
            self.org, self.host, self.open_day, self._t("09:30"), self._t("10:00")
        )
        self.assertTrue(ok)
        resp = self.client.get(self._avail(host=self.host.pk, date=self.open_day.isoformat()))
        starts = {s["start"] for s in resp.data["slots"]}
        self.assertNotIn("09:00", starts)
        self.assertIn("09:30", starts)

    def test_overlapping_booking_rejected(self):
        self._book(self.host, self.open_day, "10:00", "10:30")
        self.assertFalse(
            validate_booking_slot(
                self.org, self.host, self.open_day, self._t("10:00"), self._t("10:30")
            )[0]
        )
        self.assertFalse(
            validate_booking_slot(
                self.org, self.host, self.open_day, self._t("10:15"), self._t("10:45")
            )[0]
        )
        self.assertTrue(
            validate_booking_slot(
                self.org, self.host, self.open_day, self._t("10:30"), self._t("11:00")
            )[0]
        )

    def test_rejected_visit_does_not_block_slot(self):
        self._book(self.host, self.open_day, "10:00", "10:30", status=VisitStatus.REJECTED)
        resp = self.client.get(self._avail(host=self.host.pk, date=self.open_day.isoformat()))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("10:00", {s["start"] for s in resp.data["slots"]})

    def test_checked_out_visit_does_not_block_slot(self):
        self._book(self.host, self.open_day, "10:00", "10:30", status=VisitStatus.CHECKED_OUT)
        resp = self.client.get(self._avail(host=self.host.pk, date=self.open_day.isoformat()))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("10:00", {s["start"] for s in resp.data["slots"]})

    def test_wrong_organization_host_rejected(self):
        resp = self.client.get(self._avail(host=self.other_host.pk, date=self.open_day.isoformat()))
        self.assertEqual(resp.status_code, 400)

    def test_host_must_belong_to_department_when_requested(self):
        resp = self.client.get(
            self._avail(host=self.host_dept2.pk, date=self.open_day.isoformat(), department=self.dept.pk)
        )
        self.assertEqual(resp.status_code, 400)
        resp2 = self.client.get(
            self._avail(host=self.host_dept2.pk, date=self.open_day.isoformat(), department=self.dept2.pk)
        )
        self.assertEqual(resp2.status_code, 200)

    def test_inactive_host_rejected(self):
        for host in (self.host_inactive, self.host_disabled):
            resp = self.client.get(self._avail(host=host.pk, date=self.open_day.isoformat()))
            self.assertEqual(resp.status_code, 400, host.email)

    def test_invalid_or_past_date_rejected(self):
        ok = self._avail(host=self.host.pk, date=self.open_day.isoformat())
        bads = [
            self._avail(host=self.host.pk),                      # date missing
            self._avail(date=self.open_day.isoformat()),         # host missing
            self._avail(host="abc", date=self.open_day.isoformat()),
            self._avail(host=self.host.pk, date="not-a-date"),
            self._avail(host=self.host.pk, date=(self.today - timedelta(days=1)).isoformat()),
        ]
        for url in bads:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 400, url)

    # ---- Service helpers ---------------------------------------------

    def test_service_level_availability_matches_endpoint(self):
        slots = get_host_availability(self.org, self.host, self.open_day)
        self.assertEqual(len(slots), 18)
        self.assertEqual(slots[0], {"start": "09:00", "end": "09:30"})

    def test_slot_duration_configurable_per_organization(self):
        Organization.objects.filter(pk=self.org.pk).update(
            visitor_policies={"appointment_duration_minutes": 60}
        )
        resp = self.client.get(self._avail(host=self.host.pk, date=self.open_day.isoformat()))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["slot_duration_minutes"], 60)
        self.assertEqual(resp.data["slots"][0]["start"], "09:00")
        self.assertEqual(resp.data["slots"][0]["end"], "10:00")
        self.assertEqual(len(resp.data["slots"]), 9)

    # ---- Booking submission (slot-safe) ------------------------------

    def test_booking_succeeds_when_slot_available(self):
        resp = self._post(self.open_day, "10:00", "10:30")
        self.assertEqual(resp.status_code, 201, resp.data)
        visit = Visit.objects.get(visit_id=resp.data["booking"]["visit_id"])
        self.assertEqual(visit.expected_arrival, self._t("10:00"))
        self.assertEqual(visit.expected_exit, self._t("10:30"))
        self.assertEqual(visit.host_id, self.host.pk)
        self.assertEqual(visit.status, VisitStatus.PENDING)
        self.assertEqual(visit.source, VisitSource.PUBLIC_BOOKING)

    def test_booking_fails_when_slot_unavailable_at_submission(self):
        self._book(self.host, self.open_day, "10:00", "10:30", phone="7122000020")
        resp = self._post(self.open_day, "10:00", "10:30", phone="7888100020")
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertIn("no longer available", str(resp.data))
        self.assertEqual(
            Visit.objects.filter(host=self.host, visit_date=self.open_day).count(), 1
        )

    def test_two_submissions_cannot_reserve_the_same_slot(self):
        first = self._post(self.open_day, "10:00", "10:30", phone="7888100030")
        self.assertEqual(first.status_code, 201, first.data)
        second = self._post(self.open_day, "10:00", "10:30", phone="7888100031")
        self.assertEqual(second.status_code, 400)
        self.assertEqual(
            Visit.objects.filter(
                host=self.host, visit_date=self.open_day, status=VisitStatus.PENDING
            ).count(),
            1,
        )

    # The concurrent-booking race lives in ConcurrentBookingRaceTests, which
    # uses TransactionTestCase so its worker threads can actually see the
    # fixtures. See the class docstring there for why an APITestCase cannot
    # host a threaded test.

    # ---- Regression: existing flows still work -----------------------

    def test_walkin_flow_still_works(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._login(self.admin)}")
        resp = self.client.post(
            "/api/visits/walkin/",
            {
                "visitor": {"full_name": "Walkin Guest", "phone": "9888888002"},
                "visit": {"purpose": "Site visit", "host": self.host.pk},
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data["visit"]["status"], VisitStatus.APPROVED)
        visit = Visit.objects.get(pk=resp.data["visit"]["id"])
        self.assertIsNotNone(visit.qr_pass)
        self.client.credentials()

    def test_approval_qr_checkin_checkout_flow_still_works(self):
        booking = self._post(self.open_day, "14:00", "14:30", phone="7888100080")
        self.assertEqual(booking.status_code, 201, booking.data)
        visit = Visit.objects.get(visit_id=booking.data["booking"]["visit_id"])

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._login(self.admin)}")
        approved = self.client.post(f"/api/visits/{visit.pk}/approve/", {}, format="json")
        self.assertEqual(approved.status_code, 200, approved.data)
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.APPROVED)
        self.assertTrue(QRPass.objects.filter(visit=visit).exists())

        checked_in = self.client.post(f"/api/visits/{visit.pk}/checkin/", {}, format="json")
        self.assertEqual(checked_in.status_code, 200, checked_in.data)
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.CHECKED_IN)

        checked_out = self.client.post(f"/api/visits/{visit.pk}/checkout/", {}, format="json")
        self.assertEqual(checked_out.status_code, 200, checked_out.data)
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.CHECKED_OUT)
        self.client.credentials()

    # ---- Calendar (one request for the whole range) ------------------

    def _cal(self, slug="pulse-labs", **params):
        qs = "&".join(f"{key}={value}" for key, value in params.items())
        return f"/api/public/booking/{slug}/calendar/?{qs}"

    def test_calendar_counts_match_per_day_availability(self):
        self._book(self.host, self.open_day, "10:00", "10:30")
        resp = self.client.get(self._cal(host=self.host.pk, start=self.today.isoformat(), days=7))
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(len(resp.data["days"]), 7)
        self.assertEqual(resp.data["slot_duration_minutes"], 30)
        for offset in range(7):
            day = self.today + timedelta(days=offset)
            expected = len(get_host_availability(self.org, self.host, day))
            self.assertEqual(resp.data["days"][day.isoformat()], expected, day)
        # 09:00-18:00 in 30-minute slots = 18, minus the booked one.
        self.assertEqual(resp.data["days"][self.open_day.isoformat()], 17)

    def test_calendar_defaults_to_90_days_from_today(self):
        resp = self.client.get(self._cal(host=self.host.pk))
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(len(resp.data["days"]), 90)
        self.assertEqual(resp.data["start"], self.today.isoformat())

    def test_calendar_clamps_past_start_to_today(self):
        past = (self.today - timedelta(days=5)).isoformat()
        resp = self.client.get(self._cal(host=self.host.pk, start=past, days=3))
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["start"], self.today.isoformat())

    def test_calendar_marks_closed_days_with_zero(self):
        resp = self.client.get(self._cal(slug="closed-co", host=self.closed_host.pk, start=self.sunday.isoformat(), days=1))
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["days"][self.sunday.isoformat()], 0)

    def test_calendar_rejects_bad_input_and_foreign_hosts(self):
        self.assertEqual(self.client.get(self._cal(host=self.other_host.pk)).status_code, 400)
        self.assertEqual(self.client.get(self._cal(host=self.host_disabled.pk)).status_code, 400)
        self.assertEqual(self.client.get(self._cal(host="abc")).status_code, 400)
        self.assertEqual(self.client.get(self._cal(host=self.host.pk, days=91)).status_code, 400)
        self.assertEqual(self.client.get(self._cal(host=self.host.pk, start="nope")).status_code, 400)
        self.assertEqual(self.client.get(self._cal(slug="missing-org", host=self.host.pk)).status_code, 404)

    def test_calendar_query_count_does_not_grow_with_days(self):
        url = self._cal(host=self.host.pk, days=90)
        with self.assertNumQueries(self._calendar_queries(url, 1)):
            self.client.get(url)

    def test_today_hides_and_rejects_slots_that_already_started(self):
        from datetime import time as dtime
        from accounts.utils import org_localdate, org_timezone
        from visits.availability import get_host_availability_calendar

        today = org_localdate(self.org)
        noon = datetime.combine(today, dtime(12, 10), tzinfo=org_timezone(self.org))
        with patch("django.utils.timezone.now", return_value=noon):
            slots = get_host_availability(self.org, self.host, today)
            self.assertTrue(slots)
            self.assertTrue(all(s["start"] > "12:10" for s in slots), slots)
            self.assertEqual(slots[0]["start"], "12:30")
            # 12:30 .. 17:30 in 30-minute slots
            self.assertEqual(get_host_availability_calendar(self.org, self.host, today, 1)[today.isoformat()], 11)
            ok, reason = validate_booking_slot(self.org, self.host, today, dtime(9, 0), dtime(9, 30))
            self.assertFalse(ok)
            self.assertIn("already passed", reason)
            ok, _ = validate_booking_slot(self.org, self.host, today, dtime(12, 30), dtime(13, 0))
            self.assertTrue(ok)
            # Tomorrow is untouched.
            tomorrow = today + timedelta(days=1)
            self.assertEqual(get_host_availability(self.org, self.host, tomorrow)[0]["start"], "09:00")

    def _calendar_queries(self, url, _):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as short:
            self.client.get(self._cal(host=self.host.pk, days=1))
        return len(short.captured_queries)


    # ---- Regression --------------------------------------------------


class LogoutApiTests(APITestCase):
    """POST /api/auth/logout/ blacklists the presented refresh token."""

    def setUp(self):
        self.org = Organization.objects.create(name="Logout Org", slug="logout-org")
        self.user = User.objects.create_user(
            email="lo@example.com", password="Str0ng!Pass", full_name="L",
            role=Role.ADMIN, organization=self.org,
        )
        resp = self.client.post(
            "/api/auth/token/",
            {"email": "lo@example.com", "password": "Str0ng!Pass"},
            format="json",
        )
        self.tokens = resp.data
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.tokens['access']}")

    def test_logout_blacklists_refresh_token(self):
        resp = self.client.post(
            "/api/auth/logout/", {"refresh": self.tokens["refresh"]}, format="json"
        )
        self.assertEqual(resp.status_code, 205)

        # The blacklisted refresh token must no longer issue a new access pair.
        self.client.credentials()
        resp = self.client.post(
            "/api/auth/token/refresh/",
            {"refresh": self.tokens["refresh"]},
            format="json",
        )
        self.assertEqual(resp.status_code, 401)

    def test_logout_requires_refresh_token(self):
        resp = self.client.post("/api/auth/logout/", {}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_logout_rejects_bogus_token(self):
        resp = self.client.post("/api/auth/logout/", {"refresh": "not-a-token"}, format="json")
        self.assertEqual(resp.status_code, 400)


class ReissueApiTests(APITestCase):
    """POST /api/visits/{id}/reissue/ rotates an expired/used QR pass."""

    def setUp(self):
        cache.clear()  # throttle counters are shared across tests in a run
        self.org = Organization.objects.create(name="Reissue Org", slug="reissue-org")
        self.user = User.objects.create_user(
            email="ri@example.com", password="Str0ng!Pass", full_name="R",
            role=Role.ADMIN, organization=self.org,
        )
        resp = self.client.post(
            "/api/auth/token/",
            {"email": "ri@example.com", "password": "Str0ng!Pass"},
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")
        self.visit = self._register()

    def _register(self):
        resp = self.client.post(
            "/api/visits/register/",
            {
                "visitor": {"full_name": "Guest", "phone": "7777777777"},
                "visit": {"purpose": "Client meeting", "host": self.user.pk},
            },
            format="json",
        )
        return Visit.objects.get(pk=resp.data["visit"]["id"])

    def test_reissue_rotates_expired_pass(self):
        resp = self.client.post(f"/api/visits/{self.visit.pk}/approve/", {}, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)
        qr = QRPass.objects.get(visit=self.visit)
        old_token, old_sig = str(qr.token), qr.signature

        QRPass.objects.filter(visit=self.visit).update(expires_at=timezone.now() - timezone.timedelta(minutes=1))
        qr.refresh_from_db()
        self.assertFalse(qr.is_valid)

        resp = self.client.post(f"/api/visits/{self.visit.pk}/reissue/", {}, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)

        qr.refresh_from_db()
        self.assertNotEqual(str(qr.token), old_token)
        self.assertNotEqual(qr.signature, old_sig)
        self.assertFalse(qr.is_used)
        self.assertTrue(qr.is_valid)

        opt_ok, _, _ = QRPass.verify(old_token, old_sig)
        self.assertFalse(opt_ok)
        ok, msg, _ = QRPass.verify(str(qr.token), qr.signature)
        self.assertTrue(ok, msg)

    def test_reissue_rejects_unapproved_visit(self):
        self.assertEqual(self.visit.status, VisitStatus.PENDING)
        resp = self.client.post(f"/api/visits/{self.visit.pk}/reissue/", {}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Cannot re-issue", resp.data["detail"])

    def test_reissue_requires_approve_permission(self):
        resp = self.client.post(f"/api/visits/{self.visit.pk}/approve/", {}, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)
        QRPass.objects.filter(visit=self.visit).update(expires_at=timezone.now() - timezone.timedelta(minutes=1))

        guard = User.objects.create_user(
            email="sec@example.com", password="Str0ng!Pass", full_name="S",
            role=Role.SECURITY, organization=self.org,
        )
        resp = self.client.post(
            "/api/auth/token/",
            {"email": "sec@example.com", "password": "Str0ng!Pass"},
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")
        resp = self.client.post(f"/api/visits/{self.visit.pk}/reissue/", {}, format="json")
        self.assertEqual(resp.status_code, 403)
        _ = guard


class GenericVisitCreationDisabledTests(APITestCase):
    """F2 — generic ``POST /api/visits/`` must never create a visit.

    It used to persist straight from ``VisitSerializer.create`` and therefore
    skipped ``create_visitor``, the registration throttle, ``register_visit``'s
    validation and the audit trail. The two domain endpoints remain the only
    ways in.
    """

    def setUp(self):
        cache.clear()
        self.org = Organization.objects.create(name="Create Org", slug="create-org")
        self.other_org = Organization.objects.create(name="Rival Org", slug="rival-org")
        self.building = Building.objects.create(organization=self.org, name="Main", floors=2)
        self.rival_building = Building.objects.create(
            organization=self.other_org, name="Rival Tower", floors=1
        )
        self.admin = User.objects.create_user(
            email="cr@example.com", password="Str0ng!Pass", full_name="C",
            role=Role.ADMIN, organization=self.org,
        )
        self.receptionist = User.objects.create_user(
            email="crr@example.com", password="Str0ng!Pass", full_name="CR",
            role=Role.RECEPTIONIST, organization=self.org,
        )
        self.security = User.objects.create_user(
            email="crs@example.com", password="Str0ng!Pass", full_name="CS",
            role=Role.SECURITY, organization=self.org,
        )
        # an ADMIN that has been deactivated: role would allow it, is_active does not
        self.suspended_admin = User.objects.create_user(
            email="crx@example.com", password="Str0ng!Pass", full_name="CX",
            role=Role.ADMIN, organization=self.org, is_active=False,
        )
        self.rival_admin = User.objects.create_user(
            email="rival@example.com", password="Str0ng!Pass", full_name="R",
            role=Role.ADMIN, organization=self.other_org,
        )
        self.visitor = Visitor.objects.create(
            full_name="Anna", phone="5550001111", organization=self.org
        )
        self.rival_visitor = Visitor.objects.create(
            full_name="Rival Guest", phone="5550009999", organization=self.other_org
        )
        self.existing = Visit.objects.create(
            visitor=self.visitor, organization=self.org, building=self.building,
            host=self.admin, purpose="Initial", visit_date=timezone.localdate(),
        )

    def _login(self, user):
        resp = self.client.post(
            "/api/auth/token/",
            {"email": user.email, "password": "Str0ng!Pass"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        return resp.data["access"]

    def _payload(self, **overrides):
        data = {
            "visitor_id": self.visitor.pk,
            "host": self.admin.pk,
            "building": self.building.pk,
            "purpose": "Client meeting",
            "visit_date": timezone.localdate().isoformat(),
            "expected_arrival": "10:00",
            "expected_exit": "17:00",
        }
        data.update(overrides)
        return data

    def _post(self, user, payload=None):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._login(user)}")
        try:
            return self.client.post("/api/visits/", payload or self._payload(), format="json")
        finally:
            self.client.credentials()

    def _post_as(self, user, payload=None):
        """Force-authenticate (for users that cannot obtain a token)."""
        self.client.force_authenticate(user=user)
        try:
            return self.client.post("/api/visits/", payload or self._payload(), format="json")
        finally:
            self.client.force_authenticate(user=None)

    def _register_payload(self, phone="5550001111", **visit):
        data = {
            "purpose": "Client meeting",
            "host": self.admin.pk,
            "building": self.building.pk,
            "expected_arrival": "10:00",
            "expected_exit": "17:00",
        }
        data.update(visit)
        return {
            "visitor": {"full_name": "Anna", "phone": phone},
            "visit": data,
        }

    def _domain_post(self, endpoint, user, payload=None):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._login(user)}")
        try:
            return self.client.post(
                endpoint, payload or self._register_payload(), format="json"
            )
        finally:
            self.client.credentials()

    # ---- the route is gone ------------------------------------------

    def test_admin_post_is_405_and_creates_nothing(self):
        before = Visit.objects.count()
        resp = self._post(self.admin)
        self.assertEqual(resp.status_code, 405, resp.content)
        self.assertEqual(Visit.objects.count(), before)
        self.assertFalse(AuditLog.objects.filter(action="Visit registered").exists())

    def test_every_role_is_405_and_creates_nothing(self):
        # RBAC used to be irrelevant here: the route never consulted it.
        for user in (self.admin, self.receptionist, self.security, self.rival_admin):
            with self.subTest(role=user.role, org=user.organization.slug):
                before = Visit.objects.count()
                resp = self._post(user)
                self.assertEqual(resp.status_code, 405, resp.content)
                self.assertEqual(Visit.objects.count(), before)

    def test_suspended_admin_is_405_and_creates_nothing(self):
        before = Visit.objects.count()
        resp = self._post_as(self.suspended_admin)
        self.assertEqual(resp.status_code, 405, resp.content)
        self.assertEqual(Visit.objects.count(), before)

    def test_unauthenticated_post_is_rejected(self):
        resp = self.client.post("/api/visits/", self._payload(), format="json")
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(Visit.objects.count(), 1)

    def test_405_points_at_the_domain_endpoints(self):
        resp = self._post(self.admin)
        self.assertEqual(resp.status_code, 405)
        self.assertIn("/api/visits/register/", resp.data["detail"])
        self.assertIn("/api/visits/walkin/", resp.data["detail"])

    def test_405_response_does_not_advertise_post(self):
        resp = self._post(self.admin)
        self.assertNotIn("POST", resp.get("Allow", ""))

    def test_cannot_bypass_through_a_foreign_visitor_id(self):
        before = Visit.objects.count()
        resp = self._post(self.admin, self._payload(visitor_id=self.rival_visitor.pk))
        self.assertEqual(resp.status_code, 405)
        self.assertEqual(Visit.objects.count(), before)
        self.assertFalse(Visit.objects.filter(visitor=self.rival_visitor).exists())

    def test_cannot_bypass_through_a_foreign_building(self):
        before = Visit.objects.count()
        resp = self._post(self.admin, self._payload(building=self.rival_building.pk))
        self.assertEqual(resp.status_code, 405)
        self.assertEqual(Visit.objects.count(), before)

    def test_cannot_bypass_with_an_empty_or_nonsense_body(self):
        for payload in ({}, {"purpose": ""}, {"status": "APPROVED"}, {"organization": self.other_org.pk}):
            with self.subTest(payload=payload):
                before = Visit.objects.count()
                resp = self._post(self.admin, payload)
                self.assertEqual(resp.status_code, 405, resp.content)
                self.assertEqual(Visit.objects.count(), before)

    def test_serializer_cannot_persist_a_visit_on_its_own(self):
        # defence in depth: even handed a full, valid body the read-only
        # serializer yields no writable data, and a visit cannot exist without
        # a visitor, so the old "just write the model" shortcut is gone.
        serializer = VisitSerializer(data=self._payload())
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data, {})
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                Visit.objects.create(
                    **serializer.validated_data,
                    organization=self.org,
                    created_by=self.admin,
                )
        self.assertEqual(Visit.objects.count(), 1)

    # ---- the domain endpoints still work -----------------------------

    def test_register_endpoint_creates_a_pending_visit(self):
        resp = self._domain_post("/api/visits/register/", self.admin)
        self.assertEqual(resp.status_code, 201, resp.content)
        visit = Visit.objects.get(pk=resp.data["visit"]["id"])
        self.assertEqual(visit.status, VisitStatus.PENDING)
        self.assertEqual(visit.organization, self.org)
        self.assertEqual(visit.visitor, self.visitor)
        self.assertEqual(visit.created_by, self.admin)

    def test_walkin_endpoint_creates_an_approved_visit(self):
        resp = self._domain_post(
            "/api/visits/walkin/", self.admin,
            self._register_payload(phone="5550007777", purpose="Site visit"),
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        visit = Visit.objects.get(pk=resp.data["visit"]["id"])
        self.assertEqual(visit.status, VisitStatus.APPROVED)
        self.assertIsNotNone(visit.qr_pass)

    # ---- reads are untouched -----------------------------------------

    def test_list_and_retrieve_still_work(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._login(self.admin)}")
        try:
            listing = self.client.get("/api/visits/")
            self.assertEqual(listing.status_code, 200, listing.content)
            self.assertEqual(listing.data["count"], 1)
            detail = self.client.get(f"/api/visits/{self.existing.pk}/")
            self.assertEqual(detail.status_code, 200, detail.content)
            self.assertEqual(detail.data["visitor"]["id"], self.visitor.pk)
        finally:
            self.client.credentials()

    def test_list_is_still_tenant_scoped(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._login(self.rival_admin)}")
        try:
            listing = self.client.get("/api/visits/")
            self.assertEqual(listing.status_code, 200, listing.content)
            self.assertEqual(listing.data["count"], 0)
            self.assertEqual(
                self.client.get(f"/api/visits/{self.existing.pk}/").status_code, 404
            )
        finally:
            self.client.credentials()


class VisitCreationEndpointSecurityTests(APITestCase):
    """The only two ways to create a visit, fully guarded (F2 remediation).

    Each control that the old generic ``POST /api/visits/`` skipped is asserted
    here against ``/api/visits/register/`` and ``/api/visits/walkin/``:
    RBAC, registration throttling, organization/ownership validation, purpose
    validation and the audit trail.
    """

    ENDPOINTS = ("/api/visits/register/", "/api/visits/walkin/")

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.org = Organization.objects.create(name="Guard Co", slug="guard-co")
        self.other_org = Organization.objects.create(name="Outsider Co", slug="outsider-co")
        self.building = Building.objects.create(organization=self.org, name="Main", floors=2)
        self.admin = User.objects.create_user(
            email="admin@guard.co", password="Str0ng!Pass", full_name="Admin",
            role=Role.ADMIN, organization=self.org,
        )
        self.receptionist = User.objects.create_user(
            email="reception@guard.co", password="Str0ng!Pass", full_name="Reception",
            role=Role.RECEPTIONIST, organization=self.org,
        )
        # SECURITY has scan/check-in rights but no `create_visitor`
        self.security = User.objects.create_user(
            email="security@guard.co", password="Str0ng!Pass", full_name="Security",
            role=Role.SECURITY, organization=self.org,
        )
        self.outsider = User.objects.create_user(
            email="outsider@other.co", password="Str0ng!Pass", full_name="Outsider",
            role=Role.ADMIN, organization=self.other_org,
        )
        self.foreign_building = Building.objects.create(
            organization=self.other_org, name="Foreign", floors=1
        )

    def _login(self, user):
        resp = self.client.post(
            "/api/auth/token/",
            {"email": user.email, "password": "Str0ng!Pass"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        return resp.data["access"]

    def _as(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._login(user)}")
        self.addCleanup(self.client.credentials)

    def _payload(self, phone="9911000001", **visit):
        data = {
            "purpose": "Client meeting",
            "host": self.admin.pk,
            "building": self.building.pk,
            "expected_arrival": "10:00",
            "expected_exit": "17:00",
        }
        data.update(visit)
        return {
            "visitor": {"full_name": "Guarded Guest", "phone": phone},
            "visit": data,
        }

    def _post(self, endpoint, user, payload=None):
        self._as(user)
        return self.client.post(endpoint, payload or self._payload(), format="json")

    # ---- RBAC: create_visitor is ADMIN / RECEPTIONIST only ------------

    def test_security_role_cannot_register(self):
        for endpoint in self.ENDPOINTS:
            with self.subTest(endpoint=endpoint):
                resp = self._post(endpoint, self.security)
                self.assertEqual(resp.status_code, 403, resp.content)
        self.assertEqual(Visit.objects.count(), 0)
        self.assertEqual(Visitor.objects.count(), 0)

    def test_outsider_admin_cannot_register_into_another_tenant(self):
        # the payload names Guard Co's host/building on purpose: the request
        # must be rejected outright rather than silently re-targeted
        for endpoint in self.ENDPOINTS:
            with self.subTest(endpoint=endpoint):
                resp = self._post(endpoint, self.outsider)
                self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(Visit.objects.count(), 0)

        # with its own host it succeeds, for its own org only
        for endpoint in self.ENDPOINTS:
            with self.subTest(endpoint=endpoint, own_host=True):
                resp = self._post(
                    endpoint, self.outsider,
                    self._payload(phone="9944000001", host=self.outsider.pk, building=None),
                )
                self.assertEqual(resp.status_code, 201, resp.content)
                visit = Visit.objects.get(pk=resp.data["visit"]["id"])
                self.assertEqual(visit.organization, self.other_org)
        self.assertFalse(Visit.objects.filter(organization=self.org).exists())

    def test_admin_and_receptionist_may_register(self):
        combos = [
            (user, endpoint)
            for user in (self.admin, self.receptionist)
            for endpoint in self.ENDPOINTS
        ]
        for index, (user, endpoint) in enumerate(combos):
            with self.subTest(user=user.role, endpoint=endpoint):
                resp = self._post(endpoint, user, self._payload(phone=f"9911{index:06d}"))
                self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(Visit.objects.count(), len(combos))

    def test_unauthenticated_cannot_register(self):
        for endpoint in self.ENDPOINTS:
            with self.subTest(endpoint=endpoint):
                resp = self.client.post(endpoint, self._payload(), format="json")
                self.assertEqual(resp.status_code, 401)
        self.assertEqual(Visit.objects.count(), 0)

    # ---- throttling: 10 registrations/min/IP --------------------------

    def test_register_endpoint_is_throttled_after_ten_per_minute(self):
        for index in range(10):
            resp = self._post("/api/visits/register/", self.admin, self._payload(phone=f"9912{index:06d}"))
            self.assertEqual(resp.status_code, 201, resp.content)
        throttled = self._post("/api/visits/register/", self.admin)
        self.assertEqual(throttled.status_code, 429)
        self.assertIn("throttled", str(throttled.data.get("detail", "")).lower())
        # the rejected request created nothing
        self.assertEqual(Visit.objects.count(), 10)

    def test_walkin_endpoint_is_throttled_after_ten_per_minute(self):
        for index in range(10):
            resp = self._post("/api/visits/walkin/", self.admin, self._payload(phone=f"9913{index:06d}"))
            self.assertEqual(resp.status_code, 201, resp.content)
        throttled = self._post("/api/visits/walkin/", self.admin)
        self.assertEqual(throttled.status_code, 429)
        self.assertEqual(Visit.objects.count(), 10)

    def test_removed_generic_endpoint_is_never_throttled_because_it_never_runs(self):
        for index in range(15):
            resp = self._post("/api/visits/", self.admin, self._payload(phone=f"9914{index:06d}"))
            self.assertEqual(resp.status_code, 405)
        self.assertEqual(Visit.objects.count(), 0)

    # ---- validation is applied before anything is persisted -----------

    def test_cross_org_host_is_rejected(self):
        for endpoint in self.ENDPOINTS:
            with self.subTest(endpoint=endpoint):
                resp = self._post(
                    endpoint, self.admin, self._payload(host=self.outsider.pk)
                )
                self.assertEqual(resp.status_code, 400, resp.content)
                self.assertIn("host", str(resp.data).lower())
        self.assertEqual(Visit.objects.count(), 0)

    def test_cross_org_building_is_rejected(self):
        for endpoint in self.ENDPOINTS:
            with self.subTest(endpoint=endpoint):
                resp = self._post(
                    endpoint, self.admin, self._payload(building=self.foreign_building.pk)
                )
                self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(Visit.objects.count(), 0)

    def test_missing_purpose_is_rejected(self):
        for endpoint in self.ENDPOINTS:
            with self.subTest(endpoint=endpoint):
                resp = self._post(endpoint, self.admin, self._payload(purpose=""))
                self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(Visit.objects.count(), 0)

    def test_overlong_purpose_is_rejected(self):
        resp = self._post("/api/visits/register/", self.admin, self._payload(purpose="x" * 201))
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(Visit.objects.count(), 0)

    def test_inverted_time_window_is_rejected(self):
        resp = self._post(
            "/api/visits/register/", self.admin,
            self._payload(expected_arrival="17:00", expected_exit="10:00"),
        )
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(Visit.objects.count(), 0)

    def test_organization_cannot_be_injected(self):
        payload = self._payload()
        payload["visit"]["organization"] = self.other_org.pk
        payload["visit"]["status"] = VisitStatus.APPROVED
        payload["visit"]["created_by"] = self.outsider.pk
        resp = self._post("/api/visits/register/", self.admin, payload)
        self.assertEqual(resp.status_code, 201, resp.content)
        visit = Visit.objects.get(pk=resp.data["visit"]["id"])
        self.assertEqual(visit.organization, self.org)
        self.assertEqual(visit.created_by, self.admin)
        self.assertEqual(visit.status, VisitStatus.PENDING)

    # ---- audit trail --------------------------------------------------

    def test_register_endpoint_writes_an_audit_entry(self):
        resp = self._post("/api/visits/register/", self.admin)
        self.assertEqual(resp.status_code, 201, resp.content)
        visit = Visit.objects.get(pk=resp.data["visit"]["id"])
        entry = AuditLog.objects.filter(
            action="Visit registered", user=self.admin, entity_id=str(visit.visit_id)
        )
        self.assertEqual(entry.count(), 1, "register must be audited")

    def test_walkin_endpoint_audits_registration_and_approval(self):
        resp = self._post("/api/visits/walkin/", self.admin)
        self.assertEqual(resp.status_code, 201, resp.content)
        visit = Visit.objects.get(pk=resp.data["visit"]["id"])
        for action in ("Visit registered", "Visit approved"):
            with self.subTest(action=action):
                self.assertTrue(
                    AuditLog.objects.filter(
                        action=action, user=self.admin, entity_id=str(visit.visit_id)
                    ).exists(),
                    f"walk-in must audit {action!r}",
                )

    def test_rejected_registration_is_not_audited_as_created(self):
        resp = self._post("/api/visits/register/", self.admin, self._payload(host=self.outsider.pk))
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(AuditLog.objects.filter(action="Visit registered").exists())

    def test_forbidden_role_creates_no_audit_entry(self):
        resp = self._post("/api/visits/register/", self.security)
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(AuditLog.objects.filter(action="Visit registered").exists())


class ConcurrentBookingRaceTests(TransactionTestCase):
    """Two public bookings for the same host and slot, submitted at the same instant.

    Why this is a ``TransactionTestCase`` and not an ``APITestCase``:

    ``APITestCase`` (via ``TestCase``) wraps every test in a transaction that is
    rolled back. A worker thread gets its own connection and therefore its own
    transaction, so it cannot see rows the test created but has not committed.
    The thread's ``Organization.objects.get(pk=...)`` raised ``DoesNotExist``,
    the ``except`` branch appended that exception to ``outcomes``, and
    ``bool(exception)`` is ``True`` -- so two *crashed* threads were
    indistinguishable from two *successful* bookings and the assertion
    ``sorted(bool(o) for o in outcomes) == [False, True]`` passed for the wrong
    reason on any backend that ran it. On SQLite it skipped, so the flaw sat
    unnoticed.

    ``TransactionTestCase`` commits, so the workers see the fixtures and the
    ``select_for_update`` on the host row in ``create_pre_booking`` is genuinely
    exercised.

    The assertions also separate "raised" from "returned False". A thread that
    crashed has not lost a race, it failed, and must never be counted as a
    winner.
    """

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.org = Organization.objects.create(
            name="Race Labs", slug="race-labs",
            working_hours_start="09:00", working_hours_end="18:00",
        )
        self.dept = Department.objects.create(organization=self.org, name="Advisory")
        self.host = User.objects.create_user(
            email="amit@race.test", password="Str0ng!Pass",
            full_name="Amit", organization=self.org, is_active=True,
        )
        Employee.objects.create(
            user=self.host, organization=self.org, employee_id="E-RACE-1",
            department=self.dept, designation="Manager",
            status=Employee.Status.ACTIVE,
        )
        self.day = timezone.localdate() + timedelta(days=2)

    def _attempt(self, phone, barrier, outcomes, errors, lock):
        try:
            org = Organization.objects.get(pk=self.org.pk)
            barrier.wait(timeout=15)
            _, ok, _ = create_pre_booking(
                org,
                visitor_data={"full_name": "Rohit Mehta", "phone": phone},
                visit_type=VisitType.INTERVIEW,
                department_id=self.dept.pk,
                host_id=self.host.pk,
                visit_date=self.day.isoformat(),
                expected_arrival="10:00",
                expected_exit="10:30",
                purpose="Technical Interview",
            )
            with lock:
                outcomes.append(ok)
        except Exception as exc:  # pragma: no cover - surfaced as a failure below
            with lock:
                errors.append(f"{type(exc).__name__}: {exc}")
        finally:
            connections.close_all()

    @skipUnless(connection.vendor == "postgresql", "row locking requires PostgreSQL")
    def test_concurrent_bookings_cannot_both_reserve_same_slot(self):
        barrier = threading.Barrier(2)
        outcomes, errors, lock = [], [], threading.Lock()

        threads = [
            threading.Thread(
                target=self._attempt,
                args=(phone, barrier, outcomes, errors, lock),
            )
            for phone in ("7888100091", "7888100092")
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        self.assertFalse(any(t.is_alive() for t in threads), "concurrent threads timed out")
        self.assertEqual(
            errors, [],
            f"a worker must never raise: the host row was not visible to it, or "
            f"the lock deadlocked. {errors}",
        )
        self.assertEqual(len(outcomes), 2, f"both threads must report: {outcomes}")
        self.assertEqual(
            sum(1 for o in outcomes if o), 1,
            f"exactly one submission may win the slot; outcomes={outcomes}",
        )
        self.assertEqual(
            Visit.objects.filter(host=self.host, visit_date=self.day).count(), 1,
            "exactly one visit may exist for this host and date",
        )

    def _book_one(self, phone):
        """Book the shared slot once, in this thread's connection."""
        org = Organization.objects.get(pk=self.org.pk)
        return create_pre_booking(
            org,
            visitor_data={"full_name": "Rohit Mehta", "phone": phone},
            visit_type=VisitType.INTERVIEW,
            department_id=self.dept.pk,
            host_id=self.host.pk,
            visit_date=self.day.isoformat(),
            expected_arrival="10:00",
            expected_exit="10:30",
            purpose="Technical Interview",
        )

    def test_a_second_booking_for_the_same_slot_is_refused(self):
        """Sequential proof of the invariant the race test contends.

        If this fails, the locking is not the problem -- the slot was never
        exclusive. Keeping it separate means a failure in the threaded test can
        be read as a locking regression rather than a broken conflict check.
        """
        _, first_ok, _ = self._book_one("7888100071")
        _, second_ok, second_msg = self._book_one("7888100072")
        self.assertTrue(first_ok)
        self.assertFalse(second_ok)
        self.assertIn("no longer available", str(second_msg))
        self.assertEqual(
            Visit.objects.filter(host=self.host, visit_date=self.day).count(), 1,
        )


class ConcurrentRescheduleRaceTests(TransactionTestCase):
    """Two visitors move their bookings into the same empty slot at once.

    See ``ConcurrentBookingRaceTests`` for why this is a ``TransactionTestCase``.
    ``reschedule_visit`` locks the host row and re-checks the target slot, so
    exactly one of the two moves may succeed.

    ``client_class`` is overridden because the default for
    ``TransactionTestCase`` is Django's ``Client``, which has no
    ``format="json"``. It treats that keyword as an HTTP header and
    form-encodes the body, so a nested payload such as ``{"visitor": {...}}``
    reaches the view empty and the endpoint reports a missing field rather than
    the real problem. ``APITestCase`` uses DRF's ``APIClient``, which is why the
    identical payload works there.
    """

    client_class = APIClient

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.org = Organization.objects.create(
            name="Race Co", slug="race-co",
            working_hours_start="09:00", working_hours_end="18:00",
        )
        self.dept = Department.objects.create(organization=self.org, name="Advisory")
        self.host = User.objects.create_user(
            email="host@race.test", password="Str0ng!Pass",
            full_name="Host", role=Role.ADMIN, organization=self.org, is_active=True,
        )
        Employee.objects.create(
            user=self.host, organization=self.org, employee_id="E-RACE-2",
            department=self.dept, designation="Lead",
            status=Employee.Status.ACTIVE,
        )
        self.today = timezone.localdate()
        self.day1 = self.today + timedelta(days=5)
        self.day3 = self.today + timedelta(days=7)

    def _book(self, phone, start, end):
        resp = self.client.post(
            "/api/public/booking/race-co/",
            {
                "visitor": {"full_name": "Race Guest", "phone": phone},
                "visit_type": VisitType.CLIENT_MEETING,
                "department": self.dept.pk,
                "host": self.host.pk,
                "visit_date": self.day1.isoformat(),
                "expected_arrival": start,
                "expected_exit": end,
                "purpose": "Client Meeting",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        return Visit.objects.get(visit_id=resp.data["booking"]["visit_id"])


    def _attempt(self, session, visit, barrier, outcomes, errors, lock):
        try:
            barrier.wait(timeout=15)
            _, ok, _ = reschedule_visit(
                session,
                visit.pk,
                new_date=self.day3.isoformat(),
                expected_arrival="12:00",
                expected_exit="12:30",
            )
            with lock:
                outcomes.append(ok)
        except Exception as exc:  # pragma: no cover - surfaced as a failure below
            with lock:
                errors.append(f"{type(exc).__name__}: {exc}")
        finally:
            connections.close_all()

    @skipUnless(connection.vendor == "postgresql", "row locking requires PostgreSQL")
    def test_concurrent_conflicting_reschedules_serialize(self):
        mine = self._book("4200000001", "10:00", "10:30")
        theirs = self._book("4200000002", "11:00", "11:30")
        mine.refresh_from_db()
        theirs.refresh_from_db()
        my_session = self._session(mine)
        their_session = self._session(theirs)

        barrier = threading.Barrier(2)
        outcomes, errors, lock = [], [], threading.Lock()
        threads = [
            threading.Thread(
                target=self._attempt,
                args=(session, visit, barrier, outcomes, errors, lock),
            )
            for session, visit in ((my_session, mine), (their_session, theirs))
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        self.assertFalse(any(t.is_alive() for t in threads), "concurrent threads timed out")
        self.assertEqual(errors, [], f"a worker must never raise: {errors}")
        self.assertEqual(len(outcomes), 2, f"both threads must report: {outcomes}")
        self.assertEqual(
            sum(1 for o in outcomes if o), 1,
            f"exactly one reschedule may claim the target slot; outcomes={outcomes}",
        )
        self.assertEqual(
            Visit.objects.filter(
                host=self.host,
                visit_date=self.day3,
                status__in=[VisitStatus.PENDING, VisitStatus.APPROVED],
            ).count(),
            1,
            "the shared target slot must hold exactly one visit",
        )


class ConcurrentWorkspaceSlugRaceTests(TransactionTestCase):
    """Two workspaces with the same name, created at the same instant.

    The slug used to be chosen by asking the database whether it was free and
    then inserting it. That is check-then-act against a unique column: both
    threads could see the same free slug, and the loser's IntegrityError
    propagated out of the serializer as an unhandled 500 on a request that
    would otherwise have succeeded with a suffixed slug.

    TransactionTestCase because the worker threads need committed fixtures and
    their own connections -- see ConcurrentBookingRaceTests for the full
    argument. The interesting part here has no fixtures at all, which is the
    point: two independent signups collide without sharing anything.
    """

    def _create_workspace(self, name, barrier, slugs, errors, lock):
        try:
            barrier.wait(timeout=15)
            serializer = OrganizationCreateSerializer(data={"name": name})
            if not serializer.is_valid():
                with lock:
                    errors.append(f"invalid: {serializer.errors}")
                return
            serializer.save()
            with lock:
                slugs.append(serializer.instance.slug)
        except Exception as exc:  # pragma: no cover - surfaced as a failure below
            with lock:
                errors.append(f"{type(exc).__name__}: {exc}")
        finally:
            connections.close_all()

    @skipUnless(connection.vendor == "postgresql", "unique index races require PostgreSQL")
    def test_concurrent_workspace_creation_yields_two_distinct_slugs(self):
        barrier = threading.Barrier(2)
        slugs, errors, lock = [], [], threading.Lock()
        threads = [
            threading.Thread(
                target=self._create_workspace,
                args=("Race Co", barrier, slugs, errors, lock),
            )
            for _ in range(2)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        self.assertFalse(any(t.is_alive() for t in threads), "threads timed out")
        self.assertEqual(errors, [], f"neither signup may fail: {errors}")
        self.assertEqual(len(slugs), 2, f"both signups must succeed: {slugs}")
        self.assertEqual(
            len(set(slugs)), 2,
            f"the two workspaces must hold different slugs, got {slugs}",
        )
        self.assertEqual(
            Organization.objects.filter(slug__startswith="race-co").count(), 2,
        )


class MediaServingTests(TestCase):
    """The /media/ machinery must serve MEDIA_ROOT and nothing outside it."""

    def _root(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        (root / "photo.png").write_bytes(b"\x89PNG\r\n\x1a\npayload")
        (root / "sub").mkdir()
        return root

    def test_serves_a_file_inside_document_root(self):
        root = self._root()
        request = RequestFactory().get("/media/photo.png")
        response = serve(request, "photo.png", document_root=str(root))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"\x89PNG\r\n\x1a\npayload")
        self.assertEqual(response["Content-Type"], "image/png")

    def test_dotdot_cannot_escape_document_root(self):
        root = self._root()
        secret = root.parent / "escaped-secret.txt"
        try:
            secret.write_text("do not serve")
            request = RequestFactory().get("/media/../escaped-secret.txt")
            # serve refuses traversal via safe_join and raises
            # SuspiciousFileOperation, which Django's request handler converts
            # into an HTTP 400 -- the file is never reachable, just not with
            # the 404 a browser would expect for a missing file.
            with self.assertRaises(SuspiciousFileOperation):
                serve(request, "../escaped-secret.txt", document_root=str(root))
        finally:
            secret.unlink(missing_ok=True)

    def test_directory_listing_is_off(self):
        root = self._root()
        request = RequestFactory().get("/media/")
        # show_indexes defaults to False, so an index request raises Http404,
        # which the request handler turns into a 404 response.
        with self.assertRaises(Http404):
            serve(request, "", document_root=str(root))


class ProductionMediaRouteTests(TestCase):
    """config/urls must register the scoped media route under production settings.

    urlpatterns are evaluated at module import under whatever settings were
    current then -- during tests that is ENVIRONMENT=development, so the
    production branch would sit unexercised forever. The module is loaded again
    under a fresh name with production settings: that exercises the branch
    without mutating the already-imported module, which Django's URL resolver
    caches as soon as the test runner starts.
    """

    def _production_urlconf(self):
        spec = importlib.util.spec_from_file_location(
            "production_urls_check", config_urls.__file__
        )
        module = importlib.util.module_from_spec(spec)
        with override_settings(ENVIRONMENT="production", DEBUG=False):
            spec.loader.exec_module(module)
        return module

    def test_production_serves_media_and_never_private_media(self):
        prod = self._production_urlconf()
        self.assertIs(resolve("/media/photo.png", urlconf=prod).func, serve)
        with self.assertRaises(Resolver404):
            resolve("/private_media/scan.png", urlconf=prod)

    def test_development_urlconf_has_no_media_route(self):
        patterns = [str(p.pattern) for p in config_urls.urlpatterns]
        self.assertNotIn("media/<path:path>", patterns)
