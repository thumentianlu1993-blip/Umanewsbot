# A-002 / F01 可执行共享合同交付（代码审核与开发full通过，正式PR收据待协调）

输入方案：7c78f67d04cc156520d21916f3eb0a3ef066305e（原R APPROVED/F01-M-01 CLOSED）。
任务DDL 2026-10-04 18:00 Asia/Shanghai。当前F01未标全部完成，下游未解锁集成。
worktree `/Users/mentianlu/.codex/worktrees/5482/umanews`；branch `codex/next-version-race-data-20261003`。
代码base 907f8de6，A-002直接base为7c78f67d；固定实现head以Git及协调消息为准。

已完成：content_contracts无ORM/网络/隐式时钟DTO、严格parser/生产者serializer、私有/公开字段边界；
17项stdlib行为测试通过；新增显式测试映射。接口见[A-002-interfaces.md](A-002-interfaces.md)。
未修改writer、业务调度、schema、第三方权限策略或公开端点。

测试先行证据（运行目录 `/tmp/umanews-a002-evidence`）：

| 阶段 | 命令/观察结果 |
|---|---|
| 首轮RED | `PYTHONPATH=server python3 -m unittest stable.test_content_contracts`；3项测试6个子例ERROR，正常导入API骨架后调用parse_input抛目标NotImplementedError；无import/环境失败 |
| 首轮GREEN | 同命令3/3通过，DTO独立快照/未知与0/四组往返 |
| 严格边界RED | 同命令11项：26 fail/7 error，非法schema/字段/摘要未拒绝及build/public API缺失 |
| 严格边界GREEN | 同命令11/11通过 |
| 公开错实体RED | 同命令15项：1 failure（ContractError not raised），公开摘要错canonical未阻断 |
| 最终局部GREEN | 同命令15/15通过；无DB/Redis/网络 |

完整日志各为red.log、green-round1.log、red-round2.log、green-round2.log、red-round3.log、green-round3.log。
测试mutation目标见[test_cases.md](test_cases.md)。API骨架仅供RED导入，不包含行为；JSON文档工具不作为行为GREEN证据。
workflow contract PASS/4 tests PASS、文档fixture 4正例/5反例 PASS、diff check PASS。

影响诊断：以7c78f67d为base生成本地plan，full/247 domains/294 labels。
原因是rules/catalog映射演进，保留原base+候选完整覆盖；没有为省开销改工具选择算法/skip规则。
Linux交付：专用Colima umanews-impact-ci由协调者恢复；固定候选的一套full待运行，最多2批并发，每批<=200。
宿主GREEN只是开发证据；Linux完整集合、收尾、skip与候选外收据未取得时不得称交付测试已通过。
原R代码复审0e05029c已APPROVED、A002-P2-01/02 CLOSED；后续映射补丁单独列审。

当前额度最新每周已用93%、剩7%；无子代理/模型CLI。持续检查与用户<=1%停止约束保持。
临时异常按2s/5s最多3次有界恢复，未知写入结果先读收据，不重复派单或改生产。

首次Linux收集发现新测试未登记catalog.profiles，fail closed为unowned test；已补显式python profile（纯stdlib），不改变runner或豁免。原e9未开始执行full；新候选重新收集，旧结果仅归e9。Docker默认temp挂载问题已用本线Users下TMPDIR解决，镜像已按原Dockerfile成功构建。

原R代码review @836c9f18：A002-P2-01/02 REVISE。两项聚焦RED为2方法5个失败（动作两个副本各bool/float，公开身份状态错配）；修复后17/17宿主GREEN。动作expected_input_version复用_version，expected_generations复用严格_generations；公开kind/id/identity_state同时绑定，三种身份状态匹配正常、六种不匹配拒绝。原R限定复审待返。原e9及650未执行任何full批次，待新固定树收集。

## 最终阶段事实（2026-10-03，Asia/Shanghai）

- 实现/原R批准 SHA：`0e05029c1ed00713a6f66e461e6753c1e4dadb27`；代码已实现、审核通过。
- 开发测试base：`7c78f67d04cc156520d21916f3eb0a3ef066305e`；主线/正式PR预期base：`907f8de699b31a6fcc80acc78e9ba070aadc4f28`，不能混用。
- 原R报告：`/Users/mentianlu/.codex/worktrees/3ab1/umanews/docs/changes/next-version-capabilities/lanes/R/A-002-F01-code-rereview.md`，独立固定17测试PASS、前后指纹一致。
- 开发full：41/41批、6182精确执行、0fail/0error、10既有allowlist skip、全部生命周期complete；不是6182全部通过，应表达为6172非跳过项通过+10已批准覆盖缺口。
- 原runner固定树 `be3cee831b2359ecec7b4e946a0a3a16753d826e`；plan digest `d1dd7ec5c6c62cce97eb101327fc3d3199f2ba68600c656295b3177d505668b3`。
- Linux运行时 `sha256:fcf8cdaf63af51b1b8a6e30e3d2fdf871d127c3c1461bfd00c9fc6d610eab905`；原Dockerfile构建，Git源固定archive；无外网/non-root/无宿主Docker socket。
- 候选外测试集合核验：从可信907f提取verify_test_plan.py/core.py，`python -I`执行PASS，完整ID/同树/profile/skip理由与期限/收尾一致。
- 原始分片与log：`/tmp/umanews-a002-evidence/linux-full-0e05029c`；独立扁平核验目录`/tmp/umanews-a002-evidence/verification-reports-0e05029c`；summary.json和execution-plan.json保存完整证据。
- 最初汇总的重复分片来自原子目录及复制副本同时被rglob读取；改用独立扁平目录后核验通过，未重跑测试、改报告内容或放宽skip。
- 测试窗口已交还协调者/C线，A无在途container/子代理/模型CLI；没有因修映射再启动第二full。

