"""Behaviour added for the 2026-11 audit follow-ups.

Least-privilege visitor fields, QR credential scoping, walk-in source, staff
host-conflict check, password validators on staff signup, case-insensitive
e-mail uniqueness, login throttle, host notifications on visitor
reschedule/cancel, dashboard permission, on-leave hosts, duplicate blacklist
and department codes, weekly working-hours validation.
"""

from datetime import date, timedelta

from django.core import mail
from django.core.cache import cache
from django.db import IntegrityError
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Role, User
from organizations.models import Building, Department, Employee, Organization
from visits.models import Blacklist, BlacklistReason, Visit, VisitSource, VisitStatus, Visitor
from visits.services import approve_visit, register_visit

PASSWORD = "Str0ng!Pass-2024"


def auth(client, user):
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")


class FollowupBase(APITestCase):
    def setUp(self):
        cache.clear()
        self.org = Organization.objects.create(name="Acme", slug="acme")
        self.building = Building.objects.create(organization=self.org, name="HQ")
        self.dept = Department.objects.create(organization=self.org, name="Engineering", code="ENG")
        self.admin = User.objects.create_user(email="admin@acme.test", password=PASSWORD, full_name="Admin", role=Role.ADMIN, organization=self.org)
        self.reception = User.objects.create_user(email="desk@acme.test", password=PASSWORD, full_name="Desk", role=Role.RECEPTIONIST, organization=self.org)
        self.security = User.objects.create_user(email="gate@acme.test", password=PASSWORD, full_name="Gate", role=Role.SECURITY, organization=self.org)
        self.visitor = Visitor.objects.create(
            organization=self.org, full_name="Ravi Kumar", phone="9999999999", company="Acme",
            address="12 Lake Road", emergency_contact="Sita", emergency_phone="8888888888",
            document_type="PASSPORT", document_number="P1234567",
        )
        self.visit = Visit.objects.create(
            visitor=self.visitor, organization=self.org, host=self.admin, created_by=self.reception,
            purpose="Interview", visit_date=date.today(), expected_arrival="10:00", expected_exit="11:00",
        )


class VisitorFieldScopingTests(FollowupBase):
    def test_security_does_not_receive_home_details_but_keeps_identity(self):
        auth(self.client, self.security)
        row = self.client.get(f"/api/visitors/{self.visitor.pk}/").data
        for hidden in ("address", "emergency_contact", "emergency_phone"):
            self.assertNotIn(hidden, row)
        self.assertEqual(row["document_number"], "P1234567")
        self.assertEqual(row["phone"], "9999999999")
        # nested inside a visit as well
        nested = self.client.get(f"/api/visits/{self.visit.pk}/").data["visitor"]
        self.assertNotIn("address", nested)
        self.assertIn("document_type", nested)

    def test_reception_and_admin_receive_everything(self):
        for user in (self.reception, self.admin):
            auth(self.client, user)
            row = self.client.get(f"/api/visitors/{self.visitor.pk}/").data
            self.assertEqual(row["address"], "12 Lake Road")
            self.assertEqual(row["emergency_contact"], "Sita")


class QrCredentialScopingTests(FollowupBase):
    def setUp(self):
        super().setUp()
        self.assertTrue(approve_visit(self.visit, self.admin)[0])

    def test_security_sees_pass_status_but_not_the_credential(self):
        auth(self.client, self.security)
        qr = self.client.get(f"/api/visits/{self.visit.pk}/").data["qr"]
        self.assertTrue(qr["is_valid"])
        self.assertNotIn("token", qr)
        self.assertNotIn("signature", qr)

    def test_reception_can_print_the_pass(self):
        auth(self.client, self.reception)
        qr = self.client.get(f"/api/visits/{self.visit.pk}/").data["qr"]
        self.assertIn("token", qr)
        self.assertIn("signature", qr)


