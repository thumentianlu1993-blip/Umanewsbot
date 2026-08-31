# 分级目标来源冲突审核提案

提案日期：`2026-08-29`

## 状态

`PROPOSED_NOT_APPROVED`

本文件是给独立审核人使用的逐项结论和证据索引，不是可执行审批。不得把本文件改名、转换为
`status=approved` 或填写虚构审核人后用于发布 `COMPLETE` target ledger。

已另生成机器可读但不可执行的审核包：

- root：`/Users/mentianlu/.codex/umanews-source-conflict-review-proposal-20260829`
- package manifest SHA-256：
  `a44b8bbd19b9e298e2288c1dd6c9f6801197171afe84222513e2677d9e24b08e`
- proposal SHA-256：
  `c1d62b529e423b5498787a9ac12eb9f3332426aa580d579012cf1f39c3a129d3`
- evidence：10 files / 37,686,403 bytes，逐一验证 path、size、SHA、HTTPS URL；全部已从 `/tmp`
  冻结到上述持久目录
- 状态：`PROPOSED_NOT_APPROVED / approval=false / reviewed_by="" / reviewed_at=""`

仅在临时内存副本中把 reviewer 标为 `SIMULATION_ONLY_NOT_A_REVIEW` 后运行结构验证，确认 9 个 conflict
key 全覆盖、预计编译 12,048 行、两届 Abbaye/2023 Dueling Grounds Derby 增加、Hollywood Futurity/
2026 Penelope 删除、2022 Bed o' Roses 改 G2。临时副本已销毁，不能作为人工审核完成证据。

## 绑定范围

- scope policy：`actual_held_races_only`
- blocker payload SHA-256：
  `dedf39dff4fb4a342dd3737fa7d096e7c9d641598dd5847ec7f5558e9495d9d1`
- blocker keys：
  - `2000:france:flat`
  - `2000:united_states:flat`
  - `2001:france:flat`
  - `2008:united_states:flat`
  - `2022:united_states:flat`
  - `2023:united_states:flat`
  - `2025:france:flat`
  - `2026:france:flat`
  - `2026:united_states:flat`

如果新的 parser/source cache 产生不同 blocker SHA 或 key 集合，本提案整体失效，必须重新生成。

## 建议决议

1. `2000:france:flat`：补入 Prix de l'Abbaye G1；evidence 为 France Galop Abbaye history 与
   Namid page。
2. `2000:united_states:flat`：接受 parsed held scope；TOBA history 的实际举行 G1 为 96，不能按
   计划摘要补造两场。
3. `2001:france:flat`：补入 Prix de l'Abbaye G1；evidence 为 France Galop Abbaye history。
4. `2008:united_states:flat`：删除 `Hollywood Futurity` 重复别名，保留 `CashCall Futurity`；
   `Frank J. De Francis Memorial Dash` 在 occurrence 阶段标记 `not_run`，不获取 starters。
5. `2022:united_states:flat`：把 `Bed o' Roses S` 从 G3 改为 G2。
6. `2023:united_states:flat`：补入 `National Thoroughbred League Dueling Grounds Derby` G3。
7. `2025:france:flat`：接受 parser 的 28/23/63 明细，France Galop programme 与其完全一致。
8. `2026:france:flat`：删除 `Penelope` G3。
9. `2026:united_states:flat`：接受 parsed held scope；TOBA 多出的未举行 G3 不进入实际参赛马分母。

预期 series/year inventory 行数：`12,048`。该数字不是 held occurrence 数，也不是预计 TRA
请求数。

## 独立审核人必须核对

- 逐个打开官方 URL，确认内容与冻结 SHA 对应且确实支持建议结论；
- 检查 2008 CashCall/Hollywood 是否为同一 occurrence，不是两个实际场次；
- 检查 2008 Frank J. De Francis、2026 Cougar II/Californian 的 `not_run` 证据；
- 检查 2022 Bed o' Roses 的当届等级和 2023 Dueling Grounds Derby 的日期、等级；
- 检查 France Galop 2025/2026 programme 的逐行计数，而非只看摘要；
- 确认 target review 只修正 series inventory，另由 occurrence ledger 处理同系列一年多次举行、
  取消和未来未举行。

审核完成后应另建 JSON，满足
`graded-horse-source-conflict-review.v1`：精确绑定 evidence path/SHA/size/URL、全部 9 个
resolution、`reviewed_by` 和带时区 `reviewed_at`。审批 JSON 不应引用 `/tmp` 临时路径；正式证据
必须先冻结到不可变、可重放的 artifact 根目录。
