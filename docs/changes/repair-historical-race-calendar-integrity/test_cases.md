# 历史赛事赛历完整性修复测试用例

## 1. RED 规则

- 实现开始后先新增本文件标记为 RED 的自动化测试，并实际运行。
- 有效 RED 必须因当前年份、分页、重点或马号行为错误而失败；环境缺依赖、fixture 错误、语法错误
  不算 RED。
- 香港生产审计和 apply 不以本地 fixture 冒充生产成功；生产阶段另记 artifact/backup/verifier。

## 2. 模型与年份合同

| ID | 场景 | 预期 | 阶段 |
|---|---|---|---|
| Y01 | 已知 `local_date=2024-12-08`、公开 `year=2025` | 模型/service 拒绝 | RED |
| Y02 | 普通香港马季事件 | `year=edition_year=2024` | RED |
| Y03 | 2025 届真实延期至 2026 | `year=2026`、`edition_year=2025`，证据完整时允许 | RED |
| Y04 | 跨届次但缺原因或权威证据 | 拒绝 | RED |
| Y05 | target 关联 event | 比较 target.year 与 event.edition_year | RED |
| Y06 | series 年度唯一 | 按 `(race_series, edition_year)` 拒绝重复 | RED |
| Y07 | 第一阶段 migration | 现有 event 的 edition_year 回填为旧 year | GREEN |
| Y08 | Release C constraint | local_date/year 不一致无法写入 | GREEN/PostgreSQL |
| Y09 | Release A 兼容期 edition_year 为空 | 兼容读取明确回退旧 year，新写强制双写 | RED |
| Y10 | 非香港合法延期 | census 分类合法，公开自然年/届次年分别正确 | RED |
| Y11 | 非香港未分类 mismatch | 阻断 Release C migration | RED/PostgreSQL |
| Y12 | Release A 镜像 migration plan | 不包含 B/C 最终约束 leaf | 发布合同 RED |
| Y13 | superseded target 与同 series/year active target | 条件唯一允许共存，superseded 不可再领取 | RED/PostgreSQL |
| Y14 | Release A repair receipt | manifest unique，actor/status/approval/action/rollback SHA 完整 | RED/PostgreSQL |

## 3. 香港 prepare/apply

| ID | 场景 | 预期 | 阶段 |
|---|---|---|---|
| H01 | 2019—2025 连续偏移 fixture | prepare 全部枚举，不从 2024 截断 | RED |
| H02 | 普通马季与真实延期混合 | 分类不同，不能统一按日期改写 | RED |
| H03 | target 年度链存在唯一冲突 | artifact 给出完整重编号图或阻断 | RED |
| H03A | 连续错年落到已有正确届次 | survivor active；旧 target superseded；旧 event 脱离 series、自然年正确且永久 draft | RED/PostgreSQL |
| H04 | 未知依赖或一对多系列 | prepare 标记 conflict，apply 非零 | RED |
| H05 | prepare | 数据库行计数和哈希不变，输出目录预存在时拒绝 | RED |
| H06 | artifact SHA 漂移 | apply 在任何写入前拒绝 | RED |
| H07 | 当前行 precondition 漂移 | 整批回滚，无 legacy registry/临时年份残留 | RED/PostgreSQL |
| H08 | 正常 apply | event PK 与全部依赖 FK/计数守恒 | RED/PostgreSQL |
| H09 | 重跑同一 artifact | `already_applied`，零额外写入 | RED |
| H10 | rollback 当前状态精确匹配 | 恢复 before，删除本 manifest legacy path | GREEN/PostgreSQL |
| H11 | rollback 状态漂移 | 非零停止，不部分恢复 | GREEN/PostgreSQL |
| H12 | approval 缺失/actor/action scope 不符 | 任何写入前拒绝 | RED |
| H13 | 并发 writer 在 freeze 后尝试 admission | 被拒绝，不能进入目标事务 | RED/PostgreSQL |
| H14 | 进程 commit 前被终止 | DB/receipt 均无提交，rollback artifact 可判定 | RED/PostgreSQL |
| H15 | commit 后、summary 前被终止 | DB receipt 显示已提交，重跑只继续 verifier | RED/PostgreSQL |
| H16 | Release C 后请求旧数据 rollback | 直接拒绝；只允许反向约束 migration 或整库恢复 | RED/PostgreSQL |
| H17 | 旧 `hong_kong_racing_season_spans_calendar_years` artifact | 拒绝并要求重新 prepare | RED |
| H18 | 非香港合法跨届次 mismatch | approved action 修 public year/slug/path，edition/target 不变 | RED |
| H19 | duplicate rollback | 恢复 target/event/registry/FK，superseded 状态清除 | RED/PostgreSQL |
| H20 | duplicate 有不可重挂依赖 | prepare/apply block，不留下半合并 | RED |

