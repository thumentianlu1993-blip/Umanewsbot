## Context

首个生产滚动批次（`p0batch-ef7d482c4401`，日本 10 匹）证明滚动流水线各环节正常工作，但队列候选身份证据不足导致 0/10 可提交：`ambiguous_identity=3`、`identity_mismatch=2`、`identity_incomplete=4`、`partial_career=1`。调研（见 `docs/current_state.md` 2026-07-21 条目与专项调研）确认：

- 队列 `source_refs.horse_identity_keys` 与 `HorseP0Source.evidence_payload.horse_identity_keys` 基本全空；`TERM_ACTIVE_WITH_ZH` 来源路径从不计算 identity keys。
- 强证据已存在但未打通：netkeiba `ExternalHorse/ExternalHorseAlias`（约 12.4k，含 external ID、父母、出生日期）、`ExternalRaceEntry/Result.horse_id`（约 6 万行）、`RaceEventRunner/Result.source_refs` 中英国 Sporting Life `horse_id` 与法国 ZEturf `horse_id`、netkeiba 工具产出的 `horse_url`（数字 ID 在 URL 中）、本地 HTML 缓存中 NAR `k_lineageLoginCode` 与 HKJC `horseid`。
- `_participant_identity_keys` 只认 `external_horse_id/horse_id/horseId/id_horse` 四个键名，不认 `horse_url`/`horse_slug`。
- 批次认可的 namespace 集合（japan={jbis,jra,netkeiba,nar}、uk={sporting_life,racing_post}、france={geny,france_galop}、us={equibase,hrn}）与导入侧实际 namespace（`zeturf`、`horse_racing_nation`、`keiba_go_jp`）不一致；且 zeturf runner ID 与 geny 马 ID 不同源，不可映射。JBIS/Geny 客户端只做马名检索，批次四字段锁要求 profile 具备父/母/出生年——只回填 identity keys 不足以让日本/法国候选可提交，必须同时回填四字段。
- 65,042 条 pending `HorseIdentityConflict` 预期几乎不含四字段身份（代码上不存在产生四字段的入口），价值在"同名候选 + 马号 + 赛事 + 原因"聚合索引。

## Goals / Non-Goals

**Goals:**

- 用离线证据为 P0 队列回填 external identity keys 与来源 URL：唯一强匹配写入，歧义 fail closed 进冲突。
- namespace 映射到批次认可集合，原始值留证据。
- 回填后重跑按地区 P0 来源同步，使滚动批次可采信候选显著增加（输出前后对比）。
- pending 冲突按"唯一马候选 + 原因"聚合，输出只读统计；对有强身份证据的冲突给出批量裁决建议，经人工批准后经既有 resolved 通道写回。
- 全流程 dry-run → artifact → 人工批准 → 分批 commit，零网络请求。

**Non-Goals:**

- 不做 HRN slug 触网解析、不做 JRA 官方行新抓取、不做任何新网络请求。
- 不自动合并同名马、不绕过四字段身份锁、不修改赛事/新闻数据、不创建 RaceEvent。
- 不做冲突的无人值守批量解决：批量裁决建议必须经人工批准。
- 不改变滚动批次流水线本身（checkpoint/预算/提交链）。

## Decisions

### 1. 四个离线证据源按地区启用，各自产出统一 identity 候选

- 日本：`ExternalHorseAlias` 按"规范化马名 + 地区"匹配，命中后要求 `ExternalHorse` 记录存在；`ExternalRaceEntry/Result.horse_id` 通过"马名 + 赛事日期对齐 RaceEvent"回推；netkeiba `horse_url` 提取数字 ID。JRA 中央马只能依赖 netkeiba 旁路（官方行无马链接，已验证）。
- 英国：`RaceEventRunner/Result.source_refs.horse_id`（Sporting Life）直接映射 `sporting_life:{id}`。
- 法国：`source_refs.horse_id`（ZEturf）只以原始 namespace 留存证据；geny 马 ID 与 zeturf runner ID 不同源，本期不生成 geny identity key。
- 中国香港：本地 HKJC HTML 缓存重解析 `horseid` 映射 `hkjc:{id}`。
- 日本 NAR：本地 HTML 缓存重解析 `k_lineageLoginCode` 映射 `nar:{id}`。
- 美国：本期只有 HRN slug（非 ID），不做回填，全部保持待补强并在统计中单列。

