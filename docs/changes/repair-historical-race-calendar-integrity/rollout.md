# 历史赛事赛历完整性修复 rollout

## 1. 工作区与基线

- worktree：
  `/Users/mentianlu/.codex/worktrees/diagnose-historical-race-calendar-gaps/umanews`
- branch：`codex/diagnose-historical-race-calendar-gaps`
- 起始基线：`origin/main@43b81fd3288a1e7b997ffad78d03565327e3d990`
- 诊断基线：`docs/historical_race_calendar_gap_diagnosis_20260731.md`

主工作区、生产数据库和既有 historical runner 不参与本轮设计写入。

## 2. 与既有在途工作的关系

- `backfill-race-events-to-1984` 旧 OpenSpec 仍是历史链在途基线，但其中“公开 URL 使用届次年”
  和“重点=P0/P1/人工置顶”两项合同被本 change 显式取代；其具体 spec/design/test 与 runbook
  必须在实现中同步，不能只依赖本 rollout 声明。
- `formalize-historical-batch-crawl-pipeline`、`scale-and-isolate-historical-race-batches` 的
  runner、artifact、租约和资源隔离不改；本 change 只调整年份身份消费合同和数据 verifier。
- 2026 系列 identity、P0 马来源、race-live projection、历史详情导入都引用 `RaceEvent.year`，
  实现前必须重新盘点并逐一迁移为公开自然年或届次年，不能机械替换。
- 年度分级赛参赛马 collector 是 GitHub Actions artifact-only 链路；修复不连接生产数据库。

## 3. 阶段和门禁

### R0：设计

- 完成 spec/design/test/tasks/rollout。
- 独立方案审核通过。
- 不写测试、业务代码、迁移或生产数据。

### R1：本地实现

- 用户已明确授权实现并取得真实 RED。
- Release A 兼容 schema、代码和离线数据工具已完成本地实现。
- 最新主线程 Django `205/205`、collector `101/101`；URL + detail `166/166`、gate
  `68/68`，Django check、migration drift/graph 和 diff check 通过。
- 真实 PostgreSQL Release A 专项连续两轮 `5/5`；migration 往返、约束和 shared/exclusive
  并发已验证。50k 性能门禁尚未完成。完整 `stable` 为
  `3989 tests / 25 failures / 54 errors / 72 skipped`，包含已识别环境/既有失败，不能声称
  全绿。

### R2：Release A 关闭态发布

- 最新 review 后取得发布授权。
- 镜像只包含 nullable `edition_year`、全量 canonical path registry 回填、target supersession、
  `HistoricalRaceCalendarRepairReceipt` 和兼容代码；Release B/C migration 在该 commit 中
  不得存在。
- 不自动执行香港 prepare/apply，不启动网络，不改变历史可见性。

### R3：全库生产只读 census

- 另行取得生产只读/必要来源 cache 访问授权。
- 冻结全地区 mismatch；每行必须生成 action。香港生成完整 duplicate/依赖图，非香港合法跨届次
  也必须修 public year/path、保留 edition，不能只分类。
- 数据库保持零写入。

### R4：Release B

- census 已证明可移除旧 `(race_series, year)` 约束。
- 单独提交、review、授权并发布 series/edition 约束切换；`edition_year` 仍 nullable。
- 保存唯一 migration leaf、commit/image 与 pending plan。

### R5：人工 approval 与数据写入

- artifact 冲突清零并冻结 manifest/approval SHA 与 action IDs。
- 最新状态复核、maintenance/freeze、备份验证和精确生产写入授权后单事务 apply。
- `HistoricalRaceCalendarRepairReceipt`、独立 verifier、公网旧新 URL、历史筛选和 collector
  结果验收。

### R6：Release C 约束收紧

- 全库自然年/届次 verifier 通过后，单独提交、review、授权和发布 non-null/check constraint。
- verifier 未通过时保持 Release B 兼容 schema，不猜测成功。

## 4. 灰度和开关

- 前台分页和历史重点是代码行为，随 R2 生效；发布前必须用真实数据量 explain 和浏览器验收。
- public-path registry 读取随 R2 上线；migration 回填全部 canonical path，在香港 apply 创建
  legacy path 前不改变现有 URL。
