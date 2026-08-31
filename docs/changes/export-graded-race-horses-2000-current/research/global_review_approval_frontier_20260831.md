# 全局 proposal→approval→binding 审批前沿

日期：2026-08-31

## 缺口

postprocess frontier 原先能把 COMPLETE enrichment batch 串到 materialization、candidate、identity proposal 与 module
proposal，但终态名称 `ready_for_global_review_aggregation` 容易被误解为两类 approval 已齐。automatic binding producer
又正确要求 approval parents 全量齐套；两者之间缺少可重放、可续跑的逐批审核状态机。

## 实现

`audit_global_stable_id_review_approval_readiness.py` 先重放原 postprocess frontier，再读取专用 identity/module
approval parents：

1. approval child 名必须属于已经完整验证的 proposal batch IDs，并分别形成连续前缀；
2. 已完成 proposal prefix 可以在后续网络/materialization 批次仍等待时进入人工审核；
3. identity 缺失时输出 exact proposal/rows/decision-template SHA、reviewer decisions 要求与 publisher argv；
4. identity exact 而 module 缺失时输出 exact module rows、四模块/source-record authority 核对要求与 publisher argv；
5. 两类 handoff 均为 `REVIEW_REQUIRED_NOT_APPROVED`，`automatic_publish_authorized=false`；
6. 已存在 approval 会调用 binding producer 的严格 loader，重新验证 member、marker、proposal、decision 与 horse set；
7. 只有全部 planned batches 双 approval 齐套，才返回唯一 automatic binding argv。

identity handoff 同时生成逐马 cohort，不改变推荐动作：

- `verified_provider_identity_reconfirmation`：已有 verified provider ID，只做 exact snapshot 复核；
- `official_crosswalk_review` / `official_local_crosswalk_review`：核对官方或本地官方 crosswalk；
- `strong_biodata_review`：核对 birth date、sex、sire、dam 四字段强匹配；
- `observed_provider_identity_review`：observed ID 仍未 verified；
- `new_profile_cross_language_duplicate_review`：create-new 前必须跨语言防重；
- `ambiguous_or_blocked_identity_review`：冲突、拒绝或资料不足，不能绑定。

所有 cohort 都固定 `manual_review_required=true / automatic_approval_allowed=false`。classifier 会重算 proposal row
SHA，并要求 template 的 ordinal/provider/row SHA/action/profile/default review fields 与 proposal 完全相等；不能通过改
template 把 blocked/create-new 静默变成 bind。

automatic binding 的授权范围仅为
`LOCAL_IMMUTABLE_BINDING_ARTIFACT_ONLY_NO_NETWORK_OR_DATABASE_WRITE`。它可以在 exact approvals 已经存在后自动执行，
但不授予 identity apply、production apply、public fetch、publish 或任何生产 maintenance 权限。

## 状态

- `review_proposals_incomplete`：尚无可审核 proposal；
- `identity_approval_required`：下一批需人工 identity decisions；
- `module_approval_required`：下一批需人工四模块审核；
- `waiting_for_more_review_proposals`：当前 proposal prefix 已全部双审，后续 proposal 尚未齐；
- `ready_for_automatic_batch_binding`：全量双审批 exact，可生成本地 binding artifact。

任何 orphan/extra/跳批 approval、proposal SHA、decision、member、horse-set 或 loader 漂移均 safe-stop，且 auditor
自身不创建目录或文件。

## 验证与真实零状态

- 专项 `9/9`：覆盖零状态、orphan、proposal prefix 流水线、identity→module handoff、全量 binding argv、loader drift、
  七个 cohort 与 template-action drift；
- 现有 13 马 plan manifest/rows SHA：`51eccdcc…fc230 / 20f09958…0b137`；
- execution ledger SHA：`573f2ac1…d9840`；
- 真实结果：`review_proposals_incomplete`，upstream `waiting_for_enrichment_completion`，3 planned、0 proposal、
  0 identity approval、0 module approval、0 output；全部 authority false；
- 临时六类 parent 与 binding output 顶层成员为 0，演练后撤除；无 proof、claim、网络、DB 或生产写。
