## Context

生产只读核对显示，当前正式术语库和术语候选池仍几乎全部是日文内容；多地区新闻源、语言字段和外部马名识别链路已经具备，但香港、英国、法国、美国等地区缺少可用中文译名数据。现有 `import_terms` 支持 CSV 预检和幂等导入，字段为 `term_type,source_language,source_ja,target_zh,aliases_ja,aliases_zh,priority,is_active,notes,race_grade`；第一版种子准备应复用这条入口，而不是新建一套正式入库机制。

本变更只做“准备可人工审核的术语种子”，来源限定为 HKJC 体系和 WP Stud。HKJC 体系第一版优先支持本地马匹资料、海外赛事转播资料、术语说明或赛绩指引等稳定 HTML/文本入口；`racecards` PDF 或排位表全量抽取只作为后续扩展，不纳入首批实现交付。WP Stud 作为高质量民间整理来源。由于来源页面结构、覆盖范围和译名冲突会持续变化，第一版必须保留来源证据、限速触网和冲突清单，避免把抓取结果直接变成正式术语。

## Goals / Non-Goals

**Goals:**

- 生成严格兼容现有术语导入字段的 `seed_candidates.csv`。
- 生成供人工审核的 `seed_conflicts.csv`，记录 HKJC 和 WP Stud 的译名差异、推荐主译名和来源证据。
- 第一版覆盖 `horse`、`race`、`jockey`、`trainer`、`racecourse`、`fixed_phrase`。
- 地区排序为香港优先、日本最后，中间地区按实现便利度处理。
- 输出所有 `target_zh` 为简体中文；繁体来源必须做繁简转换，并在 `notes` 或冲突文件中保留原始繁体证据。
- 命令默认只写 seed 文件到独立输出目录，不写 `TermEntry`、`TermAlias`、`TermCandidate` 或 `External*` 表。

**Non-Goals:**

- 不直接把种子候选导入生产正式术语库。
- 不新增后台审核 UI；第一版用 CSV 文件人工审核。
- 不把 Flameracing、Wikipedia、Wikidata、Idol Horse 纳入第一批实现。
- 不在第一版实现 HKJC `racecards` PDF、排位表 PDF 或网页排位表的全量抽取。
- 不做完整多地区外部赛马数据库生产 commit。
- 不自动重翻译、重评分、发布或 QQ 推送既有文章。

## Decisions

### 1. 复用现有导入字段作为候选主表格式

`seed_candidates.csv` 严格使用现有 `import_terms` 字段，不新增 `racing_region`、`source_tier`、`evidence_url` 等列。地区、来源、证据 URL、繁简转换说明和候选置信度写入 `notes`，确保文件可以直接通过现有 `import_terms --dry-run` 预检。

替代方案是新增更丰富的 CSV schema，再写转换器导入正式术语。该方案表达能力更强，但第一版会增加审核和导入链路复杂度，也更容易绕开当前已验证的导入校验。

### 2. 冲突文件与候选文件分离

`seed_conflicts.csv` 不要求兼容 `import_terms`，用于记录同一实体在 HKJC 与 WP Stud 中的译名冲突、别名候选和推荐处理。这样主候选表保持干净可导入，复杂判断留给人工审核。

### 3. HKJC 优先，WP Stud 作为补充与佐证

同一实体同时命中 HKJC 和 WP Stud 时，HKJC 译名作为 `target_zh`，WP Stud 译名进入 `aliases_zh` 或 `notes`。只有 WP Stud 有译名时，可以生成主译名候选，但必须在 `notes` 标明 `source_tier=community` 和 `requires_review=true`。

### 4. 多语言原文以多行候选表达

现有导入格式每行只有一个 `source_language`，因此同一概念如果同时有英文名和繁体中文名，可生成多行候选。例如英文原文行使用 `source_language=en`，繁体中文原文行使用 `source_language=zh-hant`，两行都输出同一个简体 `target_zh`，并在 `notes` 里互相记录对方原文。

### 5. 繁简转换封装为服务层能力

实现应提供小型转换函数，例如 `to_simplified_chinese(text)`。现有依赖没有可靠繁简转换库；若实施阶段引入轻量 Python 依赖，必须同步更新 `requirements.txt`、在测试环境验证导入，并用测试覆盖常见香港赛马译名、全角标点和非中文英文名不被破坏。原始繁体证据必须保存在 `notes` 或 `seed_conflicts.csv` 中。不得用未经测试的大面积手写映射作为唯一转换依据。

### 6. 触网命令必须低频且默认不写库

新增管理命令应支持 `--allow-network`、`--source`、`--region`、`--limit-pages`、`--max-requests`、`--request-interval-seconds`、`--timeout-seconds`、`--output-dir` 等参数。未传 `--allow-network` 时只允许使用 fixture、缓存文件或本地输入；任何模式下默认只写输出文件，不写正式数据库。默认输出目录为 `runtime/termbase_seed/<timestamp>/`，并生成请求/来源摘要，记录 URL、状态码、失败原因、请求数量和结果是否完整。

### 7. 实施前先固定真实来源入口

HKJC 与 WP Stud 的具体页面入口、可抓取字段和选择器必须先通过小型 source discovery/spike 确认，并把固定 URL、样本 HTML 或本地 fixture 记录到实现文档或测试 fixture。若某个来源返回 403、429、结构不可解析或字段不足，该来源在本轮应标记为不完整并写入摘要，不应阻塞其他来源生成候选。

### 8. 初始优先级规则保持保守

首批候选优先级使用固定、可解释的规则：HKJC 主译名候选默认 `priority=100`；只有 WP Stud 的民间候选默认 `priority=80` 且必须 `requires_review=true`；同一概念存在 HKJC 与 WP Stud 时仍以 HKJC 主译名优先级为准，WP Stud 进入别名或备注。后续人工审核可在导入前调整重点赛事、知名马匹或热点人物的优先级。

## Risks / Trade-offs

- [Risk] HKJC 页面结构变化或 PDF 格式多样，解析容易不稳定。 → 第一版先实现最稳定的网页/文本入口，并用 fixture 锁定样本；PDF 与 racecards 全量抽取只记录为后续任务。
- [Risk] WP Stud 民间译名与 HKJC 官方译名冲突。 → HKJC 优先，冲突进入 `seed_conflicts.csv`，WP Stud 只作为别名或佐证。
- [Risk] 繁简转换误改专名。 → 保留原始繁体证据，并为关键香港马名、赛事名、骑师/练马师名建立转换测试。
- [Risk] `notes` 承载来源元数据会变长。 → 第一版接受该 trade-off，以换取与现有导入器严格兼容；后续如审核量变大，再考虑独立 seed model 或富格式审核 UI。
- [Risk] 候选文件被误当成已审核正式术语直接导入。 → 文件名和文档必须标明 `seed` 与 `requires_review`，默认输出到独立目录，并要求先执行 `import_terms --dry-run` 和人工抽检。

## Migration Plan

本变更不需要数据库迁移。部署后可在本地或生产容器中执行种子准备命令生成 CSV 文件；人工审核通过后，仍按现有术语导入流程备份、dry-run、正式导入和抽样验证。

回滚方式是删除或忽略生成的 seed 文件；由于命令不写正式表，不需要数据库回滚。

## Deferred Questions

- HKJC `racecards` PDF、排位表和赛果 PDF 的结构化抽取留到种子文件首轮审核后再评估。
- 是否为香港国际赛、G1 赛事、知名马匹额外加权，留到人工审核第一批候选质量后再调整。
