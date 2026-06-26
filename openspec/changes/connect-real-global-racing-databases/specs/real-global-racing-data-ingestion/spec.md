## ADDED Requirements

### Requirement: 真实数据库接入必须按地区顺序推进
系统 SHALL 按 `香港 -> 英国 -> 法国 -> 美国` 的顺序接入真实赛马数据库。前一地区未完成最近 2 个月赛事和涉及马匹详情的验证前，后一地区不得进入正式生产 commit。

#### Scenario: 香港完成前不得正式写入英国
- **WHEN** 香港最近 2 个月真实赛事和涉及马匹详情尚未完成 dry-run、commit 和统计验证
- **THEN** 系统不得把英国、法国或美国真实数据写入正式 `External*` 表
- **AND** 英法美最多只能执行 read-only spike 或隔离 fixture 解析

#### Scenario: 每个地区完成后停止
- **WHEN** 任一地区完成最近 2 个月赛事、赛果、涉及马匹详情抓取和写入验证
- **THEN** 本轮任务 SHALL 停止该地区的继续抓取
- **AND** 系统不得自动加入 Celery Beat 周期调度或后台持续导入队列

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

### Requirement: 英法美必须先完成真实入口准入
系统 SHALL 在正式写入英国、法国、美国数据前，分别证明最近赛事、单场结果和马匹 profile 的真实入口稳定可访问并具备字段覆盖。

#### Scenario: 英国准入
- **WHEN** 香港阶段完成后进入英国
- **THEN** 系统先对英国候选来源执行 read-only spike
- **AND** 报告 MUST 明确 Sporting Life 与 BHA 的职责边界、样本 URL、字段覆盖、访问限制和是否进入正式导入

#### Scenario: 法国准入
- **WHEN** 英国阶段完成后进入法国
- **THEN** 系统先对 France Galop 或其他法国权威来源执行 read-only spike
- **AND** 报告 MUST 明确赛程、出马、赛果、马匹 profile 的入口参数和法语字段处理边界

#### Scenario: 美国准入
- **WHEN** 法国阶段完成后进入美国
- **THEN** 系统先对 Equibase 或其他美国权威来源执行 read-only spike
- **AND** 报告 MUST 明确 HTML chart、PDF chart、entries 和 horse profile 中哪个作为正式导入主来源

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
