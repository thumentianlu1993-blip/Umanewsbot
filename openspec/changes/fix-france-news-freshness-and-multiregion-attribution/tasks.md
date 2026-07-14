## 0. Pre-declared hypotheses

- **H1 法国最新稿发现：** 使用 TDN posts 日期倒序后，最近 72 小时审核查询的去重新候选数 MUST 大于旧 `/search` 入口；若没有提升或出现历史稿越过 3 天门禁则 BLOCKER。
- **H2 时间可信度：** France Galop 日期 fixture 与生产抽样 MUST 100% 解析为 Europe/Paris 对应 UTC；重复 fallback 抓取覆盖 verified 时间数 MUST 为 0，否则 BLOCKER。
- **H3 翻译恢复：** 可恢复失败 MUST 在最多 3 次内成功或进入可见耗尽终态；重复任务并发产生重复 TranslationRun 数 MUST 为 0，否则 BLOCKER。
- **H4 归属质量：** 有效 gold set MUST 保持总量 >=150、五个运营地区各 >=10、跨地区 >=20；总体主地区准确率 >=95%、单地区 >=90%、相关 precision >=95%、recall >=50%、无依据变化 <=2%、过度扩散 <=1%、锁定覆盖 0，否则 BLOCKER。线上 recall 单独下降只告警并阻止扩大灰度，不自动关闭；precision/过度扩散失败要求回退。
- **H5 批量性能：** 250 篇 PostgreSQL 基准 MUST <=30 SQL、<=30 秒、RSS 增量 <=256 MiB，否则 BLOCKER。
- **H6 分发幂等：** 相关地区开启后，同一 article/target 的网页公开与 QQ 交付新增重复数 MUST 为 0，否则 BLOCKER。

## 1. 数据契约与配置

- [x] 1.1 (application) 为 `NewsArticle` 新增 nullable `published_at_verified`、`published_at_evidence`、翻译错误类别/下次重试/耗尽时间和归属状态/置信度/规则版本字段及必要索引 (adr: adr-002-structured-state)
- [x] 1.2 (application) 新增 `MultiregionAttributionRun` 持久运行账本及外键正确的 `MultiregionAttributionLock` 可续租锁，并生成 backward-compatible Django 迁移；历史发布时间可信度保持 NULL，不在迁移中联网或批量回填 (adr: adr-002-structured-state)
- [x] 1.3 (application) 在 `server/app/settings.py` 增加 TDN 法国查询集合、新鲜度、翻译自动重试开关/次数/退避/批次/陈旧阈值、`MULTIREGION_ATTRIBUTION_MODE` 与质量门槛配置，并兼容旧布尔开关 (adr: adr-003-translation-retry) (adr: adr-004-attribution-mode)
- [x] 1.4 (operations) 在 `.env.example` 和两个生产 Compose 配置约定中补充新配置，默认保持归属写入和相关地区查询关闭 (adr: adr-004-attribution-mode)

## 2. 法国最新稿与可信发布时间

- [x] 2.1 (integration) 将 `TDNFranceKeywordAdapter` 改为 `/wp/v2/posts` 日期倒序查询，传递 UTC `after`、有限字段和 3 天时间下界 (req: req-tdn-date-search) (req: req-france-english-coverage)
- [x] 2.2 (integration) 将 `TDNFranceBroadKeywordAdapter` 改为配置化多查询聚合，按 canonical 身份去重并按真实发布时间倒序稳定截断 (req: req-tdn-date-search)
- [x] 2.3 (integration) 保存 TDN 查询词、请求 URL、`date_gmt`、时间可信度、去重和跳过原因，保持部分查询失败时的可审计降级 (req: req-france-query-audit)
- [x] 2.4 (integration) 为 `FranceGalopEnglishNewsAdapter` 实现英文详情页官方日期解析、时区转换和原始证据保存 (req: req-published-evidence)
- [x] 2.5 (integration) 在来源 draft 中统一生成 `published_at_evidence`，明确 `api/detail/listing/fallback` 与 verified 状态 (req: req-published-evidence)
- [x] 2.6 (integration) 修改入库 upsert：不可信 fallback 只允许新建时使用，重复抓取不得覆盖已有时间，后续 verified 时间可审计纠正 (req: req-fallback-preservation)
- [x] 2.7 (integration) 在自动发布校验中阻断 `published_at_verified=false` 的新来源文章，同时保持 legacy NULL 文章兼容 (req: req-published-evidence)
- [x] 2.8 (application) 扩充来源抓取摘要，使 TDN/France Galop 能分别报告新稿、重复、历史过滤、时间缺失、时间不可信和查询失败 (req: req-source-freshness-observability)
- [x] 2.9 (application) 新增 France Galop 近期错误发布时间修复管理命令，支持有界网络取证、dry-run、manifest、漂移校验和逐篇原子 commit，且不触发直接发布或 QQ (req: req-time-repair)