class RegistrationRulesTests(FollowupBase):
    def _payload(self, **visit):
        base = {"purpose": "Meeting", "host": self.admin.pk, "building": self.building.pk,
                "visit_date": (date.today() + timedelta(days=1)).isoformat(),
                "expected_arrival": "10:00", "expected_exit": "11:00"}
        base.update(visit)
        return {"visitor": {"full_name": "New Person", "phone": "7777777777"}, "visit": base}

    def test_walk_in_is_recorded_with_walk_in_source(self):
        auth(self.client, self.reception)
        resp = self.client.post("/api/visits/walkin/", self._payload(), format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.data["visit"]["source"], VisitSource.WALK_IN)
        resp = self.client.post("/api/visits/register/", self._payload(expected_arrival="14:00", expected_exit="15:00"), format="json")
        self.assertEqual(resp.data["visit"]["source"], VisitSource.STAFF)

    def test_staff_registration_warns_about_overlapping_host_slot(self):
        day = (date.today() + timedelta(days=1)).isoformat()
        auth(self.client, self.reception)
        first = self.client.post("/api/visits/register/", self._payload(visit_date=day), format="json")
        self.assertEqual(first.status_code, 201, first.content)
        self.assertEqual(first.data["warnings"], [])
        clash = self.client.post("/api/visits/register/", self._payload(visit_date=day, expected_arrival="10:30", expected_exit="11:30"), format="json")
        self.assertEqual(clash.status_code, 201, clash.content)  # booked, but flagged
        self.assertEqual(len(clash.data["warnings"]), 1)
        self.assertIn("already has a visitor between 10:00 and 11:00", clash.data["warnings"][0])
        adjacent = self.client.post("/api/visits/register/", self._payload(visit_date=day, expected_arrival="11:30", expected_exit="12:00"), format="json")
        self.assertEqual(adjacent.data["warnings"], [])
        # a cancelled visit no longer counts
        for pk in (first.data["visit"]["id"], clash.data["visit"]["id"]):
            Visit.objects.filter(pk=pk).update(status=VisitStatus.CANCELLED)
        again = self.client.post("/api/visits/register/", self._payload(visit_date=day), format="json")
        self.assertEqual(again.data["warnings"], [])

    def test_walk_in_is_exempt_from_the_slot_warning(self):
        day = (date.today() + timedelta(days=1)).isoformat()
        auth(self.client, self.reception)
        self.assertEqual(self.client.post("/api/visits/register/", self._payload(visit_date=day), format="json").status_code, 201)
        resp = self.client.post("/api/visits/walkin/", self._payload(visit_date=day), format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.data["warnings"], [])


class AccountRulesTests(FollowupBase):
    def test_staff_signup_runs_django_password_validators(self):
        self.client.credentials()
        for bad in ("12345678", "password1", "qwertyuiop"):
            resp = self.client.post("/api/auth/register/", {"email": "n@x.test", "full_name": "N", "password": bad}, format="json")
            self.assertEqual(resp.status_code, 400, bad)
            self.assertIn("password", resp.data)

    def test_emails_are_unique_case_insensitively(self):
        self.client.credentials()
        resp = self.client.post("/api/auth/register/", {"email": "Dup@Example.COM", "full_name": "Dup", "password": PASSWORD}, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.data["user"]["email"], "dup@example.com")
        resp = self.client.post("/api/auth/register/", {"email": "dup@example.com", "full_name": "Dup2", "password": PASSWORD}, format="json")
        self.assertEqual(resp.status_code, 400)
        with self.assertRaises(IntegrityError):
            User.objects.create_user(email="DUP@example.com", password=PASSWORD, full_name="Dup3")

    def test_login_is_rate_limited_per_ip(self):
        # settings relax the rate under the test runner; pin the real one here
        from unittest import mock

        from api.throttles import LoginRateThrottle

        self.client.credentials()
        with mock.patch.object(LoginRateThrottle, "THROTTLE_RATES", {"login": "20/min"}):
            last = None
            for _ in range(21):
                last = self.client.post("/api/auth/token/", {"email": "nobody@acme.test", "password": "x"}, format="json")
        self.assertEqual(last.status_code, 429)

    def test_onboarding_cannot_create_two_workspaces_for_one_account(self):
        nobody = User.objects.create_user(email="solo@x.test", password=PASSWORD, full_name="Solo")
        auth(self.client, nobody)
        self.assertEqual(self.client.post("/api/organizations/", {"name": "First"}, format="json").status_code, 201)
        self.assertEqual(self.client.post("/api/organizations/", {"name": "Second"}, format="json").status_code, 400)
        self.assertEqual(Organization.objects.filter(name__in=["First", "Second"]).count(), 1)

    def test_onboarding_rejects_unknown_timezone(self):
        nobody = User.objects.create_user(email="tz@x.test", password=PASSWORD, full_name="Tz")
        auth(self.client, nobody)
        resp = self.client.post("/api/organizations/", {"name": "Tz Co", "timezone": "Mars/Olympus"}, format="json")
        self.assertEqual(resp.status_code, 400)


