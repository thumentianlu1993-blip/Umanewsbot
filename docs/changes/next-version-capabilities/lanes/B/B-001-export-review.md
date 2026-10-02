# B-001 有界只读查询与脱敏导出方案

日期：2026-10-03，Asia/Shanghai。状态：提交审核的本地准备，全部 SQL/命令未在生产执行。
直接依赖 [采样方案](B-001-plan.md)；协调者已报告现有 SSH 连接恢复、docker ps 可读且8个容器可见；这是协调会话证据，不证明本线已查询 DB/样本。原 exit255 保留为瞬时失败，不要求用户处理访问、不修改权限。R通过后，具体命令/字段先交协调者技术核对，再用既有连接执行。

## 协调决定与标签状态

协调者指定 R 托管保留集及独立验收材料，B 负责 development 初标和漏斗/导出准备。
标签状态分三个独立字段，不能仅用 reviewed 表达：

| 字段 | 可用值 | 含义 |
|---|---|---|
| model_annotation_status | none / draft / disputed | 模型推断或建议；协调者、R 的模型判断也在这一栏 |
| machine_validation_status | not_run / passed / failed / unknown | 另一实现/进程进行的摘要、span、结构及证据一致性校验；不能证明领域事实正确 |
| human_verification_status | not_reviewed / verified / disputed / unknown | 只有真实人类实际核验可写 verified，并记录脱敏角色代号和证据；当前全为 not_reviewed |

另有 `evidence_resolution=resolved/unknown/disputed`。领域疑难先交协调者少量候选、出处区块和分歧；协调者基于证据作出的模型裁决记作模型裁决，不能生成 human gold。
机器或模型能做可复算答案时记录相应状态和输入，不要求现在让用户标全量 100 篇；没有真正人类核验的事实不称为人工 gold。

## 执行边界和预算

- 固定生产应用 SHA、实际 schema、T 与 start=T−28 天；时间传入 UTC ISO 8601，报告显示北京时间。
- 单次 PostgreSQL REPEATABLE READ READ ONLY 会话，事务最长 180 秒，单语句 15 秒，lock_timeout 1 秒，idle_in_transaction_session_timeout 15 秒。
  外部进程超时 180 秒强制终止，事务断开自然回滚；出错立即退出，不自动重复查询。
- `psql -X --set=ON_ERROR_STOP=1`，不加载 psqlrc；连接使用协调者既有连接环境，凭据不作为 CLI 参数、不输出。
  启动环境 `PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=15000 -c lock_timeout=1000 -c idle_in_transaction_session_timeout=15000'`。
  不运行 Django app startup、manage.py audit 或 service helper，避免未核验的启动/服务副作用。
- schema 探针仅查下表 7 张业务表列、相关迁移名与非敏感 server version，不查询 credentials、用户或 OperationLog 自由文本。
  缺字段、非 PostgreSQL、SHA/schema 不符、超时或连接失败立即停止并出 failed receipt。
- cohort 精确聚合不截断；明细最多 10,000 篇、来源最多 100 个、28 天 crawl/window 明细上限 20,000 行、候选决策上限 100,000 行、homepage exposure 上限 20,000 行。
  先计数，超过任一上限只保留精确聚合并报告 `detail_budget_exceeded`，不将截断明细当全分母；追加预算由协调者记录后重新审核。
- 候选原文索引最多每地区 200 篇、总计 1,000；从全量 cohort 元数据离线按失败40/非失败未公开40/其余120分层，不访问 API。
  缺层保留缺口，不偷偷换成只抽 published。真实事件分组/标签不足时追加候选需新 manifest。
- 内容导出只用协调者/R批准的明确 article ID 清单，≤150 篇；单篇 UTF-8 原文/HTML/译文总和≤512 KiB，整包≤30 MiB。
  超限保留 article ID/实际长度/原因，拒绝截断内容进入质量验收；文章仍留在漏斗，必要时协调者审核提高内容预算。

## 字段 allowlist

