from django.apps import AppConfig


class UserauthConfig(AppConfig):
    name = 'userauth'

    def ready(self):
        # Ensure signal handlers are registered on startup.
        from . import signals  # noqa: F401