- 香港 prepare/apply 命令没有 Celery/Beat 注册，不加入自动调度。
- apply 继续受现有历史 backfill 总开关、显式 `--apply`、manifest/approval SHA、action scope、
  actor 和 maintenance 门禁保护。
- collector 规则随新 workflow/code 生效；正式年度运行只允许全新 output root/fresh run，不提供
  旧 checkpoint 迁移。

## 5. 发布前检查

- worktree 已迁移到最新 `origin/main` 并处理所有相关在途变更。
- 无同 scope historical inventory/detail/series reconciliation、race-live projection 或 P0
  participant 写任务。
- migration plan 只含本 change 受审 migration。
- Release A migration 对当前生产行兼容，不要求错误香港数据先被修复，且镜像中不存在 B/C leaf。
- Release B/C 各自必须在前置 receipt 满足后才创建和发布，不能与 A 存在于同一 migration graph。
- 两份 Compose config、Django check、完整回归、真实 PostgreSQL 和 review fingerprint 通过。
- 备份、回滚命令和 public-path registry 路由已演练。

## 6. 生产检查点

- P0：Release A schema/代码已部署，历史数据零写入。
- P1：全库 census/香港 action artifact 完成，记录分类总数和 SHA。
- P2：Release B 约束切换已发布，数据仍未 apply。
- P3：人工 approval 完成、maintenance/备份已验证、尚未 apply。
- P4：单事务 apply、`HistoricalRaceCalendarRepairReceipt` 和独立 verifier 完成。
- P5：Release C 最终约束发布完成。
- P6：evidence-only 文档收尾。

每个检查点都必须记录实际 commit/image/schema/run id；前一检查点成功不自动授权后一检查点。

## 7. 回滚矩阵

| 阶段 | 回滚 |
|---|---|
| R1 本地 | 丢弃本 change 改动；不影响生产 |
| R2 Release A | 保留 nullable 字段/registry 表，回退兼容代码；不反向删除 schema |
| R3 census | 删除/归档未批准 artifact；数据库本来零写入 |
| R4 Release B | 先判断旧代码/schema 兼容，必要时显式反向 migration；不能只 checkout |
| R5 apply 未提交 | 事务回滚，repair receipt 不存在，verifier 确认零部分写 |
| R5 apply 已提交 | 当前状态匹配时按 ledger 精确回滚；否则停止并评估已验证备份 |
| R6 Release C | 不可直接恢复旧坏年份；先独立授权反向约束 migration，或恢复已验证整库备份 |

## 8. 验收抽样

- 全库：每个 mismatch 均有分类，非香港至少抽查一例合法延期（若存在）。
- 香港：至少覆盖香港杯完整序列的多对一检查、普通马季赛事和一例合法延期（若生产存在）。
- 日本：2024 “全部”从 1 月遍历至 12 月，重点包含 G1/G2。
- 分页：综合和单地区各抽一个超过 40 条 scope，核对唯一 ID 总数。
- 跨栏：A. P. Smithwick Hurdle 与另外两场已知无马号赛事。
- 回归：当前年重点、本周焦点、首页今日赛事、sitemap、相关文章赛事链接和系列历届导航。

## 9. 当前状态

- 四类根因已完成只读诊断。
- 独立方案审核三轮完成：Round 1 为 3 P0/7 P1/3 P2，Round 2 剩余 1 P0/2 P1，Round 3 全部关闭，
  最终 `APPROVED`，开放 P0/P1 为 0。
- 用户已明确“开始实现”。Release A 本地实现包含 nullable `edition_year`、public-path
  registry、repair receipt、target supersession、`0067`、历史 key G1/G2、`year/q` 稳定
  分页、legacy 301、collector 缺号/fresh root/计数，以及全地区离线
  prepare/apply/verifier/rollback 工具；Release B/C migration 尚不存在。
- 同一 reviewer 第二轮限定复审为 `VERDICT: APPROVED`，前轮 `1 P1 + 3 P2` 已关闭；
  `codex review` read-only exit `0`，pre/post fingerprint 均为
  `88c53c265cd0de5748438648f637e0975e75389ee8b636ab1c3848f68d033eb3`。approved parent 为
  `43b81fd3288a1e7b997ffad78d03565327e3d990`，approved content 为
  `1a31d68e51d8aa4ce28249c4feb2f3fa82517d9277818da063214972fda9646f`。
