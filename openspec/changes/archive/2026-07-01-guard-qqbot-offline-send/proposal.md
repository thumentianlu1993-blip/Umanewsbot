## Why

2026-06-26 生产 QQ 自动推送连续失败，根因是 NapCat 快速登录态失效：OneBot HTTP 仍可访问部分接口，但 `/get_status` 返回 `online=false`，`send_group_msg` 返回 `EventChecker Failed ... 网络连接异常`。现有自动交付会继续调用发送接口并消耗有限重试次数，导致大量新闻在人工重新扫码前被标记为 `failed/send_failed`。

## What Changes

- 自动 QQ 交付在真正发送前检查 OneBot 在线状态。
- 当 OneBot HTTP 不可达、响应异常、或 `online=false` 时，交付记录进入可恢复的等待状态，不调用 `/send_group_msg`，不增加尝试次数。
- 在线状态不可用时记录明确错误类型与错误摘要，便于后台和运维判断需要重新登录 NapCat。
- 文档记录本次事故、临时暂停/恢复步骤、以及新的离线保护语义。

## Capabilities

### New Capabilities

- 无。

### Modified Capabilities

- `qqbot-auto-push`: 自动交付发送前必须识别 OneBot 离线状态，并避免在 Bot 离线时消耗发送重试次数。

## Impact

- 代码：`server/stable/services/onebot.py`、`server/stable/services/qq_auto_push.py`、`server/stable/tests.py`。
- 数据：不新增数据库字段；复用现有 `QQPushDelivery.status`、`last_error_type`、`last_error`、`last_attempt_at`。
- 运维：更新 `docs/current_state.md`、`docs/deploy_runbook.md`、`docs/project_status.md`，记录 OneBot 登录态失效排查与恢复。
- 生产行为：Bot 离线时不会继续刷 `send_failed` 并耗尽重试；登录恢复后，仍可由后续任务或重新入队继续发送。
