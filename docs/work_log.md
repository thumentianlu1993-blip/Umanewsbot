# 工作日志

## 2026-06-06

### 项目：旧规格流程 + Codex 仓库协作支持

#### 已完成

- 安装并验证 旧规格流程 CLI `1.4.1`
- 使用 Codex 工具配置初始化 旧规格流程，生成 5 个 `旧规格流程-*` skills
- 基于真实 Django/Celery/Docker Compose 架构编写 `旧规格流程/config.yaml`
- 为 旧规格流程 tasks 增加 `application / integration / operations` 域路由
- 创建三个领域代理与只读 `security-scanner`
- 在 `AGENTS.md` 中增量加入 旧规格流程 / Codex 使用约定

#### 验证

- `旧规格流程 --version`：通过，版本 `1.4.1`
- `旧规格流程 list --json`：通过，当前无活动 change
- `旧规格流程 schema validate spec-driven`：通过
- 临时 change 的 `旧规格流程 instructions tasks --json` 已确认真实项目上下文与 5 条任务域规则会被注入
- 已确认生成 skills 未被手工修改，项目上下文无外部项目模板残留

### 项目：自动化术语候选发现规划

#### 已完成

- 创建 旧规格流程 change：`add-term-candidate-discovery`
- 完成 proposal、`term-candidate-discovery` capability spec、技术设计和 22 项领域路由任务
- 明确首版仅覆盖马名、比赛名、骑手名和马主名
- 明确候选与文章证据分层存储、规则优先识别、管理员确认后才能进入 `TermEntry`
- 明确不做历史全量回溯、复杂实体消歧、知识图谱和 AI 直接写入正式术语库

#### 验证

- `旧规格流程 validate add-term-candidate-discovery`：通过
- 旧规格流程 状态：全部 planning artifacts 完成，已达到 apply-ready
- 当前尚未开始应用代码实现

### 项目：仓库协作文档中文化

#### 已完成

- 将 旧规格流程 项目上下文和任务规则说明改为中文
- 将 Codex 自定义代理描述与指令改为中文
- 将 `add-term-candidate-discovery` 的 proposal、spec、design 和 tasks 说明性内容改为中文
- 在 `AGENTS.md` 与 `docs/decisions.md` 记录长期语言约定

#### 约定

- Codex 新增或维护的协作文档默认使用中文
- 命令、代码标识符和第三方工具要求的机器语法可以保留英文
- 上游自动生成且约定不手工修改的 旧规格流程 skills 保持原样

## 2026-05-17

### 项目一：自动化内容运营 + AI 编辑改写上线

#### 今日目标

- 将自动化内容运营 MVP 从本地代码推进到线上可用状态
- 打通自动评分、AI 改写、一致性校验、自动发布的生产链路
- 在保证可回滚的前提下，逐步提高自动发布吞吐

#### 已完成

- 完成自动化 MVP 代码提交并推送到 `main`
- 线上完成部署、迁移、容器重启与后台登录验证
- 修复后台管理员密码被容器启动脚本反复重置的问题：
  - 原因是 `.env` 中存在 `DJANGO_SUPERUSER_PASSWORD`
  - `start-web.sh` 每次启动都会执行 `seed_admin`
  - 处理方式是删除服务器 `.env` 中的 `DJANGO_SUPERUSER_PASSWORD`，再手动重置管理员密码
- 灰度启用 `AUTOMATION_ENABLED=true`
- 验证单篇文章自动化链路：
  - SiliconFlow 改写 API 返回正常
  - 文章可进入 `publish_ready`
  - `rewrite_title_zh / rewrite_summary_zh / rewrite_body_zh` 可生成
- 将自动发布策略调整为：
  - 常规时段每 15 分钟最多发布 4 篇
  - 每周日北京时间 13:00-16:00 每 15 分钟最多发布 10 篇
- 已完成相关代码、测试、文档更新并推送：
  - `feat: add automation operations mvp`
  - `fix: ignore generic racing words in horse detection`
  - `fix: tolerate control chars in rewrite json`
  - `feat: add peak auto publish batch limit`

#### 当前状态

- 自动化内容运营链路已经上线
- 自动发布批量规则已经改为常规 4 篇、周日重点窗口 10 篇
- 前台开始具备持续自动更新能力
- 仍建议继续人工抽检自动发布稿，尤其是重点赛事、长采访和含大量未收录马名的稿件

#### 风险与待观察

- AI 改写质量依赖模型稳定性、术语库覆盖率和 prompt 约束
- 自动发布虽然已通过校验，但仍可能存在表达风格、事实细节、术语覆盖不足等质量波动
- 周日高峰窗口发布量提高后，需要观察首页内容节奏和自动稿质量

