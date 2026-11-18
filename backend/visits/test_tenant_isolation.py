"""Tenant-isolation regression tests for the ``Visitor`` PII boundary.

``Visitor`` is a tenant-owned record: it holds identity-document numbers,
addresses, emergency contacts and internal notes.  Before ``Visitor.organization``
existed, a visitor's identity was deduplicated by phone *globally*, so one
person registered by two workspaces could land on a single shared row that
both workspaces could read -- each one seeing the other's PII.

These tests pin the fixed behaviour:

* one workspace can never read another workspace's visitor PII (API list and
  detail, console pages, blacklist panel, reports, CSV export, visit payloads);
* the same phone number is one identity *per workspace* and two independent
  identities *across* workspaces;
* inside one workspace the pre-existing dedup / blank-field backfill behaviour
  is unchanged;
* ``Visit.organization`` and ``Visitor.organization`` always agree, and visits
  stay attached to the right visitor;
* public booking and the visitor self-service portal keep working, per
  workspace, and stay scoped to the booking organization;
* the data migration attributes, splits and merges legacy rows without
  discarding PII.
"""

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Role
from organizations.models import Department, Employee, Organization
from reports.services import build_dashboard_data
from visits.models import (
    Visit,
    VisitStatus,
    VisitType,
    Visitor,
)
from visits.services import get_or_create_visitor, register_visit

User = get_user_model()

PASSWORD = "Passw0rd!123"
PHONE = "9000000001"
# PII planted on the Alpha visitor; none of it may ever reach Bravo.
ALPHA_PII = {
    "document_type": "AADHAAR",
    "document_number": "AADHAAR-1111-2222",
    "address": "12 Alpha Street",
    "emergency_contact": "Ravi Rao",
    "emergency_phone": "9000000091",
    "special_notes": "Escort required at gate",
}


# ===================================================================== reads


class TenantIsolationTestBase(TestCase):
    """Two organizations, one admin + host each, one Alpha visitor."""

    def setUp(self):
        cache.clear()
        # DRF's client so API calls can post real JSON; it also carries
        # session login, which the console assertions need.
        self.client = APIClient()
        self.today = timezone.localdate()
        self.day1 = self.today + timedelta(days=3)
        self.day2 = self.today + timedelta(days=4)
        self.org_a = Organization.objects.create(
            name="Alpha Works", slug="alpha-works",
            working_hours_start="09:00", working_hours_end="18:00",
        )
        self.org_b = Organization.objects.create(
            name="Bravo Labs", slug="bravo-labs",
            working_hours_start="09:00", working_hours_end="18:00",
        )
        self.admin_a = self._user("alpha@tenant.test", self.org_a)
        self.admin_b = self._user("bravo@tenant.test", self.org_b)
        self.dept_a = Department.objects.create(organization=self.org_a, name="Ops")
        self.dept_b = Department.objects.create(organization=self.org_b, name="Ops")
        self.host_a = self._host("alpha-host@tenant.test", self.org_a, self.dept_a)
        self.host_b = self._host("bravo-host@tenant.test", self.org_b, self.dept_b)

        self.visitor_a = Visitor.objects.create(
            organization=self.org_a, full_name="Asha Rao", phone=PHONE, **ALPHA_PII
        )
        self.visit_a = self._visit(self.visitor_a, self.org_a, self.host_a)

    # ------------------------------------------------------------- helpers

    def _user(self, email, org, role=Role.ADMIN):
        return User.objects.create_user(
            email=email, password=PASSWORD, full_name=email.split("@")[0],
            role=role, organization=org,
        )

    def _host(self, email, org, department):
        user = self._user(email, org, role=Role.RECEPTIONIST)
        Employee.objects.create(
            user=user, organization=org, employee_id=f"E-{abs(hash(email)):x}",
            department=department, designation="Lead", status=Employee.Status.ACTIVE,
        )
        return user

    def _visit(self, visitor, org, host=None, status=VisitStatus.PENDING, purpose="Meeting"):
        return Visit.objects.create(
            visitor=visitor, organization=org, host=host, purpose=purpose,
            status=status, visit_date=self.today,
        )

    def _token(self, user):
        resp = self.client.post(
            "/api/auth/token/",
            {"email": user.email, "password": PASSWORD},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        return resp.data["access"]

    def _api_get(self, user, path):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._token(user)}")
        try:
            return self.client.get(path)
        finally:
            self.client.credentials()

    def _api_post(self, user, path, payload):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._token(user)}")
        try:
            return self.client.post(path, payload, format="json")
        finally:
            self.client.credentials()


    def _register_payload(self, phone=PHONE, name="Asha Rao", purpose="Business meeting"):
        return {
            "visitor": {"full_name": name, "phone": phone},
            "visit": {"purpose": purpose, "expected_arrival": "10:00", "expected_exit": "11:00"},
        }

    def _book_payload(self, slug, phone, name="Booked Guest", host=None, department=None,
                      day=None, start="10:00", end="10:30"):
        in_a = slug == "alpha-works"
        return {
            "visitor": {"full_name": name, "phone": phone},
            "visit_type": VisitType.CLIENT_MEETING,
            "department": (department or (self.dept_a if in_a else self.dept_b)).pk,
            "host": (host or (self.host_a if in_a else self.host_b)).pk,
            "visit_date": (day or self.day1).isoformat(),
            "expected_arrival": start,
            "expected_exit": end,
            "purpose": "Client Meeting",
        }


