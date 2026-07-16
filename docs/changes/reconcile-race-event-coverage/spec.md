# 赛事总账与公开赛程关联规格

## 目标

修复历史正式目标、2025 年以后公开赛程和到期赛果三个统计层互相混用的问题，并在不创建或删除赛事、不改变公开状态的前提下，把身份唯一的 `HistoricalRaceEventTarget` 与既有 `RaceEvent` 关联。

## 范围

- 历史层：截至 2024 年的正式目标。
- 当前层：2025 年以后正式总账目标；展示扩展赛事不进入正式分母。
- 赛果层：已到期、实际举办且不处于取消或延期状态的正式目标。
- 本期只做既有目标与既有赛事的关联、分层报告和受控生产修复。
- 本期不创建新的未来 `RaceEvent`，不删除或合并赛事，不改变 `visibility_status`，不启动准实时抓取。

## 状态语义

- `not_due` 表示尚未进入赛果验收期，可以关联既有 `scheduled` 或 `postponed` 赛事。
- `not_due` 不得转换为 `imported`，历史物化器不得为它创建赛事。
- 关联本身不改变目标的 expectation/resolution，也不改变赛事状态、数据质量和公开状态。
- `not_held` 不得关联赛事。

## 身份匹配

1. 强匹配仅使用同一 `race_series` 和同一官方届次 `year` 的唯一赛事。
2. 采用前必须核对目标、赛事和系列的地区、年份一致。
3. 名称仅用于发现冲突，不作为自动关联依据。
4. 同名异系列、一对多、多对一、状态不兼容均只进入冲突清单。
5. 所有候选必须绑定目标和赛事身份 SHA-256。

## 报告分母

- `historical`：`year <= 2024` 的全部正式目标。
- `current`：`year >= 2025` 的全部正式目标。
- `result`：已超过赛事预计结束时间及宽限期，且赛事不是 `cancelled/postponed` 的已关联正式目标；历史和当前已到期目标均可进入。
- 完整赛果要求赛事为 `finished`、目标已 `imported`、`module_statuses.results=complete`、`result_confirmed_at` 非空、结果非空且全部 `is_confirmed=true`；缺少任一显式证据的旧数据均按部分或待核验处理，不能默认完整。
- 报告必须按地区、年代层和 coverage tier 可拆分，并保持每层数量守恒。

## 验收

- dry-run 分类至少包含 `exact_link`、`already_linked`、`missing_event`、`identity_conflict`、`status_conflict`。
- apply 只处理 manifest 中的 `exact_link`，重复执行幂等。
- apply 还必须校验绑定精确 manifest SHA 的独立 `approval.json` 及其 SHA；审批状态、审批人或审批时间缺失时拒绝写入。
- verifier 证明目标数、赛事数、公开状态、赛事状态和详情行数守恒。
- 每条写入产生 `OperationLog`，回滚账本保存旧 `event_id` 与写后身份。
- 东海锦标 2026 的正式目标应采用现有公开赛程，金鯱赏不得被误关联。
