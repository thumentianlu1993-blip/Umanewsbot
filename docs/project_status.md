# 项目状态文档

最后更新时间：`2026-07-07`
当前版本：`v0.0.1`（正式域名 HTTP 接入已修复，自动化运营 MVP、公开首页资讯流、抓取新鲜度修复、后台快速术语创建与当前稿术语应用、外部马名索引识别链路、榜单重点 QQ 推送、公开文章 ID URL、国际赛马资讯扩展、多地区生产窗口、术语种子数据准备和赛事日历 MVP 均已部署生产）

> 角色说明：
> 本文档用于保留项目级概览与摘要信息。
> 当前真实工作状态、最近一次关键修复、线上实际进展，请以 [docs/current_state.md](E:/Codex/docs/current_state.md) 为准。

## 1. 项目背景

目标是构建一个面向中文用户的日本赛马新闻系统，形成：

`采集 -> 翻译 -> 自动分流/改写 -> 人工编辑 / 自动发布 -> 发布 -> QQ 群自动推送`

当前阶段重点是让站点进入“可持续自动更新”的内容运营阶段，同时继续保证真实上线稳定性。

## 2. 当前技术方案

- 后端：`Django + Celery`
- 数据库：`PostgreSQL / SQLite`
- 队列：`Redis`
- 翻译：`OpenAI-compatible`（已支持 SiliconFlow）
- 媒体存储：`local / OSS` 双后端
- 推送：`OneBot`
- 部署：`Docker Compose`

## 3. 已完成（业务能力）

- `netkeiba` 与 `JRA` 采集
- 新闻/图片/快照/术语/推送/日志等数据模型
- 翻译状态机与失败重试
- 未收录马名保留日文、翻译完整性校验
- 未收录马名翻译保护已增强：使用占位符保留原文名，模型仍漏保留时记录 warning 但不阻断整篇翻译
- 外部马名索引识别链路已部署生产：`ExternalHorseAlias` 可参与马名识别、翻译保护、发布校验和候选发现；外部马名只用于确认“这是马名”，不批量写入正式术语库 `TermEntry`
- 术语工作台与批量导入
- 候选池、编辑台、发布流
- 自动化内容运营 MVP：
  - 自动评分分流 `auto / manual / ignored`
  - AI 编辑改写稿与基准翻译稿双层保存
  - 一致性校验、批量自动发布、自动化日志
  - 自动发布批量规则：常规每批 4 篇，周日北京时间 13:00-16:00 每批 10 篇
  - 邮件通知 MVP 与通知日志
