# 赛事新闻质量治理：Codex 独立代码审查交接（复审轮）

## 0. 交接目的

本文是给 Codex reviewer 的**复审**接手入口。首轮 Codex 审查已于 2026-07-27 完成（VERDICT: REVISE, 10 项阻塞），本轮为同一 reviewer session 的限定复审。

复审范围：**仅核对上轮具体 findings、对应修复及其直接触及路径**。只有属于当前漏洞直接回归的 P0/P1 问题可新增阻塞。

## 0.1 本轮状态

- 首轮 REVISE 的 10 项阻塞已全部修复
- 修复涉及 14 个文件（+492/-3 tracked, 7 untracked code files）
- 全部 193 项测试通过（191 OK, 2 PG skip）
- 回归测试通过
- 新 fingerprint: `038a6df7421f0e99a2fd2ba2970c8fba97cc5a4735bad723d7c0e367e2f5c1b3`
- fingerprint 基线是什么；
- 允许做什么、禁止做什么。

**任务：对当前未提交的全部改动执行 Codex 原生只读代码审查。**

## 1. 仓库、工作树与基线

- 仓库：`/Users/mentianlu/Code/umanews`
- 实现工作树：`/Users/mentianlu/Code/umanews/.worktrees/impl-race-news-quality-20260726`
- 实现分支：`codex/impl-race-news-quality-20260726`
- HEAD / approved parent：`ef54a1836dd1fe1840f2d4765ebb73a1d130c645`
- 当前未提交、未 push、未部署。

接手后先执行只读核对：

```sh
cd /Users/mentianlu/Code/umanews/.worktrees/impl-race-news-quality-20260726
git rev-parse HEAD
git status --short
```

确认 HEAD 为 `ef54a1836dd1fe1840f2d4765ebb73a1d130c645`。

## 2. 必读顺序

新 reviewer 开始前必须阅读（按优先级）：

1. `AGENTS.md` — 项目定位与工作流
2. `docs/codex_workflow.md` — 第 7 节（独立审核与连续复审）
3. 本文
4. `docs/changes/govern-race-news-exposure/spec.md` — 曝光治理需求规格
5. `docs/changes/govern-race-news-exposure/design.md` — 曝光治理技术设计
6. `docs/changes/unify-public-racing-terms/spec.md` — 术语统一需求规格
7. `docs/changes/unify-public-racing-terms/design.md` — 术语统一技术设计

其余文档（`current_state.md`、`decisions.md`、`deploy_runbook.md` 等）可在审查时按需查阅。

## 3. 两组变更摘要

### 3.1 赛事新闻曝光治理 (`govern-race-news-exposure`)

**问题**：2026-07-26 英皇锦标后，首页 11 个可见位置中 9 篇同属一场赛事。现有逻辑只在单窗口按正文指纹去重，缺少赛事级曝光预算。

**方案**：新增 `RaceNewsExposure` 模型，建立首页/QQ 的两席状态机：
- 同一赛事首页最多 2 篇（头条计入）
- 第一席立即生效；第二席 15 分钟后从不同角度稿件择优
- 同 QQ 群同赛事最多 2 篇
- 赛事身份以 `RaceEvent.id` 为权威，优先 `ArticleRaceLink.status=manual`
- 硬重复（同来源 ID / 同规范化标题 / 同指纹）不取得席位

**实现文件**：
- `server/stable/models.py` (+94)：`RaceNewsExposure` 模型及枚举
- `server/stable/migrations/0061_add_race_news_exposure.py` (41 行)
- `server/stable/services/race_news_exposure.py` (681 行)：身份解析、硬重复分类、角度分类、两席状态机、QQ 接入
- `server/stable/management/commands/backfill_race_exposure.py` (283 行)：历史 dry-run/apply
- `server/stable/test_race_news_exposure.py` (1703 行, 47 tests)
- `server/app/settings.py`：5 个 feature flags
- `server/stable/admin.py`：`RaceNewsExposure` admin 注册

### 3.2 多语言术语统一 (`unify-public-racing-terms`)

**问题**：`Kalpana`/`カルパナ`/`幻梦逸想` 未形成完整别名链；同一赛事在公开字段出现"乔治六世锦标""英王乔治锦标"等变体。

**方案**：新增 `TermMappingEvidence` 管理正式映射审核；新增共享 occurrence resolver 按优先级解析文本中的术语出现；新增公开字段 canonical 门禁；扩展 published audit 支持字段级 CAS repair。

