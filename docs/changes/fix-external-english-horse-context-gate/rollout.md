# 灰度、历史重判与发布边界

## 当前状态

- 本 change 已获实现授权并完成本地实现、测试先行及最后两项核心 P1 修复；rebase 后当前去重 333 项完整矩阵、77 项语言回归，以及 identity/security/N+1、article 9595、discovery field/span/context 专项均 GREEN。
- `git rebase --autostash origin/main` 已无冲突完成；当前 `HEAD` 与 `origin/main` 均为 `97a38cf5e2a692b7336c8518a4cdd6dfcc511d2a`，本 change 的未提交修改已恢复。
- rebase 后 Django check 通过，`makemigrations --check --dry-run` 返回 `No changes detected`，`git diff --check` 通过。
- 最新核心修复与 base 更新已产生新的 fingerprint；下一步是一轮新的独立只读 review，当前不得视为 review 已通过。
- article 9595 生产状态仍以先前只读证据中的 `published / auto_published` 为准；本轮未连接或写入生产，未修改文章、术语、通知或生产配置。
- 本分支不修改全局状态文档，避免与 `fix-news-body-extraction-boundaries` 和 AGENTS 工作流线程冲突。
- 发布继续冻结：独立只读 review 成功后仍须取得用户针对新 fingerprint 的明确发布确认；确认前禁止 commit、push、PR、merge、部署、历史重处理和生产写入。
- 两个非核心 B/P2 finding 已 deferred 到后续 change slug `fix-term-discovery-visible-occurrence-aggregation`：一是 raw HTML literal membership 可能遗漏 visible-text confirmed 候选，二是 raw `text.count` 可能放大同形但非 confirmed occurrence 的计数。本任务不实现，也不在此建立后续 change 的完整规格。

## 最新 reviewer finding 修复的 rollout 影响

- placeholder 修复仅改变同一字段中重叠 confirmed horse occurrence 的保护选择：最长完整名称获保护，内层短 alias 不再单独生成 placeholder；不存在数据库迁移或数据重写。
- discovery 修复只提高 finding audit 的 occurrence 可解释性，保存正文 field/span/context/classification/external IDs；不新增候选来源，不扩大 common/uncertain 的告警范围。
- structured evidence 修复把同一 surface 多次出现时的确认收窄到 occurrence-local strong/local relation；lexical-only 同形 occurrence 不再因同文 runner/result identity 广播而升级。唯一 occurrence 仍可由可信 structured identity 确认。
- committed replay 现在绑定 prepared、receipt 与 supplied reviewer identity；mismatch fail closed，同身份重放仍零写幂等。
- performance telemetry 现在按实际 entity-index source-language buckets 记录 ExternalHorseAlias/TermAlias/TermEntry 查询；2/20 篇 query 数恒定，100 篇总 SQL 预算仍为 `<=35`。
- proper-name horse noun 优先级仅覆盖首字母大写的马名候选紧邻 `filly/horse/colt/mare/gelding/stallion/broodmare/runner`；小写 `versatile filly` 等普通 adjective 继续降级，避免 over-upgrade。
- 非英文 discovery 在 resolver 未提供 context 时，从同一 resolved field/span 的 raw translation source 补齐局部上下文；不改写日文/繁中坐标，也不套用英文 visible-clean。
- 所有修复均已通过实时/batch/reprocessing/discovery 一致性、identity/security、query budget、日文/繁中/正式中文术语回归。
- visible-source 表示仅共享 validation 既有规则；未更改 source adapter、HTML extraction、正文提取器或清洗标签集合。
- 当前 worktree 已通过 `git rebase --autostash origin/main` 无冲突快进；
  `HEAD=origin/main=97a38cf5e2a692b7336c8518a4cdd6dfcc511d2a`。autostash 已恢复
  本 change 修改，因此必须基于当前完整 dirty worktree 重新生成 fingerprint
  并执行一轮独立只读 review；此前 review 结论不能替代本轮门禁。

