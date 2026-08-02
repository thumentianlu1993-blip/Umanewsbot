# design：多语言赛马术语统一与公开内容修复

## 设计原则

维持三层数据：

```text
source raw value
  -> reviewed canonical entity + multilingual aliases
  -> Chinese public display value
```

源文不可变；正式术语负责身份与展示；文章只保存经门禁生成的中文公开内容。

## 正式术语与别名

复用现有 `TermEntry` / `TermAlias`，不另建第二套词库。

首批目标：

- 马匹正式术语：`target_zh=幻梦逸想`；英语别名 `Kalpana`；日语别名 `カルパナ`。
- 赛事正式术语：`target_zh=英皇锦标`；收录经证据确认的英文全称/短称和日文全称/短称。
- 旧中文译名写入现有 `TermEntry.aliases_zh`，只用于中文搜索/兼容，不写入不支持中文语言值的
  `TermAlias`，也不参与源语言实体识别。

导入前必须检查：

- active 正式术语和 alias 的归一化冲突；
- `source_language`、`term_type`、地区和证据；
- 马匹身份是否能由赛事 runner/participant、外部正式身份或既有马匹档案唯一佐证。

`Kalpana` 当前地区若与身份事实不符，应在审核包中作为明确字段修复，不静默改写。

新增 `TermMappingEvidence` 保存正式映射证据：

- `term`、可空 `alias`
- `evidence_kind`、公开 `source_url`、`source_digest`
- `review_status`、`reviewed_by`、`reviewed_at`
- `identity_payload` 与 `identity_sha256`

只有 approved evidence 可支持 alias 激活和历史修复。URL/identity 变化产生新证据记录，不覆盖
旧证据；凭据、Cookie 和完整外部 payload 不入库。

## 解析与替换

新增统一 occurrence resolver，供翻译后校验、AI 改写后校验和历史 dry-run 复用。

优先证据：

1. 文章已确认赛事关联中的 runner / result / participant；
2. 已确认文章马匹链接；
3. 唯一 active 别名 + 强赛马语境；
4. 否则保留原文。

resolver 输出：

- `term_id / alias_id / source_language`
- occurrence 起止位置
- `confirmed / uncertain / conflict`
- evidence 与 resolver version

只替换 `confirmed`。英文按 occurrence 判断，不能因同一 surface 在别处是马名就全文替换。

## 新文章门禁

在基础翻译和 AI 改写后运行一致性校验：

- 同一 confirmed term 的公开字段必须统一为 `target_zh`；
- 已知 alias 残留时，若 occurrence confirmed 则确定性修正；
- conflict 阻断自动发布；
- uncertain 保留原文并记录审计，不伪造中文名。

标签从 confirmed terms 重建或规范化，不能同时出现 canonical 和源语言别名。

## 历史修复

复用 `term_gate_reprocessing` 的快照、分页、性能和 published audit 边界，新增正式
`canonical_term_consistency` issue 与字段级 patch 生成，不重走整篇翻译。

流程：

```text
冻结术语/别名版本
  -> 只读扫描已发布文章
  -> occurrence resolver
  -> 字段级 before/after diff
  -> manifest + 人工审核
  -> 独立 approval
  -> CAS apply
  -> 守恒 verifier
```

允许字段：`translated_title_zh / translated_summary_zh / translated_body_zh /
title_zh / summary_zh / body_zh / push_summary_zh / tags_json`。

若字段存在于 `manually_edited_fields`，整字段跳过。apply 使用文章行锁和逐字段 before SHA；
任一批准行漂移时首批整批停止。保存时必须抑制 QQ、通知和重新发布副作用。

## 模型与迁移

新增 `TermMappingEvidence` 及约束/索引 migration；`TermEntry`、`TermAlias` 继续作为正式术语
与源语言别名。现有 `TermCandidateEvidence` 只证明文章 occurrence，不能替代正式身份/译名来源
证据。`translation_metadata` 只记录 resolver version 和命中摘要，不作为正式证据真相。

## 性能

- 按 source language 和 alias normalized key 构建内存索引。
- 先从文本抽取可能 surface，再做 occurrence 分类，禁止“每篇文章 × 全量术语”扫描。
- 测试 10/20/100 篇查询数与耗时边界；生产 dry-run 小批开始。
- 本地 PostgreSQL 100 篇、2 万 active alias 的 dry-run 目标不超过 10 秒，ORM 查询数保持常数；
  生产先以 20 篇只读批次验证 RSS 和耗时，任一超过 512 MiB 或 30 秒即停止扩大。

## 可观测性

- 计数：confirmed replaced、uncertain preserved、conflict blocked、manual field skipped、
  published drift、canonical residual。
- 每个 issue 保存 article、field、term、alias、occurrence 和 evidence，不保存凭据或完整外部 payload。
- 后台可按 canonical term 查看多语言 aliases 和受影响文章。

## 回滚

- 新文章门禁由 feature flag 控制，异常时关闭一致性 enforce，保留审计。
- 历史 apply 生成逐字段 before ledger，可精确恢复；数据库备份为最终恢复点。
- 回滚不删除正式术语；若映射本身错误，先停用冲突 alias，再按 ledger 恢复受影响文章。

## 与新闻曝光变更的关系

本变更只统一实体显示与候选发现。赛事新闻聚类最终必须绑定 `RaceEvent.id`，不能把“英皇锦标”
字符串相同当作赛事身份权威。
