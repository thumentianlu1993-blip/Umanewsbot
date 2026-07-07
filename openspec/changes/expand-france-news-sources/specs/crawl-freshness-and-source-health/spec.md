## ADDED Requirements

### Requirement: 法国候选新闻源必须可只读探测
系统 SHALL 为法国候选新闻源提供只读探测能力，在写入 `NewsSource` 或开启生产抓取前验证列表页和详情页是否稳定可解析。探测 MUST 不创建 `NewsArticle`、`CrawlJob` 或生产窗口记录。

#### Scenario: 探测成功输出样本
- **WHEN** 运维人员对法国候选来源执行只读探测
- **THEN** 系统 SHALL 输出 HTTP 状态、最终 URL、列表解析数量、样本标题、样本 URL、详情正文长度和发布时间
- **AND** 系统 SHALL NOT 写入新闻业务表

#### Scenario: 访问受限来源被标记
- **WHEN** 法国候选来源返回 `403`、`429`、验证码、反机器人页面或空样本
- **THEN** 探测结果 SHALL 标记该来源为访问受限或不可稳定解析
- **AND** 该来源默认 SHALL NOT 被生产批准

#### Scenario: 样本重复率过高时提示覆盖不足
- **WHEN** 法国候选来源探测到的样本 URL 大多已存在于生产库
- **THEN** 探测结果 SHALL 输出重复数量或重复比例
- **AND** 运维人员 SHALL 能据此判断该来源对新增量贡献有限

### Requirement: 新法国来源健康必须展示解析质量
系统 SHALL 在来源健康摘要中展示新增法国来源的解析质量，使工作人员能判断该来源是无新增、解析失败还是上游访问异常。

#### Scenario: 法国来源详情解析失败
- **WHEN** 法国来源列表可抓但详情页正文为空或缺少标题
- **THEN** 抓取记录和来源健康 SHALL 展示详情解析失败摘要
- **AND** 同轮其他可解析文章 SHALL 继续处理

#### Scenario: 法国来源重复旧稿
- **WHEN** 法国来源抓取成功但新增为 0 且重复数量大于 0
- **THEN** 来源健康 SHALL 展示成功无新增和重复数量
- **AND** 不得展示为失败

#### Scenario: 法国来源触发 backoff
- **WHEN** 法国来源连续出现访问受限或网络失败
- **THEN** 系统 SHALL 按现有来源 backoff 策略降低抓取频率或暂停该来源
- **AND** 来源健康 SHALL 展示 backoff 截止时间和最近错误类别
