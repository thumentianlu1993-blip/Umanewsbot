# 最近赛事赛果定时收集与邮件审阅设计

## 1. 现状与根因

现有 `race_result_recovery_inventory`、`race_event_crawl_orchestration` 和 detail candidate importer
已经提供不可变 inventory、来源适配器、完整顺序审计、dry-run、SHA 绑定和 apply/verify。
但当前 `race_result_recovery` 是一次性恢复模式：

- `RECOVERY_EVENT_IDS_BY_SOURCE` 固定为 2026-07-27 的 40 场；
- `RECOVERY_SOURCE_MAP_VERSION` 只认可该批静态映射；
- 联网前要求人工修改 `expected_targets_approval.json`；
- 没有“最近 72 小时”目标选择、邮件审核包、发送去重或稳定调度入口。

因此不能直接把旧命令放进 cron。新工具复用成熟的候选规范化、完整性审计和写入路径，只替换
静态目标/来源选择，并在 prepare 末端增加 durable review delivery。

## 2. 组件

计划新增或修改：

- `stable/services/scheduled_race_result_review.py`
  - 冻结最近 72 小时目标；
  - 生成 inventory、动态 plan 与不可变 bundle；
  - 执行 prepare/audit/dry-run；
  - 邮件 outbox 去重、投递与安全摘要；
  - 文件锁、重试和 noop。
- `stable/management/commands/run_scheduled_race_result_review.py`
  - 生产/人工通用 prepare 入口；
  - 默认执行完整只读业务链，不提供隐式 apply。
- `stable/management/commands/apply_reviewed_race_result_bundle.py`
  - 精确 SHA + event scope 的审核后 apply/verify 入口；
  - official event 复用现有 recovery projection；内部参考 event 使用新的人工审核 promotion
    planner，保持两种 authority 分离。
- `stable/services/race_event_crawl_orchestration.py`
  - 新增 `scheduled_race_result_review` purpose；
  - 允许由确定性 selector 生成的 machine-bound target snapshot 直接联网；
  - 保留一次性 `race_result_recovery` 的原静态合同，不改变历史包语义；
  - 复用 `_annotate_recovery_result_order()` 和 recovery coverage audit。
- `runtime/policies/race_result_review/source_routes_v1.json`
  - 版本化 region/provider/adapter/authority/identity/host/path/automation contract；
  - 只启用已经受审的来源路径。
- `server/app/settings.py`、`.env.example`
  - 总开关、网络开关、artifact root、route registry、请求/磁盘预算和唯一邮件收件人；
  - 所有新开关默认关闭或收件人为空。
- `stable/models.py` 与 migration
  - `RaceResultReviewRun`：唯一 schedule slot、lease、cursor、run/bundle 终态；
  - `RaceResultReviewPendingEvent`：跨 72 小时窗口的有界 pending backlog；
  - `RaceResultReviewDelivery`：唯一 bundle/recipient、Message-ID、lease、attempt 和投递终态；
  - `RaceResultReviewApproval`：不可变 bundle/event/reviewed-row digest 与
    `official|human_reviewed_reference` authority。
- `docker-compose.prod.lowcost.yml` 与 `docker-compose.prod.yml`
  - `web/worker/beat` 挂载持久化 `/app/runtime/race_result_review`；
  - Beat 投递专用 task，普通 worker 消费；不启用 race-live worker。
- `deploy/run_scheduled_race_result_review.sh`
  - Codex 定时任务调用的非交互生产包装器；
  - 固定目标服务器、目录、容器、命令与超时，禁止接受任意 shell 参数。

新增上述四个小型治理模型的 migration。继续复用 `TaskExecutionLog`、`OperationLog` 和现有
official recovery receipt；不把 `NotificationLog` 的非唯一文本搜索当幂等主键。

## 3. 调度选择

主调度面使用生产 Celery Beat：

1. Beat 在 `Asia/Shanghai` 每日 `06:30/18:30` 投递专用 task；
2. task 与管理命令共同调用 `claim_schedule_slot(slot)`；
3. 唯一数据库约束保证同 slot 只有一个执行 lease；
4. Codex 本地项目 cron 在相同时点调用固定 deploy wrapper，作为幂等备用触发；
5. Beat 已 claim 时 Codex 返回 `already_claimed`；Beat 故障时 Codex 可取得同一 slot；
6. 两者都漏跑时，下次调用根据 durable cursor 枚举 14 天内未终结 slot，把旧 slot 原子标记为
   `coalesced_to_latest_due_slot`，只对最新到期 slot 执行一次 selector/prepare。

