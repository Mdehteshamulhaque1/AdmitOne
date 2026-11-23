"""
AdmitOne — multi-tenant access-control platform with HMAC-signed single-use QR passes.

Django settings. Kept clean for a demoable MVP that can grow into the full spec.
"""

import os
import sys

import dj_database_url
from datetime import timedelta
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.validators import validate_email
from dotenv import load_dotenv

from .env import env_bool, env_int, env_list, env_str

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env for local development (Render/Vercel inject real env vars).
# Tests that boot the settings in a fresh process set ADMITONE_IGNORE_DOTENV=1
# so a developer's own .env (e.g. their Gmail details) cannot leak into them.
if os.environ.get("ADMITONE_IGNORE_DOTENV") != "1":
    load_dotenv(BASE_DIR / ".env")


# ---------------------------------------------------------------------------
# Core settings
#
# Secure-by-default: production guards fire ONLY when DJANGO_ENV is explicitly
# set to "production" on the server (Render / Vercel).  Local development and
# tests run with the "development" default — no special env vars required as
# long as you have copied .env.example to .env.
# ---------------------------------------------------------------------------

# Strips and accepts 1/yes/on as well as true/false. The old
# `os.environ.get("DJANGO_DEBUG", "False").lower() == "true"` silently yielded
# False for "true " (trailing space) and for "1", so a deployment that meant to
# enable debug did not -- and one that meant to disable it could not be sure
# it had.
DEBUG = env_bool("DJANGO_DEBUG", False)
ENVIRONMENT = os.environ.get("DJANGO_ENV", "development")

# ---------------------------------------------------------------------------
# Secret key — never ship a hardcoded value to production.
# ---------------------------------------------------------------------------
if ENVIRONMENT == "production":
    SECRET_KEY = os.environ.get("SECRET_KEY")
    if (
        not SECRET_KEY
        or SECRET_KEY in {"your-super-secret-key-change-me", "dev-only-insecure-secret-do-not-deploy"}
    ):
        raise ImproperlyConfigured(
            "SECRET_KEY is required in production. Generate one with:\n"
            '  python -c "import secrets; print(secrets.token_urlsafe(50))"'
        )
else:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-insecure-secret-do-not-deploy")

# ---------------------------------------------------------------------------
# QR pass signing key -- deliberately NOT SECRET_KEY.
#
# SECRET_KEY also signs sessions, CSRF tokens, password-reset tokens and JWTs,
# so reusing it for visitor passes means a compromise of one breaks both, and
# rotating it (the normal response to a suspected leak) would invalidate every
# outstanding pass.  A dedicated key can be rotated on its own schedule; see
# ``visits/signing.py`` for the key-ring procedure and
# docs/DEPLOYMENT.md for the rollout.
# ---------------------------------------------------------------------------
QR_PASS_VALID_MINUTES = int(os.environ.get("QR_PASS_VALID_MINUTES", "120"))
QR_SIGNING_KEY_ID = os.environ.get("QR_SIGNING_KEY_ID", "k1")
QR_SIGNING_KEY = os.environ.get("QR_SIGNING_KEY", "")
QR_SIGNING_PREVIOUS_KEYS = os.environ.get("QR_SIGNING_PREVIOUS_KEYS", "")

# Key that verifies passes minted before the dedicated key existed. Those
# signatures used SECRET_KEY, so that is the default. Empty it once no live pass
# predates the upgrade -- that removes the legacy verification path entirely.
QR_SIGNING_LEGACY_KEY = os.environ.get("QR_SIGNING_LEGACY_KEY", SECRET_KEY)

if ENVIRONMENT == "production":
    # Fail closed. Deriving the key from SECRET_KEY in production would keep
    # the coupling this setting exists to break, and a missing value that
    # silently fell back to a default would be indistinguishable from a real key.
    if not QR_SIGNING_KEY or QR_SIGNING_KEY in {
        "change-me",
        "dev-only-insecure-secret-do-not-deploy",
    }:
        raise ImproperlyConfigured(
            "QR_SIGNING_KEY is required in production (QR passes must not be "
            "signed with SECRET_KEY). Generate one with:\n"
            '  python -c "import secrets; print(secrets.token_urlsafe(50))"\n'
            "Rotate by adding the new key to QR_SIGNING_PREVIOUS_KEYS first, "
            "then setting QR_SIGNING_KEY to the new value."
        )
    if QR_SIGNING_KEY == SECRET_KEY:
        raise ImproperlyConfigured(
            "QR_SIGNING_KEY must differ from SECRET_KEY; a shared key couples "
            "QR signing to session and JWT signing."
        )