- 前台信息流与详情页已升级为公开站点专用 Web + 移动 H5 资讯流
- QQ 推送链路：已新增并部署自动推送实现，支持重点优先/全公开、多群、去重、有限重试、OneBot 业务失败识别、OneBot 离线发送前预检、`sending` 陈旧恢复、后台交付记录和按群限速；生产 OneBot / NapCat 网关已登录并在测试群验证发送，当前生产 `QQ_PUSH_ENABLED=true`、`QQ_PUSH_SCOPE=high_value_only`、`QQ_PUSH_IMPORTANCE_STRATEGY=ranked` 已生效。
- 抓取新鲜度与来源健康：netkeiba 新着顺 / 访问量榜 / 注目数榜已切换为每小时 `00/16/26` 分错峰抓取，JRA 无年份日期解析已修复，后台来源健康摘要已上线
- 榜单来源提升：已部署 `netkeiba:latest -> access/attention` 主来源提升，访问量榜和注目数榜不互相覆盖，并为 QQ 榜单推送暴露 `source_elevated` 信号。
- 榜单重点推送：已部署 `QQ_PUSH_IMPORTANCE_STRATEGY=ranked`，`QQ_PUSH_SCOPE=high_value_only` 下只推 netkeiba 访问量榜 / 注目数榜且无 blocker 的公开文章。
- 公开文章 ID URL：已部署公开详情主路径 `/news/<article_id>/`，非纯数字旧 slug URL 跳转到 ID URL，QQ 消息链接不再包含标题全文。
- 赛事日历 / 年度赛事页 MVP：已部署生产 `f3c4c46`。已实现 `RaceEvent` 产品层、公开 `/races/` 赛事日历、年度详情页、后台 `/admin/race-events/` 工作台、CSV 种子导入、候选资料写入/应用、新闻自动/手动关联和人工移除保护；生产已导入 5 条 P0/P1 赛事种子与 10 条别名，第一版不建设马匹数据库或完整赛果库。
- 2026 五地区重要赛事填充：已按官方来源导入日本 JRA/NAR、香港 HKJC 当前公开 2025/26 马季内香港 G1/G2/G3、美国 TOBA Grade 1/2/3、英国 BHA Flat Group 1/2/3 与 Jump 2026 年 1-4 月 Grade 1/2、法国 France Galop Groupe I/II/III。当前生产 `RaceEvent=995`、`RaceEventAlias=3277`；2026 五地区计数为日本 `186`、香港 `20`、美国 `412`、英国 `203`、法国 `174`。剩余缺口是 HKJC 尚未公开 2026/27 年末香港本地分级赛日期，以及英国 Jump 2026 年 10-12 月仍需下一季官方书或其他官方结构化来源。
- 国际赛马资讯扩展：已部署多地区新闻源、公开首页地区 tab、多语言术语别名、群级 QQ 地区配置和 HKJC 受控导入；生产第一版已启用 `Sponichi`、`HKJC Racing News`、`SCMP Racing`、`Sporting Life Racing`、`Sky Sports Racing`、`France Galop English News`、`TDN France keyword`、`TDN`、`Horse Racing Nation`，其中 `BHA` 因生产探测返回 `403` 暂停启用。
- 全球赛马数据库抓取能力：香港 HKJC、英国 Sporting Life、法国 Geny、美国 Horse Racing Nation 的受控 importer 能力已部署；`2026-06-30` 已开始香港 HKJC 慢速真实 dry-run，最新 plan 为 `146` 场且前两场完整 dry-run 成功，仍未执行生产 `--commit`。
- 香港 HKJC 长窗口 dry-run：`2026-06-30` 已按用户要求启动到 `2024-07-01` 的慢速后台抓取计划，plan 共 `1496` 场；为部署多地区新闻常态生产，当前 dry-run worker 已暂停在 `hkjc-slow-dryrun.state=92`，仍未写正式表。
- 多地区正式术语库补齐：`2026-07-04` 已导入 WP Stud 香港/来港社区马名 `210` 条、HKJC 当前本地马 A-Z 官方译名 `1258` 条，并从 HKJC 本地赛果回溯香港历史马名、骑师名和赛事名到 `2026-07-04`。`2026-07-05` 已继续完成 HKJC overseas 官方 Race Card/QIDS 术语回溯，覆盖 `2024-01-01` 至 `2026-07-04`，正式导入海外 `horse / jockey / race` 候选 `7691` 条中的新增/更新项；同时补齐当前发现的 WP Stud 赛事、骑师和马场社区术语，正式新增 `1891` 条。`2026-07-06/07` 已完成最终清洗与 WP Stud HorseList 全量马名补齐：最终 `seed_candidates_final.csv` 共 `11257` 行，生产正式导入新增 `1169`、更新 `10088`、错误/跳过 `0`，并修复既有马名国别后缀和赛事年份标记脏数据。当前生产正式术语为 `TermEntry=16558`、`TermAlias=19293`，active 马名国别后缀术语 `0`、active 赛事年份标记术语 `0`；`source_language=en` 已覆盖香港、英国、法国、美国、日本和 other 的马名/赛事/骑师/马场，HKJC 官方仍保持最高优先级，WP Stud 只作为社区来源和人工审核佐证。
- HKJC 日语 alias 合并与文章术语回填工具：`2026-07-07` change `hkjc-ja-alias-article-backfill` 已实现并部署生产 `a65c1ed`。新增 `merge_hkjc_ja_aliases` 用于把同中文目标的日语主术语安全并入 HKJC 英文概念并停用冗余日语主术语；新增 `backfill_article_terms` 用于对已发布文章中文字段执行可审计术语回填。生产已合并 `112` 条 HKJC 日语 alias，文章回填扫描 `713` 篇日文已发布文章并更新 `29` 个字段、跳过 `2` 个人工字段；`/news/7117/` 已确认显示 `欢快舞步`。
- 多地区新闻常态生产：`operate-multiregion-news-production` 已实现、部署生产并归档；`2026-07-01` 已继续归档 `add-netkeiba-horse-data-import`、`expand-international-racing-coverage`、`guard-qqbot-offline-send`，生产服务器运行 `8c83708`，已具备只读审计、通用 enabled 新闻来源轮询、非日本默认人工审核、地区/来源自动发布灰度、后台地区生产概览、QQ 国际新闻地区标签和运行手册。当前 `NEWS_SOURCE_POLL_ENABLED=true`，轮询覆盖五个地区，每轮最多 12 个来源；非日本自动发布 allowlist 已开启香港、英国、法国、美国四个地区并保留每日小上限护栏，正式群仍需显式配置地区。
- 法国新闻源扩展：`2026-07-07` OpenSpec change `expand-france-news-sources` 已部署生产提交 `bfc3445`。新增 `tdn_france_broad` 英文补充来源，生产只读探测 accepted：HTTP `200`、列表 `20`、详情样本 `5`、详情错误 `0`、重复 `0`。生产已启用 `NewsSource#21`，`enabled=true`、`production_approved=true`、有效轮询 `15` 分钟；发布白名单已加入 `tdn_france:access` 和 canonical 入库使用的 `tdn:access`。真实抓取验证已入库法国新来源文章 `4` 篇，均完成翻译并进入正常人工复核，当前无来源白名单或抓取失败阻断。
- 英文术语门禁误挡修复：`2026-07-07` OpenSpec change `fix-english-term-gate-region-filter` 已部署生产提交 `bfc3445`。英文发布校验第一版改为同地区 + 全局术语范围，配置化高歧义英文词降级为 warning；新增近期误挡文章重处理命令和生产审计 `gate_issues` 摘要。上线后 dry-run 验证：香港、美国、法国最近 3 小时无可释放 `core_term_missing` 候选；英国有 `1` 篇候选但仍是真实核心术语缺失，未执行 commit。
- `2026-07-07 21:00` 线上回归复核：生产 `HEAD=dcb9b90`，服务健康；`tdn_france_broad` 再次探测 accepted，生产自然窗口已通过 `source_config=21` 入库法国文章 `10` 篇，其中 `9` 篇已翻译、`1` 篇翻译中。该来源当前 `CrawlJob#9355` 仍在运行，Celery 日志显示模型接口持续 `200 OK`，结论为单轮处理耗时偏长但仍在推进；最近 90 分钟发布/QQ 窗口均有成功账本和明确 0 原因。英文门禁 dry-run 未发现可释放误挡文章。
- `2026-07-07` 已临时暂停 `tdn_france_broad`：该来源使用 TDN WordPress search API，返回历史相关性结果且不带发布时间，adapter 将缺失日期兜底为当前时间，导致 2020/2022/2023/2024 旧文被当作当天新闻入库并有 5 篇自动发布。生产 `NewsSource#21` 已设为 `enabled=false`、`production_approved=false`；修复前不得重新启用。后续需改为二次读取 TDN post API 的真实 `date_gmt` 并按新鲜度窗口过滤旧文，同时处理已公开的旧文。
- 后台术语运营：候选详情页和文章编辑台支持原文选区快速加入术语库；新增术语成功后可一次性将该术语应用到当前文章已有中文稿
- 前后台移动端适配

## 3.1 已完成并部署生产（体验升级）

- 公开首页资讯流升级主 OpenSpec change：`upgrade-public-home-info-feed`
  - Web 端已实现：轻导航、主头条、普通新闻流、右侧热门/重点辅助模块
  - 移动 H5 已实现：轻顶部、轻量头条、高密度左文右图新闻列表
  - 实施方式：严格 TDD，按可测试行为逐轮执行 RED -> GREEN -> REFACTOR；热门代理使用有限候选集与批量快照读取
  - 首版不做原生 App、手工置顶、搜索频道、专题、赛事日历、站内评论或站内浏览量
  - 当前状态：本地实现、Django 测试、OpenSpec 校验、桌面/移动浏览器验收和 OpenSpec 归档已完成；`2026-06-22` 已通过 PR #1 合并并部署到生产 `e834f58`