- approved content 不含最终 P1/P2 加固、PostgreSQL 专项和本次文档增量，现已失效；必须复用
  同一 reviewer 重审当前完整 diff。未运行生产 census/apply，未访问或修改生产数据库，未
  commit/push/PR/部署，发布授权尚未请求或取得。

## 10. 首次代码审核修复（第二轮限定复审已关闭）

- Release A 的 `0067` 原地加入实时 maintenance gate；没有创建 `0068`，Release B/C 仍不存在。
- gate 由独立 enter/exit 命令维护，绑定 manifest SHA、action scope SHA、actor 和时间审计。
  PostgreSQL writer/transition 分别取得共享/独占事务 advisory lock；apply/rollback 在锁内再次
  检查 exact active gate，等待 writer 不会带陈旧 admission 提交。
- `RaceEvent` 新建及身份变更统一验证自然年/届次证据，并与 canonical path reserve/sync 同事务；
  legacy 抢占目标路径时 fail closed 并回滚 event 写。
- crash recovery 只接受 exact orphan ledger 且数据库保持 manifest pre-state；篡改/漂移拒绝。
- 该段为首次 review 修复时的历史状态；后续已取得下述真实 PostgreSQL 验收。仍不得据此宣称
  当前增量已 review、已获发布授权或生产门禁通过。

### 第一次复审 follow-up

- 修复 `RaceReferenceReceipt` 不可变 `delete` 被错误覆盖的问题；instance admission 仅保留在
  RaceEvent、public path 与 historical target。
- `RaceEvent.save(update_fields=...)` 现在使用 effective write-set，避免未落库的内存 year/slug
  驱动 registry 或年份验证。
- dependency snapshot 以 model + reverse accessor + FK field 作为 key，保留同 model 多 FK。
- SQLite 相关聚焦 `115/115`，check、migration drift 与 diff check 通过；`0067` 未增加
  schema，未新增 migration。同一 reviewer 第二轮限定复审已关闭前轮 `1 P1 + 3 P2` 并给出
  `VERDICT: APPROVED`。

### 第二轮限定复审冻结证据

- 原生 `codex review` 在 read-only 模式 exit `0`。
- pre/post fingerprint：
  `88c53c265cd0de5748438648f637e0975e75389ee8b636ab1c3848f68d033eb3`。
- approved parent：`43b81fd3288a1e7b997ffad78d03565327e3d990`。
- approved content：
  `1a31d68e51d8aa4ce28249c4feb2f3fa82517d9277818da063214972fda9646f`。
- 该批准仅标识后续 P1/P2、PostgreSQL 专项与事实文档写回前的实现快照，当前已失效；必须
  复用同一 reviewer 重审。发布授权尚未请求或取得。

### 最终全量扫描 follow-up（待复审）

- public-path FK 删除语义改为随 RaceEvent 原子级联；registry row 无 event 时不可解析，不保留
  孤儿。active maintenance gate 下 event instance/QuerySet delete 仍 fail closed。
- orphan recovery 先验证 controlled path/symlink components，再以 `O_NOFOLLOW` regular
  descriptor 单次读取；同一 bytes 用于 digest 与 JSON。root 内/外 symlink 均 fail closed。
- 聚焦 `116/116` 与 fresh `0066→0067→0066` 通过；无新 migration、无生产操作，待再审。

### 真实 PostgreSQL Release A 验收

- 新增 `test_historical_calendar_release_a_postgres.py`，隔离 PostgreSQL 连续两轮 `5/5`。
- fresh migrate `7.96s`；`0066→0067` `0.346s`；`0067→0066` 约
  `0.463–0.475s`。
- shared/exclusive advisory lock 使用实际 `pg_locks` 未授予记录作为等待证据，约
  `0.024s`；排队 writer 锁后重查 active gate 并被拒绝，exit 后恢复，无 deadlock 或陈旧提交。
- 约束验收覆盖路径冲突整笔回滚、event/path `CASCADE`、receipt manifest unique 与单 active
  gate 条件唯一。
- 临时容器 `umanews-histcal-pg-accept-20260731-a1` 和 tmpfs 已删除，其他容器未改变。
- 完整 `stable` 未重新变成全绿，50k 性能、Release B/C、生产 census/apply 均未运行；此前
  review fingerprint 已失效，当前必须重新 review。

### descriptor 与提交后缓存失效 follow-up

