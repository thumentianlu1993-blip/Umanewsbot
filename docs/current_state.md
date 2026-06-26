# 当前状态

## 当前结论

项目当前已经完成正式域名 HTTP 接入修复，`umafans.run` 与 `www.umafans.run` 已可访问。  
“自动化内容运营 + AI 编辑改写 MVP”已完成代码侧与生产侧上线，当前处于上线后观察与质量抽检阶段。

仓库已于 `2026-06-06` 加入 OpenSpec + Codex 协作支持，用于在较大功能、跨模块改动、架构调整和生产高风险变更前先对齐规格，再进入实现。

OpenSpec change `add-term-candidate-discovery` 已完成实现、自动化测试、本地隔离环境浏览器验收，并归档为 `2026-06-06-add-term-candidate-discovery`；正式能力规格已同步到 `openspec/specs/term-candidate-discovery/spec.md`。

`2026-06-07` 已将术语候选发现部署到生产：服务器从 `7123e4e` 拉到 `e2e3e07`，应用迁移 `0006` 新建候选与证据表，`.env` 补入术语发现开关并保持 `TERM_DISCOVERY_ENABLED=false`（灰度，先关后开）。本次部署同时核实线上 `AUTOMATION_ENABLED=true`、`REWRITE_PROVIDER=siliconflow` 仍在生效。

仓库已明确长期语言约定：Codex 新增或维护的协作文档、OpenSpec 产物与代理说明默认使用中文；仅保留必要的代码标识符、命令和工具机器语法。

`2026-06-19` 已创建公开首页资讯流升级主 OpenSpec change：`upgrade-public-home-info-feed`。该 change 作为后续前台 Web + 移动 H5 首页子任务的指导规范，目标是把当前 MVP 公开首页从“大说明 + 大卡片网格”升级为成熟资讯流：移动端轻头条 + 高密度新闻列表，桌面端门户式主内容 + 侧栏。`2026-06-21` 已完成 plan-eng-review 与 `/opsx:apply` 本地实现；实施过程按严格 TDD 执行发布过滤、头条选择、普通流去重、热门代理、公开静态资源和详情页结构测试，并已通过本地 Django 测试、OpenSpec 校验和桌面/移动浏览器验收。`2026-06-22` 已将 delta spec 同步为正式规格 `openspec/specs/public-home-info-feed/spec.md`，并归档为 `openspec/changes/archive/2026-06-22-upgrade-public-home-info-feed/`；同日 PR #1 已合并并部署到生产，服务器运行 `e834f58`，公开首页已切换到 `stable/public.css` 和新资讯流模板。`2026-06-23` PR #2 已合并并部署生产，服务器运行 `04e2ee9`，移动 H5 首屏密度 follow-up 已上线。

`2026-06-24` 已完成自动发布门禁优化 OpenSpec change：`refine-automation-publish-gates` 的实现、PR 合并与生产上线。代码已将自动发布门禁拆为 `blocker / warning / info`：`blocker` 阻断自动发布，`warning` 初期不阻断但记录并对高价值文章邮件告警，`info` 仅用于诊断；同时支持基准翻译稿自动发布、高价值来源评分放行、非马名普通词过滤、关键术语分层校验和重复内容拦截。生产服务器当前运行 PR #4 squash merge 后的提交 `42a4622`，迁移 `stable.0009_automation_publish_gates` 已应用。

`2026-06-25` 已将本轮三个运营改造 change 合并到 `main` 并部署生产：抓取新鲜度与来源健康、后台原文选区快速加入术语库、新增术语后一次性应用到当前稿。服务器 `/opt/umanewsbot` 已从 `268100d` 更新到 `7f54f13`，`web / worker / beat` 已重建，`manage.py check`、`/healthz/` 和首页 HTTP 验证通过。相关 OpenSpec change 已归档并同步正式规格；其中抓取返修的 `fix-crawl-health-running-and-schedule-stagger` 是 change1 的后续规格，随 change1 一并归档。

`2026-06-25` 已将榜单重点新闻 QQ 推送与公开文章 ID URL 改造通过 PR #8 合并并部署生产。服务器 `/opt/umanewsbot` 已更新到 `00e4bd4`，部署前 `.env` 备份为 `.env.backup.qq-ranked-idurl-20260625_191826`；生产 `.env` 已切换为 `QQ_PUSH_ENABLED=true`、`QQ_PUSH_SCOPE=high_value_only`、`QQ_PUSH_IMPORTANCE_STRATEGY=ranked`。`web / worker / beat` 已重建，`manage.py check`、`http://umafans.run/healthz/`、`http://umafans.run/`、`/news/<article_id>/` 公开详情和旧 slug 到 ID URL 的 `302` 跳转均已验证通过。本次不补推历史公开新闻，后续只等待自然榜单新闻触发测试群推送。

`2026-06-26` 已将国际赛马资讯扩展 OpenSpec change：`expand-international-racing-coverage` 合并到 `main` 并部署生产，服务器 `/opt/umanewsbot` 已从 `2f0c35c` 更新到 `5865e58`，部署前 `.env` 备份为 `.env.backup.international-coverage-20260626_103923`。本次部署应用迁移 `stable.0011`、`0012`、`0013`，`web / worker / beat` 已重建，`manage.py check`、`http://127.0.0.1/healthz/` 和首页 HTTP 验证通过。部署前发现生产 netkeiba 外部马名导入脚本仍在连续运行，已等待当前批次完成并释放 `ExternalDataImportLock` 后再部署；外层脚本 `/opt/umanewsbot/imports/run_horse_import_202504_to_202406_20260626_083946.sh` 已停止，最近两批 `1958 / 1959` 均停在 `paused`，避免部署与导入写库重叠。国际来源已同步并灰度启用第一版清单：`Sponichi latest/access`、`HKJC Racing News`、`SCMP Racing`、`Sporting Life Racing`、`Sky Sports Racing latest/access`、`France Galop English News`、`TDN France keyword`、`TDN`、`Horse Racing Nation latest/access`；生产探测中 `BHA official` 返回 `403`，已暂时停用，`At The Races`、`Paulick Report` 和 `BloodHorse` 仍保留为候选但不启用。测试 QQ 群 `1026525240` 已配置允许 `japan / hong_kong / united_kingdom / france / united_states` 五个地区。首轮手动触发 12 个新增来源抓取任务后，`Sponichi latest` 已完成并入库 `13` 篇新稿、`7` 篇重复稿，`Sponichi access` 与 `HKJC Racing News` 已开始执行，其他国际来源仍在 worker 队列中等待；后续重点观察 `CrawlJob`、翻译结果、自动发布门禁和 QQ 群推送。

`2026-06-26` 已创建新的本地 Codex 工作树 `/Users/mentianlu/.codex/worktrees/openspec-ready-20260626/umanews`，基线为 `origin/main` 的 `4d09d25`。该工作树已带入 `.codex/skills/openspec-*`、`.codex/skills/plan-eng-review`、`.codex/skills/tdd`、`.codex/skills/workflow-spine` 和 `.agents/skills` 镜像，并补齐 `gate-templates.md` 引用副本；已通过 `openspec list`、`openspec validate --all`、`openspec validate expand-international-racing-coverage --strict`、`openspec validate add-netkeiba-horse-data-import --strict`、`openspec status --change expand-international-racing-coverage --json` 和 skill 文件一致性检查。该记录仅描述本地协作工作树准备状态，不代表新的产品或生产部署变更。

`2026-06-26` 已新增并完成计划审查 OpenSpec change `start-hkjc-data-import-and-global-spikes`，用于启动香港 HKJC 外部赛马数据受控导入，并为英国 `Sporting Life + BHA`、美国 `Equibase`、法国 `France Galop` 产出结构化数据库 spike。该 change 明确不续跑日本 netkeiba 外部数据导入，日本导入由其他线程继续；本轮也不实现前台比赛页、赛果页或马匹页。已创建 `proposal.md`、`design.md`、`specs/global-racing-data-import-readiness/spec.md` 和 `tasks.md`，并通过 `/plan-eng-review`；审查后补齐 HKJC 生产 commit 前的隔离库验证、数据库备份、用户显式确认、`HKJC_IMPORT_*` 环境配置入口，以及英法美 spike 前后正式表计数保持不变的验收要求。当前 `.openspec.yaml` 为 `phase: reviewed`，已通过 `openspec validate start-hkjc-data-import-and-global-spikes --strict`、`openspec validate --all` 和 `git diff --check`。随后按 TDD 红灯阶段新增 `openspec/changes/start-hkjc-data-import-and-global-spikes/test_cases.md` 和自动化测试；本轮实现已将 4 个红灯转绿：补齐 `HKJC_IMPORT_*` settings 和 `.env.example`，新增 HKJC `--allow-network` dry-run 请求边界输出，新增英法美只读 spike runner 和正式表 before/after 计数检查。HKJC 最小样本 fixture 已保存到 `server/stable/fixtures/hkjc/`，本地隔离 SQLite `/tmp/umanews-hkjc-apply.sqlite3` 已完成赛日、单场、单马 dry-run/commit，结果写入 `docs/hkjc_data_import_samples.md`；隔离库最终统计为 3 个 import run、1 场比赛、2 个 entries、2 条 results、2 匹马、4 条别名。英法美 read-only spike 已执行 6 次公开页面 GET，请求证据、字段覆盖矩阵和准入判断已写入 `docs/global_racing_data_source_spikes.md`；三地当前均为 `needs_more_spike`，且正式表 before/after 计数保持不变。验证通过：`manage.py check`、HKJC/spike 目标测试 12 项、完整 `stable` 测试 246 项。

## 已完成内容

