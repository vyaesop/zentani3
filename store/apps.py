from django.apps import AppConfig


class StoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'store'

    def ready(self):
        # Register custom deployment checks.
        from . import checks  # noqa: F401
        from . import signals  # noqa: F401
