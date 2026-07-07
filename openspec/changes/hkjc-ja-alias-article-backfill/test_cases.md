# hkjc-ja-alias-article-backfill 测试用例

本文档只依据本 change 的 `proposal.md`、`design.md`、`tasks.md` 和 delta spec 编写，不依据未来实现倒推测试点。目标是把“HKJC 日语 alias 概念合并”和“已发布文章术语精确回填”拆成可执行、可复查的验收用例。

测试类型说明：

- `A`：自动化测试或本地命令可验证。
- `S`：management command smoke test 可验证。
- `O`：生产 dry-run / apply 前后运维验收。
- `D`：文档、OpenSpec 或非目标边界验收。

## 0. 推荐测试落点

- `stable.tests.TermAliasConceptMergeTests`：概念合并 service 测试。
- `stable.tests.ArticleTermBackfillTests`：文章字段级回填 service 测试。
- `stable.tests.TermMaintenanceCommandTests`：management command 默认 dry-run、显式 apply、artifact 输出测试。
- `stable.tests.TermResolverTests`：必要时补充 `apply_single_term_mapping` 或语言边界回归测试。

实现时类名可按现有 `server/stable/tests.py` 组织调整，但测试行为必须覆盖本文档矩阵。

## 1. 标准测试 fixture

基础术语 fixture：

- `target_en_kalamatianos`：active `TermEntry(term_type=horse, source_language=en, source_ja="Kalamatianos", target_zh="欢快舞步", racing_region=japan)`。
- `source_ja_kalamatianos`：active `TermEntry(term_type=horse, source_language=ja, source_ja="カラマティアノス", target_zh="欢快舞步", racing_region=japan)`。
- `target_en_raijin`：active `TermEntry(term_type=horse, source_language=en, source_ja="Raijin", target_zh="霹雳雷公", racing_region=japan)`。
- `source_ja_raijin_conflict`：active `TermEntry(term_type=horse, source_language=ja, source_ja="ライジン", target_zh="雷神", racing_region=japan)`。
- `target_en_scintillation`：active `TermEntry(term_type=horse, source_language=en, source_ja="Scintillation", target_zh="烁亮丽", racing_region=japan)`。
- `other_alias_owner`：active 其它概念，拥有 active `TermAlias(source_language=ja, text="シンチレーション")`，用于模拟 active alias 被其它概念占用。

基础文章 fixture：

- `published_article_7117_like`：published 日文文章，`source_language=ja`，中文字段中包含 `カラマティアノス`，发布状态和 workflow 状态均为已发布路径的稳定值。
- `published_article_manual_body`：published 日文文章，`body_zh` 包含待替换日语词，但 `manually_edited_fields=["body_zh"]`。
- `draft_article_with_match`：未发布或非 published 文章，中文字段包含同一 source text。
- `english_article_boundary`：英文文章，中文字段包含英文 source text，覆盖英文单词边界替换回归。

## 2. 覆盖关系

| Spec Scenario | 主要测试 ID |
| --- | --- |
| dry-run 输出同目标合并候选 | TC-MERGE-001, TC-MERGE-002, TC-CMD-001 |
| apply 合并安全候选 | TC-MERGE-006, TC-MERGE-007, TC-MERGE-008, TC-CMD-002 |
| 冲突项不自动合并 | TC-MERGE-003, TC-MERGE-004, TC-MERGE-005 |
| apply 前重新校验当前状态 | TC-MERGE-009 |
| active alias 被其它概念占用时跳过 | TC-MERGE-010 |
| dry-run 输出字段级 diff | TC-BACKFILL-001, TC-BACKFILL-002, TC-BACKFILL-003 |
| apply 只替换明确命中的术语文本 | TC-BACKFILL-006, TC-BACKFILL-007, TC-BACKFILL-008 |
| 手工编辑字段受到保护 | TC-BACKFILL-009 |
| 回填不产生发布副作用 | TC-BACKFILL-010 |
| 回填支持受控批次 | TC-BACKFILL-004, TC-BACKFILL-005, TC-CMD-004 |
| apply 拒绝无审核范围写入 | TC-BACKFILL-011, TC-CMD-005 |

## 3. HKJC 日语马名概念合并

