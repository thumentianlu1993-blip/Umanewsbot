## Context

自动化运营 MVP 当前按“评分 -> AI 改写 -> 一致性校验 -> 自动发布批次”运行。生产候选池样本显示，评分已经能识别高价值新闻，但发布门禁把多类低确定性风险统一当作失败处理：片假名普通词被识别为未知马名，背景赛事或血统术语被视为必须保留，摘要化改写遗漏数字后触发硬失败，采访或引语较多也会转人工。这导致高分文章停在候选池，运营需要大量人工判断。

本设计把自动发布门禁拆成“是否值得发布”和“是否能安全自动发布”两层。评分继续判断价值；门禁只阻断明确不可发布的问题；warning 初期不阻断，但需要记录、展示并对高价值文章发邮件提醒。

## Goals / Non-Goals

**Goals:**

- 支持关闭 AI 改写前置，自动发布可直接使用基准翻译稿。
- 将校验输出从单一失败原因改成结构化 issue，并区分 `blocker`、`warning`、`info`。
- warning 初期不阻断自动发布，但高价值文章出现 warning 时发送邮件告警。
- 高价值来源配置化放行评分阶段，首批覆盖 `netkeiba` 访问量榜和注目数榜。
- 删除长采访/引语较多和数字一致性作为硬门禁。
- 优化关键术语校验：核心术语更严格，背景术语缺失降级 warning。
- 引入非马名普通词 / 固定译法过滤，降低未知马名误判。
- 引入重复内容检测，把高度重复的待发布稿件从自动发布链路中剔除。
- 后台展示每篇文章的 blocker、warning、info，让人工能理解状态变化。

**Non-Goals:**

- 不在本 change 建立完整本地马名数据库；马名数据库导入和外部赛马数据校验另行处理。
- 不实现编辑区选中文本快速加入术语库；该交互另拆 change。
- 不重构 Django 单体、Celery、数据库或部署架构。
- 不接入 embedding 或外部 LLM 作为重复检测第一版依赖。
- 不改变公开前台只展示 `workflow_status=published` 且 `published_to_web_at` 非空文章的规则。

## Decisions

### 1. 校验结果使用结构化 issue，而不是继续拼接字符串

当前 `ValidationOutcome.reason` 是拼接后的中文字符串，难以区分哪些问题必须阻断，哪些只需提醒。新设计引入结构化 issue：

```python
{
  "code": "unknown_horse_not_preserved",
  "severity": "warning",
  "message": "疑似未收录马名未原样保留：タイトル",
  "payload": {"name": "タイトル", "source": "unknown_horse"}
}
```

替代方案是仅扩展现有字符串格式，例如加前缀 `[warning]`。该方案实现快，但后台筛选、邮件内容、后续统计都会脆弱，因此不采用。

### 2. `blocker / warning / info` 的行为固定，配置只控制少量阈值

- `blocker`：阻断自动发布，进入人工审核或重复状态。
- `warning`：初期不阻断自动发布，但写入日志和文章校验结果；高价值文章触发邮件告警。
- `info`：仅记录诊断信息，不触发邮件，不影响发布。

允许配置的内容包括高价值阈值、warning 邮件开关、AI 改写开关、是否要求封面、重复检测阈值。严重级别本身由规则定义，避免生产配置漂移造成难以解释的状态。

### 3. 基准翻译稿成为第一阶段自动发布内容源

新增 `AUTO_REWRITE_ENABLED` 和 `AUTO_PUBLISH_CONTENT_SOURCE`。当 `AUTO_REWRITE_ENABLED=false` 或内容源为 `base_translation` 时，自动化流程在评分后跳过改写任务，直接对 `title_zh`、`summary_zh`、`body_zh` / `translated_*` 的可发布性做基础校验。

实现时不得为了伪装成改写成功而填充 `rewrite_title_zh`、`rewrite_summary_zh`、`rewrite_body_zh`。基准翻译发布应复用现有 `effective_title`、`effective_summary`、`effective_body` 优先级，并在 `decision_reason` 或门禁 payload 中记录 `content_source=base_translation`。如果 `title_zh`、`summary_zh`、`body_zh` 尚未由翻译结果填充，则只允许从 `translated_title_zh`、`translated_summary_zh`、`translated_body_zh` 补齐对应发布字段，且不得覆盖人工编辑字段。

保留 AI 改写字段和任务，不删除现有能力。后续可以通过配置恢复 AI 改写，并继续复用结构化门禁。

### 4. 高价值来源只影响评分放行，不绕过 blocker

`netkeiba` 访问量榜和注目数榜可通过配置成为高价值来源。命中后，系统可将文章提升为自动候选或设置分数下限，但仍必须通过 blocker 门禁和重复检测。

