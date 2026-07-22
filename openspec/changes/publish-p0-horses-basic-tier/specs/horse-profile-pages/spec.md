## MODIFIED Requirements

### Requirement: 马匹资料审核控制公开可见性

系统 SHALL 支持三种发布路径，且全部经同一 `transition_review_status` 审计通道记录审核人、时间和备注：管理员后台手动发布；滚动批次地区 commit 通过幂等复验后的自动首次发布（批次审核人即发布责任人）；经人工批准 manifest 的存量批量发布。批次审核后的自动首发视同管理员发布。系统 MUST NOT 绕过该审计通道直接修改 `review_status`。后台下线或隐藏的马匹 SHALL 从公开索引、详情、关注与新闻关联中移除；hidden 或曾 hidden（`hidden_at` 非空）的马 MUST NOT 被任何自动或批量通道发布。

#### Scenario: 发布和下线记录审计信息

- **WHEN** 管理员手动发布或下线马匹资料，或批次 commit 复验通过后自动首次发布本地区马匹，或存量批量发布经批准 manifest 执行 commit
- **THEN** 系统 SHALL 记录 `published_at`/`published_by` 或 `hidden_at`/`hidden_by` 并写入操作日志
- **AND** 自动首发 SHALL 在批次台账与批次 checkpoint 中留下含 profile 列表与计数的条目

### Requirement: 首批公开验收必须由人工发布触发

系统 SHALL 保持资料补全和资料公开分离。首批每地区完整资料样本 MAY 进入 `ready`，首批公开发布 MUST 由管理员人工执行。首批公开验收完成后（2026-07-21 已完成），系统 MAY 启用经由 BASIC 发布门禁与人工批准批次约束的自动首次公开。

#### Scenario: 每地区人工发布样本

- **WHEN** 首批五地区各 10 匹完整资料马完成审核
- **THEN** 运营人员 SHOULD 每地区人工发布 1-2 匹做公开验收
- **AND** 未人工发布的完整资料马 SHALL 不自动进入前台公开列表

#### Scenario: 验收后启用受门禁约束的自动首发

- **WHEN** 首批公开验收已完成，且某 profile 通过 BASIC 发布门禁，且其所属批次经人工批准并通过幂等复验（或其发布 manifest 经人工批准）
- **THEN** 系统 MAY 对该 profile 自动首次公开，并按"马匹资料审核控制公开可见性"要求留下审计记录
- **AND** 未经批次批准或 manifest 批准的自动首次公开 SHALL NOT 启用

## ADDED Requirements

### Requirement: BASIC 层公开发布门禁

系统 SHALL 只在 profile 同时满足以下条件时允许（自动或批量）公开发布：名称非空；`racing_region` 属于五地区集合（france/hong_kong/japan/united_kingdom/united_states）；`source_refs.horse_identity_verified_keys` 含至少一个认可 namespace（netkeiba/nar/hkjc/sporting_life）的 key，或 `sire_text`/`dam_text`/`birth_date` 三字段齐全；`review_status` 为 draft 或 ready 且 `hidden_at` 为空；未设置 `manual_lock_flags.auto_publish_blocked`。只有经 fail-closed 身份回填 commit 或经人工批准批次 commit 写入的身份才计入 `horse_identity_verified_keys`；sync 按名称归属写入的未核验 key 与未映射 namespace 的中性 key MUST NOT 计入身份判据。

#### Scenario: hidden 与锁定马不自动发布

- **WHEN** 某 profile 为 hidden、曾 hidden（`hidden_at` 非空），或设置了 `manual_lock_flags.auto_publish_blocked`
- **THEN** 任何自动或批量发布通道 MUST NOT 发布该 profile

#### Scenario: 未核验或未映射的 key 不满足门禁

- **WHEN** 某 profile 的 identity keys 只来自 sync 名称归属（未核验），或只含认可集合之外的 namespace
- **THEN** BASIC 门禁的身份判据 SHALL 判定为不满足

### Requirement: 公开页对未完整马匹显示资料补全中徽章

公开索引卡片与详情页头部 SHALL 以 `completeness_status` 为唯一事实源显示完整度徽章：完整二代血统与完整马匹资料保留既有正面标签；其余档位（空壳、仅基础资料、部分血统）SHALL 统一显示「资料补全中」，内部完整度措辞 MUST NOT 出现在公开页。

#### Scenario: 未完整公开马显示补全中

- **WHEN** 用户浏览公开索引或详情页，且该马的 `completeness_status` 不是完整二代血统或完整马匹资料
- **THEN** 页面 SHALL 显示「资料补全中」徽章

#### Scenario: 完整马保留正面标签

- **WHEN** 该马的 `completeness_status` 为完整二代血统或完整马匹资料
- **THEN** 页面 SHALL 显示对应的完整度标签
