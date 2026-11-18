"""Content-Security-Policy middleware.

Emits a ``Content-Security-Policy`` response header built from the
``CONTENT_SECURITY_POLICY`` dict in settings. The dict is only defined in
production (``DJANGO_ENV=production``); in development no header is added so
local debugging is left untouched.

Nonces
------
The console has three inline scripts that cannot move to a static file without
a restructure: the Chart.js bootstrap, the html5-qrcode camera scanner, and a
print button. They are exempted with a per-request **nonce** rather than by
adding ``'unsafe-inline'`` to ``script-src``.

That distinction is the whole point. ``'unsafe-inline'`` re-permits every inline
script on the page, which is exactly the XSS sink the policy exists to close --
and this app renders visitor-supplied text (names, purposes, rejection reasons)
into the same pages. A nonce authorises only the scripts this server emitted for
this one response: an injected ``<script>`` has no way to guess it, because the
value is generated per request after the injection point.

The nonce is exposed to templates as ``csp_nonce`` via
``config.context_processors.csp_nonce``.
"""

import secrets

from django.conf import settings

# Attribute holding the per-request nonce on the HttpRequest.
NONCE_ATTR = "csp_nonce"

# Where the nonce goes. Adding it anywhere else would be pointless (a nonce is
# a script-execution authorisation) or actively harmful.
NONCE_DIRECTIVES = frozenset({"script-src"})


class ContentSecurityPolicyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        policy = getattr(settings, "CONTENT_SECURITY_POLICY", None)
        directives = (policy or {}).get("DIRECTIVES", {})
        self.directives = {k: list(v) for k, v in directives.items() if v}
        self.enabled = bool(self.directives)

    def _header_for(self, nonce):
        parts = []
        for directive, values in self.directives.items():
            if directive in NONCE_DIRECTIVES:
                values = [*values, f"'nonce-{nonce}'"]
            parts.append(" ".join([directive, *values]))
        return "; ".join(parts)

    def __call__(self, request):
        # Generated per request, before the view, so the template that renders
        # the response can read it. Unconditionally, not only in production:
        # the templates reference it unconditionally, and one
        # token_urlsafe() call is cheaper than two template code paths.
        nonce = secrets.token_urlsafe(16)
        setattr(request, NONCE_ATTR, nonce)

        response = self.get_response(request)
        if self.enabled:
            # setdefault, not assignment: a view that wants to send a stricter
            # policy of its own (e.g. one without the CDN hosts) keeps it.
            response.setdefault("Content-Security-Policy", self._header_for(nonce))
        return response