| 表 / 作用 | 可读取并导出的字段 | 不导出的字段 |
|---|---|---|
| stable_newsarticle / cohort | id, source_config_id, crawl_job_id, source_site, source_mode, racing_region, source_language, source_article_id, first_seen_at, published_at, published_at_verified, updated_at, workflow_status, crawl_status, translation_status, translation_error_category, translation_provider, translation_model, translation_retry_count, translated_at, automation_status, publish_ready_at, published_to_web_at, withdrawn_at, duplicate_of_id, score_total, quality_score | editor_notes, published_by_id, 邮件字段、error_message、全部 metadata/JSON 原样 |
| stable_newssource / 来源 | id, source_site, source_mode, racing_region, source_language, enabled, production_approved, deleted_at, effective_crawl_interval_minutes, last_crawl_status, last_crawl_at, last_error_category, failure_streak, backoff_until | notes, manual_pause_reason 自由文本、URL/账号信息、完整配置 |
| stable_crawljob / 来源尝试 | id, source_id, status, started_at, finished_at, success_count, fail_count | error_message；success_count 不擅自等同新增文章数 |
| stable_productionwindow / 窗口 | id, kind, racing_region, source_id, window_start, window_end, status, attempt_count, started_at, finished_at | target/scope、result_payload、reason_summary、last_error、triggered_by_id |
| stable_windowcandidatedecision / 选择 | id, window_id, article_id, status, reason, score, rank | payload 原样；reason 超128字符或带 URL/控制字符则替换 unknown 并计数 |
| stable_racenewsexposure / homepage账本 | id, article_id, event_id, channel, slot, status, activated_at, replaced_at；只筛 channel=homepage | QQ scope/target/delivery、reason/evidence 原样 |
| django_migrations / schema核对 | app, name，限 stable/app | 其他表和用户身份 |

原文阶段额外读取 `source_url,title_ja,body_ja_raw,body_ja_normalized,original_content_html,translated_title_zh,translated_body_zh,title_zh,body_zh,summary_zh`。
这些内容不送终端、不进入 Git、不进入未授权第三方。按原字节流计算摘要后再脱敏；原始 SHA 和脱敏 SHA 分列。
从 translation_metadata 只提取已核验路径的 selector/parse-status/清洗计数，JSON shape 未知则 unknown，不扩大读取到完整 payload。
公开 source URL 去掉 userinfo、query/fragment，若非 http/https 或包含可疑凭据则只存域名及 URL 摘要；canonical URL 缺失单列。
HTML 删除 script/style/表单控件/跟踪参数/账号区块，禁止将嵌入 token 带出；脱敏后保留正文区块相对顺序，并记录 block 到原内容 hash 的映射。
清洗误删判断需独立保管的原始 HTML；若脱敏损失了相关区块，标无法评价，不用缩水片段证明完整性。

## SQL 形状（审核输入）

以下是 psql 审核草案：范围固定28天，T由数据库事务时钟取得；全部查询在同一只读事务内执行。
start/cutoff 由同一事务的 transaction_timestamp() 固定，不使用任意历史时刻重建状态。列存在性先通过 information_schema 核对 allowlist。schema 不符不执行正文查询，不用动态拼接表名或用户 SQL。

```sql
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout = '15s';
SET LOCAL lock_timeout = '1s';
SET LOCAL idle_in_transaction_session_timeout = '15s';
SELECT current_setting('transaction_read_only') AS read_only,
       current_setting('transaction_isolation') AS isolation,
       transaction_timestamp() AS observed_at;

-- 同一事务固定边界，通过 psql gset 获取变量；不能由任意历史 cutoff 伪造状态。
SELECT transaction_timestamp() AS cutoff,
       transaction_timestamp() - interval '28 days' AS start
\gset
-- :start / :cutoff 使用 :'name' 引用。
WITH cohort AS (
  SELECT racing_region, source_site, source_mode, workflow_status,
         translation_status, translation_error_category, automation_status,
         body_ja_raw, body_ja_normalized, original_content_html,
         published_to_web_at, withdrawn_at, duplicate_of_id
  FROM stable_newsarticle
  WHERE first_seen_at >= :'start'::timestamptz
    AND first_seen_at < :'cutoff'::timestamptz
    AND racing_region IN ('japan','hong_kong','united_kingdom','france','united_states')
)
SELECT racing_region, source_site, source_mode, workflow_status,
       translation_status, translation_error_category, automation_status,
       count(*) AS article_count,
       count(*) FILTER (WHERE body_ja_raw = '' AND body_ja_normalized = '') AS empty_body,
       count(*) FILTER (WHERE original_content_html = '') AS missing_html,
       count(*) FILTER (WHERE published_to_web_at IS NOT NULL) AS ever_public,
       count(*) FILTER (WHERE workflow_status = 'published'
                          AND published_to_web_at IS NOT NULL
                          AND withdrawn_at IS NULL) AS current_public,
       count(*) FILTER (WHERE duplicate_of_id IS NOT NULL) AS duplicate_linked
FROM cohort
GROUP BY racing_region, source_site, source_mode, workflow_status,
         translation_status, translation_error_category, automation_status
ORDER BY racing_region, source_site, source_mode, workflow_status,
         translation_status, translation_error_category, automation_status;

-- 独立抓取尝试分母；保留已删除/停用来源和 NULL source 的失败。
SELECT s.racing_region, s.source_site, s.source_mode, j.status,
       count(*) AS attempts, sum(j.success_count) AS reported_success,
       sum(j.fail_count) AS reported_failure
FROM stable_crawljob j LEFT JOIN stable_newssource s ON s.id=j.source_id
WHERE j.started_at >= :'start'::timestamptz
  AND j.started_at < :'cutoff'::timestamptz
GROUP BY s.racing_region, s.source_site, s.source_mode, j.status
ORDER BY s.racing_region, s.source_site, s.source_mode, j.status;

-- 选择事件流，可包含更早入库文章；同篇重复窗口单列，不能加到 cohort 篇数。
SELECT w.racing_region, w.kind, w.status AS window_status,
       d.status AS decision_status, count(*) AS decisions,
       count(DISTINCT d.article_id) AS distinct_articles
FROM stable_productionwindow w
JOIN stable_windowcandidatedecision d ON d.window_id=w.id
WHERE w.window_start >= :'start'::timestamptz
  AND w.window_start < :'cutoff'::timestamptz
  AND w.kind='publish'
GROUP BY w.racing_region, w.kind, w.status, d.status
ORDER BY w.racing_region, w.kind, w.status, d.status;

-- 暂不关闭事务：同一会话继续预算计数、明细和批准ID内容读取，再 COMMIT。
```

