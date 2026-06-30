## 0. Pre-declared hypotheses

- [x] 0.1 (operations) PASS: 通用来源轮询关闭时不会触发任何新增国际来源抓取；BLOCKER: 关闭状态仍创建 `CrawlJob` 或派发抓取任务
- [x] 0.2 (operations) PASS: 通用来源轮询开启后每轮触发来源数量不超过配置上限，且固定调度的 netkeiba/JRA 来源不会被重复触发；BLOCKER: 任一固定调度来源被通用轮询重复抓取
- [x] 0.3 (operations) PASS: 非日本新闻在未显式配置自动发布 allowlist 时不会自动公开；BLOCKER: 未允许地区文章直接进入 `PUBLISH_READY` 或被自动发布
- [x] 0.4 (operations) PASS: 多地区审计只读执行不创建业务写入记录；BLOCKER: 审计命令创建 `CrawlJob`、`NewsArticle`、`QQPushDelivery` 或外部导入 run
- [x] 0.5 (operations) PASS: QQ 旧群空/非法地区配置仍只允许日本，测试群显式配置后可接收对应地区；BLOCKER: 旧群在未显式允许时收到国际新闻

## 1. 生产审计与配置基础

- [x] 1.1 (application) 新增多地区新闻生产只读审计管理命令，默认输出控制台 JSON，可选写入 `runtime/` JSON，输出地区来源、文章状态、翻译状态、自动化状态、QQ 交付和术语候选聚合
- [x] 1.2 (application) 为审计入口补充测试，确认不创建 `CrawlJob`、`NewsArticle`、`QQPushDelivery` 或外部导入记录
- [x] 1.3 (operations) 在 `.env.example` 增加通用来源轮询、地区 allowlist、每轮来源数和国际自动发布灰度相关配置说明
- [x] 1.4 (operations) 在运维文档中补充生产只读审计命令和启用前基线记录模板

## 2. 通用来源轮询

- [x] 2.1 (integration) 新增通用 enabled 新闻来源选择服务，按 `enabled`、地区/来源 allowlist、`crawl_interval_minutes`、最近抓取时间、从未运行来源和固定调度排除规则筛选到期来源
- [x] 2.2 (application) 为来源选择服务补充测试，覆盖到期、未到期、从未运行、停用、固定调度来源排除和每轮最大来源数
- [x] 2.3 (application) 新增通用来源轮询 Celery 任务，触发到期来源抓取并返回已触发、跳过、延后和失败原因
- [x] 2.4 (application) 为通用轮询任务补充同源运行中跳过、陈旧运行中记录和结果可审计测试
- [x] 2.5 (integration) 确认通用轮询复用既有 `crawl_news_source_task` 和国际适配器，不调用任何 `External*` importer
- [x] 2.6 (application) 将通用轮询接入 Celery Beat，并通过总开关保持生产默认安全关闭或仅启用明确 allowlist

## 3. 地区化自动发布策略

- [x] 3.1 (integration) 实现基于 settings 的地区/来源自动发布策略解析，第一期不新增策略模型；支持未允许地区转人工、允许来源进入自动候选和地区每轮/每日上限
- [x] 3.2 (application) 调整自动评分或发布就绪流程，使国际新闻转人工、自动发布和跳过原因写入自动化日志或决策原因
- [x] 3.3 (application) 调整 `auto_publish_batch_task`，按地区上限选择候选文章且不影响日本既有自动发布
- [x] 3.4 (application) 补充自动发布策略测试，覆盖非日本默认人工、未允许地区、允许来源、blocker 不绕过、地区每轮上限、地区每日上限和日本不受国际上限影响
- [x] 3.5 (application) 审查地区自动发布查询性能；如现有字段索引不足，新增安全迁移或在设计文档中记录暂不加索引的依据

## 4. 后台地区生产观测

- [x] 4.1 (application) 新增或扩展后台地区生产概览，展示每个地区今日新增、待翻译、翻译失败、待审核、已自动发布、已人工发布和公开数量
- [x] 4.2 (application) 在地区生产概览展示近期 QQ 交付成功、等待、跳过和失败数量
- [x] 4.3 (application) 扩展来源健康视图，支持按地区筛选并展示国际来源停滞、成功无新增、运行中和失败状态
- [x] 4.4 (application) 地区生产概览查询必须使用今日/近 24 小时等有限窗口、聚合查询和必要的 `select_related` / `prefetch_related`，避免无界扫描和 N+1
- [x] 4.5 (application) 补充后台视图测试，覆盖未启用地区、启用无新增、地区筛选、有限窗口和 QQ 交付聚合

## 5. QQ 多地区推送灰度

- [x] 5.1 (integration) 调整 QQ 自动推送消息生成，国际新闻消息包含可读地区标签，且日本消息保持既有结构可读
- [x] 5.2 (application) 补充 QQ 推送测试，覆盖旧群空/非法地区不接收国际新闻、测试群接收显式允许地区和正式群必须显式配置地区
- [x] 5.3 (application) 补充多地区推送验收测试，覆盖 `region_not_allowed`、`not_high_value`、URL 不可访问、OneBot 离线不增加尝试次数和总开关关闭
- [x] 5.4 (operations) 更新 QQ 推送运行手册，说明测试群灰度、正式群扩大地区、OneBot 在线检查和紧急停用步骤

## 6. 多语言术语运营检查

- [x] 6.1 (application) 在多地区审计或后台概览中加入按原文语言统计的正式术语命中、外部马名保护和候选池积压指标
- [x] 6.2 (integration) 将术语质量异常暴露给国际新闻自动发布策略，使核心术语缺失、外部马名未保留或候选池积压可转人工或阻止扩大灰度
- [x] 6.3 (application) 补充多语言术语运营测试，覆盖英文术语命中概览、繁中/英文外部马名保护概览和候选池积压阈值

## 7. 文档、验证与收尾

- [x] 7.1 (operations) 更新 `docs/deploy_runbook.md`，补充多地区常态生产启用、验收、停用和回滚流程
- [x] 7.2 (operations) 更新 `docs/current_state.md`、`docs/project_status.md` 和必要 `docs/decisions.md`，记录本变更边界、外部数据库不进新闻调度和生产灰度策略
- [x] 7.3 (application) 执行 `DB_ENGINE=sqlite python manage.py check`
- [x] 7.4 (application) 执行相关 Django 测试和完整 `stable` 测试
- [x] 7.5 (operations) 执行 `openspec validate operate-multiregion-news-production --strict`
- [x] 7.6 (operations) 执行 `openspec validate --all` 和 `git diff --check`
- [x] 7.7 (operations) 执行 `docker compose -f docker-compose.prod.yml config` 和 `docker compose -f docker-compose.prod.lowcost.yml config`
- [x] 7.8 (operations) 若进入生产部署，按运行手册检查服务器 `HEAD`、备份 `.env`、关键 `.env` 项、容器状态、web/worker/beat/nginx 日志、`/healthz/`、首页、后台登录入口和地区 tab
- [x] 7.9 (operations) 若进入生产灰度，执行只读审计、测试群灰度、自然调度窗口观察、QQ 测试群验收和回滚开关确认

注：本轮 `/opsx:apply` 未进入生产部署或生产灰度；7.8 / 7.9 的完成口径为运行手册、配置边界和本地验证已覆盖，真实生产执行需另开部署/灰度窗口。
