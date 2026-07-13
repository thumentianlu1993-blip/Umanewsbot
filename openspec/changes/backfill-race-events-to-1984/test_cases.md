# backfill-race-events-to-1984 测试用例

本文档只依据已通过工程审核的 `proposal.md`、`design.md`、delta specs 和 `tasks.md` 编写，不依据未来实现倒推测试点。当前阶段只定义完整用例，不实现业务代码、不触网、不写生产。

测试类型：

- `A`：自动化单元/集成测试。
- `S`：management command smoke。
- `F`：离线来源 fixture/parser 测试。
- `M`：前台/后台人工或浏览器验收。
- `O`：生产 dry-run、部署、备份、抓取和写后验收。
- `D`：文档、OpenSpec 和非目标边界。

## 0. 推荐测试落点

- `RaceSeriesModelTests`：系列、历史名称、关系、唯一约束和循环。
- `HistoricalRaceEventTargetModelTests`：expectation/resolution 状态机和年度唯一性。
- `HistoricalRaceInventoryServiceTests`：逐年目录、timeline、来源权威、总账和完成率。
- `HistoricalRaceInventoryCommandTests`：artifact、manifest、审批、dry-run/commit 和日志。
- `HistoricalRaceCatalogAdapterTests`：五地区跨年代离线解析。
- `HistoricalRaceBatchOrchestrationTests`：总账切批、第一批选择、年代护栏、coverage 和 apply-check。
- `HistoricalRaceImporterTests`：年度基础、派生 runners、results、冠军补位、人工锁、原子性和写后核验。
- `HistoricalRacePublicPageTests`：动态冠军、术语回退、年份/名称搜索、发布门槛和 sitemap。
- `HistoricalRaceInventoryAdminTests`：staff 权限、筛选、分页和只读边界。
- `HistoricalRacePerformanceTests`：50,000 目标、查询次数、内存、磁盘和 payload 边界。

## 1. 标准 fixture

系列 fixture：

- `series_long_lived`：日本长寿系列，1984 前创办，历经冠名、马场、距离和等级变化，当前仍举办。
- `series_promoted`：1995 创办、2005 升 G3、2018 升 G2。
- `series_demoted`：1984 时为 G2，2010 降级但继续举办。
- `series_discontinued`：1984–1998 举办，之后停办。
- `series_split_parent/child`：存在权威拆分沿革。
- `series_same_name_other_region`：名称相同但地区/沿革不同。

年度目标 fixture：

- `target_held`、`target_cancelled`、`target_not_held`、`target_not_due`。
- `target_source_unavailable`、`target_identity_review`、`target_permanent_gap`、`target_imported`。
- `target_dead_heat`：两个官方第一名。

来源 fixture：

- 当年官方结果、官方年鉴、高可信专业库、参考来源各一份。
- 1980 年代、中间年代、近年的五地区目录/结果离线文件。
- 403、超时、HTML 骨架、损坏 PDF、空表、名称歧义和同级官方冲突。

## 2. Requirement 覆盖关系

| 能力 | 主要测试 |
| --- | --- |
| 五地区完整 graded/pattern 范围 | TC-SCOPE-001 至 008 |
| 稳定系列、名称与关系 | TC-SERIES-001 至 013 |
| 年度总账与状态机 | TC-TARGET-001 至 016 |
| 来源权威和永久缺档 | TC-SOURCE-001 至 012 |
| Artifact、审批与日志 | TC-ART-001 至 015 |
| 五地区历史 adapter | TC-ADAPTER-001 至 020 |
| 总账切批和第一验收 | TC-BATCH-001 至 014 |
| 详情导入和原子性 | TC-IMPORT-001 至 018 |
| 前台、后台和 sitemap | TC-PUBLIC-001 至 018 |
| 性能、部署和最终审计 | TC-OPS-001 至 018 |

## 3. 历史范围与系列目录

