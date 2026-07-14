# international-racing-coverage Specification Delta

## ADDED Requirements

### Requirement: 国际新闻来源必须声明可验证的正文边界
每个进入生产自动抓取的国际新闻适配器 SHALL 声明可离线测试的正文选择器和来源级清理规则。正文节点缺失 SHALL 被视为页面结构漂移或解析失败，不得通过整页文本兜底掩盖。

#### Scenario: 新增国际新闻来源
- **WHEN** 系统新增一个可进入审核、翻译或自动发布链路的国际新闻来源
- **THEN** 该来源 SHALL 提供正文选择器 fixture 测试
- **AND** 测试 SHALL 证明导航、页脚和来源模板不会进入正文

#### Scenario: 既有国际来源页面结构漂移
- **WHEN** 已启用来源的页面不再匹配已验证正文结构
- **THEN** 系统 SHALL 将该文章留在不可发布或人工处理状态
- **AND** 抓取摘要 SHALL 提供足以定位来源和选择器的失败信息
