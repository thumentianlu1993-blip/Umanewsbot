## Context

当前系统已经具备日本 `netkeiba / JRA` 新闻采集、翻译、术语纠偏、自动发布、公开首页和 QQ 自动推送能力。外部赛马数据导入已有 `add-netkeiba-horse-data-import` 规划与实现经验：低频离线导入、限速抖动、单来源锁、断点续跑、外部马名索引不等同正式术语库。

国际化扩展会同时碰到四条主线：

1. 内容来源不再只有日本，原文不再只有日文。
2. 公开首页需要从单一资讯流变成地区化频道。
3. 术语库需要保留“同一个实体 / 概念 -> 简体中文标准译名”的可信词条，并允许这个概念有日文、英文或繁体中文等多个原文名。
4. QQ 群偏好不同，不能继续用一套全局范围配置决定所有群收到什么。

本变更只写规格和任务，不实现功能代码；后续实现会另开会话按任务组推进。

## Goals / Non-Goals

**Goals:**

- 建立多地区、多语言、多来源类型的第一期产品边界。
- 明确一期新闻源清单和语言限制。
- 明确公开首页地区 tab 的用户体验与数据过滤规则。
- 明确术语库多原文语言兼容路径，并降低物理字段大迁移风险。
- 明确 QQ 自动推送群级地区/范围配置。
- 明确 HKJC 数据库导入作为第一期正式落地目标。
- 明确 Equibase、英国和法国数据源只做 spike，不承诺全量导入。

**Non-Goals:**

- 不实现比赛页、赛果页、马匹页或地区专题页。
- 不抓取法语新闻正文进入审核流。
- 不把外部数据库马名自动批量写入正式 `TermEntry`。
- 不一次性全量抓取欧美历史数据库。
- 不改变 Django 单体、Celery、Docker Compose 主架构。
- 不在本会话部署生产。

## Decisions

1. 使用一个总 change 而不是多个 active child change。
   - 原因：本会话目标是把规格写完并确认可用性，后续实现会另开会话。一个总 change 能把跨模块边界放在同一个上下文里，减少多个未实现子 change 互相漂移。

2. 第一地区集合固定为五个前台可见地区。
   - 前台 tab 显示：综合、日本、中国香港、英国、法国、美国。
   - 内部可预留 `other` 或等价地区值，但第一期不在前台展示。
   - 建议内部稳定值：`japan`、`hong_kong`、`united_kingdom`、`france`、`united_states`、`other`。

3. 新闻审核语言第一期只支持 `ja / en / zh-hant`。
   - 日本新闻可为日文。
   - 香港新闻可为英文或繁体中文。
   - 英国、法国、美国新闻正文必须为英文。
   - 法语可以出现在结构化数据库字段或原始 payload 中，但不得进入新闻翻译审核主链路。

4. 法国新闻源第一期选择已实测可抓的英文来源。
   - `France Galop English News` 作为法国官方英文新闻源。
   - `TDN` 法国关键词英文新闻作为法国补充新闻源，用于覆盖 France Galop、Arc、Chantilly、Deauville 等法国赛马相关英文稿。
   - `Jour de Galop` 和 `Paris Turf` 暂不进入新闻审核主链路，因为正文为法语，用户审核成本高。
   - `At The Races` 当前返回 403，不作为第一版生产新闻源。

5. 术语库采用“概念 + 多语言别名”模型，不把同一匹马拆成多条正式术语。
   - 现有 `TermEntry.source_ja`、`aliases_ja` 可先作为数据库兼容字段继续存在。
   - `TermEntry` 代表正式中文术语概念，例如一匹马、一场赛事、一个骑师或一个马场。
   - 新增 `TermAlias` 或等价结构保存 `term_id / source_language / text / alias_type`，同一 `TermEntry` 可拥有 `ja / en / zh-hant` 多个原文名。
   - 带大小写的原文语言按大小写不敏感处理术语生命周期：`Equinox`、`EQUINOX` 和 `equinox` 在同一 `term_type + source_language` 下视为同一原文或别名；后台表单、导入、候选合并、术语 API、匹配和启停同步必须保持一致。
   - UI、表单、导入模板、服务层命名应展示为“原文”“原文别名”“原文语言”，但业务含义是“该概念在某语言下的原文名”。
   - 现有术语的 `source_ja` 和 `aliases_ja` 迁移为 `ja` 别名；旧字段继续作为主别名兼容显示和导入。
   - 后续若要重命名物理字段，应作为独立清理 change，不混入本期国际化承载。

