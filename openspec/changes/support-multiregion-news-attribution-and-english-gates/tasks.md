## 1. 数据模型与迁移

- [x] 1.1 (application) 新增 `NewsArticleRelatedRegion` 或等价独立关联表，保留 `NewsArticle.racing_region` 作为主地区，并为 `article + region` 去重和 `region + article` 查询建立约束与索引
- [x] 1.2 (application) 为文章增加内容类别、归属来源、归属摘要等必要字段或可复用元数据，保证旧文章默认兼容单地区逻辑
- [x] 1.3 (application) 编写 Django 迁移并验证 PostgreSQL 与 SQLite 均可应用，避免影响既有已发布文章和审核队列

## 2. 多地区归属服务

- [x] 2.1 (integration) 新增或扩展新闻归属服务，按“人工结果优先、赛事地区、核心对象地区、来源默认地区”的顺序计算主地区和关联地区
- [x] 2.2 (integration) 支持法国实体海外新闻同时进入法国池和比赛对应地区池，支持英国来源中的爱尔兰内容暂归英国并保留 `ireland` 标签
- [x] 2.3 (integration) 支持来源、标题、正文、核心术语、赛事、马、骑手、练马师等信号生成归属解释，供后台和窗口审计展示
- [x] 2.4 (application) 将归属服务接入抓取入库、候选生成、自动化处理、人工重算和补跑流程，确保新旧入口得到一致结果
- [x] 2.5 (application) 提供统一的文章地区集合和地区可见性 QuerySet helper，并支持配置关闭相关地区参与查询时回退到只看 `NewsArticle.racing_region`

## 3. 英文门禁与内容类别

- [x] 3.1 (integration) 将英文核心术语门禁改为使用文章主地区加关联地区的地区集合，避免相关地区术语被地区筛选误排除
- [x] 3.2 (integration) 在既有英文门禁语义分层基础上补充可接受译名差异处理，区分专名缺失、普通英文词、缩写、机构名和可解释翻译差异
- [x] 3.3 (integration) 增加内容类别识别与来源配置支持，覆盖 `news`、`preview`、`result_brief`、`official_notice`、`racecard_update`、`tips`、`feature`、`sales_breeding`、`other`
- [x] 3.4 (integration) 将内容类别用于软门禁、自动发布和 QQ 推送资格判断，但不把普通 `tips`、营销投注提示和一般公告作为硬门禁放行理由
- [x] 3.5 (application) 提供重算命令或管理动作，支持 dry-run 查看归属和门禁变化，并在 commit 模式下只恢复候选资格，不直接发布

## 4. 发布窗口与公开页面

- [x] 4.1 (application) 调整生产窗口候选查询，使地区窗口包含主地区或关联地区命中的文章，并在总体候选集中按文章去重
- [x] 4.2 (application) 调整配额统计，使多地区文章只消耗主地区窗口配额，关联地区仅计入可见和有内容统计
- [x] 4.3 (application) 调整窗口审计输出，展示每个地区的主地区命中、关联地区命中、发布数、0 篇原因和门禁原因
- [x] 4.4 (application) 调整公开首页和地区 tab 查询，使地区 tab 展示主地区或关联地区文章，全部 tab 同一篇文章只出现一次
- [x] 4.5 (application) 调整文章列表和详情页的地区标签展示，清楚区分主地区与关联地区

## 5. QQ 推送

- [x] 5.1 (integration) 调整 QQ 群订阅匹配逻辑，使群订阅任一主地区或关联地区时都可收到该文章
- [x] 5.2 (integration) 保持同一文章对同一 QQ 群只发送一次，并确保现有发送去重日志继续生效
- [x] 5.3 (integration) 调整 QQ 推送资格规则，使高价值新闻、赛果简报和重要赛事预览可推送，普通 tips、营销投注提示和一般公告默认不推送
- [x] 5.4 (application) 在 QQ 窗口审计中展示每个地区、每个群的候选数、发送数、跳过原因和 0 篇原因

## 6. 后台与运营入口

