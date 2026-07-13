# news-content-boundary-cleaning Specification

## ADDED Requirements

### Requirement: 国际新闻必须命中可信正文节点
系统 SHALL 只从来源适配器声明的可信正文节点提取国际新闻主体。系统 MUST NOT 在正文选择器未命中时回退到整页 `body` 并继续发布，且 SHALL 记录可审计的解析状态与选择器信息。

#### Scenario: 来源选择器命中正文
- **WHEN** 国际新闻详情页包含该来源声明的可信正文节点
- **THEN** 系统 SHALL 只从该节点及允许的正文子节点生成 `body_ja_raw`
- **AND** 解析元数据 SHALL 记录命中的选择器和成功状态

#### Scenario: 来源选择器没有命中
- **WHEN** 国际新闻详情页不包含该来源声明的任何可信正文节点
- **THEN** 系统 SHALL 返回空正文或等价不可发布结果
- **AND** 系统 SHALL 记录 `selector_not_found` 或等价失败原因
- **AND** 系统 MUST NOT 使用整页 `body` 作为正文兜底

#### Scenario: 正文清理后没有剩余内容
- **WHEN** 可信正文节点命中但其中内容全部属于模板或博彩噪声
- **THEN** 系统 SHALL 返回空正文或等价不可发布结果
- **AND** 系统 SHALL 记录 `empty_after_cleaning` 或等价失败原因
- **AND** 系统 MUST NOT 把清理前节点或整页文本恢复为正文

### Requirement: 系统必须移除正文容器内的来源模板噪声
系统 SHALL 在翻译前移除正文容器内的导航、登录、分享、推荐、下载、版权、页脚、编辑注和跨页跳转 CTA 等非新闻主体内容。清理规则 SHALL 按来源和独立结构或段落生效，并保留真实新闻段落和图片说明。

#### Scenario: Sporting Life 页面包含站点框架
- **WHEN** Sporting Life 页面在新闻主体附近包含导航、登录、分享、推荐、责任博彩提示或页脚
- **THEN** 清理后的正文 SHALL NOT 包含这些模板区块
- **AND** 清理后的正文 SHALL 保留新闻标题之后的真实报道段落

#### Scenario: TDN 正文含编辑注和读者跳转
- **WHEN** TDN 正文节点以 `Editor's Note` 或纯跳转说明开头并以 `Read Today's Paper` 结束
- **THEN** 系统 SHALL 删除前导编辑注、纯跳转说明和尾部跳转
- **AND** 系统 SHALL 保留两者之间的新闻主体

#### Scenario: 正文以完整赛果活动链接收尾
- **WHEN** 正文尾部出现仅引导读者查阅完整赛果或活动详情的独立 CTA 段落
- **THEN** 系统 SHALL 删除该 CTA 及其后的模板内容
- **AND** 该 CTA SHALL NOT 进入翻译正文或公开文章

#### Scenario: 正文提及与边界标记相似的普通句子
- **WHEN** 新闻主体中间的普通句子包含与某个边界标记相似但不构成独立模板段落的文字
- **THEN** 系统 SHALL 保留该句子
- **AND** 系统 SHALL NOT 从该处截断正文

### Requirement: 博彩内容必须默认屏蔽并保护明确例外
系统 SHALL 在翻译前尽可能移除下注号召、投注建议、优惠、免费投注、博彩导流和责任博彩等非新闻主体段落。系统 SHALL 保留赛事标题、马主等专有名词内的博彩公司名称，以及作为新闻事实出现的赔率。

#### Scenario: 段落是博彩推广或投注建议
- **WHEN** 正文候选段落主要内容是下注号召、投注建议、优惠、免费投注、博彩导流或责任博彩说明
- **THEN** 系统 SHALL 删除该段落
- **AND** 系统 SHALL 记录博彩噪声过滤原因

#### Scenario: 公司名属于赛事标题或其他专有名词
- **WHEN** 博彩公司名称是赛事标题、马主或其他专有名词不可分割的一部分
- **THEN** 系统 SHALL 保留该名称及其所属新闻事实

#### Scenario: 段落报告赔率
- **WHEN** 段落以新闻事实方式报告马匹或赛事赔率且不构成投注优惠或下注号召
- **THEN** 系统 SHALL 保留该赔率内容

### Requirement: 正文清理必须可回归和可审计
系统 SHALL 为正文清理输出成功状态、命中选择器、移除规则与计数等结构化摘要。测试 SHALL 使用问题页面的本地精简 fixture，不依赖实时外网页面。

#### Scenario: 清理成功并移除噪声
- **WHEN** 适配器完成正文选择和清理
- **THEN** 详情元数据 SHALL 包含正文解析状态和移除内容的规则摘要或计数
- **AND** 翻译元数据 SHALL NOT 复制整页 HTML

#### Scenario: 生产页面结构发生漂移
- **WHEN** 某来源页面结构变化导致可信正文选择器不再命中
- **THEN** 离线 fixture 测试或抓取摘要 SHALL 能明确显示选择器失败
- **AND** 系统 SHALL 阻止该页面框架进入公开正文

### Requirement: 指定历史文章必须受控重建并保持公开身份
系统 SHALL 在部署并备份后，对文章 `8086`、`8267`、`8316`、`8318` 使用新的正文规则重解析、重译和校验。修复 SHALL 更新既有已发布文章并保持其公开状态，不得创建重复公开文章、重复发布动作或重复 QQ 分发。

#### Scenario: 重建四篇问题文章
- **WHEN** 运维人员执行本变更的生产历史修复
- **THEN** 四篇文章 SHALL 使用清理后的正文完成翻译和公开更新
- **AND** 公开文章 ID SHALL 保持不变
- **AND** 既有发布状态与原发布时间 SHALL 保持不变
- **AND** 系统 SHALL NOT 创建新的 QQ delivery
- **AND** 页面框架、编辑注、跳转 CTA 与不允许的博彩内容 SHALL NOT 出现在公开正文

#### Scenario: 历史修复失败
- **WHEN** 任一文章无法命中正文、翻译失败或校验不通过
- **THEN** 系统 SHALL 停止该文章的公开替换并保留失败证据
- **AND** 其他文章的处理结果 SHALL 可独立审计和回滚

#### Scenario: 正文修复命令默认 dry-run
- **WHEN** 运维人员未提供显式 commit 参数运行指定文章修复
- **THEN** 系统 SHALL 输出正文前后哈希、长度、解析状态和清理规则摘要
- **AND** 系统 SHALL NOT 修改文章、翻译、发布状态或 QQ delivery

#### Scenario: 强制重译已批准的问题文章
- **WHEN** 运维人员以显式文章 ID 和强制参数同步重译已确认需要替换的公开稿
- **THEN** 系统 SHALL 复用既有翻译 provider、`TranslationRun` 和译文写回逻辑覆盖该文章中文稿
- **AND** 强制参数 SHALL 默认关闭
- **AND** 翻译失败 SHALL 留下失败状态和日志而不得再次发布或推送
