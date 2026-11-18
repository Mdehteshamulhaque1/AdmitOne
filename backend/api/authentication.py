from django.contrib.auth.models import AnonymousUser
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import BasePermission


class VisitorAccountAuthentication(BaseAuthentication):
    """Bearer-token authentication for self-service visitor *accounts*.

    Like the portal session, the principal is never a staff ``User``:
    ``request.user`` stays anonymous and the account is exposed as
    ``request.visitor_account`` (session as ``request.visitor_account_session``),
    so no RBAC path can treat a visitor as an employee.
    """

    keyword = "Bearer"

    def authenticate(self, request):
        from visits.visitor_accounts import get_session

        header = request.headers.get("Authorization") or ""
        scheme, _, token = header.partition(" ")
        if scheme.lower() != self.keyword.lower() or not token.strip():
            return None
        session = get_session(token.strip())
        if session is None:
            raise AuthenticationFailed("Your session has expired. Please sign in again.")
        request.visitor_account = session.account
        request.visitor_account_session = session
        return (AnonymousUser(), session.token_hash)

    def authenticate_header(self, request):
        return self.keyword


class IsVisitorAccount(BasePermission):
    message = "Please sign in to your visitor account."

    def has_permission(self, request, view):
        return getattr(request, "visitor_account", None) is not None