| ID | 前置条件 | 步骤 | 期望结果 | 类型 |
| --- | --- | --- | --- | --- |
| TC-MERGE-001 | 存在 `target_en_kalamatianos` 与 `source_ja_kalamatianos` | 执行概念合并 plan/dry-run | 输出 candidate，包含 target term id、source term id、`カラマティアノス`、`Kalamatianos`、`target_zh=欢快舞步`、原因 `same_target`；数据库无变化 | A |
| TC-MERGE-002 | 同 TC-MERGE-001，但 `target_zh` 存在前后空格或全半角差异 | 执行 plan/dry-run | 按规范化中文目标识别为同目标 candidate；artifact 保留原始值和规范化比较值 | A |
| TC-MERGE-003 | 存在 `target_en_raijin` 与 `source_ja_raijin_conflict` | 执行 plan/dry-run | 输出 skipped/review，原因包含 `target_zh_conflict`，不输出 candidate | A |
| TC-MERGE-004 | 日语 owner 与目标英文概念 `term_type` 不同 | 执行 plan/dry-run | 输出 skipped/review，原因包含 `term_type_mismatch`，不写库 | A |
| TC-MERGE-005 | 目标英文概念或日语 owner 为 inactive | 执行 plan/dry-run | 输出 skipped/review，原因包含 inactive 状态，不创建 candidate | A |
| TC-MERGE-006 | TC-MERGE-001 的 dry-run candidate 已审核 | 执行合并 apply | 目标英文概念新增 active 日语 alias `カラマティアノス`；源日语主术语 inactive 或标记已合并；源 notes 记录 `merged_into_term_id` | A |
| TC-MERGE-007 | TC-MERGE-006 已成功执行一次 | 再次执行同一 apply | 不创建重复 `TermAlias`；summary 记录 `already_merged` 或等价幂等结果 | A |
| TC-MERGE-008 | apply candidate 混有 1 条安全记录和 1 条冲突记录 | 执行 apply | 安全记录写入；冲突记录 skipped；summary 分别记录 applied/skipped 计数 | A |
| TC-MERGE-009 | dry-run 后，源日语 term 的 `target_zh` 被改为不同值 | 使用旧 plan artifact 执行 apply | apply 重新校验并跳过该行；数据库不写 alias、不停用源 term；apply result 记录 `stale_or_mismatch` | A |
| TC-MERGE-010 | `シンチレーション` 已被 `other_alias_owner` active alias 占用 | 尝试把 `シンチレーション` 合并到 `target_en_scintillation` | 输出 skipped/review，包含占用方 term id；目标英文概念不新增重复 alias | A |
| TC-MERGE-011 | 日语 source text 是另一个概念的主原文而非 alias | 执行 plan/apply | 视为 active owner 占用并跳过，artifact 包含 owner term id 和 owner source kind | A |
| TC-MERGE-012 | 日语 owner 不是主术语，而是其它 term 的 alias 且中文目标相同 | 执行 plan/dry-run | 按非安全子集跳过，输出人工复核原因，不自动移动 alias | A |
| TC-MERGE-013 | candidate artifact 输出到临时目录 | 检查 artifact 文件 | 至少包含 machine-readable JSON、人工复核 CSV、summary JSON；summary 记录 scanned/candidate/skipped counts | A/S |
| TC-MERGE-014 | 合并 apply 成功 | 检查 `source_terms_for_language(ja)` 或等价解析 | 目标英文概念可通过日语 alias 被日文文章术语匹配命中 | A |
| TC-MERGE-015 | 日语主术语同时拥有同步出来的同文本 primary `TermAlias` | 执行 plan/dry-run | 同一个 term 的主原文和自身 primary alias 只算一个 owner，仍输出同目标合并 candidate | A |

## 4. 已发布文章术语回填