- 域名购买与解析
- 正式域名 `umafans.run` / `www.umafans.run` 接入
- 本轮线上问题已修复，正式域名已可访问
- 公网服务器上 `Django + PostgreSQL + Celery + Redis + Docker Compose + Nginx` 主链路已运行
- 基础抓取、翻译、后台、前台链路已具备可继续迭代的基础
- 自动化运营 MVP 代码侧已完成：
  - 翻译成功后可进入自动评分分流
  - 支持 `auto / manual / ignored` 三类分流
  - 支持基准翻译稿与 AI 改写稿双层保存
  - 支持一致性校验、批量自动发布、自动化日志与通知日志
  - 后台候选池、详情页、编辑台、日志页已展示自动化状态与决策留痕
  - 前台展示优先级已调整为人工稿优先，其次改写稿，最后基准翻译稿
- OpenSpec + Codex 工作流已完成仓库级配置：
  - `openspec/config.yaml` 记录真实项目上下文、验证命令和任务域路由
  - `.codex/skills/openspec-*` 提供提案、实现、同步与归档技能
  - `.codex/skills/plan-eng-review` 提供实现前工程计划审查入口；`tdd` 与 `workflow-spine` 作为其配套审查约束与流程参考
  - `.codex/agents/` 提供 `application / integration / operations` 领域代理与只读安全审查代理
  - `AGENTS.md` 已补充规格驱动开发与子代理使用约定
- 专有术语候选发现与待标注池已完成：
  - 支持马名、比赛名、骑手名和马主名发现
  - 支持候选去重、证据聚合、工作人员审核和安全写入正式术语
  - 已完成 69 项测试与本地浏览器功能验收
  - 生产默认关闭，等待灰度启用

## 当前进行中的 OpenSpec change

- `start-hkjc-data-import-and-global-spikes`：准备启动 HKJC 赛日/单场/单马样本导入闭环，并产出英法美数据库 spike。当前已完成提案、设计、规格、任务、`/plan-eng-review`、TDD 红灯测试和第一批最小实现；尚未执行真实 HKJC 网络站点探测、生产 commit 或英法美真实网络 spike。

## 本轮问题简述

本轮线上问题并不是单一故障，而是多层运行态与仓库预期不一致叠加导致：

- 早期曾出现 DNS 解析未生效或本地查询返回 `NXDOMAIN`
- 服务器曾运行旧版 `nginx` 配置，仍保留 `80 -> 443` 跳转逻辑
- 服务器 `.env` 曾保留旧版 IP + HTTPS 强制配置
- 服务器运行中的 commit 一度与仓库当前预期不一致
- 最终通过对齐服务器代码版本、运行态配置、域名配置，完成正式域名 HTTP 接入修复

## 当前线上状态

- 线上域名已通
- 正式域名 `umafans.run` / `www.umafans.run` 可访问
- 自动化运营 MVP 已上线
- 公开首页资讯流升级已上线生产：`/` 使用公开站点专用 `public.css`、头条、普通新闻流和原站热度模块；移动 H5 已展示头条 + 高密度左文右图列表；移动端首屏密度 follow-up 已上线，390px 视口首屏可见 4 条普通新闻卡
- 自动化能力通过 `.env` 中 `AUTOMATION_ENABLED` 控制，当前已进入灰度运行与质量观察阶段
- 已核实线上 `AUTOMATION_ENABLED=true`、`AUTO_REWRITE_ENABLED=false`、`AUTO_PUBLISH_CONTENT_SOURCE=base_translation`、`AUTOMATION_WARNING_EMAIL_ENABLED=true`，当前按“基准翻译稿自动发布 + 高价值 warning 邮件告警”灰度运行
- 术语候选发现代码已部署到生产（`e2e3e07`，迁移 `0006` 已应用），`TERM_DISCOVERY_ENABLED=false` 默认关闭，等待单篇抽检后灰度开启
- `2026-06-24` 已完成 QQ Bot / OneBot 生产运行态配置：独立 NapCat 容器 `umanewsbot-onebot-1` 已启动，OneBot HTTP 仅绑定服务器 `127.0.0.1:3000` 并通过 Docker 网络别名 `onebot` 给应用访问，测试群 `1026525240` 已写入 `PushTarget`，OneBot 直连与 Django `BotPusher` 均已成功发送测试消息。
- `2026-06-25` 生产服务器运行 `7f54f13`：netkeiba 新着顺 / 访问量榜 / 注目数榜调度已加载为每小时 `00/16/26` 分，后台已具备来源健康摘要；候选详情页和文章编辑台已具备原文选区快速加入术语库，以及新增术语后 15 秒一次性浮层“应用到当前稿”。

## 下一步优先级

1. 继续观察公开首页资讯流生产运行，重点确认 `/`、`/news/<article_id>/`、旧非纯数字 `/news/<slug>/` 跳转、图片、`public.css`、移动 H5 首屏密度和自动发布内容长期表现
2. 生产迁移已于 `2026-06-07` 完成；下一步在生产做单篇手动重新发现并抽检术语候选质量，确认后灰度启用 `TERM_DISCOVERY_ENABLED`
3. 观察自动化发布质量与 `AutomationLog`
4. 补充翻译 warning 可视化和术语库补全流程
5. 继续观察 QQ Bot 测试群灰度推送，必要时通过 `QQ_PUSH_ENABLED=false` 暂停自动发送
6. 继续观察 netkeiba `00/16/26` 分错峰抓取在连续小时内生成 `CrawlJob`，并抽检后台来源健康摘要
7. 对 `expand-international-racing-coverage` 做一次上线前整体 review；后续进入 PR / 部署前，需要重点确认迁移窗口、国际新闻源灰度启用顺序、HKJC payload 小样本和生产外部导入锁状态
8. HTTPS / 证书接入
9. 部署稳定化与监控 / 备份 / 回滚完善
10. 继续低批量观察 `refine-automation-publish-gates` 上线后的 warning 邮件、重复内容阻断、候选池门禁展示和自动发布结果

## 2026-06-25 榜单重点新闻 QQ 推送规划

- 已形成协调总纲：`docs/ranked_news_push_plan.md`。该文档只作为本轮计划说明，不作为 OpenSpec 长期能力规格。
- 本轮拆为三个 OpenSpec 子 change：`elevate-ranked-netkeiba-sources`、`push-ranked-news-to-qq`、`use-article-id-public-urls`。
- 推送策略方向：`QQ_PUSH_SCOPE` 继续表示“全推 / 重点推”，重点推送的判定方式由后续配置承载；本期统一实现 `ranked` 榜单策略，即只推 `netkeiba:access` 与 `netkeiba:attention` 新闻。
- QQ 推送 blocker 判断必须复用现有 `NewsArticle.gate_blockers` / `gate_issues.severity=blocker` 结构化门禁结果，不在 QQ 服务里重新实现一套发布门禁。
- 归档状态：`add-qqbot-auto-push` 已先归档为正式 `qqbot-auto-push` 规格，随后本轮三个子 change 已归档到 `openspec/changes/archive/2026-06-25-*` 并同步正式规格。后续仍建议维护者定期清理其他已完成的 active change。
- `elevate-ranked-netkeiba-sources` 已完成并部署生产：`upsert_article_from_draft()` 会将同一 netkeiba 文章从 `latest` 提升为首次命中的 `access` 或 `attention`，二者之间不互相覆盖，`latest` 也不会覆盖榜单来源；每次命中仍创建 `NewsSnapshot`。入库结果新增 `source_elevated` 稳定信号，且仍兼容旧的 `article, created = ...` 解包方式。
- `push-ranked-news-to-qq` 已完成并部署生产：新增 `QQ_PUSH_IMPORTANCE_STRATEGY=ranked`，`high_value_only` 下只推 `netkeiba:access` / `netkeiba:attention` 且无 blocker 的公开文章；已公开文章被榜单来源提升时会触发 QQ 自动推送编排，并继续依靠 `QQPushDelivery(article, target)` 唯一约束去重。QQ delivery 真正发送前也会复检推送资格，若文章后来出现 blocker 或不再符合范围，会标记为 `skipped/not_eligible`，不会继续发群消息。
- `use-article-id-public-urls` 已完成并部署生产：`NewsArticle.public_path` 改为 `/news/<article_id>/`，公开详情页可通过文章 ID 访问，非纯数字旧 slug URL 会跳转到 ID URL；首页、热门列表、后台前台查看入口和 QQ 自动推送消息均继续通过 `article.public_path` 使用 ID URL。
- 本地已通过完整 `stable` 测试、三个子 change 的严格校验、`openspec validate --all` 和 `git diff --check`；生产已通过容器重建、Django check、外部健康检查、首页检查、ID URL 与旧 slug 跳转 smoke test。

## 当前已知风险与待确认项

- 公开首页资讯流升级已部署生产；后续仍需观察真实访问、图片加载和自动发布内容在首页的长期表现
- 当前正式域名阶段仍以 HTTP 为主，HTTPS 证书尚未接入完成
- 需要把 HTTP 阶段的临时安全配置，在 HTTPS 切换时重新收紧
- 需要继续确认抓取调度、翻译调度、发布链路在正式域名环境下的长期稳定性
- 自动化发布涉及内容安全，生产首轮建议低频、低批量、保守开关启用
- AI 改写真实效果依赖模型配置与术语库质量，需继续通过后台人工抽检
- 邮件通知首版已实现；短信 / 微信通知当前只保留日志与配置位；QQ / OneBot 真实发送网关已在生产配置并通过测试消息，自动推送代码已部署并进入测试群灰度
- 需要补足更标准的部署基线、回滚与备份演练
- QQ Bot 自动推送已在生产开启测试群灰度；如出现 QQ 客户端发送异常，优先通过 `QQ_PUSH_ENABLED=false` 停止自动推送并保留 OneBot 网关排查。

## 2026-06-23 QQ 群自动推送 OpenSpec change

### 当前实现