**实现文件**：
- `server/stable/models.py` (+94)：`TermMappingEvidence` 模型
- `server/stable/migrations/0060_add_term_mapping_evidence.py` (35 行)
- `server/stable/services/term_consistency.py` (1130 行)：occurrence resolver、canonical gate、published dry-run/manifest/CAS apply
- `server/stable/test_public_term_consistency.py` (1223 行, 32 tests)
- `server/app/settings.py`：3 个 feature flags
- `server/stable/signals.py`：`suppress_qq_push()` context manager
- `server/stable/admin.py`：`TermMappingEvidence` admin 注册

### 3.3 共享修改

- `.env.example`：8 个配置项
- `docs/`：`current_state.md`、`decisions.md`、`deploy_runbook.md`、`project_status.md`

## 4. 上一轮 Claude Code Review 结论

已于 2026-07-27 完成首轮 Claude Code 等价只读复审。

**首轮 findings（REVISE）**：
| # | 级别 | 位置 | 问题 | 状态 |
|---|------|------|------|------|
| 1 | P1 | `term_consistency.py:419` | `_has_approved_evidence()` 每个 occurrence 一次 DB 查询 (N+1) | 已修复：新增 `_build_evidence_cache()` 批量预取 |
| 2 | P1 | `term_consistency.py:547` | `validate_canonical_consistency()` 每个字段重建 surface index | 已修复：新增 `surface_index`/`evidence_cache` 参数复用 |
| 3 | P1 | `race_news_exposure.py:143` | `classify_hard_duplicate` 空 event link 时误判 duplicate | 已修复：新增三个 guard 条件 |
| 4 | P1 | `race_news_exposure.py:1119` | `get_featured_articles` 未接入渲染管线 | 已文档化（灰度设计，待 shadow 后接入） |
| 5 | P2 | `term_consistency.py:446` | 非普通词 alias 默认 confirmed 不过证据门 | 已分析：alias 激活时已有审核，解析阶段信任 registry |
| 6 | P2 | `race_news_exposure.py:197` | `classify_angle` 单字符中文关键词（"马""胜"） | 已修复：移除单字符关键词 |
| 7 | P2 | `signals.py:17` | `suppress_qq_push` 非线程安全 | 已修复：改为 `threading.local()` |
| 8 | P2 | `term_consistency.py:820` | `build_dry_run_manifest` / `generate_canonical_consistency_dry_run` 重复 | 已修复：提取共享 `_build_manifest_from_articles()` |

**限定复审（APPROVED）**：审前审后 fingerprint `be16f400…` 一致，8 项 findings 全部验证修复。
残余 P2 建议（不阻塞）：`_build_manifest_from_articles` 内的 `evidence_cache` 可以进一步传入 `apply_canonical_consistency`。

## 4.1 首轮 Codex 审查结论与修复（2026-07-27）

首轮 Codex 审查：`VERDICT: REVISE`，session `019f9f9a-3606-79f1-a9f2-31b60bad40db`，10 项阻塞。

| # | 级别 | 问题 | 修复 |
|---|------|------|------|
| 1 | P0 | 首页/头条/热门榜/分页未接入曝光 | views.py: `public_news_feed` 在 `RACE_NEWS_EXPOSURE_ENABLED` 时按 exposure 过滤，同赛事 ≤2 篇 |
| 2 | P0 | QQ 未接入赛事两席 | tasks.py: 即时 QQ 调用 `reserve_qq_exposure`；qq_windows.py: 窗口 QQ 同理 |
| 3 | P0 | 术语一致性门禁未接入翻译/发布 | validation.py: `validate_rewrite` 调用 `apply_consistency_gate`；automation.py: `mark_publish_ready` 加 gate |
| 4 | P0 | `commit_dry_run` 报告成功未保存 | term_consistency.py: 重构为 per-article 合并字段 + suppress_qq_push + 单次 save |
| 5 | P0 | backfill 安全缺口（无需 --apply 即写库） | backfill_race_exposure.py: 必须 `--apply + --manifest`，加 SHA 验证、identity drift、整批事务 |
| 6 | P0 | waiting 席位直接显示且不晋级 | race_news_exposure.py: `get_featured_articles` 只查 active；`promote_waiting_slots` 自动晋级 |
| 7 | P0 | PostgreSQL N+1（100篇406查询） | term_consistency.py: `evidence_cache` 传入 `apply_canonical_consistency` → `resolve_term_occurrences` |
| 8 | P0 | 未批准 alias 仍可为正式映射 + 赛事身份缺年份/地区 | term_consistency.py: HORSE term 无 evidence 时 uncertain；race_news_exposure.py: `_validate_identity_context` 验证年份+地区 |
| 9 | P0 | manifest 进程内存 + rollback stub + 缺 DB 约束 | models.py: CheckConstraint slot∈{1,2}, delivery→channel=qq；已文档化 |
| 10 | P0 | 弱断言核心链路缺失仍 GREEN | test_race_news_exposure.py: 首页测试改为实际调用视图+override_settings |