候选统一为 `{profile_id, namespace, external_id, source_url, evidence_kind, evidence_refs}`。备选方案是先扩展 `ExternalHorse` 覆盖英法港再回填：成本远超收益，现有证据已够第一迭代。

### 2. 写入判据：唯一强匹配 + 双向一致性 + 四字段回填

一条 identity 候选写入前必须满足：同一 profile 在该 namespace 下只有唯一候选 ID；该 ID 反向匹配（按规范化马名，统一使用 `_normalize_identity_name` 语义的 casefold + 剔除非字母数字）唯一命中同一 profile；候选 ID 与 profile 已有其他 namespace 的 ID 不矛盾（如已有 netkeiba ID 与 ExternalHorse 记录不一致则冲突；既有未映射 namespace 的 key 视为中性证据，不构成矛盾）。满足不了就建/复用 `HorseIdentityConflict`（`ambiguous_external_identity`），不写入。

**四字段回填**：ExternalHorse 侧存在 father/mother/birth_date 时，按同一判据把父、母、出生日期写入 profile 的 `sire_text` / `dam_text` / `birth_date`：既有列为空才写；既有列与证据不一致时不覆盖、记冲突。identity key 一律 casefold 写入。这是日本候选通过批次四字段身份锁（`has_provider_bound_identity` 失败时要求四字段齐全）的前置条件；同名歧义马仍被检索层正确阻断，本判据不负责解决歧义。

### 3. namespace 处理：映射仅限于同源 ID，zeturf 只留原始证据

`horse_url`/`horse_slug` 中的数字 ID 以批次认可 namespace 提取为 identity key（netkeiba URL→`netkeiba:{id}`、NAR `k_lineageLoginCode`→`nar:{id}`、HKJC `horseid`→`hkjc:{id}`、Sporting Life `horse_id`→`sporting_life:{id}`，均 casefold）。**zeturf `data-runner` 数值 ID 与 geny 马 ID（`c\d+_h\d+`）不同源，不做 zeturf→geny 映射**——只以原始 namespace 存入 `identity_evidence`；HRN slug 同理只留证据。`_participant_identity_keys` 增加 `horse_url`/`horse_slug` 的同源 ID 提取。

### 4. 全部写入走 dry-run artifact → 人工批准 → 按地区分批 commit

回填服务默认 dry-run：输出候选 JSONL、冲突增量、前后对比统计、SHA-256 manifest。commit 必须显式提供经批准的 manifest SHA，按地区分批执行，**单事务 ≤500 profile**（沿用已实证的 OOM 运维边界），每地区 commit 后输出对账（写入数、冲突数、跳过数）。source_refs/evidence 合并写入幂等；流式处理 + 分批 prefetch，不在内存累积全量。生产执行前置：停止 beat/worker、串行执行（同 runbook 既有先例）。

### 5. sync 覆盖缺陷修复与执行顺序

`_upsert_p0_source` 重写 `evidence_payload` 时合并保留 `horse_identity_keys` 与 `identity_evidence` 键，不再整体覆盖（否则回填后重跑 sync 会自我抹除证据）。执行顺序固化为：先按地区重跑 sync（让 `_participant_identity_keys` 扩展先产生同源 key），再回填，再按需增量 sync 对账；两路径产出的 key 形态一致（同映射、同 casefold），不并存双形态。

### 6. 回推对齐键与交叉验证

ExternalRaceEntry/Result 回推的对齐键为"规范化马名 + 赛事日期 + race_name 或 venue"，同日同名不同赛场不得对齐；对齐命中后若该 horse_id 存在 ExternalHorse 记录，用其父母/出生年与 profile 既有值交叉验证，不一致进冲突。

