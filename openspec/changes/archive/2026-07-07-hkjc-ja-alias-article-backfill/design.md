## Context

现有术语库已经支持正式术语、source alias、按语言解析术语、翻译链路应用术语，以及后台快速创建术语后对文章执行单条术语替换。HKJC 2020-2023 赛事补齐后，生产数据里仍存在一类历史遗留形态：日语马名作为独立日语主术语存在，中文目标与 HKJC 英文概念一致，但没有并入英文 HKJC 概念的 alias 集合。

这类数据会造成两个问题：

- 概念层面：后台搜索可能因为独立日语主术语而命中，但英文 HKJC 概念本身没有日文 alias，后续以该概念为准的替换和审计不完整。
- 内容层面：术语补齐前已经发布的文章不会自动重新应用新术语，因此仍可能保留 `カラマティアノス` 等原文。

本变更只处理术语维护和已发布内容的精确术语回填，不改变采集、翻译、自动发布、QQ 推送主链路。

## Goals / Non-Goals

**Goals:**

- 提供可 dry-run、可审计、可重复执行的同中文目标日语主术语并入 HKJC 英文概念流程。
- 对冲突、不同目标、不同类型、非主术语 owner 等不安全情况输出人工复核记录，不自动写入。
- 提供已发布文章字段级术语回填流程，复用现有术语替换语义，只替换明确命中的 source text。
- 生产执行必须支持 artifact 输出、显式 apply、执行前后计数和健康检查记录；文章回填 artifact 必须包含可恢复原字段值的完整数据。
- 保持现有 Django 单体和术语模型，不引入新外部依赖。

**Non-Goals:**

- 不重新翻译整篇文章。
- 不修改文章发布状态、审核状态、抓取状态或 QQ 推送状态。
- 不自动处理中文目标冲突的日语 alias；冲突项留给人工判定。
- 不合并所有重复术语类型，只处理本次 HKJC horse alias 场景需要的安全子集。
- 不为审计新增数据库表；本次审计输出写入 runtime artifact 和术语 notes。

## Decisions

1. 概念合并采用“计划 + apply”两阶段服务。

   - 选择：新增或扩展术语维护 service，先生成 merge plan，再由管理命令显式 apply。
   - 理由：生产术语库是业务真源，必须先看到候选、跳过原因和预期写入数，才能执行。
   - 备选：直接在导入脚本中遇到同目标就合并。放弃原因是历史数据和当前导入批次已经分离，直接写入不利于复核和回滚。

2. 只自动合并安全子集。

   - 选择：自动合并条件限定为目标 HKJC 英文概念 active、源日语 owner 为 active 日语主术语、`term_type` 一致、规范化后的 `target_zh` 一致、且没有发现不同中文目标、不同类型或其它 active 概念占用同一日语 source text。
   - 理由：这覆盖当前主要剩余项，同时避免把冲突 alias 移到错误概念上。
   - 备选：按英文名或外部 ID 强行合并。放弃原因是现有 HKJC/WP Stud/手工术语来源并不总有同一外部 ID，且冲突项需要人工判断。

3. 合并写入以现有模型表达，不新增迁移。

   - 选择：将日语 source text 写成目标概念的 alias；将冗余日语主术语停用，并在 notes 中记录 `merged_into_term_id`、时间和命令上下文。
   - 理由：现有 `TermEntry`/alias 模型已经能表达“一个概念多语言 source text”，停用状态也能解释后台里少量 inactive 术语的来源。
   - 备选：新增 merge history 表。放弃原因是本次操作规模小，runtime CSV/JSON artifact 加 notes 足以审计。

4. 文章回填复用现有术语替换语义。

   - 选择：以 term 或 merge artifact 为输入，扫描文章中文字段中是否仍包含 source text，生成字段级 before/after diff；JSON artifact 保存完整字段原值和目标值，CSV artifact 保存便于人工抽查的摘要；apply 时复用 `apply_single_term_mapping` 等现有替换逻辑。
   - 理由：这能保持与翻译链路、后台“应用新术语到文章”的行为一致，并降低新增替换规则风险。
   - 备选：重跑翻译或 AI 改写。放弃原因是会扩大内容变化面，且无法保证只修复术语。

