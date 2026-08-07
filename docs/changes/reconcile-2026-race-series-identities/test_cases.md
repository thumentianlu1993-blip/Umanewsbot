# test_cases：2026 赛事系列身份归并与双卡片治理

## 分类与守恒

1. 已正确关联 target 不进入待审表，但计入总分母。
2. 唯一同地区、同年、同名称 event 且 series 不同，进入“唯一名称匹配”。
3. 同一名称命中两个 event，进入“同名多候选”，不生成默认正向 decision。
4. 无名称命中进入“无名称匹配”。
5. `not_held` 进入独立表，不匹配 event。
6. 分区计数与 target 总数严格守恒；重复或漏行失败。
7. 探索基线 1,085 = 684 + 226 + 11 + 162 + 2；正式快照不同则输出 drift blocker，不能静默接受。
8. 既有分类器的每个已知 classification/reason 都进入唯一机器分区；未知 reason 进入异常清单并阻塞。
9. `exact_link`、已关联身份/状态冲突、系列年度多候选、event 已占用、地区/状态冲突分别可审计，
   不会被四个预期表吞并或漏掉。

## 名称与身份边界

10. `RaceSeriesName`/event alias 只为歧义/无匹配行增加补充建议，不改变正式基础分桶，也不自动批准。
11. 跨地区同名（如英国 Sprint Cup 与香港同名赛事）不能成为正向候选。
12. 美国两个独立 Bayakoa Stakes 可以保持不同系列；同中文名不构成合并证据。
13. 名称相似但地区/日期/马场/等级/场地类型/距离矛盾，标记人工冲突。
14. 已存在对称 `do_not_merge` 锁的系列对不能生成正向 decision。

## 引擎兼容性

15. source 只有一个 annual event、无 target/name/relation，destination 无 2026 event，且批内身份互斥，
    标为 engine-compatible。
16. source 含其他年度 event、target、name 或非预期 relation 时不兼容。
17. 一个 source 对应两个 destination，两个候选都转人工，不允许任选其一。
18. destination 已有 2026 event、event 已被其他 target 拥有或 source/destination 重复，阻塞正向动作。
19. `engine_compatible=true` 但 decision 为空/defer 时，不生成动作。

## 工作簿与 decisions

20. JSON、CSV、XLSX 各类行集合、ID 和 SHA 一致；XLSX 含审核说明、四个预期数据 sheet 和异常清单。
21. 原始 manifest SHA 不符、manifest 绑定文件被替换、机器列与其散列一起修改、旧工作簿配新
    manifest，均拒绝。
22. 只有唯一匹配表的 decision/review_note 可编辑；其他 sheet 被编辑，或机器列被修改、删除、隐藏、
    重复、公式替换时回读拒绝。
23. 定稿 XLSX 文件 SHA 不符拒绝；BOM、中文、长名称和 Excel 日期保持稳定。
24. 任一非 defer 动作缺审核说明、白名单公开 URL 或 target/event/source series/destination series
    四项审核 identity SHA 时拒绝；只有
    `merge_and_link` 与正向技术兼容性冲突时由适配层拒绝。
25. review_note 精确映射 evidence.summary，锁定的公开 URL 映射 source_urls；用户新增 URL 不被接受。
26. 歧义/无匹配/未举办/异常表只能 defer；唯一匹配表的负向动作即使正向不兼容也可转既有
    decision，再由既有引擎验证精确系列对；defer 零动作。
27. 同一输入重复生成的 canonical JSON/CSV 内容 SHA 一致；XLSX 元数据固定或从机器 manifest 排除。
28. 导出递归排除完整 source_refs、notes、manual flags、原始 payload、Cookie/请求头/凭据键和值模式。

## 既有引擎集成回归

29. 生成的 decisions + 空 field repairs 能通过既有 prepare；审核后只改变 target/event 名称、日期、
    来源，或任一 source/destination series 的名称、锁、来源等 identity 字段而 ID 不变时，prepare
    因审核 SHA 漂移整批拒绝。
30. 正向动作移动 event、链接 target、建立 approved `MERGED_INTO`，名称/slug/公开状态和详情哈希不变。
31. 负向动作只写对称锁，不移动 event。
32. 首批全部动作在一个 manifest/事务中；任一 before/依赖/人工锁/目标年度漂移，整批零写入。
33. apply 后 verifier 通过；相同 artifact 重放必须明确拒绝或幂等返回，且零业务写入、不产生重复关系。
34. rollback 恢复 event/target/series relation/locks，且不影响无关事件后续变化。

## PostgreSQL 与性能

35. PostgreSQL repeatable-read 导出在并发插入/更新边界得到一致快照或明确失败。
36. PostgreSQL 并发 apply 仍由既有锁顺序串行化，不出现同年双 event。
37. 约 1,100 targets / 1,500 events fixture 下查询数有固定上限，不随行数线性增长。
38. SQLite 完成分类、序列化、工作簿和服务逻辑；PostgreSQL 16 完成快照、锁和 apply/rollback 专项。

## 生产验收

39. 正式导出先记录生产 HEAD、as-of 和新计数；与探索基线差异或异常清单非空必须人工确认。
41. 写前 custom-format 备份通过 `pg_restore -l`；失败则不 apply。
42. apply 前后 RaceEvent/runner/result/article/history-winner 总量及逐事件详情哈希守恒。
43. 每个实际含正向动作的地区至少抽查 2 个已合并系列（不足 2 个则全量），2026 详情页能读取
    历史届次/冠军，URL 与中文名不变；五地区赛历入口均正常。
44. `/healthz/`、`/races/`、抽样详情页正常；无计划外 Celery、QQ 或新闻发布副作用。

## RED/GREEN 证据

- RED：先为候选分桶、完整守恒、XLSX 防篡改、decision 转换和引擎兼容边界写失败测试。
- GREEN：实现适配层后通过；既有 `test_race_series_identity_review` 全量回归不得减少或放宽。
- PostgreSQL RED/GREEN 独立记录，不用 SQLite 结果代替锁与隔离级别证明。
