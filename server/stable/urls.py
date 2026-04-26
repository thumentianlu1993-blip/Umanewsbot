from django.urls import path

from . import views

urlpatterns = [
    path("login/", views.BackendLoginView.as_view(), name="backend-login"),
    path("logout/", views.BackendLogoutView.as_view(), name="backend-logout"),
    path("", views.console_dashboard, name="console-dashboard"),
    path("sources/", views.source_list, name="console-source-list"),
    path("sources/new/", views.source_create, name="console-source-create"),
    path("sources/<int:source_id>/edit/", views.source_edit, name="console-source-edit"),
    path("sources/<int:source_id>/toggle/", views.source_toggle, name="console-source-toggle"),
    path("sources/<int:source_id>/delete/", views.source_delete, name="console-source-delete"),
    path("sources/<int:source_id>/test-crawl/", views.source_test_crawl, name="console-source-test-crawl"),
    path("candidates/", views.candidate_list, name="console-candidate-list"),
    path("candidates/batch-retranslate/", views.candidate_batch_retranslate, name="console-candidate-batch-retranslate"),
    path("candidates/<int:article_id>/", views.candidate_detail, name="console-candidate-detail"),
    path("candidates/<int:article_id>/retranslate/", views.candidate_retranslate, name="console-candidate-retranslate"),
    path("candidates/<int:article_id>/ignore/", views.candidate_ignore, name="console-candidate-ignore"),
    path("articles/<int:article_id>/edit/", views.article_editor, name="console-article-editor"),
    path("articles/<int:article_id>/preview/", views.article_preview, name="console-article-preview"),
    path("articles/<int:article_id>/images/<int:image_id>/localize/", views.article_localize_image, name="console-article-localize-image"),
    path("articles/<int:article_id>/assets/<int:asset_id>/set-cover/", views.article_set_cover, name="console-article-set-cover"),
    path("articles/<int:article_id>/upload-cover/", views.article_upload_cover, name="console-article-upload-cover"),
    path("terms/", views.term_list, name="console-term-list"),
    path("terms/new/", views.term_create, name="console-term-create"),
    path("terms/import/", views.term_import, name="console-term-import"),
    path("terms/<int:term_id>/edit/", views.term_edit, name="console-term-edit"),
    path("terms/<int:term_id>/toggle/", views.term_toggle_active, name="console-term-toggle"),
    path("published/", views.published_list, name="console-published-list"),
    path("logs/", views.operation_log_list, name="console-log-list"),
]

