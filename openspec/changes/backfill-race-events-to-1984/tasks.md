## 0. Pre-declared hypotheses

- [x] 0.1 (application) PASS：使用离线 fixture 生成 50,000 个年度目标时峰值内存不超过 512 MiB、总耗时不超过 120 秒；BLOCKER：任一阈值超出或目标数/哈希不确定
- [x] 0.2 (application) PASS：历史总账后台首屏查询不超过 12 次数据库查询，50,000 目标测试库响应不超过 1 秒；BLOCKER：出现 N+1、无分页或超出阈值
- [x] 0.3 (integration) PASS：第一批选择器五地区各含 3 系列、约 9 个真实年度目标且整体覆盖三年代，总量在 40–50；BLOCKER：任一地区/年代缺失或选择 not-held 作为详情抓取样本
- [x] 0.4 (operations) PASS：网络关闭时外部请求为 0，开启时所有 adapter 共享预算且缓存/磁盘阈值前 fail closed；BLOCKER：任一 adapter 绕过全局开关、审批或预算
- [x] 0.5 (operations) PASS：每个 apply scope 原子写入并通过写后计数，失败恢复后总账和正式表回到 scope 前状态；BLOCKER：部分提交、缺口丢失或无法根据 artifact/备份回滚

## 1. 历史系列与年度总账模型

- [x] 1.1 (application) 新增 `RaceSeries`、审核状态、创办/终止年份、来源证据、人工锁和稳定 key 约束
- [x] 1.2 (application) 新增 `RaceSeriesName` 与 `RaceSeriesRelation`，支持历史名称有效期和前身/后继/合并/拆分关系
- [x] 1.3 (application) 新增 `HistoricalRaceEventTarget`、expectation/resolution 状态、模块状态、证据、永久不可得批准和年度唯一约束
- [x] 1.4 (application) 为 `RaceEvent` 增加 nullable `race_series` 外键并保留 `series_key` 兼容同步
- [x] 1.5 (application) 为 `RaceEventResult` 增加 official finish position、回填现有 source_refs，并调整历史冠军唯一约束以支持并列冠军
- [x] 1.6 (application) 生成并审查 Django 迁移、稳定 slug、系列年度唯一约束、索引和 PostgreSQL/SQLite 兼容性

## 2. Inventory artifact 与系列身份治理

- [x] 2.1 (integration) 实现逐字段来源权威、候选合并、冲突分类和低级来源只补空服务
- [x] 2.2 (integration) 实现系列 mapping 候选、历史名称有效期、前身后继和模糊匹配待审逻辑
- [x] 2.3 (integration) 实现 expectation/resolution 双状态转换、年度目标生成、not_due/not_held/cancelled 区分和总账完成率计算
- [x] 2.4 (application) 新增 inventory 管理命令，流式生成 series candidates、conflicts、annual targets、gap ledger 和 summary
- [x] 2.5 (application) 为 inventory artifact 增加 manifest SHA-256、review、approval、dry-run 和 commit 身份校验
- [x] 2.6 (application) 实现永久不可得双来源证据校验、人工批准元数据和重新开启缺口能力
- [x] 2.7 (application) 新增后台历史总账汇总页，支持地区、年代、系列、状态、模块和冲突筛选且不提供绕过 artifact 的 apply
- [x] 2.8 (application) 在 settings 中增加默认关闭的历史功能/网络设置，并校验 plan 缓存字节和最小磁盘预算
- [x] 2.9 (integration) 限制 runner/result raw payload 为结构化行级证据，整页 HTML/PDF 只保存 source cache 身份
- [x] 2.10 (application) 为 inventory commit、mapping、永久缺档批准、publication、网络 run 和写后核验接入 OperationLog/TaskExecutionLog
- [x] 2.11 (operations) 在 `.env.example` 和运维文档记录历史开关、请求预算、缓存和磁盘保守默认

## 3. 现有 2026 赛事系列迁移

- [x] 3.1 (application) 为生产 995 个 2026 `RaceEvent` 生成只读稳定系列 mapping artifact
- [x] 3.2 (integration) 识别并阻断带年份/日期的不稳定 key、同年重复 key 和名称相似冲突
- [x] 3.3 (application) 实现从已批准 mapping artifact 幂等创建系列并绑定现有年度赛事的命令
- [x] 3.4 (operations) 审核五地区 mapping 汇总、美国重复 key 和日本/香港日期型 key，保留批准证据