| ID | 前置条件 | 步骤 | 期望结果 | 类型 |
| --- | --- | --- | --- | --- |
| TC-BACKFILL-001 | `published_article_7117_like` 的 `body_zh` 包含 `カラマティアノス`，目标 term 已有日语 alias | 执行文章回填 dry-run | 输出字段级 diff，包含 article id、field、term id、source text、target `欢快舞步`、完整 before/after 值、摘要、替换次数；数据库无变化 | A |
| TC-BACKFILL-002 | 同一文章多个中文字段包含待替换 source text | 执行 dry-run | 每个字段独立输出 diff row；summary 记录命中文章数和命中字段数 | A |
| TC-BACKFILL-003 | 文章字段很长 | 执行 dry-run | JSON artifact 保留完整 before/after 字段值；CSV artifact 可以只保留摘要，但不得作为唯一恢复依据 | A |
| TC-BACKFILL-004 | 存在多个已发布文章 | 使用 article id 过滤执行 dry-run | 只扫描指定文章；summary 的 scanned count 与过滤范围一致 | A/S |
| TC-BACKFILL-005 | 存在不同 `source_language` 的文章 | 使用 `source_language=ja` 和 term 过滤执行 dry-run | 只扫描日文来源文章；英文/繁中文章不被扫描或修改 | A/S |
| TC-BACKFILL-006 | TC-BACKFILL-001 的 diff artifact 已审核 | 使用 artifact 执行 apply | 对命中字段执行替换，`カラマティアノス` 变为 `欢快舞步`；未命中字段不变 | A |
| TC-BACKFILL-007 | 同一字段包含同一 source text 多次 | 执行 apply | 所有明确命中的 source text 均替换为 `target_zh`；replacement count 正确 | A |
| TC-BACKFILL-008 | 同一 term 拥有多个 source text，字段只包含其中一个 | 执行 apply | 只替换字段中实际命中的 source text；其它候选不产生变化 | A |
| TC-BACKFILL-009 | `published_article_manual_body.body_zh` 被记录在 `manually_edited_fields` | 执行 dry-run/apply | `body_zh` 默认 skipped，artifact 记录 `manual_field`；机器翻译字段若命中仍可更新 | A |
| TC-BACKFILL-010 | 文章存在发布状态、审核状态、workflow 状态、QQ delivery 记录 | 执行回填 apply | 只允许相关中文字段和 `updated_at` 变化；发布/审核/workflow/QQ 推送状态不变，不创建新 QQ delivery | A |
| TC-BACKFILL-011 | 未提供已审核 diff artifact，也未提供 term/article/date/source-language/limit 等显式范围 | 执行文章回填 `--apply` | 命令拒绝写入，返回可读错误；所有文章字段保持不变 | A/S |
| TC-BACKFILL-012 | `draft_article_with_match` 包含待替换 source text | 默认执行已发布文章回填 dry-run/apply | draft 或非 published 文章不被扫描或修改 | A |
| TC-BACKFILL-013 | dry-run 后文章当前字段被人工改动，不再等于 artifact before | 使用旧 artifact 执行 apply | apply 跳过该字段并记录 `stale_field_value` 或等价原因，不覆盖当前值 | A |
| TC-BACKFILL-014 | apply 成功后重复执行同一 artifact | 再次执行 apply | 不产生额外变化；summary 记录 unchanged/already_applied | A |
| TC-BACKFILL-015 | 英文 term `source_language=en`，字段包含 `Kalamatianos` | 执行回填 | 按英文单词边界替换；不得把长单词内部片段误替换 | A |
| TC-BACKFILL-016 | 中文字段不包含任何目标 source text | 执行 dry-run/apply | artifact 记录 no-op summary；数据库无字段变化 | A |
| TC-BACKFILL-017 | 输入 term id 不存在或 inactive | 执行 dry-run/apply | 返回可读错误或 skipped 记录，不扫描无效 term 导致的全库写入 | A/S |
| TC-BACKFILL-018 | 从 merge artifact 读取 term 范围 | 执行文章回填 dry-run | 仅使用 merge artifact 中 applied 或 candidate-approved 的 term/source text 范围，不把 skipped conflict 项纳入替换 | A/S |

## 5. Management command smoke tests

命令名由实现阶段决定；若最终命令名不同，以下用例按语义迁移到对应命令。

| ID | 前置条件 | 步骤 | 期望结果 | 类型 |
| --- | --- | --- | --- | --- |
| TC-CMD-001 | 合并 fixture 已创建 | 不带 `--apply` 执行概念合并命令 | 默认 dry-run，退出码为 0，输出 artifact 路径和 summary；数据库无变化 | S |
| TC-CMD-002 | TC-CMD-001 artifact 已审核 | 带 `--apply --plan-file <artifact>` 执行概念合并命令 | 写入安全 candidate，输出 apply result artifact；summary 计数与数据库变化一致 | S |
| TC-CMD-003 | 概念合并命令提供不存在的 artifact 路径 | 执行 `--apply` | 拒绝执行，退出码非 0 或 CommandError；数据库无变化 | S |
| TC-CMD-004 | 文章回填 fixture 已创建 | 不带 `--apply` 执行文章回填命令并提供 term/article 过滤 | 默认 dry-run，输出 diff JSON、review CSV、summary JSON；数据库无变化 | S |
| TC-CMD-005 | 未提供 artifact 或显式过滤范围 | 执行文章回填命令 `--apply` | 拒绝写入，错误文案说明需要 reviewed artifact 或 explicit filters | S |
| TC-CMD-006 | 已审核文章 diff artifact 存在 | 执行文章回填命令 `--apply --diff-file <artifact>` | 只修改 artifact 覆盖的字段，输出 apply result；不修改非 artifact 文章 | S |
| TC-CMD-007 | 命令指定 `--output-dir` | 执行 dry-run | 所有 artifact 写入指定目录；stdout 打印 summary 和路径 | S |
| TC-CMD-008 | 命令指定 `--limit 1` | 执行 dry-run | scanned 或候选输出受 limit 控制，summary 记录 limit 生效 | S |