其余查询使用相同 start/cutoff：

1. cohort count/group-by-region；预算通过后 metadata 额外包含 updated_at、三类内容 octet_length 和 SQL 计算的 input_sha256：`encode(sha256(convert_to(title_ja || E'\n' || COALESCE(NULLIF(body_ja_normalized,''),body_ja_raw,''),'UTF8')),'hex')`。先核验当前 PostgreSQL 内置 sha256(bytea) 可用，不安装扩展；不可用则停止该导出。它只导出摘要，不输出原文。全存量 status 分组另列 `dataset=inventory_at_T`，不混入 cohort。
2. NewsSource allowlist；CrawlJob count 后明细；窗口即使无 candidate 也必须独立输出，避免内连接隐藏 no_ready_candidates 窗口。
3. candidate cohort 状态 LEFT JOIN：以固定 cohort article 为左表，关联该时段 publish window 的 decisions；无记录输出 none，唯一文章和多窗口决定数分列。
4. homepage exposure 以 cohort 为左表，按 channel/status distinct article 统计，同时输出无记录数；activated_at 在窗口内的事件流另报。
5. 配置证据由协调者既有受审只读入口提供 allowlist 有效 settings JSON；本计划不新建通过 Django startup 取配置的未经审核命令。已定位当前 settings.py:1130 在 LOG_DIR 非空时会 mkdir，直接 import 并非无条件无副作用。只读取容器 allowlist env 加核验默认值时标 config_source=env_plus_code_defaults，并保留 effective_settings_verified=false，不冒称常驻进程有效配置。

明细 SQL 只显式列字段，不 SELECT * 导出；不通过字符串拼接输入 ID：受审 exporter 使用参数化 `WHERE id = ANY(%s::bigint[])`，显式长度上限与去重。
正文导出必须待 R 审核后形成独立实现提交。
全流程不创建临时表，不持有 FOR UPDATE，不执行函数 apply/nextval，不读取 Redis，也不把 Postgres 当前状态称为历史 T 精确状态。

## 时刻一致性限制

T 是实际只读事务 observation 时刻，start 从它派生；不能用今天数据库状态伪造任意历史 cutoff 的全状态快照。
内容选择可能需第二次只读事务：metadata 快照先交协调者/R；从五地区分层候选选最多150个明确ID，导出程序直接将原文落专用受控runtime路径，只返回计数/哈希给B，不将公共原始内容回传B模型。R/协调者独立查看/分组/划分和托管后，仅解封development给B。B不得读取完整原始包、保留集原文或标签。
第二次读取必须匹配首次的每篇 input SHA 和 updated_at；任一漂移记录 stale_input 并停止冻结该篇，不以新内容覆盖旧标签。
两次 observation 分别标记；历史 cohort 与最新配置不在同一时刻时显式记录差值，不能声称绝对一致。

## 产物路径与验证

