# 全球赛马数据库源 spike 记录

日期：2026-06-25

关联 OpenSpec change：`expand-international-racing-coverage`

## 边界

- 本文档只记录小样本技术 spike 结论和后续建议。
- 本轮没有把 `Equibase`、英国 `Sporting Life + BHA` 或法国 `France Galop` 加入 Celery Beat、生产管理命令调度或正式导入队列。
- 本轮没有向正式 `ExternalRace / ExternalRaceEntry / ExternalRaceResult / ExternalHorse / ExternalHorseAlias` 表写入欧美 spike 数据。
- 如后续要正式导入欧美数据库，必须另开 OpenSpec change，单独设计字段、限速、失败恢复和生产开关。

## 请求边界

- 本轮实现阶段未对欧美站点执行生产式爬取。
- spike 样本请求次数：`0` 次生产请求。
- 限速建议：后续正式 spike 可从 `10-30 秒/请求` 起步，先单日期、单比赛、单马 profile 小样本，不做历史全量。
- 样本解析保存位置：仅允许仓库文档、隔离 fixture 或临时文件，不允许写正式外部数据表。

## 2026-06-25 国际新闻源真实探测

执行命令：

```bash
DB_ENGINE=sqlite python server/manage.py probe_international_news_sources --limit 2 --json
```

该命令只做 dry-run，不写入 `NewsArticle`，每个来源最多解析 2 篇真实新闻详情。

探测结论：

- `Sponichi`：成功解析 2 篇真实新闻，正文长度约 `4979 / 4990`，可作为日本二期新闻源候选。
- `HKJC Racing News`：改用页面公开脚本暴露的 banner API 后，成功解析 2 篇真实新闻，正文长度约 `4261 / 2624`。
- `SCMP Racing`：成功解析 2 篇真实新闻，正文长度约 `3885 / 2993`。
- `BHA`：成功解析 2 篇真实 press release，正文长度约 `1502 / 1270`；需要使用正文容器专用选择器，避免侧栏标题干扰。
- `Sporting Life Racing`：成功解析 2 篇真实新闻，正文长度约 `4883 / 5439`。
- `At The Races`：当前从本地环境请求 `https://www.attheraces.com/news` 返回 `403 Forbidden`，法国英文新闻源上线前需要换入口、放慢探测或改为备用英文来源。
- `Paulick Report`：当前从本地环境请求 `https://paulickreport.com/news/` 返回 `403 Forbidden`，上线前需要确认访问限制或替换来源。
- `BloodHorse`：曾成功解析 2 篇真实新闻；随后同入口返回 `Pardon Our Interruption` 反机器人页，说明该站存在会话/风控波动，不建议未复验前自动启用。

## 美国：Equibase

样本入口建议：

- Entries：`https://www.equibase.com/static/entry/`
- Results：`https://www.equibase.com/static/chart/`
- Charts：`https://www.equibase.com/static/chart/pdf/`
- Horse profile/search：`https://www.equibase.com/profiles/`

字段覆盖预期：

- 比赛：日期、马场、场次、比赛名、等级/条件、距离、场地、跑道、天气/Going、奖金。
- 出马：马名、外部 horse profile、骑师、练马师、档位、负磅、装备、赔率或 morning line。
- 赛果/charts：名次、完成时间、距离差、赔率、分段、沿途位置、骑师、练马师。
- 马匹：英文名、出生年份、性别、父母血统、马主、练马师、近走成绩。

风险：

- 访问限制和反爬风险最高；PDF chart 解析成本较高。
- 页面入口和参数可能随赛日、马场代码变化，需要先建立小样本 URL 矩阵。
- 不建议一期直接正式导入全量历史数据。

建议：

- 后续正式实现前先做 `dry-run + fixture` spike，优先解析单日 entries/results 和 1-3 个 horse profile。
- 如果 PDF chart 是字段最完整来源，应独立评估 PDF 解析稳定性。

## 英国：Sporting Life + BHA

样本入口建议：

- Racecards：`https://www.sportinglife.com/racing/racecards`
- Results：`https://www.sportinglife.com/racing/results`
- Horse profile：`https://www.sportinglife.com/racing/profiles/horse/`
- BHA 官方搜索/监管信息：`https://www.britishhorseracing.com/`

字段覆盖预期：

- `Sporting Life`：racecards、results、horse profile 的可读性较好，适合作为新闻源之外的结构化候选。
- `BHA`：官方性质更强，适合补充官方马匹、赛程、监管和公告信息，但页面/API 入口需要单独确认。

风险：

- `Sporting Life` 页面可能依赖前端渲染或内部 JSON，需要确认是否能稳定慢速抓取。
- BHA 官方数据字段可能分散在搜索、profile、公告和监管页面，字段完整度未确认。

建议：

- 后续先做 racecards/results/horse profile 三类 fixture，不直接写正式表。
- 如果 Sporting Life 字段完整，后续可作为英国正式导入候选；BHA 作为权威校验/补字段来源。

## 法国：France Galop

样本入口建议：

- Calendar / meetings：`https://www.france-galop.com/`
- Declarations / runners：`https://www.france-galop.com/`
- Results：`https://www.france-galop.com/`
- Horse profile/search：`https://www.france-galop.com/`

字段覆盖预期：

- 结构化赛程、报名、出马、赛果和马匹资料具备权威价值。
- 法语字段可作为结构化缓存字段或原始 payload，不进入新闻审核、翻译、自动发布或 QQ 自动推送主链路。

风险：

- 页面可能依赖 JS、会话或查询参数；字段名和页面正文以法语为主。
- 用户明确无法审核法语新闻正文，因此 France Galop 不作为本期新闻源。

建议：

- 后续只评估结构化数据库入口，不抓法语新闻正文。
- 若正式导入，需要在字段层保留原始法语 payload，同时用英文/中文后台标签解释字段含义。

## 后续进入正式导入的优先级

1. `HKJC`：本期已实现正式受控导入入口，可继续用 payload 小样本和后续真实慢速请求验证。
2. 英国 `Sporting Life + BHA`：字段和公开入口较有希望，建议下一期做 fixture spike。
3. 美国 `Equibase`：价值高但限制风险高，建议先做 PDF/HTML 小样本解析评估。
4. 法国 `France Galop`：只保留结构化数据候选，不进入法语新闻审核链路。