- 移动端首页密度 follow-up：
  - 已小幅压缩移动端头条区域，隐藏头条摘要并收紧顶部间距
  - 390px 浏览器验收中，首屏普通新闻卡可见数量从生产基线的 3 条提升到 4 条
  - 当前状态：`2026-06-23` 已通过 PR #2 合并并部署到生产 `04e2ee9`

## 4. 已完成（上线准备）

### 4.1 生产配置

- 安全配置：`DEBUG`、`ALLOWED_HOSTS`、`CSRF_TRUSTED_ORIGINS`、Cookie、HSTS、反代头
- 日志配置：控制台 + 可选文件日志
- 数据库配置：支持 RDS 参数（超时、连接复用、sslmode）

### 4.2 后台入口与路由

- 后台入口：`/admin/`
- 后台登录：`/admin/login/`
- Django Admin：`/django-admin/`
- 兼容跳转：
  - `/login/` -> `/admin/login/`
  - `/console/` -> `/admin/`

### 4.3 OSS 媒体存储

- 新增 OSS 存储后端：`stable.services.oss_storage.AliyunOSSStorage`
- 图片本地化、封面上传统一走 `default_storage`
- URL 解析兼容本地与 OSS

### 4.4 部署资产

- 标准模式（RDS）：`docker-compose.prod.yml`
- 低成本模式（本机 PG）：`docker-compose.prod.lowcost.yml`
- Compose 兼容包装脚本：`deploy/docker/compose-wrapper.sh`
- Docker 与启动脚本：
  - `Dockerfile`
  - `deploy/docker/start-web.sh`
  - `deploy/docker/start-worker.sh`
  - `deploy/docker/start-beat.sh`
  - `deploy/docker/wait_for_services.py`
- Nginx：`deploy/nginx/nginx.conf`
- 部署脚本：
  - `deploy.sh`
  - `deploy_lowcost.sh`
  - `deploy/deploy.sh`
  - `deploy/deploy_lowcost.sh`
- 回滚脚本：
  - `deploy/rollback.sh`
  - `deploy/rollback_lowcost.sh`
- 备份恢复脚本：
  - `deploy/backup_db.sh`
  - `deploy/upload_backup_to_oss.py`
  - `deploy/restore_db.sh`

### 4.5 文档资产

- [生产部署指南](E:/Codex/docs/deploy_production.md)
- [阿里云香港手把手指南](E:/Codex/docs/alicloud_hongkong_step_by_step.md)
- [回滚指南](E:/Codex/docs/rollback_guide.md)
- [备份与恢复指南](E:/Codex/docs/backup_recovery.md)
- [生产检查清单](E:/Codex/docs/production_checklist.md)
- [后台使用说明](E:/Codex/docs/backend_usage.md)
- [PRD 归档说明](E:/Codex/docs/PRD/README.md)

### 4.6 OpenSpec / Codex 协作资产

- OpenSpec 项目配置：`openspec/config.yaml`
- OpenSpec 规格与变更目录：`openspec/specs/`、`openspec/changes/`
- Codex OpenSpec skills：`.codex/skills/openspec-*`
- Codex 工程计划审查 skill：`.codex/skills/plan-eng-review`，配套 `tdd`、`workflow-spine` 与 `gate-templates.md` 引用；`2026-06-26` 新工作树 `/Users/mentianlu/.codex/worktrees/openspec-ready-20260626/umanews` 已补齐并验证这些入口
- Codex 领域代理：`application`、`integration`、`operations`
- Codex 只读安全审查代理：`security-scanner`
- 较大功能、跨模块、架构和生产高风险变更采用“探索 -> 提案/规格/设计/任务 -> 实现 -> 验证 -> 归档”流程
- `start-hkjc-data-import-and-global-spikes` 已完成 `/plan-eng-review`、TDD 红灯测试、最小实现、read-only spike、生产部署、验证和归档；生产服务镜像来自 `b0361cf`。2026-06-26 已在生产执行一次 HKJC fixture 样本 commit（`run_id=1960`），写入 `1` 场、`2` 条报名、`2` 条成绩、`2` 匹马和 `4` 条别名；该样本不来自真实网络抓取，也不生成公开比赛页。英法美三地当前均为 `needs_more_spike`。正式规格已同步到 `openspec/specs/global-racing-data-import-readiness/spec.md`；后续如要正式导入英法美或真实 HKJC 网络适配，应另起 change。
- `connect-real-global-racing-databases` 已创建并通过 OpenSpec 严格校验；目标按香港、英国、法国、美国顺序接入真实赛马数据库，每地抓最近 2 个月赛事和涉及马匹详情后停止。当前香港阶段已完成 HKJC 官方 HTML 单场真实 dry-run 和隔离 SQLite commit：`HK20260624HV01` 解析并写入 `1` 场、`12` 条报名、`12` 条成绩、`12` 条英文别名；并已完成 recent-days/date-range 小范围真实链路，`--recent-days 60 --end-date 2026-06-26 --limit-races 1 --limit-horses 1` dry-run 请求 `4` 次官方页面，返回 `completion.is_complete=false`、`meetings_found=28`，隔离 SQLite commit 写入 `1` 场、`12` 条报名、`12` 条成绩、`1` 匹马 profile 和 `12` 条别名，重复执行正式对象计数不增长。HKJC 追加 plan-only 批次预检：过滤 overseas `S*` racecourse 后，最近 60 天本地香港 `HV/ST` 比赛为 `144` 场，可按每批 `20` 场拆为 `8` 批；已通过 `--skip-races 20` 真实 smoke 证明日期范围后续批次可从第 21 场开始，并通过 `--race-ids HK20260624HV02,HK20260613ST04 --limit-horses 1` 真实 smoke 证明可按指定 race_id 精确批次只请求目标比赛和受限马匹详情。英法美已追加 `18` 次只读入口复核：英国 `Sporting Life + BHA` 可行性最高，美国 `Equibase` 入口更具体但 chart/PDF 仍需 fixture spike，法国 `France Galop` 仍未定位稳定结构化查询参数。下一步仍需部署后执行 HKJC 生产最近 2 个月全量 dry-run/commit，香港完成后再按顺序进入英国正式 parser/importer TDD。
- 生产 HKJC 真实网络运行状态：`connect-real-global-racing-databases` 当前实现已部署到生产 `04c0444`，备份 `backups/db/pre-hkjc-real-network-20260626_202442.sql.gz` 通过校验，部署后 check/healthz/小样本 dry-run 通过，生产 plan-only 仍为 `144` 场、`8` 批；第 1 批 full dry-run 曾在马匹 profile 补抓阶段遇到 HKJC `ReadTimeout` / TLS handshake timeout 中断，该次未 commit、未写表，HKJC 锁为空且表计数仍为上次 fixture 样本 `1/2/2/2/4`。已按 TDD 补 transient timeout retry 并重新部署，随后将前 6 个 plan-only 批次拆成 24 个 5 场小批次 dry-run，均 `completion.is_complete=true`，累计覆盖 `120` 场、`1522` 条 entries、`1522` 条 results 和 `1522` 个 horse profile 请求，当前停在生产 commit 前确认点。
- `connect-real-global-racing-databases` 的本轮目标已在 `2026-06-27` 调整为确认四地真实抓取能力可用，并按该口径完成：HKJC 生产真实 dry-run 证据成立，UK / France / US 少量真实 proof 证明 Sporting Life、Geny、Horse Racing Nation 的赛事、赛果和马匹详情入口可访问并可解析；新增 importer、审计命令、batch command 渲染器、fixtures、OpenSpec 规格/归档和 proof 文档已从干净 `origin/main` 基线整理为独立上线包。代码提交 `93b7007` 已部署生产，check/healthz/首页/命令入口/proof-only 审计和导入锁状态均通过；最近 60 天完整大量爬取和生产 `--commit` 保持为后续单独执行窗口。

