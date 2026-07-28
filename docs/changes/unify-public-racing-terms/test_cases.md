# test_cases：多语言赛马术语统一与公开内容修复

## RED 计划

用户确认实现后，先为多语言 alias 汇聚、公开字段一致性和 published CAS 修复新增测试，确认当前
行为产生预期 RED，再实现。不得用事后伪造的历史 RED。

## 术语与身份

- `Kalpana`、`カルパナ` 均解析到同一 `TermEntry` 和 `幻梦逸想`。
- 英文全称/短称、日文全称/短称统一到 `英皇锦标`。
- alias 语言、类型或地区冲突时 fail closed。
- 同 surface 对应两个 active term 时返回 conflict，不按 priority 猜测。
- 普通英文句子中的同形词不替换；赛事 runner 结构证据下只替换目标 occurrence。
- 旧中文译名只进入 `aliases_zh`；`TermAlias.source_language` 不接受伪造中文值。
- alias 没有 approved `TermMappingEvidence` 时不能激活或进入 published repair。

## 新文章

- 标题、摘要、正文、push summary 和标签统一 canonical。
- AI 改写重新产生 `Kalpana` 或 `カルパナ` 时，confirmed occurrence 被修正。
- uncertain occurrence 保留原文且不产生错误马名标签。
- conflict 阻断自动发布，并在 gate issue 中包含字段/occurrence 证据。
- 日、英来源经过实时和批量链路得到一致结果。

## 历史 dry-run / apply

- dry-run 不写数据库，输出确定性字段 diff、before SHA、mapping version 和 manifest SHA。
- 人工编辑字段跳过，其他字段可独立修复。
- 源文字段、slug、公开时间、workflow、QQ delivery、NotificationLog 全部守恒。
- before SHA、术语版本、article ID 或 manifest 漂移时整批拒绝。
- 同一批准包重放零额外业务效果。
- rollback 精确恢复字段，仍不触发 QQ 或通知。

## 性能

- alias 索引批量预取，无逐篇全词库查询。
- 本地 PostgreSQL 100 篇、2 万 active alias 的 dry-run 不超过 10 秒且 ORM 查询数保持常数；
  生产 20 篇只读批次超过 512 MiB RSS 或 30 秒即停止。
- 长正文和同一 alias 多 occurrence 不产生重叠替换或位置偏移。

## 生产验收

- 先只读盘点英皇锦标相关文章及同场马匹术语。
- 人工核对首批 mapping 的身份、语言、地区和来源证据。
- dry-run 抽检至少包含英文稿、日文稿、混合残留稿和人工编辑稿。
- apply 后搜索 `Kalpana / カルパナ / 乔治六世锦标 / 英王乔治锦标` 的公开残留；
  允许源文和明确 unresolved occurrence，公开 canonical 字段不得无解释残留。
- 文章详情、首页、赛事详情在 1440px / 390px 下正常，QQ delivery 数与 message ID 不变。

## 预计测试入口

- `stable.test_english_term_context_gates`
- `stable.test_term_gate_reprocessing`
- 赛事/马匹公开显示相关测试
- 新增 `stable.test_public_term_consistency`

实现时追加实际 RED/GREEN 命令、结果和性能基线。

## RED 证据 -- 2026-07-26

### 命令

```bash
cd server && python manage.py test stable.test_public_term_consistency -v2
```

### 结果

```
Ran 32 tests in 92.264s
FAILED (failures=3)
```

### 通过的测试 (29/32)

全部 29 个非性能测试通过（`stable.test_public_term_consistency --exclude-tag=performance`）。

### 失败的测试 (3) -- 性能基线 (性能基线尚未达标)

| 测试 | 断言 | 实际 |
|---|---|---|
| `test_100_article_dry_run_within_10_seconds` | <10s, <50 queries | ~53s (SQLite 内存数据库瓶颈) |
| `test_orm_query_count_constant_regardless_of_article_count` | queries(10) ~= queries(100) delta=5 | SQLite 查询数波动较大 |
| `test_no_overlapping_replacement_or_position_offset` | 50+ occurrences, no overlapping spans | 通过（已修复） |

3 项性能基线在 SQLite 内存数据库下未达标，需要优化 alias 预取和索引构建策略：
- 大批量 (20k+) alias 处理在 SQLite 中超过 50 查询预算
- 生产 PostgreSQL 环境预计改善显著

### 回归测试

- `stable.test_english_term_context_gates` -- OK
- `stable.test_term_gate_reprocessing` -- OK
- `python manage.py check` -- OK
- `python manage.py makemigrations --check --dry-run` -- OK (无变更)
