# 赛事新闻质量治理：第四轮复审后交接文档

## 0. 交接目的

本文档供接手 agent 无缝继续工作。当前代码已通过 4 轮限定复审，7 项阻塞仍未关闭。
**任务：在不引入新范围的前提下，完成 7 项剩余修复。**

## 1. 仓库与基线

- 仓库：`/Users/mentianlu/Code/umanews`
- 工作树：`.worktrees/impl-race-news-quality-20260726`
- 分支：`codex/impl-race-news-quality-20260726`
- HEAD：`ef54a1836dd1fe1840f2d4765ebb73a1d130c645`
- 上游：`review-ref`（不可移动本地 ref，指向 `0bf3fd9`）
- 工作树绝对路径：`/Users/mentianlu/Code/umanews/.worktrees/impl-race-news-quality-20260726`
- venv：`.venv/bin/python3`
- Django：`server/manage.py`，`DJANGO_SETTINGS_MODULE=app.settings`

**禁止**：fetch、commit、push、deploy、生产写入、改变 `review-ref`。

## 2. 当前变更总览

### Tracked (15 files, +578/-6)

| 文件 | 说明 |
|------|------|
| `server/stable/models.py` | `TermMappingEvidence` + `RaceNewsExposure` + CheckConstraints |
| `server/stable/admin.py` | 两个新模型 admin |
| `server/stable/signals.py` | `suppress_qq_push()` threading.local() |
| `server/stable/views.py` | 首页 EXISTS 子查询曝光过滤 |
| `server/stable/tasks.py` | QQ 即时推送 + 窗口推送接入曝光 |
| `server/stable/services/validation.py` | `validate_rewrite` 接入术语门禁 |
| `server/stable/services/automation.py` | `mark_publish_ready` fail-closed 术语门禁 |
| `server/stable/services/qq_windows.py` | 窗口 QQ 接入曝光 reservation |
| `server/stable/services/editorial_headlines.py` | `set_manual_headline` 接入 replace_slot2 |
| `server/app/settings.py` | 8 个功能开关 |
| `.env.example` | 8 个配置项 |
| `docs/` × 4 | 状态文档 |

### Untracked code (8 files)

| 文件 | 行数 |
|------|------|
| `server/stable/services/term_consistency.py` | ~1130 |
| `server/stable/services/race_news_exposure.py` | ~730 |
| `server/stable/management/commands/backfill_race_exposure.py` | ~300 |
| `server/stable/migrations/0060_add_term_mapping_evidence.py` | 35 |
| `server/stable/migrations/0061_add_race_news_exposure.py` | 41 |
| `server/stable/migrations/0062_add_exposure_constraints.py` | ~20 |
| `server/stable/test_public_term_consistency.py` | ~1223 |
| `server/stable/test_race_news_exposure.py` | ~1703 |

### 变更文档 (参考，不修改)

- `docs/changes/govern-race-news-exposure/{spec,design,test_cases,tasks,rollout}.md`
- `docs/changes/unify-public-racing-terms/{spec,design,test_cases,tasks,rollout}.md`

## 3. 测试基线

```sh
cd /Users/mentianlu/Code/umanews/.worktrees/impl-race-news-quality-20260726/server
.venv/bin/python3 manage.py test \
  stable.test_race_news_exposure \
  stable.test_public_term_consistency \
  stable.test_editorial_headlines \
  stable.test_english_term_context_gates \
  stable.test_term_gate_reprocessing -v2
```

**预期**：193 tests, 191 OK, 2 PG skip。Django check 通过。`makemigrations --check --dry-run` 通过。

## 4. 7 项剩余阻塞（来自第四轮限定复审）

### Issue 1: 首页性能测试静默跳过

**位置**: `server/stable/test_race_news_exposure.py`，性能测试相关类

**问题**: 首页已改用 `Exists` 子查询，但测试中导入不存在的性能测试辅助函数导致静默跳过。

**修复方向**: 检查性能测试的 import 路径，确保 `_try_import_service` 返回的是实际存在的函数；或补全函数实现。

### Issue 2: 窗口 QQ 未原子绑定 exposure、quota、delivery

