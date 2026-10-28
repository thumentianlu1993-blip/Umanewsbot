# 全量 CI 的既有环境覆盖缺口

2026-10-28 远端 run `40666270552` 执行6978项/49片，出现190条失败和以下10项skip。190条失败的集成修复另行记录；这10项的允许跳过策略与当前 main 完全一致，`review_by=2026-10-16`，已过期。验证器明确拒绝过期skip，不得自动延期、删测试或换成伪造样本。

## 实际缺口

| 用例 | 原因 |
|---|---|
| `stable.test_historical_race_detail_direct_urls.HistoricalRaceDetailDirectUrlTests.test_sporting_life_real_cache_preserves_structured_non_finish_statuses` | Sporting Life real cache root not configured |
| `stable.test_historical_race_detail_distance_metadata.HistoricalRaceDetailDistanceMetadataRealCacheTests.test_equibase_yearbook_result_preserves_distance_unit` | real cache root not configured |
| `stable.test_historical_race_detail_distance_metadata.HistoricalRaceDetailDistanceMetadataRealCacheTests.test_jra_2005_legacy_page_preserves_distance_unit` | real cache root not configured |
| `stable.test_historical_race_detail_distance_metadata.HistoricalRaceDetailDistanceMetadataRealCacheTests.test_sporting_life_race_118984_preserves_distance_units` | real cache root not configured |
| `stable.test_historical_race_detail_runner_v2_package_identity.HistoricalRaceDetailRunnerV2PackageIdentityRealSmokeTests.test_empty_event_distance_uses_real_parsed_metadata_with_original_units` | real cache root not configured |
| `stable.test_historical_race_detail_runner_v2_package_identity.HistoricalRaceDetailRunnerV2PackageIdentityRealSmokeTests.test_hk_package_rejects_raw_candidate_without_validation_evidence` | real cache root not configured |
| `stable.test_historical_race_detail_runner_v2_package_identity.HistoricalRaceDetailRunnerV2PackageIdentityRealSmokeTests.test_hk_real_validated_candidate_packages_with_plan_inventory_identity` | real cache root not configured |
| `stable.test_historical_race_detail_runner_v2_package_identity.HistoricalRaceDetailRunnerV2PackageIdentityRealSmokeTests.test_nonempty_event_and_parsed_distance_conflict_becomes_validation_gap` | real cache root not configured |
| `stable.test_race_live_gate_remediation.RollbackGateBehaviorRemediationTests.test_root_artifact_is_exact_0700_0600_secret_free_and_no_replace` | root-owned artifact contract requires root EUID |
| `stable.test_migration_history_repair.MigrationHistoryRepairDockerImageContractTests.test_candidate_image_contains_only_the_exact_reviewed_audit_file` | set RUN_MIGRATION_REPAIR_DOCKER_CONTRACT=true for the real image contract |

## 建议的下一项独立工作

1. 为8个历史来源测试补齐有来源和摘要的真实缓存夹具（优先复用已保存、许可适用的缓存）；冻结脱敏/裁剪规则并让CI离线执行，不能拿合成内容冒充真实缓存。
2. 为1个root文件归属合同提供独立、禁网、无宿主socket/敏感挂载的测试环境，仅运行该合同；现有非root容器约束不静默放宽。
3. 为1个真实镜像合同提供绑定候选镜像digest的独立执行路径；当前测试容器明确禁止嵌套Docker，不能假装已测真实镜像。
4. 独立审核这些测试基础设施变更；10项实际执行成功后移除对应skip豁免，再运行固定候选的完整CI。

这会从P02业务移植扩展到仓库通用测试环境与执行身份设计，应在继续该新增范围前按根 [AGENTS.md](../../../AGENTS.md) 判断G1。此文件只是具体方案，不授权改变CI运行身份、开放网络或新增生产权限。

在环境缺口解决前，保持Draft，不合并、不部署，也不将本地定向测试或CI执行完成等同于完整验收通过。