## 6. Artifact schema and rollback coverage

| ID | 前置条件 | 步骤 | 期望结果 | 类型 |
| --- | --- | --- | --- | --- |
| TC-ART-001 | 概念合并 dry-run 完成 | 检查 `merge_plan.json` 或等价 JSON | 每行包含 action、source term id、target term id、source text、source language、term type、target zh、skip/candidate reason | A/D |
| TC-ART-002 | 概念合并 apply 完成 | 检查 apply result JSON | 每行包含 applied/skipped 状态、写入 alias id、停用 source term id、notes 更新摘要或跳过原因 | A/D |
| TC-ART-003 | 文章回填 dry-run 完成 | 检查 diff JSON | 每行包含 article id、field、term id、source text、target zh、full before、full after、replacement count、manual skip 标记 | A/D |
| TC-ART-004 | 文章回填 apply 完成 | 检查 apply result JSON | 每行包含 applied/skipped/unchanged/stale 状态和当前字段校验结果 | A/D |
| TC-ART-005 | 需要从 artifact 恢复文章字段 | 使用 diff JSON 的 before 值人工或脚本恢复测试库字段 | 能恢复到 dry-run 前字段值；CSV 摘要不是恢复所需唯一数据 | A/O |

## 7. 生产运维验收

| ID | 前置条件 | 步骤 | 期望结果 | 类型 |
| --- | --- | --- | --- | --- |
| TC-OPS-001 | 本地实现完成 | 执行 `DB_ENGINE=sqlite python manage.py check` | Django check 通过 | A |
| TC-OPS-002 | 本地实现完成 | 执行 `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable` | 完整 stable 测试通过 | A |
| TC-OPS-003 | OpenSpec artifact 完成 | 执行 `openspec validate hkjc-ja-alias-article-backfill --strict` | 严格校验通过 | D |
| TC-OPS-004 | 准备生产 dry-run | 记录生产当前 commit、容器状态、`/healthz/`、导入锁、数据库备份路径 | 所有前置状态写入 `docs/deploy_runbook.md` 或执行记录 | O |
| TC-OPS-005 | 生产概念合并 dry-run 完成 | 人工抽查 candidate/skipped CSV | candidate 只包含同类型同目标安全项；冲突项在 skipped/review 中 | O |
| TC-OPS-006 | 生产概念合并 apply 完成 | 抽查后台术语搜索 `Kalamatianos` 和 `カラマティアノス` | 英文 HKJC 概念可被英文和日文 source text 搜到；冗余日语主术语 inactive 并有 notes | O |
| TC-OPS-007 | 生产文章回填 dry-run 完成 | 抽查 `http://umafans.run/news/7117/` 对应 diff | 只包含预期字段和预期术语替换，无整段重写 | O |
| TC-OPS-008 | 生产文章回填 apply 完成 | 抽查受影响文章前台页面、后台字段、summary 计数、`/healthz/` | 前台不再显示已修复 source text；站点健康；summary 与抽查一致 | O |
| TC-OPS-009 | 生产执行完成 | 更新 `docs/current_state.md`、`docs/deploy_runbook.md`、`docs/project_status.md` | 文档记录命令、计数、artifact 路径、验收 URL 和剩余 skipped/review 项 | D/O |

## 8. 非目标边界

| ID | 前置条件 | 步骤 | 期望结果 | 类型 |
| --- | --- | --- | --- | --- |
| TC-SCOPE-001 | 文章仍有风格或翻译质量问题 | 执行本 change 命令 | 不调用翻译 provider，不调用 AI 改写，不重建全文 | A/D |
| TC-SCOPE-002 | 存在中文目标冲突 alias，例如 `ライジン` | 执行概念合并 apply | 不自动选择目标概念，保留人工复核 | A/D |
| TC-SCOPE-003 | 存在非 horse 类型 HKJC 日语缺口 | 执行本轮 horse alias 合并 | 不扩大到未规划的 jockey/race 全量合并，除非显式过滤和规格允许 | D |
| TC-SCOPE-004 | 文章被回填后符合 QQ 推送条件 | 执行文章回填 apply | 不触发 QQ 自动推送或补推 | A |

## 9. 当前预期执行命令

实现完成后至少执行：

```bash
DB_ENGINE=sqlite python manage.py check
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable --noinput
openspec validate hkjc-ja-alias-article-backfill --strict
git diff --check
```

若实现阶段新增了更细粒度测试类，先执行目标测试类，再执行完整 `stable` 测试。
