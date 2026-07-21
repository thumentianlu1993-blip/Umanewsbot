## 0. Pre-declared hypotheses

- [x] 0.1 (operations) 在实现前确认回填判据：唯一强匹配（同 namespace 唯一候选 ID + 反向唯一命中 + 与既有身份不矛盾）才写入；歧义一律 `HorseIdentityConflict`，不猜测合并。
- [x] 0.2 (operations) 在实现前确认范围边界：本 change 不发任何网络请求；HRN slug 解析、JRA 官方行抓取不在范围；批量冲突裁决建议必须经人工批准 manifest 后才写回。
- [x] 0.3 (operations) 在更新 proposal 后重新执行 plan-eng-review，并将 review 结果写入 `.openspec.yaml`。

## 1. 证据提取与统一候选

- [x] 1.1 (integration) 日本：实现 ExternalHorseAlias 规范化马名匹配候选（关联 ExternalHorse 提取 external ID、父母、出生日期），以及 netkeiba `horse_url` 数字 ID 提取。
- [x] 1.2 (integration) 日本：实现 ExternalRaceEntry/Result.horse_id 经"马名 + 赛事日期对齐 RaceEvent"的回推候选，对齐不唯一时丢弃并进冲突。
- [x] 1.3 (integration) 英国/法国：实现 RaceEventRunner/Result.source_refs `horse_id` 候选（Sporting Life 生成 `sporting_life:{id}` key；ZEturf 只留原始证据不生成 geny key）。
- [x] 1.4 (integration) 香港/NAR：实现本地 HTML 缓存重解析脚本，提取 HKJC `horseid` 与 NAR `k_lineageLoginCode`，缓存缺失时如实记录不可解析，不触网补抓。
- [x] 1.5 (integration) 统一 identity 候选结构 `{profile_id, namespace, external_id, source_url, evidence_kind, evidence_refs}`；仅同源 ID 映射为批次认可 namespace（netkeiba/nar/hkjc/sporting_life，casefold 写入），zeturf/HRN 原始值只入 `identity_evidence`。
- [x] 1.6 (integration) 四字段回填：从 ExternalHorse 提取 father/mother/birth_date，既有列为空才写 `sire_text`/`dam_text`/`birth_date`，不一致记冲突；identity key 一律 casefold。
- [x] 1.7 (operations) NAR 只读覆盖探针：统计本地 HTML 缓存中 `k_lineageLoginCode` 可解析率并写入 dry-run artifact，覆盖不足则 NAR 证据源本期不启用。

## 2. 唯一性判据与冲突

- [x] 2.1 (integration) 实现双向唯一性判据：同 namespace 唯一候选 + 反向规范化名唯一命中（统一 `_normalize_identity_name` 语义）+ 与既有 identity keys 不矛盾（既有未映射 key 视为中性证据）；扩展 `_participant_identity_keys` 支持 `horse_url`/`horse_slug` ID 提取（同映射、同 casefold）。
- [x] 2.3 (integration) ExternalRaceEntry 回推对齐键为规范化马名 + 赛事日期 + race_name/venue；对齐命中且存在 ExternalHorse 记录时用父母/出生年交叉验证 profile 既有值，不一致进冲突。
- [x] 2.2 (integration) 歧义候选建/复用 `HorseIdentityConflict`（`ambiguous_external_identity`）：离线确定性 fingerprint `sha256("offline"|namespace|candidate_ids|profile_ids|reason)`，与事件级冲突隔离；只更新 PENDING 记录，RESOLVED/IGNORED 跳过不覆盖裁决证据。

## 3. dry-run、批准与分批 commit

- [x] 3.1 (integration) 实现回填 dry-run artifact：候选 JSONL、冲突增量、前后对比统计、SHA-256 manifest；默认不落库。
- [x] 3.2 (integration) 实现 commit 入口：必须显式批准 manifest SHA，按地区分批（单事务 ≤500 profile）写入 `HorseProfile.source_refs.horse_identity_keys`、`HorseP0Source.evidence_payload.horse_identity_keys`、`horse_source_urls` 与四字段列；identity keys 合并写入幂等；每地区输出对账。
- [x] 3.4 (integration) 修复 `_upsert_p0_source` 整体覆盖 `evidence_payload` 的缺陷：重写时合并保留 `horse_identity_keys` 与 `identity_evidence`；执行顺序固化为先按地区 sync、再回填、再增量对账。
- [x] 3.3 (application) 新增管理命令：dry-run 预览、批准 manifest、分批 commit、按地区重跑同步的串行入口。

## 4. 冲突聚合统计与裁决通道

- [x] 4.1 (integration) 实现 pending 冲突只读聚合：按"规范化马名 + 候选 profile 集合 + 原因"分组，输出每组冲突数、赛事数、强身份证据状态、建议动作（`resolvable_with_identity / needs_admin_review / insufficient_evidence`）与 SHA-256 manifest。
- [x] 4.2 (application) 实现批量裁决建议执行：仅对"回填后四字段或 external ID 唯一对齐"的组生成 resolved 建议，经人工批准后经既有 `resolved_profile + resolved_horse_number` 通道写回，写回必须走 `full_clean()` 校验；保留 `_reopen_identity_conflict` 保护；未批准 manifest 不得写回（负向测试）。

## 5. 效果度量

- [x] 5.1 (integration) 实现批次视角前后对比：含可采信 identity keys / source URL 的队列候选数与占比、`needs_identity_enrichment` 占比变化，按地区输出 artifact；覆盖率如实报告，不设虚构目标值。

## 6. 验证与文档

- [x] 6.1 (integration) 目标测试：四证据源候选提取、URL/slug ID 提取、双向唯一性全分支（含未映射 key 中性处理）、歧义冲突（离线 fingerprint、resolved 跳过）、casefold 写入、四字段只填空列与不一致记冲突、sync 合并保留 identity 键、dry-run/commit 门禁、幂等重跑、冲突聚合分组、批量裁决只走批准通道且过 full_clean。
- [x] 6.2 (operations) 本地验证：`DB_ENGINE=sqlite python manage.py check`、目标测试、完整 `stable` 回归、`makemigrations --check --dry-run`、`openspec validate enrich-p0-horse-external-identity --strict`、`openspec validate --all`、`git diff --check`。
- [x] 6.3 (integration) 离线 fixture 端到端：候选 → 歧义冲突 → 批准 → commit → 同步 → 批次可采信对比，全程零网络。
- [x] 6.4 (operations) 独立 code review 并修复全部 actionable finding；更新 `docs/current_state.md`、`docs/project_status.md`、`docs/deploy_runbook.md`、`docs/decisions.md`。
- [x] 6.5 (operations) 生产执行：备份 → 停 beat/worker（OOM 先例前置）→ 按地区 dry-run artifact → 人工批准 → 分批 commit（单事务 ≤500）→ 重跑地区同步 → 对比统计 → 抽样验证滚动批次可选出带身份与四字段候选。