## 3. 翻译失败自动恢复

- [x] 3.1 (integration) 实现翻译异常分类器，区分限流、供应商不可用、超时、永久 payload、认证和未知错误，并解析 `Retry-After` (req: req-translation-errors)
- [x] 3.2 (application) 在翻译失败路径保存错误类别、自动重试次数、下次重试时间和耗尽时间，同时保留原始错误摘要 (req: req-translation-backoff) (req: req-translation-idempotency)
- [x] 3.3 (application) 实现到期失败选择与每分钟有限批次 Celery Beat 任务，受默认关闭开关控制并使用 60/300/900 秒退避、抖动和配置上限 (req: req-translation-backoff) (req: req-translation-idempotency)
- [x] 3.4 (application) 在 worker 中使用预期状态/到期时间条件 UPDATE 原子 claim，防止周期任务、人工按钮和来源提升对同一文章并发翻译 (req: req-translation-backoff) (req: req-translation-idempotency)
- [x] 3.5 (application) 将翻译恢复成功文章重新接入既有自动化评分流程，清空下次重试/耗尽字段并记录由重试恢复进入候选的审计原因 (req: req-translation-backoff)
- [x] 3.6 (application) 在运营后台提供错误类别、重试次数、下次时间和耗尽筛选，以及单篇/勾选批量立即重试入口 (req: req-translation-operations)
- [x] 3.7 (application) 复用现有通知体系，对永久失败、重试耗尽和重试任务持续异常发送去重告警与快速处理链接 (req: req-translation-operations)
- [x] 3.8 (application) 实现超时 `TRANSLATING` 状态恢复为 transient stale failure，并记录 TaskExecutionLog/文章审计原因 (req: req-translation-backoff) (req: req-translation-idempotency)

## 4. 多地区归属准确度

- [x] 4.1 (integration) 重构归属证据生成，分别输出中心赛事/赛场、核心对象所属地、标题导语上下文、背景提及和来源 fallback (req: req-attribution-evidence) (req: req-global-france-attribution)
- [x] 4.2 (integration) 阻止来源 URL、来源备注、普通词术语和历史履历/血统背景地名单独参与主地区判定 (req: req-attribution-evidence) (req: req-global-france-attribution)
- [x] 4.3 (integration) 实现叙事中心规则：标题有强主体行动/成果证据时主体地区为主、赛事地区相关；否则赛事地区为主，可信对象原属地相关 (req: req-attribution-evidence) (req: req-global-france-attribution)
- [x] 4.4 (integration) 实现法国主题规则：France Galop、法国育马场、Arqana/法国拍卖、法国马场和机构新闻在无更强赛事中心时以法国为主 (req: req-attribution-evidence) (req: req-global-france-attribution)
- [x] 4.5 (integration) 输出规则版本、数值置信度、high/medium/low 档位、正反证据和 `applied/fallback/needs_review` 状态 (req: req-attribution-confidence)
- [x] 4.6 (integration) 对互斥赛事中心、仅弱上下文、超过 3 个候选相关地区和缺少强证据的跨来源主地区变化执行 fail-closed 复核 (req: req-attribution-spread)
- [x] 4.7 (application) 保证人工 `attribution_locked` 在新采集、重评、dry-run 和 commit 中均不可被覆盖，并记录 locked skip (req: req-attribution-dry-run)
- [x] 4.8 (application) 将归属重处理改为持久 dry-run/run ID/manifest/commit/resume，保存 before/after、证据、指标、规则/术语/gold/文章指纹、cursor 和已完成 ID，并使用 `MultiregionAttributionLock` 可续租 lease (req: req-attribution-run-ledger)
- [x] 4.9 (application) 实现 `off|shadow|enforce` 单一模式：summary 使用 applied/shadow 命名空间且兼容 legacy 扁平读取，shadow 不覆盖 applied，enforce 才写主/相关地区，相关地区查询仅在 enforce 下生效 (req: req-attribution-mode)

## 5. 质量基准与生产资格

