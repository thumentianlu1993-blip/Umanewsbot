## ADDED Requirements

### Requirement: 法国英文来源必须覆盖最新赛事与行业内容 <!-- id: req-france-english-coverage -->
系统 SHALL 通过 France Galop 英文页和按日期查询的全球英文来源发现法国赛事、赛果、赛前预测、马匹/从业者、育马、拍卖、马场和机构新闻。来源文章 MUST 继续经过去重、新鲜度、翻译和发布门禁。

#### Scenario: 法国赛事新稿进入法国候选
- **WHEN** 英文来源发布以法国赛事或法国马场为中心的最新文章
- **THEN** 系统 SHALL 将法国作为主地区或相关地区候选
- **AND** 文章 SHALL 进入现有法国生产链路

#### Scenario: 法国育马与拍卖内容进入新闻池
- **WHEN** 英文稿以法国育马场、法国拍卖或法国赛马机构为主题
- **THEN** 系统 SHALL 将法国保存为可信归属
- **AND** MUST NOT 仅因文章不报道具体比赛而排除

### Requirement: 全球来源的法国稿不得被来源默认地区吞没 <!-- id: req-global-france-attribution -->
系统 MUST 依据文章内容归属全球英文来源文章。来源默认地区 SHALL 仅在没有可信事件或核心对象证据时使用。

#### Scenario: TDN 巴黎大奖赛稿进入法国池
- **WHEN** TDN 全球最新流发布以 Grand Prix de Paris 或 ParisLongchamp 为中心的文章
- **THEN** 系统 SHALL 将法国纳入文章地区归属
- **AND** MUST NOT 仅因 TDN 默认地区是美国而只归属美国

#### Scenario: 无法国内容时沿用来源 fallback
- **WHEN** 全球来源文章没有法国赛事、对象或主题证据
- **THEN** 系统 SHALL NOT 因宽关键词的背景噪声加入法国
- **AND** MAY 使用来源默认地区作为 fallback

### Requirement: 法国宽查询必须可配置并可审计 <!-- id: req-france-query-audit -->
系统 SHALL 维护审核过的法国查询集合，并为每个候选记录命中查询、真实发布时间、去重结果和内容归属结果。新增查询 MUST 先通过只读样本审计。

#### Scenario: 查询命中证据可追溯
- **WHEN** 一篇文章由法国宽查询发现
- **THEN** 系统 SHALL 保存命中的查询和列表请求证据
- **AND** 运营 SHALL 能区分查询命中与最终法国归属

#### Scenario: 新关键词先审计
- **WHEN** 运维准备增加新的法国关键词或赛事名称
- **THEN** 系统 SHALL 支持只读输出近期命中样本和误报情况
- **AND** 未批准查询 MUST NOT 进入生产来源配置