#### 下一步建议

- 观察 1-2 个赛马日的自动发布效果
- 抽查 `AutomationLog` 中转人工原因，判断是否需要优化评分阈值
- 根据实际稿件质量决定是否补充风格样稿摘要规则

### 项目二：翻译稳定性与未知马名保护

#### 今日目标

- 解决大量文章因 `Translation response changed unknown horse names` 翻译失败的问题
- 确保未知马名不会阻断整篇新闻翻译

#### 已完成

- 排查确认原逻辑过于严格：
  - 系统会提取疑似未知马名
  - 如果模型没有在译文中原样保留这些名称
  - 连续重试后会直接抛出 `Translation response changed unknown horse names`
- 修复策略：
  - 翻译前将未知马名替换为 `__UMA_KEEP_n__` 占位符
  - prompt 明确要求模型原样复制占位符
  - 模型返回后系统自动把占位符还原为原始日文马名
  - 如果模型仍然漏保留未知马名，不再让整篇翻译失败，而是写入 `metadata.warning`
- 补充测试：
  - 未知马名占位符可正确还原
  - 模型仍漏保留未知马名时，翻译不失败，只记录 warning
- 已完成提交并推送：
  - `fix: do not fail translation on unknown horse names`

#### 当前状态

- 未知马名不再是阻断翻译的硬失败项
- 翻译链路会尽量保留未知马名原文，同时继续翻译剩余正文
- 相关 warning 会保留在翻译 metadata 中，后续可用于后台排查或术语库补全

#### 风险与待观察

- 疑似马名识别仍可能误判普通片假名词，需要继续通过停用词和上下文规则优化
- 如果模型完全删除占位符，系统会接受译文但记录 warning；这类稿件需要通过后续抽检发现
- 术语库覆盖率越高，未知马名保护压力越小

#### 下一步建议

- 后台增加“翻译 warning”筛选或提示，便于定位需要补术语的文章
- 定期从 warning 中提取高频未知马名，批量补充术语库
- 继续维护片假名停用词，减少普通词被误判为马名

### 项目三：专有术语候选发现与待标注池

#### 已完成

- 新增候选与证据模型、迁移、索引和唯一约束。
- 新增四类实体规则发现、正式术语去重、跨类型冲突和幂等证据聚合。
- 新增发现任务并接入新增文章入库旁路，失败不影响原有主链路。
- 新增工作人员候选审核后台、单篇重跑和操作日志。
- 新增接受、修改后接受、合并、拒绝、忽略及批量拒绝/忽略。
- 完成中文部署、后台和术语库说明。

#### 验证

- `DB_ENGINE=sqlite python manage.py check`：通过。
- `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable`：通过，69 项。
- `旧规格流程 validate add-term-candidate-discovery`：通过。
- 两种生产 Compose 配置基于 `.env.example` 检查通过。
- 使用 `/tmp/umanews-term-acceptance.sqlite3` 部署隔离测试环境，并通过浏览器完成完整后台审核流程。
- 浏览器验收中修复状态成功提示重复“已”和正式术语别名搜索不兼容 SQLite 的问题。

#### 当前状态

- 功能代码已完成，生产默认关闭。
- 下一阶段应先做单篇手动发现和候选质量抽检，再通过 `TERM_DISCOVERY_ENABLED=true` 灰度启用。
- 旧规格流程 change 已归档为 `2026-06-06-add-term-candidate-discovery`，正式规格已同步到主规格目录。

## 2026-06-07

### 项目：术语候选发现生产灰度部署

#### 已完成

- 将 `origin/main` 推进到 `e2e3e07`（含术语候选发现），服务器 `/opt/umanewsbot` 从 `7123e4e` 拉到 `e2e3e07`
- 迁移前备份：`.env.backup.20260607_033207` 与数据库快照 `backups/pre-0006-20260607_033207.sql`（74M，含 `PostgreSQL database dump complete` 标记）
- 应用迁移 `0006`，新建 `stable_termcandidate` 与 `stable_termcandidateevidence` 两张表（纯新增 `CreateModel` + 索引/约束，无破坏性操作）
- `.env` 追加术语发现开关并保持关闭：`TERM_DISCOVERY_ENABLED=false` / `TERM_DISCOVERY_PROVIDER=rules` / `TERM_DISCOVERY_MIN_CONFIDENCE=60`
- 用新镜像 `umanewsbot:prod` 重建并重启 `web/worker/beat`，`db/redis/nginx` 未动

#### 验证

