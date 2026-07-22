## 0. Pre-declared hypotheses

- [ ] 0.1 (integration) 瞬态恢复 PASS：429/5xx/timeout/connection fixture 在前两次失败、第三次成功时最终成功且总执行 3 次；超过上限只产生一次终态通知
- [ ] 0.2 (integration) 内容安全 PASS：placeholder/required term/response incomplete 耗尽 provider 内重试后 Celery 自动重试为 0；任一内容错误被自动循环或放宽为 BLOCKER
- [ ] 0.3 (application) 幂等 PASS：并发重复任务仅 1 个调用 provider，迟到任务对成功/人工终态写入为 0；任一覆盖为 BLOCKER
- [ ] 0.4 (operations) 历史恢复 PASS：每批最多 10 篇、只恢复批准瞬态类别，队列峰值和 provider 429 不高于上线前基线；重试风暴为 BLOCKER

## 1. 错误分类与持久化

- [ ] 1.1 (integration) 实现纯异常分类器，覆盖 rate limit、5xx、timeout、connection、JSON、完整性、placeholder、required term、auth/config 和 unknown (req: req-translation-error-classification) (adr: adr-001-translation-error-codes)
- [ ] 1.2 (application) 增加 ArticleTranslationStatus.RETRYING、article/run error code 与 next_retry_at 字段、索引和 migration，历史行保持兼容 (req: req-transient-translation-retry)
- [ ] 1.3 (integration) 调整 TranslationRun 完成路径保存稳定码、HTTP/attempt 元数据和有界错误摘要，不保存敏感请求内容 (req: req-translation-error-classification)
- [ ] 1.4 (application) 更新后台、筛选、API/序列化和地区聚合对 retrying/错误码的显示 (req: req-region-translation-funnel)

## 2. 有界任务级重试与认领

- [ ] 2.1 (application) 将 translate task 改为 bound task，并实现含首次总次数 3 的指数退避、抖动、上限和下一重试时间 (req: req-transient-translation-retry) (adr: adr-002-bounded-task-retry)
- [ ] 2.2 (integration) 保留 provider 内内容重译边界，内容错误耗尽后直接终态失败且不触发 Celery retry (req: req-transient-translation-retry) (adr: adr-003-content-retry-boundary)
- [ ] 2.3 (application) 实现短事务文章认领、活动翻译跳过、retrying 到期认领和成功/人工终态保护 (req: req-translation-task-claim) (adr: adr-004-translation-claim)
- [ ] 2.4 (application) 将翻译失败通知移动到最终失败分支，重试中只记录日志，确保每个终态签名只通知一次 (req: req-transient-translation-retry)
- [ ] 2.5 (application) 增加全局每分钟重试预算、单批与并发配置，预算耗尽时安全延后而非丢弃 (req: req-translation-retry-budget)

## 3. 历史失败恢复

- [ ] 3.1 (application) 新增 translation_failed dry-run manifest 命令，支持地区/来源/时间/错误码/limit/稳定游标和内容指纹；历史空码优先读取 run 元数据，message projection 明示证据与置信度且不自动批准 (req: req-translation-recovery-manifest) (adr: adr-005-translation-manifest)
- [ ] 3.2 (application) 实现 manifest apply 的 SHA/漂移/终态/活动任务检查，只重新排队批准的瞬态类别 (req: req-translation-recovery-manifest)
- [ ] 3.3 (application) 将恢复派发接入全局预算和批次上限，输出下一游标、派发/跳过/漂移计数 (req: req-translation-retry-budget)
- [ ] 3.4 (integration) 确保历史恢复成功后复用现有评分/门禁链路，命令本身不评分、不发布、不 QQ (req: req-translation-recovery-manifest)

## 4. 生产漏斗与文档

- [ ] 4.1 (integration) 扩展多地区审计，按错误码、年龄、attempt、retrying/terminal/manual 汇总并保持查询有界 (req: req-region-translation-funnel)
- [ ] 4.2 (application) 为 2 小时最终失败异常激增增加有冷却的 ops signal，包含地区和主要错误码 (req: req-region-translation-funnel)
- [ ] 4.3 (operations) 更新 `.env.example`、current_state、decisions、deploy_runbook 和 project_status，记录开关、预算、manifest、灰度和回滚 (adr: adr-002-bounded-task-retry) (adr: adr-005-translation-manifest)

## 5. 自动化验证

- [ ] 5.1 (integration) 增加各错误类型分类与 provider 内容重试边界测试 (req: req-translation-error-classification) (req: req-transient-translation-retry)
- [ ] 5.2 (application) 增加 Celery eager 下退避次数、retrying 状态、终态单通知、关闭开关和预算耗尽测试 (req: req-transient-translation-retry) (req: req-translation-retry-budget)
- [ ] 5.3 (application) 增加并发认领、迟到结果、人工编辑/发布终态保护和幂等测试 (req: req-translation-task-claim)
- [ ] 5.4 (application) 增加 manifest 零写入、SHA、漂移、错误类别选择、游标和批次上限测试 (req: req-translation-recovery-manifest)
- [ ] 5.5 (operations) 运行目标/完整测试、migration apply/rollback/reapply、Django check、Compose config、OpenSpec strict 和 `git diff --check` (req: req-region-translation-funnel)

## 6. 生产灰度与历史恢复

- [ ] 6.1 (operations) 备份并部署迁移，保持瞬态自动重试关闭，核对 HEAD/容器环境/worker/beat/healthz 和队列基线 (req: req-transient-translation-retry)
- [ ] 6.2 (operations) 对一个地区新稿开启重试 24 小时，验收成功率、总 attempts、费用、429、队列峰值和终态通知 (req: req-transient-translation-retry) (req: req-translation-retry-budget)
- [ ] 6.3 (operations) 扩到五地区后为历史失败生成新 manifest，按地区每批最多 10 篇恢复批准瞬态类别 (req: req-translation-recovery-manifest)
- [ ] 6.4 (operations) 记录历史恢复成功/失败/仍人工数量和后续公开漏斗，异常时关闭自动重试并停止后续批次 (req: req-region-translation-funnel)