## 5. 当前验证结果

- `DB_ENGINE=sqlite /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 manage.py check`：通过
- `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 manage.py test stable`：通过，147 项
- `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py test stable.tests.TermResolverTests stable.tests.AutomationFlowTests stable.tests.TranslationWorkflowTests stable.tests.TermCandidateDiscoveryTests --noinput`：通过，49 项
- `openspec validate use-external-horse-alias-for-name-recognition --strict`：通过
- `DB_ENGINE=sqlite /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 manage.py test stable.tests.PublicHomeInfoFeedTests`：通过，10 项
- `openspec validate upgrade-public-home-info-feed --strict`：归档前通过
- `openspec validate --all`：归档前通过；同步正式规格并归档后再次通过
- 公开首页资讯流浏览器验收：桌面首页、移动首页、桌面详情页、移动详情页通过；移动普通卡约 128px 高，无横向溢出，图片加载正常
- 公开首页资讯流生产验收：服务器 HEAD `e834f58`，`http://umafans.run/healthz/` 与 `/` 均返回 `200`，首页引用 `/static/stable/public.2eec24723b45.css`，390px 移动端普通新闻卡约 `128px` 高且首屏头条后可见 3 条普通新闻
- 移动端首页密度 follow-up 生产验收：服务器 HEAD `04e2ee9`，`http://umafans.run/healthz/` 与 `/` 均返回 `200`，首页引用 `/static/stable/public.9aaf4b105424.css`，390px 视口下头条约 `257px` 高，第一张普通新闻卡 `top=388`，首屏可见 4 条普通新闻卡，普通卡仍约 `128px` 高，无横向溢出
- 自动发布门禁优化生产验收：服务器 HEAD `42a4622`，迁移 `stable.0009_automation_publish_gates` 已应用，`AUTO_REWRITE_ENABLED=false`、`AUTO_PUBLISH_CONTENT_SOURCE=base_translation`、`AUTOMATION_WARNING_EMAIL_ENABLED=true` 已生效，`http://umafans.run/healthz/` 与 `/` 均返回 `200`
- 三个运营改造 change 生产验收：服务器 HEAD `7f54f13`，`web / worker / beat` 已重建，`manage.py check` 通过，`http://127.0.0.1/healthz/` 与 `/` 均返回 `200`；运行态确认 netkeiba 新着顺 / 访问量榜 / 注目数榜调度分钟为 `00/16/26`，OpenSpec 归档后 `openspec validate --all` 通过
- 外部马名索引识别链路生产验收：服务器 HEAD `35b0866`，`manage.py check` 通过，`http://127.0.0.1/healthz/`、`http://umafans.run/healthz/` 和 `/` 均返回 `200`；生产只读 smoke test 确认 `ExternalHorseAlias=11521`，`ロブチェン` 可识别为 `external_alias`
- 榜单重点 QQ 推送与公开文章 ID URL 生产验收：服务器 HEAD `00e4bd4`，生产 `.env` 已切换为 `QQ_PUSH_ENABLED=true`、`QQ_PUSH_SCOPE=high_value_only`、`QQ_PUSH_IMPORTANCE_STRATEGY=ranked`；`manage.py check` 通过，`http://umafans.run/healthz/` 与 `/` 均返回 `200`，抽检 `/news/<article_id>/` 返回 `200`，旧 slug URL 返回 `302` 并跳转到 ID URL
- 榜单重点 QQ 推送相关 OpenSpec 归档：`add-qqbot-auto-push`、`elevate-ranked-netkeiba-sources`、`push-ranked-news-to-qq`、`use-article-id-public-urls` 已归档并同步正式规格，归档后 `openspec validate --all` 通过
- QQ Bot 登录态恢复与离线防护本地验证：2026-06-26 排查确认 NapCat 登录态失效会导致 OneBot 无法发送；重新扫码登录后 `/get_status online=true`、测试群消息发送成功，并恢复 `QQ_PUSH_ENABLED=true`。本轮补充自动推送发送前 OneBot 在线预检，离线或状态检查失败时不调用发送接口、不增加 `attempt_count`，完整 `stable` 测试通过 268 项。
- QQ Bot 离线防护生产验收：服务器 HEAD `a2146d6`，部署前 `.env` 备份为 `.env.backup.qqbot-offline-guard-20260626_223731`；部署后 `manage.py check` 通过，本地和公网 `/healthz/` 均返回 `200`，worker 环境确认 `QQ_PUSH_ENABLED=true`、`QQ_PUSH_SCOPE=high_value_only`、`QQ_PUSH_IMPORTANCE_STRATEGY=ranked`，`BotPusher().is_online()` 返回 `(True, '')`，测试群 `1026525240` 发送部署验证消息成功。
- `docker compose -f docker-compose.prod.yml config`：通过
- `docker compose -f docker-compose.prod.lowcost.yml config`：通过