- `showmigrations stable`：`0006` 已 `[X]` 应用（`web` 启动脚本 `start-web.sh` 启动时已自动迁移，显式 `migrate` 显示 `No migrations to apply`）
- `manage.py check`：0 issues
- `TermCandidate` / `TermCandidateEvidence` 计数 `0/0`（发现关闭，符合预期）
- 容器：`web/db` healthy，`worker/beat` up，`nginx/redis` 稳定
- `nginx → web` 返回 `200`；外网 `umafans.run` / `www.umafans.run` 均 `200`
- `worker` 近 200 行日志 0 报错
- 核对线上运行态：`AUTOMATION_ENABLED=true`、`REWRITE_PROVIDER=siliconflow` 未变更；生产数据库名 `horse_news`

#### 当前状态与下一步

- 术语候选发现代码已上线，生产默认关闭
- 下一步：在后台或 shell 做单篇手动重新发现，抽检候选质量；确认后再将 `TERM_DISCOVERY_ENABLED=true` 灰度开启，仅重启 `web` 与 `worker`
- 回滚：将 `TERM_DISCOVERY_ENABLED=false` 即可停用，无需回滚迁移或删除候选数据；如需整体回退可用 `.env.backup.20260607_033207` 与 `backups/pre-0006-20260607_033207.sql`

## 2026-06-27

### 项目：全球赛马数据库能力确认上线包整理

#### 已完成

- 用户将目标调整为：先保证香港、英国、法国、美国的数据爬取能力真实可用，不要求本轮真实爬取最近 60 天完整数据。
- 从 `origin/main` 创建干净上线基线，单独整理全球赛马数据库能力确认改造，避免当前本地大工作树里的 QQ、前台、compose 等旁支差异冲突。
- 复核四地管理命令入口：`import_hkjc_external_data`、`import_uk_external_data`、`import_france_external_data`、`import_us_external_data` 均具备 `--allow-network`、低频/限量、精确批次、dry-run 和受控 `--commit` 能力。
- 生产只读核对 HKJC：服务器 `/opt/umanewsbot` 当前为 `9ff667a`，`runtime/hkjc_import/` 中存在真实 dry-run 批次 JSON；有效批次合计覆盖 `130` 场、`1652` 条 entries/results/horses、`1783` 次请求，抽样为 `dry_run=true`、`would_write_formal_tables=false`、`completion.is_complete=true`。
- 复核 UK / France / US proof：`runtime/global_racing_import/proof-20260627` 中三地 proof 均有真实 `200` 响应、非写库 dry-run、非空 coverage，并通过 proof-only 审计。
- Review 当前文件改造必要性：四地 importer、fixtures、审计命令、batch command 渲染器、旧规格流程 规格和 `docs/global_racing_*` 属于本目标必要改造；QQ 推送、前台信息流、历史 archive、OneBot compose 端口等旁支差异不属于本目标必要范围。

#### 验证

- `stable.tests.HKJCExternalDataImportTests`、`UKExternalDataImportTests`、`FranceExternalDataImportTests`、`USExternalDataImportTests`、`GlobalRacingImporterCommitGateTests`、`GlobalRacingImportOutputAuditTests`、`GlobalRacingSpikeIsolationTests`：通过。
- `audit_global_racing_import_outputs --proof-only --fail-on-incomplete` 复跑 `runtime/global_racing_import/proof-20260627`：通过，`proof_ready=true`、`proof_blocking_reasons=[]`、`commit_candidate_ready=false`。
- `旧规格流程 validate --all`：通过。
- `git diff --check`：通过。

#### 生产部署

- 已将提交 `93b7007` 推送到 `main` 并部署到 `/opt/umanewsbot`。
- 部署前确认无 started import，HKJC/netkeiba 锁为空。
- `bash ./deploy_lowcost.sh` 成功，迁移显示 `No migrations to apply`，`web / worker / beat` 已重建。
- 部署后 `manage.py check` 通过，`healthz` 本地与公网均为 `200`，首页为 `200`。
- 生产命令入口和 proof-only 审计通过，未启动真实抓取或生产 `--commit`。

## 2026-06-30

### 项目：香港 HKJC 慢速真实 dry-run 启动

#### 已完成

- 按用户要求从香港开始尝试慢速抓取赛马数据库；本轮仍为 dry-run，不写正式表，不执行生产 `--commit`。
- 生产服务器 `/opt/umanewsbot` 当前为 `7b6e51b`，执行前确认 `web/db/redis` healthy、`worker/beat/nginx` 运行，`ExternalDataImportRun(status="started")=0`，HKJC/netkeiba 锁为空。
- 重新运行 HKJC 最近 60 天 plan-only：输出 `runtime/global_racing_import/hkjc-20260630/hkjc-plan-20260630.json`，`meetings=29`、`races=146`、`estimated_requests_without_horses=176`，拆为 `8` 批。
- 最新 plan 已不同于历史 `144` 场，因此旧的 `120/144` 停点不能直接作为续跑依据。
- 使用 `HKJC_IMPORT_REQUEST_INTERVAL_SECONDS=8` 和 `HKJC_IMPORT_MAX_REQUESTS_PER_RUN=100` 执行 `HK20260627ST02,HK20260627ST03` 精确小批 dry-run：输出 `runtime/global_racing_import/hkjc-20260630/hkjc-batch1-races-001-002-dryrun-20260630.json`。

