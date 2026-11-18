from rest_framework.throttling import SimpleRateThrottle


class RegisterRateThrottle(SimpleRateThrottle):
    """Per-IP rate limit for POST /api/visits/register/ (avoids spam)."""

    scope = "register_visit"

    def get_cache_key(self, request, view):
        ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class PublicBookingRateThrottle(SimpleRateThrottle):
    """Per-IP limit for the anonymous pre-booking endpoints.

    The booking form fires several reads (context, hosts) before submission,
    so the read/write budget must be generous enough for a legitimate booking
    while still protecting the public API from abuse.
    """

    scope = "public_booking"

    def get_cache_key(self, request, view):
        ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class LoginRateThrottle(SimpleRateThrottle):
    """Per-IP limit for staff sign-in.

    The account lockout (5 strikes / 15 min) protects a password; this limit
    protects *other people's* accounts from being locked on purpose by an
    attacker hammering the endpoint (audit finding "lockout is account-based").
    """

    scope = "login"

    def get_cache_key(self, request, view):
        ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class VisitorAuthThrottle(SimpleRateThrottle):
    """Per-IP limit for visitor-account sign-up and sign-in."""

    scope = "visitor_auth"

    def get_cache_key(self, request, view):
        ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}
