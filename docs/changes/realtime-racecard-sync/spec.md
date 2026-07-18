# 准实时赛前 racecard/off time 同步规格

## 背景

准实时赛果安全基线已经部署，但生产未来赛事缺少 `RaceEvent.race_datetime`，
现有 `initialize_race_live_events` 又要求带时区的开赛时间、唯一外部赛事身份和完整参赛者
manifest，因此首轮英国 shadow 无法初始化。

The Racing API Free 的官方文档和 2026-07-18 生产脱敏 proof 均证明
`/v1/racecards/free` 可按 `today|tomorrow` 返回 `race_id`、`off_dt`、地区、赛场、
赛事名及 runner 的 `horse_id/horse/number/draw/jockey/jockey_id`。该来源只作为
赛前身份和暂定赛果补充来源，不提升为官方来源。

## 目标

1. 对显式指定的英国 `RaceEvent`，从 The Racing API Free 的今日/明日 racecard
   中寻找唯一精确匹配。
2. 生成可审计、可复现、不含 raw 响应和第三方评级内容的初始化 manifest。
3. 扩展现有 initializer，使获准 manifest 能在一个事务中：
   - 补齐 `race_datetime` 和 `local_start_time`；
   - 建立 The Racing API 外部赛事身份；
   - 建立完整 participant/source identity；
   - 建立首个不可变 racecard revision；
   - 初始化 live owner、tracking、shadow policy、event allowlist 和 host budget。
4. 解除英国单地区 shadow 的生产初始化硬阻塞，但不在本变更中启动 shadow。

## 范围

### 来源与请求

- 仅允许固定 host `api.theracingapi.com`。
- 仅允许：
  - `/v1/racecards/free?day=today&region_codes=gb&limit=500&skip=0`
  - `/v1/racecards/free?day=tomorrow&region_codes=gb&limit=500&skip=0`
- 每次 prepare 最多两次请求，继续遵守 Free 计划 1 RPS、15 秒 timeout、
  2 MiB 响应上限、禁止 redirect、TLS/DNS/公网 IP 和 registry digest 门禁。
- 网络期间不持有数据库事务或行锁。
- 本变更必须升级 tracked source registry 与 transport 精确 allowlist，保留现有
  regions、无地区 today、results today 三条路径，并新增上述两条 sync 路径。
  新 registry digest 必须同时进入镜像复制契约、生产配置和现有 proof/results runner 回归；
  旧 digest 或未知 query 顺序继续拒绝。
- prepare 会写 `RaceLiveHostBudget` 控制面：row 缺失时以
  `host=api.theracingapi.com/min_interval_ms=1050` 受控 bootstrap，随后每次请求通过
  现有 reservation/outcome CAS 更新动态字段。它仍然对 RaceEvent、runner/result 和其他
  live 业务事实零写入。
- reservation 若返回尚未到达的 `next_allowed_at`，prepare 只允许等待至该时刻再重试一次；
  单次等待上限为 2 秒。并发 runner/prepare 将窗口推到上限之外时，本轮直接输出
  `host_budget_wait_exceeded` blocker，不继续轮询或绕过共享限速。

### 目标赛事

- 调用方必须显式提供一个或多个 `event_id`。
- 首期只接受 `country_region=united_kingdom`。
- 赛事必须是当前或未来 `scheduled` 赛事，`local_date` 已存在，且不存在：
  - runners/results 人工锁；
  - 已有 live control/tracking/source/participant/revision；
  - 已有结构化赛果；
  - 与本 manifest 不一致的 `race_datetime/local_start_time`。
- 首期英国 event 的 `timezone_name` 必须已经是 `Europe/London`；不在本变更中把
  默认 `Asia/Tokyo` 或其他值自动修正为英国时区。
- 普通赛事可作为 shadow 样本，但报告必须区分重点赛事与普通赛事。

### 唯一匹配

候选必须同时满足：

1. TRA `region=GB`。
2. `off_dt` 是带时区 ISO-8601 时间，其来源当地日期等于 `RaceEvent.local_date`。
   比较前必须先把该 instant 转换到 `ZoneInfo("Europe/London")`，禁止直接采用响应 offset
   的 wall-clock。
3. 赛场名称经 Unicode NFKC、casefold、标点/空白归一化后精确相等。
4. 赛事名经相同归一化后，精确命中以下至少一项：
   - `RaceEvent.original_name`；
   - active `RaceEventAlias`；
   - 同年度有效的 `RaceSeriesName`；
   - `RaceSeries.canonical_name_original`；
   - `MajorRaceEvent.name/normalized_name/aliases`。
5. 满足全部条件的 TRA racecard 恰好一个。

不允许编辑距离、substring、马号、开赛时间接近度或人工猜测形成自动绑定。
零命中和多命中都只进入 blocker 报告，不产生可 apply 事件。

### 客观字段

manifest 只保存：

- 赛事：`race_id`、`off_dt`、`region`、`course`、`race_name`、`race_status`。
- 参赛者：`horse_id`、`horse`、`number`、`draw`、`jockey`、`jockey_id`。
- 审计：响应 SHA、请求路径、耗时、代码/registry/terms/coverage digest 和数据库基线。

禁止保存或公开赔率、form、评级、奖金、血统、评论、预测和其他专有内容。
不保存原始响应。

### Participant 身份

- `external_runner_id = horse_id`。
- `stable_key = "tra:" + sha256(horse_id)`，不得以马号或姓名代替稳定身份。
- `canonical_name = horse`。
- `country_region` 留空；不能把举办地区伪造成马匹国籍。
- Free schema 没有独立退赛状态时，racecard 中出现的 runner 只标为 `declared`；
  不因后续列表缺失自动推断 `scratched/withdrawn`。
- `horse_number/draw/jockey` 作为赛事内客观字段写入 racecard revision。

