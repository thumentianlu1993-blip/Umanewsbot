## 0. Pre-declared hypotheses

- [x] 0.1 (integration) H1 正确性：HKJC 最近 60 天 dry-run 解析到的赛日、比赛、赛果、唯一马匹数量必须来自真实页面；如果任一数量为 0 且页面可访问，判定为 BLOCKER。
- [x] 0.2 (integration) H2 限速：真实网络抓取相邻请求间隔必须不小于配置值；测试中移除 sleep 调用或绕过 rate limiter 必须失败。
- [x] 0.3 (application) H3 幂等：同一 HKJC 日期范围 commit 执行两次后，`ExternalRace / ExternalRaceEntry / ExternalRaceResult / ExternalHorse / ExternalHorseAlias` 不得重复增长。
- [x] 0.4 (operations) H4 停止边界：本会话按 proof 边界停止，不注册 HKJC、英国、法国或美国 Celery Beat 周期任务；如后续发现新增周期调度，判定为 BLOCKER。
- [x] 0.5 (operations) H5 生产安全：本会话不执行英法美生产 commit；后续任何真实网络 commit 前必须有数据库备份路径、dry-run 结果、锁检查和用户确认记录，缺任一项不得执行生产 commit。

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

- [x] 4.1 (operations) 部署前读取生产 HEAD、容器状态、导入锁、started run 和 HKJC 现有计数，确认无外部长导入冲突。
- [x] 4.2 (operations) 备份生产数据库并记录备份路径和校验结果。
- [x] 4.3 (operations) 部署 HKJC 真实 HTML 导入代码，执行 `manage.py check`、`/healthz/` 和小样本 dry-run smoke。
- [x] 4.4 (operations) 执行 HKJC 生产 plan-only 和前 120 场 full dry-run，记录请求数量、赛日数量、比赛数量、唯一马匹数量、失败摘要和预计写入量。
- [x] 4.5 (operations) 按用户指令暂停香港；不执行 HKJC 生产 commit，记录停点、锁释放和正式表计数。
- [x] 4.6 (operations) 更新 `docs/current_state.md`、`docs/project_status.md`、`docs/deploy_runbook.md` 和 HKJC 数据导入文档，说明香港暂停且后续进入英国真实抓取。

## 5. 英国准入与正式导入准备

- [x] 5.1 (integration) 复核 Sporting Life racecards、results、horse profile 真实入口，保存请求证据和字段覆盖矩阵。
- [x] 5.2 (integration) 复核 BHA 官方可用入口，明确其作为主来源或补字段来源的职责。
- [x] 5.3 (application) 按 TDD 新增英国 Sporting Life parser/importer fixture 和 dry-run 测试，覆盖日期结果页、单场 racecard/result 和 horse profile。
- [x] 5.4 (integration) 实现英国 Sporting Life 真实抓取管理命令，支持日期范围、recent-days、limit-races、limit-horses、max-requests、dry-run 和请求证据输出。
- [x] 5.5 (operations) 执行英国最近 2 个月 live dry-run 或拆批 dry-run，记录请求数量、比赛数量、唯一马匹数量、失败摘要和预计写入量。
  - 2026-06-26 已完成首批 `limit-races=5 / limit-horses=10` dry-run；2026-06-27 已新增 `--skip-races` 并完成 `skip=5` 续批 dry-run。
  - 2026-06-27 已新增英国 `--plan-only --batch-size`，真实 plan-only 只请求 `60` 个日期结果页，不抓 racecard/profile，枚举 `47` 场比赛、`10` 个批次；随后完成第 `3` 批 `skip=10` dry-run，请求 `47` 次页面，覆盖 `5` 场、`82` 条 entries/results、`82` 匹唯一马并补抓 `10` 个 profile。
  - 2026-06-27 已完成第 `4` 批 `skip=15` dry-run，请求 `75` 次页面，覆盖 `5` 场、`65` 条 entries/results、`65` 匹唯一马并补抓 `10` 个 profile；本批使用 `2` 秒/请求限速。该 `4/10` 口径为未过滤海外赛场前的历史拆批记录，后续已由英国赛场 allowlist 和 proof 边界取代。
  - 2026-06-27 已按 TDD 增加英国赛场 allowlist 和 `--race-urls` 精确批次入口；过滤海外赛场后当前有效英国窗口为 `35` 场、`7` 批，早先 `47` 场 / `10` 批为未过滤历史证据。已用精确 URL dry-run 完成剩余 racecard 覆盖：`SL924388..393` 请求 `15` 次覆盖 `5` 场、`27` 匹唯一马；`SL924394..924418` 请求 `15` 次覆盖 `5` 场、`37` 匹唯一马；`SL925053..925058` 请求 `16` 次覆盖 `6` 场、`73` 匹唯一马。英国 racecard dry-run 已覆盖 `35/35` 场；完整 profile 大量补抓改由后续会话处理。
  - 2026-06-27 用户收敛边界：本会话只需抓几个真实批次证明接入和 importer 可用，完整大量爬取后续另开会话。随后完成两组英国全量 profile proof：`SL915095,SL915096,SL916196,SL916199,SL916198` 请求 `51` 次，覆盖 `5` 场、`46` 匹唯一马，`horse_profiles_fetched=46`，`completion.is_complete=true`；`SL916197,SL916201,SL916202,SL916200,SL918557` 请求 `64` 次，覆盖 `5` 场、`59` 匹唯一马，`horse_profiles_fetched=59`，`completion.is_complete=true`。按 proof 标准，英国接入可用性已证明；生产 commit 仍不执行。
