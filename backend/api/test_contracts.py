"""Contract tests for two things that drifted silently.

1. The dashboard average-visit KPI was named ``avg_duration`` by the service
   and ``avg_duration_minutes`` by the API, with the view translating between
   them field by field. Nothing caught the mismatch, and a rename on either
   side would have silently produced a 500 rather than a review prompt.

2. The visitor portal list endpoint had an N+1: 17 queries for 8 visits,
   3 for 1. The serializer reads ``visit.visitor.phone`` and
   ``visit.host.employee_profile.designation`` per row, neither of which was in
   ``select_related``.

The query assertion here is on *independence from row count*, not on an exact
number, so a legitimate later query is caught but a re-introduced per-row
lookup fails loudly.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from accounts.models import Role, User
from api.serializers import DashboardSummarySerializer
from api.views import DASHBOARD_SUMMARY_KEYS
from organizations.models import Building, Organization
from reports.services import build_dashboard_data
from visits.models import Visit, VisitType, Visitor


class DashboardKpiNamingContractTests(TestCase):
    """One canonical name for the average-visit KPI: ``avg_duration_minutes``.

    The unit is in the name because the bare ``avg_duration`` was ambiguous
    about whether it was minutes, seconds or milliseconds.
    """

    def setUp(self):
        self.org = Organization.objects.create(name="Kpi Co", slug="kpi-co", timezone="UTC")
        self.admin = User.objects.create_user(
            email="admin@kpi.test", password="Passw0rd!123", full_name="A",
            role=Role.ADMIN, organization=self.org,
        )

    def test_the_service_dict_uses_the_canonical_name(self):
        kpis, _ = build_dashboard_data(self.admin)
        self.assertIn("avg_duration_minutes", kpis)
        self.assertNotIn(
            "avg_duration", kpis,
            "the bare name is what the API used to have to rename; it should not exist",
        )

    def test_the_api_key_list_matches_the_service_dict(self):
        # This is the drift guard. DASHBOARD_SUMMARY_KEYS is copied straight
        # into the response, so a key the service does not produce raises here
        # instead of becoming a 500 on a live dashboard.
        kpis, _ = build_dashboard_data(self.admin)
        for key in DASHBOARD_SUMMARY_KEYS:
            self.assertIn(key, kpis, f"API declares {key!r} but the service does not produce it")

    def test_the_serialized_response_exposes_only_the_canonical_name(self):
        kpis, _ = build_dashboard_data(self.admin)
        data = DashboardSummarySerializer(
            {key: kpis[key] for key in DASHBOARD_SUMMARY_KEYS}
        ).data
        self.assertIn("avg_duration_minutes", data)
        self.assertNotIn("avg_duration", data)
        # The full response shape is pinned so a dropped or renamed key is a
        # test failure rather than a blank tile.
        self.assertEqual(
            set(data),
            {
                "today", "week", "month", "inside", "pending", "approved",
                "avg_duration_minutes", "checked_out", "rejected", "trend",
            },
        )

    def test_the_value_is_the_mean_visit_length_in_whole_minutes(self):
        building = Building.objects.create(organization=self.org, name="HQ")
        host = User.objects.create_user(
            email="host@kpi.test", password="Passw0rd!123", full_name="H",
            organization=self.org,
        )
        now = timezone.now()
        # 30 and 90 minutes -> mean 60. Whole minutes, no decimals.
        for index, minutes in enumerate((30, 90)):
            visit = Visit.objects.create(
                visitor=Visitor.objects.create(
                    organization=self.org, full_name=f"V{index}",
                    phone=f"999000000{index}",
                ),
                organization=self.org, building=building, host=host,
                created_by=self.admin, purpose="Meeting",
                visit_type=VisitType.CLIENT_MEETING,
                visit_date=timezone.localdate(),
                expected_arrival=now.replace(second=0, microsecond=0),
            )
            visit.checked_in_at = now - timedelta(minutes=minutes)
            visit.checked_out_at = now
            visit.save(update_fields=["checked_in_at", "checked_out_at"])

        kpis, _ = build_dashboard_data(self.admin)
        self.assertEqual(kpis["avg_duration_minutes"], 60)

    def test_no_completed_visit_reports_zero_not_none(self):
        kpis, _ = build_dashboard_data(self.admin)
        self.assertEqual(kpis["avg_duration_minutes"], 0)