| ID | 前置条件 | 步骤 | 期望结果 | 类型 |
| --- | --- | --- | --- | --- |
| TC-SCOPE-001 | 五地区 2026 目录 fixture | 生成初始系列候选 | 包含 JRA/NAR、香港、英国/法国 Pattern、美国 Graded；不含普通赛 | A |
| TC-SCOPE-002 | 1988 目录含已停办系列 | 汇总 1984–当前目录 | 历史独有系列进入候选，即使 2026 不存在 | A |
| TC-SCOPE-003 | 普通让赛从未分级 | 生成总账 | 不建立系列或年度目标 | A |
| TC-SCOPE-004 | `series_promoted` | 应用 timeline | 1995–2004 前分级届次也进入总账，等级不是 G3 | A |
| TC-SCOPE-005 | `series_demoted` | 应用 timeline | 2011 后降级届次继续收录，保存真实等级 | A |
| TC-SCOPE-006 | 1984 前创办系列 | 生成目标 | 起点为 1984，不生成更早目标 | A |
| TC-SCOPE-007 | 1995 创办系列 | 生成目标 | 起点为 1995；1984–1994 无虚假目标 | A |
| TC-SCOPE-008 | 当前年度新增分级赛事 | 重建滚动总账 | 新系列进入当前年度；旧年度不被机械补造 | A |

## 4. 稳定系列模型、迁移和关系

| ID | 前置条件 | 步骤 | 期望结果 | 类型 |
| --- | --- | --- | --- | --- |
| TC-SERIES-001 | 空库 | 创建稳定 key 相同的两个系列 | 唯一约束拒绝第二条 | A |
| TC-SERIES-002 | 同名不同地区赛事 | 建立两个系列 | 允许独立系列；名称相同不自动合并 | A |
| TC-SERIES-003 | 系列有三个历史名称 | 保存有效年份 | 名称有效期和 source evidence 可读取 | A |
| TC-SERIES-004 | 同一名称有效期冲突 | 保存重叠矛盾记录 | 服务拒绝或进入冲突，不静默覆盖 | A |
| TC-SERIES-005 | `series_split_parent/child` | 保存 approved 拆分关系 | 关系、批准人和证据正确保存 | A |
| TC-SERIES-006 | 系列指向自身 | 保存 predecessor | 拒绝 self relation | A |
| TC-SERIES-007 | A→B→C 已存在 | 尝试 C→A | 拒绝关系环并输出冲突路径 | A |
| TC-SERIES-008 | 相同关系已存在 | 重复保存 | 唯一约束或服务幂等，不产生重复 | A |
| TC-SERIES-009 | 两个 RaceEvent 同系列同年 | 保存第二条 | `(race_series, year)` 条件唯一约束拒绝 | A |
| TC-SERIES-010 | 旧 RaceEvent 没有 FK | 应用迁移并访问页面 | nullable 兼容，旧页面/查询不报错 | A |
| TC-SERIES-011 | 旧 event slug 已公开 | 绑定系列并修改名称 | 原 slug/URL 不变 | A |
| TC-SERIES-012 | 新历史赛事建议 slug 冲突 | dry-run 基础创建 | 阻断并进入 identity review，数据库无写入 | A/S |
| TC-SERIES-013 | 现有 source_refs 含合法/非法 official rank | 执行数据迁移 | 合法整数回填；非法/空值按设计回退；迁移可在 SQLite/PostgreSQL 执行 | A |

## 5. 年度总账与状态机

