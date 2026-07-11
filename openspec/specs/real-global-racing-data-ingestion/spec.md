# real-global-racing-data-ingestion Specification

## Purpose
规范香港、英国、法国和美国真实赛马数据库的低频抓取、dry-run、生产写入门禁、停止边界和对新闻分发链路的隔离要求。
## Requirements
### Requirement: 真实数据库接入必须按地区顺序和显式门禁推进
系统 SHALL 按 `香港 -> 英国 -> 法国 -> 美国` 的顺序接入真实赛马数据库。若前一地区已达到用户确认的暂停边界且未执行生产 commit，后一地区 MAY 进入真实抓取实现、dry-run 和隔离验证；任一地区的生产 commit 仍 MUST 满足本地区备份、dry-run、锁检查和用户确认门禁。

#### Scenario: 香港暂停后可以进入英国真实抓取
- **WHEN** 香港生产 dry-run 已达到用户确认的暂停边界但尚未执行生产 commit
- **THEN** 系统 MAY 开始英国真实页面 parser、importer、dry-run 和隔离库验证
- **AND** 系统不得把英国、法国或美国真实数据写入生产 `External*` 表，除非对应地区已单独通过生产 commit 门禁

#### Scenario: 每个地区完成后停止
- **WHEN** 任一地区完成最近 2 个月赛事、赛果、涉及马匹详情抓取和写入验证
- **THEN** 本轮任务 SHALL 停止该地区的继续抓取
- **AND** 系统不得自动加入 Celery Beat 周期调度或后台持续导入队列

#### Scenario: 用户将本会话收敛为 proof 后停止
- **WHEN** 用户明确要求英国、法国、美国本会话只抓几个真实批次证明接入方式和 importer 可用
- **THEN** 系统 SHALL 把本会话验收边界调整为低频真实 dry-run proof
- **AND** 报告 MUST 明确 proof 与完整两个月大量爬取不是同一件事
- **AND** 完整大量爬取 SHALL 留给后续会话单独执行，不得在本会话继续扩大抓取范围

### Requirement: HKJC 真实 HTML 导入必须覆盖最近 2 个月赛事
系统 SHALL 从 HKJC 官方公开页面低频抓取最近 2 个月赛日、每场比赛结果和所有涉及马匹详情，并映射到现有外部缓存表。

#### Scenario: 枚举 HKJC 最近 2 个月赛日
- **WHEN** 运维人员执行 HKJC 真实网络 dry-run 并指定 `--recent-days 60` 或等价日期范围
- **THEN** 系统从 HKJC `localresults` 页面解析赛日下拉列表
- **AND** 系统只选择目标日期范围内的赛日
- **AND** 系统记录解析到的赛日数量和来源 URL

#### Scenario: 解析 HKJC 单场结果
- **WHEN** 系统请求 HKJC 单场 `localresults?racedate=YYYY/MM/DD&Racecourse=<code>&RaceNo=<n>` 页面
- **THEN** 系统解析比赛日期、场地、场次、比赛名、班次、途程、跑道、Going、奖金或可用摘要字段
- **AND** 系统解析每匹马的名次、马号、英文名、牌号、骑师、练马师、负磅、档位、距离差、沿途位置、完成时间和赔率中可用字段
- **AND** 系统把每匹马详情链接中的 `horseid` 作为外部 horse id

#### Scenario: 解析 HKJC 马匹详情
- **WHEN** 系统请求 HKJC `/local/information/horse?horseid=<id>` 页面
- **THEN** 系统解析英文名、牌号、产地、年龄、毛色、性别、进口类型、练马师、马主、当前评分、父系、母系和战绩摘要中可用字段
- **AND** 系统生成英文马名 `ExternalHorseAlias`
- **AND** 系统保留原始页面字段到 `raw_payload`

