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

## 2026-10-29 已确认的实施范围

用户明确同意将上述10项纳入第1项。最新旧候选CI `40677898864` 已完成6978项/49片，failure/error均为0，仍有10项过期skip，最终验证失败。此处不宣称完整CI通过。

- 缓存：从本地已保存的v3 smoke及Sporting Life v8原始缓存提取7份页面及必要的4场描述/事件/已验证候选；保持页面原始字节，登记URL、原始与打包哈希。仅重定位本地路径，离线运行原8项断言。无新抓取。
- 身份：收集器为两个精确测试ID分配专用profile，禁止模块/类通配扩大特权。其他ID仍走原有非root环境；验证器继续检查执行集合、完整生命周期和零skip。
- root合同：专用容器仍禁网、只读根、临时数据目录、无socket；PostgreSQL以tester身份初始化，测试本身uid/gid=0。初始化所需SETUID/SETGID/CHOWN/SETPCAP在运行测试前全部丢弃，测试进程核验CapBnd/CapPrm/CapEff/CapInh/CapAmb全零及NoNewPrivs=1。只允许指定root测试ID。
- 镜像合同：宿主编排器只负责从固定git archive构建候选应用镜像并取得不可变image ID；测试在该应用镜像内以10001身份、禁网、只读根执行，不提供嵌套Docker。原有精确audit路径/唯一文件/审核内容断言移入可在镜像内运行的分支；候选revision、冻结源码和实际image ID写入证据。镜像不得用测试依赖镜像代替。
- 回归：先取得缺缓存/错误身份/错误镜像或遗漏profile的RED；补齐后跑10项、调度/隔离/验证器工具测试，再固定提交运行完整CI。删除10项过期skip豁免，不延期。
- 交付：延用同一只读reviewer复审；不修改生产、发布合同或开启业务开关。失败时保持Draft。若基础镜像构建需要包下载，仅属于现有CI构建依赖，不允许测试外网。

应用镜像worker从`/source`验证固定Git树，测试及业务代码从实际`/app/server`导入；逐文件核对镜像server内容、revision和固定源码，并将实际image ID绑定plan/report。不依赖应用镜像内git或Docker。

双镜像协议：`plan.image_id`保留依赖测试镜像；`plan.application_image_id`只绑定真实应用镜像。收集后逐batch写入`image_id`（application-image使用后者，其余使用前者）；宿主按该不可变ID启动并记录`actual_image_id`，worker报告带`image_id`，最终验证要求三者与plan匹配。任一缺失/格式错误/串用均失败。单片重跑必须已有同一应用镜像且revision=test_sha，禁止重建替换；完整导出tar同时包含两镜像。独立交付核验加载同run的tar，检查两个ID均存在、应用revision及所有batch映射，再用受信控制重新收集比较。仅收集无需构建镜像。覆盖缺失、替换、串用、残余capability的拒绝测试。

### 当前实现与阶段证据

- 已保存的7份原始页面和必要元数据共28文件（约1.87MB），见`server/stable/fixtures/ci_real_cache/manifest.json`。页面字节不变；本地路径转为明确占位符，原始/打包摘要分别保留。`.gitattributes`只对该目录的上游HTML/CFM关闭空白格式检查，页面内容仍由摘要验证。
- 精确ID分配、两种专用profile、双镜像tar和候选外核验已实现；49项工具测试及36项核心/专用身份测试通过（批次有重叠）。
- 原8项缓存断言及邻近回归共47项通过。真实应用镜像内1项合同已通过；专用root 1项已通过最终验证器，UID/GID=0、五类capability全零、NoNewPrivs=1、外网/socket不可用。
- root容器初始化复制代码时不保留宿主owner，避免引入FOWNER；保留原始文件模式和字节，并验证Git树。
- 最终同快照10项批次、镜像篡改拒绝、独立实现复审及完整CI仍待完成。阶段产物位于`/tmp/p02-ci-gaps-20261029/`，不能据此宣称最终CI通过。