| ID | 前置条件 | 步骤 | 期望结果 | 类型 |
| --- | --- | --- | --- | --- |
| TC-TARGET-001 | 同系列/年份已有 target | 重复生成 | 幂等更新，不创建第二条 | A |
| TC-TARGET-002 | `target_held` | 保存 held + pending | 成功；模块状态初始明确 | A |
| TC-TARGET-003 | `target_cancelled` 有排期/取消证据 | apply 基础赛事 | 创建 `RaceEvent(status=cancelled)` 并关联 target | A |
| TC-TARGET-004 | `target_not_held` | 应用总账 | 不创建 RaceEvent；原因和证据保存 | A |
| TC-TARGET-005 | not-held target 关联 RaceEvent | 校验/保存 | 拒绝非法组合 | A |
| TC-TARGET-006 | not-due target | 尝试标记 imported | 拒绝非法转换 | A |
| TC-TARGET-007 | permanent gap 无批准证据 | 保存 resolution | 拒绝 | A |
| TC-TARGET-008 | permanent gap 有双来源/批准元数据 | 保存 resolution | 成功，证据身份完整 | A |
| TC-TARGET-009 | future race | 计算 expectation | `not_due`，不进入缺失分母 | A |
| TC-TARGET-010 | 已超过地区宽限期 | 重算 expectation | 从 not-due 转 held/due 处理，进入详情应到 | A |
| TC-TARGET-011 | target identity 冲突解决 | 重新审核 | 可从 identity review 转 pending/ready，保留旧状态日志 | A |
| TC-TARGET-012 | imported target 找到更权威来源 | 生成新候选 | 不直接改 imported；生成 diff 和新批准流程 | A |
| TC-TARGET-013 | 全部目标 imported/not-held/not-due/permanent | 计算 summary | accounted rate 100%；data complete 单独计算 | A |
| TC-TARGET-014 | 存在 source unavailable | 计算 summary | accounted rate <100%，不得宣称闭环 | A |
| TC-TARGET-015 | permanent gap 存在 | 计算 summary | accounted 可 100%，data complete <100%，缺档单列 | A |
| TC-TARGET-016 | 同一总账按地区/年代/系列聚合 | 生成 summary | 子计数之和与全局分母一致，无重复/漏计 | A |

## 6. 来源权威、冲突和永久不可得

| ID | 前置条件 | 步骤 | 期望结果 | 类型 |
| --- | --- | --- | --- | --- |
| TC-SOURCE-001 | 官方结果和参考来源冲突 | 合并冠军字段 | 保留官方值，记录低级冲突 | A |
| TC-SOURCE-002 | 低级来源补官方空字段 | 合并 | 允许补空，字段 provenance 指向补充来源 | A |
| TC-SOURCE-003 | 两个同级官方来源冲突 | 合并 | blocker，受影响 scope 不可 apply | A |
| TC-SOURCE-004 | 后抓低权威来源 | 重跑 | 不因“最新”覆盖高权威值 | A |
| TC-SOURCE-005 | 三个复制同一错误的参考来源 | 合并 | 不按多数票覆盖官方事实 | A |
| TC-SOURCE-006 | 单来源 403 | 标记缺口 | 只能 source unavailable，不可 permanent | A |
| TC-SOURCE-007 | 单来源连续失败三次 | 标记缺口 | 仍不可自动 permanent | A |
| TC-SOURCE-008 | 官方档案和独立可信源均核查无资料 | 审批 permanent | 保存 URL、范围、时间、响应/目录、批准人和 SHA | A/S |
| TC-SOURCE-009 | 双来源其实引用同一数据库 | 审核 evidence | 不满足独立来源要求 | A |
| TC-SOURCE-010 | 页面改版但 archive cache 可得 | 重新核查 | 不标永久缺档，使用 archive 候选继续 | A/F |
| TC-SOURCE-011 | 身份错配导致“无结果” | mapping 修正后重跑 | 缺口重新开启并可转 ready | A |
| TC-SOURCE-012 | 人工锁字段与官方新候选冲突 | 生成/apply diff | 保留人工值，artifact 记录 skipped_manual | A |

## 7. Artifact、命令和审计