这样既承认榜单来源的运营价值，又避免把空正文、乱码、广告页或重复内容直接发布。

### 5. warning 邮件按“高价值 + warning”触发

初期 warning 不阻断，但用户需要被提醒。邮件触发条件：

- 文章达到高价值阈值，默认 `score_total >= 90`，或命中高价值来源；
- 校验结果包含 `warning`；
- 文章没有因 `blocker` 进入人工审核；
- 通知开关启用且收件人配置存在。

默认收件人写入示例配置为 `754652181@qq.com`，真实生产仍通过 `.env` 控制。邮件内容必须包含候选后台链接、原文链接、分数、来源、warning 列表和当前发布状态。

### 6. 关键术语校验分核心与背景

核心术语包括标题、摘要、首段中出现的术语，以及高优先级马名/赛事。核心术语缺失作为 `blocker`，路由到人工审核；背景段落中的术语缺失不阻断，只作为 warning。

校验匹配必须接受 `source_ja`、`aliases_ja`、`target_zh`、`aliases_zh`，并做基础归一化：全半角、括号、间隔号、空白和常见繁简差异。

### 7. 非马名普通词以数据方式管理

第一批普通词包括 `タイトル`、`メートル`、`オッズ`、`ハンデ`、`ラジオ`、`ダート`、`マイル`、`スプリント`、`クラス`、`チャンス`、`キャリア`、`イメージ`、`デビュー`、`ゲート`。这些词可以进入正式术语库作为固定译法，但未知马名识别也必须显式排除它们。

实现上可先用数据迁移或 seed 命令导入，同时让 `extract_unknown_horse_names()` 从正式术语或专用普通词集合读取排除项。长期马名准确性由本地马名数据库分支解决。

### 8. 重复内容检测先用本地文本相似度

第一版只与已发布文章比对，范围限制为近 7 天或有限候选集。比对文本取标题、摘要和正文前段，使用可本地运行的相似度算法，避免新增外部模型依赖。

重复检测必须生成结构化 issue，并按阈值路由：

- 高于高阈值：生成 `duplicate_content` blocker，设置 `workflow_status=duplicate`，阻断自动发布；
- 中间区间：生成 `possible_duplicate_content` blocker，设置 `workflow_status=pending_review` 并转人工审核；
- 低于低阈值：继续自动发布。

保留 `duplicate_of`、`duplicate_score`、`duplicate_reason` 等可解释字段，便于后台审查。

## Risks / Trade-offs

- [Risk] warning 不阻断可能发布带有术语或数字省略的文章。  
  Mitigation: 初期只对基础翻译稿启用自动发布，warning 邮件提醒高价值文章，并保留人工抽检。

- [Risk] 高价值来源放行可能提高低质量文章进入自动链路的概率。  
  Mitigation: 高价值来源只影响评分，不绕过 blocker 和重复检测。

- [Risk] 重复检测文本相似度可能误判同场比赛不同角度文章。  
  Mitigation: 第一版设中间区间转人工，并在日志中展示相似文章、分数和原因。

- [Risk] 新增字段和状态迁移影响生产数据。  
  Mitigation: 迁移只做新增字段或枚举扩展；部署前备份数据库；可通过关闭自动化新开关回退行为。

- [Risk] 邮件告警过多造成噪音。  
  Mitigation: 使用高价值阈值、去重窗口和通知开关控制频率。

- [Risk] 非马名普通词列表永远不完整。  
  Mitigation: 先用本轮 bad case 种子止血，后续由本地马名数据库和术语候选审核持续改进。

## Migration Plan

1. 新增配置默认值，保持生产可灰度启用。
2. 新增模型字段或状态迁移，部署前备份生产数据库。
3. 先以 `AUTO_REWRITE_ENABLED=false`、warning 不阻断、邮件开启的方式上线观察。
4. 验证候选池、自动发布批次、邮件日志、公开首页和详情页。
5. 如出现异常，关闭新开关或恢复 `AUTOMATION_ENABLED=false`，无需立即回滚迁移。

## Resolved Questions

- 不新增 `AutomationStatus.PUBLISH_READY_WITH_WARNINGS`。warning 不阻断时仍使用现有 `AutomationStatus.PUBLISH_READY`，并通过结构化 issue 字段、`AutomationLog.payload` 和后台展示区分“带 warning 的可发布”。
- 新增 `WorkflowStatus.DUPLICATE` 描述高度重复内容，避免与普通 `ignored` 混淆；中等相似内容不使用 duplicate 状态，而是转入 `pending_review`。
- warning 邮件需要频率限制：同一文章同一 warning 组合在 24 小时内只发送一次；缺少收件人或开关关闭时写入 `NotificationLog` skipped，不阻断自动发布。
