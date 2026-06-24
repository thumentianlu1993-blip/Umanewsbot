## Why

当前项目已经具备公开网站发布、自动化内容运营和 OneBot 手动推送雏形，但“最新新闻自动进入指定 QQ 群”的分发闭环仍未完成。现在公开首页与自动发布链路已经上线观察，适合把 QQ 群推送从手动操作升级为可灰度、可追踪、可重试的自动分发能力。

## What Changes

- 新增发布后自动 QQ 群推送流程：文章公开详情页 URL 可访问后，自动推送到数据库中启用的多个 QQ 群。
- 新增推送范围策略：支持 `all_public` 和 `high_value_only`，默认只推高价值新闻，避免上线初期刷屏。
- 新增自动推送交付记录：以“文章 x QQ 群”为粒度记录状态、尝试次数、错误、成功时间和 OneBot 响应，并保证同一篇文章不会重复推送到同一群。
- 新增有限重试机制：OneBot 请求失败、公开 URL 暂不可访问或网络超时时，按配置进行有限次重试。
- 调整 QQ 推送消息内容：自动推送使用中文最终稿的标题、摘要和公开站点链接；摘要为空时从正文截断并追加 `……`。
- 补充生产配置与运维文档：说明 NapCatQQ / OneBot HTTP 推荐路线、同机低成本部署、安全边界、后台群配置和验收步骤。
- 保留现有手动推送入口，不在本变更中移除或破坏既有 `PushTarget`、`PushLog` 和 OneBot 客户端能力。

## Capabilities

### New Capabilities

- `qqbot-auto-push`: 公开文章发布后自动向多个 QQ 群推送中文标题、摘要和站内链接，并提供范围策略、去重、重试和后台可见交付状态。

### Modified Capabilities

- 无。

## Impact

- Django 模型与迁移：新增自动推送交付记录，必要时扩展现有 `PushStatus` 或新增自动推送状态枚举。
- Celery 任务：新增发布后自动推送编排、公开 URL 可访问检查、单群交付任务和有限重试。
- 服务层：复用并收紧 OneBot HTTP 调用、消息模板生成和高价值新闻判断。
- 后台管理：通过 Django Admin 管理 QQ 群、查看自动推送交付记录和失败原因。
- 配置：新增 `QQ_PUSH_ENABLED`、`QQ_PUSH_SCOPE`、`QQ_PUSH_MAX_ATTEMPTS`、`QQ_PUSH_URL_CHECK_TIMEOUT_SECONDS`、`ONEBOT_TIMEOUT_SECONDS` 等环境变量。
- 部署与文档：更新 `.env.example`、Compose OneBot 示例、`docs/qqbot_setup.md`、`docs/deploy_runbook.md`、`docs/current_state.md` 和 `docs/project_status.md`。
- 外部系统：依赖同机运行的 OneBot v11 HTTP 网关；推荐 NapCatQQ，go-cqhttp 不作为新接入路线。
