# event 924 暂定赛果单赛事公开灰度规格

## 文档状态

- 专项：准实时赛事赛果
- 变更：event `924` 已存 shadow 赛果的单赛事 `provisional_public` 灰度
- 基线：`origin/main@353464c76c63d1e43043ccbefe0ebc88274b0888`
- 阶段：方案限定复审 `APPROVED`，进入测试先行
- 生产边界：方案审核、代码审核和精确发布授权完成前，不改生产策略、不晋级
  revision、不新增公开结果、不打开 scheduler、不扩展其他赛事

## 背景

event `924`（2026 Newbury Hackwood Stakes，英国 G3）已经通过 The Racing API Free
有界单赛事 runner 取得首个完整 shadow 赛果。生产 observation `1` 和 result revision
`2` 保存了 7 匹马的完整 `1–7` 名次，但 `published_at`、`RaceEventResult`、
`RaceEventRevisionPublication` 和官方复核 incident 仍为空。

人工只读复核确认，TRA 的 7 匹顺序与 Racing Post 和 Sporting Life 的公开客观赛果一致。
该复核只是灰度证据，不把这两个网页升级为自动生产 API，也不复制它们的评论、评级、走势、
赔率分析或其他专有内容。

现有代码已经具备：

- 四层 publication policy 和精确 event allowlist；
- 唯一 `admit_race_live_publication()` 准入服务；
- revision publication audit、legacy current projection 和官方复核 incident；
- 前台 fail-closed read gate、“暂定赛果”标识和 kill-switch 隐藏语义；
- 独立 `race_live` worker、单赛事 claim/checkpoint、scheduler 默认关闭。

本次只补齐从“已经验证的 shadow revision”到“受控单赛事公开灰度”的可执行入口及页面一致性，
不实现英国官方自动抓取，也不扩大正式公开范围。

## 范围

### 包含

1. 新增严格、可哈希、可 dry-run/apply/verify 的 publication transition manifest。
2. 对 manifest 唯一绑定的 event、source、observation 和 revision 做 compare-and-swap
   校验。
3. 在一个数据库外层事务中完成：
   - 将 manifest 列出的四层 policy 从精确 shadow 版本提升为
     `provisional_public` 并递增版本；
   - 在 `control -> tracking -> event` 统一锁序下调用与现有
     `admit_race_live_publication()` 相同的唯一内部 admission core；
   - 物化当前 `RaceEventResult`、publication audit 和官方复核 incident；
   - 停用 event `924` 的后续 TRA tracking，但不改写 provider attempt/success 时间。
4. 暂定赛果公开时，把赛事粗状态从 `scheduled`/`running` 推进为 `finished`，但不把
   provisional 误写为 `result_confirmed_at`。
5. 物化公开结果时，可从同一获准 racecard revision 为同一 participant 补齐 result
   observation 中缺失的客观 `barrier` 和 `jockey_name`；不得覆盖非空 result 字段，不得
   引入评级、评论、预测、赔率分析或未留 provenance 的字段。
6. event `924` 的页面、日历、read gate、状态标识、kill switch 和回滚验证。
7. 用受审 prepare 工具在 promotion 前一次生成 promotion、disable 和 restore 三份独立
   CAS manifest；回滚只隐藏公开读取和停止新晋级，不删除 observation、revision、
   publication audit 或 incident。
8. 增加版本化的 BHA 人工官方复核 registry 和离线 evidence receipt 入口。该入口不自动
   抓取 BHA，不把 BHA 页面内容投影到前台，只记录人工核对的 marker、证据 SHA 和与 TRA
   客观顺序的比较结果。

### 不包含

- scheduler 从 `false` 改为 `true`；
- 增加 event `924` 以外的 tracking/allowlist；
- 重新请求 The Racing API 或任何第三方网页；
- 把 Racing Post、Sporting Life 或偶尔可访问网页作为稳定实时 API；
- 将 TRA provisional 标为 official；
- 实现 BHA 自动 adapter、自动网页提取、自动 official/corrected importer 或 incident
  自动探针；
- 购买 Basic、North America add-on 或历史包；
- 修改历史 runner、历史 receipt/checkpoint、新闻 worker 或 QQ 队列；
- 发布其他地区或其他赛事。

## 功能要求

### Requirement 1：transition manifest 必须严格绑定当前事实

manifest 至少绑定：

- schema version、generated time、approved commit、event ID、source key；
- expected owner generation、owner manifest SHA；
- expected tracking state、claim generation、空 active claim；
- expected observation ID、parser version、phase、normalized SHA；
- expected result revision ID/no、phase、content SHA、未发布状态；
- expected racecard revision ID 和 participant 集合摘要；
- 四层 policy 的 scope/type/key/mode/version/registry/coverage/validity；
- allowlist 的 source、enabled、max mode、version、coverage digest、官方 route/version/
  contract digest、terms evidence digest、validity；
