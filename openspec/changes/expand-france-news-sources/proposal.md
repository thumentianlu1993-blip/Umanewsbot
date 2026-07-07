## Why

生产只读审计显示，法国现有两个新闻源近 24 小时几乎没有新稿入库：`france_galop_news` 当前列表前 20 条基本已入库，`tdn_france` 只搜索 `France Galop` 关键词且多为旧稿。法国新闻量不足不能只靠发布门禁修复解决，需要单独扩展更稳定、更宽覆盖的法国赛马新闻来源。

## What Changes

- 为法国地区调研并接入一批新的可抓新闻来源，优先选择稳定、公开、低反爬、与法国赛马高度相关的来源。
- 为每个候选法国来源提供只读探测、样本解析、去重、来源健康和启用策略。
- 新增或完善法国新闻 adapter，确保标题、正文、发布时间、原文 URL、来源语言、地区和 source metadata 正确入库。
- 将新增法国来源接入 `NewsSource` 同步和多地区 15 分钟生产窗口，但默认仍受 `enabled`、`production_approved`、backoff 和来源 allowlist 控制。
- 扩展生产审计，明确法国各来源是“无新稿”“解析失败”“访问受限”还是“入库后被门禁拦住”。
- 提供上线后验收口径：最近若干窗口内法国来源抓取成功率、新增量、重复量、发布候选和公开量。

## Capabilities

### New Capabilities

- 无。

### Modified Capabilities

- `multiregion-news-production`: 扩展法国常态新闻来源覆盖和法国地区上线验收要求。
- `crawl-freshness-and-source-health`: 增加法国新来源的健康、无新增和解析失败可观测性要求。

## Impact

- 影响代码：`server/stable/adapters/international.py`、`server/stable/services/sources.py`、抓取探测命令、生产审计命令、相关测试 fixture。
- 影响配置：新增法国来源默认不得直接全量打开，必须通过 `enabled`、`production_approved` 和生产开关灰度启用。
- 影响运维：上线前需要真实探测候选源；上线后需要观察法国最近窗口新增与公开情况，并保留停用单源的回滚路径。
- 不改变：英文术语硬门禁修复、QQ 推送策略、外部赛马数据库 importer、赛事详情页数据导入。
