# 已审核赛事中文名统一导入预演测试用例

## 自动化测试

| ID | 场景 | 预期 |
|---|---|---|
| T01 | 五份文件 SHA 均匹配 | 接受输入并记录 5 份锁 |
| T01a | 从 Markdown 解析的 2023 行按原生产查询排序重建分组行集 | 实算 SHA 必须等于 `c9c209e6…66d`，不得复制文档自报值 |
| T01b | 工作簿路径在哈希后、解析前被替换 | 哈希与解析始终使用一次加载的同一份 bytes，不产生 TOCTOU 窗口 |
| T02 | 任一 SHA、工作表或必需列变化 | fail closed，不生成 apply-ready |
| T02a | 工作簿的原文、年份、计数、Key 或 ID 与原始 Markdown 清单不同 | fail closed，并报告具体行和字段 |
| T03 | `2023` 行全部已确认且中文名/来源完整 | 通过 |
| T04 | 任一行状态非已确认或中文名空白 | fail closed |
| T04a | 审核中文名仍含让赛字样 | 仅删除让赛字样/空括号，保存 before/after；调整后再次校验 |
| T04b | 删除让赛字样后为空或仍不合法 | fail closed |
| T04c | 中文名含重复空格或尾部标点但不属于让赛标记 | 原样保留，不折叠空格、不删除标点 |
| T05 | 年份表达含单年、顿号和范围 | 正确展开、去重、升序 |
| T06 | 年份展开数与“年度赛事数”不一致 | fail closed |
| T07 | 同一系列多行中文名一致 | 聚合为一条系列动作 |
| T08 | 同一系列出现不同中文名 | fail closed |
| T09 | 普通赛事 ID + Key + 地区 + 年份 + 原文精确匹配 | 生成年度赛事动作 |
| T10 | 当前赛事中文名等于原文 | 分类为 would_update |
| T11 | 当前赛事中文名已等于建议值 | 分类为 already_applied |
| T12 | 当前赛事已有其他中文名 | 分类为 conflict |
| T12a | 系列或赛事目标字段存在 manual lock | 分类为 locked，整批 blocked |
| T13 | 香港污染行唯一匹配 6019/2012 | 候选改绑 5963 并写中文名，原文不变 |
| T14 | 5963 已有 2012 赛事或污染行不唯一 | conflict，整批 blocked |
| T15 | 不同 RaceSeries 使用相同中文名 | 进入提示，不自动合并 |
| T16 | 生产缺少目标系列或年度赛事 | missing，整批 blocked |
| T17 | 生产多出工作簿范围外同系列 Event 且中文名等于原文 | 逐场检查地区/系列/锁后纳入 fallback 翻译；已有独立中文名者仅 out_of_scope 提示 |
| T18 | 相同输入与相同 before 快照重复运行 | 业务 manifest identity 一致 |
| T19 | dry-run 前后任一目标字段、行数或 updated_at 变化 | 全字段摘要不同，snapshot drift，整批 blocked |
| T20 | 报告工作簿公式错误扫描与全表渲染 | 无公式错误，关键表可读 |
| T21 | 日本序号 64 修订为“京成杯秋季赛” | 语义 diff 仅一个获授权译名单元格，新工作簿保留其他业务值、公式和版式，16 个年度目标均使用新值 |
| T21a | 日本修订文件额外改变任一其他业务单元格或版式契约 | fail closed，不锁定新 SHA |
| T22 | apply 未传 `--commit` | 完成全量 CAS 校验但零写入、零 OperationLog |
| T22a | bundle 任一成员、index 内容身份或 expected index 原始 SHA 不符 | verify/apply/verifier/rollback 均在数据库访问或写入前 fail closed |
| T23 | RaceSeries/RaceEvent/HistoricalRaceEventTarget 任一 concrete field、`updated_at`、人工锁或主键集合漂移 | 事务内 fail closed，零部分写入 |
| T24 | apply 使用锁定 artifact 且全部 before 一致 | 单事务更新 `1300/8883/1` 并新增一条 OperationLog |
| T25 | 香港 Event 或 HistoricalRaceEventTarget 改绑触发目标系列年度唯一约束冲突 | commit 前阻断，整批回滚 |
| T25a | 香港修正缺少唯一关联历史目标，或 target/event 年份、地区、当前系列不一致 | dry-run/apply fail closed，零写入 |
| T26 | 写后 verifier | 三模型全部 after 一致、让赛标记为零、香港 Event/历史目标同步改绑、无额外目标 |
| T27 | 两个 PostgreSQL 连接在快照后并发修改目标 | apply 锁定后完整 CAS 发现漂移；锁等待受 5 秒 lock timeout 约束 |
| T28 | PostgreSQL 条件唯一约束发生并发竞争 | 无部分写入，错误明确，事务回滚 |
| T29 | OperationLog 创建失败 | 1300/8883/1 全部回滚，零成功日志 |
| T30 | 成功 apply 后重复执行相同 batch | fail closed/no-op，且不新增第二条 apply 日志 |
| T31 | 对象级 rollback 的 after-state 完全一致 | 单事务恢复本批业务字段、写一条 rollback 日志，独立 verifier 通过 |
| T32 | rollback 前任一 after 字段漂移或 apply 日志不唯一 | 禁止回滚，升级人工事故决策 |
| T33 | 1300 系列/8883 赛事 PostgreSQL 16 fixture | 查询数 <=40、commit <=60s、RSS 增量 <=256 MiB，并记录实际值 |
| T34 | `updated_at` 与批量写入 | 全部目标显式写为同一批次时间且被 after 快照/审计覆盖 |
| T35 | 香港关联历史目标成功改绑后执行 verifier 与对象 rollback | Event/target 同步到目标系列，rollback 后同步恢复源系列，两阶段完整行 CAS 均通过 |
| T36 | rollback 使用相同 batch ID/after-state 但 bundle-index、rollback artifact 或 production-before SHA 与原 apply 日志不一致 | 在锁定和业务写回前 fail closed，保持 after-state，零 rollback 日志 |
| T37 | 审核中文名含 `Handicap`、`(H)` 或独立 `H`，以及合法 `H. Allen` 人名 | 前三类让赛标记被隐藏且无残留；`H. Allen` 原样保留 |
| T38 | 同系列已公开 2026 Event `96` 仍为“京成杯秋季让赛” | 仅在 ID、年份、系列、地区、原文、旧中文名和已审核目标名全部精确匹配时纳入补充动作并改为“京成杯秋季赛” |
| T39 | 服务端 canonical JSON 中 JSONField 数字为 `1.0` | 分块传输保持原始数字词法；归档中所有 `fullRow.rowSha256` 与整体 `secondSha256` 均可从落盘内容独立重算 |
| T40 | 固定 Event `96` 已是目标名、名称漂移、身份漂移或记录缺失 | 分别分类为 already_applied、conflict、conflict、missing；任何漂移/缺失均使整批 blocked，不得静默遗漏 |
| T41 | 对象 rollback 精确恢复 Event `96` 的旧中文名“京成杯秋季让赛” | `rolled-back` verifier 接受 artifact 明列的精确 before；`applied` verifier 仍拒绝任何让赛标记 |
| T42 | commit 目标计数为 `1300/8883` 或退化为 `1300/8664` | 前者通过生产数量门，后者在数据库写入前 fail closed |
| T43 | CLI 读取 154 MB production-before、54 MB dry-run 和 45 MB rollback artifact | 全量文件先由 bundle index 流式哈希；执行只展开受哈希绑定的 metadata/紧凑 plan，连同 Django 初始化的入口峰值低于 256 MiB |
| T44 | 紧凑 execution plan 执行 apply、独立 verifier 和 rollback | before 完整行 SHA、稳定字段 SHA、必要 restore 值与完整 rollback 逐项一致；写后与回滚验证均通过 |
| T45 | 中文名为 `维多利亚（Handicap）` 或 `维多利亚(Handicap)` | 英文让赛词及其直接包裹的中英文括号整体删除，结果精确为“维多利亚” |
| T46 | 目标系列关联的范围外 Event 仍以 original_name 回退 | 生成 `translate_out_of_scope_fallback`；地区漂移或中文名锁定使整批 blocked |
| T47 | 同 batch ID 存在旧候选 OperationLog，但 bundle/artifact SHA 与当前 index/metadata 不同 | 独立 verifier 在接受数据库 after-state 前 fail closed |
| T48 | 预演后目标系列新增/改绑 Event，或完整范围中的非动作 Event 发生 full-row 漂移 | apply 在锁定父系列和完整 Event 集后发现集合/归属/SHA 不一致，零业务写入、零 OperationLog |
| T49 | lossless 重建中任一 full row 数字词法变化，或整体 content SHA 与服务端 `second.sha256` 不同 | 生成器在 execution plan 与 bundle 生成前 fail closed |
| T50 | snapshot 前后 checkout、image ID/tag 或 container started-at 任一变化 | 运行时 metadata 精确比较失败，本次只读快照候选作废 |
| T51 | 非动作源 Series `6019` 在预演后发生 key/地区/任意 concrete field 漂移 | apply、独立 verifier 和 rollback 均在业务写入前/验收时因完整父行 CAS 失败 |
| T52 | 非 allowlist 范围外 Event 有独立中文名且其中含“让赛” | 保持报告项，不生成 supplemental 更新，不覆盖人工独立名称 |
| T53 | supplemental fallback 或 Event `96` 的 series ID 正确但 `seriesKey` 漂移 | 分类 conflict，整批 blocked |