**位置**: 
- `server/stable/services/qq_windows.py:233`（`existing_delivery` 查询之前）
- `server/stable/services/qq_windows.py:263`（`ensure_qq_push_deliveries` 调用）

**问题**: 即时 QQ（`tasks.py`）已在单一 `transaction.atomic()` 中完成 reservation + delivery 原子绑定。但窗口 QQ 路径：
1. `reserve_qq_exposure` 在 transaction 外调用，exposure 独立提交
2. `_reserve_qq_quotas` 在 transaction 外调用，quota 独立提交
3. `ensure_qq_push_deliveries` 在 transaction 外调用，delivery 独立提交
4. 三者不在同一事务中，任一步骤失败无法整体回滚

**修复方向**: 将窗口 QQ 中每个 target 的 exposure reservation + quota check + delivery creation 包裹在同一个 `transaction.atomic()` 内，参照 `tasks.py` 中的实现模式。

### Issue 3: `validate_rewrite()` 异常仍 fail-open

**位置**: `server/stable/services/validation.py`

**问题**: `automation.py` 中术语 gate 异常已 fail-closed。但 `validation.py` 中 `validate_rewrite()` 对 `apply_consistency_gate` 的调用仍在 `try/except` 外或异常处理不当——如果 gate 本身抛异常，不会阻断发布。

**修复方向**: 检查 `validate_rewrite()` 中术语门禁调用的异常处理。确保 gate 异常时返回验证失败（由调用方的 fail-closed 逻辑接管），而非静默通过。

### Issue 4: 人工头条吞 exposure 异常

**位置**: `server/stable/services/editorial_headlines.py:455`

**问题**: `set_manual_headline` 中 exposure 同步逻辑被 `except Exception as exc: logger.warning(...)` 包裹。如果 `replace_slot2` 或 `reserve_exposure` 抛出异常（如数据库约束冲突），只记录日志，头条仍提交。

**修复方向**: exposure 同步失败时不应吞异常。两个选项：
1. （推荐）将 exposure 同步放入 `set_manual_headline` 的现有 `transaction.atomic()` 块内，使其与头条设置原子化。失败时整个事务回滚。
2. 在 exposure 同步失败时 raise，让整个 `set_manual_headline` 失败。

### Issue 5: Manifest 进程内存 + rollback stub

**位置**:
- `server/stable/services/term_consistency.py:_MANIFEST_STORE`（模块级 dict）
- `server/stable/services/term_consistency.py:rollback_canonical_consistency`（stub）

**问题**: dry-run manifest 只存在进程内存（重启丢失），rollback 是空实现。

**修复方向**: 这是已文档化的已知限制，不是本轮新增范围。如果时间允许，可将 `_MANIFEST_STORE` 持久化到 Django 缓存或数据库；否则在文档中记录为生产就绪前须解决的技术债。

### Issue 6: 未审核 alias 可绕过 evidence + auto identity 缺年份/地区

**位置**:
- `server/stable/services/term_consistency.py`：`resolve_term_occurrences` 的 occurrence 状态判定
- `server/stable/services/race_news_exposure.py:_validate_identity_context`

**问题**: 
- 日文 alias 可通过 `source_ja` 匹配绕过 evidence，直接 `confirmed`
- `_validate_identity_context` 的年份/地区校验在 auto link 场景被调用，但年份使用 `RacingRegion` 而非 `RaceEvent.country_region`，且 YYYY 格式比较可能漏掉跨年赛事

**修复方向**: 
- 日文 alias 也需检查 `_has_approved_evidence`
- 确认 `_validate_identity_context` 中的 `event.year` 字段名正确（检查 RaceEvent 模型实际字段名）
- 确认 `article.racing_region` 与 `event.country_region` 的比较使用正确的字段

### Issue 7: NFKC 偏移、术语快照、auto-link inventory

**位置**:
- `server/stable/services/term_consistency.py:_apply_occurrence_replacements`
- `server/stable/services/term_consistency.py:_term_snapshot_sha256`
- `server/stable/management/commands/backfill_race_exposure.py:_dry_run`

**问题**:
- NFKC 正规化后 occurrence 位置偏移未完整处理
- `_term_snapshot_sha256` 未包含 alias 内容和 evidence 状态
- backfill dry-run 仍只扫描 `ArticleRaceLink.status=MANUAL`，遗漏 auto link