else:
    # Local development and tests: derive a distinct, non-SECRET_KEY key so the
    # code path exercised locally is the one that runs in production.
    QR_SIGNING_KEY = os.environ.get("QR_SIGNING_KEY") or "dev-only-qr-signing-key"

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS") or ["127.0.0.1", "localhost"]
if ENVIRONMENT == "production" and ALLOWED_HOSTS == ["127.0.0.1", "localhost"]:
    raise ImproperlyConfigured(
        "ALLOWED_HOSTS must be set in production "
        "(e.g. your-domain.onrender.com)."
    )

# CSRF / CORS for cross-origin frontend (Vercel)
#
# env_list() strips each element. A plain .split(",") leaves a leading space on
# every value after the first, and neither django.middleware.csrf nor
# corsheaders strips it before comparing -- so
#
#   CSRF_TRUSTED_ORIGINS="https://a.app, https://b.app"
#
# would configure the first origin and silently ignore the second. The failure
# is invisible: the setting looks populated and the origin that was supposed to
# be trusted is not.
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")
CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS")
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_CREDENTIALS = True


# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # Third-party
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",

    # Local apps
    "accounts",
    "organizations",
    "visits",
    "reports",
    "api",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "config.middleware.ContentSecurityPolicyMiddleware",  # CSP header (prod only)
    "whitenoise.middleware.WhiteNoiseMiddleware",  # Static files in production
    "corsheaders.middleware.CorsMiddleware",       # CORS headers
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# Database
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases
#
# Production uses Supabase (PostgreSQL) via DATABASE_URL. Session Pooler example
# (placeholders only — never commit real credentials):
#   postgresql://postgres.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres
#
# dj-database-url honours ?sslmode=require in the URL, and we also force it
# whenever a Postgres engine is selected (Supabase requires TLS).
# Local development without DATABASE_URL falls back to SQLite.
# In production DATABASE_URL is required — never silently fall back to SQLite.

# An *empty* DATABASE_URL (``DATABASE_URL=`` left blank in .env, which is how
# .env.example ships it) must mean "not configured", not "configured as
# nothing": dj-database-url returns ``{}`` for an empty string and settings
# then died with a bare ``KeyError: 'ENGINE'`` that said nothing about the
# cause. Treat blank as unset so the SQLite fallback (dev) or the production
# guard below (prod) applies, each with its own clear message.
_DATABASE_URL = (os.environ.get("DATABASE_URL") or "").strip()
_SQLITE_FALLBACK = f"sqlite:///{BASE_DIR / 'db.sqlite3'}"

DATABASES = {
    "default": dj_database_url.parse(
        _DATABASE_URL or _SQLITE_FALLBACK,
        conn_max_age=600,
        conn_health_checks=True,
    )
}
if not DATABASES["default"].get("ENGINE"):
    raise ImproperlyConfigured(
        "DATABASE_URL could not be parsed. Expected a URL such as "
        "postgresql://user:password@host:5432/dbname?sslmode=require"
    )

if DATABASES["default"]["ENGINE"].startswith("django.db.backends.postgresql"):
    DATABASES["default"].setdefault("OPTIONS", {})
    # Supabase's transaction/session pooler URLs append ?pgbouncer=&connection_limit=
    # query params. dj-database-url folds those into OPTIONS, but psycopg does not
    # understand them and would raise an invalid-connection-option error — drop them.
    for _key in ("pgbouncer", "connection_limit"):
        DATABASES["default"]["OPTIONS"].pop(_key, None)
    # Respect an explicit sslmode; default to require (Supabase mandates TLS).
    DATABASES["default"]["OPTIONS"].setdefault(
        "sslmode", os.environ.get("POSTGRES_SSL_MODE", "require")
    )

if ENVIRONMENT == "production" and not DATABASES["default"]["ENGINE"].startswith(
    "django.db.backends.postgresql"
):
    raise ImproperlyConfigured(
        "DATABASE_URL is required in production (Supabase PostgreSQL). Set the "
        "DATABASE_URL environment variable on Render — the SQLite fallback is "
        "only for local development."
    )


# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# WhiteNoise for compressed, cached static files in production
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# Visitor identity documents (ID scans, passports) are a different class of
# file from the rest of MEDIA_ROOT and are never served from a public URL.
#
# MEDIA_ROOT is exposed by a URL in development (see config/urls.py) and would
# be served by a CDN or the web server in production, so anything under it is
# effectively public. Documents therefore live in a separate root that no URL
# pattern points at, and are reached only through the authorized download view
# (`visits:document`). The storage backend has no `base_url` at all, so a
# stray `{{ field.url }}` in a template raises instead of quietly publishing an
# ID scan to anyone who guesses the path.
#
# In production, point PRIVATEMEDIA_ROOT at a persistent volume and serve it
# only through that view (or move `visits.storage.private_document_storage` to
# a private S3 bucket and hand out short-lived signed URLs -- see
# docs/DEPLOYMENT.md).
PRIVATEMEDIA_ROOT = BASE_DIR / "private_media"

# Ceilings for visitor uploads. The default storage backend is unbuffered and
# writes straight to disk, so the limits are enforced in
# `visits.validators`, not by a web server.
MAX_UPLOAD_IMAGE_BYTES = 5 * 1024 * 1024   # visitor photos, avatars, logos
MAX_UPLOAD_DOCUMENT_BYTES = 10 * 1024 * 1024  # ID scans

# Custom user model
AUTH_USER_MODEL = "accounts.User"

# Only the Django admin uses session login now; the SPA and visitors use tokens.
LOGIN_URL = "/admin/login/"
LOGIN_REDIRECT_URL = "/admin/"

# Every login path (session + JWT) goes through LockoutBackend so the
# 5-failed-attempts lockout cannot be bypassed via a different endpoint.
AUTHENTICATION_BACKENDS = ["accounts.backends.LockoutBackend"]

# Account lockout: 5 failed attempts -> 15 minute lock
MAX_LOGIN_ATTEMPTS = 5
ACCOUNT_LOCKOUT_MINUTES = 15

# Password hashing — Argon2 is the active default (argon2-cffi pinned in
# requirements.txt). PBKDF2 stays as a Django built-in compatibility hasher.
# bcrypt is intentionally NOT listed: this app has no legacy accounts that
# store bcrypt hashes, so the optional dependency would be dead weight and a
# stray bcrypt hash would crash login if the library were ever missing.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

# Django REST Framework
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    # The browsable renderer ships an interactive HTML page that will issue
    # GET/POST/PUT/DELETE against any endpoint on the page, acting as whoever
    # opened it, and it echoes the response body into that page. In production
    # that is a self-service mutation surface plus a reconnaissance page that
    # enumerates the API, for no benefit: the SPA fetches JSON, and the
    # operations console talks to HTML views. The failure mode when this leaks
    # into production is not obvious -- endpoints keep working, so nobody
    # notices a second, undocumented way to drive them.
    "DEFAULT_RENDERER_CLASSES": (
        ("rest_framework.renderers.JSONRenderer",
         "rest_framework.renderers.BrowsableAPIRenderer")
        if ENVIRONMENT != "production"
        else ("rest_framework.renderers.JSONRenderer",)
    ),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "PAGE_SIZE_QUERY_PARAM": "page_size",
    "MAX_PAGE_SIZE": 1000,
    "DEFAULT_THROTTLE_CLASSES": (
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ),
    "DEFAULT_THROTTLE_RATES": {
        "anon": "100/hour",
        "user": "1000/hour",
        "register_visit": "10/min",
        "public_booking": "20/min",
        "visitor_auth": "15/min",
        # Per-IP staff sign-in limit. Relaxed under the test runner because
        # every test signs in from 127.0.0.1 and the suite would throttle
        # itself; the dedicated throttle test pins the real rate explicitly.
        "login": "100000/min" if "test" in sys.argv else "20/min",
    },
}

SIMPLE_JWT = {
    # Short-lived: the SPA keeps tokens in localStorage, so a leaked access
    # token must stop working quickly. Refresh rotation keeps users signed in.
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
    # Record ``last_login`` on JWT sign-in too, so the Team page's
    # "last sign-in" column reflects SPA logins and not only console sessions.
    "UPDATE_LAST_LOGIN": True,
}

# Logging: ensure every 500/exception is printed to the service logs (Render).
# Without this, DEBUG=False hides tracebacks and deployments are hard to debug.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "WARNING",
    },
    "loggers": {
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
    },
}

# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Email
#
# The QR pass is delivered by mail, so a misconfigured mailer is a broken
# product, not a cosmetic problem. In development the console backend is kept
# (it prints to the terminal and needs no credentials); in production it is
# rejected outright, because every non-delivering backend Django ships with
# fails *silently* -- send() returns 0, no exception is raised, and approval
# flows report success while the visitor never receives their pass.
#
# `visits.emails.send_qr_pass_email` is the only thing that turns a delivery
# failure into a log line, so the guard below is the thing standing between a
# misconfigured deploy and thousands of undelivered passes.
# ---------------------------------------------------------------------------

# Backends that complete without delivering anything. In production each of
# these turns "the mail server is down" into "everything is fine".
NON_DELIVERING_EMAIL_BACKENDS = frozenset({
    "django.core.mail.backends.console.EmailBackend",
    "django.core.mail.backends.locmem.EmailBackend",
    "django.core.mail.backends.filebased.EmailBackend",
    "django.core.mail.backends.dummy.EmailBackend",
})

# Development sends real mail as soon as SMTP credentials are filled in (for
# example a Gmail address + App Password in backend/.env) and prints mail to
# the console otherwise. Production always uses SMTP and is validated below.
_SMTP_CREDENTIALS_SET = bool(os.environ.get("EMAIL_HOST_USER", "").strip() and os.environ.get("EMAIL_HOST_PASSWORD", "").strip())
_EMAIL_DEFAULT_BACKEND = (
    "django.core.mail.backends.smtp.EmailBackend"
    if ENVIRONMENT == "production" or _SMTP_CREDENTIALS_SET
    else "django.core.mail.backends.console.EmailBackend"
)