#### Scenario: HKJC dry-run 不写正式表
- **WHEN** HKJC 真实网络导入以 dry-run 运行
- **THEN** 系统返回请求数量、赛日数量、比赛数量、结果数量、唯一马匹数量和预计写入数量
- **AND** `ExternalRace`、`ExternalRaceEntry`、`ExternalRaceResult`、`ExternalHorse` 和 `ExternalHorseAlias` 计数不得变化

#### Scenario: HKJC commit 写入正式外部缓存
- **WHEN** HKJC 真实网络 dry-run 已通过且运维人员执行 `--commit`
- **THEN** 系统以单来源互斥方式写入 HKJC `ExternalRace`、`ExternalRaceEntry`、`ExternalRaceResult`、`ExternalHorse` 和 `ExternalHorseAlias`
- **AND** 系统返回 `run_id`、请求数量、覆盖统计、成功数、失败数和停止点
- **AND** 同一范围重复执行 SHALL 幂等更新，不重复创建相同来源的比赛、出马、赛果、马匹或别名

### Requirement: 真实抓取必须限速、可中断且可审计
系统 MUST 对所有真实数据库抓取执行保守限速、批量上限、单来源锁和请求证据记录，避免触发来源站点风控或污染正式数据。

#### Scenario: 请求间隔生效
- **WHEN** 系统执行任一地区真实网络抓取
- **THEN** 相邻外部请求之间 MUST 至少等待配置的请求间隔
- **AND** 请求间隔 MUST 可由 Django settings 和环境变量配置

#### Scenario: 超过批量上限时拒绝或停止
- **WHEN** 目标范围内比赛数量、马匹数量或请求数量超过本次配置上限
- **THEN** 系统 MUST 在 commit 前拒绝本次导入，或在 dry-run 中标记需要拆分批次
- **AND** 系统不得静默截断后伪装为完整导入

#### Scenario: 单来源导入互斥
- **WHEN** 已存在同一来源的运行中导入锁
- **THEN** 系统 MUST 拒绝新的正式 commit
- **AND** dry-run 不得抢占或覆盖正在 commit 的锁

#### Scenario: 请求证据可审计
- **WHEN** 任一真实网络导入完成或失败
- **THEN** `ExternalDataImportRun.parameters` 或文档记录 MUST 包含目标范围、请求入口、请求数量、限速配置、失败摘要和停止原因

#### Scenario: dry-run 批次输出必须可离线汇总
- **WHEN** 运维人员准备从多个 plan/dry-run JSON 输出进入生产 commit 评估
- **THEN** 系统 MUST 提供离线审计命令汇总文件数量、plan 批次数、非 plan 批次数、coverage 总量、请求总量、plan 覆盖缺口和 incomplete 文件
- **AND** 该命令 MUST 在 JSON 输出中提供 `blocking_reasons`，列出阻止进入 commit 候选的机器可读原因
- **AND** 该命令 MUST 要求至少一个 plan-only 文件且 plan 中至少包含一个 `race_ids`、`partants_urls` 或 `race_urls` 项目，才能标记为 commit 候选
- **AND** 该命令 MUST 要求至少一个非 plan dry-run 批次文件，才能标记为 commit 候选
- **AND** 该命令 MUST 要求所有 plan 与 dry-run JSON 文件包含非空 `source`
- **AND** 该命令 MUST 要求同一次审计中的 plan 与 dry-run 批次来自同一个 `source`
- **AND** 该命令 MUST 要求所有 plan-only 文件本身为 dry-run 且 `completion.is_complete=true`
- **AND** 该命令 MUST 要求所有 plan-only 文件包含非空请求证据，且每个请求状态码均为成功响应
- **AND** 该命令 MUST 在 plan-only 文件声明 `coverage_scope_limited=true` 或包含 `limit_tracks`、`limit_races`、`limit_horses` 等覆盖限制时支持失败退出
- **AND** 该命令 MUST 在任一 dry-run JSON 显式报告 `would_write_formal_tables=true` 时支持失败退出
- **AND** 该命令 MUST 在任一非 plan dry-run 批次缺少请求证据、存在非成功请求响应、或 `coverage_stats.races`、`entries`、`results`、`horses` 任一为 `0` 时支持失败退出
- **AND** 该命令 MUST 在发现 `completion.is_complete=false`、不可解析 JSON 或非 dry-run 批次时支持失败退出
- **AND** 该命令 MUST 在批次声明的 `horse_profiles_fetched` 少于 `unique_horses_found` 且没有 `race_detail_rows` 或 `geny_partants_rows` 等等价行内马匹详情来源时支持失败退出
- **AND** 该命令 MUST 在 plan-only 输出中同一 `race_ids`、`partants_urls` 或 `race_urls` 项目重复出现时支持失败退出
- **AND** 该命令 MUST 在 plan-only 输出列出的 `race_ids`、`partants_urls` 或 `race_urls` 未被后续 dry-run 批次覆盖时支持失败退出
- **AND** 该命令 MUST 在后续 dry-run 批次覆盖了 plan-only 未列出的 `race_ids`、`partants_urls` 或 `race_urls` 时支持失败退出
- **AND** 该命令 MUST 在后续 dry-run 批次重复覆盖同一个 plan 项目时支持失败退出