- 新增 OpenSpec change：`add-qqbot-auto-push`。
- 新增自动 QQ 推送交付模型，以“文章 x QQ 群”为唯一粒度记录状态、尝试次数、最大尝试次数、错误类型、错误信息、OneBot 响应、消息 ID、最后尝试时间和成功时间。
- 自动推送默认关闭：`QQ_PUSH_ENABLED=false`。
- 自动推送默认范围：`QQ_PUSH_SCOPE=high_value_only`，首版高价值口径为 `score_total >= AUTO_REVIEW_THRESHOLD`；也支持 `all_public`。
- 发布入口已接入自动推送入队：人工发布、`publish_article()` helper 和自动发布成功后都会在开关开启时异步进入 QQ 推送编排。
- 推送前检查 `SITE_URL + article.public_path` 是否可访问；URL 不可访问和 OneBot 发送失败分别记录为 `url_unavailable` 与 `send_failed`。
- 自动交付会先原子领取尝试再执行 URL 检查和 OneBot 发送，避免重复任务并发消耗重试次数。
- OneBot HTTP 200 但 JSON 返回业务失败时按 `send_failed` 记录，不会误标记为成功。
- `sending` 状态超过 `QQ_PUSH_SENDING_STALE_SECONDS`（默认 600 秒）后允许后续任务重新领取，避免 worker 异常后长期卡住。
- 自动发送按目标群最近一次尝试时间做最小间隔保护，`QQ_PUSH_MIN_INTERVAL_SECONDS` 默认 60 秒，避免批量发布或补推时压垮 QQ / NapCat 发送通道。
- 自动推送只读取 `PushTarget.is_active=true` 的群；`is_default` 保留给后台手动推送默认目标。
- Django Admin 新增自动交付记录查看入口，并在文章详情中展示交付内联记录。

### 当前启用策略

- 生产已配置 NapCatQQ / OneBot v11 网关、测试群和 access token。
- 生产 `.env` 已设置 `QQ_PUSH_SCOPE=high_value_only`、`QQ_PUSH_IMPORTANCE_STRATEGY=ranked`，当前只等待自然榜单新闻触发测试群推送。
- 生产已部署迁移 `stable.0010_qqpushdelivery`，并设置 `QQ_PUSH_ENABLED=true` 进入测试群灰度。
- OneBot API 不得公网裸露；优先 Docker 内网 `http://onebot:3000`，临时映射只能绑定 `127.0.0.1`。

### 验收记录

- OneBot 直连和 Django 应用侧短消息均已成功发送到测试群 `1026525240`。
- 生产批量补推 126 篇公开文章时，交付记录成功创建并进入有限重试；NapCat / QQ 客户端随后返回 `网络连接异常`，系统正确记录为 `send_failed` 且未误标为成功。
- 已补充 `QQ_PUSH_MIN_INTERVAL_SECONDS` 节流保护，后续自动任务按目标群最小间隔重排，降低 QQ 风控和客户端异常风险。
- 2026-06-25 重新扫码登录 NapCat 后，Django `BotPusher` 短消息发送成功，`qq_auto_push_article_task -> qq_push_delivery_task -> OneBot` 自动任务链路已用真实公开文章验证成功，`QQ_PUSH_ENABLED=true`、`QQ_PUSH_SCOPE=all_public` 在生产 worker 生效。
- 2026-06-25 存量补推按 65 秒间隔运行并成功发送 79 条交付记录；按当前验收判断，不再要求继续补推全部历史公开新闻，剩余历史 `retrying/send_failed` 记录保留用于后台排查，不影响后续新发布文章自动推送。
- 2026-06-25 榜单重点推送部署后，生产 worker 已确认 `QQ_PUSH_ENABLED=true`、`QQ_PUSH_SCOPE=high_value_only`、`QQ_PUSH_IMPORTANCE_STRATEGY=ranked` 生效；本次不补推历史公开新闻，后续只等待自然榜单新闻推送。

## 2026-06-24 自动发布门禁优化本地实现

- OpenSpec change：`refine-automation-publish-gates`，当前 `tasks.md` 已完成本地实现和验证。
- 新增配置：
  - `AUTO_REWRITE_ENABLED=false`：默认跳过 AI 改写前置。
  - `AUTO_PUBLISH_CONTENT_SOURCE=base_translation`：默认使用基准翻译稿作为自动发布内容源。
  - `HIGH_VALUE_SOURCE_RULES=netkeiba:access,netkeiba:attention`：访问量榜和注目数榜评分阶段放行。
  - `AUTOMATION_WARNING_NOTIFY_EMAILS=754652181@qq.com`：高价值 warning 初期告警收件人示例。
- 新增数据字段：
  - `NewsArticle.gate_issues` 保存结构化门禁 issue。
  - `WorkflowStatus.DUPLICATE` 描述高度重复内容。
  - `duplicate_of / duplicate_score / duplicate_reason` 保存重复检测解释。
  - `automation_warning_email_signature / automation_warning_email_sent_at` 用于 warning 邮件 24 小时去重。
- 迁移 `0009_automation_publish_gates` 会导入首批非马名普通词固定译法，包括 `タイトル`、`メートル`、`オッズ`、`ハンデ`、`ラジオ`、`ダート`、`マイル`、`スプリント`、`クラス`、`チャンス`、`キャリア`、`イメージ`、`デビュー`、`ゲート`。
- 后台候选列表、候选详情、自动化日志和 Django Admin 已展示 blocker / warning / info、重复检测结果和相似文章信息。
- `2026-06-24` review 返修：
  - 重新校验通过且当前不再重复的文章，会清理旧 `duplicate_of / duplicate_score / duplicate_reason`，并把旧 `duplicate` / `pending_review` 状态恢复为可进入自动发布批次的候选状态，避免显示 `publish_ready` 但被批发布排除。
  - 候选列表与候选详情中的相似文章现在链接到后台候选详情 `/admin/candidates/<id>/`。
- 本地验证：
  - `DB_ENGINE=sqlite /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py check`：通过。
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py test stable.tests.AutomationFlowTests stable.tests.ConsoleFlowTests --noinput`：通过，23 项。
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py test stable --noinput`：通过，106 项。
  - `openspec validate refine-automation-publish-gates --strict`：通过。

### 生产上线结果

- PR：GitHub PR #4 `[codex] refine automation publish gates` 已 squash merge。
- 生产提交：服务器 `/opt/umanewsbot` 已从 `71ab966` 更新到 `42a4622`。
- 部署前 `.env` 备份：`.env.backup.refine-automation-20260624_013323`。
- 已设置生产灰度配置：
  - `AUTO_REWRITE_ENABLED=false`
  - `AUTO_PUBLISH_CONTENT_SOURCE=base_translation`
  - `HIGH_VALUE_SOURCE_RULES=netkeiba:access,netkeiba:attention`
  - `HIGH_VALUE_WARNING_SCORE_THRESHOLD=90`
  - `AUTO_DUPLICATE_LOOKBACK_DAYS=7`
  - `AUTO_DUPLICATE_HIGH_THRESHOLD=0.86`
  - `AUTO_DUPLICATE_REVIEW_THRESHOLD=0.72`
  - `AUTOMATION_WARNING_EMAIL_ENABLED=true`
  - `AUTOMATION_WARNING_NOTIFY_EMAILS=754652181@qq.com`
  - `AUTOMATION_WARNING_EMAIL_DEDUP_HOURS=24`
- 容器：`web` healthy，`db / redis` healthy，`worker / beat` up。
- 迁移：`stable.0009_automation_publish_gates` 已应用；运行时确认 `WorkflowStatus.DUPLICATE=True`，首批 `non_horse_common_word` 普通词种子数量为 `14`。
- 验证：
  - `docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py check`：通过。
  - `http://umafans.run/healthz/` 返回 `200`。
  - `http://umafans.run/` 返回 `200`。
- 部署注意：重启初期日志曾出现一次 `automation_warning_email_sent_at` 字段已存在异常，判断为容器启动自动迁移与手工迁移并发撞车；后续日志显示 `No migrations to apply`，`showmigrations stable` 显示 `0009` 已应用，服务健康检查持续返回 `200`。

## 2026-06-24 抓取新鲜度与 JRA 日期解析本地实现

- OpenSpec change：`fix-crawl-freshness-and-jra-date-parse`，当前已完成本地实现并于 `2026-06-25` 部署生产。
- 修复范围：
  - JRA 官方新闻日期解析兼容 `2026年5月31日`、`5月31日`、零填充和非零填充日期。
  - JRA 无年份日期优先使用列表月份或 URL 年份；缺少上下文时使用当前东京年份，若推断日期晚于当前东京日期超过 7 天则回退上一年。
  - JRA 列表中单条日期异常会跳过该条并继续处理同一列表中其他新闻；整体结构或网络失败仍会记录为 JRA 抓取失败。
  - netkeiba 访问量榜和注目数榜从每天 `00:00/12:00`、`00:05/12:05` 调整为小时级抓取，并在 review 返修后避开新着顺和周日重赏高频补抓：新着顺每小时 `00` 分，访问量榜每小时 `16` 分，注目数榜每小时 `26` 分。
  - 内置来源定义同步更新访问量榜 / 注目数榜 `crawl_interval_minutes=60` 和来源备注，避免后台展示、异常检测与实际调度不一致。
  - 后台工作台和来源列表新增来源健康摘要，区分“运行中”“运行超时”“成功”“成功无新增”“失败”“长时间未运行”，并展示最近新增数、重复数或错误摘要；超过 60 分钟仍未完成的运行中记录会显示为疑似卡住，停用来源不参与“长时间未运行”判定。
  - JRA 单篇详情结构异常被跳过时，跳过摘要会同时写入本轮 `CrawlJob.error_message` 和 `NewsSource.last_crawl_message`，便于事后按 job 追溯。
- 本地验证：
  - `DB_ENGINE=sqlite /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py check`：通过。
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py test stable.tests.AdapterTests stable.tests.ConsoleFlowTests stable.tests.CrawlAutoTranslateTests --noinput`：通过，25 项。
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py test stable --noinput`：通过，118 项。
  - `openspec validate fix-crawl-health-running-and-schedule-stagger --strict`：通过。
  - `openspec validate --all`：通过，7 项。
