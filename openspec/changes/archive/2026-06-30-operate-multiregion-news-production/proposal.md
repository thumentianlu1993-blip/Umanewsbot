## Why

系统已经具备日本、中国香港、英国、法国和美国新闻源承载能力，也完成过国际来源生产灰度启用和手动抓取验证；但常态生产仍依赖日本固定 Celery Beat 任务，国际来源缺少按 `NewsSource` 配置自动轮询、地区化运营观测和分阶段推送策略。

本变更用于把“已接入多地区”升级为“可长期运行的多地区新闻生产 + 发布 + QQ 推送闭环”，并明确外部赛马数据库导入仍保持受控手动/批处理边界，不进入新闻常态调度。

## What Changes

- 新增多地区新闻生产运行能力：生产只读审计、地区/来源灰度策略、常态调度、运行指标、回滚和文档化验收。
- 将新闻抓取调度从日本固定任务扩展为通用 `enabled` 来源轮询：按 `NewsSource.enabled`、`crawl_interval_minutes`、地区、来源优先级和最近抓取记录选择到期来源，并避免同一来源并发抓取。
- 保留现有日本 `netkeiba / JRA` 稳定调度语义；通用调度不得导致日本来源重复高频抓取或绕过既有错峰约束。
- 为多地区自动发布增加运营策略：按地区和来源控制是否允许自动发布、每日/每轮上限、默认人工审核边界和逐步放量规则。
- 为后台补充地区化运营观测：按地区展示今日抓取、待翻译、待审核、已发布、自动发布、QQ 交付和异常状态，使工作人员能判断某地区是否真正进入常态生产。
- 扩展 QQ 推送灰度要求：群级地区配置继续生效；正式群默认不因国际新闻常态化突然收到全球新闻；测试群可按地区灰度；消息应让用户能识别新闻地区。
- 建立多语言术语运营检查：国际新闻常态化前后需要可审计地观察英文/繁中术语命中、外部马名保护、候选池积压和翻译失败。
- 明确外部赛马数据库 importer 的边界：HK/UK/FR/US `External*` 数据导入可继续为马名识别和后续数据底座服务，但不得加入新闻 Beat、不得自动生成公开新闻或前台赛果页面。
- 新增生产只读审计和灰度运行手册，包含启用前基线、每地区试运行、QQ 测试群验收、停用/回滚和异常排查命令。

## Capabilities

### New Capabilities

- `multiregion-news-production`: 定义多地区新闻常态生产的审计、灰度、通用调度、地区运营指标、验收和回滚边界。

### Modified Capabilities

- `crawl-freshness-and-source-health`: 增加通用 enabled 来源轮询、同源并发保护和地区化来源健康要求。
- `automation-publish-gates`: 增加按地区/来源控制自动发布策略、批次上限和国际新闻默认人工审核边界。
- `qqbot-auto-push`: 增加多地区常态生产下的群级灰度、地区标识、无显式配置不扩散到旧群和推送验收要求。
- `termbase-and-race-priority`: 增加国际新闻常态化下多语言术语命中、候选池积压和外部马名保护的运营检查要求。

## Impact

- 代码范围：`server/app/settings.py`、`server/stable/tasks.py`、`server/stable/models.py`、`server/stable/services/sources.py`、`server/stable/services/automation.py`、`server/stable/services/qq_auto_push.py`、后台 views/forms/templates/admin、相关 tests。
- 数据模型：第一期优先复用现有 `NewsSource`、`CrawlJob`、`NewsArticle`、`PushTarget`、`QQPushDelivery`、`TermCandidate` 和 `TermAlias`，不新增地区发布策略模型；如后续运营需要后台维护策略，应另起独立 change 评估模型、迁移和 UI。
- 配置：预计新增通用来源调度开关、每轮最大来源数、地区/来源 allowlist、国际自动发布灰度策略和 QQ 测试群验收配置；现有 `QQ_PUSH_ENABLED` 总开关继续保留。
- 运维：需要生产只读审计、灰度启用步骤、回滚步骤、来源异常排查、QQ OneBot 在线检查和 docs/current_state.md、docs/project_status.md、docs/deploy_runbook.md 回写。
- 非目标：不实现公开比赛页、赛果页、马匹页；不把 HK/UK/FR/US 外部数据库导入加入新闻自动调度；不绕过上游反爬限制；不一次性开放所有正式 QQ 群接收全球新闻。
