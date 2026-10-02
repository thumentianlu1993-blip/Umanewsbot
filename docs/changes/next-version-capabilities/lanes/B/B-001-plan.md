# B-001 / F02 新闻漏斗与模型黄金样例方案

阶段：方案可审，未冻结 F02 fixture，未完成基线。日期：2026-10-03，Asia/Shanghai；DDL：2026-10-05 18:00。

本线工作树 `/Users/mentianlu/.codex/worktrees/a14d/umanews`，分支 `codex/next-version-news-ai-20261003`。
代码 base：`907f8de699b31a6fcc80acc78e9ba070aadc4f28`；规划继承提交：`4c9725c9`，源为 `d0cec076019f35b6f7db56b09ebee291e57fd9f9`。
模型按派单为 `gpt-6.1-sol / medium`，未独立核验客户端设置；产品 API 模型配置不变。

## 目标、边界和当前状态

交付五地区新闻全链漏斗、至少每地区 20 篇真实新闻的固定样例、可追溯标注及开发/保留集隔离。
协调者后续决定：R 托管保留集，B 负责 development 初标和漏斗/脱敏准备。模型草标、独立机器核验、真实人类核验分别记录；协调者/R 的模型裁决不称为人工 gold。细化读取合同见 [有界导出方案](B-001-export-review.md)。

当前只修改本线文档与证据索引，不修改服务、数据库、配置或共享总任务表。授权和交付边界统一引用根 [AGENTS.md](../../../../../AGENTS.md)。
R 方案审核前只做调查和文档准备；不启动依赖未审方案的采样实现、fixture 冻结或模型行为实现。

已核验本地历史快照 250 篇，五地区各 50 篇、17 个来源。全部输入摘要和文件 manifest 一致。
历史日期为 2026-05-25 至 2026-07-13，不能代表当前运行态。该包曾用于归属评测，只能作开发素材。
它没有正文 HTML、工作流/失败状态、清洗标注、occurrence 实体和重大事件标注。
所以 F02 完整标注样本计数仍为 0；新的独立真实保留集计数为 0。

正文边界目录有 7 个缩减/合成 HTML 回归 fixture，明确不计入真实样本分母。
`docs/data/multiregion_gold_labels.example.csv` 只有表头。
既有 provisional 归属标签 159 条，不能冒充 F02 黄金标注：历史报告 `structurally_qualified=false`，且标签维度不同。
详情与逐篇索引见 [sample_inventory.json](sample_inventory.json)。未将原文或个人信息复制进 Git。

现有 SSH 别名 `umanews` 的 BatchMode 只读容器列表探测失败，退出码 255，远端关闭连接。
没有读取生产数据库/Redis，没有任务投递，也未改 SSH 配置。协调者后续已用现有连接成功列出8个容器、web/db健康；原失败保留为瞬时失败，访问不需用户处理。本线未进行DB查询，运行版本、生产配置和漏斗数字均待证。

## 采样设计（待 R 审核）

1. 固定快照时刻 T，优先读取 T 前 28 天五地区全部入库新闻的元数据与窗口/任务记录；地区为日本、香港、英国、法国、美国。
   原地区、来源默认地区、证据核定主地区与相关地区分列。报告来源地区和主地区两个视角，全局按 article ID 去重。
2. 抽至少 100 篇真实新闻，按证据核定主地区每地区至少 20 篇；开发 12、保留 8 为起始配额。
   配额不足时追加真实样本，不能拿历史开发包或合成稿填保留集。跨地区 other/未知身份保留在候选账本，另列缺口。
3. 每地区目标至少 2 篇未公开稿、2 篇翻译/清洗/选择失败稿、2 个污染案例、2 个误删风险/反例、2 个普通词姓名例、1 组至少 2 篇重复报道、2 个重大事件。
   标签可以重叠；无真实案例则记录 0 与缺口，不能把“风险”写成已发生错误。至少半数为常规对照，避免只测异常。
   同一类别尽量让开发和保留各有至少 1 例；约束冲突时扩样并记录新增数量。
4. 按来源与阶段分层；来源足够时每地区至少 2 个来源，单来源原则上不超过该地区一半。日本单列 JRA/netkeiba/Sponichi。
   失败正文为空的稿仍保留在漏斗/失败切片，但不能计作满足实体/清洗验收条件的完整新闻篇数；另补正文充分的真实样本。
5. 聚类单位为真实事件/同场同届/转载链；重复报道作为多个 article 留在同一组。相同 input SHA、canonical URL、近似正文和同事件报道不得跨 split。
   先按组隔离，再检查每地区/阶段/类别配额，稳定 seed 为 `F02-20261003-v1`。分组由标注依据复核，字符串相似度只提供候选。
