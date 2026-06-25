## 1. 来源提升实现

- [x] 1.1 (application) 在 `server/stable/tests.py` 中新增来源提升测试，覆盖 `latest -> access`、`latest -> attention`、`access` 与 `attention` 不互相覆盖、榜单来源不被 `latest` 覆盖
- [x] 1.2 (integration) 在 `server/stable/services/ingestion.py` 中实现 netkeiba 榜单来源提升规则，并保持每次抓取继续创建 `NewsSnapshot`
- [x] 1.3 (integration) 来源提升时同步更新 `source_config`、`source_note`、`crawl_job` 和 `last_seen_at`，避免后台展示与自动化判断不一致
- [x] 1.4 (integration) 让入库结果暴露 `source_elevated` 或等价稳定信号，供后续 QQ 推送逻辑判断已公开文章刚刚成为榜单重点新闻

## 2. 验证

- [x] 2.1 (application) 运行来源提升相关 Django 测试，确认新增测试通过
- [x] 2.2 (application) 运行 `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable --noinput`，当前完整 `stable` 测试已通过（168 tests OK）
- [x] 2.3 (application) 运行 `openspec validate elevate-ranked-netkeiba-sources --strict`
- [x] 2.4 (operations) 更新 `docs/current_state.md` 和 `docs/project_status.md`，记录来源提升规则和后续观察点
