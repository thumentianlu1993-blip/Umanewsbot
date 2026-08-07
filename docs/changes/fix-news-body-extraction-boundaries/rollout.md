# 新闻正文提取边界发布与历史处理方案

## 当前状态

未 commit、push、建 PR 或部署。当前 GREEN 不授权 Gate A–D 的任何生产动作。

## Gate A：此前从未入库的全新文章采集修复

### 生效范围

- 代码会收紧所有后续 HRN 详情解析，但 Gate A 的公开修复验收只覆盖此前从未入库的新文章。
- 既有文章的重复抓取即使更新原文层，也不会常规重译/改写，`effective_body` 仍可能优先旧中文稿；因此所有
  部署前既有 HRN 文章继续属于 Gate B/C，不得以重复抓取冒充公开修复。
- 不修改来源启停、抓取频率、翻译模型、自动发布策略、QQ 策略或公开模板。
- 部署本身不主动更新历史文章。

### 发布前

2. 用同一 scope 重算 fingerprint，显式 stage 后验证 index 内容与 approved content hash 一致。
3. 核对生产 HEAD、web/worker/beat 镜像、HRN source 配置、Celery active/reserved/queue。
4. 建立 `.env` 与 PostgreSQL 备份并验证可读；本变更无迁移。

### 发布后验收

1. Django check、migration drift、web/worker/beat 镜像一致、内外 `/healthz/`。
2. 一个此前从未入库的新 HRN 页面解析元数据为 `body_selector=.article-body`、`body_parse_status=ok`。
3. 新稿 `body_ja_raw/body_ja_normalized` 无页面框架，首尾和结构文本完整。
4. 翻译/改写输入与 `effective_body` 无框架污染；真实公开详情 200。
5. 若选择器失败或正文为空，确认 upsert 前已拒绝：不创建/更新文章或 snapshot、不派发术语/翻译，且来源/CrawlJob 有可见失败证据。

### 回滚

- 暂停 HRN 来源或其自动发布资格，排空相关 worker 动作。
- 恢复部署前镜像/commit，重建 web/worker/beat 并验证 healthz、队列和来源状态。
- 因旧代码仍存在宽泛 `main` 风险，在修复版恢复前不得重新开启 HRN 自动发布。

## Gate B：历史文章识别（只读）

### 目的

确定所有保存了 HRN 原始 HTML 的文章中，哪些在新可信容器规则下正文发生变化、缺少 HTML 或结构已漂移。

### 执行边界

- 必须与代码部署分开授权和记录；默认只读。
- 部署/重抓前冻结既有 HRN `max_id`；使用明确 `source_site`、`after_id`、`max_id`、`limit` 分批稳定扫描，
  scope 包含全部部署前 HRN 文章，不触网、不翻译、不改写、不发布、不发 QQ。
- 每批保存 JSON 与 SHA-256，记录生产 HEAD/镜像、选择范围、文章总数和 changed/missing/failed/unchanged 分类。
- 报告只含状态与哈希，不复制完整 HTML、正文或秘密。

### 审核

- 首批必须人工查看 `9623`、`9519`、一个未发布候选和一个正常反例的原文/新解析首尾。
- 人工正文、机器改写、翻译失败或缺少 HTML分别进入不同决定，不允许“一键全部重译”。
- 识别完成不改变生产状态，也不构成重处理授权。

## Gate C：历史文章重处理（生产写入）

### 前置条件

- 全量历史 scope 已分类，精确 schema v2 批准 manifest 及 manifest file SHA 已审核；legacy v1 不可用于写入。
- 当前代码/运行镜像仍与识别版本一致；文章 HTML/旧正文/有效正文哈希未漂移。
- 取得用户针对精确文章批次和动作的明确历史重处理授权。
- 完成可读备份、队列安全窗口和回滚准备。

### 分层处理

1. 对批准文章运行 manifest-bound repair dry-run；逐篇核对新正文首尾、结构和哈希。
   dry-run 还必须提供 schema v2 的 `after_title_sha256`、`after_body_normalized_sha256` 和
   `after_parse_metadata_sha256`，禁止从旧 v1 artifact 推断这些输出。
2. commit 必须提供 schema v2 批准 manifest + file SHA；在单一事务锁定全部目标行后校验文章集合、
   `updated_at`、HTML、旧正文，以及将持久化的标题、raw/normalized 正文和 canonical parse metadata 哈希，
   任一缺字段或漂移整批零写入、零 OperationLog。
3. 原文层 commit 只更新 `title_ja/body_ja_raw/body_ja_normalized` 与审计元数据。
4. 中文层按文章实际有效字段处理：
   - 普通机器翻译稿：同步强制翻译；
   - 机器改写稿：显式重跑/替换旧改写后再验证 `effective_body`；
   - 人工正文：默认不覆盖，交人工编辑决定。
5. 每篇验收公开页面、后台字段、`effective_body`、workflow、发布时间和 QQ delivery。

### 禁止事项

- 不重新调用发布动作，不刷新 `published_to_web_at`。
- 不创建新文章或新 QQ delivery。
- 不用 SQL/模板按已知中文词删除脏内容。
- 不因一篇失败继续接受同篇部分写入；失败篇保留证据并停止。

## Gate D：生产部署

代码部署只修复新解析；历史识别与历史重处理均不是部署附带动作。每一道生产写入门禁都需要在对应最新
review 后取得当前版本/当前批次的明确用户授权。任何受审内容变化都会使旧 review 和旧授权失效。

## 证据回写

- 仅当相应动作真实发生后，更新 `docs/current_state.md`、`docs/project_status.md`、
  `docs/deploy_runbook.md` 和本任务 `release_report.md`。
- 发布后 evidence-only patch 必须遵守 `docs/codex_workflow.md` 的文件 allowlist 和同一 code reviewer
  会话复审要求；不得夹带代码、测试、配置、迁移、spec/tasks 或治理变化。