| ID | 前置条件 | 步骤 | 期望结果 | 类型 |
| --- | --- | --- | --- | --- |
| TC-ART-001 | 离线目录 fixture | 执行 inventory plan | 生成 series candidates/conflicts、annual targets/review、gap ledger、summary、manifest | S |
| TC-ART-002 | 同 TC-ART-001 | 检查 manifest | 每个 artifact 有路径、大小、SHA-256、schema/version | A/D |
| TC-ART-003 | 默认配置 | 不带 commit/allow-network 执行 | 只读，数据库和网络请求均为 0 | A/S |
| TC-ART-004 | 功能开关 false | 执行离线 plan/dry-run | 允许只读阶段 | A/S |
| TC-ART-005 | 功能开关 false | 尝试 commit/publication | 拒绝且零写入 | A/S |
| TC-ART-006 | 网络开关 false、plan true | prepare | 拒绝且请求计数为 0 | A/S |
| TC-ART-007 | 开关均 true 但应到未审批 | prepare | fail closed，零请求 | A/S |
| TC-ART-008 | artifact 审批后修改一个字节 | commit | 哈希不符，任何模型零写入 | A/S |
| TC-ART-009 | commit 阶段模拟网络客户端 | 执行 commit | 网络调用必须为 0，只读已批准 cache | A |
| TC-ART-010 | 同一批准 artifact 已 commit | 重复 commit | 幂等，不重复系列/target/event/log | A/S |
| TC-ART-011 | manifest 缺 review 或 summary | commit | 拒绝不完整 artifact | A/S |
| TC-ART-012 | 后台 staff 查看总账 | 筛选/打开冲突 | 可查看；无直接绕过 artifact apply 按钮/端点 | A/M |
| TC-ART-013 | 非 staff/匿名用户 | 访问总账后台 URL | 302 登录或 403，不泄露 artifact 路径 | A |
| TC-ART-014 | commit、mapping、permanent approval、publication | 检查日志 | OperationLog/TaskExecutionLog 绑定 SHA、范围、操作者、结果 | A |
| TC-ART-015 | 日志输入含环境变量/整页 HTML | 检查日志 | 不保存秘密、整页原件或完整敏感响应 | A |
| TC-ART-016 | ready目标发现补充详情直链 | 生成detail-source artifact | 复制并绑定当前target/inventory SHA、URL和source-cache字节身份 | A/S |
| TC-ART-017 | detail-source审批后修改候选或缓存一个字节 | check/commit | manifest校验失败，target/event零写入 | A/S |
| TC-ART-018 | detail-source审批后target来源变化 | commit | target SHA漂移整批阻断，无成功日志 | A/S |
| TC-ART-019 | 同一详情URL出现不同缓存正文 | package | source URL/size/SHA任一不同均拒绝，不以同URL替换capture | A/F |

## 8. 五地区历史目录与 timeline adapter

| ID | 前置条件 | 步骤 | 期望结果 | 类型 |
| --- | --- | --- | --- | --- |
| TC-ADAPTER-001 | JRA/NAR 1984 fixture | 解析年度目录 | 输出地区、年份、原名、等级、日期/马场、source URL 和 parser version | F |
| TC-ADAPTER-002 | JRA/NAR 中间/近年 fixture | 分别解析 | 标准 schema 一致，旧格式分支可审计 | F |
| TC-ADAPTER-003 | 日本系列升格前 timeline | 解析沿革/结果索引 | 前分级届次和真实等级进入 timeline | F |
| TC-ADAPTER-004 | HKJC 1980s 赛季 fixture | 解析 | 正确处理跨年赛季、繁中/英文名称和分级语义 | F |
| TC-ADAPTER-005 | HKJC 改名/停办 fixture | timeline | 名称有效期、not-held/最后举办年正确 | F |
| TC-ADAPTER-006 | HKJC 页面空壳或 locale 错误 | 解析 | 不把空壳当成功，输出 blocker | F |
| TC-ADAPTER-007 | BHA Flat 1980s fixture | 解析 | Pattern 等级、日期、马场正确 | F |
| TC-ADAPTER-008 | BHA Jump fixture | 解析 | Jump surface/等级和 Flat 不混淆 | F |
| TC-ADAPTER-009 | 英国赞助冠名变化 | mapping | 同一沿革生成候选，不仅凭名自动批准 | F |
| TC-ADAPTER-010 | France Galop 1980s fixture | 解析 | 法文名称、Groupe 等级、马场和年份正确 | F |
| TC-ADAPTER-011 | 法国 PDF OCR 断词 | 解析 | 通过明确修正规则或进入 review，不静默造名 | F |
| TC-ADAPTER-012 | 法国历史独有系列 | 汇总 | 进入系列候选和 timeline | F |
| TC-ADAPTER-013 | TOBA/委员会 1984 fixture | 解析 | 美国 graded 级别和年度赛事清单正确 | F |
| TC-ADAPTER-014 | 美国同名赛事不同赛场 | mapping | 不自动合并，进入 identity review | F |
| TC-ADAPTER-015 | 美国 Bayakoa/Frankel 重复 key fixture | mapping | 冲突明确列出，需批准后绑定 | F |
| TC-ADAPTER-016 | 任一来源损坏 PDF | 解析 | 非零失败或 blocker，不能输出空成功 | F |
| TC-ADAPTER-017 | 任一来源解析出总账外年份 | 标准化 | unexpected candidate blocker | F |
| TC-ADAPTER-018 | 任一 adapter 需网络 | 请求两次 | 共用 run 请求预算和最小间隔 | A/F |
| TC-ADAPTER-019 | cache 写入将超字节/磁盘门槛 | 请求前检查 | 停止且不写部分响应，state 记录 blocker | A |
| TC-ADAPTER-020 | 已批准 cache 仍在回滚期 | 执行清理 | 对应文件保留；非绑定临时 cache 可按策略清理 | A/O |

