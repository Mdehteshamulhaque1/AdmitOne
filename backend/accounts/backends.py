"""Custom Django authentication backend.

Account lockout (5 failed attempts -> temporary lock) is enforced here for
BOTH authentication paths, so it cannot be bypassed by using a different
login endpoint:

  - API / JWT login   (``/api/auth/token/``  -> ``authenticate()``)
  - Console session login (``accounts:login`` / Django admin)

The JWT serializer relies on this backend instead of re-implementing the
lockout counters (single source of truth in ``accounts.models.User``).
"""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

User = get_user_model()


class LockoutBackend(ModelBackend):
    """Authenticates by email, tracks failed attempts and blocks locked users."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            # Mirrors ModelBackend: accept the login field key as-is
            # (e.g. ``email`` when USERNAME_FIELD is "email").
            username = kwargs.get(User.USERNAME_FIELD)
        if username is None or password is None:
            return None
        email = str(username).strip()
        user = User._default_manager.filter(email__iexact=email).first()
        if user is None:
            return None
        if user.is_locked:
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            user.reset_failed_attempts()
            return user
        if user.has_usable_password():
            user.register_failed_attempt(settings)
        return None