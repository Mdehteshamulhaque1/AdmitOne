from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.db.models.functions import Lower


class Role(models.TextChoices):
    ADMIN = "ADMIN", "Admin"
    RECEPTIONIST = "RECEPTIONIST", "Receptionist"
    SECURITY = "SECURITY", "Security"


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", Role.ADMIN)
        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    """Custom user model. Login is email-based. Each user belongs to a single
    organization and has exactly one role (ADMIN, RECEPTIONIST or SECURITY).

    Account states
    --------------
    ``organization is None`` is a legitimate, *non-operational* state, not a
    broken one. A visitor-facing signup (the SPA's ``/signup``) creates such an
    account: enough to hold a JWT so the user can reach ``/onboarding`` and
    create the workspace that will make them its ADMIN. Until then the account
    must not be able to do operational work, and that is enforced by
    ``accounts.permissions.has_tenant`` rather than by the role column.

    The former ``is_email_verified`` flag was removed rather than enforced.
    Nothing ever read it -- registration set it to ``True`` immediately and no
    authentication path consulted it -- so while it sat in the admin next to the
    genuine lockout counters it read as an assurance the system did not
    actually provide. There is no e-mail verification flow in this project
    (no token, no endpoint, no expiry), so enforcing the flag would have locked
    every real user out. Access control here is role-based plus tenant-based;
    inventing a verification flow would be a new product feature, not a fix.
    """

    username = None
    email = models.EmailField("email address", unique=True)
    full_name = models.CharField(max_length=120)
    phone = models.CharField(max_length=20, blank=True)
    avatar = models.ImageField(upload_to="avatars/", blank=True, null=True)
    # Least privilege by default. The previous default was ``Role.ADMIN``,
    # which meant *any* code path that created a User without naming a role --
    # including the public registration endpoint -- silently produced an
    # administrator. A field default is the last line of defence, so it now
    # grants the weakest role in the model. Elevation happens in exactly one
    # place: ``api.views.OrganizationCreateView``, which attaches the caller to
    # a workspace they just created.
    role = models.CharField(
        max_length=20, choices=Role.choices, default=Role.RECEPTIONIST
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="users",
    )
    # Security / account lockout
    failed_login_attempts = models.PositiveIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    notification_preferences = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

    objects = UserManager()

    class Meta:
        constraints = [
            # ``LockoutBackend`` looks accounts up with ``email__iexact``; the
            # plain unique index on ``email`` is case-sensitive on PostgreSQL,
            # so without this two accounts differing only in case could exist
            # and make login ambiguous (audit finding "email normalization").
            models.UniqueConstraint(Lower("email"), name="uniq_user_email_ci"),
        ]

    def __str__(self):
        return f"{self.full_name} <{self.email}>"

    @property
    def is_locked(self):
        from django.utils import timezone

        return self.locked_until is not None and self.locked_until > timezone.now()

    def register_failed_attempt(self, settings):
        from datetime import timedelta

        from django.db.models import F
        from django.utils import timezone

        self.__class__.objects.filter(pk=self.pk).update(
            failed_login_attempts=F("failed_login_attempts") + 1
        )
        self.refresh_from_db(fields=["failed_login_attempts"])
        if self.failed_login_attempts >= settings.MAX_LOGIN_ATTEMPTS:
            locked_until = timezone.now() + timedelta(
                minutes=settings.ACCOUNT_LOCKOUT_MINUTES
            )
            self.__class__.objects.filter(pk=self.pk).update(
                locked_until=locked_until, failed_login_attempts=0
            )
            self.locked_until = locked_until
            self.failed_login_attempts = 0

    def reset_failed_attempts(self):
        self.__class__.objects.filter(pk=self.pk).update(
            failed_login_attempts=0, locked_until=None
        )
        self.failed_login_attempts = 0
        self.locked_until = None