6. 语言相关识别规则必须分流。
   - 日文片假名马名启发式只适用于 `source_language=ja`。
   - 英文和繁体中文文章不能套用日文片假名普通词/马名规则。
   - 英文马名、繁体中文马名和外部别名识别应优先依赖外部索引、正式术语和来源结构化字段。
   - 自动化评分中的重点马匹命中、赛事优先级、自动标签和核心术语信号必须按文章 `source_language` 读取对应语言的 `TermAlias`，但匹配结果回到同一个 `TermEntry`。
   - 候选合并允许跨语言合并到同一正式术语概念，但写入时必须保留候选自己的 `source_language`，不得把英文名混入日文别名数组。

7. QQ 推送配置迁移到群级。
   - `QQ_PUSH_ENABLED` 仍是总开关。
   - 每个 `PushTarget` 应能配置允许地区、推送范围、重点策略和启用状态。
   - 现有全局 `QQ_PUSH_SCOPE / QQ_PUSH_IMPORTANCE_STRATEGY` 可作为范围和重点策略的迁移兼容默认值来源，但地区不得用“空值等于全球”处理。
   - 现有目标群的空 `allowed_regions` MUST 在迁移时回填为 `["japan"]`；运行时若仍遇到空地区列表，也按旧行为仅允许日本新闻，避免旧群突然收到全球新闻。
   - 总开关管“能不能推”，群配置管“推什么给谁”。文章地区必须明确；缺少地区的文章不得自动推送，并应记录 `region_missing` 或等价跳过原因。

8. HKJC 是第一期正式外部数据库导入。
   - 选择原因：HKJC 官方页面公开度高，赛程、出马、赛果、马匹、试闸和相关记录集中，且对中文用户价值高。
   - 导入范围包括比赛、出马、赛果、马匹、血统/父母、马主、练马师、骑师、档位、场地、Going、天气或场地状态、日期和原始 payload。
   - `--commit` 写库前必须检查 payload 数量；超过 `max_races` 或 `max_horses` 时直接失败，不做静默截断，避免运维误以为整份 payload 已完整导入。

9. 欧美数据库先 spike。
   - 美国 `Equibase` 价值最高但反爬和访问限制风险最高。
   - 英国 `Sporting Life + BHA` 需要确认公开页面与接口字段覆盖。
   - 法国 `France Galop` 权威但可能存在 JS、会话、法语字段和查询体验问题。
   - spike 产物必须是字段覆盖矩阵、入口 URL/参数、限速风险、样本解析结果和后续实现建议。

10. 赛果导入不是前台赛果产品。
   - 本变更可以导入比赛/出马/赛果数据，但只作为外部缓存和后续大项目底座。
   - 前台比赛页、赛果页、马匹页、今日赛程模块等另起独立大项目。

11. 公开文章 ID 与来源去重键分离。
   - 用户可见公开详情页继续使用 `NewsArticle.id` 作为全局自增数字 ID，例如 `/news/<article_id>/`。
   - `source_article_id` 不是公开文章 ID，而是来源内幂等去重键；国际新闻源必须从完整 URL 生成稳定且低碰撞的键，例如 `slug-short_hash`。
   - 不得用本地自增 ID 替代来源去重键，否则重复抓取同一上游文章时无法稳定更新同一篇 `NewsArticle`。

12. 原始 HTML 与轻量 metadata 分离。
   - 原始 HTML 只进入 `NewsArticle.original_content_html`。
   - `translation_metadata` 只保存轻量抓取/翻译元信息，不保存整页 HTML，避免 JSON 字段膨胀和重复存储。