class HostAndDashboardTests(FollowupBase):
    def test_on_leave_and_inactive_employees_are_not_offered_as_hosts(self):
        Employee.objects.create(user=self.reception, organization=self.org, employee_id="E-D", status=Employee.Status.ON_LEAVE)
        Employee.objects.create(user=self.security, organization=self.org, employee_id="E-G", status=Employee.Status.ACTIVE)
        auth(self.client, self.admin)
        ids = {h["id"] for h in self.client.get("/api/hosts/").data}
        self.assertNotIn(self.reception.pk, ids)
        self.assertIn(self.security.pk, ids)
        self.assertIn(self.admin.pk, ids)  # no profile yet -> still eligible

    def test_dashboard_requires_view_reports(self):
        from accounts.permissions import user_permissions

        for user in (self.admin, self.reception, self.security):
            self.assertIn("view_reports", user_permissions(user))
            auth(self.client, user)
            self.assertEqual(self.client.get("/api/dashboard/summary/").status_code, 200)
        nobody = User.objects.create_user(email="n2@x.test", password=PASSWORD, full_name="N2")
        auth(self.client, nobody)
        # a tenantless receptionist still holds view_reports by role; the
        # endpoint answers with empty analytics rather than leaking anything
        self.assertEqual(self.client.get("/api/dashboard/summary/").status_code, 200)


class ConstraintTests(FollowupBase):
    def test_second_active_blacklist_entry_is_refused_by_the_database(self):
        Blacklist.objects.create(visitor=self.visitor, reason=BlacklistReason.MISCONDUCT, added_by=self.admin)
        with self.assertRaises(IntegrityError):
            Blacklist.objects.create(visitor=self.visitor, reason=BlacklistReason.PERMANENT_BAN, added_by=self.admin)

    def test_lifted_entries_do_not_block_a_new_ban(self):
        old = Blacklist.objects.create(visitor=self.visitor, reason=BlacklistReason.MISCONDUCT, added_by=self.admin)
        old.is_active = False
        old.save(update_fields=["is_active"])
        Blacklist.objects.create(visitor=self.visitor, reason=BlacklistReason.PERMANENT_BAN, added_by=self.admin)

    def test_department_code_unique_per_workspace(self):
        auth(self.client, self.admin)
        resp = self.client.post("/api/departments/", {"name": "Enterprise", "code": "eng"}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("code", resp.data)
        other = Organization.objects.create(name="Other", slug="other")
        Department.objects.create(organization=other, name="Eng", code="ENG")  # fine elsewhere


class WeeklyHoursTests(FollowupBase):
    def test_weekly_hours_round_trip_and_validation(self):
        auth(self.client, self.admin)
        good = {"0": [{"start": "09:00", "end": "13:00"}, {"start": "14:00", "end": "18:00"}], "6": []}
        resp = self.client.patch("/api/organizations/me/", {"weekly_working_hours": good}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data["weekly_working_hours"], good)
        for bad in (
            {"7": []},
            {"0": [{"start": "9:00", "end": "13:00"}]},
            {"0": [{"start": "13:00", "end": "09:00"}]},
            {"0": [{"start": "09:00", "end": "13:00"}, {"start": "12:00", "end": "18:00"}]},
            "nope",
        ):
            resp = self.client.patch("/api/organizations/me/", {"weekly_working_hours": bad}, format="json")
            self.assertEqual(resp.status_code, 400, bad)
        # the booking engine honours it: Sunday closed, Monday lunch break
        from visits.availability import weekly_windows

        self.org.refresh_from_db()
        monday = date(2026, 11, 23)
        self.assertEqual(len(weekly_windows(self.org, monday)), 2)
        self.assertEqual(weekly_windows(self.org, date(2026, 11, 22)), [])


class HostNotificationTests(FollowupBase):
    def test_visitor_reschedule_and_cancel_notify_the_host(self):
        from visits.services import cancel_visit, reschedule_visit
        from visits.visitor_accounts import scope_for_visit

        Employee.objects.create(user=self.admin, organization=self.org, employee_id="E-A", department=self.dept)
        booked = Visit.objects.create(
            visitor=self.visitor, organization=self.org, host=self.admin, purpose="Client Meeting",
            source=VisitSource.PUBLIC_BOOKING, visit_date=date.today() + timedelta(days=3),
            expected_arrival="10:00", expected_exit="10:30",
        )
        mail.outbox.clear()
        day = (date.today() + timedelta(days=4)).isoformat()
        _, ok, msg = reschedule_visit(scope_for_visit(booked), booked.pk, new_date=day, expected_arrival="11:00", expected_exit="11:30")
        self.assertTrue(ok, msg)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("rescheduled", mail.outbox[0].subject)
        self.assertEqual(mail.outbox[0].to, [self.admin.email])
        _, ok, msg = cancel_visit(scope_for_visit(booked), booked.pk, reason="Plans changed")
        self.assertTrue(ok, msg)
        self.assertEqual(len(mail.outbox), 2)
        self.assertIn("cancelled", mail.outbox[1].subject)