## 9. 批次选择、coverage 和地区同步

| ID | 前置条件 | 步骤 | 期望结果 | 类型 |
| --- | --- | --- | --- | --- |
| TC-BATCH-001 | 批准总账含五地区样本 | 生成第一批 | 每地区 3 系列、约 9 held/cancelled 目标，总量 40–50 | A |
| TC-BATCH-002 | 第一批仅近年 | 校验 | 失败，列出缺少年代的地区 | A |
| TC-BATCH-003 | 停办系列无近年届次 | 选择样本 | 在真实范围取样，由同地区其他系列补近年；不选虚假 not-held | A |
| TC-BATCH-004 | 总账外 target 注入 plan | 校验 | fail closed、零网络 | A |
| TC-BATCH-005 | 总账 ready 与 gap 混合 | 生成 plan | 只选 ready；gap 仍留总账 | A |
| TC-BATCH-006 | 每地区请求 51 个目标且未批准上限变化 | 校验 | 拒绝超过默认 50 | A |
| TC-BATCH-007 | plan 显式调整上限并重新审批 | 校验 | 可接受；护栏仍按标准目标数 | A |
| TC-BATCH-008 | 某地区领先最慢地区 101 目标 | 生成下一批 | 拒绝并提示落后地区 | A |
| TC-BATCH-009 | 某地区领先 100 目标 | 生成下一批 | 不因护栏单独拒绝 | A |
| TC-BATCH-010 | 候选含完整 40、gap 5 | coverage | 40 个 complete scope 可审；5 个 gap 不进入候选且不消失 | A |
| TC-BATCH-011 | 模块键存在但 items 空 | coverage | `empty_<module>` blocker，不算完整 | A |
| TC-BATCH-012 | candidate 超出应到 | coverage | unexpected candidate blocker | A |
| TC-BATCH-013 | source URL/provenance 缺失 | coverage | blocker，不生成 apply scope | A |
| TC-BATCH-014 | 2016–2025 完成后 | 生成下一年代 | 可进入 2006–2015；不得跳过未 accounted 的当前年代缺口报告 | A/O |
| TC-BATCH-015 | 2016–2025含五地区pending目标 | 生成标准批次 | 每地区最多50个，按新到旧稳定选择，只包含pending未materialize due目标 | A/O |
| TC-BATCH-016 | 空批次、重复target、年代外或inventory SHA漂移 | 生成artifact | fail closed，不生成可批准清单 | A/S |
| TC-BATCH-017 | 上批gap仍pending且提供上批selection snapshot | 生成下一标准批次 | limit前排除旧target并补入新target；排除snapshot复制进manifest，gap仍留remaining分母 | A/S |
| TC-BATCH-018 | 排除snapshot跨inventory、内部SHA漂移、target重复或与新selection相交 | 生成artifact | fail closed，不生成可批准清单且不改变target状态 | A/S |

## 10. 详情导入、冠军和原子写入

