## 1. 重点推送实现

- [x] 1.1 (application) 在 `server/stable/tests.py` 中新增 QQ 推送资格测试，覆盖 `QQ_PUSH_IMPORTANCE_STRATEGY=ranked` 下访问量榜可推、注目数榜可推、新着顺在 `high_value_only` 下不推、`all_public` 仍可推、非法策略值回退到 `ranked`
- [x] 1.2 (integration) 在 `server/app/settings.py` 和 `server/stable/services/qq_auto_push.py` 增加重点推送策略配置读取与归一化，本期支持 `QQ_PUSH_IMPORTANCE_STRATEGY=ranked`，并使其以 `netkeiba:access` 和 `netkeiba:attention` 作为榜单重点新闻口径
- [x] 1.3 (integration) 确保结构化 blocker、未公开、公开 URL 不可访问的文章不会成功发送；blocker 判定必须复用 `NewsArticle.gate_blockers` 或 `gate_issues.severity=blocker`，并保留现有错误记录语义
- [x] 1.4 (application) 读取来源提升子 change 暴露的 `source_elevated` 或等价稳定信号，在榜单来源提升后的已公开文章路径中触发 QQ 自动推送编排，并继续依靠 `QQPushDelivery(article, target)` 唯一约束避免重复发送

## 2. 配置与验证

- [x] 2.1 (application) 运行 QQ 自动推送相关 Django 测试，确认新增测试通过
- [x] 2.2 (application) 运行 `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable --noinput`，当前完整 `stable` 测试已通过（168 tests OK）
- [x] 2.3 (application) 运行 `openspec validate push-ranked-news-to-qq --strict`
- [x] 2.4 (application) 运行 `openspec validate --all` 和 `git diff --check`
- [x] 2.5 (operations) 更新 `docs/qqbot_setup.md`、`docs/current_state.md` 和 `docs/deploy_runbook.md`，说明生产推荐 `QQ_PUSH_SCOPE=high_value_only`、`QQ_PUSH_IMPORTANCE_STRATEGY=ranked`，且本期重点策略表示 netkeiba 访问量榜 / 注目数榜新闻
- [x] 2.6 (operations) 部署后将生产 `.env` 中 `QQ_PUSH_SCOPE` 从测试期 `all_public` 切换为 `high_value_only`，设置 `QQ_PUSH_IMPORTANCE_STRATEGY=ranked`；生产 worker 已确认读取 `QQ_PUSH_ENABLED=true`、`QQ_PUSH_SCOPE=high_value_only`、`QQ_PUSH_IMPORTANCE_STRATEGY=ranked`，后续等待自然榜单新闻触发测试群推送
- [x] 2.7 (operations) 本 change 完成并准备归档前，确认 `add-qqbot-auto-push` 已同步或归档为正式 `qqbot-auto-push` 规格；本轮需求完成后提醒维护者尽可能归档其他已完成的 active change