协调者使用专用受控 runtime 目录 `runtime/next_version/F02/<observation-id>/`，新目录不覆盖旧包；权限0700、文件0600。
这只是文件产物，不调用生产发布/数据写入流程；目录实际根和只读连接由协调者提供，不写其他开发工作树。

- `receipt.json`：app SHA/schema、T/start、只读会话设置、查询/导出版本 SHA、行/字节上限、实际数、退出状态与缺口；不含 DSN。
- `funnel_aggregates.json`、`cohort_metadata.jsonl`、`sources.jsonl`、`crawl_jobs.jsonl`、`windows.jsonl`、`decisions.jsonl`、`homepage_exposures.jsonl`：只含 allowlist。
- `effective_config.json`：allowlist 生产值与取得时间/SHA，未知保持 null；不输出 API key/base URL/token/完整 env。
- `development/`：B 可消费的经批准开发原文与草标；`holdout_commitment.json`：只含 R 托管计数和摘要。
- `holdout_access_consumption.jsonl`：由 R 在受控路径维护访问/协议/版本/消费账本；B 只收状态与汇总。M11 之后原文、标签和逐篇输出仍留 R，不解封给 B。
- 保留原文/标签不放 B 树，R/协调者使用单独访问控制目录；仅“放 R worktree”不是物理访问隔离，默认靠读取约定防上下文泄漏，需更强隔离时由协调者提供受限存储。
- `manifest.json`：逐文件 SHA256、输入/脱敏摘要、计数、schema与标签版本；原始保留集摘要只由 R 计算并输出承诺。

验证按以下次序 fail closed：字段/schema → 只读设置 → 预算 → 聚合/明细对账 → article ID/状态覆盖 → 输入摘要/漂移 → 脱敏扫描 → group/split交叉检查 → 标签状态来源 → manifest。
所有地区聚合之和必须等于精确 cohort 数；明细超预算时 `complete=false`，不能出完整基线收据。
检查至少200候选/地区的可用性与真实失败/未公开层；不足按实际值报，类别未知不伪造。
运行终止或任何检查失败不冻结 fixture、不给 M01 完成证明。当前这份文档只通过本地字段/引用检查，无生产执行证据。

M11 评估接口继承 [采样方案的最终保留集消费合同](B-001-plan.md)：R 在代码/模型/提示词/配置与评分协议冻结后独立执行，B 只收 allowlist 汇总。
反馈用于进一步调参或逐篇内容泄漏时标 consumed；同集之后只出非独立回归结果，新版本的独立结论必须来自未消费且无事件泄漏的另一个集合。
此规则不授权新增抓取/真实模型调用；所有内容交接直接进入 R 托管路径，B 不先读全集。

## 执行命令包草案（仍未执行）

技术核对时先绑定实际容器ID、标签image/revision、数据库/schema与受审脚本SHA；目前不猜容器名或数据库账号。

```sh
# 第一步仅发现既有容器，受审执行阶段由协调者确认唯一 resident web/db ID。
ssh -o BatchMode=yes -o ConnectTimeout=8 umanews \
  'docker ps --format "{{.ID}} {{.Names}} {{.Image}} {{.Status}}"'
# 精确绑定后只读 inspect 的 format 仅列选定 identity 字段，禁止 docker inspect 原样/env全量。
docker inspect --format '{{.Id}} {{.Image}} {{index .Config.Labels "org.opencontainers.image.revision"}}' <bound-web-id>
# 数据库查询形状：在已绑定db容器中，通过现有环境读取POSTGRES_USER/DB，不打印它们；不含密码参数。
# <reviewed-query.sql> 由协调者同一只读连接传stdin，无远端业务文件修改。
docker exec -i <bound-db-id> sh -c \
  'PGOPTIONS="-c default_transaction_read_only=on -c statement_timeout=15000 -c lock_timeout=1000 -c idle_in_transaction_session_timeout=15000" psql -X --set=ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" --file=-' \
  < <reviewed-query.sql>
```

上面带尖括号的是绑定合同占位符，禁止原样执行。执行前出具体命令文件及SHA供协调者核对；真实SSH目标、容器ID、超时wrapper与runtime绝对路径齐备后才有可执行包。
元数据可以通过只读stdout直接由程序落本线/协调者专用runtime文件，工具只显示receipt计数/哈希；原文由独立托管路径接收，禁止text()/stdout直接展示。
本地当前只准备文档，没有生成可执行导出器；R审方案通过后实现并做离线fixture验证，先发命令包再进行真实只读执行。
