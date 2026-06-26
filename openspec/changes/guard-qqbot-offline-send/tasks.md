## 1. OneBot 离线防护实现

- [x] 1.1 (application) 在 `server/stable/tests.py` 中新增自动 QQ 交付测试，覆盖 OneBot `online=false` 时不调用 `/send_group_msg`、不增加 `attempt_count`、记录离线错误摘要。
- [x] 1.2 (application) 在 `server/stable/tests.py` 中新增自动 QQ 交付测试，覆盖 OneBot 状态检查异常时不调用 `/send_group_msg`、不增加 `attempt_count`、记录状态检查失败摘要。
- [x] 1.3 (application) 在 `server/stable/tests.py` 中新增自动 QQ 交付测试，覆盖 OneBot 从离线恢复在线后可继续正常发送。
- [x] 1.4 (integration) 在 `server/stable/services/onebot.py` 中新增 OneBot 在线状态检查封装，复用 token、超时、响应校验和错误脱敏。
- [x] 1.5 (integration) 在 `server/stable/services/qq_auto_push.py` 中把 OneBot 在线检查接入自动交付发送前路径，确保离线时不 claim attempt、不调用发送接口，并保留可恢复状态。

## 2. 文档与验证

- [x] 2.1 (operations) 更新 `docs/current_state.md`、`docs/deploy_runbook.md` 和 `docs/project_status.md`，记录 2026-06-26 QQ 登录态失效事故、恢复步骤和离线防护语义。
- [x] 2.2 (application) 运行 QQ 自动推送目标测试，确认新增测试通过。
- [x] 2.3 (application) 运行 `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable`。
- [x] 2.4 (operations) 运行 `openspec validate guard-qqbot-offline-send --strict`、`openspec validate --all` 和 `git diff --check`。
- [x] 2.5 (operations) 部署后确认生产 `QQ_PUSH_ENABLED=true`、OneBot `/get_status online=true`、测试群发送成功、`/healthz/` 返回 `200`。
