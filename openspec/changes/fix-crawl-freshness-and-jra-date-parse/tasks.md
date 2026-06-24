## 1. 抓取解析与调度实现

- [x] 1.1 (integration) 增强 `JRAAdapter` 日期解析，兼容带年份、无年份、零填充和非零填充日期，并处理跨年附近的合理年份回退。
- [x] 1.2 (application) 调整 Celery Beat 中 `crawl_netkeiba_access` 与 `crawl_netkeiba_attention` 调度，使访问量榜和注目数榜至少按小时级频率运行并错峰执行。
- [x] 1.3 (application) 同步更新 `BUILTIN_SOURCE_DEFINITIONS` 中访问量榜和注目数榜的 `crawl_interval_minutes` 与备注，确保后台展示、异常检测和实际调度一致。
- [x] 1.4 (application) 确认抓取任务成功但无新增时仍写入成功状态、重复数量和可理解摘要，不把 `new=0` 误记为失败。

## 2. 后台来源健康展示

- [x] 2.1 (application) 在来源列表或仪表盘 view 层组装每个启用来源的最近抓取健康摘要，包括最近抓取时间、状态、新增数、重复数和错误摘要。
- [x] 2.2 (application) 更新来源列表或仪表盘模板，清晰区分“成功无新增”“抓取失败”“长时间未运行”。
- [x] 2.3 (application) 保持后台展示轻量，不新增数据库模型；如需详细信息，链接或展示最近 `CrawlJob` 摘要。

## 3. 测试与验证

- [x] 3.1 (integration) 增加 JRA 日期解析测试，覆盖 `2026年5月31日`、`5月31日`、零填充日期和跨年附近日期。
- [x] 3.2 (integration) 增加 JRA 单条日期异常测试，确认异常条目被记录且同列表其他可解析新闻继续处理。
- [x] 3.3 (application) 增加 Celery Beat 调度和内置来源定义测试或配置断言，确认访问量榜和注目数榜至少小时级运行、错峰，且 `crawl_interval_minutes` 与实际调度一致。
- [x] 3.4 (application) 增加后台来源健康展示测试，覆盖成功无新增、失败错误摘要和长时间未运行。
- [x] 3.5 (application) 增加抓取任务记录测试，确认 netkeiba 无新增时 `CrawlJob` 与 `NewsSource.last_crawl_message` 表达为成功无新增。
- [x] 3.6 (operations) 执行 `DB_ENGINE=sqlite python manage.py check` 和相关 `stable` 测试。
- [x] 3.7 (operations) 执行 `openspec validate fix-crawl-freshness-and-jra-date-parse --strict`。

## 4. 文档、部署与生产验收

- [x] 4.1 (operations) 更新 `.env.example` 或部署文档，记录 netkeiba 榜单新抓取频率、JRA 日期解析修复和来源健康排障入口。
- [x] 4.2 (operations) 更新 `docs/current_state.md` 与 `docs/deploy_runbook.md`，记录本 change 的上线状态、验证命令和回滚方式。
- [ ] 4.3 (operations) 生产部署时重启 `beat / worker / web`，确认 Celery Beat 已加载新调度。
- [ ] 4.4 (operations) 生产验收：确认 JRA 抓取不再因无年份日期失败，netkeiba 访问量榜/注目数榜在连续两个小时内按新频率生成错峰 `CrawlJob`，后台来源健康摘要可读。
