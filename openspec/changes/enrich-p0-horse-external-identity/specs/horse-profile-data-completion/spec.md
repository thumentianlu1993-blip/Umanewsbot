## ADDED Requirements

### Requirement: P0 队列身份回填必须只使用离线证据且唯一强匹配

系统 SHALL 仅从本地证据源（ExternalHorse/ExternalHorseAlias、ExternalRaceEntry/Result、RaceEventRunner/Result source_refs、本地 HTML 缓存）为 P0 队列生成 external identity 候选，MUST NOT 发出任何网络请求。identity keys SHALL 只在唯一强匹配时写入：同 namespace 唯一候选、反向规范化马名唯一命中、与既有身份不矛盾；既有未映射 namespace 的 key SHALL 视为中性证据。ExternalHorse 的父亲、母亲、出生日期 SHALL 按同一判据回填到 profile 的 `sire_text` / `dam_text` / `birth_date`：既有列为空才写，不一致记冲突，MUST NOT 覆盖既有值。

#### Scenario: 唯一强匹配写入

- **WHEN** 某 profile 在同一 namespace 下只有唯一候选 external ID，且该 ID 反向规范化马名唯一命中同一 profile
- **THEN** 系统 SHALL 把 `{namespace}:{external_id}` 写入 `HorseProfile.source_refs.horse_identity_keys` 与 `HorseP0Source.evidence_payload.horse_identity_keys`
- **AND** 原始 namespace 与原始 ID SHALL 保留在 `identity_evidence`

#### Scenario: 歧义 fail closed

- **WHEN** 某 profile 的候选 external ID 不唯一、反向命中多个 profile 或与既有身份矛盾
- **THEN** 系统 SHALL 创建或复用 `HorseIdentityConflict` 记录证据
- **AND** MUST NOT 写入 identity keys 或猜测合并

#### Scenario: 全程零网络

- **WHEN** 系统执行证据提取、候选生成、dry-run 或 commit
- **THEN** 系统 MUST NOT 发起任何外部网络请求
- **AND** 本地 HTML 缓存缺失时 SHALL 记录不可解析，不触网补抓

### Requirement: identity key namespace 必须同源映射到批次认可集合并保留原始值

系统 SHALL 只把同源 ID 映射为滚动批次认可的 namespace（netkeiba URL→`netkeiba:{id}`、NAR `k_lineageLoginCode`→`nar:{id}`、HKJC `horseid`→`hkjc:{id}`、Sporting Life `horse_id`→`sporting_life:{id}`），identity key 一律 casefold 写入。zeturf runner ID 与 geny 马 ID 不同源，系统 MUST NOT 生成 `geny:{id}` key；HRN slug 同理。原始 namespace 与原始值 MUST 保留在证据字段。

#### Scenario: ZEturf ID 不映射只留证据

- **WHEN** 法国赛事行的 `source_refs.horse_id` 来自 ZEturf
- **THEN** 系统 MUST NOT 生成 `geny:{id}` identity key
- **AND** `identity_evidence` SHALL 记录原始 namespace `zeturf` 与原始 ID

#### Scenario: 四字段只填空列

- **WHEN** ExternalHorse 记录提供父、母、出生日期，且 profile 对应列为空
- **THEN** 系统 SHALL 写入 `sire_text` / `dam_text` / `birth_date`
- **AND** 既有值与证据不一致时 MUST NOT 覆盖，并记录身份冲突

### Requirement: 回填写入必须经 dry-run artifact 与人工批准

系统 SHALL 默认只输出 dry-run artifact（候选清单、冲突增量、前后对比、SHA-256 manifest）；commit MUST 要求显式批准的 manifest SHA，按地区分批单事务执行，identity keys 合并写入 MUST 幂等。

#### Scenario: 未批准不得写入

- **WHEN** 操作者未提供经批准的 manifest SHA 即执行 commit
- **THEN** 系统 SHALL fail closed，不修改任何 profile 或 P0 来源

#### Scenario: 重复 commit 幂等

- **WHEN** 对同一批准 artifact 重复执行 commit
- **THEN** identity keys 与 evidence SHALL 不产生重复项
- **AND** 对账输出 planned write 为 0

### Requirement: 身份冲突必须聚合为可治理队列

系统 SHALL 按"规范化马名 + 候选 profile 集合 + 原因"聚合 pending `HorseIdentityConflict`，输出每组冲突数、涉及赛事数、强身份证据状态与建议动作（`resolvable_with_identity / needs_admin_review / insufficient_evidence`）。

#### Scenario: 聚合统计只读输出

- **WHEN** 操作者运行冲突聚合统计
- **THEN** 系统 SHALL 输出分组统计 artifact 与 SHA-256 manifest
- **AND** MUST NOT 修改任何冲突记录

#### Scenario: 批量裁决必须经人工批准

- **WHEN** 某分组在回填后具备四字段或 external ID 唯一对齐证据
- **THEN** 系统 MAY 生成 resolved 建议
- **AND** 只有在人工批准 manifest 后，系统才通过既有 resolved 通道写回，写回 MUST 经过既有校验与 reopen 保护