**修复方向**:
- `_apply_occurrence_replacements` 改用 casefold 比较（上轮已部分完成，确认覆盖所有路径）
- `_term_snapshot_sha256` 加入 `TermAlias`（text, source_language, is_active）和 `TermMappingEvidence`（review_status）内容
- backfill `_dry_run` 的 queryset 过滤条件加 `ArticleRaceLinkStatus.AUTO`

## 5. 已确认关闭的项（不要重复修复）

以下项已在之前轮次的复审中确认关闭，**不应修改或撤销**：

1. Backfill `IntegrityError` 整批回滚 ✅
2. `0060/0061/0062` 迁移及 PostgreSQL 约束 ✅
3. Waiting slot-2 自动晋级 ✅
4. Backfill 需显式 `--apply` + `--expected-sha256` ✅
5. 首页 EXISTS 子查询（DB 层过滤）✅
6. 即时 QQ reservation+delivery 原子化 ✅
7. `replace_slot2` 校验：channel/homepage、15 分钟、角度差异、质量 ✅
8. 术语 enforce → blocker（`TERM_CONSISTENCY_ENFORCE=True` 时）✅
9. 人工头条接入 `replace_slot2` 调用 ✅
10. `suppress_qq_push` threading.local() ✅

## 6. 功能开关（全部默认关闭）

```python
# settings.py 中已定义
TERM_CONSISTENCY_ENABLED = False    # 术语一致性门禁
TERM_CONSISTENCY_SHADOW = True      # shadow 模式
TERM_CONSISTENCY_ENFORCE = False    # enforce 模式（blocker 级）

RACE_NEWS_EXPOSURE_ENABLED = False  # 曝光治理
RACE_NEWS_EXPOSURE_SHADOW = True    # shadow 模式
RACE_NEWS_SECOND_SLOT_DELAY_MINUTES = 15
RACE_NEWS_HOMEPAGE_MAX = 2
RACE_NEWS_QQ_TARGET_MAX = 2
```

## 7. 工作约束

- **禁止** commit、push、deploy、生产写入
- **禁止** 修改 `docs/changes/` 下的变更文档
- **禁止** 修改已确认关闭的项（见 §5）
- **禁止** 引入超出上述 7 项的新范围
- **允许** 修改代码文件、运行测试、运行 Django check
- 修复后运行全量测试：193 tests → 191 OK, 2 PG skip
- 不要运行 `git fetch` 或改变 `review-ref`

## 8. 修复完成后

1. 运行全量测试确认通过
2. 运行 `python3 .codex/scripts/review_fingerprint.py`
3. 在聊天中提供 `FINGERPRINT_SHA256`、`content_manifest_sha256`、HEAD
4. 编辑本交接文档，在末尾追加修复摘要
5. 通知用户复审就绪

## 9. 关键模型参考

```python
# RaceNewsExposure 核心字段
event: FK(RaceEvent), article: FK(NewsArticle)
channel: "homepage"|"qq", scope_key: "site"|"target:<id>"
slot: 1|2 (CheckConstraint)
status: waiting|active|replaced|sent|suppressed
angle: comprehensive_result|winner|connections|runner|analysis|market|other

# TermMappingEvidence
term: FK(TermEntry), alias: FK(TermAlias, nullable)
evidence_kind, source_url, source_digest
review_status: pending|approved|rejected
identity_sha256

# 现有关键模型
TermEntry: target_zh, source_ja, term_type, racing_region, aliases_zh, is_active
TermAlias: term(FK), text, source_language, is_active
ArticleRaceLink: article(FK), event(FK), status(manual|auto|candidate|removed), confidence
RaceEvent: year, country_region, ...
NewsArticle: score_total, manually_edited_fields, racing_region, published_at, ...
```

## 10. 第五轮修复摘要（2026-07-28，Claude Code）

7 项阻塞已全部处理。HEAD 不变（`ef54a1836dd1fe1840f2d4765ebb73a1d130c645`，未 commit）。

### 修复明细

