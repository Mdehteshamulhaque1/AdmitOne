"""WhatsApp delivery of approved QR passes (Meta Cloud API), with a fake API."""

import io
import json
import urllib.error
from datetime import date, time, timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings

from accounts.models import Role, User
from organizations.models import Organization
from visits import whatsapp
from visits.models import Visit, VisitNotification, VisitStatus, Visitor
from visits.services import approve_visit

CONFIG = dict(
    WHATSAPP_PROVIDER="meta",
    WHATSAPP_ACCESS_TOKEN="EAAG-secret-token",
    WHATSAPP_PHONE_NUMBER_ID="1234567890",
    WHATSAPP_TEMPLATE_NAME="visitor_pass_approved",
    WHATSAPP_TEMPLATE_LANGUAGE="en",
)


class FakeClient:
    def __init__(self, fail=None):
        self.fail = fail
        self.sent = []

    def upload_png(self, png):
        assert png.startswith(b"\x89PNG")
        if self.fail:
            raise whatsapp.WhatsAppError(self.fail)
        return "media-1"

    def send_template(self, to, media_id, body_values):
        self.sent.append((to, media_id, body_values))
        return "wamid.1"


class WhatsAppTestBase(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Lakeview Institute", slug="lakeview")
        self.admin = User.objects.create_user(email="admin@lv.test", password="Str0ng!Pass1", full_name="Asha Rao", role=Role.ADMIN, organization=self.org)
        self.visitor = Visitor.objects.create(organization=self.org, full_name="Ravi Kumar", phone="98765 43210")
        self.visit = Visit.objects.create(
            organization=self.org, visitor=self.visitor, host=self.admin, purpose="Mock interview",
            visit_date=date.today() + timedelta(days=1), expected_arrival=time(10, 0), expected_exit=time(10, 30),
            status=VisitStatus.PENDING,
        )

    def approve(self):
        ok, msg = approve_visit(self.visit, self.admin)
        self.assertTrue(ok, msg)
        self.visit.refresh_from_db()
        return msg


class NormalisePhoneTests(TestCase):
    def test_indian_and_international_numbers(self):
        self.assertEqual(whatsapp.normalise_phone("9876543210"), "919876543210")
        self.assertEqual(whatsapp.normalise_phone("098765 43210"), "919876543210")
        self.assertEqual(whatsapp.normalise_phone("+91 98765-43210"), "919876543210")
        self.assertEqual(whatsapp.normalise_phone("+44 7700 900123"), "447700900123")
        self.assertEqual(whatsapp.normalise_phone("0044 7700 900123"), "447700900123")
        self.assertIsNone(whatsapp.normalise_phone("12345"))
        self.assertIsNone(whatsapp.normalise_phone(""))


class SendPassTests(WhatsAppTestBase):
    def test_off_by_default_and_approval_message_unchanged(self):
        msg = self.approve()
        self.assertNotIn("WhatsApp", msg)
        self.assertEqual(whatsapp.send_qr_pass_whatsapp(self.visit), "not_configured")
        self.assertFalse(VisitNotification.objects.filter(event=whatsapp.EVENT_QR_PASS_WHATSAPP).exists())

    @override_settings(**CONFIG)
    def test_approval_sends_the_pass_once(self):
        fake = FakeClient()
        with patch.object(whatsapp, "MetaCloudClient", return_value=fake):
            msg = self.approve()
            self.assertIn("WhatsApp", msg)
            self.assertEqual(whatsapp.send_qr_pass_whatsapp(self.visit), "already_sent")
        to, media, values = fake.sent[0]
        self.assertEqual(len(fake.sent), 1)
        self.assertEqual((to, media), ("919876543210", "media-1"))
        self.assertEqual(values[0:2], ["Ravi Kumar", "Lakeview Institute"])
        self.assertIn("10:00-10:30", values[2])
        self.assertEqual(values[3], "Asha Rao")
        self.assertEqual(values[4], str(self.visit.visit_id)[:8].upper())
        row = VisitNotification.objects.get(event=whatsapp.EVENT_QR_PASS_WHATSAPP)
        self.assertEqual((row.status, row.recipient), (VisitNotification.Status.SENT, "919876543210"))
        self.assertIsNotNone(row.sent_at)

    @override_settings(**CONFIG)
    def test_api_failure_is_recorded_and_approval_still_succeeds(self):
        with patch.object(whatsapp, "MetaCloudClient", return_value=FakeClient(fail="WhatsApp API 400: Template not found")):
            self.approve()
        self.assertEqual(self.visit.status, VisitStatus.APPROVED)
        row = VisitNotification.objects.get(event=whatsapp.EVENT_QR_PASS_WHATSAPP)
        self.assertEqual(row.status, VisitNotification.Status.FAILED)
        self.assertIn("Template not found", row.error)

    @override_settings(**CONFIG)
    def test_invalid_phone_is_not_sent(self):
        self.visitor.phone = "123"
        self.visitor.save()
        fake = FakeClient()
        with patch.object(whatsapp, "MetaCloudClient", return_value=fake):
            self.approve()
        self.assertEqual(fake.sent, [])
        self.assertEqual(VisitNotification.objects.get(event=whatsapp.EVENT_QR_PASS_WHATSAPP).status, VisitNotification.Status.FAILED)


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@override_settings(**CONFIG)
class MetaCloudClientTests(TestCase):
    def test_upload_and_send_call_the_cloud_api_correctly(self):
        calls = []

        def opener(req, timeout):
            calls.append(req)
            body = {"id": "media-9"} if req.full_url.endswith("/media") else {"messages": [{"id": "wamid.9"}]}
            return _Resp(json.dumps(body).encode())

        client = whatsapp.MetaCloudClient(opener=opener)
        self.assertEqual(client.upload_png(b"\x89PNGdata"), "media-9")
        self.assertEqual(client.send_template("919876543210", "media-9", ["a", "b", "c", "d", "e"]), "wamid.9")
        upload, send = calls
        self.assertEqual(upload.full_url, "https://graph.facebook.com/v21.0/1234567890/media")
        self.assertEqual(upload.get_header("Authorization"), "Bearer EAAG-secret-token")
        self.assertIn(b"\x89PNGdata", upload.data)
        payload = json.loads(send.data)
        self.assertEqual(payload["to"], "919876543210")
        self.assertEqual(payload["template"]["name"], "visitor_pass_approved")
        self.assertEqual(payload["template"]["components"][0]["parameters"][0]["image"]["id"], "media-9")
        self.assertEqual([p["text"] for p in payload["template"]["components"][1]["parameters"]], ["a", "b", "c", "d", "e"])

    def test_http_errors_become_safe_messages_without_the_token(self):
        def opener(req, timeout):
            raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, io.BytesIO(b'{"error":{"message":"Invalid OAuth access token."}}'))

        with self.assertRaises(whatsapp.WhatsAppError) as ctx:
            whatsapp.MetaCloudClient(opener=opener).upload_png(b"\x89PNG")
        self.assertIn("Invalid OAuth access token", str(ctx.exception))
        self.assertNotIn("EAAG-secret-token", str(ctx.exception))
