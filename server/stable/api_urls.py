from django.urls import path

from . import views

urlpatterns = [
    path("articles/", views.article_list_api, name="api-article-list"),
    path("articles/<int:article_id>/", views.article_detail_api, name="api-article-detail"),
    path("articles/<int:article_id>/translation-status/", views.article_translation_status_api, name="api-article-translation-status"),
    path("articles/<int:article_id>/retranslate/", views.article_retranslate_api, name="api-article-retranslate"),
    path("articles/<int:article_id>/update/", views.article_update_api, name="api-article-update"),
    path("articles/<int:article_id>/push/", views.article_push_api, name="api-article-push"),
    path("tasks/", views.task_log_list_api, name="api-task-log-list"),
    path("terms/", views.term_list_api, name="api-term-list"),
    path("terms/create/", views.term_create_api, name="api-term-create"),
    path("terms/<int:term_id>/", views.term_detail_api, name="api-term-detail"),
    path("terms/<int:term_id>/update/", views.term_update_api, name="api-term-update"),
    path("terms/<int:term_id>/toggle-active/", views.term_toggle_active_api, name="api-term-toggle-active"),
]
