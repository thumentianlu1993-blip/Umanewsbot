## 0. Pre-declared hypotheses

- [ ] 0.1 (integration) H1 正确性：HKJC 最近 60 天 dry-run 解析到的赛日、比赛、赛果、唯一马匹数量必须来自真实页面；如果任一数量为 0 且页面可访问，判定为 BLOCKER。
- [x] 0.2 (integration) H2 限速：真实网络抓取相邻请求间隔必须不小于配置值；测试中移除 sleep 调用或绕过 rate limiter 必须失败。
- [x] 0.3 (application) H3 幂等：同一 HKJC 日期范围 commit 执行两次后，`ExternalRace / ExternalRaceEntry / ExternalRaceResult / ExternalHorse / ExternalHorseAlias` 不得重复增长。
- [ ] 0.4 (operations) H4 停止边界：每个地区最近 2 个月赛事和涉及马匹详情完成后不得注册 Celery Beat 周期任务；如发现新增周期调度，判定为 BLOCKER。
- [ ] 0.5 (operations) H5 生产安全：任何真实网络 commit 前必须有数据库备份路径、dry-run 结果、锁检查和用户确认记录；缺任一项不得执行生产 commit。

## 1. HKJC TDD 测试与 fixture

- [x] 1.1 (integration) 新增 HKJC 官方 `localresults` 赛日列表 HTML fixture，并写 RED 测试验证最近 60 天赛日筛选、日期格式和来源 URL 记录。
- [x] 1.2 (integration) 新增 HKJC 单场 `localresults` HTML fixture，并写 RED 测试验证比赛字段、结果表字段、马匹详情链接和 `horseid` 提取。
- [x] 1.3 (integration) 新增 HKJC 马匹详情 HTML fixture，并写 RED 测试验证英文名、牌号、产地、年龄、毛色、性别、练马师、马主、评分、父系、母系和 raw payload。
- [x] 1.4 (application) 写 RED 测试验证 HKJC 真实网络 dry-run 不写 `External*` 表，并返回请求数量、覆盖统计、限速配置和停止原因。
- [x] 1.5 (application) 写 RED 测试验证 HKJC 真实网络 commit 写入 `ExternalRace / Entry / Result / Horse / Alias` 且重复执行幂等。
- [x] 1.6 (application) 写 RED 测试验证 HKJC commit 仍受单来源锁、`max_races`、`max_horses` 和请求上限保护。

## 2. HKJC 真实 HTML 导入实现

- [x] 2.1 (integration) 实现 HKJC HTML client：统一 User-Agent、timeout、request interval、请求证据、HTTP 错误和低频 sleep。
- [x] 2.2 (integration) 实现 HKJC 赛日列表 parser，将 `localresults` 下拉选项解析为目标日期范围内的赛日。
- [x] 2.3 (integration) 实现 HKJC 单场结果 parser，将 race header、结果表、马匹链接和可用字段转换为规范 payload。
- [x] 2.4 (integration) 实现 HKJC 马匹详情 parser，将 profile 基础信息和近走摘要转换为规范 payload。
- [x] 2.5 (application) 扩展 `HKJCExternalDataImporter`，支持真实网络 race-date/date-range/recent-days dry-run 生成完整 payload。
- [x] 2.6 (application) 允许通过已验证的真实网络 payload 执行 HKJC commit，同时保留无网络占位 commit 拒绝和单来源锁。
- [x] 2.7 (application) 扩展 `import_hkjc_external_data` 管理命令，支持 `--recent-days`、`--start-date`、`--end-date`、`--limit-races`、`--limit-horses`、`--max-requests` 和请求证据输出。

## 3. 本地验证与香港小批量运行

