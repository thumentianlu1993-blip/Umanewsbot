# 当前状态

## 当前结论

项目当前已经完成正式域名 HTTP 接入修复，`umafans.run` 与 `www.umafans.run` 已可访问。  
“自动化内容运营 + AI 编辑改写 MVP”已完成代码侧与生产侧上线，当前处于上线后观察与质量抽检阶段。

仓库已于 `2026-06-06` 加入 OpenSpec + Codex 协作支持，用于在较大功能、跨模块改动、架构调整和生产高风险变更前先对齐规格，再进入实现。

OpenSpec change `add-term-candidate-discovery` 已完成实现、自动化测试、本地隔离环境浏览器验收，并归档为 `2026-06-06-add-term-candidate-discovery`；正式能力规格已同步到 `openspec/specs/term-candidate-discovery/spec.md`。

`2026-06-07` 已将术语候选发现部署到生产：服务器从 `7123e4e` 拉到 `e2e3e07`，应用迁移 `0006` 新建候选与证据表，`.env` 补入术语发现开关并保持 `TERM_DISCOVERY_ENABLED=false`（灰度，先关后开）。本次部署同时核实线上 `AUTOMATION_ENABLED=true`、`REWRITE_PROVIDER=siliconflow` 仍在生效。

仓库已明确长期语言约定：Codex 新增或维护的协作文档、OpenSpec 产物与代理说明默认使用中文；仅保留必要的代码标识符、命令和工具机器语法。

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
  - `.codex/agents/` 提供 `application / integration / operations` 领域代理与只读安全审查代理
  - `AGENTS.md` 已补充规格驱动开发与子代理使用约定
- 专有术语候选发现与待标注池已完成：
  - 支持马名、比赛名、骑手名和马主名发现
  - 支持候选去重、证据聚合、工作人员审核和安全写入正式术语
  - 已完成 69 项测试与本地浏览器功能验收
  - 生产默认关闭，等待灰度启用

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
- 自动化能力通过 `.env` 中 `AUTOMATION_ENABLED` 控制，当前已进入灰度运行与质量观察阶段
- 已核实线上 `AUTOMATION_ENABLED=true`、`REWRITE_PROVIDER=siliconflow`（真实 AI 改写在生效）
- 术语候选发现代码已部署到生产（`e2e3e07`，迁移 `0006` 已应用），`TERM_DISCOVERY_ENABLED=false` 默认关闭，等待单篇抽检后灰度开启

## 下一步优先级

1. 生产迁移已于 `2026-06-07` 完成；下一步在生产做单篇手动重新发现并抽检术语候选质量，确认后灰度启用 `TERM_DISCOVERY_ENABLED`
2. 观察自动化发布质量与 `AutomationLog`
3. 补充翻译 warning 可视化和术语库补全流程
4. HTTPS / 证书接入
5. 部署稳定化与监控 / 备份 / 回滚完善

## 当前已知风险与待确认项

- 当前正式域名阶段仍以 HTTP 为主，HTTPS 证书尚未接入完成
- 需要把 HTTP 阶段的临时安全配置，在 HTTPS 切换时重新收紧
- 需要继续确认抓取调度、翻译调度、发布链路在正式域名环境下的长期稳定性
- 自动化发布涉及内容安全，生产首轮建议低频、低批量、保守开关启用
- AI 改写真实效果依赖模型配置与术语库质量，需继续通过后台人工抽检
- 邮件通知首版已实现；短信 / QQ / 微信通知当前只保留日志与配置位，尚未接真实发送网关
- 需要补足更标准的部署基线、回滚与备份演练
- QQ Bot 实网联调与正式推送链路仍需单独验收

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
