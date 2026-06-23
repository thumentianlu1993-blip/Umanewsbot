## 1. 配置、数据结构与状态基础

- [x] 1.1 (application) 新增自动发布门禁配置读取：AI 改写开关、发布内容来源、高价值来源规则、warning 告警开关、告警收件人、重复检测阈值和检查窗口。
- [x] 1.2 (application) 设计并新增结构化门禁结果存储字段或兼容现有 JSON 字段，确保每个 issue 可保存 code、severity、message、route 和 payload。
- [x] 1.3 (application) 新增 `WorkflowStatus.DUPLICATE`、重复内容字段、迁移和 Django Admin 展示字段；中等相似内容仍转入 `pending_review`。
- [x] 1.4 (application) 导入首批非马名普通词 / 固定译法种子，并确保可通过数据迁移或管理命令重复执行。
- [x] 1.5 (operations) 更新 `.env.example` 和部署文档，说明新开关默认值、warning 邮件配置和灰度启用方式。

## 2. 门禁、术语与重复检测服务

- [x] 2.1 (integration) 将自动化校验输出改为结构化 issue，并统一 blocker、warning、info 的生成和聚合逻辑。
- [x] 2.2 (integration) 调整硬门禁规则：保留缺标题、缺正文、正文过短、乱码、广告导航页、翻译失败等 blocker；移除长采访、引语较多和数字一致性硬阻断。
- [x] 2.3 (integration) 支持基准翻译稿作为自动发布内容源，关闭 AI 改写时跳过改写任务但继续执行基础门禁和 warning 记录；不得伪造改写字段，只能复用 `effective_*` 和必要的非人工发布字段补齐。
- [x] 2.4 (integration) 实现高价值来源配置化评分放行，首批覆盖 `netkeiba` 访问量榜和注目数榜，且不得绕过 blocker。
- [x] 2.5 (integration) 优化未知马名识别：排除首批非马名普通词，并将未收录马名未原样保留降级为 warning。
- [x] 2.6 (integration) 优化关键术语校验：区分核心术语与背景术语，核心术语缺失输出 blocker，背景术语缺失输出 warning，并支持日文原词、日文别名、中文译名、中文别名和归一化等价写法。
- [x] 2.7 (integration) 新增本地文本相似度重复检测服务，比对近期待发布或已发布文章，高度重复输出 duplicate blocker，中等相似输出 manual-review blocker。
- [x] 2.8 (application) 将自动化分流逻辑改为只由 blocker 阻断自动发布，warning 初期不阻断但必须持久化和展示。

## 3. 后台展示与邮件告警

- [x] 3.1 (application) 在候选新闻列表、候选详情和自动化日志中展示评分结论、blocker、warning、info、重复检测结果和相似文章链接。
- [x] 3.2 (integration) 新增高价值 warning 邮件告警服务，邮件包含候选详情链接、原文链接、来源、分数、warning 列表和当前发布状态。
- [x] 3.3 (integration) 增加 warning 邮件 24 小时去重和跳过日志，确保缺少收件人配置时记录 skipped 且不阻断自动发布。
- [x] 3.4 (application) 确保自动发布批次和公开前台仍只发布 `workflow_status=published` 且 `published_to_web_at` 非空的文章。

## 4. 测试、验收与文档

- [x] 4.1 (application) 增加模型、配置和后台展示测试，覆盖结构化 issue 保存、warning 不阻断、blocker 阻断和重复状态展示。
- [x] 4.2 (integration) 增加自动化服务测试，覆盖高价值来源评分放行、基准翻译发布、AI 改写跳过、术语普通词过滤、核心/背景术语校验和重复检测。
- [x] 4.3 (integration) 增加邮件告警测试，覆盖高价值 warning 发送、普通 warning 不发送、blocker 不发送和缺少收件人 skipped。
- [x] 4.4 (application) 使用从候选新闻池 bad case 固化出的本地测试样例复测，包括 `タイトル`、`メートル`、`オッズ`、`ハンデ`、背景术语缺失和数字省略样例，不让自动化测试依赖生产数据库。
- [x] 4.5 (operations) 执行 `DB_ENGINE=sqlite python manage.py check`、`DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable` 和 OpenSpec 校验。
- [x] 4.6 (operations) 更新 `docs/current_state.md`、`docs/decisions.md` 和必要的部署运行手册，记录新门禁策略、灰度开关、告警行为和回退方式。
