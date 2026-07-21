# race-name-translation-import Delta

## ADDED Requirements

### Requirement: 输入锁定与身份对照

导入工具 SHALL 以 SHA-256 锁定五份最终审核工作簿（日本另锁修订前基线），逐行对照 `docs/collected_complete_race_names_missing_zh_20260719.md` 身份基线，并且输入哈希与解析 MUST 消费同一份 bytes。日本最终输入 MUST 由修订前基线产生，语义差异 allowlist 仅允许序号 64 的“建议中文名”从“京成杯秋季让赛”变为“京成杯秋季赛”。

完整规则以 `docs/changes/import-reviewed-race-name-translations/spec.md` 为权威。

#### Scenario: 输入 SHA 漂移

- **WHEN** 任一锁定工作簿的 SHA-256、结构、行数或身份列与锁定值不一致
- **THEN** 工具 MUST fail closed，不生成 manifest、dry-run 或任何 apply-ready 结论

#### Scenario: 日本修订多点差异

- **WHEN** 日本最终输入与修订前基线相比出现序号 64 译名单元格以外的任何业务差异
- **THEN** 工具 MUST 阻断，不进入候选生成

### Requirement: 让赛标记不进入中文展示名

最终中文名 MUST NOT 包含“让赛 / 讓賽 / 让步赛 / 讓步賽”，原文 `(H)`、独立 `H`、`Handicap` 及其直接包裹括号 MUST NOT 进入中文展示名；工具 SHALL 只删除这些标记，不补写其他词，并同时保存审核原值、调整后值与规则说明。

#### Scenario: 京成杯秋季赛精确值

- **WHEN** 处理日本 `Keisei Hai Autumn H` 分组
- **THEN** 最终中文名 MUST 精确为“京成杯秋季赛”，影响 2010–2025 共 16 场，任何“京成杯秋季”或“京成杯秋季让赛”值 MUST NOT 进入正式 manifest

#### Scenario: 让赛清理越界

- **WHEN** 清理逻辑试图折叠无关空格、删除无关尾部标点或改写为新词（如“锦标”）
- **THEN** 工具 MUST fail closed

### Requirement: 只读 dry-run 与分类门禁

工具 SHALL 对生产当前值执行只读比较并分类为 `would_update / already_applied / conflict / locked / missing / out_of_scope`；存在任一 `conflict`、`locked`、`missing`、输入错误、快照漂移或香港修正不唯一时顶层 `apply_ready` MUST 为 `false`。生产快照 MUST 在前后各读一次运行时 metadata（checkout HEAD、容器 image ID/tag、started-at）并精确比较。

#### Scenario: 人工锁阻断

- **WHEN** 目标 RaceSeries 的 `manual_lock_flags.chinese_name` 为真，或 RaceEvent 对应字段锁为真
- **THEN** 该对象 MUST 分类为 `locked` 并阻断整批 apply-ready

#### Scenario: 快照漂移

- **WHEN** 两轮生产完整快照 SHA 不一致，或 snapshot 前后运行时 metadata 任一变化
- **THEN** 候选生成 MUST 失败，不得复用旧快照

### Requirement: 写入目标集合固定且逐对象 CAS

正式 apply MUST 只更新 `1300` 个 `RaceSeries.chinese_name`、`8883` 个 `RaceEvent.chinese_name`（`8663` 审核表年度赛事 + Event `96` + `219` 同系列原文回退）以及香港 Event `16446` 的 `race_series_id/series_key` 与 HistoricalRaceEventTarget `49052` 的 `race_series_id`，并在单个事务中对 `eventScope` 全部父子对象执行完整行 compare-and-swap。已有独立中文名的范围外 Event MUST NOT 被覆盖（唯一例外 Event `96`）；supplemental Event MUST 同时匹配 RaceSeries ID、series key 与地区。

#### Scenario: 香港身份修正同步

- **WHEN** 执行香港 `SURFACE Bauhinia Sprint Trophy(H)` 2012 修正
- **THEN** RaceEvent `16446` 与 HistoricalRaceEventTarget `49052` MUST 同事务改绑到 RaceSeries `5963`，`original_name` 不变；只改一侧或目标系列/年份冲突 MUST 阻断整批

#### Scenario: 非 allowlist 独立中文名

- **WHEN** 范围外 Event 已有独立中文名（无论是否含让赛标记）
- **THEN** 该 Event MUST NOT 进入 supplemental action，仅出现在 out-of-scope 报告

#### Scenario: CAS 漂移

- **WHEN** 事务内任一父系列、子集合、系列归属或非动作行完整 SHA 与冻结快照不一致
- **THEN** 整批 MUST 回滚，禁止拆批续写

### Requirement: 受审 bundle、审计与回滚

生产执行 MUST 只接受精确十二成员的受审 bundle；apply/rollback/verifier 命令 MUST 显式接收锁定的 `bundle-index.json` 原始 SHA-256，并在各阶段重算全部成员。apply 成功 MUST 恰写一条 `race_name_translations_applied` OperationLog 并绑定八项 artifact SHA；对象级 rollback 只在 after-state 完整行精确匹配时允许，否则 MUST 转入人工事故处置。

#### Scenario: bundle 成员被篡改

- **WHEN** 任一 bundle 成员、index 内容身份或 index 原始 SHA 与锁定值不一致
- **THEN** 当前阶段 MUST 立即停止，不得进入写入

#### Scenario: rollback after-state 漂移

- **WHEN** 执行对象级 rollback 时任一目标当前完整行不等于本批 after 快照
- **THEN** 工具 MUST 禁止强制覆盖，保留 bundle、日志和备份并升级为人工事故决策