| ID | 前置条件 | 步骤 | 期望结果 | 类型 |
| --- | --- | --- | --- | --- |
| TC-IMPORT-001 | 独立 racecard + result | dry-run/apply | runners/results 分别写入，来源正确 | A/S |
| TC-IMPORT-002 | 只有包含全部参赛者的完整赛果 | apply | 派生 runners，标记 derived；未知赔率/闸位为空 | A |
| TC-IMPORT-003 | 赛果只列前三 | 尝试派生 runners | 不视为完整出马表，coverage blocker | A |
| TC-IMPORT-004 | 包含退赛/未完赛马 | 导入 | runners/results 状态保留，不误删 | A |
| TC-IMPORT-005 | 单一官方冠军 | 导入 | official finish position=1，可动态汇总 | A |
| TC-IMPORT-006 | 两匹并列第一 | 导入 | 两条稳定存储顺序不同、官方名次均为 1；页面可显示两冠军 | A |
| TC-IMPORT-007 | 无完整赛果但有可信冠军 | apply 补位 | HistoryWinner 写入并保留来源 | A |
| TC-IMPORT-008 | 后续补齐正式赛果 | 查询冠军 | 正式赛果优先，补位不重复显示 | A |
| TC-IMPORT-009 | 同年两个补位冠军 | 保存 | 新唯一约束允许不同马名，不允许完全重复 | A |
| TC-IMPORT-010 | candidate 比现有数据更少 | apply-check | candidate_less_complete blocker | A |
| TC-IMPORT-011 | 高权威候选补空 | approved apply | 更新未锁字段，保存 before/source/reason | A |
| TC-IMPORT-012 | 人工锁字段冲突 | apply | 跳过锁字段，其余批准字段可写 | A |
| TC-IMPORT-013 | scope 后半模块抛异常 | apply | 年度赛事、候选、runners/results、target 状态全部回滚 | A |
| TC-IMPORT-014 | scope A 成功、scope B gap | apply A | A imported；B 原 gap 状态不变 | A |
| TC-IMPORT-015 | 写后 runner 数与 artifact 不符 | verify | 不标 imported，生成 blocker/回滚指引 | A |
| TC-IMPORT-016 | 同一 artifact 重跑 | apply | 幂等，无重复行和重复日志副作用 | A |
| TC-IMPORT-017 | raw payload 含整页 HTML/PDF bytes | 标准化/apply | 拒绝或剥离整页内容，只留结构化行和 cache identity | A |
| TC-IMPORT-018 | importer 收到错误 expected SHA | apply | 写入前失败，所有正式表零变化 | A/S |
| TC-IMPORT-019 | IrishRacing 英法备用详情页 | parse/package | 仅产生 actual runners/results，马号与闸位分离，赛事身份不符时拒绝 | A |
| TC-IMPORT-020 | 法国 target 使用 uk_irishracing provider | artifact build | 地区不匹配并 fail closed | A/S |
| TC-IMPORT-021 | IrishRacing 赛果有并列名次 | parse/apply | 存储顺序唯一，official_finish_position 保留官方并列位次 | A |
| TC-IMPORT-022 | Equibase standard PDF含空格表头和`1a`联合投注编号 | parse/package | 完整保留所有实际出走，runners按马号、results按官方顺序 | A/F |
| TC-IMPORT-023 | Equibase PDF页眉日期、赛场或场次与target不符 | parse/package | fail closed，不生成可写入候选 | A/F |
| TC-IMPORT-024 | JRA英文年度表与日文官方结果表 | source discovery | 以日期/赛场唯一对齐官方单场结果，歧义不猜测 | A/F |
| TC-IMPORT-025 | 美国同名赛事或Belmont工程期移师 | TOBA discovery | 先按赛事名和场地区分；年度表名称唯一时允许记录实际移师场地 | A/F |
| TC-IMPORT-026 | JRA英文表不含障碍赛或赞助名不同 | source discovery | 仅通过显式日文官方别名唯一匹配结果页，未知名称继续进入issue | A/F |
| TC-IMPORT-027 | TOBA同场同时有Juvenile、Fillies、Turf、Sprint变体 | source discovery | 核心限定词必须按完整单词一致，不能因短名称包含关系串场 | A/F |
| TC-IMPORT-028 | 两个美国target最终匹配同一Equibase URL | source discovery | 两个候选均移除并输出`duplicate_source_url`，不得进入缓存 | A/F |
| TC-IMPORT-029 | TOBA年度表将赛事标记为`not run` | source discovery | 输出`source_reports_not_run`审核证据，不自动生成结果URL或改变总账状态 | A/F |
| TC-IMPORT-026 | Equibase Yearbook含实际出赛与退赛 | 离线解析 | runners按马号含退赛，results仅含实际出赛并按官方名次 | A/F |
| TC-IMPORT-027 | event距离为裸数字、批准来源为`2400m` | 权威字段dry-run | 输出`2400 -> 2400m`，保留来源/snapshot/parser，不写库 | A/S |
| TC-IMPORT-028 | 英国批准来源为`3m 210y` | 权威字段apply | 原样保存mile/yard文本，不解释为metre，写before/after日志 | A/S |
| TC-IMPORT-029 | 字段候选包含未知字段或缺source URL/snapshot | dry-run/apply | fail closed，所有target和event零变化 | A/S |
| TC-IMPORT-030 | 权威字段批次审批后一个target SHA漂移 | apply | 写入前整批失败，前序scope和OperationLog均不落库 | A/S |
| TC-IMPORT-031 | 字段批次后半scope异常 | apply | 外层事务回滚前序event字段、provenance和日志 | A/S |
| TC-IMPORT-032 | 字段批次成功后复用旧详情候选 | detail dry-run | 因target SHA变化阻断，必须重新导出、打包和dry-run | A/S |

