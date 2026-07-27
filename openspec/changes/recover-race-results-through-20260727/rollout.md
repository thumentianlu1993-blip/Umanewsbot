# 发布与数据恢复计划

## 当前基线

- 本地基线：独立 worktree，`origin/main@a59956b327157d29630fab1f1c98ba9c9cacfed0`。
- 生产基线：`HEAD=a59956b327157d29630fab1f1c98ba9c9cacfed0`。
- 只读观察：窗口内精确为
  `59 event rows = 40 missing + 9 duplicate-zero + 9 duplicate-confirmed + 1 provisional`，
  对应 `50 race groups = 40 + 9 + event 924`；event 924 有 7 条未确认 TRA 结果，26 条重点赛事过期且零结果。
- 公网观察：`/races/?when=finished` 最晚展示 `2026-07-05`。
- 当前没有实现、部署、迁移、候选网络 run 或生产业务写入。

## 门禁

1. 方案审核：proposal/design/specs/test_cases/tasks/rollout 全部通过同一 reviewer。
2. 实现审核：测试先 RED；实现后 focused、PostgreSQL、完整回归、静态检查和独立 code review 通过。
3. Release 授权：绑定精确 commit/fingerprint，只允许部署关闭态代码与迁移。
4. Inventory 授权：生产只读生成，不触网、不写业务表。
5. Network prepare 授权：绑定 inventory SHA、地区、event IDs、具备自动化许可的 candidate
   来源、`<=75` 请求、`<=30s` timeout、`<=512 MiB` cache 和输出目录；只写
   artifact/source cache，manual-only official route 自动请求数必须为 0。
6. Production apply 授权：绑定 candidate/official-evidence/identity-review/approval SHA、owner 分流、result/revision/link 预计动作、备份和 blocker=0。
7. 公开验收：写后 verifier、幂等重放、浏览器与观察窗口全部通过后才称完成。

任何前一门禁的批准都不能替代后一门禁。

## 部署顺序

1. 重新核对生产 HEAD、镜像、队列、锁、磁盘和正在运行的历史/live/import 任务。
2. 创建环境与数据库恢复点，校验 custom-format、大小、mode、SHA 和 `pg_restore -l`。
3. 部署受审精确版本并执行迁移；恢复、网络、scheduler、TRA public、publication 均保持关闭。
4. 验证 web/worker/beat/race_live_worker 镜像一致、Django check、迁移、内外 healthz 和旧赛事页。
5. 生成并独立审核 inventory。
6. 按批准地区串行 prepare 与人工官方核验；禁止并发复用同一 run。
7. blocker 清零并取得精确 apply 授权后，暂停 beat、排空相关队列，分地区串行 apply。
8. 每批立即 verifier、幂等重放和非目标快照；异常即停。
9. 完成浏览器验收后恢复调度并观察。

## Owner 分流

- `live`：只走现有 manual official evidence/publication transition。
- `historical`：走历史 official revision 投影原语。
- `unmanaged`：CAS 晋级 historical 后走同一投影原语。
- `manual_paused` 或 identity/generation/revision 漂移：blocker，不写。

event 924 必须保持 live owner，不能为了本次恢复切换到 historical。

非 live 赛事不得调用要求 `LIVE + tracking claim` 的
`apply_race_result_observation_revision()`；它们走 recovery 专用 official
observation/revision projection。若 live 赛事缺少 allowlist、incident、provisional
revision、tracking 或 official authorization，保持 blocker，不由恢复命令补造。

## 迁移与并发

- 本 change 只新增 `RaceEventProductCanonicalLink` 一张空表及一份迁移；两端均
  `ForeignKey(PROTECT)`，条件唯一约束保证同一 duplicate 至多一条 active link，同时保留
  inactive 历史。部署迁移不创建 link、不接管 owner、不改赛事或结果。
- 空表阶段必须完成 PostgreSQL 与 SQLite migrate/rollback/migrate 往返。生产一旦存在 link
  审计，禁止反向迁移删除表；应用回滚采用停用 link + 前向修复，结构异常使用写前数据库恢复点。
- PostgreSQL canonical approval 使用 transaction advisory lock 与确定顺序 row lock；
  SQLite 仅验证功能，不替代真实 PostgreSQL 并发验收。

## 回滚

- canonical link：置为 inactive，恢复写前公开选择；不删除 link 审批记录。
- official projection：按 ledger 恢复写前 current revision、last-known-good pointer、结果投影、状态和确认时间。
- owner：仅在 generation/manifest/current revision 与本次写后身份完全一致时恢复写前 owner；否则拒绝自动回滚。
- revision/evidence/OperationLog 不物理删除。
- 每场 rollback ledger 为不可覆盖 write-ahead 文件；verifier 必须区分
  `applied` 与 `prepared_not_applied`，后者不能驱动 rollback。
- ledger verifier 失败、跨表漂移或批量异常时，停止写入并使用写前数据库恢复点。

## 完成定义

只有同时满足以下条件才可报告“7 月 8–27 日赛果收集并确认完成”：

- inventory event rows 与 race groups 数量守恒；
- 所有赛果应到目标均为 `confirmed_result`，`blocked=0`；
- inventory 已存在的 cancelled/postponed 身份未漂移且不创建结果；新发现取消/延期因本批
  无 outcome contract 只能 blocker；
- canonical link 无环、无跨地区/年度，公开日历无重复；
- owner/current revision/result projection/evidence verifier 全部通过；
- `/races/?when=finished` 与目标详情页验收通过；
- 新闻、QQ、窗口外赛事、未来赛事和 TRA public 状态无未授权变化；
- 恢复点、artifact SHA、逐场结果与剩余风险已写回规定文档。