- 生产部署：
  - 服务器 `/opt/umanewsbot` 已于 `2026-06-25` 更新到 `7f54f13`，部署前 `.env` 备份为 `.env.backup.three-changes-20260625_003714`。
  - `web / worker / beat` 已重建，`manage.py check` 通过，`http://127.0.0.1/healthz/` 与 `/` 均返回 `200`。
  - 运行态确认 `crawl-netkeiba-latest-hourly / access / attention` 分钟分别为 `0 / 16 / 26`，内置来源定义中三者 `crawl_interval_minutes=60`。
  - 后续仍需等待自然调度，确认访问量榜 / 注目数榜在连续小时内按 `16 / 26` 分生成新 `CrawlJob`。

## 2026-06-23 前台发布判定代码阅读结论

- 公开前台首页 `/` 与详情页 `/news/<article_id>/` 只展示 `workflow_status=published` 且 `published_to_web_at` 非空的 `NewsArticle`；旧的非纯数字 `/news/<slug>/` 兼容入口会跳转到对应 ID URL。
- 抓取入库的新稿默认是 `workflow_status=pending_translation`，不会因为来自 `netkeiba` 新着、访问榜、注目榜或 `JRA` 官方新闻而直接进入前台。
- 翻译成功后文章进入 `pending_edit`；若 `AUTOMATION_ENABLED=true`，会触发自动化评分、改写与校验链路。
- 自动化评分为 `auto` 的文章也不会立刻公开；必须完成改写、通过一致性校验成为 `automation_status=publish_ready`，再由批量自动发布任务写入 `workflow_status=published` 与 `published_to_web_at` 后才进入前台。
- 自动化硬规则会把重复稿、正文过短或为空、疑似乱码/结构损坏、疑似广告或导航短页直接置为 `ignored`，默认不进入前台。
- 长采访或引语较多、翻译未成功、缺少基准中文翻译等会转为 `manual` / `pending_review`，需要人工审核后发布。
- 人工发布通过运营后台文章编辑页完成时会写入 `workflow_status=published`、`published_to_web_at`、`published_by_mode=manual`；无封面时需要二次确认。Django Admin 或后台 API 若只改 `workflow_status` 而不补 `published_to_web_at`，仍不会被公开前台接收。

## 2026-06-23 外部赛马数据导入 OpenSpec 提案

- 已创建 OpenSpec change：`add-netkeiba-horse-data-import`。
- 提案目标：使用 `keibascraper` / netkeiba 作为低频离线导入来源，先抓取近两年比赛、出走、赛果、赔率、马匹血统和马匹履历数据，保存结构化字段与原始 payload，并派生本地马名索引。
- 关键约束：导入默认关闭，不加入自动全量调度；生产必须人工显式执行、强制限速、随机抖动、小批量、可暂停、可恢复；导入失败不得影响新闻抓取、翻译、自动化发布或公开前台。
- 当前状态：仅完成 proposal、design、delta spec 和 tasks，尚未实现代码，尚未执行真实爬取。

## 2026-06-19 公开首页资讯流升级 OpenSpec 主 change

### 已归档产物

- 正式规格：`openspec/specs/public-home-info-feed/spec.md`
- 归档目录：`openspec/changes/archive/2026-06-22-upgrade-public-home-info-feed/`
- 归档内保留 proposal、design、delta spec、tasks 和 `.openspec.yaml`

### 主范围

- Web 端：首页升级为轻导航、主头条、普通新闻流和右侧热门/重点辅助模块。
- 移动 H5：首页升级为轻顶部、轻量头条和高密度左文右图新闻列表。
- 数据层优先复用现有 `NewsArticle`、`NewsSnapshot` 与自动评分字段，不新增数据库模型。
- 公开站点样式从后台 `console.css` 中解耦，后续实现应新增公开站点专用样式入口。
- 文章详情页与首页共享公开站点视觉体系，并保持已有有效稿件字段优先级。
- 后续实施采用严格 TDD：发布过滤、普通流排序、头条选择、热门代理、详情页字段和公开静态资源必须逐行为执行 RED -> GREEN -> REFACTOR，禁止一次性批量写完全部测试后再实现。
- 热门代理必须在有限候选集内批量读取 `NewsSnapshot` 或使用等价预取方式，避免无上限扫描或逐篇文章查询最近快照。

### 明确非目标

- 不做原生 App、个性化推荐、无限滚动、站内浏览量、站内评论或用户系统。
- 不在本轮新增手工置顶、推荐位、专题、搜索频道或赛事日历模型。
- 不改抓取、翻译、AI 改写、自动发布、QQ 推送或 Docker Compose 主架构。

### 本地实现结果

- 公开首页 `/` 已升级为公开站点专用模板和 `stable/public.css`，不再以后台 `console.css` 作为主要样式入口。
- 首页数据层复用现有 `NewsArticle`、`NewsSnapshot` 与自动评分字段，提供 `headline_article`、`feed_articles`、`latest_articles` 和 `hot_articles`。
- 头条选择按近期范围、赛事优先级、自动评分、封面和发布时间排序；低量内容回退到近 7 天或最新已发布文章。
- 热门代理在有限已发布候选集内批量读取上游访问/注目快照，无快照时按自动评分和发布时间回退；页面只标注“原站热度/原站排行”，不包装为本站评论或浏览量。
- 移动 H5 首页采用轻头条 + 左文右图高密度列表，普通卡片在 390px 视口验收中稳定为约 128px 高，缺图卡不破坏列表布局。
- 详情页复用公开站点 base，继续展示有效标题、摘要、正文、来源、原文链接和发布时间，并完成窄屏阅读排版验收。
- 本轮未新增数据库模型、迁移、生产配置或部署运行手册步骤。

### 校验结果

- `openspec validate upgrade-public-home-info-feed --strict`：归档前通过。
- `openspec validate --all`：归档前通过；归档并同步正式 spec 后再次通过。
- `/plan-eng-review upgrade-public-home-info-feed`：通过。
- `DB_ENGINE=sqlite /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 manage.py test stable.tests.PublicHomeInfoFeedTests`：通过，10 项。
- `DB_ENGINE=sqlite /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 manage.py check`：通过。
- `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 manage.py test stable`：通过，88 项。
- 本地开发服务器浏览器验收：桌面首页、移动首页、桌面详情页、移动详情页通过；无横向溢出，图片加载正常，移动普通卡高度受控，桌面主列与右侧热门模块不重叠。

### 生产部署结果（2026-06-22）

- GitHub PR #1 从 draft 转为 ready 后合并到 `main`，merge commit 为 `e834f58`，包含实现提交 `1c9be7d`。
- 服务器 `/opt/umanewsbot` 从 `62a6a02` 快进到 `e834f58`；部署前备份 `.env` 为 `.env.backup.20260622_140844`。
- 生产使用低成本 compose 执行 `./deploy_lowcost.sh`：重建 `web/worker/beat`，`migrate` 显示 `No migrations to apply`，`collectstatic` 成功处理 `stable/public.css`，`web` 容器 healthy。
- 外部健康检查通过：`http://umafans.run/healthz/` 与 `http://umafans.run/` 均返回 `200`。
- 首页 HTML 已引用 `/static/stable/public.2eec24723b45.css`，页面包含 `home-page`、`headline-card`、`news-card` 和“原站热度”；不再引用后台 `console.css`。
- 浏览器生产验收通过：桌面端显示轻导航、头条和热门模块；390px 移动端普通新闻卡约 `128px` 高，首屏头条后可见 3 条普通新闻，无横向溢出；新闻详情页可打开，标题、封面和公开详情结构正常，控制台无错误。

### 移动端首屏密度 follow-up（2026-06-22）

- 在不改变首页数据层、公开 URL、模板结构或普通新闻卡尺寸的前提下，后续小幅收紧移动端首页视觉密度。
- 调整范围仅限 `server/stable/static/stable/public.css` 的 `max-width: 599px` 移动端规则：
  - 顶部和页面内边距略收紧。
  - 移动端头条图片从 `16 / 9` 改为 `16 / 7`。
  - 移动端头条摘要隐藏，仅保留来源时间和两行标题。
  - 普通新闻卡继续保持约 `128px` 高和右侧缩略图结构。
- 本地临时 SQLite + 浏览器验收结果：390px 视口下头条高度约 `250px`，第一张普通新闻卡提前到 `top=381`，首屏可见 4 条普通新闻卡，无横向溢出，控制台无错误。
- 生产部署结果（2026-06-23）：GitHub PR #2 合并到 `main`，merge commit 为 `04e2ee9`；服务器 `/opt/umanewsbot` 从 `e834f58` 快进到 `04e2ee9`，部署前备份 `.env` 为 `.env.backup.20260623_120201`。
- 生产 `./deploy_lowcost.sh` 执行成功：`migrate` 显示 `No migrations to apply`，`collectstatic` 后首页引用 `/static/stable/public.9aaf4b105424.css`，`web` 容器 healthy。
- 外部健康检查通过：`http://umafans.run/healthz/` 与 `http://umafans.run/` 均返回 `200`；首页包含 `home-page`、`headline-card`、`news-card` 和“原站热度”，不再引用 `console.css`。
- 浏览器生产验收：390px 移动端头条约 `257px` 高，第一张普通新闻卡 `top=388`，普通卡约 `128px` 高，首屏可见 4 条普通新闻卡，无横向溢出；详情页公开结构、封面和标题正常，控制台无错误。

## 2026-06-07 术语候选发现生产部署纪要

### 部署内容

- 服务器 `/opt/umanewsbot`：`git pull origin main` 从 `7123e4e` 快进到 `e2e3e07`
- 迁移 `0006`（纯新增 `TermCandidate` / `TermCandidateEvidence` 两表）已应用；`web` 启动脚本会自动迁移，显式 `migrate` 显示 `No migrations to apply`
- `.env` 追加并保持关闭：`TERM_DISCOVERY_ENABLED=false` / `TERM_DISCOVERY_PROVIDER=rules` / `TERM_DISCOVERY_MIN_CONFIDENCE=60`
- 用低成本 compose `docker-compose.prod.lowcost.yml` 重建 `web/worker/beat`，`db/redis/nginx` 未动

