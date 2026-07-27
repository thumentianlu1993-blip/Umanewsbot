## 0. Pre-declared hypotheses

- **H1 范围守恒 PASS：** 冻结基线必须精确满足
  `59 event rows = 40 missing + 9 duplicate-zero + 9 duplicate-confirmed + 1 provisional`
  与 `50 race groups = 40 missing + 9 duplicate groups + event 924`；任一计数或 event ID
  集合漂移即 BLOCKER，重新盘点与审批，不调整分母掩盖。
- **H2 来源覆盖 PASS：** 40 场 event ID 精确等于日本 6、英国 11、法国 4、美国 19；
  每场均有 candidate 或逐场 blocker，官方确认仅来自有效 route contract，`blocked=0`
  才能 completed。
- **H3 网络性能 PASS：** candidate prepare 总请求 `<=75`、单请求 timeout `<=30s`、
  source cache `<=512 MiB`；manual-only route 自动请求数必须为 `0`，缓存 resume 不重复请求。
- **H4 查询性能 PASS：** 59 行 inventory export `<=25 SQL`，40 场公开日历保持既有
  `<=12 SQL`；不得引入逐 event canonical/live resolver N+1。
- **H5 写入安全 PASS：** 每场单事务、owner/generation/current revision CAS、同 artifact
  幂等重放业务/审计/`updated_at` 零变化；任一 ledger/DB 身份不一致即 BLOCKER。

## 1. 方案门禁与 RED

- [x] 1.1 (operations) 对 proposal、design、四份 delta spec 和生产只读盘点运行独立工程审核，解决全部 P0/P1/P2 finding 后冻结实现范围。
- [x] 1.2 (application) 为双层 inventory、共享 lifecycle 到期判定、59 条 event row 守恒、跨 `RaceSeries` identity pending、数据库漂移拒绝、accounted 守恒与 `blocker=0` completion 编写测试并取得有效 RED。
- [x] 1.3 (integration) 为 `race_result_recovery` 结果专用编排、adapter 多模块过滤、空地区 blocker、来源层级和 TRA provisional 边界编写测试并取得有效 RED。
- [x] 1.4 (application) 为 recovery official receipt（同着/非完赛/route 过期）、participant 精确身份、canonical link constraint 与 PostgreSQL 并发防环、live 前置、historical/unmanaged/manual-paused owner 分支、official observation/revision 投影、write-ahead ledger/orphan、逐场事务回滚、幂等重放和非目标零变化编写测试并取得有效 RED。
- [x] 1.5 (application) 为日历/详情 canonical 单一展示、恢复后 finished/confirmed 状态和 cancelled/postponed 排除编写页面测试并取得有效 RED。

## 2. 核心实现

- [x] 2.1 (integration) 实现双层恢复 inventory、共享 lifecycle 到期判定、event/race-group identity、accounted/completion 状态、不可变 artifact 和 manifest SHA 校验。
- [x] 2.2 (application) 新增唯一一份 `RaceEventProductCanonicalLink` 模型迁移：两端 `ForeignKey(PROTECT)`、每个 duplicate 仅一条 active 的条件唯一约束、自环数据库约束、digest 约束、canonical/active 索引；事务服务使用 PostgreSQL advisory lock + row lock 校验同地区/年度与链/环，回滚只 inactive 且改选创建新审批行，接入后台只读入口。
- [x] 2.3 (integration) 扩展赛事编排以支持受限 `race_result_recovery + modules=["results"]`，复用请求预算、source cache、resume、coverage、candidate identity 和 apply-check。
- [x] 2.4 (integration) 将具备自动化许可的 JRA、NAR、HKJC、Sporting Life、ZEturf、TOBA chart discovery 与 TRA 候选统一为恢复 schema，保留 raw/normalized/display 三层值及来源权威等级；Equibase 既有 parser 仅处理另行获准的本地输入，不自动抓 chart，HRN 只做兼容回归。
- [x] 2.5 (integration) 实现 non-live recovery official receipt 批量审核包，复用 BHA、France Galop、JRA、NAR、HKJC、Equibase route registry 的 host/path/marker/digest/validity 校验，支持同着、非完赛和字段 provenance，不保存凭据或受限原始页面；event 924 保持既有 live receipt。
- [x] 2.6 (application) 实现 identity approval、participant/source identity 精确绑定、字段 diff、精确 manifest+approval 双 SHA、owner/generation CAS、official observation/revision/evidence、live 既有 transition 与 non-live recovery projection 分流、逐场原子 apply、OperationLog、每场不可覆盖 write-ahead rollback ledger、orphan verifier、幂等重放和独立 verifier 管理命令。
- [x] 2.7 (application) 接入 canonical product event 公开读取、日历去重与赛事状态展示，保持未确认冠军隐藏和详情 URL 稳定。
- [x] 2.8 (integration) 将 recovery inventory/crawl/apply/verify 命令纳入 `historical_batch_runner` 明确 allowlist 与 phase/参数分类，强制 crawl 仅网络、apply 仅写库、verify 双关闭。

## 3. GREEN、回归与独立代码审核

