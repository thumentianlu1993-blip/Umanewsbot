## ADDED Requirements

### Requirement: OneBot 离线时自动交付必须暂停发送
系统 SHALL 在自动 QQ 交付真正调用 OneBot `/send_group_msg` 前检查 OneBot 当前是否在线可发送。若 OneBot HTTP 不可达、状态响应异常、业务状态失败，或 `/get_status` 显示 `online=false`，系统 MUST NOT 调用 `/send_group_msg`，MUST NOT 增加本次交付的 `attempt_count`，并 MUST 在交付记录中写入可排查的离线或状态检查失败摘要。Bot 恢复在线后，同一交付记录 MUST 仍可由后续任务继续发送，且不需要人工重建交付记录。

#### Scenario: OneBot 显示离线时不消耗重试
- **WHEN** 自动交付任务准备发送一条尚未达到最大尝试次数的 QQ 交付记录
- **AND** OneBot `/get_status` 返回 `status=ok` 且 `data.online=false`
- **THEN** 系统 SHALL NOT 调用 `/send_group_msg`
- **AND** 系统 SHALL NOT 增加该交付记录的 `attempt_count`
- **AND** 系统 SHALL 记录 OneBot 离线相关错误摘要

#### Scenario: OneBot 状态检查失败时不消耗重试
- **WHEN** 自动交付任务准备发送一条尚未达到最大尝试次数的 QQ 交付记录
- **AND** OneBot 状态检查超时、HTTP 失败、返回非 JSON 或返回业务失败
- **THEN** 系统 SHALL NOT 调用 `/send_group_msg`
- **AND** 系统 SHALL NOT 增加该交付记录的 `attempt_count`
- **AND** 系统 SHALL 记录状态检查失败摘要

#### Scenario: OneBot 恢复在线后继续发送
- **WHEN** 自动交付记录此前因 OneBot 离线被保留为可恢复状态
- **AND** 后续 OneBot `/get_status` 返回 `status=ok` 且 `data.online=true`
- **THEN** 系统 SHALL 正常领取发送尝试并调用 `/send_group_msg`