#### Scenario: 少量真实 proof 输出必须可离线汇总
- **WHEN** 运维人员按用户收敛边界只验证英国、法国或美国少量真实 dry-run proof
- **THEN** 系统 MUST 提供 proof-only 离线审计模式，汇总 proof 文件数量、请求数量、成功响应数量、coverage、每来源 proof 摘要和阻断原因
- **AND** proof-only 审计 MUST 要求每个 proof JSON 为 `dry_run=true` 且未显式报告 `would_write_formal_tables=true`
- **AND** proof-only 审计 MUST 要求每个 proof JSON 包含非空 `source`、至少一个真实请求、至少一个比赛和至少一个马匹 coverage
- **AND** proof-only 审计 MUST 支持运维人员声明期望 `source` 清单，并在任一期望来源缺失时失败退出
- **AND** proof-only 审计 MUST 支持运维人员声明每个期望 `source` 必须出现的请求类型，并在任一请求类型缺失时失败退出
- **AND** proof-only 审计 MUST 要求每个请求状态码均为成功响应
- **AND** proof-only 审计 MAY 接受因 `limit_horses_reached`、`limit_races_reached` 或 `limit_tracks_reached` 导致的 `completion.is_complete=false`
- **AND** proof-only 审计输出 MUST 明确 `proof_ready` 与 `commit_candidate_ready` 是不同口径，proof 通过不得被解释为生产 commit 候选

#### Scenario: plan-only 必须显式授权真实网络
- **WHEN** 运维人员对香港、英国、法国 Geny 或美国执行 `--plan-only` 以生成最近 2 个月拆批计划
- **THEN** 命令 MUST 要求同时提供 `--allow-network`
- **AND** 系统不得在缺少显式网络授权时请求外部日期页、赛日页、结果页或赛场页

#### Scenario: plan 批次必须能渲染为精确执行命令
- **WHEN** 运维人员已获得香港、英国、法国 Geny 或美国的 plan-only JSON 并准备执行第 N 个批次
- **THEN** 系统 MUST 提供只读命令从 plan 文件中选择指定 `batch_index` 或 `batch_no`
- **AND** 系统 MUST 支持一次渲染 plan 文件中的全部批次，输出每个批次的 `batch_number`、目标数量和命令行
- **AND** 该命令 MUST 根据来源渲染精确批次导入命令：香港和美国使用 `race_ids`，英国使用 `race_urls`，法国 Geny 使用 `partants_urls`
- **AND** 渲染结果 MUST 默认包含 `--allow-network`，但不得实际发起外部请求或写入数据库
- **AND** 离线审计 MUST 识别并忽略此类只读命令清单 artifact，避免它污染 plan/dry-run 覆盖判断
- **AND** 当 plan 不是 `plan_only=true`、批次不存在、来源不支持或目标清单缺失时，系统 MUST 拒绝渲染

