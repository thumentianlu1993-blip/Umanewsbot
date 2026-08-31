# 全局 stable-ID enrichment plan frontier

## 目的

`audit_global_stable_id_enrichment_plan_readiness.py` 关闭 coverage COMPLETE 到全量零 search planner 之间的最后
一段手工参数风险。它是只读门禁，不联网、不写数据库、不创建输出目录。

## 精确合同

- 重新运行 bulk 32 批与 pre-2005 targeted 65 批 postprocess frontiers；两者必须全部 ready 且 inactive；
- merged v2 manifest 的 97 个 source root/SHA 必须与上述 frontiers 精确相等；
- coverage root/SHA 必须 COMPLETE，逐 occurrence 覆盖 merged ledger，无 overlap/gap；
- component set 必须恰为 32 个 `provider_native_bulk_run` 与 65 个
  `provider_native_targeted_materialization`，不得混入 13 马 pilot、held 或 external components；
- stable rows 必须是唯一合法 `hrs_*`，全部 occurrence key 唯一；输出参数固定 zero-search、5 马/批、最多 201
  results pages、2 个 parent profiles、至少 250ms、批间至少 30 分钟。

只有全部条件成立才返回 `ready_for_exact_global_zero_search_enrichment_plan` 和唯一
`global_enrichment_plan_argv`。该 argv 生成的仍是 `PROPOSED_NOT_APPROVED` plan，不授权 fresh proof、网络、staging
或 production apply。

## 真实等待态证据

- bulk execution ledger：0/32，SHA `6c83d21a29004b3ec40fb3d060b4701f17fe3cc109a7b8a9adda812f87261c47`；
- targeted execution ledger：0/65，SHA `8f9d51cc9dc81eaec1f0b72b307ed6dbe9d96157230e0a4d2efd0524afc6a50d`；
- 真实 CLI：exit 75，`safe-stop: authoritative source partitions are not globally merge-ready`；
- `/Users/mentianlu/.codex/umanews-global-stable-merged-v1-20260831`、
  `/Users/mentianlu/.codex/umanews-global-stable-coverage-v1-20260831`、
  `/Users/mentianlu/.codex/umanews-global-stable-enrichment-plan-v1-20260831` 均 absent；
- 本轮未 acquire shared lock、未停 Beat、未读取生产凭据、未访问 TRA、未写数据库或 registry。

## 验证

- 新门禁与 coverage refactor 聚焦：`2/2`；
- 合成相关链（含后续多批 review frontier）：`28/28`；
- 完整 `runtime/research`：`558/558`；
- change test case IDs：`300/300` 唯一；
- `py_compile` 与 `git diff --check` 通过。
