## Context

当前英文术语门禁位于 `server/stable/services/validation.py` 的 `validate_rewrite()`。流程会读取 active `TermEntry`，用 `source_terms_by_entry()` 按来源语言生成候选词，若原文命中但中文发布稿未保留正式中文译名或 alias，则调用 `_is_core_term()` 判断是否生成 `core_term_missing` blocker。`_is_core_term()` 目前包含 `priority >= 80` 直接核心的规则，因此高优先级马名词库中的普通英文词会被硬阻断。

已上线的英文特殊规则解决了两类误挡：跨地区英文术语会变成 `term_region_excluded`，配置化高歧义词会变成 `ambiguous_term_downgraded` warning。但这仍是词表级规则，不能区分 `Tuesday` 本次是“周二”还是马名、`GOOD JOB` 本次是普通短语还是香港马名。7 月 1 日以来的海外候选池复核显示，普通英文词放行后，旧 `core_term_missing` 层面预计可新增清掉 `13` 篇；真实专名仍会阻断 `39` 篇。

## Goals / Non-Goals

**Goals:**

- 在英文术语门禁中按命中上下文区分普通英文词和真实专有名词。
- 普通英文词高置信命中不再生成 blocker，真实专有名词继续沿用当前 `core_term_missing` 逻辑。
- 不确定命中保持保守，继续人工审核或 blocker，不自动放行。
- 所有降级或保留 blocker 的判断都写入结构化 payload，便于后台、审计命令和生产复核解释。
- 提供优化版重校验能力，对目标地区和时间窗内旧 `core_term_missing` 文章输出完整 dry-run。

**Non-Goals:**

- 不重构正式术语库模型，不新增术语分类字段作为本轮硬依赖。
- 不直接修改文章中文内容，不重新翻译，不自动公开发布文章。
- 不把所有英文普通词都永久加入全局白名单；本轮关注“本次命中上下文”的判定。
- 不改变日本日文新闻的术语门禁逻辑。

## Decisions

1. 在 `validate_rewrite()` 内、`_term_preserved()` 缺失后和生成 `core_term_missing` 前插入语义判定。

   理由：这是信息最完整的位置，已经知道 article、source text、publish text、entry、source terms、核心位置和地区过滤结果。若放在事后重处理命令中，只能修旧数据，不能阻止新误挡。

   备选方案：只扩展 `MULTIREGION_TERM_GATE_AMBIGUOUS_ENGLISH_TERMS`。该方案实现快，但会把 `Tuesday / GOOD JOB / Fast Track` 这类可能既是普通词又是马名的词按全局词表放行，误放风险更高。

2. 采用“确定性规则优先 + 可选结构化分类器兜底”的两段式判断。

   确定性规则用于稳定识别：

   - 明显专有名词：`race / jockey / trainer` 类型、多词首字母大写人名、数字赛名、`Prix / Stakes / Derby / Cup / Guineas / Futurity / Classic` 等赛事结构。
   - 明显普通词：单词或短语命中普通词表、功能词、页面字段词、日期词，且未出现在强赛马专名上下文中。

   无法确定且即将成为 blocker 的命中，再进入分类器。分类器输出只接受结构化 JSON：`classification`、`confidence`、`reason`、`suggested_translation`。实现可以先提供规则分类器接口，后续再接 LLM；生产默认必须保守。

3. 分类结果影响 issue severity，但不影响术语库数据。

   - `common_word` 且置信度达到阈值：生成 warning/info，例如 `english_term_common_word_downgraded`，不生成 blocker。
   - `proper_noun`：继续生成当前 `core_term_missing` blocker。
   - `uncertain` 或低置信：继续生成 blocker 或转人工，payload 中记录不确定原因。

   这样可以保证新规则只改变“本次门禁处理”，不把临时判断写回 `TermEntry`，避免污染正式术语库。

4. 重校验命令需要预加载术语和 alias，并先收窄候选集。

   现有 `reprocess_term_gate_blocked_articles` 会先扫描地区历史 `manual_review_required` 积压，再逐篇完整调用 `validate_rewrite()`，在生产交互执行中过慢。新实现应先按时间窗、地区、automation 状态、workflow 终态和 `gate_issues` 中是否存在 `core_term_missing` 过滤；术语和 alias 应批量加载或在校验上下文中复用，输出完整 blocker/warning，而不是只做旧 blocker 轻量分类。

5. 普通词判定需要有可审计的种子来源和可回归的批次验收。

   第一版普通词表应来自本次已审核的 `still_potential_core_terms_breakdown_classified.csv` 中 `普通英文词` 集合，并以代码常量或 settings 默认值形式进入判定逻辑；后续新增词必须能通过配置或代码 review 扩展，不能隐式依赖聊天记录。生产上线前，必须用 7 月 1 日以来四地区旧 `core_term_missing` 候选做完整 dry-run，对比当前投影：普通词相关旧 blocker 至少应新增清掉 `13` 篇，且真实专名阻断不应减少为误放行。

## Risks / Trade-offs

- [真实马名被误判为普通词] -> 默认只对高置信 `common_word` 降级；不确定命中保持 blocker；测试覆盖 `GOOD JOB / Tuesday / Fast Track` 等可双关词。
- [分类器引入成本和不稳定性] -> 第一版先实现确定性规则和接口；LLM 分类通过开关控制，失败或超时按 `uncertain` 处理。
- [门禁 payload 变复杂] -> 统一 payload 字段：`term_semantic_classification`、`confidence`、`classification_reason`、`matched_text`、`matched_context`、`position`、`term_id`。
- [生产重处理误写状态] -> dry-run 默认，不写库；commit 只调用既有 `apply_validation_outcome()`，只把完整校验通过的文章恢复到可发布候选，不直接公开发布。
- [性能回退] -> 只对英文来源、命中且未保留、即将生成 blocker 的术语做分类；确定性规则应为纯本地函数；重校验命令必须提供 limit/region/hours/source 过滤。
- [普通词表来源漂移] -> 种子词必须来自仓库内审核 artifact 或明确配置，新增/删除词通过测试和 dry-run 结果复核，不把临时人工判断藏在代码外。