### 迁移前备份（可回滚）

- `.env.backup.20260607_033207`
- 数据库快照 `backups/pre-0006-20260607_033207.sql`（74M，`horse_news` 库，含 `PostgreSQL database dump complete` 标记）

### 上线后验证

- 容器 `web/db` healthy、`worker/beat` up；`manage.py check` 0 issues
- 候选/证据模型可查、计数 `0/0`；`nginx → web` 与外网 `umafans.run` / `www.umafans.run` 均 `200`
- `worker` 近 200 行日志无报错；核对 `AUTOMATION_ENABLED=true`、`REWRITE_PROVIDER=siliconflow` 未变更

### 回滚方式

- 停用功能：将 `TERM_DISCOVERY_ENABLED=false`（当前即为关闭），重启 `web` 与 `worker` 即可，无需回滚迁移或删除候选数据
- 整体回退：用上面的 `.env` 备份与数据库快照还原

## 最近一次翻译稳定性修复

- 现象：部分文章翻译失败，错误为 `Translation response changed unknown horse names`
- 原因：未知马名校验过于严格；模型没有原样保留疑似未收录马名时，系统会让整篇翻译失败
- 修复：
  - 翻译 prompt 中对未知马名使用 `__UMA_KEEP_n__` 占位符保护
  - 模型返回后将占位符还原为原始日文马名
  - 若模型仍未保留未知马名，不再让整篇失败，而是写入 metadata warning 后接受译文
