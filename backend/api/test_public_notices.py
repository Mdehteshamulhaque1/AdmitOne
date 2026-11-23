"""Public notices: admins publish them in workspace settings; anyone can read current ones."""

from datetime import date, timedelta

from django.core.cache import cache
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Role, User
from organizations.models import Organization


class PublicNoticeTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.org = Organization.objects.create(name="Acme Training", slug="acme")
        self.admin = User.objects.create_user(email="admin@acme.test", password="Str0ng!Pass1", full_name="Admin", role=Role.ADMIN, organization=self.org)
        self.guard = User.objects.create_user(email="gate@acme.test", password="Str0ng!Pass1", full_name="Guard", role=Role.SECURITY, organization=self.org)

    def as_user(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")

    def save(self, notices, user=None):
        self.as_user(user or self.admin)
        return self.client.patch("/api/organizations/me/", {"visitor_policies": {"public_notices": notices}}, format="json")

    def test_admin_publishes_and_public_reads_current_notices(self):
        past = (date.today() - timedelta(days=3)).isoformat()
        future = (date.today() + timedelta(days=3)).isoformat()
        resp = self.save([
            {"title": "  Gate 2 closed on Saturday  ", "body": "Use Gate 1.", "published_on": future, "until": future},
            {"title": "Old notice", "body": "Expired", "until": past},
            {"title": "No passes on holidays", "body": ""},
        ])
        self.assertEqual(resp.status_code, 200, resp.data)
        self.client.credentials()  # anonymous
        resp = self.client.get("/api/public/notices/")
        self.assertEqual(resp.status_code, 200)
        titles = [n["title"] for n in resp.data["notices"]]
        self.assertEqual(titles, ["Gate 2 closed on Saturday", "No passes on holidays"])  # trimmed, expired hidden, newest first
        self.assertEqual(resp.data["notices"][0]["organization"], "Acme Training")
        self.assertEqual(resp.data["notices"][1]["published_on"], date.today().isoformat())  # defaulted

    def test_invalid_notices_are_rejected(self):
        for bad in (
            "not a list",
            [{"title": ""}],
            [{"title": "x" * 121}],
            [{"title": "ok", "until": "next week"}],
            [{"title": f"n{i}"} for i in range(21)],
        ):
            self.assertEqual(self.save(bad).status_code, 400, bad)

    def test_only_admins_can_publish(self):
        self.assertEqual(self.save([{"title": "Hi"}], user=self.guard).status_code, 403)

    def test_no_notices_is_an_empty_list(self):
        resp = self.client.get("/api/public/notices/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data, {"notices": []})
