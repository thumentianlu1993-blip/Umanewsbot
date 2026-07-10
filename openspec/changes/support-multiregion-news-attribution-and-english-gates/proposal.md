## Why

香港、英国、法国新增新闻源前，系统需要先解决跨地区新闻归属、地区 tab 展示、QQ 订阅匹配和英文门禁分层问题。否则新增来源虽然能提高抓取量，但仍可能出现“抓到了却发不出去”、英国源报道法国赛事却只进英国池、或多地区新闻无法触达对应地区用户的问题。

## What Changes

- 引入文章多地区归属：保留现有 `NewsArticle.racing_region` 作为主地区，新增相关地区能力，使同一篇文章可以出现在多个地区 tab，但详情页和综合流仍只保留一篇文章。
- 建立自动地区归属规则：赛事发生地优先，其次核心对象所属地区，再退回来源默认地区；英国源中的爱尔兰内容暂归英国并保留 `ireland` 标签；人工调整保存最终结果即可，不新增额外操作日志。
- 调整发布窗口和配额语义：多地区文章只占主地区发布配额；相关地区可用于判断该地区窗口已有内容，但不消耗该地区发布上限。
- 调整 QQ 自动推送地区匹配：群订阅任一主地区或相关地区即可收到文章，同一篇文章对同一群仍只发送一次；消息展示主地区和必要相关地区标签。
- 扩展后台与审计：候选详情、文章编辑、地区生产概览、发布窗口账本和只读审计必须展示主地区、相关地区、自动归属原因和门禁原因。
- 在已上线 `fix-english-term-gate-region-filter` 与 `classify-english-term-gate-context` 基础上进一步分层英文门禁：普通词误挡继续降级；可信核心专名仍保护；`preview / result_brief / official_notice / racecard_update / tips / feature / sales_breeding` 等内容类别允许配置不同自动发布和 QQ 资格。
- 提供受控重处理/回填入口：可对近期候选重新计算主地区、相关地区和门禁结果；dry-run 默认只输出影响范围，commit 不直接公开发布文章。

## Capabilities

### New Capabilities
- `multiregion-news-attribution`: 定义新闻文章主地区、相关地区、自动识别、人工调整、前台地区 tab、发布配额和 QQ 匹配的统一归属能力。

### Modified Capabilities
- `multiregion-news-production`: 发布窗口、地区生产审计和地区概览需要识别主地区与相关地区，并按新配额语义处理多地区文章。
- `automation-publish-gates`: 英文门禁需要结合内容类别、主/相关地区和既有语义分类结果做更细分的 blocker / warning / info 决策。
- `qqbot-auto-push`: QQ 群地区匹配需要从单一文章地区扩展为主地区或相关地区命中，且同群同文继续幂等去重。
- `public-home-info-feed`: 地区 tab 需要展示主地区或相关地区命中的已发布文章，同时综合流保持单篇去重。
- `international-racing-coverage`: 国际新闻来源不再只能固定继承来源地区；英文全球来源可按内容实体归属到目标地区，法国仍不得接入法语正文主链路。

## Impact

- 数据模型：可能新增 `NewsArticle` 相关地区字段或关联表，以及必要索引；现有 `racing_region` 保持主地区语义。
- 服务层：影响新闻入库、地区归属服务、自动评分/门禁、发布窗口候选选择、地区审计、QQ 推送资格判断和公开首页查询。
- 后台与前台：候选详情、文章编辑、地区生产概览、公开首页地区 tab、文章详情和 QQ 消息需要展示多地区信息。
- 运维：需要新增 dry-run 审计和受控重处理命令；上线前后需记录生产只读审计、样本回填范围和验证结果。
- 不包含新增具体新闻源适配器；来源扩容由后续 `expand-international-news-source-pool` change 承接。
