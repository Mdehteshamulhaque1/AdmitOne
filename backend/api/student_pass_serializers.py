"""Serializers for 6-month student passes (``/api/student-passes/``)."""

import re
from datetime import timedelta

from rest_framework import serializers

from accounts.permissions import has_perm
from accounts.utils import org_localdate
from visits.models import DocumentType, StudentPass, StudentPassScan
from visits.student_passes import effective_status
from visits.validators import validate_image_upload

from .visitor_serializers import VisitorBookingSerializer

ID_FORMATS = VisitorBookingSerializer.ID_FORMATS


def clean_id_number(doc_type, raw):
    """Normalise an ID number and check its shape; raises ``ValidationError``."""
    number = (raw or "").strip() if doc_type == DocumentType.COMPANY_ID else re.sub(r"\s+", "", raw or "").upper()
    if not number:
        raise serializers.ValidationError({"document_number": ["Enter the ID proof number."]})
    pattern, message = ID_FORMATS[doc_type]
    if not re.fullmatch(pattern, number):
        raise serializers.ValidationError({"document_number": [message]})
    return number


class StudentPassCreateSerializer(serializers.Serializer):
    """Issue a pass to an admitted student (multipart: the photo is a file)."""

    full_name = serializers.CharField(max_length=150)
    phone = serializers.CharField(max_length=20)
    email = serializers.EmailField(required=False, allow_blank=True)
    admission_number = serializers.CharField(max_length=40)
    course = serializers.CharField(max_length=120)
    batch = serializers.CharField(max_length=60, required=False, allow_blank=True)
    document_type = serializers.ChoiceField(choices=DocumentType.choices)
    document_number = serializers.CharField(max_length=60)
    photo = serializers.ImageField(validators=[validate_image_upload])
    valid_from = serializers.DateField(required=False)

    def validate_full_name(self, value):
        value = " ".join(value.split())
        if len(value) < 2:
            raise serializers.ValidationError("Enter the student's full name.")
        return value

    def validate_phone(self, value):
        value = value.strip()
        if len(re.sub(r"\D", "", value)) < 7:
            raise serializers.ValidationError("Enter a contact number with at least 7 digits.")
        return value

    def validate_admission_number(self, value):
        value = value.strip().upper()
        if not value:
            raise serializers.ValidationError("Enter the admission or roll number.")
        org = self.context["organization"]
        if StudentPass.objects.filter(organization=org, admission_number__iexact=value).exists():
            raise serializers.ValidationError("A pass already exists for this admission number. Renew it instead.")
        return value

    def validate_valid_from(self, value):
        today = org_localdate(self.context["organization"])
        if value < today - timedelta(days=31):
            raise serializers.ValidationError("The start date can't be more than a month in the past.")
        return value

    def validate(self, attrs):
        attrs["document_number"] = clean_id_number(attrs["document_type"], attrs.get("document_number"))
        attrs["course"] = attrs["course"].strip()
        attrs["batch"] = (attrs.get("batch") or "").strip()
        return attrs


class StudentPassSerializer(serializers.ModelSerializer):
    """A pass as staff see it. The QR payload and the full ID number are only
    included for callers allowed to manage passes / see documents."""

    status = serializers.SerializerMethodField()
    days_left = serializers.SerializerMethodField()
    student = serializers.SerializerMethodField()
    today = serializers.SerializerMethodField()
    payload = serializers.SerializerMethodField()
    issued_by_name = serializers.CharField(source="issued_by.full_name", read_only=True, default="")

    class Meta:
        model = StudentPass
        fields = [
            "id", "admission_number", "course", "batch", "valid_from", "valid_until", "status",
            "days_left", "renewed_count", "issued_at", "issued_by_name", "revoked_at", "revoked_reason",
            "student", "today", "payload",
        ]

    def _user(self):
        request = self.context.get("request")
        return getattr(request, "user", None)

    def _today(self, obj):
        cache = self.context.setdefault("_today", {})
        if obj.organization_id not in cache:
            cache[obj.organization_id] = org_localdate(obj.organization)
        return cache[obj.organization_id]

    def get_status(self, obj):
        return effective_status(obj, self._today(obj))

    def get_days_left(self, obj):
        return max((obj.valid_until - self._today(obj)).days + 1, 0)

    def get_student(self, obj):
        v = obj.visitor
        request = self.context.get("request")
        photo = request.build_absolute_uri(v.photo.url) if (v.photo and request) else (v.photo.url if v.photo else None)
        data = {
            "id": v.pk,
            "full_name": v.full_name,
            "phone": v.phone,
            "email": v.email,
            "photo": photo,
            "is_blacklisted": v.is_blacklisted,
        }
        user = self._user()
        if user and user.is_authenticated and has_perm(user, "view_visitor_documents"):
            data["document_type"] = v.document_type
            data["document_number"] = v.document_number
        return data

    def get_today(self, obj):
        last = obj.scans.filter(scan_date=self._today(obj)).order_by("-scanned_at").first()
        return {"direction": last.direction, "at": last.scanned_at} if last else None

    def get_payload(self, obj):
        user = self._user()
        if user and user.is_authenticated and has_perm(user, "manage_student_passes"):
            return obj.payload
        return None


class StudentPassScanSerializer(serializers.ModelSerializer):
    admission_number = serializers.CharField(source="student_pass.admission_number", read_only=True)
    student_name = serializers.CharField(source="student_pass.visitor.full_name", read_only=True)
    course = serializers.CharField(source="student_pass.course", read_only=True)
    scanned_by_name = serializers.CharField(source="scanned_by.full_name", read_only=True, default="")

    class Meta:
        model = StudentPassScan
        fields = ["id", "admission_number", "student_name", "course", "direction", "scan_date", "scanned_at", "scanned_by_name"]