### 7. 离线冲突 fingerprint 与 resolved 保护

离线歧义冲突使用确定性 fingerprint：`sha256("offline"|namespace|sorted(candidate_ids)|sorted(profile_ids)|reason)`，与既有事件级冲突（race_event_id 编入）隔离命名空间。复用既有冲突时只允许更新 PENDING 记录；RESOLVED/IGNORED 一律跳过，不覆盖裁决证据。

### 8. 冲突聚合统计与批量裁决建议

只读统计按 `(规范化马名, 候选 profile 集合, 原因)` 分组（iterator + 分批 prefetch candidate_profiles/terms），输出：每组冲突数、涉及赛事数、是否已有强身份证据（回填后）、建议动作（`resolvable_with_identity / needs_admin_review / insufficient_evidence`）。批量裁决建议只对"回填后四字段或 external ID 唯一对齐"的组生成，必须经人工批准 manifest 后才通过既有 resolved 通道写回；写回必须走 `full_clean()` 校验（Admin clean() 同规则）；每日通知与 `_reopen_identity_conflict` 保护保持不变。

### 9. NAR 覆盖探针先行

`k_lineageLoginCode` 在代码库零佐证。NAR 证据源启用前先做只读覆盖探针：统计本地 HTML 缓存中可解析该字段的页面比例并写入 dry-run artifact；覆盖不足时 NAR 证据源本期不启用，如实报告。

## Risks / Trade-offs

- [ExternalHorseAlias 同名多 ID] -> 双向唯一性判据，歧义直接冲突，不猜。
- [映射表掩盖真实来源] -> 原始 namespace/id 全部留在 `identity_evidence`；统计 artifact 按原始 namespace 分列。
- [netkeiba 覆盖仅限日本且时间窗有限] -> 统计如实报告覆盖率；不为了覆盖率放宽判据。
- [日本/法国候选回填后仍受检索层限制] -> 诚实口径：identity key 改善队列治理，四字段回填让日本非歧义马可过四字段锁；JBIS/Geny 检索歧义与 zeturf/HRN 无同源 ID 的马继续待补强，统计分“预期可提交”与“仅治理改善”两层报告。
- [sync 重跑覆盖回填证据] -> `_upsert_p0_source` 合并保留 identity 键；执行顺序固化为先 sync 后回填。
- [分批 commit 中途失败] -> 单事务 ≤500 profile，失败地区可独立重跑；已 commit 地区幂等（identity keys 合并写入，不重复）。
- [回填后滚动批次误判身份已解决] -> 批次既有四字段锁与来源复核不变；回填只提供 identity keys/URL，客户端仍以四字段验证页面身份。

## Migration Plan

1. 实现证据提取、唯一性判据、namespace 映射与 dry-run artifact，全量测试。
2. 本地（sqlite fixture）端到端：候选生成 → 歧义冲突 → 批准 → commit → 同步 → 批次可采信对比。
3. 生产执行：备份 → 按地区 dry-run artifact → 人工批准 → 分批 commit → 重跑地区同步 → 对比统计。
4. 冲突聚合统计只读先行；批量裁决建议单独 manifest 单独批准。
5. 回滚：identity keys/evidence 按 artifact 记录的原值回退；冲突新增标记按批次 ID 批量撤销。

## Resolved Questions

- 范围：离线证据回填 + 回填后冲突重分组 + 管理员冲突队列；不做 HRN slug 触网解析（用户 2026-07-21 确认）。
- namespace：同源 ID 映射到批次认可集合（netkeiba/nar/hkjc/sporting_life），zeturf/HRN 只留原始证据不映射（plan-eng-review P1-3 修正，2026-07-21）。
- 四字段回填：同意把 ExternalHorse 的父/母/出生日期回填到 profile 的 sire_text/dam_text/birth_date 列，唯一匹配 + 不矛盾才写（用户 2026-07-21 确认）。
- sync 覆盖缺陷：`_upsert_p0_source` 合并保留 identity 键，执行顺序为先 sync 后回填（plan-eng-review P0-2 修正，2026-07-21）。