#### Scenario: incomplete payload 不得 commit
- **WHEN** 任一地区导入 payload 明确包含 `completion.is_complete=false`
- **THEN** 系统 MUST 拒绝 `--commit`
- **AND** 系统不得创建 `ExternalDataImportRun` 或写入 `ExternalRace`、`ExternalRaceEntry`、`ExternalRaceResult`、`ExternalHorse`、`ExternalHorseAlias`

#### Scenario: 缺少完成度证明不得 commit
- **WHEN** 任一地区导入 payload 缺少 `completion.is_complete=true` 的严格布尔完成证明
- **THEN** 系统 MUST 拒绝 `--commit`
- **AND** 系统不得把缺失 completion、`null`、字符串或其他非布尔值解释为完整导入

#### Scenario: 自相矛盾的完成度证明不得 commit
- **WHEN** 任一地区导入 payload 声明 `completion.is_complete=true`，但 `stop_reason` 不是 `complete`，或 `horse_profiles_fetched` 少于 `unique_horses_found` 且没有声明已认可的行内详情来源
- **THEN** 系统 MUST 拒绝 `--commit`
- **AND** 系统不得仅凭 `is_complete=true` 覆盖马匹详情缺口或受限停止原因

#### Scenario: 缺少马匹详情覆盖计数不得 commit
- **WHEN** 任一地区导入 payload 声明 `completion.is_complete=true`，但缺少 `unique_horses_found` 或 `horse_profiles_fetched`，或两者不可解析为整数
- **THEN** 系统 MUST 拒绝 `--commit`
- **AND** 系统不得把缺少可审计马匹详情覆盖计数的 payload 写入正式外部缓存

#### Scenario: 缺少基本覆盖不得 commit
- **WHEN** 任一地区导入 payload 的 `coverage_stats.races`、`entries`、`results` 或 `horses` 任一为 `0`
- **THEN** 系统 MUST 拒绝 `--commit`
- **AND** 系统不得把空赛事、空出马、空赛果或空马匹集合写入正式外部缓存

### Requirement: 英法美必须从 spike 升级为真实抓取准入
系统 SHALL 将英国、法国、美国从只读 spike 升级为真实抓取目标，并在正式写入生产数据前分别证明最近赛事、单场结果和马匹 profile 的真实入口稳定可访问并具备字段覆盖。

#### Scenario: 英国准入
- **WHEN** 香港阶段按用户指令暂停后进入英国
- **THEN** 系统先以 Sporting Life 作为英国真实导入主候选实现 parser/importer dry-run
- **AND** 报告 MUST 明确 Sporting Life 与 BHA 的职责边界、样本 URL、字段覆盖、访问限制和生产 commit 前门禁

#### Scenario: 英国批次不得混入海外赛场
- **WHEN** Sporting Life 日期结果页同时暴露英国、爱尔兰、美国、加拿大、法国或其他海外赛场链接
- **THEN** 英国 importer MUST 只把英国赛场 allowlist 命中的 racecard 纳入英国批次计划和 coverage 统计
- **AND** plan-only 输出 MUST 暴露可复用的 `race_urls`，以便后续批次直接请求指定 racecard，减少重复日期扫描请求
- **AND** 报告 MUST 区分未过滤历史证据与当前有效英国覆盖口径

#### Scenario: 法国准入
- **WHEN** 英国阶段完成后进入法国
- **THEN** 系统先定位 France Galop 或 Geny 等法国公开来源的真实 race/result/horse detail 入口，并实现 parser/importer dry-run
- **AND** 报告 MUST 明确赛程、出马、赛果、马匹 profile 或行内详情的入口参数、法语字段处理边界和生产 commit 前门禁
- **AND** 若来源返回 `429` 或同等限流响应，系统 MUST 停止当前 dry-run 批次、返回 partial 请求证据和完成度摘要，且不得写入正式 `External*` 表

