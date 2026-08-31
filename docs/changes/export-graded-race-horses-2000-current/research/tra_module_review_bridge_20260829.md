# TRA 单马候选到 P0 落表链的 authority/module review bridge

日期：2026-08-29（Asia/Shanghai）

状态：代码与合成 fixture 已完成；尚无真实 TRA candidate、真实审核批准、数据库写入或生产 apply。

## 问题与结论

`racing-api-horse-p0-candidate.v1` 有意保持：

- `confidence=0`；
- `record_authority_status=count_aligned_records_unverified`；
- `career_collection_status=partial`。

因此即使 TRA profile/results 分页完整，也不能直接进入现有 P0 production apply。原有 strict contract 要求
模块 confidence 至少 90 且逐场履历为 `source_records_verified`。直接修改 candidate 或把 provider count
守恒解释成 authority verified 会绕过人工审核和 immutable source chain。

本次新增：

- `racing_api_horse_module_review.py`；
- `manage_racing_api_horse_module_review`；
- `test_racing_api_horse_module_review.py`；
- `build_region_approval_bundle` 对“research 已绑定独立 authority manifest”的显式入口。

## 三阶段 artifact

### 1. Prepare proposal

逐个输入 candidate path 与精确 SHA：

```bash
python server/manage.py manage_racing_api_horse_module_review prepare \
  --candidate <candidate-1.json> \
  --candidate-sha256 <candidate-1-sha256> \
  --output-dir <new-proposal-dir>
```

每个 proposal 只允许单一地区，输出：

- `review-rows.jsonl`；
- `proposal-manifest.json`；
- 最后发布的 `PREPARED`。

状态固定为 `PROPOSED_NOT_APPROVED / execution_ready=false / database_writes=0`。每行重新验证：

- candidate 为零写、无 blocker/manual-lock conflict、页面字段和 provider profile/career 完整；
- identity disposition 只允许 reviewed bind/create candidate；
- 四字段身份与唯一 `hrs_*` 完整；
- official/provider start count、started/nonstarter、gap/unconfirmed 守恒；
- 每条 HorseRaceRecord candidate 都绑定同一 `hrs_*` 的冻结 `/results` URL 和 response SHA；
- profile 与 results response evidence 均存在，host/path 不越过 TRA allowlist。

### 2. Publish exact approval

只有项目所有者/审核人明确批准 proposal manifest 与 rows SHA 后，才运行：

```bash
python server/manage.py manage_racing_api_horse_module_review publish \
  --proposal-dir <proposal-dir> \
  --approved-manifest-sha256 <exact-proposal-manifest-sha256> \
  --approved-rows-sha256 <exact-review-rows-sha256> \
  --approved-by <reviewer> \
  --decision-source-reference <approval-reference> \
  --output-dir <new-approval-dir>
```

输出 `approved-decisions.jsonl`、`approval-manifest.json` 和最后发布的 `COMPLETE`。这仍是零数据库写入；
candidate 任一字节变化都会使后续 build safe-stop。

### 3. Build reviewed research

```bash
python server/manage.py manage_racing_api_horse_module_review build-research \
  --approval-dir <approval-dir> \
  --approved-manifest-sha256 <exact-approval-manifest-sha256> \
  --output-dir <new-research-dir>
```

输出：

- `research_v3_<region>.json`；
- `authority_manifest_<region>.json`；
- `build-manifest.json`；
- 最后发布的 `COMPLETE`。

只有此阶段会在新的 reviewed research projection 中把 career 提升为
`source_records_verified / complete`，原 candidate 字节不改。美国 authority manifest 必须逐马覆盖 exact
identity 与 record count；其他地区沿用现有 authority schema 的空 US rows，但 research/mapping 的
`decision_source_reference`、authority input 与 module approval manifest SHA 必须三者完全一致。

随后仍使用既有链：

```text
reviewed research + authority
  -> authenticated mapping/module reviewer
  -> reviewed completion artifact
  -> immutable release candidate
  -> independent release approval
  -> zero-write dry-run
  -> backup + production G3
  -> apply + verifier + 页面抽检
```

本 bridge 不新增旁路写入，也不允许 prepare/publish/build 阶段创建 HorseProfile、HorseRaceRecord 或公开页面。

## 验证

- 新模块专项 `7/7`；覆盖美国 authority、爱尔兰非 US 路径、candidate SHA 漂移、错误 `hrs_*` URL、
  blocker/字段缺失、未绑定 decision reference 和管理命令。
- TRA staging/identity/candidate、P0 production apply 与 rolling batch 组合回归 `289/289`。
- 合成美国候选已贯通：proposal -> approval -> reviewed research/authority -> mapping bundle ->
  `prepare_reviewed_p0_completion_artifact`，最后仍为零业务数据库写入。
- 本轮未调用 TRA、未使用真实凭据、未写生产数据库、未提交/发布/部署。

完整 `stable` suite 既有 `4,445` 已执行、`32 failures / 144 errors / 128 skipped` 的非绿色结论保持不变；
不能用上述聚焦回归替代。
