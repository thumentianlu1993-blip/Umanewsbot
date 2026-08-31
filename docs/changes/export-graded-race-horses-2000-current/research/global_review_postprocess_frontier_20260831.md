# 全量 enrichment review postprocess frontier

## 关闭的断点

旧 completion audit 只能消费一个 candidate batch。全量 zero-search plan 会产生多个网络批次；若靠人工枚举
materialization/candidate/proposal，可能出现跳批、orphan child、跨批重复 `hrs_*` 或 candidate 已偏离原
materialization/source run 的情况。

`audit_global_stable_id_review_postprocess_readiness.py` 以 exact plan + execution ledger 为唯一批次序列，对四个专用
parent 做只读重放：

1. materialization；
2. candidate batch；
3. identity proposal；
4. module proposal。

每层 child 名必须是 batch ID，且只能形成 COMPLETE batch IDs 的连续前缀；candidate/identity/module 不得领先上游。
每个 materialization 会重验 manifest/marker、全部 run/normalized/response identity、成员集合与计划 horse set；
candidate 会在任何 proposal 命令输出前回绑 materialization root/SHA、source batch SHA、逐马 source-run SHA 与
unique `hrs_*` union。

## 权限边界

- materialization 缺失：只给确定性 materialize argv；
- candidate 缺失：只给 staging dry-run，以及明确标为“另行授权 staging apply 后”的 candidate argv；
- identity/module 缺失：只给 proposal prepare argv；
- `ready_for_global_review_aggregation` 仍不批准 staging write、identity/module approval、reviewed release 或 production apply。

## 真实零状态重放

使用现有 France/Ireland 13 马 zero-search 计划验证通用合同：

- plan manifest/plan SHA：`51eccdcc…fc230 / 20f09958…0b137`；
- execution ledger SHA：`573f2ac1c3153f8ca086e9bc1ff1fb60102c8bb5706794483cf4405c4dbd9840`；
- 结果：`waiting_for_enrichment_completion`，3 planned batches、13 unique horses、0 completed、0 children；
- materialization/candidate/identity/module 四个 future parents 均 absent，审计后仍 absent；
- network requests/database writes/所有 authority 均为 0/false。

最终全量 plan 尚未生成；本证据只验证 frontier 的真实零状态行为，不把 13 马 pilot 当全量 denominator。

## 验证

- 新 frontier 专项 `4/4`；
- 合成相关链 `28/28`；
- 完整 `runtime/research` `558/558`；
- change test IDs `300/300` 唯一；
- `py_compile` 与 `git diff --check` 通过。
