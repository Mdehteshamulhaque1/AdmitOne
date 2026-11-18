"""Serializers for the self-service visitor account API (``/api/visitor/``)."""

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from organizations.models import Organization
from visits.models import VisitType

from .serializers import PublicBuildingSerializer, VisitorFacingVisitSerializer


def _validate_password(value):
    try:
        validate_password(value)
    except DjangoValidationError as exc:
        raise serializers.ValidationError(list(exc.messages))
    return value


class VisitorRegisterSerializer(serializers.Serializer):
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


class VisitorProfileSerializer(serializers.Serializer):
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
    visit_type = serializers.ChoiceField(choices=VisitType.choices)
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


class VisitorAccountVisitSerializer(VisitorFacingVisitSerializer):
    """Portal shape plus the organisation slug (bookings span organisations)."""

    organization_slug = serializers.CharField(source="organization.slug", read_only=True)
    organization_city = serializers.CharField(source="organization.city", read_only=True, default="")

    class Meta(VisitorFacingVisitSerializer.Meta):
        fields = VisitorFacingVisitSerializer.Meta.fields + ["organization_slug", "organization_city"]