生产 Beat 不依赖 Mac/SSH；Codex cron 满足用户可见 automation 和备用触发需求。task 使用普通
worker 的独立 route key 和有限 soft/hard time limit，不接入 race-live queue。

## 4. 目标冻结算法

`select_due_targets(now)`：

1. 用 aware `now` 计算绝对 72 小时新到期窗口，并读取未终结 pending backlog；
2. 读取 published、非 cancelled/postponed 的 `RaceEvent`，预取 results、participants、
   aliases 和 canonical duplicate link；
3. `race_datetime` 存在时直接比较；
4. 缺时间时，将 `local_date` 在 `timezone_name` 的次日 00:00 转为 UTC，只有该时点已过才到期；
5. 计算 `result_state`：
   - `complete_confirmed`；
   - `missing`；
   - `provisional`；
   - `incomplete_confirmed`；
   - `status_repair_required`；
6. 排除 canonical duplicate 的非主记录；其他非 complete 状态 upsert pending；
7. 目标为新到期与未过 14 天 pending 的并集；完成、取消、延期、duplicate 时终结 pending；
8. 按 event ID 排序，写 inventory 和 canonical selector payload SHA。

目标 snapshot 的 machine approval 不是另一个人工授权：它记录 selector version、窗口、event
identity/result identity SHA、route registry SHA 和代码 revision。prepare 前重新计算，任何漂移
即停止；它不能接受调用者任意传入 event ID。

## 5. 动态来源路由与 plan

注册表 route 完整合同至少包含：

```json
{
  "key": "uk-sporting-life-results-v1",
  "region": "united_kingdom",
  "provider": "sporting_life",
  "adapter": "uk_sporting_life_detail",
  "source_authority": "third_party_high_access",
  "candidate_permission": "internal_reference",
  "identity_namespaces": ["sporting_life"],
  "modules": ["results"],
  "allowed_methods": ["GET"],
  "allowed_hosts": ["www.sportinglife.com"],
  "allowed_path_prefixes": ["/racing/results/"],
  "redirect_hosts": ["www.sportinglife.com"],
  "max_redirects": 1,
  "request_budget": 20,
  "minimum_interval_seconds": 5,
  "access_mode": "automated_internal_reference",
  "terms_evidence_sha256": "<64hex>",
  "robots_evidence_sha256": "<64hex>",
  "adapter_manifest_sha256": "<64hex>",
  "contract_digest": "<64hex>",
  "automation_allowed": true,
  "contract_version": "1",
  "valid_until": "2026-12-31T23:59:59Z"
}
```

registry 只保存 canonical adapter key；不接受
`uk_sporting_life_results` 这类内部 alias。validator 先把 `adapter` 解析为已注册 manifest，并要求
route 与 manifest 的 canonical key、region、source、
authority、results-only modules 双向一致；命令模板、允许 method/host/path/redirect、预算和
permission evidence 均进入 manifest/contract digest。adapter 任何潜在 transport 若不被 route
完整覆盖，在子进程启动前失败且 transport=0。

selector 收集全部满足 region、namespace、identity 和有效 contract 的 route。唯一命中才进入 plan；
零命中/多命中分别为 `route_missing/route_conflict`。plan 只含 `results` 模块，并设置固定 request
budget、host interval、source cache budget 和 `allow_network=true`。总网络开关关闭时命令在 target
选择后返回 `disabled_network`，不创建伪候选。

一次性 recovery 的静态常量保留，避免旧 artifact 被新规则重新解释。新 purpose 使用独立 schema
和 selector version，不能接收手写 `regions[].event_ids`。

## 6. prepare、audit 与 bundle

数据流：

```text
目标冻结
  -> route 唯一选择
  -> adapter prepare
  -> combined candidates
  -> recovery 完整性 audit
  -> importer dry-run
  -> review bundle
  -> durable email intent
  -> SMTP delivery
```

- 每个阶段写 state 和固定错误码；失败可从下一调度重新开始，不覆盖旧 run。
- adapter 输出继续由 recovery aggregate 只保留 results；runner roster 只用于完整性核对，不进入
  apply scope。
- coverage audit 逐 event 守恒，只有 `result_order_complete=true`、候选唯一、来源/地区匹配的
  event 进入 reviewable scope。
- dry-run 使用与 apply 相同 parser/planner，但事务回滚且 receipt 增量为零。
- bundle canonical payload 不含自身 digest；文件写入临时 generation，逐文件 fsync 后原子 rename。
- 先生成 `review_payload.json`，包含实际可写字段全集；每 event 计算 `reviewed_row_digest`。
  `review.csv` 只由该 payload 确定性展开，verifier 双向检查行数、字段和 digest。apply 只消费
  review payload，parser candidates 不再是隐藏写入输入。