class CrossTenantReadTests(TenantIsolationTestBase):
    """Requirement: Organization A cannot access Organization B's Visitor PII."""

    def test_api_visitor_list_hides_foreign_visitor(self):
        resp = self._api_get(self.admin_b, "/api/visitors/")
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.content.decode()
        for secret in ALPHA_PII.values():
            self.assertNotIn(secret, body)
        self.assertNotIn("Asha Rao", body)
        self.assertNotIn(self.visitor_a.pk, [r["id"] for r in resp.data["results"]])

    def test_api_visitor_search_cannot_reach_foreign_visitor(self):
        for query in ("Asha", PHONE, "AADHAAR-1111-2222", "Alpha Street"):
            resp = self._api_get(self.admin_b, f"/api/visitors/?q={query}")
            self.assertEqual(resp.status_code, 200, resp.content)
            self.assertEqual(
                resp.data["results"], [], f"search {query!r} leaked a foreign visitor"
            )

    def test_api_visitor_detail_is_404_for_foreign_visitor(self):
        resp = self._api_get(self.admin_b, f"/api/visitors/{self.visitor_a.pk}/")
        self.assertEqual(resp.status_code, 404, resp.content)

    def test_api_visit_detail_does_not_leak_foreign_visitor_pii(self):
        resp = self._api_get(self.admin_a, f"/api/visits/{self.visit_a.pk}/")
        self.assertEqual(resp.status_code, 200, resp.content)
        # the owning organization does see its own PII
        self.assertEqual(resp.data["visitor"]["id"], self.visitor_a.pk)
        self.assertEqual(resp.data["visitor"]["document_number"], ALPHA_PII["document_number"])

        bravo_visitor = Visitor.objects.create(
            organization=self.org_b, full_name="Bravo Guest", phone="9000000002",
            document_number="PASSPORT-7777-6666",
        )
        bravo_visit = self._visit(bravo_visitor, self.org_b, self.host_b, purpose="Bravo meeting")
        resp = self._api_get(self.admin_b, f"/api/visits/{bravo_visit.pk}/")
        self.assertEqual(resp.status_code, 200, resp.content)
        # Bravo's visit resolves to Bravo's visitor, never Alpha's PII
        self.assertEqual(resp.data["visitor"]["id"], bravo_visitor.pk)
        self.assertEqual(resp.data["visitor"]["document_number"], "PASSPORT-7777-6666")
        self.assertNotIn(ALPHA_PII["document_number"], resp.content.decode())
        # and Alpha's visit row is not reachable at all
        blocked = self._api_get(self.admin_b, f"/api/visits/{self.visit_a.pk}/")
        self.assertEqual(blocked.status_code, 404)


    def test_dashboard_and_csv_ignore_foreign_visitors(self):
        self._visit(self.visitor_a, self.org_a, self.host_a, purpose="Second")
        bravo_visitor = Visitor.objects.create(
            organization=self.org_b, full_name="Bravo Guest", phone="9000000002"
        )
        self._visit(bravo_visitor, self.org_b, self.host_b)

        kpis, _ = build_dashboard_data(self.admin_b)
        self.assertEqual(kpis["repeat"], 0, "Bravo must not count Alpha's repeat visits")
        self.assertEqual(kpis["first_time"], 1)

        resp = self._api_get(self.admin_b, "/api/reports/export/?period=all")
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.content.decode("utf-8-sig")
        self.assertIn("Bravo Guest", body)
        self.assertNotIn("Asha Rao", body)
        self.assertNotIn(ALPHA_PII["document_number"], body)


    def test_quarantined_legacy_visitor_is_invisible_to_every_tenant(self):
        legacy = Visitor.objects.create(
            full_name="Legacy Nobody", phone="9000000009", document_number="DOC-LEGACY"
        )
        self.assertIsNone(legacy.organization_id)
        for admin in (self.admin_a, self.admin_b):
            resp = self._api_get(admin, "/api/visitors/")
            self.assertNotIn(legacy.pk, [r["id"] for r in resp.data["results"]])

    def test_generic_visit_create_endpoint_cannot_cross_tenants(self):
        # F2: the generic creation route is gone, so there is no second way to
        # attach another workspace's visitor to a visit.
        payload = {
            "visitor_id": self.visitor_a.pk,
            "host": self.host_b.pk,
            "purpose": "Bravo meeting",
            "visit_date": self.today.isoformat(),
            "expected_arrival": "10:00",
            "expected_exit": "11:00",
        }
        resp = self._api_post(self.admin_b, "/api/visits/", payload)
        self.assertEqual(resp.status_code, 405, resp.content)
        self.assertFalse(Visit.objects.filter(purpose="Bravo meeting").exists())
        # no new visit appeared against the Alpha visitor either
        self.assertEqual(Visit.objects.filter(visitor=self.visitor_a).count(), 1)

    def test_register_endpoint_rejects_foreign_host(self):
        payload = {
            "visitor": {"full_name": "Rival Guest", "phone": "9000000099"},
            "visit": {
                "purpose": "Bravo meeting",
                "host": self.host_a.pk,
                "expected_arrival": "10:00",
                "expected_exit": "11:00",
            },
        }
        resp = self._api_post(self.admin_b, "/api/visits/register/", payload)
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertFalse(Visit.objects.filter(purpose="Bravo meeting").exists())

    def test_register_endpoint_accepts_own_visitor(self):
        payload = {
            "visitor": {"full_name": self.visitor_a.full_name, "phone": self.visitor_a.phone},
            "visit": {
                "purpose": "Alpha meeting",
                "host": self.host_a.pk,
                "expected_arrival": "10:00",
                "expected_exit": "11:00",
            },
        }
        resp = self._api_post(self.admin_a, "/api/visits/register/", payload)
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.data["visit"]["visitor"]["id"], self.visitor_a.pk)
        self.assertEqual(
            Visit.objects.get(pk=resp.data["visit"]["id"]).organization, self.org_a
        )
        # the Alpha document number is echoed only to Alpha
        self.assertEqual(
            resp.data["visit"]["visitor"]["document_number"],
            ALPHA_PII["document_number"],
        )