## 11. 公开页面、后台、搜索和 sitemap

| ID | 前置条件 | 步骤 | 期望结果 | 类型 |
| --- | --- | --- | --- | --- |
| TC-PUBLIC-001 | finished held 赛事身份/结果/runners 完整 | 批准 publication | published，日志记录门槛证据 | A |
| TC-PUBLIC-002 | 缺赔率但来源不提供 | 批准 publication | 不因赔率缺失阻止 | A |
| TC-PUBLIC-003 | 缺完整 results | publication | 保持 draft | A |
| TC-PUBLIC-004 | permanent gap 且资料不完整 | publication | 保持 draft，不进 sitemap | A |
| TC-PUBLIC-005 | cancelled 有排期/取消证据 | publication | 可公开取消说明，不要求 runners/results | A/M |
| TC-PUBLIC-006 | 普通详情重抓 draft | 应用候选 | 不自动改变可见性 | A |
| TC-PUBLIC-007 | 同系列 43 届 | 打开任一年度详情 | 历届冠军按年份汇总，不复制、不 N+1 | A/M |
| TC-PUBLIC-008 | 同年并列冠军 | 打开详情 | 两位冠军均显示 | A/M |
| TC-PUBLIC-009 | 马名/骑师命中术语 | 打开详情 | 显示正式中文译名 | A |
| TC-PUBLIC-010 | 未命中术语 | 打开详情 | 保留原文、生成缺口，不自动造词/建 HorseProfile | A |
| TC-PUBLIC-011 | 日历 year=1984 | 请求页面 | 只展示 1984 年公开赛事，不需连续懒加载 | A/M |
| TC-PUBLIC-012 | q 命中年度原名/中文名/别名 | 搜索 | 返回对应年度详情链接 | A |
| TC-PUBLIC-013 | q 命中历史系列名称 | 搜索 | 返回有效年份年度赛事，不出现独立系列页 | A |
| TC-PUBLIC-014 | year/q/region/tab 组合 | 翻页或切方向 | 所有筛选参数保留 | A/M |
| TC-PUBLIC-015 | 无 year/q | 打开日历 | 默认当前日期窗口，旧行为兼容 | A |
| TC-PUBLIC-016 | 20,000 published 历史 URL | 生成 sitemap | sitemap index + 分片，每片不超配置上限 | A |
| TC-PUBLIC-017 | draft/conflict/not-held | 生成 sitemap | 均不出现 | A |
| TC-PUBLIC-018 | published 状态变化 | 再取 sitemap | cache 正确失效，新增/移除 URL 反映状态 | A |

## 12. 性能、部署与最终运维验收

