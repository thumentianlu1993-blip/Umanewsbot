## 0. Pre-declared hypotheses

- [ ] 0.1 (integration) 漏斗 PASS：fixture 中 listing/detail/stale/non-racing/duplicate/created 各阶段计数精确且总量可对账；任一静默丢失为 BLOCKER
- [ ] 0.2 (integration) probe 安全 PASS：每次候选探测请求数有界且 CrawlJob/NewsArticle/ProductionWindow/NewsSource 写入为 0；任一业务写入为 BLOCKER
- [ ] 0.3 (operations) 初始 7 天观察目标：入库 HK≥7、FR≥21、UK≥56、US≥140；公开 HK≥3、FR≥7、UK≥14、US≥35。目标用于复盘而非硬发布门槛
- [ ] 0.4 (operations) 生产直开 PASS：每地区同时新增生产批准来源初始不超过 2 个，首 4 个窗口日期/非赛马/正文严重错误、容器重启和 healthz 失败均为 0，队列不持续增长；任一违反为 BLOCKER

## 1. 结构化抓取漏斗

- [ ] 1.1 (application) 为 CrawlJob 增加有界 `result_payload` JSONField 和 migration，历史行默认为空对象 (req: req-crawl-structured-yield) (adr: adr-001-source-funnel-first)
- [ ] 1.2 (integration) 定义国际 adapter 统一抓取计数器和稳定跳过/错误原因码，不保存原始正文或无界 HTML (req: req-crawl-structured-yield)
- [ ] 1.3 (integration) 接入现有国际抓取任务，记录 listing/detail/stale/non-racing/duplicate/created 并保持部分失败继续语义 (req: req-crawl-structured-yield)
- [ ] 1.4 (integration) 扩展多地区审计，从 CrawlJob 有限窗口和文章状态聚合逐来源抓取→公开全漏斗 (req: req-source-full-funnel) (adr: adr-001-source-funnel-first)
- [ ] 1.5 (application) 更新来源健康与地区后台展示，区分上游无稿、解析失败、旧稿、重复、入库和下游阻断 (req: req-source-full-funnel)

## 2. 现有来源诊断与 parser 修复

- [ ] 2.1 (integration) 扩展只读 probe 输出 HTTP、listing、详情、真实日期、canonical ID、相关性和重复证据，保证业务表零写入 (req: req-source-probe-readonly)
- [ ] 2.2 (integration) 为香港现有两个来源保存最小、脱敏、无 Cookie/token 的有限 fixture，逐项对照近 7 天 upstream 供给与 adapter 产出 (req: req-source-probe-readonly) (adr: adr-002-repair-before-expand)
- [ ] 2.3 (integration) 为法国现有来源执行同样对照，并检查时效过滤、canonical TDN 归一和语言链路 (req: req-source-probe-readonly) (adr: adr-002-repair-before-expand)
- [ ] 2.4 (integration) 仅对证据确认的漏抓实施 parser/date/filter/canonical 最小修复并补 fixture 回归；无漏抓则记录 upstream 低供给结论 (req: req-crawl-structured-yield)

## 3. 候选来源准入与有界并行上线

- [ ] 3.1 (operations) 建立香港、法国优先的候选来源准入清单，记录访问、正文、日期、语言、相关性、canonical、重复和许可证据 (req: req-regional-source-admission) (adr: adr-003-source-admission)
- [ ] 3.2 (integration) 为通过准入且现有 adapter 不覆盖的候选实现最小 adapter/fixture；blocked/deferred 候选不得进入来源注册 (req: req-regional-source-admission)
- [ ] 3.3 (integration) 将 accepted 来源以 `enabled=false/production_approved=false` 同步，保持现有五地区和来源 allowlist 默认不扩大 (req: req-regional-source-admission)
- [ ] 3.4 (operations) 为每地区最多 2 个 accepted 来源直接生产启用提供命令、分来源证据目录、首 4 窗口内容/容量观察和快速停用步骤 (req: req-bounded-parallel-production-rollout) (adr: adr-004-bounded-parallel-rollout)
- [ ] 3.5 (operations) 若无 accepted 候选，输出带证据的 no-go 并停止该地区扩源，不以弱来源替代 (req: req-regional-source-admission)

## 4. 目标、告警与文档

- [ ] 4.1 (application) 将地区供给/公开观察目标作为配置化审计阈值，低于目标输出分层缺口而不触发强制发布 (req: req-regional-yield-slo) (adr: adr-005-regional-slo)
- [ ] 4.2 (operations) 更新 `.env.example`、current_state、decisions、deploy_runbook、project_status，记录漏斗、准入、SLO、有界并行直开、熔断和回滚 (req: req-regional-yield-slo)

## 5. 自动化验证

- [ ] 5.1 (integration) 增加逐阶段计数、部分详情失败、全 stale、全 duplicate、非赛马过滤和有界 payload 测试 (req: req-crawl-structured-yield)
- [ ] 5.2 (integration) 增加 probe 业务表零写入、请求预算、403/429/反机器人/TLS 停止扩大测试 (req: req-source-probe-readonly)
- [ ] 5.3 (integration) 为每个 parser 修复或新 adapter 增加真实留存 fixture 的 listing/detail/date/canonical/正文回归 (req: req-regional-source-admission)
- [ ] 5.4 (application) 增加全漏斗对账、地区 SLO 分层和“供给达标但公开未达”归因测试 (req: req-source-full-funnel) (req: req-regional-yield-slo)
- [ ] 5.5 (operations) 运行目标/完整测试、migration apply/rollback/reapply、Django check、Compose config、OpenSpec strict 和 `git diff --check` (req: req-bounded-parallel-production-rollout)

## 6. 有界并行生产启用与在线观察

- [ ] 6.1 (operations) 在前置四个变更稳定后部署漏斗能力，保持新来源全部关闭，只读采集 7 天基线 (req: req-source-full-funnel)
- [ ] 6.2 (operations) 对香港/法国通过准入的来源按每地区初始最多 2 个设置 enabled/production_approved，直接进入现有生产窗口，不设置 shadow (req: req-bounded-parallel-production-rollout)
- [ ] 6.3 (operations) 观察首 4 个窗口和 24 小时 listing→公开漏斗、重复、日期、正文、CPU、内存、队列、容器与 healthz；异常逐源停用且停止提高并发 (req: req-bounded-parallel-production-rollout)
- [ ] 6.4 (operations) 逐地区观察完整 7 天供给/公开目标；UK/US 仅在修复下游后仍未达标时重复准入流程 (req: req-regional-yield-slo)
