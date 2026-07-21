## Why

P0 马全量范围已入队（46,318 匹 profile、56,745 条来源），滚动批次流水线也已产品化并部署生产，但首个生产滚动批次（日本 10 匹）证明：**队列候选几乎全部只有裸马名**——`HorseProfile.source_refs.horse_identity_keys` 为空、`HorseP0Source.evidence_payload.horse_identity_keys` 为空、`identity_status=created_pending_identity`，批次只能靠来源马名精确检索碰运气，10 匹全部因 `ambiguous_identity / identity_mismatch / identity_incomplete / partial_career` 被 fail-closed 阻断（0/10 可提交）。

代码核实与数据调研发现，可用来回填身份的强证据已经存在，只是没有打通：

- `ExternalHorse`/`ExternalHorseAlias`（netkeiba，约 12.4k，含 external ID、父母、出生日期）与 `ExternalRaceEntry/Result.horse_id`（约 6 万行）覆盖日本。
- `RaceEventRunner/RaceEventResult.source_refs` 已含英国 Sporting Life `horse_id`、法国 ZEturf `horse_id`，以及日本 netkeiba 工具的 `horse_url`（数字 ID 在 URL 中）。
- 本地原始 HTML 缓存含 NAR `k_lineageLoginCode`（keiba.go.jp 官方马 ID）与 HKJC `horseid`。
- 但 `_participant_identity_keys` 只认 4 个 ID 键名（不认 `horse_url`/`horse_slug`），且导入侧 namespace（`zeturf`/`horse_racing_nation`/`keiba_go_jp`）不在批次认可的 adapter namespace 集合内，已生成的少数 key 也未被批次采信。

同时 65,042 条 pending `HorseIdentityConflict` 尚未按"唯一马候选 + 原因"聚合治理（交接文档 9.3）。外部身份回填后，大量冲突可批量裁决。

本专项在不发任何新网络请求的前提下，把上述离线证据回填为队列可用的 external identity，并把剩余冲突整理成管理员可处理的队列，让滚动补全批次真正具备可提交候选。

## What Changes

- 离线身份回填：按地区从 ExternalHorse/Alias、ExternalRaceEntry/Result、`RaceEventRunner/Result.source_refs`（horse_id / horse_url 数字 ID 提取）、NAR/HKJC 本地 HTML 缓存重解析四个证据源生成 identity 候选；唯一强匹配（同 namespace 唯一候选 + 反向规范化名唯一命中 + 与既有身份不矛盾）才写入 `HorseProfile.source_refs.horse_identity_keys`、`HorseP0Source.evidence_payload.horse_identity_keys` 和 `horse_source_urls`；歧义一律新建/复用 `HorseIdentityConflict`（fail closed，不猜测合并）。
- 四字段身份回填：从 `ExternalHorse`（netkeiba，含 father/mother/birth_date）把父、母、出生日期回填到 profile 的 `sire_text` / `dam_text` / `birth_date` 列，判据与 identity key 相同（唯一匹配 + 与既有值不矛盾才写，既有值不同源不一致时进冲突）。这是日本候选通过滚动批次四字段身份锁的前置条件；同名歧义马仍正确阻断。
- namespace 映射与证据保留：`horse_url`/`horse_slug` 中的数字 ID 以 `{namespace}:{id}` 形式进入 identity keys（`netkeiba`/`nar`/`hkjc` 等批次认可 namespace，casefold 写入）；`zeturf` 的 runner ID 与 geny 马 ID 不同源，**不做 zeturf→geny 映射**，只以原始 namespace 留存证据；既有未映射 key 视为中性证据，不算矛盾。
- sync 覆盖缺陷修复：`_upsert_p0_source` 重写 `evidence_payload` 时合并保留 `horse_identity_keys` / `identity_evidence`，不再整体覆盖抹掉回填证据。
- 冲突重分组与管理员队列：回填后重算 pending 冲突，按"规范化马名 + 候选 profile 集合 + 原因"聚合输出只读统计 artifact；已有强身份证据的冲突给出可批量裁决建议（人工批准后通过既有 resolved 通道 + `full_clean()` 校验写回），其余进入 Django Admin 可筛选的管理员队列视图。
- 与滚动批次对齐：回填后重跑 P0 来源同步（按地区、每事务 ≤500 profile、遵守已实证的 OOM 运维前置），确认批次选出的候选携带可采信 identity keys / source URLs / 四字段，输出前后对比指标（分"预期可提交"与"仅治理改善"两层口径，不设虚构目标值）。
- 全程门禁：所有写入先 dry-run 产出 artifact（候选清单、SHA-256 manifest、前后对比），人工批准后按地区分批 commit（单事务 ≤500）；不修改任何赛事/新闻数据，不创建 RaceEvent，不触网。

## Capabilities

### New Capabilities

- 无

### Modified Capabilities

- `horse-profile-data-completion`: P0 队列候选从"裸马名 + 待身份补强"升级为"经离线证据回填的 external identity + 来源 URL"，滚动批次的可提交候选比例可度量；身份冲突从逐条未治理升级为聚合统计 + 管理员队列 + 可批量裁决通道。

## Impact

- 代码：`server/stable/services/` 新增身份回填服务与只读统计服务；扩展 `p0_horse_profiles.py` 的 identity key 提取（URL/slug 派生）与 namespace 映射；新增管理命令；`runtime/tools/` 新增 NAR/HKJC 缓存重解析脚本；新增专项测试。
- 数据：写 `HorseProfile.source_refs`、`HorseP0Source.evidence_payload`、`HorseProfile.sire_text` / `dam_text` / `birth_date`（仅唯一匹配且不矛盾时）、`HorseIdentityConflict`（新建/复用/状态）；不改模型、无迁移。
- 运维：dry-run artifact → 人工批准 → 按地区分批 commit；每步输出 SHA-256 manifest；生产执行遵守 4 GiB 内存约束（分批 + 流式）。
- 文档：`docs/current_state.md`、`docs/project_status.md`、`docs/deploy_runbook.md`、`docs/decisions.md`（namespace 映射与可批量裁决口径）。
- 明确不做：HRN slug 触网解析、JRA 官方行新增抓取、任何新网络请求、自动合并同名马、绕过四字段身份锁。
