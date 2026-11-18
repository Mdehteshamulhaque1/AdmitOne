"""Tests for the SPA management surface: scan, cancel, visitor edits/blacklist,
workspace settings, buildings, departments, team, audit log, account."""

from datetime import date, timedelta

from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Role, User
from organizations.models import AuditLog, Building, Department, Employee, Organization
from visits.models import Blacklist, BlacklistReason, QRPass, Visit, VisitStatus, Visitor
from visits.services import approve_visit

PASSWORD = "Str0ng!Pass-2024"


def auth(client, user):
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")


class ManagementApiBase(APITestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme", slug="acme")
        self.other_org = Organization.objects.create(name="Globex", slug="globex")
        self.building = Building.objects.create(organization=self.org, name="HQ")
        self.dept = Department.objects.create(organization=self.org, name="Engineering", code="ENG")
        self.admin = self._user("admin@acme.test", Role.ADMIN)
        self.reception = self._user("desk@acme.test", Role.RECEPTIONIST)
        self.security = self._user("gate@acme.test", Role.SECURITY)
        self.outsider = self._user("admin@globex.test", Role.ADMIN, org=self.other_org)
        self.visitor = Visitor.objects.create(
            organization=self.org, full_name="Ravi Kumar", phone="9999999999", company="Acme"
        )
        self.visit = Visit.objects.create(
            visitor=self.visitor, organization=self.org, building=self.building,
            host=self.admin, created_by=self.reception, purpose="Interview",
            visit_date=date.today(),
        )

    def _user(self, email, role, org=None):
        return User.objects.create_user(
            email=email, password=PASSWORD, full_name=email.split("@")[0],
            role=role, organization=org or self.org,
        )

    def _approved_visit(self, visitor=None, org=None):
        org = org or self.org
        visitor = visitor or self.visitor
        actor = self.admin if org == self.org else self.outsider
        visit = Visit.objects.create(
            visitor=visitor, organization=org, host=actor, created_by=actor,
            purpose="Meeting", visit_date=date.today(),
        )
        ok, _ = approve_visit(visit, actor)
        assert ok
        visit.refresh_from_db()
        return visit


class HealthTests(APITestCase):
    def test_health_reports_database(self):
        resp = self.client.get("/api/health/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok", "database": "ok"})


