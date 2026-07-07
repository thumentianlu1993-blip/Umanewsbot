## ADDED Requirements

### Requirement: 首页必须提供我的关注模块
系统 SHALL 在公开首页提供“我的关注”模块或标签页，用于展示当前匿名关注 token 覆盖范围内的已发布相关新闻。关注流 MUST 基于 `ArticleHorseLink(auto/manual)` 判断命中马匹，不得重新扫描文章文本。

#### Scenario: 展示关注马相关新闻
- **WHEN** 当前浏览器存在 `follower_token` 且关注了已发布马匹
- **THEN** 首页“我的关注”模块 SHALL 展示该关注马相关的已发布文章
- **AND** 文章 SHALL 按公开发布时间倒序展示

#### Scenario: 展示后代相关新闻
- **WHEN** 用户关注某马并设置 `include_descendants=true`
- **THEN** 首页“我的关注”模块 SHALL 展示该马本身、直接子代和孙代相关的已发布文章
- **AND** 命中关系 SHALL 基于父母 `HorseProfile` 外键计算

#### Scenario: 关注流不重新扫描正文
- **WHEN** 某篇文章文本包含关注马名称但没有 `ArticleHorseLink(auto/manual)`
- **THEN** 首页“我的关注”模块 SHALL 不展示该文章
- **AND** 系统 SHALL 通过关联扫描或后台确认先建立可用 `ArticleHorseLink`

#### Scenario: 无关注时显示轻量空状态
- **WHEN** 当前浏览器没有关注任何马匹
- **THEN** 首页 SHALL 显示轻量空状态或隐藏关注文章列表
- **AND** 不得影响综合、日本、香港、英国、法国和美国地区资讯流

#### Scenario: 关注模块不暴露匿名 token
- **WHEN** 首页渲染“我的关注”模块或管理入口
- **THEN** 页面 SHALL 只使用服务端从签名 cookie 解析出的关注范围
- **AND** 不得在 HTML、JavaScript、日志或链接参数中输出明文 `follower_token`

### Requirement: 关注模块必须提供管理入口
系统 SHALL 在首页关注模块提供管理入口，让当前匿名 token 用户查看已关注马匹、取消关注和调整是否包含后代。

#### Scenario: 管理关注马列表
- **WHEN** 用户打开关注管理入口
- **THEN** 系统 SHALL 列出当前 `follower_token` 下的关注马匹
- **AND** 每条关注 SHALL 显示是否包含后代

#### Scenario: 取消关注后首页移除相关新闻
- **WHEN** 用户取消关注某马
- **THEN** 系统 SHALL 删除或停用对应关注关系
- **AND** 后续首页“我的关注”模块 SHALL 不再因该马展示相关新闻

#### Scenario: 调整后代订阅范围
- **WHEN** 用户关闭或开启某关注的后代订阅
- **THEN** 首页“我的关注”模块 SHALL 按新的 `include_descendants` 设置重新计算文章范围

### Requirement: 新闻详情页必须展示相关马匹 tag
系统 SHALL 在公开新闻详情页下方 tag 区展示与该文章关联且已发布的马匹 tag。马匹 tag MUST 链接到 `/horses/<id>/`。

#### Scenario: 详情页展示已发布相关马匹 tag
- **WHEN** 已发布文章存在 `ArticleHorseLink(auto/manual)` 且关联马匹为 `published`
- **THEN** 新闻详情页 SHALL 在 tag 区展示该马匹
- **AND** 点击 tag SHALL 进入 `/horses/<id>/`

#### Scenario: 详情页不展示未公开马匹
- **WHEN** 已发布文章关联的马匹处于 `draft`、`ready` 或 `hidden`
- **THEN** 新闻详情页 SHALL 不展示该马匹 tag

#### Scenario: 候选和移除关联不展示
- **WHEN** 文章存在 `ArticleHorseLink(candidate)` 或 `ArticleHorseLink(removed)`
- **THEN** 新闻详情页 SHALL 不展示这些关联对应的马匹 tag