6. 所有历史已评测的 250 篇及其同文、转载和同事件衍生稿强制 development/excluded，记录排除原因。
   在 B 查看任何新保留集原文、标签或模型输出前，由 R/协调者保管划分和私有标签；B 只持保留集计数、opaque ID 与承诺摘要。
   审核者不将保留集正文/标签放入共享开发树、PR、提示词或子代理上下文。M11 固定版本评估才解封，记录模型/提示词 SHA。
7. 若 28 天内不足，优先取已批准来源的既有原文缓存和 90 天存量，窗口扩展由协调者记录；不新增真实抓取或付费调用。
   若需扩大采集/权限，协调者依根 AGENTS.md 判断，B 不自行扩大。缺样本时 F02 保持部分完成。

100 篇是最低规模，不是长期错误率证明。报告整体和保留集各自分子/分母；40 篇保留集即使零污染也不能证明长期 <1%。
原规划阈值保持：重大事实/错马/自造名/关键误删为 0，污染比例 <1%，实体精确率建议 ≥99%、召回率建议 ≥97%。
无法评价的样本单列，不从总目标偷偷删除。自然重大事件覆盖另需独立的事件目标账本，不能只在已入库稿中定义漏报分母。

## 标注指南与证据合同

样本类型只可为 `real_snapshot`、`real_holdout`、`synthetic_regression`；历史真实包增加 `prior_evaluation=true`。
旧标签状态不足以证明核验来源；新合同用 model_annotation_status、machine_validation_status、human_verification_status 三个独立字段，详见有界导出方案。当前真实人类核验全为 not_reviewed；程序/模型建议不得直接转为人工黄金标签。
B 可做开发集模型草标，R 托管保留集及独立验收材料；关键事实/姓名/重大事件疑难整理成小包交协调者按出处裁决，可留 unknown。模型裁决和真实人类核验分列，不要求用户现在标全量100篇。
无法从证据认定则标 unknown/disputed，并给出缺证据原因，不能用当前模型输出当答案。

每篇记录：

- provenance：快照时刻、导出/脱敏版本、article ID、来源 ID/语言/地区、公开来源 URL、input SHA、原文/HTML/清洗正文/译文各自 SHA；不含 Cookie、凭据、用户编辑者身份。
- state：入库时间、原站发布时间及是否核验、清洗状态/selector、工作流/翻译/自动化状态、候选决策与失败原因、首次公开与撤回时间、曝光记录。
- blocks：在被冻结原文上的区块 ID、start/end、原句摘要、`keep/remove/uncertain`、广告/导航/推荐/引语/表格/图片说明类型；误删判定要对照原 HTML 与清洗结果。
- entities：逐 occurrence 的原字符串及 span，明确 span 所属文本/hash；类型、稳定 ID 或未知候选、普通词语义、中文名及出处；无可靠中文名就保留原名。
- facts：断言 ID、主语/谓词/对象、日期/距离/奖金/名次等值与单位、否定/计划/引语归属、证据区块；预测不能标已发生。
- events：同事件 group ID、真实赛事 ID/年度（未知单列）、重大事件与理由、独立事件账本条目、重复/新事实关系；多个角度不自动判重复。
- annotation：角色代号、时间、标签版本、状态、依据与分歧结论；不存个人姓名或联系方式。

冻结时生成 manifest SHA，包含样本清单、输入摘要、split/group、标注版本和覆盖检查。split 或标签变动即新版本。
开发素材存专用 runtime 目录，Git 只放脱敏合同、摘要与最小合法开发 fixture；真实保留集内容由独立负责人保管。
版权与敏感内容保留原受控位置，不把大批原文或未公开译稿推入公开仓库。

## 漏斗查询与配置核对

只读查询用 PostgreSQL `REPEATABLE READ READ ONLY`，statement_timeout、lock_timeout 有界，无锁业务写入。
先核对实际应用 SHA/schema，避免把 base 的模型结构当生产真相。读取到的所有阶段属于同一 observation。
采样与审计不调用翻译、重写、归属 apply、抓取、发布或曝光 reservation 函数，不发 Celery、不连接模型 API。
导出按字段 allowlist；自由文本错误仅输出错误类别，不导出可能包含请求内容/凭据的堆栈。