## 用户与运营行为

### Prepare

- 命令对赛事业务事实只读，但会 bootstrap/更新共享 `RaceLiveHostBudget` 控制面。
- 必须显式确认真实网络、提供 event IDs、安全 run-id 和全部 digest/route 参数。
- 输出到配置固定的 `RACE_LIVE_RACECARD_ARTIFACT_ROOT/<run-id>`：
  - `manifest.json`：可交给 initializer 的 schema v2 manifest；
  - `report.json`：命中、零命中、多命中、baseline blocker 和字段摘要；
  - `requests.jsonl`：不含凭据和实体值的请求元数据。
- `run-id` 只能是安全 basename。artifact root 必须是绝对、非 symlink 的 resolved
  runtime 目录；配置路径与 resolved 路径不一致时拒绝。
- 在同父目录的 0700 临时目录中写 `requests.jsonl`、`report.json`，无 blocker 时最后写
  绑定前两者 SHA 的 `manifest.json`；各文件 0600，fsync 后原子 rename 为最终 run-id。
  任一阶段失败只清理临时目录，不留下最终目录或 apply-ready manifest。
- initializer 必须从只读挂载的同一完成目录读取 `manifest.json` 及其两个 sibling，
  重算 `requests.jsonl/report.json` SHA；只传入单独 manifest、缺 sibling 或任一内容
  被替换时均拒绝。
- 任一目标未唯一匹配时命令仍输出报告，但不输出可 apply manifest。

### Dry-run / Apply / Verify

- `initialize_race_live_events` 继续默认 dry-run。
- schema v1 行为保持兼容。
- schema v2 fresh apply 必须同时校验事件旧时间值、`updated_at`、人工锁、
  expected `status/local_date/timezone_name`、外部赛事/runner 唯一性和全部既有
  live/result 状态。
- fresh apply 在同一数据库事务内先写时间，再创建全部初始化行；任何失败全部回滚。
- fresh/replay 分类必须先锁 event/control：只有 control 的 `owner_manifest_sha256` 已等于
  当前 manifest SHA 时才可走 replay；replay 仍精确核对最终时间和全部初始化行，但不再
  比较 pre-apply `updated_at`。任何不同 SHA 永远不能进入 replay。
- 相同 manifest SHA 的精确 replay 不新增 revision、participant、日志或 counter。
- 相同赛事上的不同 manifest、不同开赛时间或外部 ID 必须 fail closed。
- v2 允许复用合法运行中的 HostBudget；只核对 host 和 `min_interval_ms=1050` 等不可变
  配置，不要求 `next_allowed_at/circuit/failure/lock_version` 回到零。
- `policy_valid_until` 不得晚于 registry `valid_until`；prepare 和 initializer 都需复核。
  官方复核 route 另带 evidence SHA 和独立有效期，不能借来源 registry 自动背书。

### 初始状态与轮询

- prepare 与 initializer 使用同一个 aware `generated_at/clock`。
- 开赛前初始化为 `racecard_ready`，`next_poll_at` 必须由
  `calculate_race_live_next_poll_at()` 重新计算并精确验证。
- 到达或超过 off time 后初始化为 `awaiting_result`；首次 `next_poll_at=generated_at`
  立即 due，后续 checkpoint 恢复既有 3 分钟/有界探针算法。
- 对开赛前初始化的赛事，结果 runner 在持有有效 claim 且 `now >= race_datetime` 后，
  先用 owner/claim CAS 把 `racecard_ready` 晋级为 `awaiting_result`，再请求/应用 results。
  未到 off time 不允许提前晋级或发 HTTP；但有效 claim 必须通过成功 checkpoint 清除
  `active_attempt_token/claim_expires_at`，保持 failure counter 不变，并用同一调度函数把
  `next_poll_at` 推进到下一有界窗口（不得晚于 off time）。只有 claim 已失效或 owner
  漂移时才严格零 mutation。
- operator 不能任意填写 tracking state 或 next poll。

## 非目标

- 不自动启用 `RACE_LIVE_SCHEDULER_ENABLED`。
- 不把 runner 切换为 `the_racing_api_free`。
- 不切换任何 policy 到 `provisional_public`。
- 不实现赛后结果轮询；该能力已存在。
- 不实现初始化后的 racecard 变更、退赛 revision 或 off-time 改期自动 apply。
- 不实现五地区自动发现、官方来源适配器、official/corrected 自动晋级。
- 不购买 Basic、Standard、Pro 或地区 add-on。
- 不写或读取历史 runner 的 runtime、lease、checkpoint 或 source cache。

## 验收标准

1. 合成/获许可 fixture 能证明 today+tomorrow、唯一匹配和客观字段白名单。
2. 精确命中时输出 schema v2 manifest；零命中、多命中、字段漂移和不安全路径均无 manifest。
3. v2 dry-run 零数据库写入。
4. v2 apply 原子补齐时间并建立现有 initializer 的全部 shadow 基线。
5. apply 任一后段失败时，RaceEvent 时间与所有 live 表均保持 apply 前状态。
6. replay 幂等；竞争 manifest 至多一个成功。
7. schema v1 初始化回归不变。
8. 不在输出、日志、异常、数据库或镜像中暴露凭据/raw 响应。
9. Django check、migration drift、SQLite 目标/回归、PostgreSQL 事务竞争和
   Compose/secret 隔离验证通过。
10. 初始 pre-off tracking 可在 off time 通过 claim CAS 晋级 awaiting，并在赛后进入现有
    暂定赛果 runner；状态和 next poll 不由 manifest 调用方自由决定。
11. pre-off 有效 claim 会零 HTTP 地 checkpoint 释放并推进 next poll；stale claim/owner
    mismatch 零写入，不依赖 lease 超时恢复。