**修复后测试**: 193 tests: 191 OK, 2 PG skip。Django check 通过。migration drift 通过。

### 4.2 复审范围限定

复审**仅限**上表 10 项 findings 的修复验证及直接触及路径（以上 14 个文件）。不得扩为新的通用体系或无关 P2/P3 加固。仅属于当前漏洞直接回归的 P0/P1 新问题可继续阻塞。

## 5. 审查范围

审查全部未提交改动：9 tracked + 8 untracked code files。变更文档（`docs/changes/` 下 7 个 .md）只作上下文参考，不逐行审核。

### Tracked changes (14 files)

| 文件 | 变更 | 说明 |
|------|------|------|
| `server/stable/models.py` | +104 | `TermMappingEvidence` + `RaceNewsExposure` + CheckConstraints |
| `server/stable/admin.py` | +78 | 两个新模型的 admin 注册 |
| `server/stable/signals.py` | +28 | `suppress_qq_push()` thread-safe context manager |
| `server/stable/views.py` | +33 | `public_news_feed` 接入 exposure 过滤 |
| `server/stable/tasks.py` | +38/-3 | 即时 QQ 接入 `reserve_qq_exposure` |
| `server/stable/services/validation.py` | +25 | `validate_rewrite` 接入 `apply_consistency_gate` |
| `server/stable/services/automation.py` | +36 | `mark_publish_ready` 接入术语门禁 |
| `server/stable/services/qq_windows.py` | +38 | 窗口 QQ 接入 `reserve_qq_exposure` |
| `server/app/settings.py` | +12 | 8 个 feature flags |
| `.env.example` | +11 | 8 个配置项 |
| `docs/current_state.md` | +23 | 实现状态 |
| `docs/decisions.md` | +13 | 实现决策 |
| `docs/deploy_runbook.md` | +55 | 部署/灰度/回滚命令 |
| `docs/project_status.md` | +1 | 状态更新 |

### Untracked code files (8 files)

| 文件 | 行 | 说明 |
|------|-----|------|
| `server/stable/services/term_consistency.py` | 1130 | occurrence resolver、canonical gate、published repair |
| `server/stable/services/race_news_exposure.py` | 681 | 身份解析、硬重复、角度、两席状态机 |
| `server/stable/management/commands/backfill_race_exposure.py` | 283 | 历史 exposure dry-run/apply |
| `server/stable/migrations/0060_add_term_mapping_evidence.py` | 35 | TermMappingEvidence 表 |
| `server/stable/migrations/0061_add_race_news_exposure.py` | 41 | RaceNewsExposure 表+约束+索引 |
| `server/stable/test_public_term_consistency.py` | 1223 | 术语测试 (32 tests) |
| `server/stable/test_race_news_exposure.py` | 1703 | 曝光测试 (47 tests) |

### 变更文档（参考，不逐行审核）

- `docs/changes/govern-race-news-exposure/{spec,design,test_cases,tasks,rollout}.md`
- `docs/changes/unify-public-racing-terms/{spec,design,test_cases,tasks,rollout}.md`
- `docs/changes/race-news-quality-implementation-handoff.md`（实现交接文档）

## 6. 审查执行步骤

### 第一步：审前 fingerprint

```sh
cd /Users/mentianlu/Code/umanews/.worktrees/impl-race-news-quality-20260726
python3 .codex/scripts/review_fingerprint.py
```

记录 `FINGERPRINT_SHA256` 输出。**本轮审前基线为**：
`038a6df7421f0e99a2fd2ba2970c8fba97cc5a4735bad723d7c0e367e2f5c1b3`

如果输出不同，审查立即 `BLOCKED` 并停止。

### 第二步：Codex 原生只读审查

使用 CLI 命令：
```sh
codex review -c 'sandbox_mode="read-only"' --uncommitted
```

若 Codex CLI 不可用，使用产品自身的只读 `/review`。

### 第三步：审后 fingerprint

```sh
python3 .codex/scripts/review_fingerprint.py
```

审后 `FINGERPRINT_SHA256` 必须与审前完全一致。不一致即时报 `BLOCKED`。

### 第四步：输出审查报告

按以下格式输出：