1. **首页性能测试静默跳过** — `test_race_news_exposure.py` 性能测试改导入真实存在的
   `stable.services.race_news_exposure.get_featured_articles`，并在
   `override_settings(RACE_NEWS_EXPOSURE_ENABLED=True)` 下统计查询数（≤10）；
   导入失败改为 `self.fail` 而非静默通过。
2. **窗口 QQ 原子绑定** — `qq_windows.py` 每个 target 的 existing-delivery 检查、
   `reserve_qq_exposure`、`_reserve_qq_quotas`、`ensure_qq_push_deliveries` 及
   exposure→delivery 关联全部移入单个 `transaction.atomic()`；任一步失败整体回滚，
   决策记录（WindowTargetDecision）在事务外按结果写入。
3. **`validate_rewrite()` fail-open** — `validation.py` 术语门禁异常由
   INFO/ROUTE_AUTO 改为 BLOCKER/ROUTE_MANUAL（`term_consistency_error`），
   与 `automation.mark_publish_ready` 的 fail-closed 语义一致。
4. **人工头条吞 exposure 异常** — `editorial_headlines.py` 移除 exposure 同步的
   `try/except` 吞异常；同步本就在 `set_manual_headline` 的 `transaction.atomic()`
   内，异常现在直接传播并回滚整个头条设置。
5. **Manifest 进程内存 + rollback stub** — 判定为既有技术债（非本轮新增范围），
   记录于下方"生产就绪前技术债"，未改代码。
6. **未审核 alias 绕过 evidence** — `term_consistency.py`：
   - 同一 surface 同时命中 alias 与 term 自身 `source_ja` 时，优先经 registry
     （`alias_id=None`）条目解析，未经审核的 alias 不再借 `source_ja` 匹配获得信任。
   - HORSE alias 的 evidence 门禁移至 `is_race_context` 之前，对所有来源语言生效，
     日文 alias 不再经"非英文一律 race context"规则绕过 `_has_approved_evidence`。
   - `_validate_identity_context` 字段名已核对无误（`event.year` 为
     PositiveSmallIntegerField、`event.country_region` 对 `article.racing_region`，
     ±1 年窗口覆盖跨年赛事），无需改动。
   - 测试更新：`test_japanese_alias_resolves_to_same_term_entry` 改为先写入 approved
     evidence（测试意图不变）；新增 `test_japanese_alias_without_evidence_is_uncertain`
     覆盖新门禁。
7. **NFKC 偏移 / 术语快照 / backfill inventory** —
   - `_apply_occurrence_replacements`：偏移失配时回退到大小写不敏感的 surface 查找
     （从右向左、跳过已替换区间），不再静默跳过替换。
   - `_term_snapshot_sha256` 加入 `TermAlias`（text/source_language/is_active）与
     `TermMappingEvidence`（review_status）内容，dry-run 与 commit 之间的 alias 激活
     或 evidence 审核变化会使 manifest 失效。
   - `backfill_race_exposure._dry_run` 扫描条件加入 `ArticleRaceLinkStatus.AUTO`
     （低置信 auto link 仍由 `_resolve_identity` 阈值过滤）。

### 生产就绪前技术债（Issue 5，未关闭）

- `term_consistency._MANIFEST_STORE` 仅存于进程内存，worker 重启后 dry-run manifest
  丢失，`commit_dry_run` 将无法找到 run_id。生产启用术语历史修复前须持久化
  （Django cache 或数据库表）。
- `rollback_canonical_consistency` 为空实现（始终返回不支持）。生产启用前须实现
  真正的回滚或明确下线该入口。

### 验证结果

- 基线套件：194 tests（193 + 新增 1），191 OK + 1 新增 OK，2 PG skip，全绿。
- Django check、`makemigrations --check --dry-run` 通过。
- 扩展套件（tests_legacy 等 727 tests）：12 失败 + 3 错误均为既有失败，集中于
  RaceEventPageMVP（current-year CSV 导入门禁）、多地区归因公开页、P0 马档案公开页、
  HKJC 种子准备，与本轮修改文件无交集（其中 QQ 窗口相关用例全部通过）。
- FINGERPRINT_SHA256: `b174b1d1800d3eeff8b95f58ecf683ea42e23e02ed664336b07fa0baedb2e072`
- content_manifest_sha256: `f41ff920556e88a96fd5e453a91b3f1fca66777862b1f83ed48a0a820fb823cd`
- HEAD: `ef54a1836dd1fe1840f2d4765ebb73a1d130c645`

