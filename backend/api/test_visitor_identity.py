"""Gate-pass identity on visitor bookings: photo + identity proof + ID number."""

import io
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from PIL import Image

from api.test_visitor_accounts import VisitorAccountBase
from visits.models import Visit

_MEDIA = tempfile.mkdtemp(prefix="admitone-test-media-")


def png_upload(name="face.png", size=(64, 64)):
    buf = io.BytesIO()
    Image.new("RGB", size, (40, 90, 200)).save(buf, format="PNG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/png")


@override_settings(MEDIA_ROOT=_MEDIA)
class VisitorIdentityTests(VisitorAccountBase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_MEDIA, ignore_errors=True)

    def book(self, fmt="multipart", **extra):
        return self.client.post("/api/visitor/bookings/", self.booking_payload(**extra), format=fmt)

    def test_photo_and_id_are_saved_on_the_visitor(self):
        self.signup()
        resp = self.book(document_type="AADHAAR", document_number="1234 5678 9012", photo=png_upload())
        self.assertEqual(resp.status_code, 201, resp.content)
        visitor = Visit.objects.get(visit_id=resp.data["visit"]["reference"].lower()).visitor
        self.assertEqual(visitor.document_type, "AADHAAR")
        self.assertEqual(visitor.document_number, "123456789012")  # spaces removed
        self.assertTrue(visitor.photo.name.startswith("visitor_photos/"))

    def test_pan_is_normalised_to_upper_case(self):
        self.signup()
        resp = self.book(fmt="json", document_type="PAN", document_number="abcde1234f")
        self.assertEqual(resp.status_code, 201, resp.content)
        visitor = Visit.objects.get(visit_id=resp.data["visit"]["reference"].lower()).visitor
        self.assertEqual(visitor.document_number, "ABCDE1234F")

    def test_bad_id_numbers_are_rejected_with_a_clear_message(self):
        self.signup()
        cases = [
            ({"document_type": "AADHAAR", "document_number": "12345"}, "12 digits"),
            ({"document_type": "PAN", "document_number": "1234567890"}, "ABCDE1234F"),
            ({"document_type": "PASSPORT", "document_number": "12345678"}, "A1234567"),
            ({"document_type": "AADHAAR", "document_number": ""}, "Enter the ID proof number"),
            ({"document_number": "123456789012"}, "Choose which identity proof"),
        ]
        for extra, message in cases:
            resp = self.book(fmt="json", **extra)
            self.assertEqual(resp.status_code, 400, extra)
            self.assertIn(message, str(resp.data), extra)
        self.assertFalse(Visit.objects.exists())

    def test_non_image_photo_is_rejected(self):
        self.signup()
        fake = SimpleUploadedFile("face.png", b"<html>not an image</html>", content_type="image/png")
        resp = self.book(document_type="AADHAAR", document_number="123456789012", photo=fake)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("photo", resp.data)
        self.assertFalse(Visit.objects.exists())

    def test_booking_without_identity_still_works(self):
        self.signup()
        self.assertEqual(self.book(fmt="json").status_code, 201)

    def test_new_id_replaces_the_previous_one(self):
        self.signup()
        self.assertEqual(self.book(fmt="json", document_type="PAN", document_number="ABCDE1234F").status_code, 201)
        resp = self.book(fmt="json", document_type="PASSPORT", document_number="K1234567", expected_arrival="11:00", expected_exit="11:30")
        self.assertEqual(resp.status_code, 201, resp.content)
        visitor = Visit.objects.get(visit_id=resp.data["visit"]["reference"].lower()).visitor
        self.assertEqual((visitor.document_type, visitor.document_number), ("PASSPORT", "K1234567"))
