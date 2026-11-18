"""Report/dashboard tests: KPI correctness, org isolation, time windows, CSV."""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from accounts.models import Role, User
from organizations.models import Building, Department, Employee, Organization
from visits.models import Visit, VisitStatus, Visitor

from .services import build_dashboard_data

PASSWORD = "Passw0rd!123"


class ReportTestCase(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Reports Co", slug="reports-co")
        self.dept = Department.objects.create(organization=self.org, name="Engineering")
        self.building = Building.objects.create(organization=self.org, name="HQ", floors=3)
        self.other_org = Organization.objects.create(name="Rival Co", slug="rival-co")

        self.admin = self._user("admin@reports.com", Role.ADMIN)
        self.host = self._user("host@reports.com", Role.RECEPTIONIST)
        Employee.objects.create(
            user=self.host, organization=self.org, employee_id="RP-1",
            department=self.dept, designation="Engineer",
        )
        self.visitor = Visitor.objects.create(
            full_name="Rep Guest", phone="7123412345", organization=self.org
        )

    def _user(self, email, role):
        return User.objects.create_user(
            email=email, password=PASSWORD, full_name=email, role=role,
            organization=self.org,
        )

    def _visit(self, org=None, status=VisitStatus.PENDING, days_ago=None,
               visit_date=None, purpose=None):
        v = Visit.objects.create(
            visitor=self.visitor, organization=org or self.org,
            host=self.host, purpose=purpose or "Meet", status=status,
            visit_date=visit_date or timezone.localdate(),
        )
        if days_ago is not None:
            Visit.objects.filter(pk=v.pk).update(
                registered_at=timezone.now() - timedelta(days=days_ago),
            )
            v.refresh_from_db()
        return v


class DashboardDataTests(ReportTestCase):
    def test_kpis_match_database(self):
        self._visit(status=VisitStatus.PENDING)
        self._visit(status=VisitStatus.APPROVED, visit_date=timezone.localdate())
        self._visit(status=VisitStatus.CHECKED_IN)
        self._visit(status=VisitStatus.CHECKED_OUT)
        self._visit(status=VisitStatus.REJECTED)

        kpis, charts = build_dashboard_data(self.admin)

        self.assertEqual(kpis["total"], 5)
        self.assertEqual(kpis["pending"], 1)
        self.assertEqual(kpis["approved"], 1)
        self.assertEqual(kpis["inside"], 1)
        self.assertEqual(kpis["checked_out"], 1)
        self.assertEqual(kpis["rejected"], 1)
        self.assertEqual(kpis["today"], 5)
        self.assertEqual(kpis["week"], 5)
        self.assertEqual(kpis["month"], 5)

    def test_dashboard_isolated_per_org(self):
        self._visit()
        self._visit(org=self.other_org)
        self._visit(org=self.other_org)

        kpis, _ = build_dashboard_data(self.admin)
        self.assertEqual(kpis["total"], 1)