- 验证：
  - 新增未知马名占位符还原测试
  - 新增未知马名仍缺失但不阻断翻译的测试
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable` 通过，45 项

## 自动化内容运营 MVP 开发纪要

### 本轮新增能力

- `NewsArticle` 增加自动化字段：分流模式、风险等级、自动化状态、评分、决策原因、基准翻译稿、改写稿、自动发布时间与错误信息
- 新增 `AutomationLog`，记录评分、改写、校验、发布、通知各阶段过程
- 新增 `NotificationLog`，记录邮件 / 短信 / QQ / 微信通知状态；MVP 真实发送只启用邮件
- 新增自动化服务：
  - `stable.services.automation`
  - `stable.services.rewriting`
  - `stable.services.validation`
  - `stable.services.notifications`
- 新增 Celery 任务：
  - `process_article_automation_task`
  - `score_article_task`
  - `rewrite_article_task`
  - `validate_rewrite_task`
  - `auto_publish_batch_task`
  - `send_notification_task`
  - `detect_automation_anomalies_task`
  - 新增 Celery Beat 调度：
    - 每 15 分钟批量自动发布
    - 每 30 分钟检测自动化异常
  - 自动发布批量规则已调整为：
    - 常规时段每批最多 4 篇
    - 每周日北京时间 13:00-16:00 每批最多 10 篇
    - 调度频率仍为每 15 分钟一次

### 当前验证结果

- `DB_ENGINE=sqlite python manage.py check`：通过
- `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable`：通过，40 项测试

### 生产启用前注意

- 必须先部署代码并执行迁移 `python manage.py migrate`
- 初次部署建议 `AUTOMATION_ENABLED=false`
- 确认后台可看到自动化字段和日志后，再切换 `AUTOMATION_ENABLED=true`
- 当前自动发布策略为常规每批 4 篇、周日 13:00-16:00 每批 10 篇，并定期人工抽检自动发布稿

## 专有术语候选发现与待标注池

### 当前实现

- 新增 `TermCandidate` 与 `TermCandidateEvidence`，分别保存待审核术语和按文章聚合的来源证据。
- 首版支持马名、比赛名、骑手名和马主名四类实体。
- 新文章入库后可旁路触发发现任务；发现失败不会阻断抓取、翻译、改写或发布。
- 候选会与正式 `TermEntry.source_ja`、日文别名及已有候选去重；停用正式术语也参与去重。
- 后台新增“术语候选”列表、详情、单篇重新发现、接受、修改后接受、合并、拒绝、忽略和保守批量拒绝/忽略。
- 规则或 AI 发现结果不会直接写入正式术语库，只有工作人员明确接受后才创建 `TermEntry`。

### 当前启用策略

- `TERM_DISCOVERY_ENABLED=false`：默认关闭。`2026-06-07` 已在生产应用迁移并部署代码，当前处于“先关后开”灰度阶段，待单篇抽检后再开启。
- `TERM_DISCOVERY_PROVIDER=rules`：首版使用保守规则发现器。
- `TERM_DISCOVERY_MIN_CONFIDENCE=60`：低于阈值的发现结果不进入候选池。

### 当前验证结果

- `DB_ENGINE=sqlite python manage.py check`：通过。
- `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable`：通过，69 项。
- `openspec validate --all`：通过。
- 两种生产 Compose 配置基于 `.env.example` 检查通过。
- 已使用独立 SQLite 数据库部署本地验收环境，并通过浏览器完成筛选、单篇重跑、接受、合并、拒绝、忽略、批量操作、操作日志和别名搜索验收。

## 最近一次关键修复纪要

### 现象

- 域名已经解析到服务器 IP
- HTTP 请求被 `301` 跳转到 HTTPS
- HTTPS 请求返回 `400 Bad Request`
- 浏览器无法正常打开正式域名页面

### 排查过程

- 先确认 DNS 是否已经真正打通，排除“域名未解析”的假象
- 再比对仓库当前代码与服务器实际 `HEAD`
- 检查服务器 `.env` 中的 `ALLOWED_HOSTS`、`SITE_URL`、`SECURE_SSL_REDIRECT` 等关键项
- 进入 `nginx` 容器读取真实 `/etc/nginx/conf.d/default.conf`
- 检查 `web` 容器运行态环境变量与日志
- 最终确认线上实际行为与仓库当前预期不一致

### 确认的真实根因

- 服务器并未运行到本地最新域名接入修复版本
- 服务器仍在使用旧版 `nginx` 配置，保留 `80 -> 443` 跳转与启用中的 HTTPS server block
- 服务器 `.env` 仍使用旧版 IP + HTTPS 强制配置
- `ALLOWED_HOSTS` 未包含正式域名，导致域名下请求被 Django 拒绝

### 修复动作

- 备份服务器 `.env`
- 清理或暂存本地未提交运行态差异
- 将服务器代码同步到正确版本
- 更新 `.env`，切换为正式域名 + HTTP 阶段配置
- 重建并启动 `web / worker / beat / db / redis / nginx`
- 进入容器核对真实 `nginx` 配置与环境变量，确保运行态与仓库一致

### 修复后验证结果

- `nginx` 容器加载了新版 `default.conf`
- `80 -> 443` 强制跳转已移除
- 正式域名 `umafans.run` / `www.umafans.run` 页面可打开
- 线上服务恢复到与当前仓库预期一致的状态

### 后续如何避免再次发生

- 每次部署前先确认服务器 `HEAD`，不要只看本地仓库
- 每次域名或安全策略变更时，同时核对：
  - 仓库代码
  - 服务器 `.env`
  - `nginx` 容器内真实配置
  - `web` 容器内真实环境变量
- 不把聊天记录当唯一记忆来源，关键修复过程必须落文档
- 生产问题处理时，坚持“先核对运行态，再给结论”

## 2026-06-23 外部赛马数据导入实现状态

### 本地已实现

- 新增 OpenSpec change：`add-netkeiba-horse-data-import`。
- 新增 `keibascraper==3.1.5` 依赖，并通过管理命令提供 import 冒烟检查入口。
- 新增外部赛马数据表：比赛、出走表、赛果、赔率、马匹、马匹履历、马名索引、导入运行、导入错误和单来源导入锁。
- 新增 `stable.services.external_horse_data`：
  - 包装 `keibascraper.race_list()` 与 `keibascraper.load()`。
  - 项目侧强制执行网络开关、请求间隔、随机抖动。
  - 保存结构化字段与 `raw_payload`。
  - 对比赛、出走、赛果、赔率、马匹、履历做幂等 upsert。
  - 从出走表、赛果、可信单马参数派生 `ExternalHorseAlias`。
  - 单马导入仅在存在可信马名时创建马名索引，避免凭空写入错误马名。
  - 记录覆盖率统计：比赛数、出走数、赛果数、赔率数、马匹数、履历数、唯一马 ID、唯一日文马名、缺失马 ID/马名记录数。
- 新增管理命令 `import_external_horse_data`：
  - 支持默认近两年、指定年月、指定 `race_id`、指定 `horse_id`、`--horse-name`、`--dry-run`。
  - 支持 `--max-races`、`--max-horses`、`--fetch-odds`、`--no-fetch-horse-detail`。
  - 支持 `--lookup-name` 查询本地马名索引。
  - 支持 `--stats-run-id` 查看导入运行统计。
  - 支持 `--check-dependency` 检查 `keibascraper` 是否可 import。
- 新增 Celery 任务 `import_external_horse_data_task`，但未加入默认 Celery Beat 全量调度。

### 当前默认策略

- `EXTERNAL_HORSE_DATA_IMPORT_ENABLED=false`。
- `EXTERNAL_HORSE_DATA_ALLOW_NETWORK=false`。
- 代码已可部署迁移，但生产不会自动发起 netkeiba 请求。
- 外部数据导入当前不参与新闻抓取、翻译、AI 改写、自动发布或公开前台。

### 本地验证

- `DB_ENGINE=sqlite python manage.py check`：通过。
- `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable.tests.ExternalHorseDataImportTests`：通过，8 项。
- `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable`：通过，96 项。

### 生产执行提醒

- 生产首次真实导入前必须备份数据库。
- 先执行 dry-run 或单月小批量。
- 首次真实请求建议使用 8-10 秒间隔、小批量、低峰时段，不抓赔率。
- 同一来源通过导入锁避免多 worker 并发放大请求。
- 如发现异常，优先关闭 `EXTERNAL_HORSE_DATA_IMPORT_ENABLED` / `EXTERNAL_HORSE_DATA_ALLOW_NETWORK` 并停止任务；新表不参与主新闻链路。

### 生产首轮小批量导入结果

- 生产部署提交：`58a6e82`。
- 部署前 `.env` 备份：`.env.backup.external-horse-data-20260623_231514`。
- 服务器迁移：`stable.0008_externaldataimportrun_externaldataimportlock_and_more` 已应用。
- 容器内依赖检查：`keibascraper import ok`。
- dry-run：`2026-05` 单月、小批量、最多 10 场，预计 20 个请求。
- 真实导入命令：`2026-05`、`--max-races 10`、`--max-horses 30`、不抓赔率、不补马匹详情、请求间隔 10 秒 + 2 秒抖动。
- 运行结果：`run_id=1`，`status=paused`，`success_count=10`，`failure_count=0`，`skipped_count=326`。
- 写入统计：`race_count=10`、`entry_count=151`、`result_count=143`、`horse_count=143`、`unique_horse_id_count=143`、`unique_horse_name_count=143`、`missing_horse_id_or_name_count=16`。
- 样本马名索引已写入，如 `ヴォルスター`、`ファイツオン`、`サトノエピック`。

### 后续继续导入注意

- `2026-06-24` 已补充按月续跑逻辑：再次导入同一月份时会先跳过已落库的 `ExternalRace.race_id`，只处理下一批未导入 race。
- 不建议直接一次性跑近两年全量；应继续按月、小批量、低速运行，并观察失败率和覆盖率。

### 生产第二批续跑结果

- 续跑部署提交：`a61d789`。
- 第二批真实导入：`run_id=2`，同为 `2026-05`，最多 10 场，不抓赔率，不补马匹详情，10 秒间隔 + 2 秒抖动。
- 续跑确认：`parameters.already_imported_race_count=10`，说明第二批已跳过首批落库 race。
- 运行结果：`status=paused`，`success_count=10`，`failure_count=0`，`skipped_count=316`。
- 累计写入统计：`race_count=20`、`entry_count=292`、`result_count=274`、`horse_count=274`、`unique_horse_id_count=274`、`unique_horse_name_count=274`、`missing_horse_id_or_name_count=36`。

### 生产第三批续跑结果

- 第三批真实导入：`run_id=3`，仍为 `2026-05`，最多 30 场，不抓赔率，不补马匹详情，10 秒间隔 + 2 秒抖动。
- 运行结果：`status=paused`，`success_count=30`，`failure_count=0`，`skipped_count=286`。
- 累计写入统计：`race_count=50`、`entry_count=742`、`result_count=695`、`horse_count=695`、`unique_horse_id_count=695`、`unique_horse_name_count=695`、`missing_horse_id_or_name_count=94`。
- 服务器健康检查：`/healthz/` 返回 `200`。

### 生产长循环导入中断记录

- `2026-06-24` 按用户确认启动长循环：从 `2026-05` 到 `2025-06`，每批 25 场，不抓赔率，不补马匹详情，10 秒间隔 + 2 秒抖动。
- 成功完成批次：`run_id=4` 到 `run_id=8`，均为 `2026-05`，每批 25 场，均 `failure_count=0`。
- 中断批次：`run_id=9`，`2026-05`，已成功 7 场后执行进程以退出码 `137` 中断；当时 `web/db` 容器发生重启，但 `OOMKilled=false`。
- 已人工收尾：将 `run_id=9` 标记为 `partial`，写入 `finished_at` 和 coverage，释放 `ExternalDataImportLock`。
- 中断后累计写入：`race_count=182`、`entry_count=2692`、`result_count=2518`、`horse_count=2401`、`unique_horse_id_count=2401`、`unique_horse_name_count=2401`、`missing_horse_id_or_name_count=348`。
- 当前服务状态：`web/db/redis/nginx/worker/beat` 运行，`/healthz/` 返回 `200`。按“报错退出则停止”约定，未继续启动后续导入。

## 后台原文选区快速加入术语库

- OpenSpec change：`add-selection-term-quick-add`。
- 本地分支：`codex/add-selection-term-quick-add`。
- 实现时间：`2026-06-24`。
- 状态：已于 `2026-06-25` 合并到 `main` 并部署生产，OpenSpec 已归档为 `openspec/changes/archive/2026-06-24-add-selection-term-quick-add/`。

### 已实现能力

- 候选详情页和文章编辑台的原文标题、原文正文已标记为可选区来源。
- 两个页面都新增“快速加入术语库”入口；管理员可点击“使用当前选区”填入日文原词，也可手工粘贴作为无 JavaScript fallback。
- 快速表单字段包含日文原词、术语类型、中文译词；术语类型默认 `horse`（马名），但可改为赛事、骑手、调教师、马主、牧场、赛马场、机构、固定译法或其他。
- 后端新增文章上下文 POST 入口 `console-article-quick-term-create`，路径为 `/admin/articles/<article_id>/quick-term/`。
- 创建正式术语时复用 `validate_term_payload()`，继续执行正式术语库的类型、重复、比赛等级、启用状态和优先级校验。
- 快速创建默认写入：`is_active=true`、`priority=0`、`race_grade=""`、`aliases_ja=[]`、`aliases_zh=[]`，并在 `notes` 记录来源文章 ID 和标题。
- 创建成功后留在当前页面并显示成功消息，同时写入 `OperationLog`。
- 创建失败时不写入 `TermEntry`，通过 messages 展示错误；重复术语提示已有术语 ID，并提供已有术语编辑页链接。

### 明确边界

- 快速加入术语库只写入 `TermEntry` 和操作日志。
- 不触发 `translate_article_task`，不触发自动化处理，不修改当前文章的 `title_zh`、`body_zh`、`base_translation_zh` 或 `rewrite_body_zh`。
- “新增术语后自动重新应用术语/重翻译联动”仍属于后续 change，不在本次实现中。
- 生产部署记录见 `docs/deploy_runbook.md` 的 `2026-06-25 三个运营改造 change 合并、部署与归档`。

### 验证结果

- `DB_ENGINE=sqlite python manage.py check` 已通过（本地使用 Codex bundled Python 执行）。
- `DB_ENGINE=sqlite python manage.py test stable.tests.ConsoleFlowTests --verbosity=2` 已通过；本轮按 OpenSpec 场景补齐非法术语类型、换行误选整段、文章不存在、非联动状态保持和原文选区脚本限制等测试。
- `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable --verbosity=2` 已通过，126 个测试全部通过。
- `openspec validate add-selection-term-quick-add --strict` 已通过。
- 本地浏览器验收使用临时 SQLite 后台：
  - 候选详情页可创建术语并返回当前候选页。
  - 候选详情页重复创建同类型同日文原词时显示失败提示和已有术语编辑链接。
  - 编辑台快速术语入口已验证不会提交外层文章编辑表单；提交成功后返回编辑台。
  - 无选区点击“使用当前选区”不会乱填，提示需在原文标题或正文中选择短词。

## 后台快速术语创建后的当前稿联动提案

- OpenSpec change：`reapply-terms-after-quick-add`。
- 创建时间：`2026-06-24`。
- 当前状态：本地实现和验证已完成；review 后的浮层交互和多标签页 session pending 返修已于 `2026-06-25` 完成，并已随 `7f54f13` 部署生产。OpenSpec 已归档为 `openspec/changes/archive/2026-06-24-reapply-terms-after-quick-add/`。
- 目标：在候选详情页或文章编辑台快速创建正式术语后，为当前文章提供明确的后续动作：
  - 一次性“应用该术语到当前稿”：只把刚创建的指定术语应用到当前文章整篇已有中文字段，不调用翻译模型，不重扫整个正式术语库。
  - 页面级“重新翻译”：复用现有 `translate_article_task`，异步重新走翻译链路；不属于术语成功浮层，若页面已有按钮则不新增。
- 关键边界：
  - 不做全站批量重翻译或批量重应用。
  - 快速创建成功后的应用入口只出现一次；刷新、离开页面或错过成功反馈后不补常驻入口。
  - 不自动发布文章，不改变前台发布过滤规则。
  - 默认保护 `manually_edited_fields` 中的人工标题、正文、摘要和推送摘要，不在无确认时覆盖人工稿。
  - 术语应用必须记录文章、用户、来源术语、更新字段和跳过字段；页面级重新翻译继续记录文章、用户和任务触发结果。
- 实现范围：
  - 新增指定术语应用服务函数，只替换刚创建术语的日文原词和日文别名。
  - 新增后台 POST 入口 `/admin/articles/<article_id>/apply-created-term/`。
  - quick-create 成功后通过 session 多 pending 字典提供一次性后续动作上下文；候选详情页和编辑台只消费匹配当前文章与页面上下文的 pending follow-up。
  - `candidate_retranslate` 改为安全返回，并继续作为页面级重新翻译入口记录任务触发结果；术语成功浮层不提供重翻译入口。
  - 候选详情页和编辑台已改为页面上方浮层：`术语【日文名（中文名）】已添加，点击此处立即应用到文章中`；浮层只承载当前术语应用，不承载重新翻译。
  - 旧的术语表单内嵌“刚创建术语”面板和 `retranslate-created-term-*` follow-up 表单/按钮已删除；重新翻译仅保留页面级既有入口。
  - 浮层点击“点击此处”立即应用，不再二次确认；点击关闭 icon、应用成功、当前页面新术语浮层出现、关闭页面或 15 秒超时后消失。
  - 浮层不阻塞选区、滚动、编辑和其他不离开当前页面的点击行为。
  - session follow-up 已从全局单槽改为多 pending 结构，避免多标签页之间互相覆盖；渲染不匹配文章或上下文时不会消费其他 pending follow-up。
  - 后端不额外增加一次性 token 限制；当前后台仅单人可信使用，手工构造接口请求被视为可接受风险。
- TDD 测试：
  - `2026-06-25` 已先在 `server/stable/tests.py` 补充完整测试约束，覆盖浮层文案、关闭/15 秒 DOM 合同、旧内嵌面板不存在、`retranslate-created-term-*` 不存在、多 pending、不匹配页面不消费 pending、同页新术语替换旧浮层，以及应用术语不派发翻译任务。
  - 红灯阶段结果：未实现新交互前，`DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable.tests.ConsoleFlowTests --noinput` 为 31 项中 5 项失败，失败集中在旧内嵌面板和单槽 session。
- 本轮验证结果：
  - `DB_ENGINE=sqlite /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py check`：通过。
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py test stable.tests.ConsoleFlowTests --noinput`：通过，31 项。
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py test stable --noinput`：通过，135 项。
  - `openspec validate reapply-terms-after-quick-add --strict`：通过。
- 生产部署记录见 `docs/deploy_runbook.md` 的 `2026-06-25 三个运营改造 change 合并、部署与归档`。
- 规格校验：`openspec validate reapply-terms-after-quick-add --strict` 已通过。

## 2026-06-25 外部马名索引接入识别链路本地实现

- OpenSpec change：`use-external-horse-alias-for-name-recognition`。
- 创建时间：`2026-06-25`。
- 当前状态：本地实现、验证、OpenSpec 归档和生产部署已完成；归档目录为 `openspec/changes/archive/2026-06-25-use-external-horse-alias-for-name-recognition/`。
- 背景：近两年外部赛马数据已导入 `ExternalHorseAlias`，当前未知马名识别仍主要依赖片假名 token + 上下文打分，无法真正判断没见过的片假名词是不是普通词，容易把 `タイトル` 等普通词误判为马名，也可能漏掉 `マヤノライジン` 等真实马名。
- 核心边界：
  - `TermEntry` 继续表示有中文译名或固定译法的正式术语，参与翻译术语表、译后替换和正式术语校验。
  - `ExternalHorseAlias` 只表示本地外部马名索引，用来确认“这是马名”，不代表已有中文译名，不批量写入 `TermEntry`。
  - 新闻处理链路只查询本地数据库，不在翻译、校验或候选发现阶段实时访问 netkeiba / keibascraper。
- 已实现能力：
  - `server/stable/services/terms.py` 新增结构化马名识别结果，区分 `formal_term`、`external_alias` 和 `heuristic`，并保留旧字符串列表接口兼容既有调用。
  - 识别链路会先提取候选片假名 token，做 NFKC 标准化，再批量查询本地 `ExternalHorseAlias.normalized_name__in`；同一日文名多次出现时按文章出现顺序和长词优先去重。
  - 正式 `TermEntry(term_type=horse)` 优先于外部马名索引；已存在正式中文译名的马名继续走正式术语提示和替换，不再作为未知马名保护。
  - 翻译阶段对外部已知但无中文译名的马名做占位符保护，译后还原为日文原名，不自动替换为中文；翻译 metadata 会记录 `recognized_horse_names` 和 `external_horse_names`。
  - 发布校验阶段把外部已知马名未保留记录为独立 `external_horse_not_preserved` warning，payload 包含日文名、全部外部 horse ID、主展示 ID、来源、置信度和冲突标记；只命中外部索引的马名不触发核心术语或背景术语缺失。
  - 术语候选发现阶段把新闻中出现、外部索引命中但无正式中文译名的马名均作为 `external_horse_alias` 高置信候选来源，包括正文背景段落中的马名；已有正式马名术语或日文别名时不重复建候选。
  - 若片假名文本同时命中普通词过滤表和外部马名索引，必须依赖强马名上下文消歧，不能仅因数据库存在同名马就识别为马名。
  - 同一日文马名对应多个外部 horse ID 时，识别结果和校验 payload 保留全部 ID，不静默只取第一条。
- `2026-06-25` review 返修：
  - `limit` 只限制需要原样保留的外部已知马名和启发式疑似马名，不再让已有中文译名的正式马名占用保护名额。
  - `extract_unknown_horse_names()`、翻译阶段和发布校验阶段均改为先取完整结构化识别结果，再对 `needs_preserve=True` 的名单截断。
  - 新增回归测试覆盖“前面出现多个正式马名，后面出现外部已知但无中文译名马名”时，翻译保护和发布校验仍能命中后者。
- 已创建规格：
  - `external-horse-name-recognition`：新增本地外部马名索引识别能力。
  - `termbase-and-race-priority`：修改翻译链路正式术语命中，并新增外部已知马名保留校验。
  - `term-candidate-discovery`：修改候选发现，使外部马名索引成为高置信来源且不绕过正式术语审核。
- 已同步正式规格：
  - `openspec/specs/external-horse-name-recognition/spec.md`
  - `openspec/specs/termbase-and-race-priority/spec.md`
  - `openspec/specs/term-candidate-discovery/spec.md`
- 验证结果：
  - `DB_ENGINE=sqlite /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py check`：通过。
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py test stable.tests.TermResolverTests stable.tests.AutomationFlowTests stable.tests.TranslationWorkflowTests stable.tests.TermCandidateDiscoveryTests --noinput`：通过，49 项。
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py test stable.tests.TermResolverTests stable.tests.AutomationFlowTests stable.tests.TranslationWorkflowTests --noinput`：review 返修后通过，39 项。
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py test stable --noinput`：review 返修后通过，147 项。
  - `openspec validate use-external-horse-alias-for-name-recognition --strict`：通过。
  - `openspec validate --all`：归档前后均通过。
