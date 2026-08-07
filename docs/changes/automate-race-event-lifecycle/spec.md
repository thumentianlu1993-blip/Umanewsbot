# 赛事日历自动更新与赛事生命周期规格

## 1. 状态

- 任务 slug：`automate-race-event-lifecycle`
- 当前阶段：阶段 A 已关闭部署；阶段 B0.1 赛后内部参考源处于 spec/design
- 本轮规划基线：`origin/main@a59956b327157d29630fab1f1c98ba9c9cacfed0`
- 当前授权：文档完善、实现准备和独立方案审核
- 下一门禁：等待用户明确“G1 范围确认 / 开始实现 / 继续实现”
- 方案审核：同一 reviewer 第三轮 `APPROVED`，无开放 P0/P1/P2

阶段 A 已在生产显式保持 `RACE_EVENT_LIFECYCLE_ENABLED=false`、
`RACE_EVENT_LIFECYCLE_MODE=off`；详细证据见 `production_release_20260726.md`。本文本轮修改
push、PR、部署、迁移或服务重启。

## 2. 问题与根因

公开赛事使用 `RaceEvent.status` 展示 `scheduled / running / finished / postponed /
cancelled`。现有准实时赛果链路另用 `RaceEventLiveTracking.state` 和不可变
`RaceEventRevision.phase` 区分 `awaiting_result / provisional / official / corrected`。

当前没有面向全部重点赛事、按赛事 IANA 时区和当地日期运行的生命周期推进任务。
`RaceEvent.status` 主要在赛果 revision 被公开物化时才改为 `finished`；当来源失败、赛事
没有 `race_datetime`、未初始化 live tracking，或生产 scheduler 关闭时，时间已经过去也
不会推进。因此来源成功被错误地变成了赛事状态前进的事实前置条件。

## 3. 目标

1. 重点赛事按当地时间从赛前、到点、赛后形成可重试、幂等、可审计的生命周期。
2. “比赛时间已过/赛事已结束”与“取得暂定/正式赛果”始终分离。
3. 复用现有 `RaceEvent`、racecard、race-live revision、来源 proof、文章门禁与 QQ 幂等
   链路，不另建重复赛事总账或赛果投影。
4. 赛前按可配置窗口同步出马表、开赛时间、骑师、闸位、退赛、延期/取消等资料。
5. 高置信、明确影响具体赛事详情的新闻可绕过软发布门禁；翻译、重复、内容完整性、来源
   合规、术语/实体一致性等硬门禁继续生效。
6. 所有字段写入执行来源权威比较，低权威数据不能静默覆盖高权威确认值。
7. 支持 dry-run、shadow、小范围 enforce、按阶段扩大和独立回滚。

## 4. 非目标

- 不改造首页“近期赛事”或首页卡片的选取逻辑。
- 不批量修正全部历史赛事状态。
- 不把尚未通过 proof 的 API 升格为生产来源。
- 不自动抓取受登录墙、防护页或条款限制的来源。
- 不把 The Racing API（TRA Free）升格为 official authority。
- 不在阶段 A 接入新外部来源、改变 race-live scheduler 或公开赛果策略。
- 不把 Sporting Life、ZEturf、HRN 的内部参考观察写入公开赛事、公开赛果、新闻、QQ、
  sitemap、搜索或公开 API。
- 不为内部参考观察提供直接 promotion/apply 能力。
- 不因为新闻出现赛事名就特殊放行或写赛事字段。
- 不绕过 QQ 类别/目标/频率/唯一性门禁。

## 5. 现有事实口径

### 5.1 重点赛事

唯一产品判定复用 `RaceEvent.is_key_race`：

```text
priority in {P0, P1} OR is_featured=true
```

自动任务另要求 `visibility_status=published`，排除 `cancelled`，并只扫描有界日期窗口。
`normalized_grade` 可决定刷新窗口强度，但不取代重点判定。迁移不会隐式启用；只有显式
纳管 manifest 中的赛事才进入 control/scanner。

### 5.2 两层状态

赛事发生状态继续使用 `RaceEvent.status`：

- `scheduled`：赛前或日期已定但尚未到点；
- `running`：已到计划/修正出走时间，尚未到赛后推进点；
- `finished`：按可靠赛果或时间规则判断赛事已结束；不等于正式赛果；
- `postponed`：已延期，必须有新日期/时间或待定标记；
- `cancelled`：已取消，不再正常推进。

赛果取得状态继续使用现有 live/revision：

- 无 tracking/revision：尚无准实时赛果事实；
- `awaiting_result`：已到点，结果待确认；
- `provisional_result`：暂定赛果；
- `official_result`：正式赛果；
- `corrected_result`：官方更正。

`result_confirmed_at` 仅在 official/corrected 时设置；provisional 不设置。