说明：本地 `.env` 若指向不存在的 `postgres@db`，测试建库会失败，这是本地环境问题。

## 6. 当前待办（项目级摘要）

- 观察公开首页资讯流生产运行，重点看首页、详情页、图片、静态资源和移动端首屏密度
- 赛事日历正式填充：`2026-07-06` 已按“官方源优先、本地语言优先、先 CSV/JSONL dry-run 再正式导入”的流程批量写入 2026 目标地区重要赛事。生产当前 `RaceEvent=995`、`RaceEventAlias=3277`；2026 五地区计数为日本 `186`、香港 `20`、美国 `412`、英国 `203`、法国 `174`。已完成基础表：日本 JRA 中央重赏 `140` 场、日本 NAR/交流ダートグレード `46` 场、香港 HKJC 已公开 2026 分级赛 `19` 场、美国 TOBA Grade 1/2/3 `411` 条、英国 BHA Flat Group 1/2/3 `138` 场、英国 BHA Jump 2026 年 1-4 月 Grade 1/2 `64` 场、法国 France Galop Groupe I/II/III `173` 条。详情表已导入日本、香港、美国当前可用批次：JRA 已完赛中央重赏 `74` 场、NAR 已完赛 `20` 场、NAR `2026-07-08` 已公布赛前出走表 `1` 场、HKJC 已公开香港分级赛 `19` 场、美国 TOBA 已完赛 Grade 1/2/3 `195` 场；生产 `RaceEventRunner=3260`、`RaceEventResult=2977`、`RaceEventHistoryWinner=0`。`取消/除外/中止/空白着顺/WV` 保留在出走表状态中，同着用唯一排序位写库并在 `source_refs.official_finish_position` 保留官方名次，前台已热补丁为展示官方名次。美国 Equibase chart 当前仍返回防护页，因此美国赛果暂用 HRN track-day 可见结果顺序；Kentucky Derby / Oaks 等 HRN 未公开结果块的场次只显示出走表。剩余详情缺口：JRA 未来 66 场、NAR 未来 25 场需等官方出走表或赛果发布，英国/法国详情来源解析，以及五地区历届冠军。
- 多地区术语库与外部马名索引：`2026-07-03` 生产只读核对显示，正式术语库和术语候选池仍主要是日文。`2026-07-04` 至 `2026-07-07` 已连续导入术语种子：第一批 fixture 候选、WP Stud 香港/海外来港社区马名、HKJC 当前本地马 A-Z 官方英文马名、HKJC 本地赛果 `2024-01-01` 至 `2026-07-04` 候选、HKJC overseas `2024-01-01` 至 `2026-07-04` 官方 `horse / jockey / race` 候选、WP Stud 赛事/骑师/马场社区候选，以及 WP Stud HorseList 全量马名。当前生产为 `TermEntry=16558`、`TermAlias=19293`；`source_language=en` 已覆盖香港、英国、法国、美国、日本和 other 的马名/赛事/骑师/马场，active 马名国别后缀和赛事年份标记脏数据均为 `0`。外部马名索引仍以日本 `netkeiba` 为主体；英国、法国、美国当前生产 `External*` 表无写入。当前应把多地区识别能力理解为“正式术语库已大幅补齐，尤其 HKJC 官方本地/海外术语可用于英文新闻识别”，仍不等同于英法美外部赛马数据库正式落库。
- 术语种子数据准备：OpenSpec change `prepare-termbase-seed-data` 已完成实现、验证和归档；本地首版已新增 `prepare_termbase_seed_data` 管理命令、`stable.services.termbase_seed` 服务层、HKJC/WP Stud fixture、操作文档和后台术语导入模板更新；内置 fixture smoke 可生成 `seed_candidates.csv`、`seed_conflicts.csv` 与 `summary.json`，候选主表严格兼容现有 `import_terms` 字段，中文目标译名统一简体化。HKJC 专用抽取已从真实页面打通 `selecthorse -> selecthorsebychar -> zh-hk horse detail`，并新增 `--hkjc-letter` 支持按 A-Z 拆批；本地赛果路径已支持日期范围、跳过马匹详情页、双语空壳赛果页进入 `skipped_races`。OpenSpec change `prepare-hkjc-overseas-termbase-seeds` 已完成本地实现、正式规格同步和归档，归档目录为 `openspec/changes/archive/2026-07-05-prepare-hkjc-overseas-termbase-seeds/`；正式规格已包含 `hkjc_overseas` 来源、Race Card 自动发现/精确参数、QIDS 日期范围抽取、官方来源元数据、结构化证据、地区映射和 `racing_region` 导入表头。`2026-07-05` 已用该路径生成并导入 `2024-01-01` 至 `2026-07-04` 海外术语。WP Stud 解析器已扩展到赛事、骑师、马场和 HorseList 马名表；生产导入时遇到既有 HKJC 官方术语或既有日文 alias 占用时，不覆盖官方主译名，不强行合并冲突概念。`2026-07-06/07` 最终返修已验证 WP Stud HorseList 触网解析、HKJC 马名国别后缀清洗、复合年份赛事拆分和 HKJC 日本马日文 alias 补充；正式导入后生产计数为 `TermEntry=16558`、`TermAlias=19293`。
- 观察自动发布质量与自动化日志
- 补充翻译 warning 可视化和术语库补全流程
- 继续评审 OpenSpec change `expand-international-racing-coverage` 的本地实现：多地区新闻源、公开首页地区 tab、`TermEntry + TermAlias` 多语言术语概念模型、群级 QQ 推送配置、HKJC 外部数据导入和全球数据源 spike 已完成本地实现与 review 返修；上线前 review 已补齐快照 metadata 不保存整页 HTML、TDN 缺详情日期时保留列表 API 时间、英文外部马名索引识别、跨语言术语 upsert 主原文保护、术语批量别名匹配、HKJC entries/results 马匹上限统计、英文术语生命周期大小写不敏感、术语启停同步别名状态、术语导入别名冲突保护、TDN/TDN France canonical 去重和术语列表语言筛选翻页保留，尚未部署生产
- 观察外部马名索引识别链路生产效果，重点抽检 `external_horse_not_preserved` warning、候选池 `external_horse_alias` 来源质量和 JRA 活动公告类启发式误报
- 推进 HTTPS / 证书接入
- 做部署稳定化
- 完善监控、备份与回滚流程
- 观察 QQ Bot 测试群灰度；OneBot 已接通并开启 `QQ_PUSH_ENABLED=true`，当前按 `QQ_PUSH_SCOPE=high_value_only` + `QQ_PUSH_IMPORTANCE_STRATEGY=ranked` 只等待自然榜单新闻自动推送。存量公开新闻已完成部分限速补推，剩余历史失败记录暂不继续补推。
- 验证并评审 `operate-multiregion-news-production` 本地实现；部署前必须执行只读审计、`.env` 备份、通用轮询默认关闭检查、测试群地区配置核验和至少一个自然调度窗口观察。

