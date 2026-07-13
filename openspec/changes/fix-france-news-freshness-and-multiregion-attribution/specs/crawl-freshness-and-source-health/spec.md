## ADDED Requirements

### Requirement: TDN 法国来源必须按发布时间发现最新稿 <!-- id: req-tdn-date-search -->
系统 SHALL 使用支持按真实发布时间倒序的 TDN posts 查询发现法国相关稿，并 MUST 在请求和本地校验两层限制新鲜度。相关度排序的历史搜索结果 MUST NOT 作为生产最新稿入口。

#### Scenario: 按日期获取最近法国稿
- **WHEN** TDN 在最近 3 天发布命中已审核法国查询的文章
- **THEN** 法国来源 SHALL 能在日期倒序结果中发现该文章
- **AND** SHALL 保存 API 返回的真实 `date_gmt` 作为发布时间证据

#### Scenario: 历史高相关稿不挤占新稿
- **WHEN** 某关键词同时存在大量历史高相关稿和最近发布稿
- **THEN** 系统 SHALL 优先处理最近发布稿
- **AND** MUST NOT 因固定页历史结果占满而漏掉最近稿

### Requirement: 来源发布时间必须保存证据与可信度 <!-- id: req-published-evidence -->
系统 SHALL 为来源发布时间保存原始值、证据来源和是否 verified。API 或详情页明确时间可标记为 verified；抓取时刻 fallback MUST 标记为不可信。

#### Scenario: France Galop 详情时间被解析
- **WHEN** France Galop 英文详情页包含官方日期和时间
- **THEN** 系统 SHALL 将其解析为带时区的 `published_at`
- **AND** SHALL 保存原始日期文本和详情 URL 作为证据

#### Scenario: 日期无法解析
- **WHEN** 详情页没有可识别官方发布时间
- **THEN** 系统 MAY 使用 fallback 时间维持入库
- **AND** MUST 标记该时间为不可信并阻止自动发布

#### Scenario: 历史未知可信度保持兼容
- **WHEN** 迁移前文章没有发布时间可信度记录
- **THEN** 系统 SHALL 将其视为 legacy unknown
- **AND** MUST NOT 因新增字段自动撤回或阻断全部历史文章

### Requirement: 不可信 fallback 时间不得污染已有文章 <!-- id: req-fallback-preservation -->
系统 MUST NOT 在重复抓取时使用不可信 fallback 时间覆盖已有可信或既有发布时间。后续取得可信时间时，系统 SHALL 允许受审计地纠正发布时间。

#### Scenario: 重复抓取不刷新旧文时间
- **WHEN** 已有文章再次从只提供 fallback 时间的列表出现
- **THEN** 系统 MUST 保留原 `published_at`
- **AND** 只更新 `last_seen_at` 和抓取快照

#### Scenario: 可信详情时间纠正 fallback
- **WHEN** 文章原时间为不可信 fallback 且后续取得 verified 详情时间
- **THEN** 系统 SHALL 将 `published_at` 修正为 verified 时间
- **AND** SHALL 保存 before/after 和证据

### Requirement: 历史错误时间修复必须受控 <!-- id: req-time-repair -->
系统 SHALL 提供 dry-run/manifest/commit 流程修复受影响文章时间。commit MUST 校验文章状态和输入未漂移，并 MUST NOT 直接重新发布文章或创建 QQ 交付。

#### Scenario: 时间修复 dry-run
- **WHEN** 运维对 France Galop 近期文章执行时间修复 dry-run
- **THEN** 系统 SHALL 输出文章 ID、旧时间、可信新时间、证据和预计状态影响
- **AND** SHALL NOT 写入业务数据

#### Scenario: 锁定 manifest 提交
- **WHEN** 运维提交已审核且未漂移的时间修复 manifest
- **THEN** 系统 SHALL 原子更新允许范围内的发布时间及证据
- **AND** MUST NOT 直接触发网页重复发布或 QQ 推送