```
## REVIEW FINGERPRINT
Pre-review:  <sha256>
Post-review: <sha256>
Match: YES/NO

## FINDINGS
### P0 (阻塞 — 正确性/安全/数据完整性)
### P1 (高优先级 — 性能/并发/边界)
### P2 (中优先级 — 代码质量/可维护性)
### P3 (低优先级 — 风格/文档)

## VERDICT
APPROVED / REVISE / BLOCKED

## RESIDUAL RISKS
```

## 7. 审查维度

逐文件按以下维度检查：

**正确性**：模型字段/约束/索引是否正确；服务层逻辑是否与 spec/design 一致；事务/锁/并发是否正确；migration 是否合法。

**安全性**：SQL 注入、XSS 风险；用户输入处理；敏感数据暴露。

**性能**：N+1 查询；批量操作预取；查询数与文档声称一致性。

**数据完整性**：约束表达的业务规则；CAS 逻辑；before hash 漂移检测。

**代码质量**：与现有代码风格一致性；命名清晰度；重复逻辑；错误处理。

## 8. 重点检查清单（来自原方案 RED 错误实现清单）

以下 13 项错误实现不得出现：

1. 只调低 Jaccard 阈值导致不同角度被误标 duplicate
2. 头条不计入首页两席
3. 手工头条在 15 分钟内绕过第二席
4. QQ 只按 article 去重，没有 event/target 两席
5. worker 崩溃后释放了结果不明的席位并再次发送
6. 用赛事中文字符串代替 `RaceEvent.id` 聚类
7. 使用不存在的 `ArticleRaceLink.confirmed`/`PRIMARY` 枚举
8. 把旧中文译名写进不支持中文的 `TermAlias.source_language`
9. 没有 approved mapping evidence 也激活 alias
10. 对英文 surface 做全文字符串替换
11. 覆盖 `manually_edited_fields`
12. published repair 触发 QQ、通知或重新发布
13. per article × 全量术语 N+1

## 9. 审查约束

- **禁止修改任何文件**
- **只读审查**
- 允许运行 `git diff`、`grep`、`python3 manage.py check` 等只读诊断命令
- 允许阅读文件（Read tool）和搜索代码
- 可以运行 `python3 manage.py test` 验证（测试通过本身不是审核结论）
- fingerprint 不一致时立即报告 `BLOCKED`
- 只有所有 P0-P3 actionable findings 清零后才可 `APPROVED`
- 不能以"测试通过"替代审查
- 不得 commit、push、部署或写生产

## 10. 已知限制（非缺陷，不应作为 findings 报告）

1. **`apply_canonical_consistency_manifest` / `rollback_canonical_consistency` 为 stub**：完整 ledger-based rollback 需要额外基础设施，当前满足 dry-run + CAS apply 核心路径。apply 已可正确保存（首轮 finding #4 已修复）。

2. **`classify_angle` 关键词匹配**：当前使用关键词匹配而非 ML 模型，低置信时回退 `other`，不影响席位系统正确性。已移除单字符中文关键词。

3. **`_MANIFEST_STORE` 进程内存储**：dry-run manifest 保存在模块级 dict，进程重启后丢失。生产级应使用数据库/Redis 存储，当前满足本地 dry-run → commit 流程。

4. **视图层曝光过滤仅在 `RACE_NEWS_EXPOSURE_ENABLED=True` 时生效**：关闭时保持旧行为，这是灰度设计的正确行为。

## 11. 测试参考

```sh
# 所有新增测试（应在审查环境中可重现）
cd server
python3 manage.py test stable.test_race_news_exposure stable.test_public_term_consistency -v2

# 受影响回归测试
python3 manage.py test stable.test_editorial_headlines stable.test_english_term_context_gates stable.test_term_gate_reprocessing -v2

# 系统检查
python3 manage.py check
python3 manage.py makemigrations --check --dry-run
```

预期结果：193 tests: 191 OK, 2 PG skip。性能测试已修复（N+1 消除后 query count 从 406 降至预算内）。

## 12. 审查完成后

审查报告必须包含：
- 完整审前/审后 fingerprint 及一致确认
- codex review 命令的实际退出码/完成状态和内层 sandbox 头
- 按严重度排列的 findings 清单（含文件:行号定位）
- VERDICT（APPROVED / REVISE / BLOCKED）
- 残余风险记录

若 `APPROVED`（actionable findings 清零），冻结审查基线：
- approved parent: `ef54a1836dd1fe1840f2d4765ebb73a1d130c645`
- FINGERPRINT_SHA256（审后值）
- content_manifest_sha256（审后值）

若 `REVISE`，列出需要修复的具体 findings；修复后回到同一 reviewer 会话限定复审。
