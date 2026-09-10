# Full-cohort 查询数测试的固定时间

## 原因与最小修复

`FullCohortRuntimeContracts.test_single_event_membership_validation_is_constant_query_count`
验证 1、201、1001 个成员时的单赛事查询数；夹具授权有效期固定到 2026-09-10 00:00 UTC，
却没有给运行校验传入已有的 `now` 参数。过期后先在 `result.valid` 失败，无法验证查询数。

仅在该调用增加 `now=datetime(2026, 8, 12, tzinfo=timezone.utc)`，与夹具赛事日期一致。
全部 cohort 大小、最多 6 次查询、增长不超过 1 次、禁止 `IN` 查询及原有断言保留。
没有修改应用的到期判断，没有延长授权或冻结全局时钟。

## 实际验证

- #194/#195/#196 的 Linux/PostgreSQL 全量均复现此失败；测试与应用校验服务的 blob
  在这些候选及基线中相同。此前隔离原样执行旧测试：到期前通过，到期瞬间以
  `registry_runtime_expired` 失败。原始证据保存在本机 `runtime/fix-m2-local-start-time/`。
- 修复后的原 `FullCohortRuntimeContracts` 两项测试在隔离 SQLite、禁网环境全部通过，
  5.096 秒、零跳过；包括原查询数测试和退休 registry 不能认领测试。
- `git diff --check` 通过。基线已有五处工作流文档引用和一条契约错误由 #186 独立处理；
  本修复不改检查器。独立只读审核及固定候选 Linux/PG 验证在提交后分别记录实际结果。

此候选仅修改测试与本验证文档，不涉及应用、迁移、配置、开关或生产数据。
不包含优先交付的 #194，也不能替代 M2 自然正式赛果与 correction 验收。