- [x] 3.1 (application) 运行 HKJC 目标测试，完成 RED -> GREEN -> REFACTOR 记录。
- [x] 3.2 (application) 运行完整 `stable` 测试、`manage.py check`、`openspec validate connect-real-global-racing-databases --strict`、`openspec validate --all` 和 `git diff --check`。
- [x] 3.3 (integration) 在本地或隔离 SQLite 执行 HKJC 真实网络 dry-run 小范围样本，记录请求 URL、请求次数、覆盖统计和未写表证据。
- [x] 3.4 (integration) 在隔离 SQLite 执行 HKJC 真实网络小范围 commit，验证表计数、run stats、lookup 和幂等。

## 4. 香港最近 2 个月生产运行

- [ ] 4.1 (operations) 部署前读取生产 HEAD、容器状态、导入锁、started run 和 HKJC 现有计数，确认无外部长导入冲突。
- [ ] 4.2 (operations) 备份生产数据库并记录备份路径和校验结果。
- [ ] 4.3 (operations) 部署 HKJC 真实 HTML 导入代码，执行 `manage.py check`、`/healthz/` 和小样本 dry-run smoke。
- [ ] 4.4 (operations) 执行 HKJC 最近 2 个月生产 dry-run，记录请求数量、赛日数量、比赛数量、唯一马匹数量、失败摘要和预计写入量。
- [ ] 4.5 (operations) 经用户确认后执行 HKJC 最近 2 个月生产 commit，记录 `run_id`、表计数、锁释放、马名 lookup 和停止点。
- [ ] 4.6 (operations) 更新 `docs/current_state.md`、`docs/project_status.md`、`docs/deploy_runbook.md` 和 HKJC 数据导入文档。

## 5. 英国准入与正式导入准备

- [x] 5.1 (integration) 复核 Sporting Life racecards、results、horse profile 真实入口，保存请求证据和字段覆盖矩阵。
- [x] 5.2 (integration) 复核 BHA 官方可用入口，明确其作为主来源或补字段来源的职责。
- [ ] 5.3 (application) 在英国入口 `ready_for_formal_import` 后，按 TDD 新增英国 parser/importer fixture 和 dry-run 测试。
- [ ] 5.4 (operations) 仅在香港阶段完成后，按生产安全门禁执行英国最近 2 个月 dry-run/commit。

## 6. 法国准入与正式导入准备

- [x] 6.1 (integration) 复核 France Galop 或其他法国权威来源的赛程、出马、赛果和马匹 profile 入口，保存请求证据和字段覆盖矩阵。
- [ ] 6.2 (integration) 明确法语字段处理、原始 payload 保留和不进入新闻正文链路的边界。
- [ ] 6.3 (application) 在法国入口 `ready_for_formal_import` 后，按 TDD 新增法国 parser/importer fixture 和 dry-run 测试。
- [ ] 6.4 (operations) 仅在英国阶段完成后，按生产安全门禁执行法国最近 2 个月 dry-run/commit。

## 7. 美国准入与正式导入准备

- [x] 7.1 (integration) 复核 Equibase entries、results、chart/PDF 和 horse profile 入口，保存请求证据和字段覆盖矩阵。
- [ ] 7.2 (integration) 明确美国正式导入主来源采用 HTML chart、PDF chart 或 profile 页面，并记录访问限制风险。
- [ ] 7.3 (application) 在美国入口 `ready_for_formal_import` 后，按 TDD 新增美国 parser/importer fixture 和 dry-run 测试。
- [ ] 7.4 (operations) 仅在法国阶段完成后，按生产安全门禁执行美国最近 2 个月 dry-run/commit。

## 8. 收尾验证与归档

- [ ] 8.1 (operations) 确认香港、英国、法国、美国均完成最近 2 个月赛事和涉及马匹详情导入，且没有持续调度残留。
- [ ] 8.2 (operations) 汇总四地区表计数、run_id、失败摘要、备份路径、限速配置和停止时间。
- [ ] 8.3 (application) 运行最终测试和 OpenSpec 校验。
- [ ] 8.4 (operations) 归档 OpenSpec change，并同步正式规格和项目状态文档。
