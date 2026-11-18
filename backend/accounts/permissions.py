from rest_framework.permissions import BasePermission

from accounts.models import Role, User

ADMIN_PERMISSIONS = {
    "create_visitor", "approve_visitor", "checkin_visitor", "checkout_visitor",
    "manage_org", "manage_buildings", "manage_departments", "manage_employees",
    "manage_users", "view_reports", "view_audit_logs", "blacklist_visitor",
    "badge_print", "scan_qr", "view_visitor_documents", "view_visitor_pii",
}
# Least privilege on personal data (audit finding "Visitor PII exposure"):
#
# * ``view_visitor_pii``       -> home address and emergency contact. Reception
#                                 and admins handle the visitor relationship;
#                                 the gate does not need where someone lives.
# * ``view_visitor_documents`` -> identity-document type/number (and scans).
#                                 Security verifies ID at the gate, so it keeps
#                                 this one.
# * ``badge_print``            -> the raw QR credential (token + signature).
#                                 Only roles that print or hand out passes get
#                                 it; the gate *scans* passes, it never needs
#                                 to render one. Serializers strip these
#                                 fields for callers without the capability.
RECEPTIONIST_PERMISSIONS = {"create_visitor", "badge_print", "view_reports",
                            "view_visitor_documents", "view_visitor_pii"}
SECURITY_PERMISSIONS = {"scan_qr", "checkin_visitor", "checkout_visitor",
                        "blacklist_visitor", "view_reports",
                        "view_visitor_documents"}


def permissions_for(role):
    base = {"view_dashboard"}
    if role == Role.ADMIN:
        return base | ADMIN_PERMISSIONS
    if role == Role.RECEPTIONIST:
        return base | RECEPTIONIST_PERMISSIONS
    if role == Role.SECURITY:
        return base | SECURITY_PERMISSIONS
    return base


def user_permissions(user):
    if user.is_superuser:
        return permissions_for(Role.ADMIN)
    if not user.is_authenticated:
        return set()
    return permissions_for(user.role)


def has_perm(user, perm):
    if user.is_superuser:
        return True
    return perm in user_permissions(user)


def can_manage_org(user):
    return has_perm(user, "manage_org") or has_perm(user, "manage_buildings")


def has_tenant(user):
    """True when the user belongs to a workspace.

    ``User.organization`` is nullable for two ordinary reasons: a freshly
    self-registered user has none until it completes onboarding, and
    ``on_delete=SET_NULL`` leaves one without after a workspace is deleted.
    Neither state is a tenant, so neither may reach tenant data or another
    account (finding F4).  Use this before any ``organization=<user's org>``
    lookup: passing ``None`` to a ``.filter()`` does not match "no
    organization", it compiles to ``IS NULL`` and matches *every* unassigned
    row in the table.
    """
    return bool(user and user.is_authenticated and user.organization_id)


def can_manage_users(user):
    """``manage_users`` only counts inside a workspace.

    The permission sets are role-only, so only ADMIN ever holds this, but a
    role-ADMIN whose workspace was deleted does hold it -- and without a tenant
    check it could reassign any other unassigned account.  There is no
    workspace to manage until onboarding completes, so the permission is denied
    outright.  Callers that only need the tenant requirement should use
    :func:`has_tenant`.
    """
    return has_tenant(user) and has_perm(user, "manage_users")


def tenant_user_queryset(user):
    """The users ``user`` is allowed to see: their own workspace, and no more.

    An org-less caller gets ``none()`` rather than ``filter(organization=None)``
    -- the latter silently means "every account that has not been onboarded",
    which is how ``/api/hosts/`` came to hand out the e-mail address and phone
    number of every unregistered user in the deployment (F4).
    """
    if not has_tenant(user):
        return User.objects.none()
    return User.objects.filter(organization_id=user.organization_id)


def require_permission(perm):
    """DRF permission factory bound to a named application permission."""

    class _Permission(BasePermission):
        message = "You do not have permission to perform this action."

        def has_permission(self, request, view):
            return bool(
                request.user
                and request.user.is_authenticated
                and has_perm(request.user, perm)
            )

    return _Permission


def require_any_permission(*perms):
    """DRF permission factory: the caller must hold at least one of ``perms``."""

    class _AnyPermission(BasePermission):
        message = "You do not have permission to perform this action."

        def has_permission(self, request, view):
            user = request.user
            return bool(
                user and user.is_authenticated and any(has_perm(user, p) for p in perms)
            )

    return _AnyPermission


class IsTenantMember(BasePermission):
    """The caller belongs to a workspace (see :func:`has_tenant`).

    Compose with ``IsAuthenticated`` and a capability check on endpoints that
    read or write tenant data; a tenantless account is denied outright rather
    than being handed an ``organization=None`` filter that matches every
    unassigned row.
    """

    message = "Finish creating your workspace before using this feature."

    def has_permission(self, request, view):
        return has_tenant(request.user)


CanApproveVisit = require_permission("approve_visitor")
CanCheckIn = require_permission("checkin_visitor")
CanCheckOut = require_permission("checkout_visitor")
CanRegisterVisitor = require_permission("create_visitor")
CanScanQR = require_permission("scan_qr")
CanBlacklist = require_permission("blacklist_visitor")
CanLiftBlacklist = require_permission("manage_org")
CanCancelVisit = require_any_permission("approve_visitor", "create_visitor")