- [x] 6.1 (application) 在后台文章详情、候选详情或审核入口展示主地区、关联地区、内容类别和归属解释
- [x] 6.2 (application) 提供一键修改主地区与关联地区的运营入口，保存最终归属结果即可，不强制记录额外操作日志
- [x] 6.3 (application) 确保人工修改后后续重算、发布窗口和 QQ 推送尊重人工结果，不被自动归属覆盖

## 7. 测试覆盖

- [x] 7.1 (application) 增加模型和迁移测试，覆盖旧文章兼容、关联地区去重、索引查询、配置回退到单地区查询和人工修改保存
- [x] 7.2 (integration) 增加归属服务单元测试，覆盖来源默认地区、赛事优先、核心对象优先、法国实体海外多地区、爱尔兰暂归英国和无实体 tips 回退
- [x] 7.3 (integration) 增加英文门禁测试，覆盖多地区术语集合、普通英文词降级、专名缺失阻断、可接受译名差异和内容类别影响
- [x] 7.4 (application) 增加发布窗口测试，覆盖主地区配额消耗、关联地区不消耗配额、总列表去重、地区 tab 命中和 0 篇原因
- [x] 7.5 (integration) 增加 QQ 推送测试，覆盖任一地区订阅命中、同群去重、高价值/赛果/预览可推、普通 tips 默认不推和 0 篇原因
- [x] 7.6 (application) 增加重算命令测试，覆盖 dry-run 不写入、commit 只恢复候选资格、不直接发布以及人工归属不被覆盖

## 8. 运维配置与文档

- [x] 8.1 (operations) 更新 `.env.example` 或默认配置说明，记录多地区归属开关、相关地区查询回退、英文门禁和重算命令涉及的可配置项
- [x] 8.2 (operations) 更新 `docs/current_state.md`、`docs/project_status.md`、`docs/decisions.md`，记录主地区/关联地区、配额、QQ 和法国英文源边界的最新决策
- [x] 8.3 (operations) 更新 `docs/deploy_runbook.md`，补充迁移、回滚、重算 dry-run、线上抽样验收和窗口审计检查步骤

## 9. 验证

- [x] 9.1 (application) 运行 `DB_ENGINE=sqlite python manage.py check`
- [x] 9.2 (application) 运行多地区归属、发布窗口、后台展示和重算命令相关测试
- [x] 9.3 (integration) 运行英文门禁、内容类别、抓取接入和 QQ 推送相关测试
- [x] 9.4 (operations) 运行 `docker compose -f docker-compose.prod.yml config` 和 `docker compose -f docker-compose.prod.lowcost.yml config`
- [x] 9.5 (operations) 运行 `openspec validate support-multiregion-news-attribution-and-english-gates --strict`
- [ ] 9.6 (operations) 上线前执行只读或 dry-run 抽样，确认香港、英国、法国、美国、日本候选的主地区、关联地区、门禁原因和 QQ 资格符合预期

## 10. Code review 门禁返修

- [x] 10.1 (integration) 将普通词忽略判断收窄到当前文章实际命中的 source term，禁止同一术语记录内的其他 alias 连带绕过核心术语门禁
- [x] 10.2 (application) 增加 ignored alias 与可信专名共存的回归测试，确认未被忽略的实际命中仍产生 `core_term_missing`
- [x] 10.3 (operations) 更新项目状态并重新运行目标测试、完整 `stable` 测试、Django/OpenSpec/迁移和 diff 校验

## 11. 生产灰度性能修复

- [x] 11.1 (integration) 在 `MULTIREGION_ATTRIBUTION_ENABLED=false` 时直接返回当前归属，禁止先扫描术语库再判断开关。
- [x] 11.2 (integration) 人工归属锁定且未 force 时复用当前归属，避免无意义推断并保护人工结果。
- [x] 11.3 (application) 增加关闭开关和人工锁定均不调用自动推断的回归测试。
- [x] 11.4 (operations) 记录生产 CPU 热点、修复边界和验证结果；保持五地区产品抽样任务未完成、生产开关关闭。