- [x] 3.1 (application) 运行 inventory/evidence/participant/canonical/owner-revision/apply/verifier/rollback/page focused 测试至 GREEN；SQLite 覆盖功能语义，PostgreSQL 单独覆盖 owner/generation、advisory/row lock、并发 canonical 审批与 apply，不宣称 SQLite 等价并发。
- [x] 3.2 (integration) 运行五地区 adapter 离线 fixture、结果专用编排、既有三模块编排、准实时 authority/publication 和生命周期回归，证明旧流程不变。
- [x] 3.3 (application) 运行完整 `stable` 回归、Django check、`makemigrations --check --dry-run`、OpenSpec strict/all、Compose config、`py_compile` 和 `git diff --check`。
- [x] 3.3a (integration) 对生产零请求暴露的 recovery expected-target、source-scoped adapter 输入和 JRA list/request-context 缺口补有效 RED，并完成最小修复与受影响回归。
- [x] 3.3b (integration) 对生产首次 prepare 暴露的 NAR/Sporting Life/ZEturf `scheduled` 静默过滤、candidate 丢失 target `event_id` 与 `Also Ran` 无顺序缺口补有效 RED；仅在 recovery mode 放宽输入，并在聚合层对所有来源以 `incomplete_result_order` 阻断缺参赛名单、缺马、重复身份、无效名次或 discovery-only 的不完整 finish order。
- [x] 3.3c (integration) 修复独立复审发现的 UK/US Sporting Life 标准输出覆盖及 recovery audit 外部 JSONL/跨来源绕过；补同 run 双来源产物、identity 绑定和 source/region mismatch RED。
- [x] 3.3d (integration) 对正式 `gap-v2` prepare 暴露的 JRA `中止` 非完赛语义补有效 RED；保留原始状态并规范化为 `pulled_up`，不补造数值名次，只允许受控非完赛状态退出完整排名分母，`unknown/declared/Also Ran` 继续阻断。
- [x] 3.4 (operations) 对精确实现 fingerprint 运行独立只读代码审核；首轮两个 P1 修复后，同一 reviewer 对 `cfba7151..c4ce802c` closure review 为 `APPROVED`、无 actionable finding。

## 4. 生产只读盘点与候选收集

- [x] 4.1 (operations) 取得精确 release 授权后部署受审版本，保持恢复 apply、网络自动化、TRA public、scheduler 和 publication 开关关闭，并验证生产 commit/镜像/迁移/健康。
- [x] 4.2 (operations) 生成 `2026-07-08..2026-07-27` 生产只读 inventory，核对 event row 数、race group 数、26 条重点缺口、9 组重复候选、event 924 provisional 和五地区分布。
- [x] 4.3 (operations) 对 inventory manifest 和 `source_research_20260727.md` 的精确 40 场 source map 取得明确审批后，仅对有自动化许可的 candidate route 按 `<=75` 请求、`<=30s` timeout、`<=512 MiB` cache 执行网络 prepare；manual-only 官方路由请求数必须为 0，只生成候选/source-cache/artifact，不写业务数据库。
- [ ] 4.4 (operations) 完成人工官方路由逐场核验、重复 identity review、字段 diff 和 blocker 分类，生成逐场 coverage、candidate SHA 与 dry-run。
- [ ] 4.5 (operations) 由独立 verifier 复核所有冻结目标 accounted 守恒，并分别报告 completion 是否 `blocker=0`、精确预计 result-row/revision/canonical-link create/update/delete、owner 分流和未闭环 blocker。

## 5. 受控生产写入与验收

- [ ] 5.1 (operations) 针对精确 candidate/approval SHA、预计写入、canonical 映射、blocker 和零删除范围取得新的生产写入授权；此前实现、部署或网络授权不得替代。
- [ ] 5.2 (operations) 暂停 beat、排空 historical/race-live 相关队列并证明无 active/reserved/lease，创建并校验 PostgreSQL custom-format 备份、环境备份和写前计数/身份快照。
- [ ] 5.3 (operations) 分地区串行执行精确 SHA apply，每批立即运行独立 verifier 和幂等重放；任何漂移或后段失败立即停止。
- [ ] 5.4 (operations) 在 1440px 与 390px 验收全部/重点/已完赛、五地区、重复赛事和目标详情页，检查 DOM 语义、横向溢出、导航、console、healthz 与部署镜像。
- [ ] 5.5 (operations) 恢复调度并确认新闻、QQ delivery、窗口外赛事、未来赛事和 TRA public 状态未被改变；记录观察窗口和剩余 blocker。

## 6. 文档与交接

- [x] 6.1 (operations) 更新 `docs/current_state.md`、`docs/decisions.md`、`docs/deploy_runbook.md`、`docs/project_overview.md`（如链路变化）和 `docs/project_status.md`，区分仓库预期、候选完成、生产写入与公开验收。
- [ ] 6.2 (operations) 固化 inventory/candidate/approval/backup/rollback/verifier SHA、逐地区覆盖、确切非影响范围和未解决 blocker，形成可由其他代理独立继续的完整交接。