- [x] 5.1 (application) 建立 159 篇版本化单审 gold labels，保存 article/source、输入 SHA、期望地区、审核来源和理由；有效样本 >=150、五个运营地区各 >=10、跨地区 >=20，单审不得伪造第二审核人，多人标注存在冲突时须裁决，未决/漂移样本不进入分母 (req: req-attribution-quality)
- [x] 5.1a (application) 支持单审部分样本校准：未选择任何地区的行忽略、明确排除保留、原始/规范值可审计；`provisional_single_review` 仅标记审核来源，不再自动 no-go。本批固定 159 条标签，最少地区法国 11、跨地区 24，主地区 98.11%、相关 precision 100%、recall 54.84%，当前覆盖与质量门槛全部通过，可进入 shadow (req: req-attribution-quality)
- [x] 5.2 (integration) 实现 gold set 评估器，计算总体/分地区主地区准确率、相关地区 precision/recall、无依据主地区变化率、过度扩散率和人工锁定覆盖数 (req: req-attribution-quality)
- [x] 5.3 (application) 将生产资格门槛接入 dry-run 报告：总体主地区准确率 95%、单地区 90%、相关 precision 95%、recall 50%、无依据变化 2%、过度扩散 1%、锁定覆盖 0；线上 recall 波动只告警并阻止扩大，precision/过度扩散失败要求回退 (req: req-attribution-quality)
- [x] 5.4 (application) 当任一门槛不达标时输出 no-go 并阻止 commit/启用建议，不允许通过降低阈值自动放行 (req: req-attribution-quality)
- [x] 5.5 (application) 为最近 72 小时生产样本生成分层抽检清单，完整列出所有主地区变化、全部 `needs_review` 和五地区随机样本 (req: req-attribution-dry-run)
- [x] 5.5a (application) 修正生产审计入口：新增 `--scope all_articles` 覆盖最近窗口全部有效文章及已发布稿，默认门禁补跑范围保持兼容；输出无截断标记、全部主地区变化、全部 `needs_review`、人工锁定和五地区确定性分层样本，将执行策略绑定 manifest，截断 run 禁止 commit，全量 commit 只写归属且不改变门禁/发布/QQ (req: req-attribution-dry-run)
- [x] 5.6 (integration) 实现 `AttributionBatchContext`，一次预加载并索引术语/alias/赛事证据供 gold set、dry-run 和 commit 复用，避免逐文章 ORM 扫描 (req: req-attribution-performance)
- [x] 5.7 (application) 为生产质量报告增加有效分母、缺失/漂移/未决样本、Wilson 区间及 SQL/耗时/RSS/预加载计数 (req: req-attribution-quality)
- [x] 5.8 (operations) 固化 Gold Set 持续扩充规则：新增来源、规则版本、shadow 误判和运营争议必须进入后续版本，并保留旧版本与指标变化 (req: req-attribution-quality)

## 6. 多地区展示、窗口与 QQ

- [x] 6.1 (application) 复核公开地区页、搜索/API 和后台列表在相关地区查询开启后使用单文章记录并保持稳定分页去重 (req: req-attribution-rollout)
- [x] 6.2 (application) 复核发布窗口只消耗主地区配额，相关地区可见文章计入可见内容但不得重复公开 (req: req-single-publish-delivery)
- [x] 6.3 (application) 复核 QQ 即时与窗口推送按 article+target 幂等，主地区和相关地区同时命中同一群时只创建一次交付 (req: req-single-publish-delivery)
- [x] 6.4 (application) 增加归属灰度阶段控制与资格显示：off、shadow、enforce 仅新文章、网页/测试群相关查询、近期回填、正式群 (req: req-attribution-rollout) (req: req-rollout-observability)
- [x] 6.5 (application) 在运营后台展示规则版本、归属模式、相关地区查询开关、gold set 指标、最近 dry-run、`needs_review` 和当前灰度阶段 (req: req-attribution-rollout) (req: req-rollout-observability)

## 7. 窗口观测与运营入口

- [x] 7.1 (application) 扩充法国来源/窗口统计，分别展示候选、去重入库、真实旧文过滤、时间不可信、翻译状态、归属状态、门禁、公开和 QQ 数量 (req: req-source-freshness-observability)
- [x] 7.2 (application) 为 0 发布增加 `search_missed_latest / published_at_unverified / translation_retry_waiting / translation_retry_exhausted / attribution_needs_review / related_region_visible` 等明确原因 (req: req-attribution-observability) (req: req-translation-retry-observability)
- [x] 7.3 (application) 从失败来源、失败翻译、归属待复核和窗口 0 原因提供到具体文章/任务的快速处理入口 (req: req-translation-operations) (req: req-attribution-observability)
- [x] 7.4 (operations) 更新 `docs/current_state.md`、`docs/decisions.md`、`docs/project_status.md` 和 `docs/deploy_runbook.md`，记录配置、指标、灰度、回滚和法国数量预期的真实口径 (req: req-rollout-observability)

## 8. 自动化测试与静态验证

