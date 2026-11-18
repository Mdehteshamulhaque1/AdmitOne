from ipaddress import ip_address

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.utils import timezone


def _behind_trusted_proxy(remote):
    """True when REMOTE_ADDR is loopback/private — i.e. a reverse proxy
    (Render) terminates the connection, not an internet client directly."""
    try:
        ip = ip_address(remote)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private or ip.is_link_local


def client_ip(request):
    """Best-effort client IP, honoring a proxy chain.

    ``X-Forwarded-For`` is trusted ONLY when the request truly arrived via a
    proxy (REMOTE_ADDR is loopback/private) and only the RIGHT-MOST hop is
    used — the value appended by the trusted proxy that talks to this app.
    The left-hand hops are attacker-controlled and are never recorded as the
    acting IP, which keeps audit attribution honest.
    """
    remote = (request.META.get("REMOTE_ADDR") or "").strip()
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    hops = [h.strip() for h in forwarded.split(",") if h.strip()]
    if hops and remote and _behind_trusted_proxy(remote):
        return hops[-1]
    return remote or None


def org_timezone(user_or_org):
    """Return the ``ZoneInfo`` for the organisation, falling back to UTC."""
    org = getattr(user_or_org, "organization", None) or user_or_org
    raw = getattr(org, "timezone", None) or "UTC"
    try:
        return ZoneInfo(raw)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def org_localdate(user_or_org, when=None):
    """Date in the organisation's local timezone (default = now)."""
    tz = org_timezone(user_or_org)
    when = when or timezone.now()
    return timezone.localtime(when, timezone=tz).date()