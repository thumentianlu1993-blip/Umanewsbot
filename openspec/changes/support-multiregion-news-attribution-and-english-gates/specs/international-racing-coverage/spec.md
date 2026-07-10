## ADDED Requirements

### Requirement: 国际英文来源必须支持按内容归属地区
系统 SHALL 支持将英文国际来源或英国来源中的文章按内容实体归属到日本、中国香港、英国、法国或美国，而不是仅按来源默认地区入库。来源默认地区 SHALL 只作为无法识别赛事或核心实体时的 fallback。

#### Scenario: 英国来源报道法国赛事归属法国
- **WHEN** 英国英文来源文章明确报道法国境内赛事
- **THEN** 系统 SHALL 将法国纳入该文章地区归属
- **AND** 系统 SHALL NOT 仅因来源默认地区是英国而只归属英国

#### Scenario: 英国来源无明确实体时归属英国
- **WHEN** 英国英文来源文章没有明确赛事地或核心实体地区
- **THEN** 系统 SHALL 将英国作为文章主地区

#### Scenario: 全球英文来源报道香港马归属香港
- **WHEN** 全球英文来源文章核心对象是香港马、香港骑师或香港练马师
- **THEN** 系统 SHALL 将中国香港纳入该文章地区归属

### Requirement: 法国新闻池必须保持原文可审核
系统 SHALL 继续禁止法语正文进入新闻审核、翻译、自动发布或 QQ 自动推送主链路。法国新闻池 MAY 接收英文来源中的法国赛事、法国赛果、法国赛马生态、法国马、法国骑师、法国练马师、法国马场、France Galop 或法国拍卖/育马相关内容。

#### Scenario: 法语正文不进入主链路
- **WHEN** 候选来源文章正文语言为法语
- **THEN** 系统 SHALL NOT 将该文章纳入新闻审核、自动发布或 QQ 自动推送主链路

#### Scenario: 英文法国生态内容进入法国池
- **WHEN** 英文文章明确报道 France Galop、Longchamp、Deauville、Chantilly、Arqana、法国育马、法国拍卖或法国马场相关内容
- **THEN** 系统 SHALL 允许该文章进入法国新闻池
- **AND** 系统 SHALL 保留命中的法国实体作为归属证据

#### Scenario: 法国实体海外参赛多地区归属
- **WHEN** 英文文章报道法国马、法国训练马、法国骑师或法国练马师在海外赛事中的表现
- **THEN** 系统 SHALL 将法国纳入文章地区归属
- **AND** 系统 SHALL 将比赛发生地区也纳入文章地区归属

### Requirement: 香港新闻池必须支持宽口径内容
系统 SHALL 允许中国香港新闻池接收赛事新闻、赛前展望、赛果简报、HKJC 官方通知、赛程/出赛表/装备/兽医报告、从化训练、香港马海外远征、香港骑师/练马师动态、香港国际赛、拍卖、售马、马主活动、人物特写和可审核英文/繁中来源文章。

#### Scenario: HKJC 官方通知进入香港池
- **WHEN** HKJC 官方来源发布兽医报告、装备更新、赛程通知或 racecard update
- **THEN** 系统 SHALL 允许该内容进入中国香港新闻池
- **AND** 系统 SHALL 按内容类别决定自动发布和 QQ 资格

#### Scenario: 香港马海外远征进入香港池
- **WHEN** 英文或繁中文章报道香港马在海外赛事参赛或获奖
- **THEN** 系统 SHALL 将中国香港纳入文章地区归属
- **AND** 系统 SHALL 将比赛发生地区也纳入文章地区归属

### Requirement: 新闻内容类别必须标准化
系统 SHALL 为新增和既有国际新闻文章保存标准内容类别。首期类别 MUST 至少包含 `news`、`preview`、`result_brief`、`official_notice`、`racecard_update`、`tips`、`feature`、`sales_breeding` 和 `other`。

#### Scenario: 赛前展望分类
- **WHEN** 文章主要介绍即将举行赛事的参赛马、赛前形势或焦点
- **THEN** 系统 SHALL 将内容类别保存为 `preview`

#### Scenario: 赛果简报分类
- **WHEN** 文章主要报道赛事结果、冠军、名次或赛后短评
- **THEN** 系统 SHALL 将内容类别保存为 `result_brief`

#### Scenario: 投注倾向内容分类
- **WHEN** 文章主要包含选号、赔率、best bets、NAP、each-way 或 free bet 表达
- **THEN** 系统 SHALL 将内容类别保存为 `tips`
