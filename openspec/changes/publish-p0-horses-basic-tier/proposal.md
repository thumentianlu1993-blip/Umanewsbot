## Why

P0 马全量范围已入队（46,318 匹 profile），身份回填专项已让日本 2,462 匹、香港 327 匹具备经核验的 identity key（另有香港 58、英国 6,342 个 sync 名称归属 key 未核验），滚动批次流水线也已产品化并部署生产。但公开站点 `/horses/` 仍只有 12 匹人工发布的马：发布通道只有后台逐匹手动操作（`transition_review_status`），46,306 匹全部是 `draft`。4.6 万匹规模下人工逐匹发布不可行，而既有规格要求"只有管理员审核发布后才进入前台"，没有任何自动首发通道。

用户已于 2026-07-22 确认三项产品决策：

1. 公开展示最低门槛为 **BASIC 层**：名称 + 地区 +（≥1 个认可 namespace 的 identity key，或 父/母/出生日期三字段齐全）；未达完整资料的马以前台「资料补全中」徽章如实展示。
2. 滚动批次地区 commit 通过幂等复验后**自动首次发布**；批次 approve 与 xlsx 人工复审仍是人工门禁，批次审核人为发布责任人。
3. 滚动补全按**日本先行**推进，再复制到其他地区。

本专项把发布层补齐到与数据层匹配的规模：定义 BASIC 发布门禁、批次 commit 后的自动首发钩子、存量带 key 马的一次性发布通道，以及前台诚实徽章。

## What Changes

- BASIC 发布门禁：新服务判定 profile 是否可公开——名称与五地区地区齐备，且 `source_refs.horse_identity_verified_keys` 含 ≥1 个认可 namespace（netkeiba/nar/hkjc/sporting_life）的 key，或 `sire_text`/`dam_text`/`birth_date` 三字段齐全；`hidden`/曾 hidden 与人工锁定（`manual_lock_flags.auto_publish_blocked`）一律阻断。verified 身份只由 fail-closed 身份回填 commit 或人工批准批次 commit 写入；sync 按名称归属写入的扁平 key 与未映射 namespace 的中性 key 不得满足门禁。
- 批次自动首发：滚动批次地区 commit 的幂等复验通过后（复验失败绝不发布），本地区 profile 经 `transition_review_status` 自动首次发布，`published_by` 为批次 commit 审核人；审计走既有四通道（OperationLog、approvals_ledger、BatchRunState artifact、completion run summary）。
- 存量发布通道：新管理命令 `publish_p0_horse_profiles`（dry-run artifact → 人工批准 manifest SHA → 按地区分批 commit，单事务 ≤500），覆盖经回填核验身份的存量马（日本 2,462 + 香港 327，已发布的由状态检查排除；英国 6,342 个 sync 归属 key 未核验，不计入）。
- 前台徽章：`completeness_status` 仍为唯一事实源；完整二代血统/完整马匹资料保留正面标签，其余公开档位统一显示「资料补全中」；详情页对 BASIC 层马保持全区块空态降级。
- 规格修订：supersede 主规格 `horse-profile-pages` 中"只有管理员审核发布后才进入前台"的表述——批次审核后的自动首发视同管理员发布，批次审核人为责任人；`auto_first_publish_enabled` 死字段保持预留不启用。

## Capabilities

### New Capabilities

- 无

### Modified Capabilities

- `horse-profile-pages`：公开发布从"仅管理员逐匹手动"扩展为"管理员手动 + 批次审核后自动首发 + 批准的存量批量发布"，全部经同一 `transition_review_status` 审计通道；公开索引/详情对未完整马显示「资料补全中」徽章。
- `horse-profile-data-completion`：滚动批次地区 commit 通过幂等复验后自动首次发布本地区马匹，发布结果纳入批次报告与台账。

## Impact

- 代码：新增 `server/stable/services/horse_profile_publish.py`、管理命令 `publish_p0_horse_profiles.py`；`p0_horse_completion_commit.py` 增加复验后自动首发钩子；`HorseProfile` 增加 `public_completeness_badge` property（无迁移）；两个公开模板各一行。
- 数据：仅 `review_status`/`published_at`/`published_by` 与 OperationLog、台账文件；无模型变更、无迁移。
- 运维：首个日本滚动批次需 `HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=true` 与 worker 静默窗口（沿用既有 OOM 前置）；存量发布 dry-run → 人工批准 → 按地区 commit。
- 文档：`docs/current_state.md`、`docs/project_status.md`、`docs/deploy_runbook.md`（自动首发 + 存量发布操作手册）、`docs/decisions.md`（BASIC 门禁口径、规格 supersede、死字段保留、锁定键）。
- 明确不做：不启用 `auto_first_publish_enabled`；不做批量下线命令（下线仍逐匹人工转 hidden）；不改变滚动批次既有身份锁、复审与串行窗口纪律；不为发布而放松 BASIC 门禁（错误身份风险由 namespace 白名单与批次/存量两层人工复审兜底）。