EMAIL_BACKEND = env_str("EMAIL_BACKEND", _EMAIL_DEFAULT_BACKEND)
EMAIL_HOST = env_str("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = env_int("EMAIL_PORT", 587, minimum=1, maximum=65535)
# Case-insensitive, and an unrecognised value is an error rather than False.
# EMAIL_USE_TLS=false silently sends SMTP credentials in cleartext, which is
# exactly the sort of misconfiguration that must not be able to happen quietly.
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", False)
EMAIL_TIMEOUT = env_int("EMAIL_TIMEOUT", 30, minimum=1, maximum=600)
EMAIL_HOST_USER = env_str("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = env_str("DEFAULT_FROM_EMAIL") or EMAIL_HOST_USER or ""
SERVER_EMAIL = DEFAULT_FROM_EMAIL or "webmaster@localhost"

# Backends that must not be trusted to deliver in production, and the SMTP
# settings that have to be coherent for one to work at all.
# WhatsApp delivery of QR passes (visits/whatsapp.py). Off unless
# WHATSAPP_PROVIDER=meta and the Cloud API credentials are set.
WHATSAPP_PROVIDER = env_str("WHATSAPP_PROVIDER", "")
WHATSAPP_ACCESS_TOKEN = os.environ.get("WHATSAPP_ACCESS_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = env_str("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_TEMPLATE_NAME = env_str("WHATSAPP_TEMPLATE_NAME", "visitor_pass_approved")
WHATSAPP_TEMPLATE_LANGUAGE = env_str("WHATSAPP_TEMPLATE_LANGUAGE", "en")
WHATSAPP_API_VERSION = env_str("WHATSAPP_API_VERSION", "v21.0")
WHATSAPP_DEFAULT_COUNTRY_CODE = env_str("WHATSAPP_DEFAULT_COUNTRY_CODE", "91")

_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]"}
_SMTP_LOCAL_HOSTS = _LOOPBACK_HOSTS | {"smtp", "mail", "sendmail", "postfix", "exim"}


def _validate_production_email():
    """Refuse to boot production with an email configuration that cannot work.

    Raises ``ImproperlyConfigured`` with every problem listed at once, so an
    operator does not fix them one deploy at a time. Called at import time, so
    the failure happens before the server accepts a request rather than at the
    first approval.
    """
    problems = []

    if EMAIL_BACKEND in NON_DELIVERING_EMAIL_BACKENDS:
        problems.append(
            f"EMAIL_BACKEND={EMAIL_BACKEND} does not send mail. In production "
            "use django.core.mail.backends.smtp.EmailBackend; a non-delivering "
            "backend makes every notification a silent no-op."
        )
    elif not EMAIL_BACKEND.endswith(".smtp.EmailBackend") and "smtp" not in EMAIL_BACKEND:
        problems.append(
            f"EMAIL_BACKEND={EMAIL_BACKEND} is not a recognised delivery backend. "
            "Expected django.core.mail.backends.smtp.EmailBackend."
        )

    if not os.environ.get("EMAIL_HOST", "").strip():
        problems.append(
            "EMAIL_HOST is not set. The default (smtp.gmail.com) is a guess, "
            "not a configuration."
        )
    elif not EMAIL_HOST:
        problems.append("EMAIL_HOST resolved to an empty value.")

    if EMAIL_USE_TLS and EMAIL_USE_SSL:
        problems.append(
            "EMAIL_USE_TLS and EMAIL_USE_SSL are both enabled. Django's SMTP "
            "backend already starts a TLS socket for SSL; set EMAIL_USE_TLS=false."
        )
    if EMAIL_USE_SSL and EMAIL_PORT != 465:
        problems.append(
            f"EMAIL_USE_SSL is enabled but EMAIL_PORT={EMAIL_PORT} is not 465, "
            "the implicit-TLS port."
        )

    # Unencrypted credentials to a remote relay is the failure this check exists
    # for. A local MTA needs neither TLS nor a password.
    is_local = EMAIL_HOST.lower() in _SMTP_LOCAL_HOSTS
    if not is_local:
        if not (EMAIL_USE_TLS or EMAIL_USE_SSL):
            problems.append(
                "Neither EMAIL_USE_TLS nor EMAIL_USE_SSL is enabled for a remote "
                f"host ({EMAIL_HOST}). SMTP credentials would cross the network "
                "in cleartext."
            )
        if not EMAIL_HOST_USER:
            problems.append(
                "EMAIL_HOST_USER is not set. The remote host "
                f"({EMAIL_HOST}) will reject unauthenticated delivery."
            )
        if not EMAIL_HOST_PASSWORD:
            problems.append(
                "EMAIL_HOST_PASSWORD is not set. The remote host "
                f"({EMAIL_HOST}) will reject unauthenticated delivery."
            )

    if not DEFAULT_FROM_EMAIL:
        problems.append(
            "DEFAULT_FROM_EMAIL is not set. Every outbound message needs a "
            "From address, and most relays reject mail without one."
        )
    else:
        try:
            validate_email(DEFAULT_FROM_EMAIL)
        except ValidationError:
            problems.append(f"DEFAULT_FROM_EMAIL={DEFAULT_FROM_EMAIL!r} is not a valid address.")

    if problems:
        raise ImproperlyConfigured(
            "Production email configuration is invalid:\n"
            + "\n".join(f"  - {p}" for p in problems)
            + "\n\nSee docs/DEPLOYMENT.md for the full list."
        )


if ENVIRONMENT == "production":
    _validate_production_email()


# Security headers — only active in production (DJANGO_ENV=production).
if ENVIRONMENT == "production":
    # Render sits behind its own proxy, so request.is_secure() must trust the
    # forwarded scheme, otherwise SECURE_SSL_REDIRECT would loop.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
    SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
    # Content-Security-Policy for the only HTML this backend still serves: the
    # Django admin (self-hosted assets) and the e-mail/404 pages. The SPA has
    # its own policy in frontend/vercel.json. No remote scripts, styles or fonts.
    CSP_DEFAULT_SRC = ("'self'",)
    CSP_SCRIPT_SRC = ("'self'",)
    CSP_STYLE_SRC = ("'self'", "'unsafe-inline'")  # admin uses inline style attributes
    CSP_FONT_SRC = ("'self'", "data:")
    CSP_IMG_SRC = ("'self'", "data:")
    CSP_MEDIA_SRC = ("'self'",)
    CSP_CONNECT_SRC = ("'self'",)
    CSP_FORM_ACTION = ("'self'",)
    CSP_BASE_URI = ("'self'",)
    CSP_FRAME_ANCESTORS = ("'none'",)
    CONTENT_SECURITY_POLICY = {
        "DIRECTIVES": {
            "default-src": CSP_DEFAULT_SRC,
            "script-src": CSP_SCRIPT_SRC,
            "style-src": CSP_STYLE_SRC,
            "font-src": CSP_FONT_SRC,
            "img-src": CSP_IMG_SRC,
            "media-src": CSP_MEDIA_SRC,
            "connect-src": CSP_CONNECT_SRC,
            "form-action": CSP_FORM_ACTION,
            "base-uri": CSP_BASE_URI,
            "frame-ancestors": CSP_FRAME_ANCESTORS,
        }
    }