## 4. 五地区历史年度目录适配器

- [x] 4.1 (integration) 调研并记录日本 JRA/NAR 1984–当前年度分级目录的权威来源、可得年代和旧格式
- [x] 4.2 (integration) 实现日本历史目录 adapter 与离线 cache 解析，输出标准 catalog candidate
- [x] 4.3 (integration) 调研并记录中国香港 1984–当前年度分级目录的官方赛季来源和改名/停办证据
- [x] 4.4 (integration) 实现香港历史目录 adapter 与离线 cache 解析
- [x] 4.5 (integration) 调研并记录英国 Pattern Race 1984–当前年度的 BHA/年鉴来源和 Flat/Jump 历史结构
- [x] 4.6 (integration) 实现英国历史目录 adapter 与离线 cache 解析
- [x] 4.7 (integration) 调研并记录法国 Pattern Race 1984–当前年度的 France Galop/年鉴来源和等级沿革
- [x] 4.8 (integration) 实现法国历史目录 adapter 与离线 cache 解析
- [x] 4.9 (integration) 调研并记录美国 Graded Stakes 1984–当前年度的 TOBA/委员会目录、改名和重复赛事
- [x] 4.10 (integration) 实现美国历史目录 adapter 与离线 cache 解析
- [x] 4.11 (integration) 为五地区实现已入选系列 lineage/timeline discovery，补足前分级、后降级、取消和 not-held 届次
- [x] 4.12 (integration) 统一五地区 adapter provenance、解析器版本、年份支持范围、请求预算、缓存/磁盘预算和 source cache manifest

## 5. 历史详情编排与受控写入

- [x] 5.1 (integration) 扩展编排器从已批准总账切分 plan，拒绝总账外目标和审批后目标漂移
- [x] 5.2 (integration) 实现从完整赛果派生 runners，并保留 `derived_from_results` 与字段缺失
- [x] 5.3 (integration) 将冠军覆盖改为年度正式赛果优先、可信冠军证据补位，禁止复制整张历史表
- [x] 5.4 (integration) 扩展 coverage 将完整 scope 与缺口 scope 分开，空候选不得占位且缺口保留总账
- [x] 5.5 (integration) 实现字段级 existing-data diff、人工锁保护、高权威增量修正和回滚 before 值
- [x] 5.6 (application) 扩展 importer 原子应用年度基础、runners、results、冠军补位和总账状态
- [x] 5.7 (application) 实现写后年度赛事/模块/来源/可见性计数核验并只在全绿后标记 imported
- [x] 5.8 (integration) 实现约 45 场第一批选择器，校验五地区、三系列、三个年代和代表性类型
- [x] 5.9 (integration) 实现每地区默认 50 目标的年代带批次和按目标数计算的地区护栏，禁止领先超过 100 个标准目标
- [x] 5.10 (integration) 实现历史date/source discovery artifact，从pending总账固定target_id并绑定selection snapshot、apply前inventory/target SHA、请求账本、source cache manifest、review、gap与approval
- [ ] 5.11 (integration) 实现日本 JRA/netkeiba/JBIS、中国香港 HKJC、英国 Racing Post/Sky Sports/BHA、法国 France Galop/PMU、美国 Equibase/BRIS/DRF/BloodHorse/NSA 日期与直接页面发现适配器
- [x] 5.12 (application) 实现批准后的目标日期/直接来源定位原子apply，保留既有source_refs，支持有证据跨年日期与cancelled证据，转ready、materialize并写OperationLog及前后target SHA
- [ ] 5.13 (integration) 扩展详情adapter优先消费直接result/racecard/cancellation URL，并分离declared/actual/non-runner/result/cancellation来源状态
- [x] 5.14 (integration) 扩展第一批选择器与管理命令，支持pending预发现抽样、1998–2026三时间锚点、同target_id后发现复核，并为1984–1997保留独立早期验收门禁
- [ ] 5.15 (integration) 为日期发现和详情adapter实现HTTPS host/重定向/最终URL白名单校验，拒绝内网、非HTTP(S)与未批准host
- [x] 5.16 (integration) 实现地区距离解析契约，保留distance_text并记录显式distance value/unit/measurement system及可追溯派生换算
- [x] 5.17 (application) 实现ready/materialized目标的detail-source artifact、审批校验、target/event非破坏apply和批准capture精确绑定
- [x] 5.18 (integration) 实现英法 IrishRacing 历史详情备用 adapter，分离地区 provider、actual/results 语义、马号/闸位和并列名次
- [x] 5.19 (integration) 实现美国 Equibase 单场 PDF 详情 adapter，绑定批准 source cache，复核日期/赛场/场次并保留联合投注编号
- [x] 5.20 (integration) 实现五地区年代带标准批次artifact命令，固定pending总账范围、地区上限、进度护栏、审核CSV、manifest和approval
- [x] 5.21 (integration) 实现JRA年度表/单场结果和TOBA/Equibase Yearbook批次来源发现与离线详情解析，显式补齐地区距离单位并保留退赛马
- [x] 5.22 (integration) 实现权威基础字段批次验证与整批原子apply服务，绑定target/inventory/字段artifact身份并限制可更新字段和来源证据
- [x] 5.23 (application) 新增权威基础字段JSONL管理命令，强制expected SHA、dry-run逐字段diff、人工锁展示和apply前全批身份复核
- [x] 5.24 (integration) 为年代带标准批次增加既有selection snapshot排除输入，在地区limit前跳过已交代gap，并复制/哈希绑定排除证据且保持总账分母不变