JRA-VAN/JV-Link 的 authority 主体是已批准的 JRA-VAN provider contract，不是 collector 或
`jrvltsql`。JRA 分阶段赛果必须由版本化 registry 将
`record_type + raw_status + sequence/correction marker` 映射到结果阶段：

- 三名、五名、字段不全或未知阶段只能是 `provisional_result`/`awaiting_result`；
- 只有 proof 确认的显式全马最终 marker 才能成为 `official_result`；
- official 后只有明确修正 marker 才能成为 `corrected_result`；
- 未登记 marker、乱序或 schema/contract 漂移一律 fail closed。

NAR/JPN1 使用独立 provider identity、external event ID 和 marker 合同，不得复用 JRA 映射。

## 6. 生命周期规则

### 6.1 有明确出走时间

1. 以 aware `race_datetime` 为唯一 instant；`local_date/local_start_time` 是赛事 IANA
   时区下的展示/核验值。
2. `now >= race_datetime` 时，`scheduled -> running`；现有 live tracking 若已初始化，
   由现有 race-live CAS 在 T+0 只进入 `awaiting_result` 并把 `next_poll_at` 设为
   `race_datetime + 3 分钟`，不得在同一个 task 继续联网。
3. 赛果首次网络轮询最早在出走后 3 分钟开始；来源未返回结果时按现有有限轮询计划继续。
4. `now >= race_datetime + 30 分钟` 时，若非延期/取消，`running/scheduled -> finished`，
   同时记录 `result_pending=true` 的派生口径（没有 official/corrected revision 时）。
5. 任何来源失败都不阻断第 2、4 步；不得生成虚假结果。

### 6.2 只有日期、没有出走时间

1. 使用 `ZoneInfo(event.timezone_name)`。
2. 在 `local_date + 1 天 00:00` 当地时间后，将非延期/取消赛事推进为 `finished`。
3. 同时登记赛果补采请求；没有已批准来源时只记录待补全，不联网猜测。
4. 时区无效、当地日期缺失或时区与地区合同不匹配时 fail closed，进入人工纠错，不采用
   服务器 `Asia/Shanghai` 隐式推断。日本/香港/英国/法国必须精确匹配固定 IANA zone；
   美国必须是该赛事已审核的具体 `America/*`。

### 6.3 延期与取消

- `cancelled` 为终态，除有权限的人工更正外不得自动回退。
- `postponed` 不按旧日期/时间推进；只有高权威来源写入新当地日期/时间并形成新
  `race_datetime` 后，受控回到 `scheduled`。
- 调度只查询数据库中当前的 `next_refresh_at`/`race_datetime`；不创建不可撤销的远期 ETA。
  改期事务同时增加 `schedule_generation`、重算下一次刷新，旧 generation 的任务在锁内拒绝。
- 已有 official/corrected 结果后，不允许自动延期/取消；进入冲突人工审核。

## 7. 字段更新与来源优先级

权威等级固定为：

| 等级 | 类别 | 示例 | 自动覆盖规则 |
|---|---|---|---|
| 500 | 官方结构化来源 | JRA/NAR/HKJC 官方结构化赛程/赛果 | 可覆盖较低等级；同等级冲突转人工 |
| 400 | 已验证专业 API | 已通过该地区/字段 proof 的专业 API | 可覆盖 300 以下；不能产生 official |
| 300 | 官方新闻/公告 | 官方退赛、延期、骑师变更公告 | 高置信且赛事唯一时可自动写指定字段 |
| 200 | 可信媒体新闻 | 已批准媒体的明确变更报道 | 默认生成候选；不得覆盖 300+ |
| 100 | 日期/时间规则推断 | 生命周期时间推进 | 只推进赛事发生状态，不写结构化赛果 |

每个可变字段的当前 provenance 和每次有效变化至少记录字段目标身份。赛事字段目标为
`event:<event_id>`；参赛马字段目标为 `participant:<RaceEventParticipant.stable_key>`，不能
只用 `event + field_name`。每条记录至少包含：

- `subject_type/subject_key/field_name`、原值、新值；
- `source_key`、来源类别/权威等级；
- `source_url` 或 external ID；
- `confidence`；
- `observed_at`、`applied_at`；
- `trigger_task`、task/run ID；
- `article_id`（适用时）；
- `candidate_id/revision_id`；
- `schedule_generation`；
- 操作模式 `dry_run/shadow/enforce`。

低权威冲突不得静默覆盖；同一场不同 participant 的闸位/骑师/退赛状态必须相互独立；
相同内容重放不重复产生审计记录。

商业订阅本身不提升权威等级。只有合同或 rights-holder 证明明确覆盖某个
`region + field_name + result_phase + provider_contract_version` 时，商业 feed 才能作为官方结构化来源；否则仍按已验证的
专业 API、聚合来源或候选证据处理。采购、来源 proof、registry 批准和生产启用是四个独立门禁。