#### 验证

- 小批结果：`dry_run=true`、`would_write_formal_tables=false`、`coverage_stats={"races":2,"entries":28,"results":28,"horses":28}`。
- `completion.is_complete=true`、`stop_reason=complete`、`unique_horses_found=28`、`horse_profiles_fetched=28`。
- 请求日志 `30/30` 均为 HTTP `200`，包含 `2` 个 race 页面和 `28` 个 horse profile 页面。
- 执行后 `ExternalDataImportRun(status="started")=0`，HKJC/netkeiba 锁为空，无 `umanewsbot-web-run-*` 临时容器残留。
- `http://umafans.run/healthz/` 与 `http://127.0.0.1/healthz/` 均返回 `200`。

#### 当前状态与下一步

- 香港 HKJC 慢速真实 dry-run 已证明当前生产网络、parser、race detail 与 horse profile 链路仍可用。
- 后续继续香港时，应按最新 `146` 场 plan 重新切批或从第 1 批剩余 race_ids 继续，不要沿用旧 `skip-races=120`。
- 生产 `--commit` 仍需要另行备份、锁检查、健康检查、完整批次审计和用户显式确认。

### 项目：香港 HKJC 慢速 dry-run 延伸到 2024-07

#### 已完成

- 用户要求保持抓取并慢速抓取到 `2024-07`；本轮继续坚持 dry-run，不执行生产 `--commit`，不写正式表。
- 生产运行长窗口 plan-only：`--start-date 2024-07-01 --end-date 2026-06-30 --plan-only --limit-races 20 --max-requests 600 --allow-network`。
- plan 输出：`runtime/global_racing_import/hkjc-20260701-to-202407/hkjc-plan-20240701-20260630.json`。
- plan 结果：`1496` 场、`75` 个 20 场批次、`254` 条请求日志，其中 `253` 条 HTTP `200`；最早进入 plan 的本地 HKJC 赛日为 `2024-09-08/09-11`，未见 `2024-07-01` 至 `2024-09` 之间的本地 `HV/ST` 场次。
- 已创建并启动生产后台 worker：`runtime/global_racing_import/hkjc-20260701-to-202407/run_hkjc_slow_dryrun_to_202407.sh`。

#### 运行配置

- PID：`runtime/global_racing_import/hkjc-20260701-to-202407/hkjc-slow-dryrun.pid`
- 状态：`runtime/global_racing_import/hkjc-20260701-to-202407/hkjc-slow-dryrun.state`
- 日志：`runtime/global_racing_import/hkjc-20260701-to-202407/hkjc-slow-dryrun.log`
- 输出：`runtime/global_racing_import/hkjc-20260701-to-202407/hkjc-mini-races-*-dryrun.json`
- 每批 `5` 场，`HKJC_IMPORT_REQUEST_INTERVAL_SECONDS=8`，`HKJC_IMPORT_MAX_REQUESTS_PER_RUN=140`，批次间暂停 `60` 秒。

#### 当前验证

- `races=3-7/1496`：输出 `hkjc-mini-races-0003-0007-dryrun.json`，`completion.is_complete=true`，`coverage_stats={"races":5,"entries":67,"results":67,"horses":67}`；有 `1` 次 horse profile 初始 `ReadTimeout` attempt，但最终补齐 `67/67` 个 profile。
- `races=8-12/1496`：输出 `hkjc-mini-races-0008-0012-dryrun.json`，`completion.is_complete=true`，`coverage_stats={"races":5,"entries":66,"results":66,"horses":66}`，`request_count=71`，`non_200_request_attempts=0`。
- 截至记录时 worker 已进入 `races=13-17/1496`。
- 生产健康检查正常，HKJC 与 netkeiba 锁未被正式写库路径占用。

#### 当前状态与下一步

- 让 worker 继续运行；它会在任一批次缺失 completion/coverage、最终未补齐马匹详情或命令失败时停止。
- 已恢复的 transient timeout attempt 仅记为 warning；最终 `completion.is_complete=false` 或 horse profile 缺口仍是停止条件。
- 不在 worker 运行期间做生产部署或重建容器；文档可先推 GitHub，生产工作树等抓取暂停后再同步。
