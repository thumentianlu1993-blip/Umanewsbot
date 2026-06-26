## ADDED Requirements

### Requirement: HKJC 样本导入必须先完成 dry-run 和 commit 闭环
系统 SHALL 支持对 HKJC 赛日、单场比赛和单匹马资料执行受控样本导入。每类样本在写入正式外部缓存表前必须先执行 dry-run，并在 commit 后提供导入统计和马名索引查询证据。

#### Scenario: HKJC 赛日样本 dry-run
- **WHEN** 运维人员使用 `--race-date` 和 `--payload-file` 执行 HKJC dry-run
- **THEN** 系统返回该 payload 的比赛、出马、赛果和唯一马匹统计
- **AND** 系统不得写入 `ExternalRace`、`ExternalRaceEntry`、`ExternalRaceResult`、`ExternalHorse` 或 `ExternalHorseAlias`

#### Scenario: HKJC 赛日样本 commit
- **WHEN** 运维人员确认 dry-run 结果后使用同一赛日 payload 执行 `--commit`
- **THEN** 系统写入对应 HKJC 外部比赛、出马、赛果、马匹和马名索引记录
- **AND** 系统返回 `run_id`、写入数量和覆盖率统计

#### Scenario: HKJC 生产样本 commit 前完成备份和确认
- **WHEN** 运维人员准备在生产环境执行 HKJC 样本 commit
- **THEN** 运维人员 MUST 先确认同一 payload 已在本地或隔离数据库完成 dry-run 和 commit
- **AND** 运维人员 MUST 完成数据库备份或快照并记录备份路径
- **AND** 运维人员 MUST 显式确认本次只执行低频小样本 commit

#### Scenario: HKJC 单场和单马样本覆盖
- **WHEN** 运维人员分别使用 `--race-id --payload-file` 和 `--horse-id --payload-file` 执行样本导入
- **THEN** 系统分别验证单场比赛字段和单匹马资料字段可以写入外部缓存
- **AND** 单匹马资料中可信英文名或繁体中文名 SHALL 派生可查询的 `ExternalHorseAlias`

#### Scenario: HKJC 样本导入后查询统计和索引
- **WHEN** HKJC 样本 commit 完成
- **THEN** 运维人员可以使用 `--stats-run-id` 查看该导入运行的状态、成功数、失败数和覆盖率统计
- **AND** 运维人员可以使用 `--lookup-name` 查询样本马名命中的外部 horse ID、语言、置信度和最近发现时间

### Requirement: HKJC commit 必须保留安全闸门
系统 MUST 在真实网络抓取实现前拒绝无 `--payload-file` 的 HKJC commit。HKJC commit 必须执行批量上限、单来源互斥和失败隔离，避免占位数据、超量 payload 或并发导入污染正式外部缓存。

#### Scenario: 无 payload 的 HKJC commit 被拒绝
- **WHEN** 运维人员执行 HKJC `--commit` 但未提供 `--payload-file`
- **THEN** 系统拒绝本次导入并返回明确错误
- **AND** 系统不得创建成功导入 run 或写入正式外部缓存表

#### Scenario: HKJC payload 超过批量上限
- **WHEN** HKJC commit payload 中比赛数量超过 `max_races` 或唯一马匹数量超过 `max_horses`
- **THEN** 系统拒绝本次导入并返回明确的超限错误
- **AND** 系统不得静默截断、部分写入或创建成功导入 run

#### Scenario: HKJC 同来源导入互斥
- **WHEN** 已存在 HKJC 来源的运行中导入锁
- **THEN** 系统拒绝或延后新的 HKJC commit
- **AND** 系统不得绕过锁并发写入同一来源外部缓存

#### Scenario: HKJC 单目标失败隔离
- **WHEN** HKJC payload 中某个比赛或马匹字段缺失导致写入失败
- **THEN** 系统记录可审计错误或返回明确失败
- **AND** 新闻抓取、翻译、自动发布、QQ 推送和公开页面继续按原逻辑运行

### Requirement: HKJC 真实网络抓取必须以小样本准入
系统 SHALL 在正式启用 HKJC 真实网络抓取前完成小样本准入验证。准入验证必须确认入口 URL 或 API、请求参数、限速设置、字段映射、失败行为和样本数据与 payload commit 路径的一致性。

#### Scenario: HKJC 真实网络赛日 dry-run
- **WHEN** 系统对 HKJC 真实网络赛日入口执行小样本 dry-run
- **THEN** 系统记录请求 URL、请求次数、限速设置、返回状态和解析字段
- **AND** 系统不得在 dry-run 阶段写入正式外部缓存表

