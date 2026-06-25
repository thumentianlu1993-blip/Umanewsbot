## 1. ID URL 实现

- [x] 1.1 (application) 在 `server/stable/tests.py` 中新增公开 URL 测试，覆盖 `/news/<id>/` 可访问、未发布 ID 不可访问、非纯数字旧 slug 跳转、首页链接使用 ID URL
- [x] 1.2 (application) 将 `NewsArticle.public_path` 改为 `/news/<article_id>/`，并确保未保存对象不会生成无效公开链接
- [x] 1.3 (application) 调整 `server/app/urls.py` 和 `server/stable/views.py`，新增 ID 详情路由并保留旧 slug 路由跳转到 ID URL
- [x] 1.4 (application) 检查公开首页、热门列表、后台“前台查看”和 QQ 自动推送消息均通过 `article.public_path` 使用 ID URL

## 2. 验证

- [x] 2.1 (application) 运行公开 URL 相关 Django 测试，确认新增测试通过
- [x] 2.2 (application) 运行 `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable --noinput`
- [x] 2.3 (application) 运行 `openspec validate use-article-id-public-urls --strict`
- [x] 2.4 (operations) 本地或生产部署后抽检 `/news/<id>/`、非纯数字旧 `/news/<slug>/` 跳转、首页文章链接和 QQ 消息链接
  - 本地已通过 `PublicHomeInfoFeedTests` 与 `QQAutoPushTests` 覆盖；生产部署后仍按 `docs/deploy_runbook.md` 抽检真实运行态。
- [x] 2.5 (operations) 更新 `docs/current_state.md`、`docs/deploy_runbook.md` 和 `docs/project_status.md`，记录公开 URL 规则变更与旧链接兼容策略