# ================================================================== dedup rules


class TenantScopedDedupeTests(TenantIsolationTestBase):
    """Requirements: per-org independence, intra-org dedup, visit integrity."""

    def _register(self, user, phone, name, purpose, **visitor_fields):
        return register_visit(
            user,
            visitor_data={"full_name": name, "phone": phone, **visitor_fields},
            purpose=purpose,
            expected_arrival="10:00",
            expected_exit="11:00",
        )

    def test_same_phone_in_two_orgs_creates_two_visitor_rows(self):
        visit_a, ok_a, _ = self._register(
            self.admin_a, PHONE, "Asha Rao", "Business meeting",
            document_number="AADHAAR-1111-2222", address="12 Alpha Street",
        )
        visit_b, ok_b, _ = self._register(
            self.admin_b, PHONE, "Asha Rao", "Client meeting",
            document_number="PASSPORT-9999-8888", company="Bravo Vendor",
        )
        self.assertTrue(ok_a)
        self.assertTrue(ok_b)
        self.assertNotEqual(visit_a.visitor_id, visit_b.visitor_id)
        self.assertEqual(Visitor.objects.filter(phone=PHONE).count(), 2)

        visit_a.visitor.refresh_from_db()
        visit_b.visitor.refresh_from_db()
        self.assertEqual(visit_a.visitor.organization, self.org_a)
        self.assertEqual(visit_b.visitor.organization, self.org_b)
        # PII stays with the organization that supplied it
        self.assertEqual(visit_a.visitor.document_number, "AADHAAR-1111-2222")
        self.assertEqual(visit_b.visitor.document_number, "PASSPORT-9999-8888")
        self.assertEqual(visit_a.visitor.address, "12 Alpha Street")
        self.assertEqual(visit_b.visitor.address, "")

    def test_same_phone_within_one_org_still_deduplicates(self):
        phone = "9000000016"
        first, ok1, _ = self._register(self.admin_a, phone, "Repeat Guest", "Business meeting")
        second, ok2, _ = self._register(self.admin_a, phone, "Repeat Guest", "Client meeting")
        self.assertTrue(ok1)
        self.assertTrue(ok2)
        self.assertEqual(first.visitor_id, second.visitor_id)
        self.assertEqual(Visitor.objects.filter(organization=self.org_a, phone=phone).count(), 1)
        self.assertEqual(Visit.objects.filter(visitor=first.visitor).count(), 2)

    def test_intra_org_dedupe_backfills_blank_fields_only_in_that_org(self):
        self._register(self.admin_a, PHONE, "Asha Rao", "Business meeting")
        self._register(self.admin_b, PHONE, "Asha Rao", "Client meeting")
        # Alpha registers again with a company Alpha never stored before
        self._register(self.admin_a, PHONE, "Asha Rao", "Interview", company="Alpha Vendor")

        alpha = Visitor.objects.get(organization=self.org_a, phone=PHONE)
        bravo = Visitor.objects.get(organization=self.org_b, phone=PHONE)
        self.assertEqual(alpha.company, "Alpha Vendor")
        self.assertEqual(bravo.company, "", "backfill must not cross the tenant boundary")

    def test_get_or_create_visitor_is_tenant_scoped(self):
        alpha, created = get_or_create_visitor(
            self.org_a, full_name="Fresh", phone="9000000008"
        )
        self.assertTrue(created)
        again, created_again = get_or_create_visitor(
            self.org_a, full_name="Fresh", phone="9000000008"
        )
        self.assertFalse(created_again)
        self.assertEqual(alpha.pk, again.pk)

        bravo, created_bravo = get_or_create_visitor(
            self.org_b, full_name="Fresh", phone="9000000008"
        )
        self.assertTrue(created_bravo)
        self.assertNotEqual(alpha.pk, bravo.pk)
        self.assertEqual(bravo.organization, self.org_b)

    def test_concurrent_duplicate_registration_returns_the_winning_row(self):
        # the loser of a race sees the unique constraint fire on insert; it must
        # fall back to the row the winner created instead of 500-ing
        with patch.object(Visitor.objects, "create", side_effect=IntegrityError("race")):
            visitor, created = get_or_create_visitor(
                self.org_a, full_name="Asha Rao", phone=PHONE
            )
        self.assertFalse(created)
        self.assertEqual(visitor.pk, self.visitor_a.pk)

    def test_visitor_data_cannot_smuggle_another_organization(self):
        visit, ok, _ = self._register(
            self.admin_a, "9000000007", "Mallory", "Business meeting",
        )
        self.assertTrue(ok)
        self.assertEqual(visit.visitor.organization, self.org_a)

        smuggled = get_or_create_visitor(
            self.org_a, full_name="Mallory", phone="9000000007",
            **{"organization": self.org_b},
        )[0]
        self.assertEqual(
            smuggled.organization, self.org_a,
            "the tenant key must never be client-writable",
        )

    def test_visit_and_visitor_organization_always_agree(self):
        self._register(self.admin_b, PHONE, "Asha Rao", "Client meeting")
        for visit in Visit.objects.all():
            self.assertEqual(
                visit.visitor.organization_id, visit.organization_id,
                f"visit {visit.pk} crosses the tenant boundary",
            )

    def test_database_constraint_scopes_identity_per_organization(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Visitor.objects.create(
                organization=self.org_a, full_name="Clone", phone=PHONE
            )
        # the same phone in a different organization is perfectly legal
        bravo = Visitor.objects.create(
            organization=self.org_b, full_name="Clone", phone=PHONE
        )
        self.assertEqual(bravo.organization, self.org_b)

    def test_blank_phone_rows_are_allowed_within_one_organization(self):
        first = Visitor.objects.create(organization=self.org_a, full_name="No Phone 1")
        second = Visitor.objects.create(organization=self.org_a, full_name="No Phone 2")
        self.assertNotEqual(first.pk, second.pk)

    def test_deleting_an_organization_removes_its_visitors(self):
        Visitor.objects.create(organization=self.org_b, full_name="Bravo Only", phone="9000000003")
        self.org_b.delete()
        self.assertFalse(Visitor.objects.filter(full_name="Bravo Only").exists())
        self.assertTrue(Visitor.objects.filter(pk=self.visitor_a.pk).exists())


# =========================================================== booking + portal


class BookingAndPortalTenantTests(TenantIsolationTestBase):
    """Requirements: public booking and visitor portal still work, per tenant."""

    def test_public_booking_creates_a_tenant_owned_visitor(self):
        resp = self.client.post(
            "/api/public/booking/alpha-works/",
            self._book_payload("alpha-works", "9000000010"),
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        visit = Visit.objects.get(visit_id=resp.data["booking"]["visit_id"])
        self.assertEqual(visit.organization, self.org_a)
        self.assertEqual(visit.visitor.organization, self.org_a)
        self.assertEqual(visit.visitor.phone, "9000000010")

    def test_public_booking_same_phone_in_two_orgs_stays_separate(self):
        for slug in ("alpha-works", "bravo-labs"):
            resp = self.client.post(
                f"/api/public/booking/{slug}/",
                self._book_payload(slug, "9000000011", name="Same Human"),
                format="json",
            )
            self.assertEqual(resp.status_code, 201, resp.content)
        rows = Visitor.objects.filter(phone="9000000011")
        self.assertEqual(rows.count(), 2)
        self.assertEqual(
            set(rows.values_list("organization_id", flat=True)),
            {self.org_a.pk, self.org_b.pk},
        )


    # ------------------------------------------------------------- helpers

    def _book(self, slug, phone, name="Booked Guest", day=None):
        payload = self._book_payload(slug, phone, name=name, day=day)
        resp = self.client.post(f"/api/public/booking/{slug}/", payload, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        return Visit.objects.get(visit_id=resp.data["booking"]["visit_id"])


# ================================================================== migration


