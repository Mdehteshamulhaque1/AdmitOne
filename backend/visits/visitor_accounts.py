"""Self-service visitor accounts: sign-up, login, sessions and bookings.

Everything a visitor can do is funnelled through the *same* domain services
the staff console and the reference+phone portal use (``create_pre_booking``,
``reschedule_visit``, ``cancel_visit``, ``mark_visitor_arriving``), so the
business rules cannot drift. Those services take a "session" object that
exposes ``organization``/``visitor`` (plus their ``_id`` twins); for an
account that may hold bookings in several organisations we build that scope
per visit with :func:`scope_for_visit` after proving the visit belongs to the
account.
"""

import hashlib
import secrets
from datetime import timedelta
from types import SimpleNamespace

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from organizations.models import AuditLog, Organization

from .models import Visit, Visitor, VisitorAccount, VisitorAccountSession
from .services import create_pre_booking

SESSION_TTL_DAYS = 14
MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 15


def _hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def normalize_email(email):
    email = (email or "").strip()
    name, _, domain = email.rpartition("@")
    return f"{name}@{domain.lower()}" if domain else email.lower()


# ------------------------------------------------------------------ accounts


PROFILE_FIELDS = ("category", "state", "university", "qualification", "passing_year")


def register_account(
    *, email, password, full_name, phone, company="", designation="", audit_ip=None, **profile
):
    """Create a visitor account. Returns ``(account, ok, msg)``.

    ``profile`` carries the optional training-centre fields
    (:data:`PROFILE_FIELDS`); anything else is ignored.
    """
    email = normalize_email(email)
    if VisitorAccount.objects.filter(email__iexact=email).exists():
        return None, False, {"email": ["An account with this e-mail already exists."]}
    account = VisitorAccount(
        email=email,
        full_name=(full_name or "").strip(),
        phone=(phone or "").strip(),
        company=(company or "").strip(),
        designation=(designation or "").strip(),
    )
    for field in PROFILE_FIELDS:
        value = profile.get(field)
        if field == "passing_year":
            account.passing_year = value or None
        elif value is not None:
            setattr(account, field, str(value).strip())
    account.set_password(password)
    try:
        with transaction.atomic():
            account.save()
            AuditLog.log(
                None, "Visitor account created", "VisitorAccount", account.pk,
                account.email, ip_address=audit_ip,
            )
    except IntegrityError:
        return None, False, {"email": ["An account with this e-mail already exists."]}
    return account, True, "Account created."


def authenticate_account(email, password):
    """Password check with the same 5-strikes/15-minute lockout as staff logins.

    Returns ``(account, message)``; ``account`` is ``None`` on failure and the
    message is deliberately generic so e-mails cannot be enumerated.
    """
    generic = "Unable to sign in with those details."
    account = VisitorAccount.objects.filter(email__iexact=normalize_email(email)).first()
    if account is None or not account.is_active:
        return None, generic
    if account.is_locked:
        return None, "Too many failed attempts. Try again in a few minutes."
    if not account.check_password(password or ""):
        account.failed_login_attempts += 1
        fields = ["failed_login_attempts"]
        if account.failed_login_attempts >= MAX_FAILED_LOGINS:
            account.locked_until = timezone.now() + timedelta(minutes=LOCKOUT_MINUTES)
            account.failed_login_attempts = 0
            fields.append("locked_until")
        account.save(update_fields=fields)
        return None, generic
    account.failed_login_attempts = 0
    account.locked_until = None
    account.last_login = timezone.now()
    account.save(update_fields=["failed_login_attempts", "locked_until", "last_login"])
    return account, "Signed in."


def create_session(account, user_agent=""):
    """Mint a bearer token; only its hash is stored. Returns ``(session, raw)``."""
    raw = secrets.token_urlsafe(32)
    session = VisitorAccountSession.objects.create(
        account=account,
        token_hash=_hash(raw),
        expires_at=timezone.now() + timedelta(days=SESSION_TTL_DAYS),
        user_agent=(user_agent or "")[:200],
    )
    return session, raw


def get_session(raw_token):
    if not raw_token:
        return None
    return (
        VisitorAccountSession.objects.select_related("account")
        .filter(token_hash=_hash(raw_token), expires_at__gt=timezone.now(), account__is_active=True)
        .first()
    )