#### Scenario: HKJC 真实网络小样本 commit
- **WHEN** HKJC 真实网络 dry-run 已确认字段稳定且运维人员显式允许 commit
- **THEN** 系统只允许低频、小批量、单来源互斥地写入样本数据
- **AND** 系统必须记录 run_id、命令、请求边界、备份路径和回滚口径

#### Scenario: HKJC 网络限速和批量上限可由运行环境控制
- **WHEN** 系统实现或启用 HKJC 真实网络小样本
- **THEN** 系统 MUST 通过 Django settings 和环境变量配置请求间隔、单次最大比赛数和单次最大马匹数
- **AND** `.env.example` 和运维 runbook MUST 展示这些配置项的默认关闭或保守取值

#### Scenario: HKJC 网络入口不可稳定访问
- **WHEN** HKJC 真实网络入口返回访问限制、空数据、结构变化或解析失败
- **THEN** 系统不得进入正式网络 commit
- **AND** 文档必须记录失败入口、错误摘要和后续替代方案

### Requirement: 英法美数据库 spike 必须只读且隔离
系统 SHALL 对英国、法国、美国数据库来源执行只读或隔离 fixture spike。spike MUST NOT 写入正式外部缓存表，MUST NOT 加入 Celery Beat、生产管理命令调度或正式导入队列。

#### Scenario: 美国 Equibase spike 隔离执行
- **WHEN** 系统执行 `Equibase` spike
- **THEN** spike 只评估 entries、results、charts 或 PDF、horse profile 的访问性和字段覆盖
- **AND** spike 不得写入正式外部比赛、出马、赛果、马匹或马名索引记录

#### Scenario: 英国 Sporting Life 和 BHA spike 隔离执行
- **WHEN** 系统执行英国数据库 spike
- **THEN** spike 分别评估 `Sporting Life` racecards、results、horse profile 和 `BHA` 官方搜索、监管或补字段入口
- **AND** spike 不得把任一来源加入正式导入队列

#### Scenario: 法国 France Galop spike 不进入新闻正文链路
- **WHEN** 系统执行 `France Galop` spike
- **THEN** spike 只评估结构化赛程、报名、出马、赛果和马匹资料入口
- **AND** 系统不得抓取法语新闻正文进入新闻审核、翻译、自动发布或 QQ 推送主链路

#### Scenario: spike 保存位置隔离
- **WHEN** spike 需要保存 HTML、JSON、PDF 或解析样本
- **THEN** 样本只能保存到隔离 fixture、临时文件或仓库文档报告
- **AND** 样本不得进入正式外部缓存表或正式术语库

#### Scenario: spike 前后正式表计数保持不变
- **WHEN** 任一英法美 spike 完成
- **THEN** 验证步骤 MUST 记录 spike 前后的正式 `External*` 表和 `ExternalHorseAlias` 计数
- **AND** 如计数发生变化，本轮 spike SHALL 判定为失败并不得给出正式导入准入

### Requirement: spike 报告必须给出正式导入准入判断
系统 SHALL 为英法美每个数据库来源产出可复查 spike 报告。报告必须记录请求边界、字段覆盖、失败情况、解析样本和后续是否进入正式导入的建议。

#### Scenario: spike 报告记录请求证据
- **WHEN** 任一英法美 spike 完成
- **THEN** 仓库文档记录样本 URL、请求次数、限速设置、请求方式、成功状态和失败摘要

#### Scenario: spike 报告记录字段覆盖矩阵
- **WHEN** 任一英法美 spike 完成
- **THEN** 仓库文档记录比赛、出马、赛果和马匹 profile 字段覆盖情况
- **AND** 文档标记无法获取、需要 JS、需要 PDF 解析或存在访问限制的字段

#### Scenario: spike 报告给出准入状态
- **WHEN** 任一英法美 spike 完成
- **THEN** 仓库文档给出 `ready_for_formal_import`、`needs_more_spike`、`not_recommended` 或等价准入状态
- **AND** 如果建议进入正式导入，文档必须说明最小正式导入范围和下一步 OpenSpec change 建议

### Requirement: 本轮不得产生前台比赛或马匹产品
系统 MUST 将本轮 HKJC 样本导入和英法美 spike 限定为外部缓存、马名索引、字段评估和后续项目准备。本轮不得实现或启用公开比赛页、赛果页、马匹页、今日赛程模块或完整数据检索产品。

#### Scenario: HKJC 样本写入后不生成公开页面
- **WHEN** HKJC 样本导入写入外部缓存表
- **THEN** 系统不得自动创建公开比赛页、赛果页或马匹页
- **AND** 公开文章详情页仍以新闻内容为主

#### Scenario: spike 完成后不改变新闻分发
- **WHEN** 英法美 spike 完成
- **THEN** 系统不得因此改变新闻抓取、自动发布或 QQ 自动推送策略
- **AND** 如需正式导入或前台展示，必须另起 OpenSpec change
