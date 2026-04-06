from django.apps import AppConfig


class StableConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "stable"
    verbose_name = "赛马新闻后台"