- 生产部署结果：
  - GitHub PR #6 `[codex] Use external horse aliases for name recognition` 已 squash merge 到 `main`，merge commit 为 `35b0866`。
  - 服务器 `/opt/umanewsbot` 已从 `817e1c8` 快进到 `35b0866`，部署前 `.env` 备份为 `.env.backup.external-horse-alias-20260625_182936`。
  - `./deploy_lowcost.sh` 执行成功，迁移显示 `No migrations to apply`，`collectstatic` 完成，`web` 容器 healthy，`worker / beat` 已重启。
  - 生产验证通过：`manage.py check` 无问题，`http://127.0.0.1/healthz/`、`http://umafans.run/healthz/` 和 `http://umafans.run/` 均返回 `200`。
  - 生产只读 smoke test：`ExternalHorseAlias` 数量为 `11521`；`recognize_horse_names("ロブチェンが出走", ...)` 返回 `ロブチェン`，来源为 `external_alias`，外部 horse ID 为 `2023107089`。
- 长文样本抽检：
  - 抽检方式：从生产只读导出 5 篇长文、2054 条启用正式术语和 11521 条 `ExternalHorseAlias`，写入本地临时 SQLite 后用当前未部署代码跑识别、候选发现和发布校验；未改生产数据。
  - 样本结果：netkeiba 长文中外部索引可命中多匹真实马名，例如 `ロブチェン`、`パントルナイーフ`、`ミクニインスパイア`、`ドリームコア` 等，并在译文未保留时产生独立 `external_horse_not_preserved` warning。
  - 观察到的后续优化点：JRA 活动公告类长文（例如 `JRA宮崎育成牧場けいばフェスタ`）仍会通过启发式把 `フェスタ`、`ウインズ`、`イベント`、`ポニー`、`オリジナル` 等普通片假名词列为疑似未知马名；外部马名索引能降低真实马名漏报，但不能完全替代后续普通词过滤和启发式收紧。
- 生产部署记录见 `docs/deploy_runbook.md` 的 `2026-06-25 外部马名索引识别链路生产部署`。

## 2026-06-25 国际赛马资讯扩展本地实现