def revoke_session(raw_token):
    return VisitorAccountSession.objects.filter(token_hash=_hash(raw_token or "")).delete()[0]


def purge_expired_sessions():
    return VisitorAccountSession.objects.filter(expires_at__lte=timezone.now()).delete()[0]


# ------------------------------------------------------------------- lookups


def search_organizations(query, limit=200):
    """The directory a signed-in visitor can book with.

    With no query this is the whole directory (every organisation with its
    buildings and floors, like a lobby board); with a query it is filtered by
    organisation name, slug, city or building name. Only signed-in visitors
    can call this, so it is not an anonymous enumeration surface.
    """
    qs = Organization.objects.prefetch_related("buildings__floor_set").order_by("name")
    q = (query or "").strip()
    if q:
        qs = qs.filter(
            Q(name__icontains=q)
            | Q(slug__icontains=q)
            | Q(city__icontains=q)
            | Q(buildings__name__icontains=q)
        ).distinct()
    return qs[:limit]


_VISIT_RELATIONS = (
    "host", "host__employee_profile", "building", "floor", "department",
    "organization", "visitor", "qr_pass",
)


def account_visits(account):
    """Every visit, across organisations, whose visitor record the account owns."""
    return (
        Visit.objects.filter(visitor__account=account)
        .select_related(*_VISIT_RELATIONS)
        .order_by("-visit_date", "-expected_arrival", "-id")
    )


def account_visit(account, visit_id):
    return (
        Visit.objects.filter(pk=visit_id, visitor__account=account)
        .select_related(*_VISIT_RELATIONS)
        .first()
    )


def scope_for_visit(visit):
    """The (organization, visitor) scope the portal services expect."""
    return SimpleNamespace(
        organization=visit.organization,
        organization_id=visit.organization_id,
        visitor=visit.visitor,
        visitor_id=visit.visitor_id,
    )


# ------------------------------------------------------------------ booking


def book_visit_for_account(account, org, *, audit_ip=None, identity=None, **booking):
    """Create a PENDING pre-booking for the account and claim the visitor row.

    The per-organisation ``Visitor`` record is resolved by phone through the
    shared ``create_pre_booking`` dedup logic. If that record is unclaimed it
    is linked to this account; if another account already owns it the booking
    is refused rather than silently merging two people's histories.
    """
    phone = (account.phone or "").strip()
    existing = Visitor.objects.filter(organization=org, phone=phone).first() if phone else None
    if existing is not None and existing.account_id not in (None, account.pk):
        return None, False, {
            "detail": "This phone number is already registered with another visitor account at this organisation."
        }
    visitor_data = {
        "full_name": account.full_name,
        "phone": phone,
        "email": account.email,
        "company": account.company,
        "designation": account.designation,
        # training-centre profile travels with every booking so staff see it
        # on the visitor record without reaching into the account
        "category": account.category,
        "state": account.state,
        "university": account.university,
        "qualification": account.qualification,
        "passing_year": account.passing_year,
    }
    booking.setdefault("category", account.category)
    with transaction.atomic():
        visit, ok, msg = create_pre_booking(org, visitor_data=visitor_data, audit_ip=audit_ip, **booking)
        if not ok:
            return None, False, msg
        visitor = visit.visitor
        update = []
        if visitor.account_id is None:
            visitor.account = account
            update.append("account")
        # The visitor's own identity for this gate pass: the latest photo and
        # ID they submit replace the previous ones on their record here.
        identity = identity or {}
        if identity.get("document_type"):
            visitor.document_type = identity["document_type"]
            visitor.document_number = identity.get("document_number", "")
            update += ["document_type", "document_number"]
        if identity.get("photo"):
            visitor.photo = identity["photo"]
            update.append("photo")
        if update:
            visitor.save(update_fields=update + ["updated_at"])
    return visit, True, msg


def account_payload(account):
    return {
        "id": account.pk,
        "email": account.email,
        "full_name": account.full_name,
        "phone": account.phone,
        "company": account.company,
        "designation": account.designation,
        "category": account.category,
        "state": account.state,
        "university": account.university,
        "qualification": account.qualification,
        "passing_year": account.passing_year,
        "created_at": account.created_at,
        "last_login": account.last_login,
        "session_days": SESSION_TTL_DAYS,
        "debug": bool(getattr(settings, "DEBUG", False)),
    }