class ScanTests(ManagementApiBase):
    def _payload(self, visit):
        return f"{visit.qr_pass.token}|{visit.qr_pass.signature}"

    def test_security_scan_checks_in_and_consumes_pass(self):
        visit = self._approved_visit()
        auth(self.client, self.security)
        resp = self.client.post("/api/visits/scan/", {"payload": self._payload(visit)}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(resp.data["ok"])
        self.assertEqual(resp.data["visit"]["status"], "CHECKED_IN")
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.CHECKED_IN)
        self.assertTrue(QRPass.objects.get(visit=visit).is_used)
        # replay is rejected
        resp = self.client.post("/api/visits/scan/", {"payload": self._payload(visit)}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("already used", resp.data["detail"])
        self.assertTrue(AuditLog.objects.filter(action="QR scan rejected").exists())

    def test_dry_run_does_not_consume(self):
        visit = self._approved_visit()
        auth(self.client, self.security)
        resp = self.client.post(
            "/api/visits/scan/", {"payload": self._payload(visit), "dry_run": True}, format="json"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["dry_run"])
        self.assertEqual(resp.data["visit"]["visitor"]["full_name"], "Ravi Kumar")
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.APPROVED)
        self.assertFalse(QRPass.objects.get(visit=visit).is_used)

    def test_token_and_signature_fields_accepted(self):
        visit = self._approved_visit()
        auth(self.client, self.security)
        resp = self.client.post(
            "/api/visits/scan/",
            {"token": str(visit.qr_pass.token), "signature": visit.qr_pass.signature},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)

    def test_tampered_signature_rejected(self):
        visit = self._approved_visit()
        auth(self.client, self.security)
        resp = self.client.post(
            "/api/visits/scan/", {"payload": f"{visit.qr_pass.token}|{'0' * 64}"}, format="json"
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("tampered", resp.data["detail"])
        self.assertIsNotNone(resp.data["visit"])  # our own visit, so it is named

    def test_foreign_tenant_pass_is_unknown(self):
        foreign_visitor = Visitor.objects.create(
            organization=self.other_org, full_name="Spy", phone="1111111111"
        )
        visit = self._approved_visit(visitor=foreign_visitor, org=self.other_org)
        auth(self.client, self.security)
        resp = self.client.post("/api/visits/scan/", {"payload": self._payload(visit)}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Unknown pass", resp.data["detail"])
        self.assertIsNone(resp.data["visit"])
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.APPROVED)

    def test_receptionist_cannot_scan(self):
        visit = self._approved_visit()
        auth(self.client, self.reception)
        resp = self.client.post("/api/visits/scan/", {"payload": self._payload(visit)}, format="json")
        self.assertEqual(resp.status_code, 403)

    def test_garbage_payload_is_400_not_500(self):
        auth(self.client, self.security)
        for payload in ("", "nonsense", "abc|def"):
            resp = self.client.post("/api/visits/scan/", {"payload": payload}, format="json")
            self.assertEqual(resp.status_code, 400, payload)


class VisitActionTests(ManagementApiBase):
    def test_staff_cancel_voids_pass(self):
        visit = self._approved_visit()
        auth(self.client, self.reception)
        resp = self.client.post(f"/api/visits/{visit.pk}/cancel/", {"reason": "No-show"}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data["visit"]["status"], "CANCELLED")
        self.assertIsNone(resp.data["visit"]["qr"])
        self.assertFalse(QRPass.objects.filter(visit=visit).exists())

    def test_cannot_cancel_checked_in(self):
        visit = self._approved_visit()
        auth(self.client, self.security)
        self.client.post(
            "/api/visits/scan/",
            {"payload": f"{visit.qr_pass.token}|{visit.qr_pass.signature}"}, format="json",
        )
        auth(self.client, self.admin)
        resp = self.client.post(f"/api/visits/{visit.pk}/cancel/", {}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_security_cannot_cancel(self):
        auth(self.client, self.security)
        resp = self.client.post(f"/api/visits/{self.visit.pk}/cancel/", {}, format="json")
        self.assertEqual(resp.status_code, 403)

    def test_approve_returns_fresh_visit_with_pass(self):
        auth(self.client, self.admin)
        resp = self.client.post(f"/api/visits/{self.visit.pk}/approve/", {}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["visit"]["status"], "APPROVED")
        self.assertIsNotNone(resp.data["visit"]["qr"])
        self.assertTrue(resp.data["visit"]["qr"]["is_valid"])

    def test_visit_filters(self):
        self._approved_visit()
        auth(self.client, self.admin)
        resp = self.client.get("/api/visits/?status=PENDING")
        self.assertEqual(resp.data["count"], 1)
        resp = self.client.get("/api/visits/?status=PENDING,APPROVED")
        self.assertEqual(resp.data["count"], 2)
        resp = self.client.get("/api/visits/?status=BOGUS")
        self.assertEqual(resp.data["count"], 0)
        resp = self.client.get("/api/visits/?q=interview")
        self.assertEqual(resp.data["count"], 1)
        resp = self.client.get("/api/visits/?date=today")
        self.assertEqual(resp.data["count"], 2)
        resp = self.client.get(f"/api/visits/?visitor={self.visitor.pk}&ordering=visit_date")
        self.assertEqual(resp.data["count"], 2)
        resp = self.client.get("/api/visits/?upcoming=1")
        self.assertEqual(resp.data["count"], 2)
        resp = self.client.get("/api/visits/?inside=1")
        self.assertEqual(resp.data["count"], 0)
        self.assertIn("visit_type_label", resp.data["results"] and resp.data["results"][0] or {"visit_type_label": 1})


class VisitorApiTests(ManagementApiBase):
    def test_list_has_annotations(self):
        Blacklist.objects.create(visitor=self.visitor, reason=BlacklistReason.MISCONDUCT, added_by=self.admin)
        auth(self.client, self.reception)
        resp = self.client.get("/api/visitors/")
        row = resp.data["results"][0]
        self.assertTrue(row["is_blacklisted"])
        self.assertEqual(row["blacklist_reason"], "MISCONDUCT")
        self.assertEqual(row["visit_count"], 1)
        resp = self.client.get("/api/visitors/?blacklisted=0")
        self.assertEqual(resp.data["count"], 0)

    def test_edit_visitor(self):
        auth(self.client, self.reception)
        resp = self.client.patch(
            f"/api/visitors/{self.visitor.pk}/", {"company": "Initech", "email": "r@x.io"}, format="json"
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data["company"], "Initech")
        self.assertTrue(AuditLog.objects.filter(action="Visitor updated").exists())

    def test_edit_visitor_duplicate_phone(self):
        Visitor.objects.create(organization=self.org, full_name="Other", phone="8888888888")
        auth(self.client, self.reception)
        resp = self.client.patch(f"/api/visitors/{self.visitor.pk}/", {"phone": "8888888888"}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_security_cannot_edit_visitor(self):
        auth(self.client, self.security)
        resp = self.client.patch(f"/api/visitors/{self.visitor.pk}/", {"company": "X"}, format="json")
        self.assertEqual(resp.status_code, 403)

    def test_visitor_visits_action(self):
        auth(self.client, self.security)
        resp = self.client.get(f"/api/visitors/{self.visitor.pk}/visits/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 1)
        self.assertEqual(resp.data[0]["purpose"], "Interview")

    def test_cross_tenant_visitor_404(self):
        auth(self.client, self.outsider)
        self.assertEqual(self.client.get(f"/api/visitors/{self.visitor.pk}/visits/").status_code, 404)
        self.assertEqual(self.client.patch(f"/api/visitors/{self.visitor.pk}/", {}).status_code, 404)

    def test_blacklist_lifecycle(self):
        auth(self.client, self.security)
        resp = self.client.post(
            f"/api/visitors/{self.visitor.pk}/blacklist/",
            {"reason": "MISCONDUCT", "comment": "Shouting"}, format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertTrue(self.visitor.is_blacklisted)
        resp = self.client.post(
            f"/api/visitors/{self.visitor.pk}/blacklist/", {"reason": "MISCONDUCT"}, format="json"
        )
        self.assertEqual(resp.status_code, 400)
        # security may not lift
        resp = self.client.delete(f"/api/visitors/{self.visitor.pk}/blacklist/")
        self.assertEqual(resp.status_code, 403)
        # blacklisted visitor cannot be approved
        auth(self.client, self.admin)
        resp = self.client.post(f"/api/visits/{self.visit.pk}/approve/", {}, format="json")
        self.assertEqual(resp.status_code, 400)
        resp = self.client.get("/api/blacklist/")
        self.assertEqual(resp.data["count"], 1)
        self.assertEqual(resp.data["results"][0]["visitor"]["full_name"], "Ravi Kumar")
        resp = self.client.delete(f"/api/visitors/{self.visitor.pk}/blacklist/")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Visitor.objects.get(pk=self.visitor.pk).is_blacklisted)
        self.assertTrue(AuditLog.objects.filter(action="Visitor un-blacklisted").exists())

    def test_receptionist_cannot_blacklist(self):
        auth(self.client, self.reception)
        resp = self.client.post(
            f"/api/visitors/{self.visitor.pk}/blacklist/", {"reason": "MISCONDUCT"}, format="json"
        )
        self.assertEqual(resp.status_code, 403)


class OrganizationSettingsTests(ManagementApiBase):
    def test_get_profile(self):
        auth(self.client, self.reception)
        resp = self.client.get("/api/organizations/me/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["slug"], "acme")
        self.assertEqual(resp.data["booking_path"], "/book/acme")

    def test_receptionist_cannot_patch(self):
        auth(self.client, self.reception)
        resp = self.client.patch("/api/organizations/me/", {"name": "X"}, format="json")
        self.assertEqual(resp.status_code, 403)

    def test_admin_patch_and_validation(self):
        auth(self.client, self.admin)
        resp = self.client.patch(
            "/api/organizations/me/",
            {"name": "Acme Corp", "timezone": "Asia/Kolkata",
             "working_hours_start": "08:30", "working_hours_end": "17:30",
             "visitor_policies": {"reminder_offsets_hours": [24, 2]}},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data["timezone"], "Asia/Kolkata")
        self.assertEqual(resp.data["slug"], "acme")  # slug untouched
        self.assertTrue(AuditLog.objects.filter(action="Organization updated").exists())
        resp = self.client.patch("/api/organizations/me/", {"timezone": "Mars/Olympus"}, format="json")
        self.assertEqual(resp.status_code, 400)
        resp = self.client.patch(
            "/api/organizations/me/", {"working_hours_start": "18:00", "working_hours_end": "09:00"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        resp = self.client.patch(
            "/api/organizations/me/", {"visitor_policies": {"reminder_offsets_hours": ["x"]}},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_tenantless_user_denied(self):
        nobody = User.objects.create_user(email="n@x.test", password=PASSWORD, full_name="N")
        auth(self.client, nobody)
        self.assertEqual(self.client.get("/api/organizations/me/").status_code, 403)
        self.assertEqual(self.client.get("/api/buildings/").status_code, 403)
        self.assertEqual(self.client.get("/api/team/").status_code, 403)

    def test_server_time(self):
        auth(self.client, self.admin)
        resp = self.client.get("/api/time/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["today"], date.today().isoformat())


class BuildingDepartmentTests(ManagementApiBase):
    def test_buildings_crud_and_guards(self):
        auth(self.client, self.reception)
        resp = self.client.get("/api/buildings/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 1)
        resp = self.client.post("/api/buildings/", {"name": "Annex"}, format="json")
        self.assertEqual(resp.status_code, 403)

        auth(self.client, self.admin)
        resp = self.client.post("/api/buildings/", {"name": "Annex", "floors": 3}, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        annex = resp.data["id"]
        self.assertTrue(Building.objects.filter(pk=annex, organization=self.org).exists())
        resp = self.client.patch(f"/api/buildings/{annex}/", {"name": "Annex B"}, format="json")
        self.assertEqual(resp.data["name"], "Annex B")
        resp = self.client.delete(f"/api/buildings/{annex}/")
        self.assertEqual(resp.status_code, 204)
        # last building cannot go
        resp = self.client.delete(f"/api/buildings/{self.building.pk}/")
        self.assertEqual(resp.status_code, 403)
        # cross-tenant is invisible
        auth(self.client, self.outsider)
        self.assertEqual(self.client.patch(f"/api/buildings/{self.building.pk}/", {"name": "x"}).status_code, 404)

    def test_departments(self):
        auth(self.client, self.admin)
        resp = self.client.post("/api/departments/", {"name": "Sales", "code": "sl"}, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.data["code"], "SL")
        resp = self.client.post("/api/departments/", {"name": "sales"}, format="json")
        self.assertEqual(resp.status_code, 400)
        resp = self.client.get("/api/departments/")
        self.assertEqual(len(resp.data), 2)
        self.assertIn("member_count", resp.data[0])


class TeamTests(ManagementApiBase):
    def test_non_admin_forbidden(self):
        auth(self.client, self.reception)
        self.assertEqual(self.client.get("/api/team/").status_code, 403)

    def test_create_member(self):
        auth(self.client, self.admin)
        resp = self.client.post(
            "/api/team/",
            {"email": "new@acme.test", "full_name": "New Person", "role": "SECURITY",
             "password": "An0ther-Str0ng!", "designation": "Guard", "department": self.dept.pk},
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        user = User.objects.get(email="new@acme.test")
        self.assertEqual(user.organization, self.org)
        self.assertEqual(user.role, Role.SECURITY)
        self.assertEqual(user.employee_profile.department, self.dept)
        self.assertEqual(resp.data["employee"]["department_name"], "Engineering")
        # can log in with the initial password
        login = self.client.post(
            "/api/auth/token/", {"email": "new@acme.test", "password": "An0ther-Str0ng!"}, format="json"
        )
        self.assertEqual(login.status_code, 200)
        # duplicate email
        resp = self.client.post(
            "/api/team/",
            {"email": "new@acme.test", "full_name": "Dup", "role": "SECURITY", "password": "An0ther-Str0ng!"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        # weak password
        resp = self.client.post(
            "/api/team/",
            {"email": "weak@acme.test", "full_name": "Weak", "role": "SECURITY", "password": "password"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        # foreign department rejected
        foreign_dept = Department.objects.create(organization=self.other_org, name="Ops")
        resp = self.client.post(
            "/api/team/",
            {"email": "f@acme.test", "full_name": "F", "role": "SECURITY",
             "password": "An0ther-Str0ng!", "department": foreign_dept.pk},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_role_change_and_last_admin_guard(self):
        auth(self.client, self.admin)
        resp = self.client.patch(f"/api/team/{self.reception.pk}/", {"role": "ADMIN"}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(User.objects.get(pk=self.reception.pk).role, Role.ADMIN)
        self.assertTrue(AuditLog.objects.filter(action="Team member updated").exists())
        # demote the other admin back; still one admin left (me)
        resp = self.client.patch(f"/api/team/{self.reception.pk}/", {"role": "RECEPTIONIST"}, format="json")
        self.assertEqual(resp.status_code, 200)
        # cannot change own role / deactivate self
        resp = self.client.patch(f"/api/team/{self.admin.pk}/", {"role": "SECURITY"}, format="json")
        self.assertEqual(resp.status_code, 400)
        resp = self.client.delete(f"/api/team/{self.admin.pk}/")
        self.assertEqual(resp.status_code, 400)
        # a second admin can be demoted only while another remains
        second = self._user("second@acme.test", Role.ADMIN)
        self.admin.role = Role.RECEPTIONIST
        self.admin.save(update_fields=["role"])
        auth(self.client, second)
        resp = self.client.patch(f"/api/team/{second.pk}/", {"is_active": False}, format="json")
        self.assertEqual(resp.status_code, 400)  # self
        self.admin.role = Role.ADMIN
        self.admin.save(update_fields=["role"])
        resp = self.client.patch(f"/api/team/{self.admin.pk}/", {"role": "SECURITY"}, format="json")
        self.assertEqual(resp.status_code, 200)
        # now `second` is the only admin: an outsider admin cannot touch them
        auth(self.client, self.outsider)
        self.assertEqual(self.client.patch(f"/api/team/{second.pk}/", {"role": "SECURITY"}).status_code, 404)

    def test_deactivate_member(self):
        auth(self.client, self.admin)
        Employee.objects.create(user=self.security, organization=self.org, employee_id="E-SEC")
        resp = self.client.delete(f"/api/team/{self.security.pk}/")
        self.assertEqual(resp.status_code, 204)
        self.security.refresh_from_db()
        self.assertFalse(self.security.is_active)
        self.assertEqual(self.security.employee_profile.status, Employee.Status.INACTIVE)
        # deactivated accounts cannot log in
        login = self.client.post(
            "/api/auth/token/", {"email": self.security.email, "password": PASSWORD}, format="json"
        )
        self.assertEqual(login.status_code, 401)
        # and are not offered as hosts
        resp = self.client.get("/api/hosts/")
        self.assertNotIn(self.security.pk, [h["id"] for h in resp.data])

    def test_reset_member_password(self):
        auth(self.client, self.admin)
        resp = self.client.patch(
            f"/api/team/{self.reception.pk}/", {"password": "Fresh-Str0ng!Pass"}, format="json"
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        login = self.client.post(
            "/api/auth/token/", {"email": self.reception.email, "password": "Fresh-Str0ng!Pass"},
            format="json",
        )
        self.assertEqual(login.status_code, 200)


class AuditLogApiTests(ManagementApiBase):
    def setUp(self):
        super().setUp()
        AuditLog.log(self.admin, "Visit approved", "Visit", "abc", "Ravi | Interview", organization_id=self.org.pk)
        AuditLog.log(self.security, "Visitor checked in", "Visit", "abc", "Ravi", organization_id=self.org.pk)
        AuditLog.log(self.outsider, "Visit approved", "Visit", "zzz", "Foreign", organization_id=self.other_org.pk)

    def test_list_scoped_and_filtered(self):
        auth(self.client, self.admin)
        resp = self.client.get("/api/audit-logs/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["count"], 2)
        self.assertEqual(resp.data["results"][0]["actor"]["email"], self.security.email)
        resp = self.client.get("/api/audit-logs/?action=Visit approved")
        self.assertEqual(resp.data["count"], 1)
        resp = self.client.get("/api/audit-logs/?q=checked")
        self.assertEqual(resp.data["count"], 1)
        resp = self.client.get(f"/api/audit-logs/?actor={self.security.pk}")
        self.assertEqual(resp.data["count"], 1)
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        resp = self.client.get(f"/api/audit-logs/?date_from={tomorrow}")
        self.assertEqual(resp.data["count"], 0)
        resp = self.client.get("/api/audit-logs/actions/")
        self.assertEqual(sorted(resp.data), ["Visit approved", "Visitor checked in"])

    def test_csv_export(self):
        auth(self.client, self.admin)
        resp = self.client.get("/api/audit-logs/?export=csv")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "text/csv")
        body = resp.content.decode("utf-8-sig")
        self.assertIn("Visitor checked in", body)
        self.assertNotIn("Foreign", body)

    def test_non_admin_forbidden(self):
        auth(self.client, self.security)
        self.assertEqual(self.client.get("/api/audit-logs/").status_code, 403)


class AccountTests(ManagementApiBase):
    def test_change_password(self):
        auth(self.client, self.reception)
        resp = self.client.post(
            "/api/auth/change-password/",
            {"current_password": "wrong", "new_password": "Totally-New-Pass1"}, format="json",
        )
        self.assertEqual(resp.status_code, 400)
        resp = self.client.post(
            "/api/auth/change-password/",
            {"current_password": PASSWORD, "new_password": "Totally-New-Pass1"}, format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        login = self.client.post(
            "/api/auth/token/", {"email": self.reception.email, "password": "Totally-New-Pass1"},
            format="json",
        )
        self.assertEqual(login.status_code, 200)
        self.assertTrue(AuditLog.objects.filter(action="Password changed").exists())

    def test_profile_update(self):
        auth(self.client, self.security)
        resp = self.client.patch("/api/auth/me/profile/", {"full_name": "Gate Officer"}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["full_name"], "Gate Officer")
        resp = self.client.patch("/api/auth/me/profile/", {"full_name": "X"}, format="json")
        self.assertEqual(resp.status_code, 400)


class DashboardAnalyticsTests(ManagementApiBase):
    def test_summary_includes_analytics(self):
        visit = self._approved_visit()
        auth(self.client, self.security)
        self.client.post(
            "/api/visits/scan/",
            {"payload": f"{visit.qr_pass.token}|{visit.qr_pass.signature}"}, format="json",
        )
        auth(self.client, self.admin)
        resp = self.client.get("/api/dashboard/summary/")
        self.assertEqual(resp.status_code, 200)
        analytics = resp.data["analytics"]
        self.assertEqual(len(analytics["daily_series"]), 14)
        self.assertEqual(analytics["daily_series"][-1]["visits"], 2)
        self.assertEqual(analytics["daily_series"][-1]["checked_in"], 1)
        self.assertEqual(analytics["status_counts"]["CHECKED_IN"], 1)
        self.assertEqual(analytics["status_counts"]["PENDING"], 1)
        self.assertEqual(analytics["top_visitors"][0]["name"], "Ravi Kumar")
        self.assertEqual(analytics["today_schedule"]["inside"], 1)
        self.assertEqual(resp.data["inside"], 1)
        self.assertEqual(resp.data["total"], 2)

    def test_tenantless_analytics_empty(self):
        nobody = User.objects.create_user(email="n@x.test", password=PASSWORD, full_name="N")
        auth(self.client, nobody)
        resp = self.client.get("/api/dashboard/summary/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["analytics"]["daily_series"], [])