## RED / GREEN 证据

- RED：先以最小合成工作簿 JSON 和生产快照 fixture 运行测试，确认 manifest builder 尚不存在或目标分类未实现而失败。
- GREEN：实现后运行同一测试集，全部通过。
- 生产只读验证不作为普通单元测试依赖；核心分类使用本地 fixture。
- apply/rollback/verifier 的纯规范化和 bundle 校验可用 SQLite/普通单测快速覆盖，但事务、并发、锁、条件唯一约束、审计失败回滚、`updated_at` 与生产规模性能必须在 PostgreSQL 16 容器中用两个独立连接完成集成测试。真实生产仅在全部测试、review、备份和授权门禁后执行。

## 手工验收

- 核对五份文件 SHA 与用户交付一致。
- 核对顶层计数、香港修正、冲突/缺失列表和跨系列同译名提示。
- 核对“规则调整”表完整记录工作簿原值与最终值，且原工作簿 SHA 不变。
- 核对日本修订前后机器语义 diff 仅含序号 64 的最终译名单元格，并记录新 SHA。
- 打开并渲染 Excel 的所有工作表，检查长文本、冻结窗格、筛选和状态颜色。
- 确认服务器 HEAD、容器和数据库只读快照元数据被记录，且没有生产写入。
- 核对 bundle 在审核提交、服务器宿主和容器内的成员 SHA 与 index 原始 SHA 全部一致。