## 4. URL 与公开年份

| ID | 场景 | 预期 | 阶段 |
|---|---|---|---|
| U01 | 旧 `/races/2025/...-2025/` legacy registry | 301 到 `/races/2024/...-2024/` | RED |
| U02 | canonical 新 URL | 200，标题和 hero 年份为 2024 | RED |
| U03 | legacy 与 canonical 抢占同一 registry 路径 | 创建时拒绝 | RED |
| U04 | legacy path 指向 draft | 不公开重定向 | RED |
| U05 | sitemap | 只包含 canonical registry，不包含 legacy | RED |
| U06 | 系列历届列表 | 以公开自然年展示链接，合法延期可另示届次 | RED |
| U07 | canonical 与 legacy 并发抢占同一路径 | registry 单表唯一，只有一个事务成功 | RED/PostgreSQL |
| U08 | event canonical 字段与 registry 漂移 | 写入拒绝或 verifier 阻断 | RED |

## 5. 历史重点

固定 `today=2026-07-31`。

| ID | 场景 | 预期 | 阶段 |
|---|---|---|---|
| K01 | year=2024, tab=key，G1/G2/G3 | 仅 G1/G2 | RED |
| K02 | JG1/JG2/JPN1/JPN2 | 全部属于历史重点 | RED |
| K03 | 历史 G3 且 priority=P0/is_featured | 仍排除 | RED |
| K04 | year=2026, tab=key | 保留 P0/P1/featured 运营语义 | 回归 |
| K05 | year=2027, tab=key | 保留 P0/P1/featured 运营语义 | 回归 |
| K06 | 未选择 year, tab=key | 保留现状 | 回归 |
| K07 | 历史 key + grade=g1 | 只显示 G1 族 | RED |
| K08 | 历史 key + grade=g3 | 空结果 | RED |
| K09 | 无效 year | 不误进历史重点分支，不抛错 | RED |
| K10 | 历史 G1/G2 normalized_grade 为空 | 不猜等级，coverage/gap 报告可见 | RED |

## 6. 分页

创建同一年度、同一地区至少 95 场，包含同日同时间和空开赛时间。

| ID | 场景 | 预期 | 阶段 |
|---|---|---|---|
| P01 | year=2024 首次请求 | 40 场，有 next | RED |
| P02 | 连续 next 到末页 | 40/40/15，95 个唯一 ID，无遗漏 | RED |
| P03 | 从末页 previous | 能逆向回到第一页且每页最终升序 | RED |
| P04 | 同日超过 40 场 | 依靠时间+ID 边界，无重复/遗漏 | RED |
| P05 | year+region+tab+grade+when+q | 每个分页 URL 和结果都保持全部条件 | RED |
| P06 | 纯 q 跨年度结果 | 可完整分页 | RED |
| P07 | 签名被篡改 | 返回第一页、HTTP 200、无越界查询 | RED |
| P08 | 旧版本或筛选指纹不符 | 返回当前筛选第一页 | RED |
| P09 | 空 local_date/空 start_time | null-bit tuple 在 SQLite/PostgreSQL 均 NULLS LAST 且稳定翻页 | RED |
| P10 | query count | 每页固定上限，无 N+1；`tasks.md 0.1` 阈值 `<=12` | GREEN |
| P11 | 默认无 year/q 日期窗口 | 当前定位和既有懒加载不退化 | 回归 |
| P12 | 无效 cursor 携带 direction | cursor 与 direction 同时丢弃，回到第一页 | RED |
| P13 | 默认窗口旧 cursor 跨上海自然日 | anchor 不符，回到新日期第一页 | RED |