- [x] 5.6 (operations) 按用户新 proof 边界，本会话不执行英国生产 commit；备份、完整 dry-run 汇总、锁检查和用户显式确认保留为后续会话 commit 门禁。

## 6. 法国准入与正式导入准备

- [x] 6.1 (integration) 复核 France Galop 或其他法国权威来源的赛程、出马、赛果和马匹 profile 入口，保存请求证据和字段覆盖矩阵。
- [x] 6.2 (integration) 明确法语字段处理、原始 payload 保留和不进入新闻正文链路的边界。
- [x] 6.3 (application) 按 TDD 新增法国 parser/importer fixture 和 dry-run 测试，覆盖真实 race/result/horse detail row 入口；独立 horse profile 页当前跳登录，作为后续补字段风险。
- [x] 6.4 (operations) 按用户新 proof 边界执行法国真实小批 dry-run；完整最近 2 个月拆批 dry-run 和生产 commit 门禁留给后续会话。
  - 2026-06-26 France Galop 官方当日 smoke 请求 `3` 次，证明官方 today/meeting/race detail 行内马匹字段可解析；历史入口受登录门禁影响，已改用 Geny 历史公开源。
  - 2026-06-26 Geny 60 天窗口小批 dry-run 请求 `11` 次，覆盖 `5` 场、`57` 条 entries、`52` 条 results、`54` 匹唯一马，未写正式表；曾遇 429，已补安全停止并建议后续至少 `10` 秒/请求。按用户新 proof 边界，法国接入可用性已证明；完整大量爬取后续另开会话，生产 commit 仍不执行。

## 7. 美国准入与正式导入准备

- [x] 7.1 (integration) 复核 Equibase entries、results、chart/PDF 和 horse profile 入口，保存请求证据和字段覆盖矩阵。
- [x] 7.2 (integration) 明确美国正式导入主来源采用 HTML chart、PDF chart 或 profile 页面，并记录访问限制风险；Equibase 当前返回防护页，Horse Racing Nation 可作为受限第一版候选但需确认最近 2 个月列表入口。
- [x] 7.3 (application) 按 TDD 新增美国 Horse Racing Nation parser/importer fixture 和 dry-run 测试，覆盖真实 entries/results track-day、runner/result table 和 horse profile 主入口。
- [x] 7.4 (operations) 按用户新 proof 边界执行美国真实小批 dry-run；完整最近 2 个月日期/赛场覆盖、拆批 dry-run 和生产 commit 门禁留给后续会话。
  - 2026-06-27 已新增 HRN `--recent-days` / `--start-date` 日期窗口；日期范围模式优先请求 `/entries-results/YYYY-MM-DD` 日期索引，并完成 60 天窗口 `limit-races=5 / limit-horses=10` 小批 dry-run。日期/track 完整覆盖策略留给后续完整大量爬取会话。
  - 按用户新 proof 边界，美国 HRN 日期索引、track-day、runner/result table 和 horse profile 接入可用性已通过 60 天窗口小批 dry-run 证明；完整大量爬取和更完整日期/track 覆盖后续另开会话，生产 commit 仍不执行。

## 8. 收尾验证与归档

- [x] 8.1 (operations) 按用户新边界确认香港暂停，英国、法国、美国均完成真实接入 proof，且本会话没有持续调度残留。
- [x] 8.2 (operations) 汇总四地区 proof 表计数或 dry-run 统计、失败摘要、限速配置和停止时间；明确完整大量爬取后续另开会话。
- [x] 8.3 (application) 运行最终测试和 OpenSpec 校验。
- [x] 8.4 (operations) 归档 OpenSpec change，并同步正式规格和项目状态文档。
