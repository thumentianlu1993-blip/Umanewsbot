## Context

2026-06-26 生产 QQ 自动推送连续失败。排查显示 OneBot HTTP 服务和 token 可用，`/get_login_info` 与 `/get_group_list` 可返回数据，但 `/get_status` 返回 `online=false`，发送接口返回 `EventChecker Failed ... 网络连接异常`。重启 NapCat 后日志明确显示快速登录态失效，需要重新扫码登录。

当前自动交付流程会在 URL 检查通过后直接领取交付、增加 `attempt_count` 并调用 `/send_group_msg`。当 Bot 已离线时，这会把登录态问题放大为大量 `failed/send_failed` 记录，并在人工重新登录前耗尽有限重试次数。

## Goals / Non-Goals

**Goals:**

- 在自动发送前识别 OneBot 离线或状态不可确认。
- Bot 离线时不调用 `/send_group_msg`，不增加交付尝试次数。
- 交付记录保留明确错误摘要，便于后台判断需要重新登录 NapCat。
- Bot 恢复在线后，后续任务可以继续发送同一交付记录。
- 将本次生产事故和恢复步骤写回运维文档。

**Non-Goals:**

- 不自动重启 NapCat、不自动生成或分发登录二维码。
- 不绕过 QQ/NapCat 风控，也不试图自动完成扫码登录。
- 不新增数据库字段或迁移。
- 不改变手动推送入口的现有行为。

## Decisions

- **发送前增加 OneBot 状态探测。** 在自动交付流程中调用 OneBot `/get_status`。只有返回 `status=ok` 且 `data.online=true` 时才继续领取发送尝试。这样可以在最接近发送的位置拦截登录失效，覆盖 HTTP 服务仍可访问但 QQ 会话不可发送的半离线状态。
- **离线状态使用现有交付字段记录。** 不新增状态枚举或迁移，交付保持 `retrying`，`last_error_type=send_failed`，`last_error` 写入 `onebot_offline` 或状态检查失败摘要。这样后台能看到问题，但不会破坏已有状态机和筛选。
- **离线时不 claim attempt。** OneBot 离线检查必须发生在 `_claim_delivery_attempt()` 之前，因此不会增加 `attempt_count`，不会更新 `last_attempt_at`，也不会触发按群限速。
- **状态检查异常按离线处理。** `/get_status` 超时、HTTP 失败、非 JSON 或 OneBot 业务失败都视为 Bot 当前不可发送，记录错误并等待后续任务重试。

## Risks / Trade-offs

- **[Risk] 状态检查增加一次 HTTP 请求。** 自动推送频率较低，额外请求成本可接受；比离线时持续发送失败更可控。
- **[Risk] 离线记录仍使用 `send_failed`。** 不新增迁移，短期后台无法单独按 `bot_offline` 类型筛选；通过 `last_error` 前缀和运维文档区分。
- **[Risk] 已经耗尽重试的历史失败记录不会自动恢复。** 本 change 保护后续交付；历史失败如需补发，应由运维人工选择性重置或手动推送，避免补推历史新闻。

## Migration Plan

1. 本地新增测试并实现 OneBot 状态检查。
2. 运行目标测试、`manage.py check`、`openspec validate --all` 和 `git diff --check`。
3. 合并部署后执行 `deploy_lowcost.sh`，确认 worker 加载新代码。
4. 生产验收以 `/get_status online=true`、测试群发送成功、`QQ_PUSH_ENABLED=true`、公网 `/healthz/` 返回 `200` 为准。
5. 如出现异常，可回滚代码；运行态仍可通过 `QQ_PUSH_ENABLED=false` 立即暂停自动推送。