## 6. 公开页面、搜索与索引

- [x] 6.1 (application) 将历届冠军改为按稳定系列汇总年度正式赛果和冠军补位并按年份去重
- [x] 6.2 (application) 保持历史人马术语动态关联，输出未命中术语缺口且不自动创建 HorseProfile
- [x] 6.3 (application) 为历史 inventory publication scope 实现质量门槛、显式批准和取消赛事公开审计
- [x] 6.4 (application) 为赛事日历增加年份筛选和赛事名称/别名/历史系列名称搜索并保留组合筛选
- [x] 6.5 (application) 实现仅包含达标 published 年度赛事的分片 sitemap 和 sitemap index
- [x] 6.6 (application) 为历史总量优化赛事日历、详情冠军和 sitemap 查询索引、分页与缓存

## 7. 自动化测试与静态验证

- [x] 7.1 (application) 补充模型约束、迁移、系列关系环、expectation/resolution 状态和现有 `series_key` 兼容测试
- [x] 7.2 (integration) 补充系列身份、年度目录、字段级来源冲突、not-held 和永久不可得证据测试
- [x] 7.3 (integration) 补充总账 artifact 哈希、审批漂移、流式大清单和 commit 不触网测试
- [x] 7.4 (integration) 为五地区历史目录 adapter 建立 1980 年代、中间年代和近年离线 fixture 测试
- [x] 7.5 (integration) 补充 runners 派生、冠军动态覆盖、部分 scope、年代护栏和写后总账测试
- [x] 7.6 (application) 补充赛事日历年份/搜索、历史详情、发布门槛、术语回退和 sitemap 分片测试
- [x] 7.7 (application) 补充后台 staff 鉴权、总账分页/查询次数、并列冠军和 sitemap cache 失效测试
- [x] 7.8 (integration) 补充历史 URL 稳定性、标准批次上限/地区进度、raw payload 边界和磁盘预算测试
- [x] 7.9 (application) 执行 Django check、迁移漂移、目标测试、完整 stable 回归和查询性能检查
- [x] 7.10 (operations) 执行 OpenSpec strict/all、git diff、Compose 配置和 Docker 镜像 source cache 路径校验
- [x] 7.11 (integration) 先补五地区date/source discovery离线fixture、冲突、无日期、直接URL、取消证据、跨年届次和来源权威测试
- [x] 7.12 (integration) 补declared/actual/non-runner/result分离、results派生和不伪造racecard测试
- [x] 7.13 (application) 补日期apply哈希漂移、source_refs非破坏合并、pending到ready、materialize、前后SHA、跨年日期、原子回滚、身份字段不可修改和OperationLog测试
- [x] 7.14 (integration) 补pending预发现抽样、selection snapshot不漏项、同target_id后发现复核、1998–2026首批三时间锚点与1984–1997早期验收门禁测试
- [x] 7.16 (integration) 补URL白名单、内网地址、重定向越界和最终host校验测试
- [x] 7.17 (integration) 补英里/弗隆/码、米制、混合单位、裸数字拒绝和原始distance_text不被覆盖测试
- [x] 7.18 (operations) 执行新增目标测试、完整stable回归、OpenSpec strict/all、Django check、迁移漂移和diff检查
- [x] 7.19 (integration) 补detail-source缓存复制、审批漂移、target原子性、target/event双层证据、dry-run命令和同URL不同capture拒绝测试
- [x] 7.20 (integration) 补Equibase standard PDF空格表头、联合投注编号、完整runners/results和赛事身份错配拒绝测试
- [x] 7.21 (integration) 补年代带批次年份边界、pending筛选、每地区稳定顺序、artifact身份和空/非法批次拒绝测试
- [x] 7.22 (integration) 补JRA年度表对齐、美国同名场地区分/移师、Equibase Yearbook出马/退赛/赛果和新来源审批测试
- [x] 7.23 (application) 补权威字段批次单位保留、未知字段/证据缺失、SHA漂移、人工锁、整批回滚和旧详情SHA失效回归测试
- [x] 7.24 (integration) 补标准批次排除snapshot的跨inventory、SHA漂移、重复target、limit前补位、artifact复制和remaining分母测试

