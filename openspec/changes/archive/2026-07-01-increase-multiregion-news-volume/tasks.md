## 0. Pre-declared hypotheses

- [x] 0.1 (operations) PASS: 新窗口调度生产部署后默认关闭；BLOCKER: 迁移或重启后自动开始 15 分钟高频抓取
- [x] 0.2 (operations) PASS: 只有已启用、生产批准且可爬性通过的来源进入 15 分钟抓取；BLOCKER: 历史停用、高风险或 JRA 等长间隔来源被误改为 15 分钟
- [x] 0.3 (operations) PASS: 同一窗口并发执行不会重复发布、重复推送或超过配额；BLOCKER: 并发 worker 可绕过窗口唯一键或配额账本
- [x] 0.4 (operations) PASS: 发布 0 篇或 QQ 推送 0 条均有结构化原因；BLOCKER: 只能从日志推断原因
- [x] 0.5 (operations) PASS: OneBot 离线、来源 403/429、全站上限触发均可被后台和通知感知；BLOCKER: 失败仅消耗重试或静默跳过

## 1. 数据模型、迁移与配置

- [x] 1.1 (application) 新增窗口运行模型，覆盖抓取、发布和 QQ 推送窗口，并增加窗口唯一键、状态、claim/lease、执行时间、模式、原因摘要和重跑字段
- [x] 1.2 (application) 新增窗口候选决策和 QQ 目标群决策模型，保存每篇文章、每个目标群的入选、跳过、失败、阻断原因和解释 payload
- [x] 1.3 (application) 新增发布与 QQ 配额账本模型，支持地区窗口、地区小时、群小时和全站小时额度原子占用
- [x] 1.4 (application) 新增重要赛事模型，保存地区、年份、赛事等级、原始/规范赛事名、可选外部 ID、别名、地区时区、本地日期/时间、UTC 升频窗口、启用状态和备注
- [x] 1.5 (application) 为 `NewsSource` 或等价来源运行态增加生产批准、有效间隔、backoff 截止、暂停原因、失败/成功连续次数、错误分类和重要赛事升频开关
- [x] 1.6 (application) 生成并检查迁移，覆盖 PostgreSQL 唯一约束、索引、默认值、回填和 SQLite 测试兼容
- [x] 1.7 (application) 在 `server/app/settings.py` 增加窗口总开关、默认 15/5 分钟、上限、backoff 阈值、候选回看、通知冷却和回滚配置
- [x] 1.8 (operations) 在 `.env.example` 增加窗口总开关、默认 15/5 分钟、上限、backoff 阈值、候选回看、通知冷却和回滚配置说明

## 2. 窗口调度与幂等执行

- [x] 2.1 (integration) 实现固定时钟窗口计算服务，支持日常 15 分钟、重要赛事 5 分钟和最多 3 小时补跑回看
- [x] 2.2 (integration) 实现窗口原子 claim/lease 服务，覆盖重复调度、worker 崩溃、lease 过期和手动重跑
- [x] 2.3 (application) 新增抓取窗口 Celery 任务，按来源窗口触发抓取并写入抓取窗口结果
- [x] 2.4 (application) 新增地区发布窗口 Celery 任务，处理候选选择、硬门禁、去重、评分、配额占用和发布状态变更
- [x] 2.5 (application) 新增地区/群 QQ 窗口 Celery 任务，处理高价值筛选、群配置、配额、OneBot 状态、delivery 创建和 0 推送原因
- [x] 2.6 (application) 将新窗口调度接入 Celery Beat，并通过总开关保持部署后默认关闭
- [x] 2.7 (application) 调整旧 `auto_publish_batch_task`，在新窗口开关开启时委托新窗口服务或避免与新窗口重复发布

## 3. 来源健康、15 分钟抓取与自动降频

- [x] 3.1 (integration) 调整内置来源同步，保护人工启停、生产批准、人工降频、暂停、有效间隔和重要赛事升频配置不被覆盖
- [x] 3.2 (integration) 实现来源生产资格选择服务，只选择已启用、生产批准且可爬性通过的来源进入 15 分钟日常抓取
- [x] 3.3 (integration) 实现来源错误分类，覆盖 `http_403`、`http_429`、`captcha_or_blocked`、`timeout`、`parse_error`、`empty_success`、`server_error`
- [x] 3.4 (integration) 实现来源自动降频和恢复规则：连续失败 3 次降频，403/429/验证码更保守 backoff，连续成功 3 次逐步恢复
- [x] 3.5 (application) 扩展来源健康后台，显示当前有效间隔、降频原因、下一次允许抓取时间、最近错误和恢复入口
- [x] 3.6 (application) 新增单来源立即重试入口，带确认步骤并遵守来源暂停/backoff 状态

