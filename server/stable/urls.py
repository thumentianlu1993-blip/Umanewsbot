from django.urls import path

from . import views

urlpatterns = [
    path("articles/", views.article_list_api, name="api-article-list"),
    path("articles/<int:article_id>/", views.article_detail_api, name="api-article-detail"),
    path("articles/<int:article_id>/update/", views.article_update_api, name="api-article-update"),
    path("articles/<int:article_id>/push/", views.article_push_api, name="api-article-push"),
    path("tasks/", views.task_log_list_api, name="api-task-log-list"),
]