## 8. 生产总账与第一批验收

- [x] 8.1 (operations) 部署空模型和只读 inventory 工具，完成生产备份、迁移、健康和回滚演练
- [x] 8.2 (operations) 对现有 2026 系列执行 mapping dry-run、人工审核 artifact 并受控 commit
- [x] 8.3 (operations) 五地区逐年生成并受控写入 1998–2026 catalog source cache 和年度总账
- [x] 8.4 (operations) 审核 1998–2026 历史独有系列、改名迁场、取消/not-held 和身份冲突，不以 TJCIS 首末出现年推断创办/停办年
- [x] 8.5 (operations) 批准并写入 1998–2026 年度总账 manifest，核验全局/地区/年代/系列分母且保持历史展示开关关闭
- [x] 8.6 (operations) 生成并审核约 45 场五地区 1998–2026 三时间锚点第一批应到清单，网络默认关闭
- [x] 8.7 (operations) 分地区开启第一批网络抓取，执行 coverage、gap ledger 和字段级 diff 审核
- [x] 8.8 (operations) 对完整 scope 执行 dry-run、生产备份、apply-check、正式写入和写后核验
- [ ] 8.9 (operations) 验收五地区前台年度详情、年份搜索、历届冠军、可见性和 sitemap，未通过不得扩大批次
- [x] 8.10 (operations) 核对生产全局开关、请求/缓存/磁盘预算、source cache 保留和 web/worker/beat 日志
- [x] 8.11 (operations) 根据第一批 dry-run 评估新增行数、索引和数据库增长，确认容量后才批准扩大批次

## 9. 全量年代带回填与最终审计

- [ ] 9.1 (operations) 完成 2016–2025 五地区批次抓取、缺口审核、分批写入和写后核验
- [ ] 9.2 (operations) 完成 2006–2015 五地区批次抓取、缺口审核、分批写入和写后核验
- [ ] 9.3 (operations) 完成 1998–2005 五地区批次抓取、缺口审核、分批写入和写后核验
- [ ] 9.4 (operations) 完成 1998–2026 全量重复/漏抓审计、前台验收并显式批准该阶段 publication scope 后开启正式展示
- [ ] 9.5 (operations) 调研、生成、审核并批准 1984–1997 五地区 catalog source cache、系列身份和年度总账
- [ ] 9.6 (operations) 完成 1984–1997 五地区早期页面结构验收，再按批准年代带抓取、审核、分批写入和写后核验
- [ ] 9.7 (operations) 对全部暂时缺口执行补源和身份复核，永久不可得逐项完成双来源证据审批
- [ ] 9.8 (operations) 生成最终 accounted/data-complete 报告，证明 accounted_rate=100% 并按地区/年代/系列披露永久缺档
- [ ] 9.9 (operations) 完成生产全量计数、重复/漏抓审计、备份恢复抽演、服务性能和公开页面最终验收
- [ ] 9.10 (operations) 更新 current_state、project_status、decisions、deploy_runbook 和来源缺口文档，归档 OpenSpec change
