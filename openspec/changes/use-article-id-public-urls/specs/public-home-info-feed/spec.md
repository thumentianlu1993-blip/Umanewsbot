## MODIFIED Requirements

### Requirement: 文章详情页与公开首页视觉一致
系统 SHALL 使文章详情页复用公开站点基础布局和样式。详情页主 URL MUST 使用全局唯一文章 ID，格式为 `/news/<article_id>/`。详情页必须继续展示标题、摘要、正文、封面、标签、来源说明、原文链接和发布时间，并保持移动端阅读体验。系统 MUST 保留旧标题 slug URL 的兼容入口，并将可公开访问的非纯数字旧 slug URL 跳转到对应 ID URL。

#### Scenario: 详情页通过文章 ID 访问
- **WHEN** 用户访问已发布文章的 `/news/<article_id>/`
- **THEN** 系统展示该文章的有效标题、摘要、正文、来源、原文链接和发布时间

#### Scenario: 详情页优先使用有效稿件字段
- **WHEN** 文章存在人工稿、AI 改写稿或基准翻译稿
- **THEN** 详情页继续按照现有有效字段优先级展示公开内容

#### Scenario: 非纯数字旧 slug URL 跳转到 ID URL
- **WHEN** 用户访问已发布文章的非纯数字旧 `/news/<slug>/`
- **THEN** 系统 SHALL 跳转到该文章的 `/news/<article_id>/`

#### Scenario: 未发布文章 ID 不公开
- **WHEN** 用户访问未发布文章的 `/news/<article_id>/`
- **THEN** 系统 SHALL 返回未找到或等价的非公开响应

#### Scenario: 首页链接使用 ID URL
- **WHEN** 用户访问公开首页并查看文章链接
- **THEN** 首页头条、普通新闻流和热门代理 SHALL 使用 `/news/<article_id>/` 链接

#### Scenario: 移动端详情页可阅读
- **WHEN** 用户在移动端宽度访问文章详情页
- **THEN** 标题、封面、正文、来源和原文链接不发生遮挡，并保持适合移动阅读的行宽和间距