13. 新增新闻源的榜单入口按“可公开稳定抓取”逐源接入。
   - 类似 netkeiba 访问量榜/注目榜的排序入口，如果能在公开 HTML 或公开接口中慢速抓取，应作为独立 `source_mode=access`、`attention` 或等价榜单源接入，并把原站排名写入 `NewsSnapshot.rank`。
   - 本轮确认 `Sponichi` 的 `ニュースランキング` 可公开访问，页面混有ボート等其他ギャンブル内容；适配器只保留赛马路径/关键词命中的文章，并保留原站排名。
   - `Sky Sports Racing` 的 racing 首页/新闻页可解析 Top Stories/页面排序，可作为英国排序型弱信号。
   - `Horse Racing Nation` 可解析新闻列表与 Trending 区块，可作为美国排序型弱信号。
   - `HKJC Racing News`、`SCMP Racing`、`BHA`、`France Galop English News` 当前未发现等价公开热门新闻榜单，第一版使用新闻 list/官方顺序。
   - `Racing Post` 列表页可解析但详情页当前返回 406；`At The Races`、`Paulick Report` 当前返回 403；`BloodHorse` 返回 Incapsula/反机器人页或空样本；这些来源在解决访问限制前不得作为生产自动新闻源或榜单源启用。

## Data Shape Sketch

```text
NewsSource
  ├─ source_site / adapter_key
  ├─ racing_region
  ├─ source_language
  └─ source_kind: news | database | official | media

NewsArticle
  ├─ racing_region
  ├─ source_language
  ├─ source_site / source_mode
  ├─ id: 公开 URL 使用的全局自增数字 ID
  ├─ source_article_id: 来源内幂等去重键
  └─ public metadata

PushTarget
  ├─ group_id / name / is_active
  ├─ allowed_regions
  ├─ push_scope
  └─ importance_strategy

TermEntry / TermAlias
  ├─ TermEntry.target_zh: 标准简体中文译名
  ├─ TermEntry.term_type / race_grade / priority
  ├─ TermEntry.source_ja / aliases_ja: 兼容主别名字段
  └─ TermAlias(term, source_language, text, alias_type)

External* cache
  ├─ source
  ├─ racing_region
  ├─ source_language / data_language
  ├─ external ids
  └─ raw_payload
```

## Risks / Trade-offs

- [Risk] 术语库字段仍叫 `source_ja`，后续开发者误以为只支持日文。Mitigation: 本期新增 `TermAlias` 作为真实多语言匹配入口，并在 UI、表单、服务层和文档中使用“原文”语义，用测试覆盖同一术语概念的日文/英文/繁中别名。
- [Risk] QQ 群级配置迁移可能改变现有测试群行为。Mitigation: 迁移时保留现有全局配置的等价默认，并在后台可见每个群最终生效配置。
- [Risk] 法国或美国数据源 spike 变成隐形全量抓取。Mitigation: spike 必须使用小样本、dry-run、限速和只读字段报告，不得进入生产自动调度。
- [Risk] 综合流简单倒序会被单地区刷屏。Mitigation: 第一期接受该 trade-off；复杂打散另起优化。
- [Risk] 香港繁中内容和简体展示混杂。Mitigation: 入库保留 `source_language=zh-hant`，发布稿统一产出简体中文。
- [Risk] 国际新闻适配器漏写地区，导致文章绕过群级地区过滤。Mitigation: 新文章入库必须写入非空地区；缺少地区时禁止 QQ 自动推送，并在后台或交付记录中显示跳过原因。
- [Risk] 排序型入口混入同站非赛马内容或前端骨架屏。Mitigation: 只有公开 HTML/API 中能解析出真实文章和排名时才接入；混合榜单必须用路径/关键词过滤并保留原站排名，不能把过滤后的列表重新编号。

## Migration Plan

1. 新增地区/语言字段并回填现有数据为 `japan / ja`。
2. 将术语库 UI/服务语义改为“正式术语概念 + 多语言原文别名”，新增 `TermAlias`，并将现有术语主原文与原文别名回填为 `ja` 别名。
3. 增加前台 tab 和地区过滤，默认综合仍展示全部已发布文章倒序。
4. 增加群级 QQ 推送配置字段，并用现有全局配置迁移现有目标群。
5. 接入一期国际新闻源。
6. 实现 HKJC 外部数据导入，并保持低频手动触发。
7. 实施全球数据源 spike，输出风险与字段覆盖报告。

## Open Questions

无。用户已确认本次只完成规格，后续实现另开会话。