| 阶段 | 现有入口/证据 | 正确分母与限制 |
|---|---|---|
| 抓取 | `CrawlJob`、`ProductionWindow` crawl、`NewsSource` | 来源尝试/成功/失败/新增/重复分别报；没有入库的失败不消失；缺列表候选账本时不能宣称全网漏报率 |
| 清洗 | `NewsArticle.original_content_html/body_ja_raw/body_ja_normalized`、`translation_metadata`、`article_content.py` 与 adapter | HTML 缺失/selector 失败/正文为空单列；现有输入为空不筛掉；质量须人工区块对照 |
| 翻译 | `translation_status/error_category/provider/model/translated_at`、任务记录 | pending/failed/succeeded 各列；blank 中文不算成功；重试次数和唯一篇数分开 |
| 选择 | `WindowCandidateDecision`、`decision_reason/gate_issues`、`publishing_windows.py` | 每窗口决策与去重文章两个分母；hard gate 具体原因缺失标 unknown；失败与未选保留 |
| 公开 | `workflow_status`、`published_to_web_at`、`withdrawn_at` | 原站 `published_at` 不等于网站公开；当前公开存量与窗口首次公开分开 |
| 曝光 | `RaceNewsExposure`、公开视图实际筛选 | active/waiting/archived 与无席位分列；旧路径/手工头条可能不在 exposure 表，按生效配置解释；席位不等于读者阅读 |

主漏斗按 T 前 28 天 `first_seen_at` 固定 cohort，所有状态为 T 时快照；另列同期阶段事件流（包括更早稿的翻译/发布）和 T 时全部存量。
清洗/翻译/选择不是严格单调状态；不要强制做相减转化率。多地区相关展示不重复加入主地区分母。
JRA 倾斜按供给→清洗失败→翻译失败→术语/人工审核→选择→公开→曝光逐层拆解；数据缺失时不预断原因。

现有 `summarize_multiregion_news_production` 仅作补充：active workflow 排除了已发布/撤回/忽略/重复，部分总量包含 related regions，不能直接当 F02 全漏斗分母。
现有 `eligible_gold_articles` 排除了 withdrawn 与空正文，不能原样复用作 F02 失败样本候选池。

配置只读取 allowlist 的有效 Django settings，记录代码默认值与生产有效值、观察时刻和应用 SHA，不输出 `.env`。
最低 allowlist：TRANSLATION_PROVIDER/MODEL、REWRITE_PROVIDER/MODEL、AUTO_TRANSLATE_ON_INGEST/SYNC、AUTOMATION_ENABLED、AUTO_REWRITE_ENABLED、
MULTIREGION_AUTO_PUBLISH_ALLOWED_REGIONS/SOURCES/REGION_BATCH_LIMITS/REGION_DAILY_LIMITS、MULTIREGION_PUBLISH_BACKLOG_ENABLED、RACE_NEWS_EXPOSURE_ENABLED。
代码默认 `TRANSLATION_PROVIDER=dummy`、`TRANSLATION_MODEL=gpt-5-mini`；rewrite 继承 translation，AUTOMATION_ENABLED 与 AUTO_REWRITE_ENABLED 为 false、RACE_NEWS_EXPOSURE_ENABLED 为 false。
这只是 `907f8de6` 代码事实；当前生产值全为 unknown。

## 验证、审核与下游接口

文档/只读任务不制造 RED。R 审核方案后，依次取得快照、独立分组/保留集托管、开发初标与复核、冻结 manifest、离线基线。
完成检查：五地区真实样本≥20；输入摘要正确；失败/未公开包含；类别与来源覆盖可解释；事件组不跨 split；unknown/disputed 单列；配置区别有运行证据。
离线评估只读固定 snapshot，解析/规则不得联网；测试采用隔离环境，不能访问生产 DB/Redis/队列。
每阶段证据绑定输入 manifest、代码 SHA、标注版本、命令/退出码；旧评测准确率不复制为当前质量。

供 M01/F06/N01–N06 消费：`sample_manifest.json`、development 样本/标签合同、保留集承诺摘要、`funnel_snapshot.json`、`effective_config.json`、逐项 coverage/unknown 清单。
这些是待产出合同，不是假称现有文件。无模型 schema/迁移变动；共享类型细节接 F01，经审核的 SHA 到位后才能进入 M01。
当前只读兼容定位：translation/rewriting 使用 `client.chat.completions.create`；此次不调用 API、不更换模型，也不把 Responses 适配称为已实现。

## 待协调事项

1. 请安排 R 审核本方案，已确定 R 托管保留集及独立验收材料；R 的机器/模型审核不自动替代真实人类核验。
2. 推荐由既有生产只读能力的协调者提供有观察时刻/SHA 的字段 allowlist 快照与配置摘要，或定位可访问的已有导出包；本机 SSH 连接已关闭，不反复尝试凭据/权限扩展。
3. 优先补采新近真实 100 篇及原 HTML/失败状态，不将历史 250 篇重命名为保留集。若访问/标注到 10/04 18:00 仍缺，提前报告 F02 的 10/05 DDL 与 M01 的 10/06 解锁风险。

当前无用户产品取舍请求；访问恢复和人员分配先由协调者处理。扩大来源/付费/权限所需决策由协调者带具体范围上报。