## 4. 重要赛事升频

- [x] 4.1 (integration) 实现重要赛事时间窗口服务，按地区当地时间录入并转 UTC 判断，支持无开跑时间的日期级窗口
- [x] 4.2 (application) 实现重要赛事后台列表、筛选、创建、编辑、启用/停用和当前窗口状态展示
- [x] 4.3 (application) 实现重要赛事 CSV 导入，按赛事名、年份、地区、赛事等级 upsert，并支持更新时间和启用状态
- [x] 4.4 (integration) 将重要赛事模式接入窗口频率判断，同地区重叠窗口合并，不叠加频率和上限
- [x] 4.5 (application) 在地区生产中心展示当前命中的重要赛事、窗口起止时间和缺少开跑时间提示

## 5. 发布选择、硬门禁、去重与配额

- [x] 5.1 (integration) 实现统一自动发布硬门禁服务，输出结构化 blocker，并被预览、发布窗口和重跑复用
- [x] 5.2 (integration) 实现内容/事件去重服务或确定性内容指纹策略，保存地区内强去重和跨地区弱去重证据
- [x] 5.3 (integration) 实现窗口候选选择服务，按硬过滤、去重、评分、重要赛事/榜单加分、保底边界和配额排序
- [x] 5.4 (integration) 实现保底发布规则：最低 45 分，不绕过硬门禁，记录 `region_minimum_fill`，并标记不可自动 QQ
- [x] 5.5 (integration) 实现发布配额占用，支持每地区每窗口最多 5、全站日常每小时 60、重要赛事每小时 120，并记录配额不足原因
- [x] 5.6 (application) 调整文章后台筛选和详情展示，显示未自动发布原因、去重赢家、保底发布标记和配额限制

## 6. QQ 推送窗口与运营通知

- [x] 6.1 (integration) 实现 QQ 窗口候选服务，只选择高价值文章，排除保底发布文章的自动 QQ
- [x] 6.2 (integration) 实现 QQ 配额占用，支持每地区每窗口最多 3、每群日常每小时 12、每群重要赛事每小时 24、全站日常每小时 40、全站重要赛事每小时 80
- [x] 6.3 (integration) 持久化 QQ 目标群决策，覆盖无发布文章、非高价值、群未订阅地区、上限触发、OneBot 离线、URL 不可访问、已推过等原因
- [x] 6.4 (integration) 保持 OneBot 离线不消耗发送尝试次数，并确保离线状态写入 QQ 窗口结果
- [x] 6.5 (integration) 实现独立运营通知服务，支持内部运营 QQ 群、邮件兜底、冷却、失败日志和关闭开关
- [x] 6.6 (application) 新增生产摘要任务和管理命令，输出每日/近 24 小时地区抓取、发布、QQ、0 原因、降频来源和上限触发

## 7. 后台地区生产中心、预览与重跑

- [x] 7.1 (application) 新增地区生产中心页面，展示全局模式、五地区最近抓取/发布/QQ 窗口、异常来源、0 结果原因、当前重要赛事和快速入口
- [x] 7.2 (application) 新增窗口详情页，展示窗口摘要、候选决策、目标群决策、配额占用、错误、补跑和重跑记录
- [x] 7.3 (application) 新增发布窗口预览，展示候选文章、硬门禁原因、去重输赢、分数、上限和预计发布列表，且不写业务状态
- [x] 7.4 (application) 新增 QQ 窗口预览，展示可推文章、目标群、跳过原因、上限和预计推送数，且不创建发送任务
- [x] 7.5 (application) 新增发布窗口和 QQ 窗口手动重跑入口，默认不重新抓取外部来源，并记录操作者与重跑次数
- [x] 7.6 (application) 调整后台导航，把地区生产中心作为多地区生产主入口，并链接来源健康、文章候选、重要赛事和 QQ 交付记录