- transition 类型和目标 mode；
- event `924` 是 tracking/allowlist 精确全集的断言；
- 预期 legacy result、publication、incident 数量。
- BHA manual route registry 的 digest/version/validity、terms evidence digest、
  operator role 和 SLA。

未知字段、重复 scope、额外 event、摘要不匹配、过期许可、不同 commit、已有 publication、
不同 owner 或 active claim 均必须在任何写入前 fail closed。

### Requirement 2：dry-run/apply/verify 必须可重复且不允许模糊写入

- 默认只 dry-run；`--apply` 必须同时要求 `--confirm-apply`。
- apply 必须要求 expected manifest SHA 和 expected approved commit。
- 同一成功 apply 重放不得新增 revision、publication、legacy result、incident 或操作日志；
  只能返回已应用/已验证状态。
- verify 只读核对 manifest 规定的 post-state；不“修复”漂移。
- 任何异常必须使外层事务整体回滚，不能留下 policy 已开而 promotion 未完成的半状态。
- `prepare_race_live_publication_transition` 必须从 PostgreSQL
  `REPEATABLE READ READ ONLY` 一致快照生成 promotion、
  disable、restore 和 SHA ledger；拒绝 symlink、不安全 root、覆盖已有 run 或非独占写入。
- promotion 前对 promotion 做数据库 dry-run，并对完整三段链做纯结构/CAS 投影验证；
  promotion 后、disable/restore 前仍须各自对当时数据库独立 dry-run。

### Requirement 3：不得绕过现有 publication admission core

- 现有 poll admission 和新的 persisted-shadow transition 必须调用同一个内部 locked
  admission core；不得复制一套较弱的身份、条款、完整性或人工锁判断。
- poll 路径继续要求匹配 owner/claim generation/token；operator transition 要求
  scheduler false、active claim 为空、expected manifest SHA/approved commit 匹配，并在
  `control -> tracking -> event` 锁序下执行，不伪造 provider claim。
- participant 必须全部 approved，result participant 集合必须与 current racecard 集合
  完全一致。
- TRA authority 继续固定为 supplemental。
- `official_verification_route` 只代表已配置的异步复核路径；不代表已官方确认。
- promotion 必须把版本化 route contract digest 和 terms evidence digest 写入 allowlist
  快照并递增 allowlist version；incident 必须保存同一 contract/terms digest 和
  `promotion commit + 15 分钟` 的人工复核责任时限。
- operator transition 不改变 `claim_generation`、`last_attempt_at`、`last_success_at`、
  `last_observation_hash`、`consecutive_failures` 或 `stale_at`；成功后只将
  `tracking_enabled=false`、`next_poll_at=null` 并写独立 operation log，避免未来开启
  scheduler 时立即重投已过 today 窗口的 event `924`。

### Requirement 4：event 924 页面必须表达真实暂定状态

成功晋级后：

- 当前 revision 仍是 `provisional`，来源类别显示“补充来源”；
- 页面显示“暂定赛果”“尚待官方来源复核”和公开时间；
- 结果顺序严格为 revision `2` 的 1–7 名，不重新排序或猜测；
- `RaceEvent.status` 显示为 `finished`；
- `result_confirmed_at` 仍为空；
- racecard 已有的闸位和骑师可作为客观 fallback；未取得的练马师、时间、马身差、负磅保留
  空值/`-`，不得从受限网页复制；
- provisional hero 不得显示“赛果已确认”，只显示“冠军 · 暂定”或等价明确措辞；
- 日历页和详情页使用相同 read gate，不能一处显示、一处隐藏。

### Requirement 5：官方复核必须与暂定首发解耦且当前可执行

- public admission 成功时创建且只创建一条 event/revision/route-version incident。
- event `924` 的 `bha_manual_verification / bha-manual-v1` 必须由受审 route registry
  定义：BHA Results 官方入口、manual-browser-only、禁止自动提取、release operator
  责任角色、15 分钟 SLA、证据 JSON schema、terms/route digest 和有效期。
- promotion 前，release operator 必须人工打开 BHA Results 入口，确认受审 route
  `manual_browser_only` 当前可执行；registry/terms 过期或入口当前完全不可人工访问时停止
  promotion。暂定首发不要求 official result 已经出现，也不要求 promotion 前已生成赛果
  receipt。
- promotion 后由 release operator 在 15 分钟责任时限内，使用离线 prepare 命令录入
  source URL、observed_at、私有截图/打印件 SHA、marker 和客观完赛 participant/position，
  生成 `0600` receipt。receipt 不保存评论、评级、赔率、页面 raw 或逐马版权描述，且
  comparison 必须由 apply 服务计算，不能由操作者自报。