## 6.1 国际赛马资讯扩展规划状态

- OpenSpec change：`expand-international-racing-coverage`
- 当前状态：已完成 proposal、design、tasks、delta specs 和本地实现；尚未部署生产
- 一期新闻源本地接入最终清单：
  - 日本：`Sponichi`
  - 中国香港：`HKJC Racing News`、`SCMP Racing`
  - 英国：`Sporting Life Racing`、`Sky Sports Racing`，官方补充 `BHA`
  - 法国：仅接英文来源 `France Galop English News`、`TDN France keyword`，不接法语新闻正文
  - 美国：`TDN`、`Horse Racing Nation`
- 一期数据库实现：新增 HKJC 受控导入命令 `import_hkjc_external_data`，默认 dry-run，支持 payload 小样本提交、统计查询和马名索引查询；commit 模式必须提供 `--payload-file`，使用单来源互斥锁防止并发写入，并在超过 `max_races / max_horses` 时直接失败；`max_horses` 会合并统计顶层 `horses`、赛事 `entries` 和 `results` 中可识别的唯一马匹；`Equibase`、英国 `Sporting Life + BHA`、法国 `France Galop` 已形成 spike 文档 `docs/global_racing_data_source_spikes.md`
- 排序型入口：本轮确认 `Sponichi 新闻ランキング`、`Sky Sports Racing Top Stories`、`Horse Racing Nation Trending` 可公开抓取，已作为独立排序/榜单源加入并保留原站 rank；review 返修后，同源普通 list 不会覆盖已入库的排序/榜单主来源，QQ `ranked` 重点策略也会识别这些国际榜单稿；`At The Races`、`Paulick Report`、`BloodHorse` 因 403、反爬或空样本风险保留为候选，不进入第一版默认清单
- 前台实现：公开首页增加 `综合 / 日本 / 中国香港 / 英国 / 法国 / 美国` 地区 tab，综合流第一期使用已发布文章倒序；地区页翻页保留 `region` 查询参数；公开详情继续使用 `/news/<NewsArticle.id>/` 全局自增数字 ID，国际来源去重键与公开 ID 分离
- 后台实现：术语库支持 `TermEntry` 正式术语概念 + `TermAlias` 多语言原文别名，先保留 `source_ja / aliases_ja` 现有物理字段兼容；翻译、改写、自动标签和自动化评分的术语命中按文章原文语言选择别名，并批量加载参与匹配术语的别名，避免每条术语各查一次；英文/繁中外部马名索引按同语言参与识别，先按文章候选片段收窄查询，并使用原文真实写法做保护和校验；英文正式术语按大小写不敏感方式命中并保留原文真实 matched_text；最终 review 返修后，自动化 P0 马匹命中、发布校验核心/背景术语判定和“新增术语后应用当前稿”也统一复用语言感知匹配，避免英文大小写漏判或漏替换；本轮补丁进一步将同语言术语查重、别名去重、导入 upsert、候选合并和术语 API 保存统一为大小写不敏感，并让后台/API 启停术语同步所有语言 `TermAlias` 状态；同语言大小写变体导入 upsert 会更新正式主原文并同步别名表，术语导入 upsert 命中跨语言别名时仍只维护该语言别名、不覆盖正式概念主原文；本次返修又补齐别名冲突保护，只有主原文命中时才允许 upsert，别名撞到其它术语会报错；AI 改写 prompt 的术语表使用文章实际命中的 `matched_text`，避免英文稿看到日文概念主名而漏用标准译名；自动化评分补充英文/繁中赛马关键词；QQ 推送从全局范围配置扩展为群级地区 / 范围 / 重点策略配置，旧群空地区或非法地区配置按日本兼容；内置来源同步保留人工 `enabled` 状态，支持后续按来源灰度启用
- 测试用例：`openspec/changes/expand-international-racing-coverage/test_cases.md` 已按 OpenSpec `proposal/design/spec` 建立完整验收矩阵，覆盖地区/语言、国际新闻源、公开首页、术语多语言、QQ 群级推送、HKJC 导入、欧美数据源 spike、迁移和非目标边界
- 真实新闻源探测：`probe_international_news_sources` dry-run 默认探测第一版最终矩阵；`Sponichi latest/access`、`HKJC Racing News`、`SCMP Racing`、`Sporting Life Racing`、`Sky Sports Racing access/latest`、`BHA official`、`France Galop English News official`、`TDN France keyword`、`TDN`、`Horse Racing Nation access/latest` 均已成功解析两篇真实样本
- 验证：新增测试用例矩阵和最终源清单返修后，本地 `manage.py check`、完整 `stable` 测试、`makemigrations --check --dry-run`、`openspec validate expand-international-racing-coverage --strict`、`openspec validate --all` 和 `git diff --check` 均已通过；2026-06-26 最终 review 返修后完整 `stable` 测试通过 231 项，已覆盖国际榜单来源提升后触发 QQ 自动推送编排、英文外部马名索引识别与真实写法保护、翻译保护和发布校验使用真实 matched_text、英文正式术语大小写不敏感匹配与当前稿替换、英文 P0 马匹评分、跨语言术语 upsert 主原文保护、术语别名批量匹配、HKJC entries/results 马匹上限统计、旧 QQ 群空/非法地区日本兼容、地区 tab 翻页保留过滤和英文赛马关键词评分；本轮术语生命周期补丁后完整 `stable` 测试通过 236 项，新增覆盖英文重复术语大小写不敏感拒绝、API 创建/更新同步别名、术语启停同步别名状态、候选合并大小写去重、同语言大小写变体导入 upsert 更新主原文，以及 AI 改写 prompt 使用英文实际命中别名；本次上线前返修后完整 `stable` 测试通过 241 项，新增覆盖术语导入 upsert 原文别名冲突预览/提交双重拒绝、`TDN France keyword` canonical 去重并保留法国地区信号、以及术语列表分页保留原文语言筛选

