# 42 场等级展示与 2025 年目录 11 项收口

用户 2026-11-16 明确要求先修正 42 场等级映射和展示，再核对 2025 年剩余 11 项并补齐真正漏采。按根 AGENTS.md 交付，当前不改生产。

## 等级范围

生产只读快照 42 场：英国 20 个 Premier Handicap、香港 19 个繁体中文一至三级赛、2027 香港四岁系列 3 场。原始事实保留，修正统一展示解析和分页前 SQL 等级筛选；不做全库重写。

- BHA 官方说明 2022-10 起 Premier Handicap 保留 G3 拍卖目录黑体地位。内部分组保持 G3，公开标记“Premier 让赛”。仅接纳英国、2023 起、BHA 障碍目录来源合同。
- 香港 19 场从 HKJC 官方目录合同识别“一級賽”等，展示 G1/G2/G3。早期香港本地分级不借此自动升为国际等级；年份门槛为 2017。
- HKJC 官方赛季接口 4YO 显示“四岁马经典赛”，不赋予 G 等级；有相冲突已存 G 等级继续拒绝。
- Python、SQLite、PostgreSQL 使用相同来源合同；错误来源、旧年份、错误地区、已存等级冲突保持待核实。

来源：[BHA 更名说明](https://www.britishhorseracing.com/press_releases/jump-pattern-committee-update-22-23-season/)、[HKJC 四岁系列](https://campaigns.hkjc.com/racing-event-hub-4yo-series/en/)。快照缩减为不含内部调度字段的 42 条离线 fixture。

## 历史目录范围

目标 ID：60625、60648、74077、74108、74276、74321、74326、74382、74384、74385、74389。
只读核对发现已有 11 条独立赛事记录，但未回绑年度目录。6 场有公开赛果（其中两场仍缺 3 条未完赛结果）；5 条取消草稿必须重新核实。旧“未举办”注释不是充分证据：Tokyo City Cup 已找到 2025-10-25 官方赛果，需纠正误标并补入四匹完整赛果；Robert J. Frankel 延期至 2026-01-08，2026 已存在记录，不能新建重复赛事。

最终数据动作以来源核验后的精确 manifest 为准。复用已有赛事 ID、slug；补年度目标与系列关联，明确取消/当年未办/跨年延期。补赛果对无在线 writer 的 Tokyo City Cup 空表及两场 NSA 已确认缺行执行。不改其他地区、年份的业务数据，不重新采集六场已有行；只补两场 NSA 遗漏的 3 条未完赛结果。

安全与恢复：事务内锁定 event、target、关联行；比较前值、人工锁、writer/enrollment 和既有一对一关联；来源文件摘要绑定。dry-run、apply、幂等和 restore 共享同一 manifest；恢复要求 after-image 不漂移，新增赛果已被生涯/来源引用时拒绝删除。收据用 OperationLog；沿用历史写入准入检查，不绕过维护门禁。

验证：真实 RED → 42 场 GREEN → 页面及 PG 等级筛选对齐；目录修复正常/漂移/错误身份/已有绑定/未知状态/回滚引用保护；隔离数据库精确清单演练。独立只读 review 后形成 G2 发布包。未确认的来源问题不伪装为已修复。

## 清单执行实现

新增受限 `historical_target_reconciliation` 服务及管理命令；仅接受 2025 英美、最多 11 项、唯一 event/target 的 SHA 固定清单，不扫描或自动匹配生产数据。清单含 target/event/series 前值、已有赛果与出马表摘要、经核对来源文件摘要、typed action 和必要字段补丁。五动作：`attach_results`（4 场）、`complete_results`（2 场 NSA 非完赛缺行）、`cancelled`（Classic）、`not_held`（Brooklyn/Cougar/Frankel，Frankel 按已锁定口径不记录延期）、`recover_results`（Tokyo）。

`not_held` 目录 event 保持 null，遵守模型约束；原取消草稿保留 ID 与非公开状态，补准确证据。`attach_results` 不改已有 50 行赛果，只核对其全表摘要并回绑 series/target。Tokyo 沿旧 ID 20884 补日期、时区、无分级、距离、四匹名单及赛果，移除旧误判的生效注释并将旧值保存在清单/收据；既有 source_refs 的其他键保留。目录解析已识别源中 non-listed black-type 的赛事身份，不能继续按初版年鉴 G3 展示。

首次 apply 完成后保存包含所有受影响事件/目标/行的 after-image；后续 apply/dry-run 对账后返回幂等。restore 比较完整 after-image，删除仅本包新建的 Tokyo 行并恢复原字段；被新来源或生涯引用时拒绝。保存恢复收据，恢复后不可用同一 manifest 再 apply。所有状态清单在本地独立 PG 内先完整演练，不访问生产数据库运行测试。

## 方案审核返修

Frankel 74326 暂从可执行数据清单排除：自然年与届次年不是同一个字段，已向用户提出 G1 口径选择。在答复并绑定既有 2026 event/target/series 前，不把该项写成 not_held 或声称闭环；不阻塞其它 10 项准备。

状态矩阵（event→target；restore 精确回到 before）：

| 动作 | 前置 | event 后态 | target 后态 |
|---|---|---|---|
| attach_results | 2025、finished/published、确认全表、未绑定系列或同系列 | 仅补 race_series；保留既有名单/赛果和公开状态 | held/imported，event 绑定，local_date 对齐，runners/results=complete |
| cancelled | cancelled/draft、空表；明确原排期取消证据 | 保持 cancelled/draft，补真实原排期日期和来源 | cancelled/ready，关联同系列 cancelled event，runners/results=not_applicable |
| not_held | cancelled/draft、空表；官方当年停办证据 | 保持 cancelled/draft，来源补充 | not_held/ready，event=null，runners/results=not_applicable |
| recover_results | Tokyo 原 cancelled/draft、空表、无人工作业锁及 live writer | finished/published、确认时间、四匹 is_confirmed=true/official_finish_position，actual date 2025-10-25、无分级、原 ID/slug 保留 | held/imported，event 绑定，日期/等级/距离同步，runners/results=complete |

Tokyo 公开前同时满足 Sporting Life WEIGHEDIN、同日同赛场同赛名、全部四个编号和官方名次一一对应、官方 Santa Anita 赛果发布证明冠军；不能只有新闻冠军就创建全表。公开迁移与新增八条行、target 关联处于同一事务。不得将原 cancelled 状态遗留。restore 删除本包新增八条行，并恢复 cancelled/draft、无日期、旧等级和未关联 target；已有正确 50 行不触碰。

字段白名单：event 仅 race_series_id/local_date/race_datetime/local_start_time/timezone_name/grade_text/normalized_grade/distance_text/surface/eligibility_text/status/visibility_status/data_quality_status/result_confirmed_at/source_refs；其中状态/公开/确认字段由动作决定，manifest 不接受任意写入。target 仅 event_id/local_date/grade_text/normalized_grade/distance_text/expectation_status/resolution_status/module_statuses/source_refs/notes/last_checked_at；禁止 year/series/slug 身份重写。source_refs 新证据与旧误判归档；被其他写入或引用改变的记录拒绝恢复。

## 用户口径已锁定

用户明确答复：“保留2026年，不存在于2025年，延期信息无需记录”。因此 Frankel 74326 纳入 `not_held`：2025 年目录 event=null、not_held/ready；不添加延期说明，不修改 2026 年 event/target/series，不创建 2025 年公开赛事。既有未公开取消草稿不转公开、不补行。上述待核排除说明至此解除，11 项范围恢复完整。

## NSA 非完赛审核返修

Commonwealth Cup 7 匹实际出走、Colonial Cup 9 匹实际出走，原有赛果分别 6/7 条，漏了 PU/F 共三条。新增 `complete_results` 仅补来源明确的 PU/F 缺行，官方名次为空，存储排序序号不得作为完赛名次；保持原有 50 条赛果不变，更新三条名单 running_status。恢复仅删除本包新增 ID 并恢复三条名单前值；后续引用与人工锁仍拒绝恢复。Remsen 12 号经 NYRA 官方 Scratches 独立核对，不能由双表差集猜测非出走。