- `bundle_sha256` 由 canonical manifest payload计算；manifest 再列出各文件 bytes SHA，verifier
  独立复算。

## 7. 邮件 outbox 与幂等

1. 取得同一持久化文件锁；
2. bundle 完成并回读验证；
3. 事务内创建/锁定唯一 `RaceResultReviewDelivery(bundle_sha256, recipient)`；
4. 已 `SENT` 返回 `already_notified`；有效 lease 返回 `delivery_in_progress`；
5. QUEUED/FAILED 或 stale SENDING 取得新 attempt lease，使用稳定
   `Message-ID=<bundle_sha256>@umafans.run`；
6. 事务提交后用 `EmailMessage` 发送白名单附件；
7. 独立事务按 attempt token 写 `SENT` 或脱敏 `FAILED`。

成功 SMTP 返回数必须为 1。发送失败使管理命令非零退出并在下一时点重试。若 SMTP 已接受但进程
在写 SENT 前崩溃，系统无法证明终态，将以相同 Message-ID at-least-once 重试；不得声称
exactly-once。附件只从已验证 generation 读取，拒绝 symlink、越界、非普通文件和 SHA 漂移。

## 8. 审核后 apply

`apply_reviewed_race_result_bundle` 分三种模式：

- 默认 dry-run：验证 bundle、当前 DB baseline 和 scope，输出将写行数；
- `--apply --confirm-apply`：要求 expected bundle SHA、approved event IDs 和 reviewer 标识；
- `--verify`：独立读取 receipt 和当前 DB，不复用 apply 进程状态。

apply 先为每个批准 event 写不可变 `RaceResultReviewApproval`，绑定 bundle、reviewed row digest、
reviewer 和 authority。官方 receipt 继续走现有 official-only projection；内部参考 observation 经
人工批准后走新的 `human_reviewed_reference` promotion，不修改原来源 authority、不生成 official
receipt，公开语义为“已人工审核赛果”。

每 event planner：

1. 安全打开 manifest 及列出的文件；
2. 校验代码/registry/bundle/file SHA；
3. 只取 reviewable 且人工批准的 event；
4. 重新核对 event identity 与 result identity baseline；
5. 根据 approval authority 调用 official projection 或 human-reviewed-reference locked planner；
6. 单 event 事务写 results、平台确认时间、finished status、approval 和 OperationLog/receipt；
7. commit 后发布该 event ledger；失败 event 不影响已提交的其他 event；
8. 最终 summary 保存每个 event 终态，完成后保护 source cache 与 bundle 为只读。

任何漂移、blocker 或未批准 event 对该 event 零写入。批准子集和失败 event 保留 pending，下一
调度继续出现。测试以 PostgreSQL 故障注入证明每 event 原子性，并验证中后段失败时前一 event 的
已提交 ledger/数据库一致、后一 event 零写入。

## 9. 配置与安全

建议设置：

- `RACE_RESULT_REVIEW_ENABLED=false`
- `RACE_RESULT_REVIEW_ALLOW_NETWORK=false`
- `RACE_RESULT_REVIEW_ARTIFACT_ROOT=/app/runtime/race_result_review`
- `RACE_RESULT_REVIEW_ROUTE_REGISTRY=.../source_routes_v1.json`
- `RACE_RESULT_REVIEW_NOTIFY_EMAILS=`
- `RACE_RESULT_REVIEW_LOOKBACK_HOURS=72`
- 请求、缓存、磁盘和附件大小上限。

发布先以两开关均关闭部署。首次生产 smoke 确认网络/邮件/业务写均为 0 后，在同一已授权发布窗口
设置总开关、网络开关和唯一收件人。apply 不依赖 prepare 网络开关，但永远需要精确审核证据。

## 10. 回滚

- 立即停止：暂停 Codex cron；或设置 `RACE_RESULT_REVIEW_ENABLED=false`。
- 网络止血：只设置 `RACE_RESULT_REVIEW_ALLOW_NETWORK=false`，保留 inventory/noop 审计。
- 邮件止血：清空唯一收件人会 fail closed，不发送到替代地址。
- 代码回滚：恢复前一镜像和 Compose；四张治理表仅追加审计状态，默认保留。只有回滚版本无法与
  migration 共存且已证明没有必须保留记录时，才执行受审 reverse migration。
- 已生成 bundle、review run/delivery/approval、TaskExecutionLog、OperationLog 是审计事实，
  不删除；未 apply 的 bundle 不影响业务表。
- 已 apply 的错误结果使用其 recovery receipt 和写前数据库备份进入独立回滚窗口，不由 cron 自动撤销。