- current-year descriptor 显式区分 public year 和 edition year；slug、query、identity 使用
  public year，跨届次 event 仍强制携带 descriptor。
- apply/rollback 的 public cache invalidation 只通过 `transaction.on_commit` 注册；失败事务及
  existing receipt 幂等重入均不清缓存。
- descriptor `13/13`、cache `10/10`，合并 Django `224/224`、collector `101/101`；check、
  migration drift、diff check 通过。真实 PostgreSQL `5/5` 两轮证据保留。
- 旧 review fingerprint 不覆盖该增量，必须复用同一 reviewer 复审；完整 `stable` 仍保留既有/
  环境 `25F / 54E / 72S`，无 commit/push/PR/deploy、生产 census/apply 或发布授权。

### 写总门禁、authority URL 与 detail edition follow-up

- apply/rollback 及 existing receipt 重入必须通过
  `HISTORICAL_RACE_BACKFILL_ENABLED=true`；prepare/verify 为只读入口，不受该开关影响。
- 跨届次 `authority_url` 必须为有效 HTTPS、受控 host、无 credentials/fragment，合法 query
  保留；detail `edition_year` 只在字段缺失时回退，显式值严格为非 bool `int 1..9999`。
- detail clean RED 未保存：首次运行被陈旧 SHA fixture 先行遮蔽，修正 fixture 后直接 GREEN；
  本记录不追溯冒充 RED。
- 最新主线程 `205/205`、URL + detail `166/166`、gate `68/68`；真实 PostgreSQL `5/5`
  两轮、collector `101/101` 保留，check、migration drift、diff check 通过。
- 完整 `stable` 仍非全绿，旧 fingerprint 失效待同一 reviewer 复审；无 commit/push/PR/deploy、
  生产 census/apply 或发布授权。

### URL 中央 validator P1 限定复审

- 同一 reviewer 最终 `APPROVED`，确认 `URL central validator P1 CLOSED`；原生 review 为
  read-only、exit `0`。
- pre/post fingerprint 均为
  `91fed97e63acacbb28ee8fed717edc049d1812f0dead8465c5a6f139bd110a39`；approved parent 为
  `43b81fd3288a1e7b997ffad78d03565327e3d990`；approved content 为
  `b3353358647cd7b842a5a16326deee25ecc09485f37f7cd6974ed32b53868d2e`。
- 本次 evidence-only 文档写回使 content 过期，须复用同一 reviewer 做 evidence 增量复审；
  `10.3` 总门保持未完成。
- URL `76/76`、主线程 `205/205`、真实 PostgreSQL `5/5` 两轮、collector `101/101`；完整
  `stable` 仍非全绿。
- non-blocking P2：apply/rollback 与 maintenance exit 存在理论锁顺序反转。PG `5/5` 未复现，
  但没有专项并发 exit 验证，故未关闭并进入后续任务。
- 无 commit/push/PR/deploy、生产 census/apply；发布未授权。

### 最新复审路径安全 P2（实现关闭，待复审）

- `_controlled_path` 改为 raw absolute path 先逐组件拒绝 symlink，再 resolve/归属检查并复核
  resolved path；受控 root 内 alias 不再被 resolve 洗掉。
- controlled input 读取以 root dirfd 为锚逐层 `O_NOFOLLOW` 打开，父目录/leaf 不通过路径重新
  跟随；hash 与 JSON 使用同一 descriptor bytes。
- manifest、approval、maintenance 三类 in-root alias RED/GREEN，root 外和 direct regular file
  合同保持；聚焦 `98/98`，check/drift/diff 通过。无 migration、无生产操作，待再审。

### 最新复审历史写入总门 P1（实现关闭，待复审）

- apply/rollback 在所有 artifact、receipt 和 rollback ledger 处理前集中要求
  `HISTORICAL_RACE_BACKFILL_ENABLED=true`；配置缺省或 false 均 fail closed。
- rollback 会恢复业务行并更新 receipt，按既有历史业务写入合同受同一总门保护；prepare/verify
  保持只读。existing receipt 重入不能在总门关闭时触发 verifier 写入。
- 新增 3 项 RED/GREEN；integrity/tooling/review-fixes 聚焦 `55/55`，加入 descriptor 回归后
  `68/68`；check、migration drift、diff check 通过。无 migration、无生产操作，当前增量等待
  同一 reviewer 限定复审。