- 离线 apply 命令验证 expected receipt SHA、approved commit、route registry、event、
  revision、participant 集合和 incident；可用结果写成不可变 manual official
  observation、marker contract/evidence，并将 incident：
  - 一致：`resolved`，保留 provisional public；official 公开仍等后续 `official_public`
    变更；
  - 冲突：`escalated`，并在同一事务中使用预生成的 disable manifest 立即收紧 event
    policy；
  - 暂不可用/尚无结果：不伪造 observation，写脱敏 operation evidence，保持
    `open/overdue`、发一次告警并安排下一探针；符合既有产品决策，明确 provisional 继续
    可见。
- Racing Post 和 Sporting Life 只能作为人工交叉核对证据，不能替代 BHA route 或 marker。
- BHA 官方 evidence 未取得并应用前不得生成 official/corrected public revision，不得显示
  “正式赛果”。
- event `924` 在晋级时已超过 T+2h，因此 promotion 和首次 manual probe 必须在同一维护
  窗口完成；本次不伪造自动探针或官方完成时间。若首次 probe 暂不可用，未完成的后续人工
  复核必须作为显式剩余风险和 open incident 报告。

### Requirement 6：共享 policy 必须允许后续 shadow 初始化

- global/UK region/TRA source 作为长期最大权限 cap，可在首次灰度后保持
  `provisional_public v2`；每个 live-owned event 必须存在显式 event policy。
- resolver 在尝试 public admission/read 时，event policy 缺失必须 fail closed，不能只靠
  allowlist 继承宽作用域 public cap。
- initializer 必须接受版本化、digest/validity 匹配的既有 shared policy，不得只接受
  `shadow v1`；每个新 event 仍创建独立 `event:ID shadow v1`。
- initializer 对 shared global/region/source 与 event scope 使用不同匹配器：shared
  policy 可复用合法的 v2+ cap；新 event policy 若已存在且不是精确 shadow v1 则冲突，
  不得继承宽 scope 自动公开。
- event `924` disable 只把其 event policy收紧到 `shadow`；promotion、disable、restore
  分别使用独立 CAS manifest 和确定版本。
- 完成 event 924 promotion/disable 后，初始化第二个精确 shadow event 必须继续成功；
  新 allowlist 即使存在，也不能在缺失/仍为 shadow 的 event policy 下公开。

### Requirement 7：kill switch 和回滚必须立即生效

- event/global/region/source 任一 policy 收紧到 `shadow` 或 `off` 后，详情页和日历立即隐藏
  live 结果。
- 隐藏不删除 revision、publication、legacy projection 或 incident。
- 重新打开只能恢复 manifest 明确允许的当前 revision。
- 数据异常时优先执行 event `924` 精确 disable manifest；结构性异常才使用发布前数据库
  备份恢复。

## 非功能要求

- PostgreSQL 上 policy lock、operator admission、projection 和 tracking stop 必须在同一
  外层 transaction 中验证原子性，并与真实 runner 竞争时保持统一锁序、无死锁。
- 命令输出只包含 event ID、行数、版本、摘要和原因，不输出 API 凭据、raw payload 或第三方
  专有字段。
- 不新增常驻 worker，不改变 Celery route、并发、CPU/内存限制或 Beat schedule。
- 公开晋级不发网络请求，因此不消耗 The Racing API host budget。
- 变更需要 Django system check、migration drift、SQLite 聚焦测试、PostgreSQL 原子性测试、
  页面集成测试和现有准实时回归。

## 验收标准

1. event `924` 的 manifest dry-run 在当前 shadow baseline 返回 `ok=true`，业务零写入。
2. 人为改变任一 event/source/revision/hash/policy version/allowlist/participant/claim 后，
   dry-run/apply 在首写前失败。
3. apply 成功后恰有：
   - result revision `2` 仍为唯一 current result revision；
   - revision publication `1`；
   - legacy result `7`；
   - official verification incident `1`；
   - active claim `0` 且 claim/provider timing 字段未被 operator promotion 改写；
   - 四层 policy 为 `provisional_public` 且版本按 manifest 精确递增；
   - allowlist version 从 `1` 精确递增到 `2`，并持久保存 route contract/terms digest；
   - incident 保存相同 digest 和 `promotion commit + 15 分钟` 的人工责任时限。
4. 页面显示正确的 1–7 名、“暂定赛果”“补充来源”和更新时间，不显示“正式赛果”。
5. event 状态为 finished，`result_confirmed_at=null`。
6. BHA manual 首次 probe 在 promotion 后 15 分钟内执行：一致时 incident resolved；冲突
   时 event 924 在同一事务自动 disable；暂不可用时保持 provisional、open incident 和一次
   告警，绝不误标 official。
7. scheduler 仍为 false，tracking/allowlist 精确全集仍为 `[924]`，live/news/history 队列无
   范围扩展。
8. event 精确 disable 后页面立即隐藏，但审计事实数量不减少；随后初始化另一个 shadow
   event 的回归继续通过。
