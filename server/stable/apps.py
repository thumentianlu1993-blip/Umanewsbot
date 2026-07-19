from django.apps import AppConfig


class StableConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "stable"
    verbose_name = "赛马新闻后台"

    def ready(self) -> None:
        from .services.internal_controls import (
            validate_internal_media_configuration,
            validate_internal_transport_configuration,
        )

        validate_internal_transport_configuration()
        validate_internal_media_configuration()
        from . import signals  # noqa: F401