### 7.1 外部 collector 信任边界

外部 collector 不得直接连接生产业务数据库。JRA Windows collector 的唯一允许输入是由 Umanews
主动只读拉取的不可变签名 snapshot；不允许共享活动数据库或在两个传输方案间运行时切换。

snapshot 至少绑定：

- schema/snapshot/provider/contract version；
- collector ID、git/build SHA、活动 fencing token；
- upstream spec/high-watermark、source observed/fetched timestamps；
- record counts、payload SHA-256、previous snapshot SHA-256；
- Ed25519 signature 和原子完成 marker。

Umanews 必须在写候选前验证活动 collector/token、公钥、允许的 build/schema/contract、签名、
payload/前驱 hash、连续水位和 marker。任一失败零写。消费水位只在业务事务 commit 后推进；
同一 snapshot/hash 重放为 noop；collector 轮换使旧 fencing token 立即失效。赛日 RPO 目标
5 分钟、RTO 30 分钟，非赛日 RPO 24 小时；超时只告警和保持结果待补，不阻断时间生命周期。
payload 保留 30 天，manifest、receipt 和字段审计长期保留。

### 7.2 内部参考源

Sporting Life、ZEturf、Horse Racing Nation 统一作为 `internal_reference`：

- 用户已确认本站可保留解析器并低频使用；
- 新增观察只供有权限的内部后台查看；
- `publication_capability/result_authority/field_apply_capability` 全部为 `none`；
- 不能创建 `RaceEventDataCandidate`、race-live revision/projection 或 official marker；
- 不能改变 `RaceEvent`、runner/result、lifecycle control、新闻或 QQ；
- 完全相同重放为 noop，内容变化追加新观察，歧义匹配不绑定赛事；
- 现有历史赛事 importer 保持原流程，本规则不追溯改变既有历史数据。

详细模型、隔离与来源特有限制见 `internal_reference_sources.md`。如以后需要人工采纳，必须
另立 change；本阶段不提供 promotion 命令或后台 action。

阶段 B0.1 只复用三个 parser 当前已经证明的 `finished` 赛后结果入口，不承担赛前资料同步，
也不注册 Celery/Beat。赛前 racecard 仍由后续 TRA/官方来源阶段负责；第三方赛前入口若需加入，
必须另做 fixture/proof 和方案审核。

## 8. 赛前刷新窗口建议

所有值集中配置并按 P0/P1 分层，不散落硬编码：

| 阶段 | P0 推荐 | P1 推荐 | 目标 |
|---|---:|---:|---|
| 提前进入窗口 | T-21 天 | T-14 天 | 每日发现出马资料/时间 |
| 中期 | T-7 天至 T-49 小时每 6 小时 | T-72 至 T-25 小时每 6 小时 | 名单、骑师、闸位 |
| 临近 | T-48 至 T-7 小时每 2 小时 | T-24 至 T-7 小时每 2 小时 | 退赛、改时 |
| 开赛前 | T-6 小时至出走每 30 分钟 | 同左 | 动态变化 |
| 赛果 | T+3 分钟起 | 同左 | 复用 race-live 有界轮询 |
| 赛后推进 | T+30 分钟 | 同左 | 状态与结果解耦 |

单场逻辑刷新上限约 P0 67 次、P1 40 次；它不是等量网络请求。provider adapter 必须优先
按“地区＋赛日＋来源”合并请求并共享缓存/HostBudget。按每年 400 场重点赛事粗估，
约 2.1 万次逻辑到期判断（年均约 58 次/日），网络请求受 `每来源每分钟/每小时/每日预算`
三层限制；赛日前高峰按地区隔离，默认总网络上限建议 100 次/日、单来源 40 次/日，
不足时降频而不是挤占新闻 worker。

这些推荐值、预算和 P0/P1 分层必须在实现前由用户确认。

## 9. 赛事影响新闻特殊放行

### 9.1 分类结果

分类必须产生可审计对象：

- `affects_race_details`
- `matched_race_id`
- `event_type`：`barrier_draw/scratch/jockey_change/runner_change/time_change/
  postponed/cancelled/other_structured_change`
- `extracted_changes`
- `evidence`（原文精确片段位置/结构化字段，不保存超出使用范围的网页正文）
- `confidence`
- `source_authority`
- `classifier_version`

只有同时满足以下条件才获得特殊放行：

1. 翻译已成功且发布稿完整；
2. 重复检测通过；
3. 唯一匹配到一个 published 重点赛事；
4. 至少两个独立身份信号（正式名/批准别名＋当地日期、赛场、已知马匹/骑师、官方 external ID
   等），或一个 provider-bound 官方赛事 ID；
5. `confidence >= 90`；
6. `event_type` 在 allowlist 且 `extracted_changes` 非空；
7. 来源已获生产抓取/发布批准。