5. 已发布文章回填默认保护人工编辑字段。

   - 选择：默认跳过 `manually_edited_fields` 中记录的发布字段；机器翻译字段可以更新，未被手工标记的发布字段可以更新。
   - 理由：术语修复不能覆盖人工编辑成果。
   - 备选：为保证前台显示全部更新而强制改写发布字段。放弃原因是生产内容存在人工审核和编辑流程，强制覆盖风险高。

6. 管理命令默认 dry-run，写入必须显式 `--apply`。

   - 选择：命令输出到 `runtime/term_backfills/<timestamp>/`，包含 summary、candidate/skip rows、article field diffs 和 apply result。
   - 理由：便于生产复核、恢复和后续写回 `docs/deploy_runbook.md`。
   - 备选：只在 stdout 输出。放弃原因是长批次容易丢失上下文，也不利于和 spreadsheet/manual review 对齐。

7. 生产 apply 必须绑定已审核范围。

   - 选择：概念合并 apply 读取 dry-run 生成的 plan artifact；文章回填 apply 读取已审核 diff artifact，或要求显式 term/article/date/source-language 过滤，并拒绝无范围全库 apply。
   - 理由：本次目标是修复已知 HKJC alias 与历史文章字段，不允许一次命令在生产误扫并写入全部已发布文章。
   - 备选：允许 `--apply` 默认按 dry-run 同条件重算全库。放弃原因是 dry-run 与 apply 间数据会变化，且人工复核对象无法稳定对应。

## Risks / Trade-offs

- [错误合并 alias] -> 自动合并只覆盖同类型、同中文目标、active 日语主术语且无其它 active owner 占用的安全子集；所有冲突输出 skip artifact。
- [覆盖人工编辑内容] -> 默认尊重 `manually_edited_fields`，测试覆盖手工字段跳过。
- [文章内容变化过宽] -> 只做明确 source text 替换，不重新翻译，不调用 AI 改写，不修改 workflow/publish/QQ 状态；生产 apply 必须绑定已审核 artifact 或显式过滤。
- [需要恢复错误文章字段] -> dry-run/apply artifact 保存完整 before/after 字段值和文章 ID，CSV 摘要仅用于人工快速复核，不作为唯一恢复依据。
- [dry-run 与 apply 间数据变化] -> apply 前重新读取并校验当前 owner/term/article 状态；校验失败的行转为 skipped。
- [停用术语造成后台困惑] -> 在 source term notes 中记录合并目标和原因，并在文档说明 inactive 术语可能来自安全概念合并。
- [大批文章扫描慢] -> 命令支持文章 ID、发布时间范围、limit、source language、term ID/artifact 过滤；生产按小批次执行。

## Migration Plan

1. 本地实现 service、命令和测试；不新增数据库迁移。
2. 在本地或 staging 用 SQLite/PostgreSQL 数据样本执行 dry-run，确认 artifact 字段完整。
3. 部署前在生产执行数据库备份，记录当前 commit、容器和 `/healthz/`。
4. 生产先执行概念合并 dry-run，人工检查 candidate/skip；确认后执行 `--apply`。
5. 使用合并输出或指定 term 范围执行文章回填 dry-run，抽查 diff；确认后从已审核 artifact 小批次 `--apply`，不执行无范围全库写入。
6. 执行后检查 `/healthz/`、相关文章页面、术语后台搜索和计数；将命令、计数、artifact 路径写回文档。
7. 回滚策略：如发现错误合并，按 artifact 中的 term/alias 记录删除目标 alias、恢复源 term active 状态；如发现错误文章替换，从生产备份或 artifact 中的完整 before 字段恢复受影响字段。

## Open Questions

- 无。计划审查决定：实现支持发现更多同类项，但生产首次 apply 只允许从已审核 artifact 或显式过滤范围执行；文章回填首批优先限定 HKJC 相关 term/merge artifact 和小批量文章范围。
