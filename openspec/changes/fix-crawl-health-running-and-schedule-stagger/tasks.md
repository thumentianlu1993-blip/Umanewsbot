## 1. 来源健康运行中状态修复

- [x] 1.1 (application) 调整 `server/stable/views.py` 的 `_source_health()`，拆分最新 `CrawlJob` 与最近已完成 `CrawlJob`，并优先展示最新运行中任务。
- [x] 1.2 (application) 确保运行中任务不使用默认 `success_count=0` 生成“成功无新增”，最近成功 / 失败 / 无新增摘要只来自已完成抓取记录。
- [x] 1.3 (application) 为超过 60 分钟仍未完成的 `started` 抓取记录展示“运行超时”或等价疑似卡住状态，避免陈旧运行中记录长期遮住停滞。
- [x] 1.4 (application) 如模板需要补充文案或 badge，更新后台工作台和来源列表，展示“运行中”和“运行超时”状态及可读摘要。
- [x] 1.5 (application) 为创建已久但没有任何 `CrawlJob` / `last_crawl_at` 的启用来源展示“长时间未运行”，避免长期显示普通“未运行”。
- [x] 1.6 (application) 停用来源不参与“长时间未运行”判定，避免人工关闭来源后继续误报警。

## 2. netkeiba 抓取调度错峰修复

- [x] 2.1 (application) 调整 `server/app/settings.py` 中 `crawl-netkeiba-access` 与 `crawl-netkeiba-attention` 触发分钟，采用新着顺 `00` 分、访问量榜 `16` 分、注目数榜 `26` 分，并避开周日高频新着顺分钟。
- [x] 2.2 (operations) 更新 `docs/deploy_runbook.md` 和 `docs/current_state.md`，记录最终错峰分钟、运行中 / 运行超时状态语义和生产验收方式。

## 3. JRA 单篇详情异常隔离

- [x] 3.1 (application) 调整 `_crawl_jra_source()` 的单篇详情处理，只跳过 `fetch_detail()` 中的日期 / 结构解析异常，并记录跳过摘要；列表、网络和数据库异常仍按整体失败处理。
- [x] 3.2 (application) 成功但存在 JRA 跳过项时，将跳过摘要同时写入本轮 `CrawlJob` 和来源最近摘要，便于事后追溯。

## 4. 测试与验证

- [x] 4.1 (application) 增加后台来源健康回归测试，覆盖最新 job 运行中且旧状态为成功时必须显示“运行中”。
- [x] 4.2 (application) 增加后台来源健康回归测试，覆盖首次 job 运行中时不得显示“长时间未运行”。
- [x] 4.3 (application) 增加后台来源健康回归测试，覆盖超过 60 分钟仍为 `started` 的 job 显示为运行超时 / 疑似卡住。
- [x] 4.4 (application) 增加后台来源健康回归测试，覆盖创建已久且从未运行的启用来源显示“长时间未运行”。
- [x] 4.5 (application) 增加后台来源健康回归测试，覆盖创建已久且从未运行的停用来源不显示“长时间未运行”。
- [x] 4.6 (application) 增加 Celery Beat 调度断言，确认 netkeiba 新着顺、访问量榜、注目数榜分钟值两两不同，访问量榜 / 注目数榜避开周日高频新着顺分钟，且仍为小时级。
- [x] 4.7 (application) 增加 JRA 单篇详情结构异常回归测试，确认异常详情被跳过且同轮后续新闻继续处理，并在本轮 `CrawlJob` 保留摘要。
- [x] 4.8 (operations) 执行 `DB_ENGINE=sqlite python manage.py check` 和相关 `stable` 测试。
- [x] 4.9 (operations) 执行 `openspec validate fix-crawl-health-running-and-schedule-stagger --strict`。

## 5. 生产部署与验收

- [ ] 5.1 (operations) 生产部署时重启 `beat / worker / web`，确认 Celery Beat 已加载 `00/16/26` 分错峰调度。
- [ ] 5.2 (operations) 生产验收：在同一小时内确认 netkeiba 新着顺、访问量榜、注目数榜分别生成错峰 `CrawlJob`，并确认运行中任务在后台显示为“运行中”、超时运行中任务显示为疑似卡住。