- [x] 8.0 (application) 添加模型/迁移测试，覆盖 legacy NULL、默认值、索引、run/lock 外键、旧配置兼容和 PostgreSQL/SQLite schema 行为 (adr: adr-002-structured-state)
- [x] 8.1 (integration) 添加 TDN posts 查询参数、日期倒序、多查询去重、部分失败、时间边界和历史稿不挤占新稿测试 (req: req-tdn-date-search)
- [x] 8.2 (integration) 添加 France Galop 多日期格式、时区、缺失日期、fallback 证据和 verified 时间解析测试 (req: req-published-evidence) (req: req-fallback-preservation)
- [x] 8.3 (integration) 添加 Europe/Paris 夏令时、upsert 不覆盖可信时间、fallback 后纠正、legacy NULL 兼容、自动发布阻断和历史时间修复漂移测试 (req: req-published-evidence) (req: req-fallback-preservation)
- [x] 8.4 (application) 添加翻译错误分类、`Retry-After`、开关关闭、退避次数、耗尽、批次上限、条件 claim、陈旧恢复、人工重试和恢复评分测试 (req: req-translation-idempotency)
- [x] 8.5 (integration) 添加五地区赛事中心、海外参赛、育马/拍卖/机构、普通地名、背景履历、冲突与真实三地区归属单元测试 (req: req-attribution-evidence) (req: req-attribution-spread)
- [x] 8.6 (application) 添加 gold set 标注裁决、SHA 漂移、有效分母、指标/Wilson 边界、单地区 no-go、持久 run/lease、部分失败 resume、重复 commit 和规则版本漂移测试 (req: req-attribution-run-ledger) (req: req-attribution-quality)
- [x] 8.7 (application) 添加地区页/API 去重、主地区配额、相关地区可见、QQ 单交付和灰度开关组合测试 (req: req-single-publish-delivery)
- [x] 8.8 (application) 添加后台失败原因、快速入口、staff 权限、有限查询窗口和大样本查询数测试 (req: req-attribution-observability)
- [x] 8.9 (integration) 在包含 17,474 条术语、38,806 个候选、17 个来源和 250 篇真实校准文章的 PostgreSQL fixture 上验证五轮基准为 5 SQL、1.66–2.14 秒、约 49 MiB RSS，满足 30 SQL、30 秒和 256 MiB 门槛 (req: req-attribution-performance)
- [x] 8.10 (application) 运行目标测试、完整 `stable` 测试、`manage.py check`、迁移一致性和 Python 编译检查 (adr: adr-002-structured-state)
- [x] 8.11 (operations) 运行两个生产 Compose config、OpenSpec strict/all、`git diff --check` 和敏感信息检查 (adr: adr-010-staged-rollout)

## 9. 生产部署与灰度验收

- [x] 9.1 (operations) 部署前确认生产 HEAD、tracked/untracked 状态、容器、Nginx runtime config、外部导入/锁、Celery active/reserved、web/worker/beat 当前开关和法国来源状态，并生成 `.env` 与数据库备份及校验值 (adr: adr-010-staged-rollout)
- [x] 9.2 (operations) 部署代码和迁移，确认 web/worker/beat 均为 attribution mode=off、相关查询关闭、翻译自动重试关闭，并验证迁移、容器、日志、内外 `/healthz/`、首页、地区页和后台入口 (req: req-attribution-rollout)
- [ ] 9.3 (operations) 在生产执行 TDN/France Galop 只读 probe、gold set 与最近 72 小时持久归属 dry-run，保存 run ID/manifest/runtime 导出并按质量与性能硬门槛判定 go/no-go (req: req-attribution-dry-run) (req: req-attribution-quality)
- [ ] 9.4 (operations) 人工审核所有主地区变化、全部 `needs_review`、France Galop 时间修复和 `7871/7699` 等翻译重试清单 (req: req-attribution-dry-run) (req: req-attribution-quality)
- [ ] 9.5 (operations) 使用锁定 manifest 小批修复可信发布时间并重试瞬时翻译失败，验证不直接重复发布或创建 QQ 交付 (req: req-recent-manifest-backfill)
- [ ] 9.6 (operations) 确认最新合格 run 与当前规则/术语/gold 版本一致且不超过 24 小时，完成至少 24 小时 shadow 与全部主地区变化/`needs_review` 人工复核后切 enforce，仅处理新文章并保持相关地区查询关闭，再连续观察至少 24 小时 (req: req-attribution-rollout)
- [ ] 9.7 (operations) 为网页和测试 QQ 群开启相关地区查询，验收地区页、发布窗口、QQ 去重、失败原因和快速处理入口 (req: req-attribution-rollout)
- [ ] 9.8 (operations) 通过审核后按 manifest 回填最近 72 小时，再扩大正式群；任何指标退化先关相关查询、再关归属写入 (req: req-attribution-rollout)
- [ ] 9.9 (operations) 验收上线后至少 3 个日常窗口和一个可模拟的重要赛事窗口，按来源候选、翻译、归属、门禁、公开和 QQ 分层记录法国及五地区真实数量 (req: req-france-layered-volume)
- [ ] 9.10 (operations) 将最终生产 commit、配置、备份、指标、发布增量、残余风险与回滚结果写回状态文档，满足全部验收后再归档 change (req: req-rollout-observability)
