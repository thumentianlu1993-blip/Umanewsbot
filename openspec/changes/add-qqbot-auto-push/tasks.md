## 1. 数据模型与配置

- [x] 1.1 (application) 新增自动 QQ 推送状态枚举和 `QQPushDelivery` 或等价模型，字段覆盖文章、目标群、状态、尝试次数、最大尝试次数、最近错误类型、错误、OneBot 响应、最后尝试时间和成功时间，并添加 `article + target` 唯一约束。
- [x] 1.2 (application) 生成并检查 Django 迁移，确保 PostgreSQL 与 SQLite 均可应用，且不改变现有 `PushTarget`、`PushLog` 的手动推送语义。
- [x] 1.3 (application) 在 `server/app/settings.py` 新增 `QQ_PUSH_ENABLED`、`QQ_PUSH_SCOPE`、`QQ_PUSH_MAX_ATTEMPTS`、`QQ_PUSH_URL_CHECK_TIMEOUT_SECONDS`、`ONEBOT_TIMEOUT_SECONDS` 等配置读取，默认自动推送关闭、范围为 `high_value_only`、最大重试 3 次。

## 2. 推送服务与任务编排

- [x] 2.1 (integration) 新增自动推送服务函数，封装公开 URL 构造、URL 可访问检查、范围策略判断、目标群读取和交付记录创建/复用；高价值判断固定使用 `score_total >= AUTO_REVIEW_THRESHOLD`，自动目标群只读取 `is_active=True`。
- [x] 2.2 (integration) 新增自动推送消息模板生成逻辑，使用 `【UmaFans】`、有效标题、有效摘要或正文截断摘要、`阅读全文` 站内链接，并保证摘要为空时追加 `……`。
- [x] 2.3 (integration) 调整 OneBot HTTP 客户端支持可配置超时，并确保错误日志与异常信息不泄露 `ONEBOT_ACCESS_TOKEN`。
- [x] 2.4 (application) 新增 Celery 编排任务和单条交付任务，实现公开 URL 检查、幂等去重、成功状态回写、失败状态回写和有限重试。
- [x] 2.5 (application) 将人工发布入口和自动发布入口统一接入自动 QQ 推送入队函数，确保发布动作只入队、不同步调用 OneBot。

## 3. 后台可见性与兼容

- [x] 3.1 (application) 在 Django Admin 注册自动 QQ 推送交付模型，支持按状态、目标群、文章和时间筛选，并只读展示错误、尝试次数、OneBot 响应和成功时间。
- [x] 3.2 (application) 保持现有手动推送入口可用，确认 `QQ_PUSH_ENABLED=false` 时不影响工作人员手动推送。
- [x] 3.3 (application) 在文章 Admin 内联或详情中展示自动推送交付记录，便于从单篇文章排查推送状态。

## 4. 运维配置与文档

- [x] 4.1 (operations) 更新 `.env.example`，补充自动 QQ 推送配置项、默认值和推荐生产灰度配置。
- [x] 4.2 (operations) 更新 `docker-compose.prod.yml` 与 `docker-compose.prod.lowcost.yml` 的 OneBot 示例，避免公网裸露 OneBot API，并说明仅 Docker 内网或 `127.0.0.1` 访问。
- [x] 4.3 (operations) 更新 `docs/qqbot_setup.md`，写明 NapCatQQ / OneBot v11 推荐路线、后台群配置步骤、测试群灰度步骤和常见失败排查。
- [x] 4.4 (operations) 更新 `docs/deploy_runbook.md`，补充生产部署、迁移、灰度启用、停用回滚、日志检查和验收命令。
- [x] 4.5 (operations) 更新 `docs/current_state.md` 与 `docs/project_status.md`，记录本变更完成后的项目状态、配置默认值和待实网联调事项。
- [x] 4.6 (operations) 如形成新的架构或生产安全决策，更新 `docs/decisions.md`。

## 5. 测试与验证

- [x] 5.1 (application) 新增模型与服务测试，覆盖交付记录唯一约束、重复触发复用、已成功不重复发送、多群部分失败互不影响。
- [x] 5.2 (application) 新增范围策略测试，覆盖默认 `high_value_only`、`all_public`、非法 scope 回退和低价值文章跳过。
- [x] 5.3 (application) 新增消息模板测试，覆盖已有摘要、摘要为空正文截断、省略号和站内公开链接。
- [x] 5.4 (application) 新增任务测试，覆盖 URL 不可访问重试、URL 与 OneBot 错误类型区分、OneBot 失败重试、达到最大尝试次数失败、后续重试成功和发布入口入队。
- [x] 5.5 (application) 新增 Admin 可见性测试或最小后台 smoke，覆盖交付记录列表和筛选字段可访问。
- [x] 5.6 (integration) 使用 mock OneBot 响应验证 `/send_group_msg` 请求 payload、超时配置和 token 不进入错误信息。
- [x] 5.7 (operations) 运行 `DB_ENGINE=sqlite python manage.py check`。
- [x] 5.8 (operations) 运行 `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable`。
- [x] 5.9 (operations) 运行 `openspec validate add-qqbot-auto-push --strict` 和 `openspec validate --all`。
- [x] 5.10 (operations) 运行 `docker compose -f docker-compose.prod.yml config` 与 `docker compose -f docker-compose.prod.lowcost.yml config`。
