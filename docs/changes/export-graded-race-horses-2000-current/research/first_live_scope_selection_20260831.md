# 首个 live TRA scope 选择

## 结论

event 956 明确释放共享赛事窗口后，首个执行 scope 固定为 stable-ID enrichment ordinal 1：France 2023，
5 个已验证 `hrs_*`，G3 request ceiling 1,035。pre-2005 targeted 与 2005+ bulk 保留为后续候选，不与首批
并发，也不生成并行 proof。

当前权威选择 artifact：

`/Users/mentianlu/.codex/umanews-first-live-scope-selection-v2-20260831`

- `selection.json` SHA-256：`366dde54f87dc263474098b7580b637e9c5cae565ecb94430d279defca11e0a6`；
- `COMPLETE` 精确等于上述 SHA；两文件权限均为 `0600`；
- v2 内嵌 selected plan/G3/ledger/lock/seed/OpenAPI/output/budget 的绝对路径、SHA 与全部运行参数；
- artifact 固定 network、fresh-proof、database-write authority 全为 false，只锁定执行顺序。

v1 SHA `31d3b6ee…836b` 保留为历史 selection 与三候选选择依据，但已由 v2 的
`supersedes_selection_sha256` 明确取代，不再作为现场执行入口。

## 选择依据

stable-ID France 2023 在三个候选中 seed 数最少，5 匹马已具有 provider stable ID，不调用 horse search，
并直接验证最终目标所需的 profile、父母 profile 与 full career 采集链。1,035 是每马最多 201 results pages 的
fail-closed protocol ceiling，不是预计消耗；页数、total 或 payload identity 漂移仍会 safe-stop。

两个未选择的候选保持原身份：

| scope | batch | count | ceiling | endpoint |
| --- | --- | ---: | ---: | --- |
| pre-2005 targeted | France 2000 | 20 anchors | 320 | search/results/profile/fallback |
| 2005+ bulk | France 2005–2007 | 105 targets | 603 | bulk results |

## 放行后的唯一顺序

1. 重新读取 event owner 明确的 safe-window revision，确认 lock absent、Beat 可暂停与 registry identity；
2. 对 selected stable scope 的现场 bytes 重跑只读 preflight；
3. preflight 必须继续为 5 seeds / 1,035 GET / zero-search，ledger/lock/output/budget 无漂移；
4. 只为 selected scope 生成 fresh 双主机 exclusive proof；
5. 立即启动 runner，由 runner 自 claim；不为两个 alternatives 生成 proof；
6. COMPLETE 后物化 5 匹 profile/parents/full-career，运行 identity/module review，再决定下一 ordinal。

该 artifact 不改变 event 956、生产 registry、Beat、`race_live=7543`、账号 limiter 或数据库状态。

## 单命令现场审计

工具：`runtime/research/audit_selected_first_live_scope.py`。现场只需传 selection root 与 SHA：

```bash
PYTHONPATH=runtime/research:server .venv/bin/python \
  runtime/research/audit_selected_first_live_scope.py \
  --selection-root /Users/mentianlu/.codex/umanews-first-live-scope-selection-v2-20260831 \
  --selection-sha256 366dde54f87dc263474098b7580b637e9c5cae565ecb94430d279defca11e0a6
```

真实运行返回 `ready_for_event_release_and_fresh_proof`，并逐项确认 selected batch 为 France 2023 / 5 seeds /
1,035 GET / zero-search，ledger/lock SHA 为 `573f2ac1…9840 / e3b0c442…b855`，output/budget absent。

auditor 严格拒绝重复 JSON key、NaN/Infinity、布尔冒充整数、marker/SHA、absolute path、G3 projection 或
ledger/lock 漂移。它不读取 credential/proof、不 claim、不联网、不写数据库。专项 `3/3`，完整 research
`539/539`。

## COMPLETE 后处理边界

selected batch 完成后不直接写 External staging。先用现有 materializer 全量展开 5 个单马 run，再运行
`prepare_selected_batch_postprocess_plan.py`。后者要求：

- execution ledger 最新 completion 正是 selected France 2023，且 `active=null`；
- batch manifest/COMPLETE 与 ledger receipt SHA 一致；
- materialization 5/5 覆盖 batch completed seed set，`hrs_*` 唯一，逐马 v1 run manifest/COMPLETE 精确匹配；
- future work 与 plan output 是新的绝对私有空路径。

输出逐马 diagnostic staging dry-run、完整 materialization 的原子 batch apply、candidate batch、全量 identity
census 与待补 exact candidate-batch SHA 的 identity/module-review handoff。状态固定
`PREPARED_NOT_AUTHORIZED`，所有写入批准为 false；它既不连数据库也不访问网络。batch staging 会在真实写窗口先
全量 dry-run，再以一个外层事务 apply；
后段失败回滚当前批新写，成功 receipt 可逐项 replay。candidate batch 只有全体 review-required/zero-blocker 才
允许 identity/module 两类 `prepare-batch`；重复 stable ID、blocked 日港 crosswalk、member SHA drift 或 batch 与
individual 参数混用均停止。专项 `3/3`，相邻 staging/candidate/identity/module 链 `90/90`，完整 research
`547/547`。

## 2026-08-31 实际执行与后处理结果

- 正确 fresh proof SHA 为 `491c422cded30442b3e9fbd9ad8a1f7d4a5340022de992322c5fbe9170486d38`；
  account scope 精确绑定 proposal SHA `bae59c28…f201`，不能使用 G3 approval SHA 代替。
- batch `0001-france-2023-01` 于 `2026-08-31T11:27:50Z` COMPLETE：5/5 seeds、19 GET、0 search、
  0 database writes，manifest/COMPLETE SHA `ed0295d95097908aef507b2c59b1da6e571586c48b5e00d4d48f63d94ddf7973`。
- execution ledger 当前 `active=null`、ordinal 1 completed，SHA `aa3d51d4…3095`；全量 materialization SHA
  `f7a1fa5e…51b99`，postprocess plan SHA `90d5613f…e2f61`。
- postprocess 状态仍为 `PREPARED_NOT_AUTHORIZED / network=0 / database_writes=0`；staging apply 与后续审核/
  canonical/public 门禁没有因首批 COMPLETE 自动获批。
