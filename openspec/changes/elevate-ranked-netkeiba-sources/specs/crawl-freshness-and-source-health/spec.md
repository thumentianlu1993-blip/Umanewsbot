## ADDED Requirements

### Requirement: netkeiba 榜单命中必须提升新着来源文章
系统 SHALL 在同一 netkeiba 文章先由新着顺入库、后续又被访问量榜或注目数榜命中时，将文章主来源从 `netkeiba:latest` 提升为对应榜单来源，同时继续记录榜单快照。

#### Scenario: 新着顺文章被访问量榜命中
- **WHEN** 已存在文章的 `source_site=netkeiba`、`source_mode=latest`，且同一 `source_article_id` 被 `source_mode=access` 的抓取 draft 命中
- **THEN** 系统 SHALL 将该文章的 `source_mode` 更新为 `access`
- **AND** 系统 SHALL 创建一条 `source_mode=access` 的 `NewsSnapshot`

#### Scenario: 新着顺文章被注目数榜命中
- **WHEN** 已存在文章的 `source_site=netkeiba`、`source_mode=latest`，且同一 `source_article_id` 被 `source_mode=attention` 的抓取 draft 命中
- **THEN** 系统 SHALL 将该文章的 `source_mode` 更新为 `attention`
- **AND** 系统 SHALL 创建一条 `source_mode=attention` 的 `NewsSnapshot`

#### Scenario: 访问量榜不被注目数榜覆盖
- **WHEN** 已存在文章的 `source_site=netkeiba`、`source_mode=access`，且同一 `source_article_id` 被 `source_mode=attention` 的抓取 draft 命中
- **THEN** 系统 SHALL 保持该文章的 `source_mode=access`
- **AND** 系统 SHALL 仍创建一条 `source_mode=attention` 的 `NewsSnapshot`

#### Scenario: 注目数榜不被访问量榜覆盖
- **WHEN** 已存在文章的 `source_site=netkeiba`、`source_mode=attention`，且同一 `source_article_id` 被 `source_mode=access` 的抓取 draft 命中
- **THEN** 系统 SHALL 保持该文章的 `source_mode=attention`
- **AND** 系统 SHALL 仍创建一条 `source_mode=access` 的 `NewsSnapshot`

#### Scenario: 新着顺不覆盖榜单来源
- **WHEN** 已存在文章的 `source_site=netkeiba`、`source_mode=access` 或 `source_mode=attention`，且同一 `source_article_id` 再次被 `source_mode=latest` 的抓取 draft 命中
- **THEN** 系统 SHALL 保持该文章当前榜单 `source_mode`
- **AND** 系统 SHALL 仍创建一条 `source_mode=latest` 的 `NewsSnapshot`

#### Scenario: 来源配置同步更新
- **WHEN** 系统将文章主来源从 `latest` 提升为 `access` 或 `attention`
- **THEN** 系统 SHALL 同步更新该文章的 `source_config` 和 `source_note`，使后台展示与主来源一致

#### Scenario: 来源提升结果可被后续流程检测
- **WHEN** 系统在一次入库更新中将文章主来源从 `latest` 提升为 `access` 或 `attention`
- **THEN** 入库结果 SHALL 暴露本轮发生来源提升的稳定信号，使后续流程可以判断该文章刚刚成为榜单重点新闻