- OpenSpec change：`expand-international-racing-coverage`。
- 当前状态：本地代码、迁移、测试、文档和 review 返修已完成；尚未部署生产，生产仍以已上线的日本新闻源和既有 QQ 推送配置为准。
- 已落地能力：
  - `NewsSource`、`NewsArticle`、外部数据缓存、`TermEntry`、`TermCandidate` 和 `PushTarget` 已增加地区、原文语言、来源类型或群级推送配置字段；现有数据默认回填为 `japan / ja`。
  - 内置来源同步已增加一期国际新闻源最终清单：`Sponichi`、`HKJC Racing News`、`SCMP Racing`、`Sporting Life Racing`、`Sky Sports Racing`、`BHA`、`France Galop English News`、`TDN France keyword`、`TDN`、`Horse Racing Nation`。新来源默认 `enabled=false`，需要人工启用或测试抓取；2026-06-26 review 返修后，内置来源同步只更新来源定义，不再覆盖工作人员手动调整的 `enabled` 状态。
  - 已补充排序型入口策略：类似 netkeiba 访问量榜/注目榜的来源，只有在公开 HTML/API 能稳定慢速抓取时才作为独立榜单源接入。本轮确认 `Sponichi 新闻ランキング`、`Sky Sports Racing Top Stories`、`Horse Racing Nation Trending` 可抓，均作为独立排序/榜单来源加入并保留原站 rank；2026-06-26 review 返修后，同源普通 list 不会覆盖已入库的排序/榜单主来源，普通 list 仍会记录 `NewsSnapshot`；旧候选 `At The Races`、`Paulick Report`、`BloodHorse` 因 403、反爬或空样本风险不进入第一版默认清单。
  - 公开首页新增 `综合 / 日本 / 中国香港 / 英国 / 法国 / 美国` 地区 tab，`/?region=<region>` 过滤头条、信息流和热门列表；地区页翻页会保留当前 `region` 查询参数，不会翻页后跳回综合流；文章详情展示地区、来源和原文语言。
  - 术语库 UI 和服务语义已从“日文原词/日文别名”扩展为“原文/原文别名/原文语言”，并新增 `TermAlias` 作为多语言原文别名表；`TermEntry` 表示正式术语概念和标准中文译名，旧 `source_ja / aliases_ja` 物理字段继续兼容并回填为 `ja` 别名。
  - 翻译、改写、发布校验、候选发现、自动标签和自动化评分会按文章 `source_language` 选择对应 `TermAlias`；日文片假名未知马名启发式只应用于 `ja`，英文和繁中不套日文规则，但会按同语言 `ExternalHorseAlias` 做保守外部马名匹配；英文候选可合并到日文正式术语概念并保存为英文别名。2026-06-26 review 返修后，术语匹配和自动化 P0 马匹命中会按本次候选术语批量加载 `TermAlias`，避免每条术语各查一次别名；英文/繁中外部马名识别会先从文章文本生成候选片段收窄数据库查询，并使用原文中实际出现的大小写/写法作为保护文本；翻译保护、发布校验和候选发现也统一使用真实匹配文本，英文正式术语按大小写不敏感方式命中并记录原文真实写法；最终 review 返修后，自动化 P0 马匹命中、发布校验的核心/背景术语判定、以及“新增术语后应用到当前稿”均复用同一套语言感知匹配，避免 `EQUINOX` 这类大写英文漏判或漏替换。本轮补丁进一步将同语言术语查重、别名去重、导入 upsert、候选合并和术语 API 保存统一为大小写不敏感；同语言大小写变体导入 upsert 会更新正式主原文并同步别名表，跨语言别名 upsert 仍只维护该语言别名、不覆盖概念主原文；后台/API 启停术语时会同步所有语言 `TermAlias` 的启用状态；AI 改写 prompt 的术语表也使用本次文章实际命中的 `matched_text`，避免英文稿看到日文概念主名而漏用标准译名。本次返修明确术语导入 upsert 的目标解析：主原文命中同一术语时才更新；如果只是原文别名命中已有其它术语，预览和提交都会拒绝该行，避免把两个正式概念误合并。
  - 自动化评分已补充英文和繁体中文赛马关键词表，英文 `preview / entries / draw / withdrawn / injury / results / stewards` 等信号会参与分类、高关注命中和重点赛事 fallback，不再只依赖日文关键词。
  - QQ 自动推送保留 `QQ_PUSH_ENABLED` 总开关；每个 `PushTarget` 可配置 `allowed_regions`、`push_scope`、`importance_strategy`。总开关管“能不能推”，群配置管“推什么给谁”；文章地区缺失时返回 `region_missing` 并不自动推送。2026-06-26 review 返修后，`importance_strategy=ranked` 不再只认 netkeiba，也会把 `Sponichi / Sky Sports Racing / Horse Racing Nation` 的排序/榜单稿视为重点新闻；已有群迁移会把空 `allowed_regions` 回填为 `["japan"]`，运行时空地区或非法地区配置也按旧行为仅允许日本，避免旧群或误配置群突然收到全球新闻。
  - HKJC 外部数据新增 `import_hkjc_external_data` 管理命令和 `HKJCExternalDataImporter`，支持 `--race-date`、`--race-id`、`--horse-id`、`--payload-file`、`--commit`、`--lookup-name`、`--stats-run-id`，默认 dry-run；提交只写 External* 缓存表和 `ExternalHorseAlias`，不生成前台赛果页。commit 模式在真实网络抓取实现前必须提供 `--payload-file`，并参考 netkeiba 外部导入使用单来源互斥锁，已有 `STARTED` 导入时拒绝并发写入；payload 超过 `max_races / max_horses` 时直接失败，不静默截断或部分写入。2026-06-26 review 返修后，`max_horses` 会合并统计顶层 `horses`、赛事 `entries` 和 `results` 中可识别的唯一马匹，避免 entries/results 里的大量马绕过批量上限。
  - 公开详情 URL 继续使用 `/news/<NewsArticle.id>/` 全局自增数字 ID；国际新闻源的 `source_article_id` 只作为来源内幂等去重键，使用完整 URL 派生的 `slug-short_hash`，避免同 slug 不同路径碰撞。
  - 国际新闻原始 HTML 只写入 `original_content_html`；`translation_metadata` 和 `NewsSnapshot.snapshot_metadata` 只保留轻量抓取/翻译元信息，不再重复保存整页 HTML；TDN 等列表 API 提供真实发布时间的来源，在详情页缺少日期节点时会回退使用列表时间；`TDN France keyword` 与美国 `TDN` 来自同一站点，入库时使用 `TDN` canonical source site 和同一 `source_article_id` 去重，`NewsSnapshot` 仍记录实际发现来源，法国关键词来源会优先保留法国地区归类。
  - 欧美数据库源 spike 结论已写入 `docs/global_racing_data_source_spikes.md`；本轮 spike 不加入 Celery Beat、生产命令队列或正式导入队列，不写正式外部数据表。
- 本轮新增迁移：
  - `server/stable/migrations/0011_remove_termcandidate_uq_term_candidate_type_normalized_and_more.py`
  - `server/stable/migrations/0012_termalias.py`
  - `server/stable/migrations/0013_alter_newsarticle_source_site_and_more.py`
- 本轮新增/调整的关键入口：
  - 新闻来源同步：`server/stable/services/sources.py`
  - 国际新闻适配器：`server/stable/adapters/international.py`
  - 国际新闻真实探测命令：`server/stable/management/commands/probe_international_news_sources.py`
  - QQ 群级推送判断：`server/stable/services/qq_auto_push.py`
  - HKJC 数据导入：`server/stable/services/external_hkjc_data.py`
  - HKJC 管理命令：`server/stable/management/commands/import_hkjc_external_data.py`
  - 公开首页地区 tab：`server/stable/views.py`、`server/stable/templates/stable/public/feed.html`
- 已完成的本地验证：
  - `openspec/changes/expand-international-racing-coverage/test_cases.md`：已新增完整测试用例矩阵，按 OpenSpec `proposal/design/spec` 拆分，不依据实现代码倒推；覆盖地区/语言、国际新闻源、公开首页、术语多语言、QQ 群级推送、HKJC 导入、欧美数据源 spike、迁移和非目标边界。
  - `DB_ENGINE=sqlite /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py check`：通过。
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py test stable.tests.AdapterTests stable.tests.InternationalSourceMetadataTests stable.tests.HKJCExternalDataImportTests stable.tests.AutomationFlowTests --noinput`：通过，35 项。
  - `DB_ENGINE=sqlite /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py test stable.tests.InternationalSourceMetadataTests stable.tests.QQAutoPushTests --verbosity 2`：通过，26 项。
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py test stable --noinput`：最终源清单返修前通过，201 项；返修后通过，209 项；2026-06-26 上线前 review 返修后通过，210 项；第二轮 review 返修后通过，214 项，新增覆盖人工来源启用保留、国际榜单来源提升、普通 list 不覆盖榜单主来源、QQ ranked 识别国际榜单稿；本次 review 补丁后通过，217 项，新增覆盖国际榜单来源提升后触发 QQ 自动推送编排、英文外部马名索引识别、术语导入 upsert 命中跨语言别名时保留正式概念主原文；术语批量别名和 HKJC 上限口径返修后通过，219 项；本轮全球范围适配 review 返修后通过，224 项，新增覆盖英文外部马名真实写法保护、非日文外部别名候选查询、旧 QQ 群空地区日本兼容、地区 tab 翻页保留过滤和英文赛马关键词评分；本轮 review 返修后通过，227 项，新增覆盖翻译保护使用英文外部马名真实写法、发布校验不误报已保留真实写法、英文正式术语大小写不敏感匹配与替换；最终 review 补丁后通过，231 项，新增覆盖英文 P0 马匹自动化评分大小写不敏感命中、英文核心术语缺失大小写不敏感阻断、新增英文术语应用当前稿大小写不敏感替换、QQ 群非法地区配置回退日本旧行为；本轮术语生命周期补丁后完整 `stable` 测试通过 236 项，新增覆盖英文重复术语大小写不敏感拒绝、API 创建/更新同步 `TermAlias`、术语启停同步别名状态、候选合并大小写去重、同语言大小写变体导入 upsert 更新主原文，以及 AI 改写 prompt 使用英文实际命中别名；本次上线前返修后完整 `stable` 测试通过 241 项，新增覆盖术语导入 upsert 原文别名冲突预览/提交双重拒绝、`TDN France keyword` canonical 去重并保留法国地区信号、以及术语列表分页保留原文语言筛选。
  - `openspec validate expand-international-racing-coverage --strict`：通过。
  - `openspec validate --all`：通过，9 项。
  - `git diff --check`：通过。
  - `DB_ENGINE=sqlite /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py makemigrations --check --dry-run`：通过，无额外迁移。
- 国际新闻源 dry-run 探测：
  - `DB_ENGINE=sqlite /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py probe_international_news_sources --limit 2 --json`：已执行，不写库。
  - 默认第一版矩阵成功解析两篇真实样本：`Sponichi latest/access`、`HKJC Racing News`、`SCMP Racing`、`Sporting Life Racing`、`Sky Sports Racing access/latest`、`BHA official`、`France Galop English News official`、`TDN France keyword`、`TDN`、`Horse Racing Nation access/latest`。
  - 榜单/排序入口结论：`Sponichi 新闻ランキング`、`Sky Sports Racing Top Stories`、`Horse Racing Nation Trending` 可抓并保留原站 rank；`HKJC Racing News`、`SCMP Racing`、`BHA`、`France Galop English News`、`TDN` 当前不按热门榜处理。
  - 旧候选源处理：`At The Races` 当前 403，`Paulick Report` 当前 403，`BloodHorse` 有反机器人/空样本风险；三者仍保留适配器供后续单独探测，但不进入第一版默认清单。
- 生产注意事项：
  - 本变更含数据库迁移，部署前必须确认没有正在运行的外部数据导入。
  - 国际新闻源默认关闭；生产启用前应先完成一次整体 review，再按地区逐个灰度启用，并用后台“测试抓取”或命令行小样本复验页面结构。
  - HKJC 正式网络导入仍应小批量、低频、单来源互斥，并从 `--payload-file --dry-run` 或单场小样本开始；如样本超过 `max_races / max_horses`，应先拆分 payload，而不是依赖程序截断。