**复审就绪。**

## 11. 第六轮修复摘要（2026-07-28，Claude Code）

第五轮限定复审结论 REVISE：1 项关闭（`validate_rewrite` fail-closed）、6 项仍开放。
本轮已全部处理。HEAD 不变（`ef54a183`，未 commit）。

### 修复明细

1. **性能测试覆盖真实视图** — `PerformanceTests.test_homepage_50_articles_query_count`
   改为在 `RACE_NEWS_EXPOSURE_ENABLED=True` 下用 test client 请求真实
   `public_news_feed()`（`GET /`）：先 10 篇 race-linked 文章测基线查询数，再扩到
   50 篇（5 个赛事 × 10 篇）断言查询数增量 ≤2（证明 EXISTS 子查询无 N+1），
   绝对上限 40。
2. **quota 拒绝回滚 orphan exposure** — 根因：quota 拒绝是**返回值**而非异常，
   `transaction.atomic()` 块正常退出即提交，把已创建的 exposure 一并提交。
   修复：`qq_windows.py` 将 exposure reservation 包在独立 savepoint 中，
   quota 拒绝时 `savepoint_rollback` 仅回滚 exposure（quota 台账行仍按既有契约
   提交、used 不变——`tests_legacy.QQWindowServiceTests` 两个 quota 用例依赖
   该契约，初版 `set_rollback(True)` 整事务回滚误伤台账行，已改为 savepoint
   方案）。delivery 创建抛异常仍由外层 atomic 整体回滚。
   新增 `WindowQQAtomicityTests.test_quota_rejection_leaves_no_orphan_exposure`
   回归（quota 打满后 exposure/delivery 均为 0）。
3. **人工头条尊重政策拒绝** — `reserve_exposure`/`replace_slot2` 的政策拒绝以
   `{"slot": None, "status": ...}` 返回、不抛异常。修复：`set_manual_headline`
   检查结果，slot 为 None 时 `raise ValueError`，整个头条事务回滚（view 已有
   ValueError 捕获路径）。新增
   `ManualHeadlineExposurePolicyTests.test_low_score_headline_rejected_rolls_back`：
   低分头条触发 `new_article_not_higher_quality` 后版本/选中文章/slot2 均不变。
4. **Manifest 持久化 + rollback 实现** —
   - 新模型 `TermConsistencyManifest`（run_id 唯一、sha 三件套、diffs JSON、
     status pending/committed/rolled_back、approved_by、时间戳），migration
     `0063_add_term_consistency_manifest`（makemigrations 生成，drift 为零），
     admin 已注册。
   - `_MANIFEST_STORE` 进程内存字典已删除；`_build_manifest_from_articles`
     改为 `update_or_create` 持久化；`commit_dry_run` 从 DB 读取、拒绝重复提交、
     成功后标记 committed。
   - diffs 增加 `before_value`；`rollback_canonical_consistency` 实现真实回滚：
     两阶段（先全量 CAS 校验 current==after，任何漂移整体中止不落盘；再恢复
     before_value），尊重 manually_edited_fields，成功后标记 rolled_back。
   - 新增 `ManifestPersistenceAndRollbackTest` 5 个用例（持久化、提交标记、
     回滚还原、漂移中止、状态门槛）。
5. **非 HORSE alias 门禁 + backfill AUTO 校验** —
   - evidence 门禁泛化为 `alias_id is not None` 即拦截（任意 term_type、任意语言）；
     仅 registry（source_ja）条目保持可信。`test_race_aliases_converge_to_canonical_zh`
     相应更新：纯 alias 补 approved evidence（测试意图不变）。
   - `backfill_race_exposure._resolve_identity` 删除自带的简化实现，改为委托
     `race_news_exposure.resolve_race_identity`，AUTO link 获得与运行时一致的
     置信度阈值 + 年份/地区上下文校验。