| ID | 前置条件 | 步骤 | 期望结果 | 类型 |
| --- | --- | --- | --- | --- |
| TC-OPS-001 | 50,000 目标 fixture | 生成总账 artifact | ≤120 秒、峰值 ≤512 MiB、哈希确定 | A/O |
| TC-OPS-002 | 50,000 target 测试库 | 请求后台首屏 | ≤12 queries、有分页、基准环境 ≤1 秒 | A |
| TC-OPS-003 | 43 届系列 | 请求详情冠军 | 有界查询，不逐年 N+1 | A |
| TC-OPS-004 | 大 sitemap | 生成单分片 | 不加载全部 URL 到单一响应，内存有界 | A |
| TC-OPS-005 | 第一批 dry-run | 输出容量报告 | 包含新增 events/runners/results/index 估计和 DB 增长 | O |
| TC-OPS-006 | 生产开关默认配置 | 部署后检查 settings/container env | 功能和网络均 false | O |
| TC-OPS-007 | 部署前 | 检查 HEAD、容器、锁、任务、healthz | 全绿后才备份/迁移 | O |
| TC-OPS-008 | 数据库备份 | gzip/SHA/可读性校验 | 真实文件通过，路径写入 evidence | O |
| TC-OPS-009 | 新迁移上线 | migrate/check | 空模型和 nullable 字段兼容，现有公开页 200 | O |
| TC-OPS-010 | 模拟回滚 | 回滚代码保留新表/nullable FK | 旧页面和抓取主链可运行 | O |
| TC-OPS-011 | 第一批 45 场计划 | 网络关闭预检 | 五地区/年代/系列/预算全绿，外部请求 0 | O |
| TC-OPS-012 | 分地区开启第一批 | 检查 request ledger | 共享预算、间隔、cache 和失败恢复正确 | O |
| TC-OPS-013 | 第一批完整 scope | backup→dry-run→apply-check→apply | 仅批准 SHA 写入，写后计数匹配 | O |
| TC-OPS-014 | 第一批上线后 | 浏览器桌面/移动验收 | 日历年份/搜索、年度详情、冠军、取消状态无布局溢出 | M/O |
| TC-OPS-015 | 批次运行中断 | resume | 不重复已成功请求/写入，保留失败摘要 | O |
| TC-OPS-016 | 四个年代带结束 | 全量重复/漏抓审计 | 总账分母与正式年度对象、not-held/gap 对账 | O |
| TC-OPS-017 | 暂时缺口清理完成 | 生成最终报告 | accounted=100%，data complete 与 permanent gap 分地区/年代/系列披露 | O |
| TC-OPS-018 | 最终验收 | 恢复抽演、性能、日志、healthz、公开 URL | 全部通过后才允许 OpenSpec 归档和目标 complete | O/D |

## 13. 非目标与防回归

| ID | 前置条件 | 步骤 | 期望结果 | 类型 |
| --- | --- | --- | --- | --- |
| TC-NONGOAL-001 | 历史普通赛来源 | 执行 inventory | 不进入目标范围 | A/D |
| TC-NONGOAL-002 | 历史参赛马无 profile | apply | 不创建 HorseProfile | A |
| TC-NONGOAL-003 | 未识别人马名 | apply/publication | 不自动写 TermEntry | A |
| TC-NONGOAL-004 | 历史数据已导入 | 检查路由 | 不新增公开 series page | A/D |
| TC-NONGOAL-005 | inventory/prepare/dry-run | 对比 ExternalRace* 计数 | 全部不变 | A |
| TC-NONGOAL-006 | 新闻生产窗口/Celery | 执行历史命令 | 不触发新闻抓取、翻译、发布或 QQ 推送 | A |
| TC-NONGOAL-007 | 现有 2026 URL | 完成系列绑定和迁移 | URL、可见性、赛果和新闻关联保持兼容 | A/M |
| TC-NONGOAL-008 | 现有单场修复命令 | 执行旧测试 | 仍可使用，不被历史总账命令破坏 | A |

## 14. 标准验证命令

实现后至少执行：

```bash
DB_ENGINE=sqlite .venv/bin/python server/manage.py check
DB_ENGINE=sqlite .venv/bin/python server/manage.py makemigrations --check --dry-run
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true .venv/bin/python server/manage.py test stable --noinput
openspec validate backfill-race-events-to-1984 --strict
openspec validate --all
git diff --check
docker compose -f docker-compose.prod.yml config
docker compose -f docker-compose.prod.lowcost.yml config
```

代码 review 期间每轮修复后必须重新执行受影响目标测试；最终必须出现一次无可修复问题的 review，才允许执行生产部署、真实网络抓取或正式写入。