### 真实主线范围与映射增量

907f→0e只读静态plan因9个继承/本线JSON unmapped而fail closed，日志`/tmp/umanews-a002-evidence/main-plan-diagnostic.log`。
已消费原R批准共享映射源`c9c798ac6190c1ad3f6ed8abb804b453641bc507`为本线`2ace4fc3109d118701c630f230e22127f5c26198`，保护content_contracts映射/profile，无catalog覆盖。
907f→2ace剩两个本线JSON，必要修复如下（待协调者/原R限定映射审核）：

- F01-contract-examples.json由新行为测试实际读取，精确映射content_contracts领域，不能当docs-only跳过行为测试。
- F01-validation.json仅文档校验结果，不作为runtime/fixture读取，精确docs白名单；没有扩大JSON通配或豁免。

新正式base静态plan固定提交后生成并回协调者；其full选择是计划，不能称新树已运行full。
原0e开发证据只归原树；此后只有规则/报告增量，代码源仍为原R批准0e。最终组合/实际main PR计划及必要验证由协调者组织。

### 正式候选外PR收据尚缺

verify_delivery_test_evidence.py要求真实GitHub PR/run、pull_request事件、运行步骤/对象和精确merge候选。
当前没有PR/真实CI run，run_id=local；因此没有伪造PR/run或用bootstrap绕过，正式交付收据未生成。
候选外verify_test_plan PASS是开发结果集合核验，不能冒称正式PR交付通过。未push/创建PR/合并/发布，F01依赖集成未解锁。

### 既有skip精确清单（没有新增豁免）

- `stable.test_historical_race_detail_direct_urls.HistoricalRaceDetailDirectUrlTests.test_sporting_life_real_cache_preserves_structured_non_finish_statuses`；profile `django`；原因 `Sporting Life real cache root not configured`；原复核期限 `2026-10-16`。
- `stable.test_historical_race_detail_distance_metadata.HistoricalRaceDetailDistanceMetadataRealCacheTests.test_equibase_yearbook_result_preserves_distance_unit`；profile `django`；原因 `real cache root not configured`；原复核期限 `2026-10-16`。
- `stable.test_historical_race_detail_distance_metadata.HistoricalRaceDetailDistanceMetadataRealCacheTests.test_jra_2005_legacy_page_preserves_distance_unit`；profile `django`；原因 `real cache root not configured`；原复核期限 `2026-10-16`。
- `stable.test_historical_race_detail_distance_metadata.HistoricalRaceDetailDistanceMetadataRealCacheTests.test_sporting_life_race_118984_preserves_distance_units`；profile `django`；原因 `real cache root not configured`；原复核期限 `2026-10-16`。
- `stable.test_historical_race_detail_runner_v2_package_identity.HistoricalRaceDetailRunnerV2PackageIdentityRealSmokeTests.test_empty_event_distance_uses_real_parsed_metadata_with_original_units`；profile `django`；原因 `real cache root not configured`；原复核期限 `2026-10-16`。
- `stable.test_historical_race_detail_runner_v2_package_identity.HistoricalRaceDetailRunnerV2PackageIdentityRealSmokeTests.test_hk_package_rejects_raw_candidate_without_validation_evidence`；profile `django`；原因 `real cache root not configured`；原复核期限 `2026-10-16`。
- `stable.test_historical_race_detail_runner_v2_package_identity.HistoricalRaceDetailRunnerV2PackageIdentityRealSmokeTests.test_hk_real_validated_candidate_packages_with_plan_inventory_identity`；profile `django`；原因 `real cache root not configured`；原复核期限 `2026-10-16`。
- `stable.test_historical_race_detail_runner_v2_package_identity.HistoricalRaceDetailRunnerV2PackageIdentityRealSmokeTests.test_nonempty_event_and_parsed_distance_conflict_becomes_validation_gap`；profile `django`；原因 `real cache root not configured`；原复核期限 `2026-10-16`。
- `stable.test_migration_history_repair.MigrationHistoryRepairDockerImageContractTests.test_candidate_image_contains_only_the_exact_reviewed_audit_file`；profile `django`；原因 `set RUN_MIGRATION_REPAIR_DOCKER_CONTRACT=true for the real image contract`；原复核期限 `2026-10-16`。
- `stable.test_race_live_gate_remediation.RollbackGateBehaviorRemediationTests.test_root_artifact_is_exact_0700_0600_secret_free_and_no_replace`；profile `django`；原因 `root-owned artifact contract requires root EUID`；原复核期限 `2026-10-16`。

每周额度最新94%已用/6%剩余；停止阈值和有界异常恢复继续有效。