## 7. 当前上线进展（摘要）

- 2026-07-01 本地新增 `increase-multiregion-news-volume` 实现：以 `ProductionWindow` 为抓取、发布和 QQ 推送的统一窗口账本；日常 15 分钟、重要赛事 5 分钟；每地区发布窗口最多 5 篇、保底 1 篇且不绕硬门禁；QQ 每地区每窗口最多 3 篇并保留群/全站小时配额。2026-07-02 review 返修后，抓取和 QQ 恢复补跑只执行最近缺失窗口，历史窗口记为合并跳过；可重试 QQ delivery 重新发送前必须占用配额；抓取窗口由真实抓取完成后回写成功/失败，HTTP 403/429 进入来源错误分类，QQ 窗口会在创建 delivery 前检查 OneBot 在线状态。新窗口生产开关默认关闭，需审计通过后再在生产显式启用。
- 2026-07-02 `increase-multiregion-news-volume` 已上线生产：生产运行 `9e97e8c`，迁移 `0017/0018` 已应用，新窗口抓取/发布/QQ 开关均已开启，16 个启用新闻源已 `production_approved=true`。生产 smoke 显示 20:15 抓取窗口 14 成功、1 个 Sponichi 上游 502 失败；20:15 发布窗口香港 1 篇、美国 3 篇，20:30 美国继续发布 1 篇，其余地区均有 `no_ready_candidates` 原因；20:15 QQ 美国发送 2 条，20:30 美国为 `already_sent`，其余地区为 `no_eligible_articles`。公开首页和地区页浏览器验收通过，ops 摘要通知已发送到测试群 `1026525240`。因当前为后半夜新闻低峰，用户确认实际 4 个自然窗口验证延期到次日继续。
- 2026-07-02 白天复核最近 6 小时自然窗口：生产已运行 `a122130`，公网 `/healthz/`、首页和抽检文章页均返回 `200`，Celery 队列为空。发布 / QQ 各地区均有 `24` 个 15 分钟日常窗口；抓取窗口 `260` 个成功、`109` 个因恢复补跑合并跳过。新窗口实际发布美国 `1` 篇、日本 `9` 篇，所有非零窗口均未超过每地区 `5` 篇；QQ 实际发送美国 `3` 条、日本 `3` 条，未超过每地区每窗口 `3` 条；其余 0 发布 / 0 推送窗口均有 `no_ready_candidates`、`no_eligible_articles` 或 `already_sent` 原因。16 个生产批准来源最新抓取均为 `success`。
- 2026-07-02 11:07 追加按地区拆因：最新 4 个发布窗口五地区均 0 发布；日本有候选但全部被 `hard_gate_blocked`（翻译失败、人工审核要求、核心术语缺失），香港 / 英国 / 法国 / 美国没有进入发布候选的文章。最近 3 小时非日本来源抓取成功但新增为 0、只命中重复旧稿；TDN France / TDN 美国早间短暂超时后已恢复，当前不是 0 发布主因。
- 2026-07-02 15:10 复核最近 2 小时窗口：五地区发布 / QQ 窗口均按 15 分钟节奏成功运行；网页发布 0 篇、QQ delivery 0 条，原因分别为 `no_ready_candidates` / `no_eligible_articles`。最近 2 小时抓取新入库 8 篇（日本 5、香港 1、英国 2），但均处于翻译失败或人工审核要求状态，未达到自动发布条件；TDN France 与 TDN 美国 15:02 各出现一次 read timeout，failure streak 为 1，属于上游短时超时。
- 2026-07-03 00:13 今日窗口复核：今日目前只有 `00:00` 一个自然窗口，抓取 / 发布 / QQ 均正常生成并成功；新入库 1 篇美国 TDN 新闻，发布 0 篇、QQ 0 条，原因分别为 `no_ready_candidates` 和 `already_sent / no_eligible_articles`；16 个生产批准来源最新状态均为 `success`。
- 2026-07-03 复核 2026-07-02 全日窗口：昨日实际覆盖 `04:00-23:45` 共 80 个 15 分钟窗口起点；发布窗口五地区各 80 个且全部成功，窗口发布日本 37、香港 1、美国 10，英国/法国 0；QQ 窗口五地区各 80 个且全部成功，窗口派发日本 3、美国 5，所有昨日 QQPushDelivery 记录均为 sent；抓取窗口无 failed，窗口 payload 新增日本 79、香港 5、英国 11、法国 1、美国 28，日本榜单唤醒 7 次。
- 2026-07-03 地区归属错配审计：现有 `NewsArticle.racing_region` 与新闻源地区完全一致，6598 篇中 0 篇偏离“按新闻源地区”。严格实体地区口径只覆盖 462 篇且均为日本文章，按用户提出的第一种/第二种逻辑未发现结构化错配；但生产实体地区数据不足，审计当时 `TermEntry.racing_region` 全为空，英法美外部马名/赛事正式缓存未落库，因此该 0 只能视为下限。2026-07-04 仅补写了首批 `10` 条术语地区，仍不足以支撑可信实体地区识别。关键词粗扫有 1213 篇疑似跨地区提及，需后续做实体地区识别改造后才能给出可信错配数。
- 2026-07-02 OpenSpec change `revive-ranked-news-for-publish` 已完成本地实现：未发布文章从普通来源升级为榜单来源时会写入 `ranked_revived_at` 和 `decision_reason.ranked_revival`；低分 ignored、价值不足人工状态、翻译失败和待翻译文章可被唤醒，翻译未完成先重试，已翻译文章重新进入自动化评分；人工拒绝、撤回、重复 blocker 和硬门禁不绕过。发布窗口候选回看同时支持 `first_seen_at` 与 `ranked_revived_at`，候选决策 payload 会记录榜单唤醒来源和时间；已发布文章仍只沿用现有 QQ 补推，不重复发布。
- 2026-07-02 `revive-ranked-news-for-publish` 验证与上线：目标榜单唤醒测试通过，完整 `stable` 测试通过 418 项；`manage.py check`、`makemigrations --check --dry-run`、OpenSpec 严格校验、全量 OpenSpec 校验和 `git diff --check` 均通过。OpenSpec change 已归档并部署生产 `a774672`，迁移 `0019_newsarticle_ranked_revived_at` 已应用；生产 `/healthz/`、首页、后台登录入口、容器状态、Celery 队列和日志 smoke 均通过。
- 目标服务器：阿里云香港 ECS，采用低成本部署方案（本机 PostgreSQL + OSS）
- 仓库线上基线：`main` 分支已包含生产化改造与低成本部署脚本
- 已发现并修复一项部署兼容性风险：
  - 部分 Ubuntu 镜像仅提供 `docker-compose`
  - 项目部署/回滚脚本现已兼容 `docker compose` 与 `docker-compose`
  - 兼容包装脚本已调整为优先使用 `docker-compose`，避免旧环境误判