6. **NFKC 全角替换 + snapshot 内容字段** —
   - 新增 `_nfkc_offset_map()`：逐字符 NFKC 建立 normalized→original 偏移映射
     （含 strip 前导对齐；跨字符组合等无法安全映射时返回 None）。
     `_apply_occurrence_replacements` 回退链：原始偏移快路径 → NFKC 偏移映射
     （`_nfkc(segment).casefold()` 校验）→ 大小写不敏感搜索兜底。全角 surface
     （如 `Ｋａｌｐａｎａ`）现在能正确定位并替换。
   - `_term_snapshot_sha256` 的 evidence 部分纳入内容字段（evidence_kind、
     source_url、source_digest、identity_sha256、review_status、reviewed_by），
     alias 部分加 alias_type；evidence 内容编辑同样使 manifest 失效。

### 验证结果

- 基线套件：201 tests（194 + 新增 7），199 OK，2 PG skip，全绿。
- Django check、`makemigrations --check --dry-run` 通过。
- 扩展套件（tests_legacy 等 727 tests）：失败清单与修改前基线**逐条一致**
  （15 项既有失败：RaceEventPageMVP 5、多地区归因 3、P0 马档案 4、HKJC 种子 3），
  无新增；QQ 窗口 legacy 用例 12/12 通过。
- 手工验证：全角 `Ｋａｌｐａｎａ` 替换为 `幻梦逸想` 且无关全角内容保留；
  evidence 内容编辑与审核状态变化均改变 `_term_snapshot_sha256`。

**复审就绪（第六轮）。**

## 12. 第七轮修复摘要（2026-07-28，Claude Code）

第六轮限定复审结论 REVISE：3 项关闭（首页真实 GET 性能、quota orphan、alias/AUTO/NFKC）、
3 项仍开放。本轮已全部处理。HEAD 不变（`ef54a183`，未 commit）。

### 修复明细

1. **头条成功但无 active exposure** — 根因有两处：
   - `reserve_exposure` 对同文章已有 exposure 一律原样返回，suppressed/replaced
     陈旧行也被当作成功（`slot` 非 None）。
   - `replace_slot2` 早退分支对新文章的 waiting/suppressed 行同样空报成功。
   修复：
   - `reserve_exposure` 仅对 live 状态（waiting/active/sent）幂等返回；
     陈旧行在 slot-1/slot-2 两条路径上**原地重激活**（每文章唯一约束禁止新建第二行）。
   - `replace_slot2` 早退分支仅对 active/sent 返回成功；waiting/suppressed/replaced
     行原地激活为 slot 2 active（继承新角度与 reason，记录 replaced_by）。
   新增 `StaleExposureReactivationTests` 3 用例（reserve 原地重激活、replace_slot2
   原地激活、人工头条端到端：suppressed → active）。
2. **Manifest apply/rollback 批次级事务与行锁** —
   - `commit_dry_run`：整个批次（manifest 行 `select_for_update`、逐文章
     `select_for_update`、CAS 校验、字段写入、manifest 状态翻转）纳入**单个
     `transaction.atomic()`**；任何失败（漂移、save 异常、故障注入）整批回滚，
     不再可能部分 apply。原先逐文章独立事务是部分提交根因。
   - `rollback_canonical_consistency`：同样改为单事务 + 行锁；CAS 漂移仍在写入前
     整体中止。
   - 新增 2 用例：注入第二篇文章 save 失败 → commit 整批回滚（首篇字段与 manifest
     状态均未变）；rollback 同理。
3. **快照遗漏 identity_payload** — `_term_snapshot_sha256` 的 evidence values 加入
   `identity_payload`；新增用例验证仅修改 payload 即改变快照哈希。

### 验证结果

- 基线套件：207 tests（201 + 新增 6），205 OK，2 PG skip，全绿。
- 扩展套件（727 tests）：失败清单与修改前基线逐条一致（15 项既有失败，无新增）。
- 无模型变更（本轮仅服务层与测试），Django check 通过。

**复审就绪（第七轮）。**

## 13. 第八轮修复摘要（2026-07-29，Claude Code）

第七轮限定复审结论 REVISE：仅剩 1 项（人工头条的两条 exposure 旁路）。本轮已处理。
HEAD 不变（`ef54a183`，未 commit）。

### 修复明细

**人工头条 waiting / 幂等两条路径无 active 席位** —