## 阶段 1：新文章实时生效

代码部署与运行模式切换是两个门禁。部署后先在 shadow/audit 中比较旧/new classifications；只有专用测试、review、生产只读 smoke 和新授权全部通过，才允许让新文章的发布校验消费新结果。

验收：

- 单篇实时 translation/validation 使用同一 occurrence resolution；
- common/uncertain 不触发高价值 horse warning；
- confirmed horse 缺失仍 warning/blocker；
- `web/worker/beat` 运行配置一致。

## 阶段 2：历史文章 dry-run 重判

历史 dry-run 必须是显式范围、只读且可复现：

- 首先锁定 article IDs（至少 9595）和输入 fingerprint；
- 保存规则版本、settings hash、term/alias snapshot hash、代码 SHA；
- 输出 before/new gate issues、每 occurrence classification、external IDs、状态与 public/QQ ledger 快照；
- warning-only 或已 published 文章不得因现有默认 selector 被悄悄遗漏；使用显式 article/issue selector；
- dry-run 不调用 `apply_validation_outcome()`，不刷新 ready 时间，不发通知，不改公开和 QQ。

article 9595 预期：13 条普通词 horse warning 归零，Logician 保留 confirmed/formal evidence；当前 published 状态和公开时间不变。

## 阶段 3：历史状态更新

历史写入需在 dry-run artifact 人工审核、manifest SHA 锁定和新的生产写授权后单独执行。

- 未发布候选：只更新 gate audit/validation 状态；通过后最多恢复为正常候选，不直接公开、不创建 QQ delivery。
- 已发布文章（包括当前 9595）：只走独立 exact-ID audit-only apply，字段精确限于 `gate_issues`、`decision_reason.gate_issues`、`decision_reason.gate_issue_counts`、`automation_warning_email_signature` 和必要 `updated_at`；不得调用 `apply_validation_outcome()`，不得把状态退回 publish_ready、刷新 `publish_ready_at/ranked_revived_at`、重复发布或新增 QQ delivery。
- audit-only apply 不发送通知、不修改既有 `NotificationLog`；`workflow_status`、`automation_status`、review/risk、公开时间、译文和 QQ ledger 都必须由 verifier 证明不变。
- commit 前重新核对 article input、settings、term/alias snapshot 和 expected outcome；任何 drift fail closed。
- commit 后独立 verifier 对文章状态、公开时间、QQ ledger、NotificationLog 和 gate issues 做 before/after 对账。

## 阶段 4：生产发布

只有最新成功代码 review 后用户针对当前 fingerprint 明确授权，才进入仓库发布与生产部署。发布前执行工作流 fingerprint freeze；部署时核对服务器 HEAD、容器代码/镜像、配置一致性、队列安全边界、Django check 和 `/healthz/`。

生产顺序：

1. 代码发布但保持保守模式；
2. 小范围新文章 shadow/audit；
3. article 9595 和锁定样本只读 dry-run；
4. 人工抽检 common/uncertain/confirmed；
5. 用户另行授权后才允许 enforce 或历史状态写入；
6. 观察高价值 warning 数、confirmed horse 保留率、validation 时延和 SQL 查询数。

## 回滚

- 代码回滚恢复上一受审版本；若保留运行模式开关，先回到 shadow/off 并按既有服务重建流程执行。
- 本 change 预计无数据库迁移；普通代码回滚不恢复数据库。
- 若历史状态更新造成问题，只针对锁定 manifest 使用 before snapshot 恢复 gate audit fields；公开状态、发布时钟和 QQ ledger不得被覆盖。
- 回滚和任何生产写入均需独立授权，不与代码发布授权混用。

## 发布前禁止项

在当前阶段禁止 commit、push、创建 PR、merge、部署、数据库迁移、服务重启、历史重处理 commit 和任何生产数据写入。
