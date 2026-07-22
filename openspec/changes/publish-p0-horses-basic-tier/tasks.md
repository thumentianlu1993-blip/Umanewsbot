## 0. Pre-declared hypotheses

- [x] 0.1 (operations) 实现前确认 BASIC 门禁非身份分支按 sire_text+dam_text+birth_date 三字段实现（名称由 name 判据覆盖）。
- [x] 0.2 (operations) 实现前确认 `published_by` = 批次 commit 审核人，不设系统用户；`auto_first_publish_enabled` 保持预留不启用。
- [x] 0.3 (operations) 实现前确认 supersede 主规格 `horse-profile-pages` 两条要求的边界（三种发布路径同审计通道；首批验收完成后启用受门禁约束的自动首发）。
- [x] 0.4 (operations) 在更新 proposal 后重新执行 plan-eng-review，并将 review 结果写入 `.openspec.yaml`。

## 1. 身份核验 provenance 与发布门禁服务

- [x] 1.1 (integration) 回填 commit 写 `source_refs.horse_identity_keys` 时同步写 `horse_identity_verified_keys`（`p0_horse_identity_enrichment` 的 `_merge_evidence` 与 profile source_refs 写入点；casefold 一致）。
- [x] 1.2 (integration) 滚动批次 `p0_horse_production_apply` 成功写入 profile 后，其当前 identity keys 全部标记进 `horse_identity_verified_keys`。
- [x] 1.3 (integration) 新增 `server/stable/services/horse_profile_publish.py`：`PublishGateResult`、`BASIC_GATE_IDENTITY_NAMESPACES`、`evaluate_basic_publish_gate`（名称 + `racing_region ∈ P0_REGIONS` + [verified key 认可 namespace 或三字段齐全] + `review_status ∈ {draft,ready}` 且 `hidden_at` 为空 + `auto_publish_blocked` 锁定键；扁平未核验 key 与未映射 namespace 不计）。
- [x] 1.4 (integration) `auto_publish_profiles`：逐匹经 `transition_review_status`，逐匹 try/except，返回 `{published, skipped_already_published, blocked, errors}`，不中途抛出。

## 2. 批次 commit 自动首发钩子

- [x] 2.1 (integration) `p0_horse_completion_commit.py`：复验通过（217 行 raise 之后）、`mark_batch_manifest_status` 之前插入自动首发；`load_batch_manifest` 提前；发布对象 = 本地区 manifest profile_ids ∪ 本 completion run 经 `HorseP0Source.completion_run` 反查的新建 profile；`completion_run` 为 None 时退回 manifest ids 并跳过 run summary。
- [x] 2.2 (integration) 审计四通道：OperationLog（经 1.4）、台账 `auto_first_publish` 条目（含 profile_ids 与计数）、`BatchRunState.artifacts["publish:<region>"]` + completed_stages、`completion_run.summary["auto_first_publish"]` 二次 save；commit 返回值增加 `auto_first_publish` 报告。
- [x] 2.3 (integration) 失败语义：errors 写入 `state.errors`、不记录完成的 publish stage 并 raise，批次不得带缺失 publish artifact 进入 committed 终态（多地区同规）；恢复走 `--retry-publish` 专用阶段（核验复验通过；全量重 commit 的快照漂移 fail closed 为既有行为，不改动）。

## 3. 存量发布命令

- [x] 3.1 (application) 新增 `publish_p0_horse_profiles` 命令：`--dry-run/--approve/--commit` + `--regions/--profile-id/--output-dir/--reviewer/--reviewer-id/--approved-sha256/--json`，结构镜像 `enrich_p0_horse_identities`。
- [x] 3.2 (integration) dry-run artifact：候选 JSONL、阻断原因直方图、SHA-256 manifest、metrics_before，默认零写库。
- [x] 3.3 (integration) commit：manifest 重算哈希 + active-superuser reviewer-id；按地区分批单事务 ≤500 profile；metrics_after；幂等重跑全 skipped。

## 4. 前台徽章

- [x] 4.1 (integration) `HorseProfile.public_completeness_badge` property：complete_pedigree_2gen/complete_profile_full 保留既有标签，其余返回「资料补全中」；无迁移。
- [x] 4.2 (integration) 模板替换：`stable/public/horse_index.html:31` 与 `stable/public/horse_detail.html:15` 改用该 property。

## 5. 测试

- [x] 5.1 (integration) provenance：回填 commit 写 verified keys；批次 apply 后 keys 标记 verified；sync 只写扁平列表不写 verified。
- [x] 5.2 (integration) 新 `test_horse_profile_publish.py`：门禁全分支（无名/other 地区/无 verified key/仅扁平 sync key/未认可 namespace/两字段缺一/hidden/hidden_at 非空的 ready/锁定/draft/ready）；命令 dry-run 零写库、未批准/篡改/非 superuser 拒绝、分批精确命中、幂等重跑、metrics artifact。
- [x] 5.3 (integration) `test_p0_horse_completion_batch.py` 扩展：复验通过才发布且覆盖 create_new；复验失败零发布；发布 errors 阻断 committed 终态并可幂等补齐；幂等重 commit 发布 0；hidden/锁定不发；OperationLog/ledger/state artifact/run summary 齐备。
- [x] 5.4 (integration) `tests.py` 扩展：index 卡片与 detail hero 徽章分档；BASIC 层详情页 200 全区块空态；既有公开页 no-network 测试通过；index 分页 q+region 组合。

## 6. 验证与文档

- [x] 6.1 (operations) 本地验证：`DB_ENGINE=sqlite python manage.py check`、目标测试、完整 `stable` 回归（基线 14F+70E 对照零新增）、`makemigrations --check --dry-run`、`openspec validate publish-p0-horses-basic-tier --strict`、`openspec validate --all`、`git diff --check`。
- [x] 6.2 (operations) 独立 code review 并修复全部 actionable finding；更新 `docs/current_state.md`、`docs/project_status.md`、`docs/deploy_runbook.md`（含 `auto_publish_blocked` 设置程序）、`docs/decisions.md`；合并 main。

## 7. 生产执行（分步用户授权）

- [x] 7.1 (operations) 备份 → 停 beat/worker → `HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=true` 并重启进程。
- [ ] 7.2 (operations) 首个日本滚动批次全链路【2026-07-22 已尝试：JBIS 名称检索同名歧义 100/100 fail closed，批次已 abandon 留证；待 netkeiba 客户端 change 后重跑】：select → approve → validate → prepare `--allow-network` → 人工复审 xlsx → bundle → commit `--confirm-reviewed-artifact` → 核验 auto_first_publish 计数、OperationLog、`/horses/?region=japan` 新马与「资料补全中」徽章。
- [x] 7.3 (operations) provenance 回填与存量发布：先对生产重跑已批准的三个身份回填 manifest 的 commit（幂等，为 2026-07-22 已写入的 2,789 个 key 补写 `horse_identity_verified_keys`）→ `publish_p0_horse_profiles --dry-run --regions japan,hong_kong` → 人工审 artifact → approve → 按地区 commit → metrics 对比。
- [ ] 7.4 (operations) 恢复 worker；healthz + `/horses/` 200；更新状态文档；同步主规格（含 Purpose 段措辞）并评估归档。