## 8. 直接上线、回滚与文档

- [x] 8.1 (operations) 新增或更新只读生产资格审计命令，输出将进入 15 分钟调度的来源、风险来源、地区开关、QQ 目标和重要赛事状态
- [x] 8.2 (operations) 更新 `docs/current_state.md`、`docs/project_status.md`、`docs/decisions.md` 和 `docs/deploy_runbook.md`，记录新窗口生产规则、直接上线口径、审计、启用、观察和回滚步骤
- [x] 8.3 (operations) 补充部署运行手册：迁移前备份、默认关闭验证、资格审计、开启五地区、最近 4 个窗口验收、异常回滚和通知检查
- [x] 8.4 (operations) 确认全局关闭、单地区关闭、单来源暂停/降频、关闭 QQ 自动推送和关闭 ops 通知的回滚配置均有文档和测试

## 9. 测试与验证

- [x] 9.1 (application) 增加模型约束测试，覆盖窗口唯一键、配额账本唯一键、重要赛事 upsert、来源运行态字段和 SQLite 兼容
- [x] 9.2 (application) 增加窗口幂等和并发测试，覆盖重复 claim、lease 过期、补跑、手动重跑、并发发布和并发 QQ 配额竞争
- [x] 9.3 (integration) 增加来源健康测试，覆盖 15 分钟生产批准选择、停用/高风险来源排除、403/429 分类、自动降频、恢复和内置同步不覆盖人工配置
- [x] 9.4 (application) 增加重要赛事测试，覆盖 CSV upsert、无开跑时间日期级窗口、时区转换、重叠窗口合并和地区独立
- [x] 9.5 (integration) 增加发布选择测试，覆盖硬门禁、保底最低 45 分、保底不自动 QQ、地区内去重、跨地区弱去重、全站上限和未发布原因
- [x] 9.6 (integration) 增加 QQ 窗口测试，覆盖高价值筛选、地区/群/全站上限、0 推送原因、OneBot 离线、不重复推送和 ops 通知冷却
- [x] 9.7 (application) 增加后台视图测试，覆盖地区生产中心、窗口详情、预览不写状态、重跑记录、重要赛事管理和来源健康入口
- [x] 9.8 (application) 执行 `DB_ENGINE=sqlite python manage.py check`
- [x] 9.9 (application) 执行相关 Django 测试和完整 `stable` 测试
- [x] 9.10 (operations) 执行 `openspec validate increase-multiregion-news-volume --strict`
- [x] 9.11 (operations) 执行 `openspec validate --all` 和 `git diff --check`
- [x] 9.12 (operations) 执行 `docker compose -f docker-compose.prod.yml config` 和 `docker compose -f docker-compose.prod.lowcost.yml config`

## 10. 生产启用验收

- [x] 10.1 (operations) 部署前备份生产数据库和 `.env`，确认没有运行中的外部数据库 importer 或高风险长任务
- [x] 10.2 (operations) 部署代码和迁移后确认新窗口调度仍关闭，`manage.py check`、本地/公网 `/healthz/`、首页、后台登录和地区生产中心均通过
- [x] 10.3 (operations) 在生产执行只读资格审计，保存将进入 15 分钟调度的来源和风险来源清单
- [x] 10.4 (operations) 开启五地区新日常规则后观察窗口 smoke，确认每地区抓取窗口触发、发布 0-5 篇且 0 发布有明确原因；深夜新闻低峰时段的最近 4 个自然窗口观察按用户确认延期到次日继续
- [x] 10.5 (operations) 观察 QQ 窗口 smoke，确认每地区每窗口不超过 3 条、0 推送有明确原因、每群/全站上限未被绕过、保底文章不自动 QQ；深夜新闻低峰时段的最近 4 个自然窗口观察按用户确认延期到次日继续
- [x] 10.6 (operations) 抽检公开首页和五个地区页，确认新发布文章无明显非赛马、重复刷屏、乱码翻译或地区错误；次日自然窗口再补更完整抽检
- [x] 10.7 (operations) 若存在启用赛事窗口，确认对应地区切换到 5 分钟模式；若无赛事，确认仍为日常模式
- [x] 10.8 (operations) 验证内部运营 QQ 群或邮件可收到每日摘要、异常通知和恢复通知，并确认通知冷却生效
