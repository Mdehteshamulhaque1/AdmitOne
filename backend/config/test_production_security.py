"""Production security-header regressions.

Each test here corresponds to a defect that shipped:

* the console's Chart.js bootstrap, the html5-qrcode scanner and the badge
  print button were all blocked by the production CSP, so the dashboard chart
  and the camera scanner silently did nothing;
* the SPA on Vercel shipped only a ``Cache-Control`` for hashed assets -- no
  CSP, no HSTS, no ``nosniff``;
* the DRF browsable API renderer was enabled in production;
* the console's "Logout" link pointed at ``/admin/logout/``, which Django 5
  answers with **405** because its ``LogoutView`` is POST-only, so console
  users could not sign out at all.

The CSP assertions are deliberately written to fail if someone "fixes" the
chart by adding ``'unsafe-inline'`` to ``script-src``.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase


User = get_user_model()

FRONTEND = Path(__file__).resolve().parent.parent.parent / "frontend"

# The policy the application actually ships in production, copied from
# config/settings.py. If the real policy changes, this needs to change with it
# or these tests stop proving anything.
PRODUCTION_POLICY = {
    "DIRECTIVES": {
        "default-src": ("'self'",),
        "script-src": ("'self'", "https://cdn.jsdelivr.net", "https://unpkg.com"),
        "style-src": (
            "'self'", "'unsafe-inline'", "https://cdn.jsdelivr.net",
            "https://fonts.googleapis.com",
        ),
        "font-src": ("'self'", "https://fonts.gstatic.com", "https://cdn.jsdelivr.net", "data:"),
        "img-src": ("'self'", "data:", "blob:"),
        "media-src": ("'self'", "blob:"),
        "connect-src": ("'self'",),
        "form-action": ("'self'",),
        "base-uri": ("'self'",),
        "frame-ancestors": ("'none'",),
    }
}

NONCE_RE = re.compile(r"'nonce-([A-Za-z0-9_-]+)'")


def csp_of(response):
    return response.headers.get("Content-Security-Policy", "")


class SpaHeaderTests(SimpleTestCase):
    """vercel.json is the SPA's only header source, so it is checked as config."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = json.loads((FRONTEND / "vercel.json").read_text(encoding="utf-8"))
        cls.rules = {rule["source"]: rule["headers"] for rule in cls.config["headers"]}

    def _value(self, source, key):
        for header in self.rules[source]:
            if header["key"].lower() == key.lower():
                return header["value"]
        self.fail(f"{key} not set for {source}")

    def test_the_catch_all_rule_exists(self):
        self.assertIn("/(.*)", self.rules)

    def test_hsts_is_shipped(self):
        value = self._value("/(.*)", "Strict-Transport-Security")
        self.assertRegex(value, r"max-age=\d{6,}")
        self.assertIn("includeSubDomains", value)

    def test_nosniff_and_referrer_policy_are_shipped(self):
        self.assertEqual(self._value("/(.*)", "X-Content-Type-Options"), "nosniff")
        self.assertIn(
            "strict-origin", self._value("/(.*)", "Referrer-Policy")
        )

    def test_clickjacking_protection_is_shipped(self):
        self.assertEqual(self._value("/(.*)", "X-Frame-Options"), "DENY")
        self.assertIn("frame-ancestors 'none'", self._value("/(.*)", "Content-Security-Policy"))

    def test_permissions_policy_keeps_the_camera_self_only(self):
        # The scanner needs camera access, but only for this origin -- not for
        # any embedder.
        value = self._value("/(.*)", "Permissions-Policy")
        self.assertIn("camera=(self)", value)

    def test_the_spa_csp_is_not_permissive(self):
        csp = self._value("/(.*)", "Content-Security-Policy")
        directives = dict(
            part.split(" ", 1) for part in csp.split("; ") if " " in part
        )
        # A bare wildcard in any directive would undo the policy.
        for name, value in directives.items():
            for token in value.split():
                self.assertNotEqual(token, "*", f"{name} allows any origin")
        self.assertIn("'none'", directives["object-src"])
        self.assertNotIn("'unsafe-eval'", csp)
        self.assertNotIn("'unsafe-eval'", csp)
        # scripts must not be loosened to run arbitrary inline code
        self.assertEqual(directives["script-src"], "'self'")

    def test_the_spa_csp_allows_the_api_origin_for_xhr(self):
        # The SPA is on Vercel and the API on Render, so a 'self'-only
        # connect-src would break every request. The allowance must stay
        # scoped to the API's provider rather than opening up '*'.
        connect = dict(
            part.split(" ", 1) for part in self._value("/(.*)", "Content-Security-Policy").split("; ")
            if part.startswith("connect-src")
        )["connect-src"]
        self.assertIn("https://*.onrender.com", connect)

    def test_the_asset_cache_rule_survives(self):
        # The pre-existing immutable-asset caching must not be lost while
        # adding the security headers.
        value = self._value("/assets/(.*)", "Cache-Control")
        self.assertIn("immutable", value)


class BrowsableApiTests(SimpleTestCase):
    """The renderer list is built in settings.py at import time.

    ``override_settings(ENVIRONMENT=...)`` cannot exercise it, because the
    tuple is decided when settings are read, not per request -- so each case
    runs in a fresh process, as the email boot tests do.
    """

    SCRIPT = (
        "from django.conf import settings;"
        "print('|'.join(str(r) for r in settings.REST_FRAMEWORK['DEFAULT_RENDERER_CLASSES']))"
    )

    def _renderers_for(self, environment):
        env = {
            **os.environ,
            "DJANGO_ENV": environment,
            "DJANGO_SETTINGS_MODULE": "config.settings",
        }
        # A production boot needs the full set of guards satisfied before the
        # settings module finishes importing.
        env.update({
            "SECRET_KEY": "renderer-check-secret-not-a-placeholder-value",
            "ALLOWED_HOSTS": "securegate.example.com",
            "DATABASE_URL": "postgres://u:p@db.invalid:5432/securegate",
            "QR_SIGNING_KEY": "renderer-check-qr-signing-key",
            "EMAIL_HOST": "smtp.sendgrid.net",
            "EMAIL_HOST_USER": "apikey",
            "EMAIL_HOST_PASSWORD": "SG.secret",
            "DEFAULT_FROM_EMAIL": "no-reply@securegate.test",
            "ADMITONE_IGNORE_DOTENV": "1",
        })
        result = subprocess.run(
            [sys.executable, "-c", self.SCRIPT],
            capture_output=True, text=True, env=env, timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def test_the_browsable_renderer_is_absent_in_production(self):
        renderers = self._renderers_for("production")
        self.assertNotIn("BrowsableAPIRenderer", renderers)
        self.assertIn("JSONRenderer", renderers)

    def test_production_has_exactly_one_renderer(self):
        self.assertEqual(len(self._renderers_for("production").split("|")), 1)

    def test_the_browsable_renderer_is_kept_in_development(self):
        self.assertIn("BrowsableAPIRenderer", self._renderers_for("development"))


