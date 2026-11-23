"""Serializers for the self-service visitor account API (``/api/visitor/``)."""

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

import re

from organizations.models import Organization
from visits.models import DocumentType, VisitType
from visits.validators import validate_image_upload

from .serializers import PublicBuildingSerializer, VisitorFacingVisitSerializer

_PROFILE_FIELD_KW = dict(required=False, allow_blank=True)


class _VisitorProfileFieldsMixin(serializers.Serializer):
    """Training-centre profile shared by sign-up and profile edits.

    Free text on the wire (the SPA offers dropdowns, with "Other" allowing a
    typed value) so a workspace can change its lists without an API change.
    """

    category = serializers.CharField(max_length=40, **_PROFILE_FIELD_KW)
    state = serializers.CharField(max_length=80, **_PROFILE_FIELD_KW)
    university = serializers.CharField(max_length=200, **_PROFILE_FIELD_KW)
    qualification = serializers.CharField(max_length=120, **_PROFILE_FIELD_KW)
    passing_year = serializers.IntegerField(
        required=False, allow_null=True, min_value=1950, max_value=2100
    )

    def validate_category(self, value):
        return (value or "").strip().upper()


def _validate_password(value):
    try:
        validate_password(value)
    except DjangoValidationError as exc:
        raise serializers.ValidationError(list(exc.messages))
    return value


class VisitorRegisterSerializer(_VisitorProfileFieldsMixin):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8, max_length=128)
    full_name = serializers.CharField(max_length=150)
    phone = serializers.CharField(max_length=20)
    company = serializers.CharField(max_length=150, required=False, allow_blank=True)
    designation = serializers.CharField(max_length=150, required=False, allow_blank=True)

    def validate_full_name(self, value):
        value = (value or "").strip()
        if len(value) < 2:
            raise serializers.ValidationError("Enter your full name.")
        return value

    def validate_phone(self, value):
        digits = "".join(ch for ch in (value or "") if ch.isdigit() or ch == "+")
        if len(digits.lstrip("+")) < 7:
            raise serializers.ValidationError("Enter a valid phone number.")
        return value.strip()

    def validate_password(self, value):
        return _validate_password(value)


class VisitorLoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)


class VisitorProfileSerializer(_VisitorProfileFieldsMixin):
    full_name = serializers.CharField(max_length=150, required=False)
    phone = serializers.CharField(max_length=20, required=False)
    company = serializers.CharField(max_length=150, required=False, allow_blank=True)
    designation = serializers.CharField(max_length=150, required=False, allow_blank=True)

    def validate_full_name(self, value):
        value = (value or "").strip()
        if len(value) < 2:
            raise serializers.ValidationError("Enter your full name.")
        return value


class VisitorChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=8, max_length=128)

    def validate_new_password(self, value):
        return _validate_password(value)


class OrganizationSearchSerializer(serializers.ModelSerializer):
    """Directory entry: the organisation plus its buildings and floors."""

    buildings = PublicBuildingSerializer(many=True, read_only=True)

    class Meta:
        model = Organization
        fields = ["id", "name", "slug", "tagline", "city", "country", "buildings"]


class VisitorBookingSerializer(serializers.Serializer):
    """Booking submitted by a signed-in visitor; identity comes from the account."""

    organization = serializers.SlugField(max_length=80)
    # Catalogue path (``category`` + ``purpose``) or legacy ``visit_type``;
    # when neither is sent the account's own category is used.
    category = serializers.CharField(required=False, allow_blank=True, max_length=40)
    visit_type = serializers.ChoiceField(choices=VisitType.choices, required=False, allow_blank=True)
    department = serializers.IntegerField(required=False, allow_null=True)
    building = serializers.IntegerField(required=False, allow_null=True)
    floor = serializers.IntegerField(required=False, allow_null=True)
    host = serializers.IntegerField(required=False, allow_null=True)
    visit_date = serializers.DateField()
    expected_arrival = serializers.RegexField(r"^\d{2}:\d{2}$", max_length=5)
    expected_exit = serializers.RegexField(r"^\d{2}:\d{2}$", max_length=5)
    purpose = serializers.CharField(allow_blank=False, max_length=200)
    purpose_other = serializers.CharField(required=False, allow_blank=True, max_length=120)
    notes = serializers.CharField(required=False, allow_blank=True, max_length=1000)
    # Identity for the gate pass (like a court or office gate-pass counter):
    # a recent photo and an identity proof. The original ID is checked at the
    # gate against what is entered here. Sent as multipart when a photo is
    # attached; everything else may also come as JSON.
    document_type = serializers.ChoiceField(choices=DocumentType.choices, required=False, allow_blank=True)
    document_number = serializers.CharField(required=False, allow_blank=True, max_length=60)
    photo = serializers.ImageField(required=False, allow_null=True, validators=[validate_image_upload])

    # Shape of each ID number, so a typo is caught before reception sees it.
    ID_FORMATS = {
        DocumentType.AADHAAR: (r"\d{12}", "Aadhaar number must be 12 digits."),
        DocumentType.PAN: (r"[A-Z]{5}\d{4}[A-Z]", "PAN must look like ABCDE1234F."),
        DocumentType.PASSPORT: (r"[A-Z]\d{7}", "Passport number must look like A1234567."),
        DocumentType.DRIVING_LICENSE: (r"[A-Z0-9-]{8,20}", "Enter the driving licence number as printed (8 to 20 letters or digits)."),
        DocumentType.COMPANY_ID: (r".{3,60}", "Enter the ID number printed on the card."),
    }

    def validate(self, attrs):
        doc_type = attrs.get("document_type") or ""
        raw = attrs.get("document_number") or ""
        number = re.sub(r"\s+", "", raw).upper() if doc_type != DocumentType.COMPANY_ID else raw.strip()
        if raw.strip() and not doc_type:
            raise serializers.ValidationError({"document_type": ["Choose which identity proof this number belongs to."]})
        if doc_type:
            if not number:
                raise serializers.ValidationError({"document_number": ["Enter the ID proof number."]})
            pattern, message = self.ID_FORMATS[doc_type]
            if not re.fullmatch(pattern, number):
                raise serializers.ValidationError({"document_number": [message]})
        attrs["document_number"] = number
        return attrs


class VisitorAccountVisitSerializer(VisitorFacingVisitSerializer):
    """Portal shape plus the organisation slug (bookings span organisations)."""

    organization_slug = serializers.CharField(source="organization.slug", read_only=True)
    organization_city = serializers.CharField(source="organization.city", read_only=True, default="")

    class Meta(VisitorFacingVisitSerializer.Meta):
        fields = VisitorFacingVisitSerializer.Meta.fields + ["organization_slug", "organization_city"]