仅出现赛事名、模糊日期、跨届同名或多个候选时不得放行。

### 9.2 保留的硬门禁

以下保持阻断，需用户确认但方案不建议取消：

- 翻译失败/未完成；
- 高度重复及窗口内容 fingerprint 重复；
- 标题、正文、来源 URL 缺失，正文过短；
- `published_at_verified=false`；
- 核心术语/未译马名未保留、机器实体类型与标签/链接冲突；
- 来源未 `production_approved`、条款/robots/许可禁止、来源身份未核准；
- 赛事身份不唯一、低置信、人工锁或高权威字段冲突；
- 非法/不安全内容及未来新增的安全、数据完整性、法律合规 blocker；
- 已撤回/已发布/已确认 duplicate 等终态。

### 9.3 可绕过的软门禁

- `AUTO_REVIEW_THRESHOLD`、`MANUAL_REVIEW_THRESHOLD`；
- 普通价值/热度/新鲜榜单加分；
- 地区窗口最低产量、soft fill、普通窗口最低分；
- 普通编辑改写阈值与封面要求（仍须标题、摘要、正文完整）；
- 地区日配额和普通每窗口配额（特殊新闻使用独立小额配额，建议每地区每小时 3、每日 12）；
- `racecard_update` 的普通“价值不足”判断。

来源生产批准、来源 allowlist、发布时间证据与术语/实体一致性不归入软门禁。

### 9.4 现有 reason code 映射

| 现有检查/reason code | 分类 | 特殊新闻行为 |
|---|---|---|
| translation 非 translated、`translation_retry_*` | hard | 阻断 |
| 同标题早稿、`duplicate_content`、`possible_duplicate_content`、`dedupe_loser` | hard | 阻断或转人工 |
| `missing_title/missing_body/body_too_short/missing_source_url` | hard | 阻断 |
| `published_at_unverified`、publish-ready `legacy_missing/manual_review/expired` | hard | 阻断或人工 |
| `core_term_missing/pending_horse_original_missing/machine_entity_type_mismatch` | hard | 阻断 |
| `attribution_needs_review/related_region_waiting_primary_region` | hard | 阻断 |
| `source_not_allowed`、来源未 production approved/条款许可 | hard | 阻断 |
| `region_not_allowed` | hard | 阻断；这是生产地区授权，不是产量软门禁 |
| `term_candidate_backlog` | hard | 阻断；属于数据完整性保护 |
| 已撤回/已发布/ignored/duplicate 等终态 | hard | 阻断 |
| `AUTO_REVIEW_THRESHOLD/MANUAL_REVIEW_THRESHOLD/below_min_score` | soft | 绕过 |
| 普通 `region_window_limit`、地区 daily/per-run limit | soft | 改用独立特殊配额 |
| 普通站点 hourly quota | soft | 不占普通配额，使用独立硬上限 |
| `AUTO_PUBLISH_REQUIRE_COVER` | soft | 可绕过 |
| rewrite confidence warning、普通 warning/info | not blocking | 保留审计 |

未来新增 blocker 默认 hard；必须通过新方案/测试显式降级，不能自动落入可绕过集合。

### 9.5 发布与赛事写入解耦

- 分类先写 assessment 和 `RaceEventDataCandidate`，不直接改 `RaceEvent`。
- 新闻成功发布事务 commit 后，才通过 `transaction.on_commit` 派发候选应用任务。
- 官方新闻、唯一赛事、`confidence >= 95`、无字段冲突时可自动应用 allowlist 字段；
  可信媒体或任一冲突进入人工审核。
- 新闻发布失败可以保留 assessment/candidate 审计，但不得改变公开赛事字段。
- 赛事候选应用失败不得回滚已经成功发布的新闻；记录错误并供重试。

## 10. 验收标准

1. 有/无出走时间的重点赛事都按 IANA 当地时间推进。
2. 来源失败不会让旧赛事永久保持赛前，也不会伪造赛果。
3. 暂定、正式、更正赛果与 `finished` 清晰分离。
4. 延期/取消和改时采用 generation/锁防止旧任务推进。
5. 字段更新有完整来源比较与审计，低权威不能覆盖高权威。
6. 特殊新闻只绕过明确软门禁，翻译/重复等硬门禁继续阻断。
7. 多 worker 并发只产生一次有效状态/字段变化。
8. 公开日历与详情读取同一持久状态，缓存及时失效。
9. 不重复发布新闻或发送 QQ。
10. 现有 race-live、字段归一化、日历移动端样式不回归。
11. Sporting Life、ZEturf、HRN 的观察只能进入内部参考模型，公开赛事/赛果/新闻/QQ 零变化。
12. 内部参考来源相同内容重放不重复，变化内容保留版本，歧义/partial/来源失败可解释。