## 7. 跨栏赛无马号

| ID | 场景 | 预期 | 阶段 |
|---|---|---|---|
| N01 | 两匹不同马、号码均为 `-`、profile 不同 | 两匹均保留，不冲突 | RED |
| N02 | `""`、`-`、`–`、`—` | 全部规范为缺失值 | RED |
| N03 | `1A` 与 `1a` | 按既有号码大小写规则规范，不能当占位符 | RED |
| N04 | 同一真实号码对应不同 profile/马名 | identity conflict | 回归 |
| N05 | 缺号、无 profile、不同完整马名 | 以规范化马名保留 | RED |
| N06 | 缺号、无 profile、同名两行但内容冲突 | ambiguity gap/fail closed | RED |
| N07 | 断点续跑 | 新 output root/fresh run 下不重复，旧 checkpoint 明确拒绝且无迁移入口 | RED |
| N08 | A. P. Smithwick Hurdle 离线 fixture | 全部参赛马完成且 horse_number 为空 | RED |
| N09 | 三个已知跨栏错误 fixture | 全部成功，永久错误数归零 | RED |
| N10 | 既有多个空马号历史详情测试 | 继续通过 | 回归 |

## 8. 集成与回归

- `server/stable/test_race_calendar_responsive_ui.py`
- 新的年份/public-path registry/香港修复测试模块
- 历史 inventory、date discovery、batch materialization、detail source/import 全部相关套件
- race series identity、race event reconciliation、crawl orchestration
- race-live initialization/racecard sync/publication transition
- P0 racecard discovery、P0 horse profile participant source
- sitemap、文章赛事链接、后台赛事编辑
- `runtime/research` collector 离线 unittest
- SQLite 聚焦与完整 `stable`
- PostgreSQL 约束、事务回滚、advisory lock 和重编号 apply

## 9. 发布合同测试

| ID | 场景 | 预期 |
|---|---|---|
| O01 | Release A source/image | pending migration 精确等于 A leaf（含 receipt/supersession/registry），不存在 B/C leaf |
| O02 | Release B source/image | 只新增旧 series/year 约束切换，edition_year 仍 nullable |
| O03 | Release C source/image | 全库 verifier receipt 为通过才允许执行最终约束 |
| O04 | 每次 release | 保存 commit/image、`showmigrations`、pending plan，漂移即停止 |
| O05 | R4 maintenance | beat/worker/race-live 和受控命令 admission 均冻结后才可 apply |
| O06 | Release C 后回滚演练 | 反向约束 migration 与整库恢复至少一条在 PostgreSQL 验证 |

## 10. 生产验收证据

代码发布后的独立数据阶段至少记录：

1. 生产只读 prepare 的 scope、snapshot、分类计数与 artifact SHA。
2. 人工审核结论；冲突/待人工必须为 0 才能整批 apply，否则缩小为明确批准子集并重新产物。
3. 写前 PostgreSQL 备份路径与 `pg_restore -l`/恢复清单验证。
4. apply run id、逐状态计数、ledger SHA。
5. verifier 自然年一致率、依赖守恒、redirect 和 sitemap 结果。
6. 公网抽检 2024/2025 香港旧新 URL、2024 日本首末页、历史重点 G1/G2、跨栏赛详情。

上述任何一项未完成都不能写“已修复上线”。
