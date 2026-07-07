## ADDED Requirements

### Requirement: 法国 TDN 关键词来源必须使用真实发布时间并过滤历史搜索结果
系统 SHALL 在处理法国 `TDN` 关键词英文新闻来源时，使用 TDN post API 的真实发布时间作为文章发布时间，并过滤搜索接口返回的历史旧文。系统 MUST NOT 因 search item 缺少日期而把历史文章标记为当前时间。

#### Scenario: search item 通过 post API 补真实日期
- **WHEN** `tdn_france_broad` 从 TDN search API 获得只包含 `id/title/url` 且不包含 `date/date_gmt` 的 search item
- **THEN** 系统 SHALL 使用 search item 的 `id` 或 `_links.self` 拉取对应 post API
- **AND** 系统 SHALL 从 post API 的 `date_gmt` 或 `date` 解析文章真实发布时间

#### Scenario: 历史旧文被新鲜度过滤
- **WHEN** TDN search API 返回一篇真实发布时间早于允许新鲜度窗口的历史文章
- **THEN** 系统 SHALL 跳过该文章
- **AND** 系统 SHALL NOT 创建或更新 `NewsArticle`
- **AND** 系统 SHALL 在抓取或探测摘要中保留跳过原因

#### Scenario: 无法取得真实 post 日期时跳过
- **WHEN** TDN search item 的 post API 不可访问、缺少 `date/date_gmt` 或日期无法解析
- **THEN** 系统 SHALL 跳过该条 search item 并继续处理同一轮其他条目
- **AND** 系统 SHALL NOT 将该文章发布时间兜底为当前时间

#### Scenario: 真实近期文章仍可入库
- **WHEN** TDN search item 的 post API 返回真实发布时间且该时间在允许新鲜度窗口内
- **THEN** 系统 SHALL 按既有 TDN canonical 去重规则创建或更新文章
- **AND** 入库文章 SHALL 保留法国来源配置语义