#### Scenario: 美国准入
- **WHEN** 法国阶段完成后进入美国
- **THEN** 系统先定位 Equibase 或其他美国权威来源的真实 entries/result/horse profile 入口，并实现 parser/importer dry-run
- **AND** 报告 MUST 明确 HTML chart、PDF chart、entries 和 horse profile 中哪个作为正式导入主来源，以及生产 commit 前门禁

### Requirement: 真实数据库接入不得改变新闻分发和前台产品
系统 MUST 将本变更限定为外部缓存和马名索引数据层，不得改变新闻抓取、翻译、自动发布、QQ 推送或公开前台展示。

#### Scenario: 写入外部缓存后不生成公开页面
- **WHEN** 任一地区真实数据库导入成功
- **THEN** 系统不得自动创建公开比赛页、赛果页、马匹页或今日赛程模块
- **AND** 公开首页和新闻详情页仍只展示已发布新闻文章

#### Scenario: 外部数据不触发 QQ 推送
- **WHEN** 任一地区真实数据库导入成功
- **THEN** 系统不得创建 `NewsArticle` 或 `QQPushDelivery`
- **AND** 现有新闻抓取、翻译、自动发布和 QQ 推送配置保持不变

### Requirement: RaceEvent 历史回填必须与 External 数据库导入分离
系统 MUST 将 `RaceEvent*` 产品层历史回填与 `ExternalRace*` 外部数据库导入保持分离。赛事信息编排工具不得把产品层回填误写入外部缓存表，也不得把外部 proof 当作产品层 apply 证据。

#### Scenario: RaceEvent 编排不写 External
- **WHEN** 运维人员执行赛事信息编排工具的 plan、prepare、audit 或 dry-run 阶段
- **THEN** 系统 MUST 不修改 `ExternalRace`、`ExternalRaceEntry`、`ExternalRaceResult`、`ExternalHorse` 或 `ExternalHorseAlias`

#### Scenario: External proof 不等于 RaceEvent apply 证据
- **WHEN** 某地区已有 `External*` proof-only 或 dry-run artifact
- **THEN** 系统 MUST 不将该 artifact 直接视为 `RaceEventRunner`、`RaceEventResult` 或 `RaceEventHistoryWinner` 的 apply 证据
- **AND** 系统 MUST 要求转换为 `RaceEventDataCandidate` 可审计候选后才能进入产品层流程

### Requirement: RaceEvent 历史回填复用真实抓取安全门禁
系统 SHALL 复用真实外部数据库抓取中已经建立的保守限速、显式网络授权、单次批量上限、运行证据和生产锁检查原则。

#### Scenario: 显式网络授权
- **WHEN** RaceEvent 历史回填需要请求外部来源页面
- **THEN** 系统 MUST 要求显式网络授权
- **AND** 系统 MUST 在运行 artifact 中记录请求入口、限速和请求摘要

#### Scenario: 批次超限
- **WHEN** RaceEvent 历史回填批次的赛事数、来源请求数或目标年份范围超过 plan 配置上限
- **THEN** 系统 MUST 拒绝执行或要求拆分批次
- **AND** 系统 MUST 不静默截断后伪装为完整覆盖

#### Scenario: 生产锁检查
- **WHEN** RaceEvent 历史回填准备进入正式 apply
- **THEN** apply-check MUST 确认外部数据导入运行数为 0 且相关导入锁为空
- **AND** 缺少该证据时 MUST 阻止 apply

### Requirement: RaceEvent 历史回填不得改变新闻分发
系统 MUST 保证 RaceEvent 历史回填不创建新闻文章、不触发翻译、不触发自动发布或 QQ 推送。

#### Scenario: 结构化赛事数据写入
- **WHEN** RaceEvent 历史回填通过审核并写入结构化赛事资料
- **THEN** 系统 MUST 不创建 `NewsArticle`
- **AND** 系统 MUST 不创建 `QQPushDelivery`

#### Scenario: 回填不触发新闻流水线
- **WHEN** RaceEvent 历史回填完成
- **THEN** 系统 MUST 不派发新闻抓取、翻译、AI 改写、自动发布或 QQ 推送任务