- 路径 A（`race_news_exposure.py` 幂等早退）：头条文章已有 `waiting` exposure 时，
  `reserve_exposure` 原样返回 waiting 状态，`slot` 非 None 使头条提交成功，但文章
  在首页不可见。修复：`set_manual_headline` 检查同步结果，遇 `status == "waiting"`
  时调用新增的 `force_activate_exposure()`（`race_news_exposure.py` 新服务函数，
  行锁 + 状态校验，仅允许 waiting→active）立即激活——人工头条属编辑覆盖，
  与第六轮 `replace_slot2` 的立即激活语义一致。
- 路径 B（`editorial_headlines.py` 已选中幂等早退）：`selection.article_id ==
  article_id` 时原先直接返回成功，完全绕过 exposure 同步。修复：重构
  `set_manual_headline`，幂等时跳过选择变更与审计（版本不变），但**仍执行
  exposure 同步**——已退化的 waiting/suppressed exposure 会被重新激活/重激活；
  政策拒绝同样 fail-closed。

新增 2 用例（`ManualHeadlineExposurePolicyTests`）：
- `test_headline_with_waiting_exposure_is_activated`：waiting → 头条成功后 active。
- `test_idempotent_headline_resyncs_degraded_exposure`：已选中文章的 exposure 被
  抑制后重设头条 → 重新激活且版本不变。

### 验证结果

- 基线套件：209 tests（207 + 新增 2），207 OK，2 PG skip，全绿。
- 无模型/迁移变更；Django check 通过。
- 扩展套件结果与修改前基线逐条一致（见当轮对话）。

**复审就绪（第八轮）。**

## 14. 第九轮修复摘要（2026-07-29，Claude Code）

最终限定复审结论 REVISE：仅剩 1 个 P1。本轮已处理。HEAD 不变（`ef54a183`，未 commit）。

### 修复明细

**人工头条角度硬编码导致同角度误拒**（`editorial_headlines.py` reserve 路径）—

- 根因：reserve 路径把曝光角度硬编码为 `comprehensive_result`。当 slot 1 已是
  综合赛果角度、头条文章真实角度为 connections（或任何其他角度）且其 slot 2
  exposure 被 suppressed 时，幂等重设会因 `same_angle_as_slot1` 被拒绝，
  头条保持 suppressed、首页不可见。
- 修复：改用文章真实 `classify_angle(article, event)["angle"]` 参与
  `reserve_exposure`；同角度/政策拒绝仍按既有语义 fail-closed（不变）。
- 新增用例 `test_idempotent_reactivate_slot2_with_real_angle`：综合赛果 slot 1
  + connections 头条 slot 2 被 suppressed → 首设重激活 → 再退化 → 幂等重设
  再次恢复 active 且版本不变。

### 验证结果

- 基线套件：210 tests（209 + 新增 1），208 OK，2 PG skip，全绿。
- 无模型/迁移变更；Django check 通过。
- 扩展套件结果与修改前基线逐条一致（见当轮对话）。

**复审就绪（第九轮）。**

## 15. 第十轮修复摘要（2026-07-29，Claude Code）

最终复审结论 REVISE：仅剩 1 个字段问题。本轮已处理。HEAD 不变（`ef54a183`，未 commit）。

### 修复明细

**active slot 2 的 `activated_at` 为 None**（`race_news_exposure.py` slot-2 路径）—

- 根因：`reserve_exposure` slot-2 路径的
  `effective_activated_at = activated_at if slot_status == ACTIVE else None`
  直接使用可空的 `activated_at` 参数；头条路径不传该参数，重激活/新建的
  active slot 2 得到 `activated_at=None`（不一致状态，下游成熟度计算与探针
  均依赖该字段）。
- 修复：改为 `(activated_at or now) if slot_status == ACTIVE else None`，
  与 slot-1 路径及 `force_activate_exposure` 的语义一致。
- 测试加固：`test_idempotent_reactivate_slot2_with_real_angle` 在首设与幂等
  恢复后均断言 `activated_at` 非 None。

### 验证结果

- 基线套件：210 tests，208 OK，2 PG skip，全绿。
- 无模型/迁移变更；Django check 通过。
- 扩展套件结果与修改前基线逐条一致（见当轮对话）。

**复审就绪（第十轮）。**