- 已发现并修复一项镜像拉取风险：
  - `worker / beat` 使用本地构建镜像 `umanewsbot:prod`
  - 部署脚本已改为仅拉取外部依赖镜像，避免误向公共仓库拉取业务镜像失败
- 已发现并修复一项健康检查风险：
  - 容器内 `curl http://127.0.0.1:8000/healthz/` 会命中 Django `DisallowedHost`
  - 应用现已自动允许回环地址进入 `ALLOWED_HOSTS`，兼容 Docker 健康检查
- 已识别一项远端编排兼容性风险：
  - 服务器自带 `docker-compose 1.29.2` 在重建带卷容器时会触发 `KeyError: 'ContainerConfig'`
  - 部署策略调整为优先使用 `docker compose` v2 插件，必要时在 ECS 上手动安装官方 CLI plugin
- 已开始域名接入准备：
  - 目标域名为 `umafans.run` 与 `www.umafans.run`
  - 当前阶段正式域名 HTTP 接入修复已完成
  - 下一阶段进入 HTTPS / 证书接入与部署稳定化
- 已拿到生产所需核心密钥：
  - `SILICONFLOW_API_KEY`
  - `OSS_ACCESS_KEY_ID`
  - `OSS_ACCESS_KEY_SECRET`
  - `OSS_BUCKET_NAME`
- 当前下一步：
  - 观察自动化发布质量，重点看 warning 邮件、重复内容阻断和候选池门禁展示
  - 生产灰度前先评审外部赛马数据导入配置，执行 dry-run 和单月小批量验证
  - 补充翻译 warning 可视化和术语库补全流程
  - 推进 HTTPS / 证书接入
  - 做部署稳定化
  - 完善监控、备份与回滚流程

## 8. 协作约定

1. 每次开始项目前优先阅读 [docs/current_state.md](E:/Codex/docs/current_state.md) 与 [AGENTS.md](E:/Codex/AGENTS.md)，本文档作为项目级摘要辅助阅读。  
2. 每次更新完成后同步回写本文件与 [docs/current_state.md](E:/Codex/docs/current_state.md)。  
3. 每次收到新 PRD 归档到 `E:/Codex/docs/PRD/`。  
4. 每次阶段性收工时同步更新 [docs/work_log.md](E:/Codex/docs/work_log.md)。

## 9. 专有术语候选发现状态

- 已完成四类实体候选发现：马名、比赛名、骑手名、马主名。
- 已完成正式术语去重、已有候选聚合、按文章证据留存和跨类型冲突提示。
- 已完成工作人员候选审核后台与单篇重新发现入口。
- 已完成接受、修改后接受、合并、拒绝、忽略和保守批量操作。
- `2026-06-07` 已部署生产并应用迁移 `0006`（服务器到 `e2e3e07`），生产默认关闭，待单篇抽检后通过 `TERM_DISCOVERY_ENABLED` 灰度启用。
- 当前验证：Django 检查通过，`stable` 69 项测试通过，两种生产 Compose 配置检查通过，并完成本地隔离环境浏览器功能验收。

## 10. 外部赛马数据导入状态

- 已实现 `add-netkeiba-horse-data-import` OpenSpec change 的首版代码。
- 新增外部比赛、出走、赛果、赔率、马匹、履历、马名索引、导入运行、错误记录和单来源锁模型。
- 新增 `import_external_horse_data` 管理命令和 `import_external_horse_data_task` Celery 任务。
- 生产默认关闭：`EXTERNAL_HORSE_DATA_IMPORT_ENABLED=false`、`EXTERNAL_HORSE_DATA_ALLOW_NETWORK=false`。
- 当前能力只维护本地外部赛马数据缓存，不改变新闻抓取、翻译、改写、自动发布或公开前台。
- 当前验证：Django check 通过，`stable` 147 项测试通过。
- 生产首轮小批量已完成：`run_id=1`，`2026-05` 前 10 场，成功 10、失败 0，写入 143 个唯一马 ID/马名索引。
- `2026-06-24` 已补充按月续跑跳过已落库 race 的逻辑，后续可继续对 `2026-05` 做小批量下一批导入。
- 生产第二批续跑已完成：`run_id=2`，累计 20 场比赛、274 个唯一马 ID/马名索引，失败 0。
- 生产第三批续跑已完成：`run_id=3`，累计 50 场比赛、695 个唯一马 ID/马名索引，失败 0。
- 生产长循环导入在 `run_id=9` 以退出码 `137` 中断；已停止继续导入、释放锁并标记 partial。当前累计 182 场比赛、2401 个唯一马 ID/马名索引，服务健康。
- 外部马名索引已接入生产识别链路：翻译阶段保护外部已知但无中文译名的马名，发布校验输出独立 `external_horse_not_preserved` warning，术语候选发现会把新闻中出现且缺少正式中文译名的外部马名以 `external_horse_alias` 来源送入候选池；同名普通词需要强马名上下文才会被识别为马名；review 返修后，保护名单 `limit` 不再被已有中文译名的正式马名占用。OpenSpec change `use-external-horse-alias-for-name-recognition` 已归档到 `openspec/changes/archive/2026-06-25-use-external-horse-alias-for-name-recognition/`，正式规格已同步，并已通过 PR #6 部署到生产 `35b0866`。
- 长文样本抽检显示：netkeiba 长文可有效命中外部马名索引，但 JRA 活动公告类长文仍会通过启发式误报普通片假名词，后续需要继续补普通词过滤或收紧启发式马名规则。
