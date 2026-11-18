from django.apps import AppConfig


class VisitsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'visits'

    def ready(self):
        # Registers the document-storage deploy checks, so a misconfigured
        # private root is reported by `manage.py check --deploy` instead of
        # being discovered when a document link 404s in production.
        from . import checks  # noqa: F401
