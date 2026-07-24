# `add-editorial-headline-control` 独立代码审查交接文档

> 目标读者：未参与实现的独立 Codex reviewer agent  
> 文档日期：2026-07-25（Asia/Shanghai）  
> 当前阶段：实现与自审完成，等待独立代码 review  
> 自审结论：`VERDICT: READY FOR REVIEW`（4 项自审发现已全部修复）

## 1. 工作区与基线

```text
worktree: /Users/mentianlu/Code/umanews/.worktrees/add-editorial-headline-control
branch:   codex/add-editorial-headline-control
base:     origin/main@10f341e6b76b634d840ec8c87b818de3c722f450 (当前 HEAD)
```

该 commit 是：
```text
Merge pull request #19 from
thumentianlu1993-blip/codex/audit-reprocess-historical-news-body-contamination
```

未提交内容限于本 change 相关文件，无其他夹带。

## 2. 本 Change 要做什么

在现有自动算法头条的基础上，增加两个互相隔离的能力：

1. **人工头条控制**：有权限后台人员可显式选择/替换/取消唯一一篇首页头条。
2. **AI 编辑推荐**：基于已有自动化信号生成一篇候选推荐及中文理由，但推荐**不修改首页**；只有人工明确接受后才切换。

现有算法回退（72h → 7d → all 三级窗口、48 候选上限、赛事优先级/分数/封面/时间排序元组）保持不变。

### 核心约束

- 人工和 AI 推荐不能同时各自生效：人工优先于算法，AI 推荐是独立快照
- 统一资格校验：人工选择、AI 推荐、算法 fallback 共用同一 `is_headline_eligible()`
- 版本乐观锁：所有写操作携带 `expected_version`，陈旧页面不能静默覆盖
- PostgreSQL 层面唯一约束：最多一个 selection 行、最多一个 active 推荐
- 失效协调：文章撤稿/改待审核/删除/清空内容/未来时间时，自动清除相关头条状态
- 推荐永不修改 selection；只有人工接受才切换
- 公开 GET 不写数据库

## 3. 变更文件清单

### 新增文件 (5)

| 文件 | 说明 |
|------|------|
| `server/stable/migrations/0054_homepage_headline_control.py` | 新建两表 + 约束 + 索引，不扫描 NewsArticle |
| `server/stable/services/editorial_headlines.py` | 完整服务层（824 行）：资格、候选、选择、推荐、失效、并发安全 |
| `server/stable/templates/stable/console/headline_control.html` | 后台头条管理页 |
| `server/stable/test_editorial_headlines.py` | 完整测试套件（57 测试、~1050 行） |
| `docs/changes/add-editorial-headline-control/review_handoff.md` | 本文件 |

### 修改文件 (10)

| 文件 | 变更要点 |
|------|---------|
| `server/stable/models.py` | +79 行：新增 `HomepageHeadlineSelection` 和 `HomepageHeadlineRecommendation` 模型 |
| `server/stable/signals.py` | +109 行：post_save(on_commit) + pre_delete 失效协调 handler |
| `server/stable/admin.py` | +8/-5 行：`mark_pending_review` 改为逐行 save（修复 bulk update 绕过 signal） |
| `server/stable/forms.py` | +17 行：新增 `HeadlineControlForm` |
| `server/stable/urls.py` | +5 行：新增 5 个头条管理路由 |
| `server/stable/views.py` | +162 行：新增 5 个管理视图 + article_editor 推荐数据 + 首页接入 resolver |
| `server/stable/templates/stable/console/article_editor.html` | +28 行：右侧栏新增 AI 推荐卡片（非嵌套 form） |
| `docs/current_state.md` | +45 行：记录实现完成状态 |
| `docs/decisions.md` | +25 行：记录实现决策 |
| `docs/project_status.md` | +16 行：简短状态更新 |

合共：**10 modified + 5 new | +489 / -5 lines**

## 4. 数据模型

### HomepageHeadlineSelection（当前控制状态）

```text
slot:        CharField(max_length=32, unique=True, default="homepage_primary")
article:     FK(NewsArticle, null=True, blank=True, on_delete=SET_NULL, related_name="+")
selected_by: FK(User, null=True, blank=True, on_delete=SET_NULL, related_name="+")
selected_at: DateTimeField(null=True, blank=True)
version:     PositiveBigIntegerField(default=0)
created_at / updated_at

约束: CheckConstraint(slot="homepage_primary"), UNIQUE(slot)
```

语义：全库仅一行固定 slot。`article is null` = 无人工头条。version 每次写递增。

### HomepageHeadlineRecommendation（推荐快照）

```text
slot:           CharField(max_length=32, default="homepage_primary")
article:        FK(NewsArticle, null=True, blank=True, on_delete=SET_NULL, related_name="+")
status:         active | accepted | superseded | invalidated
reason:         TextField
evidence:       JSONField
engine_version: CharField(max_length=64)
generated_by:   FK(User, null=True, on_delete=SET_NULL, related_name="+")
accepted_by:    FK(User, null=True, blank=True, on_delete=SET_NULL, related_name="+")
accepted_at:    DateTimeField(null=True, blank=True)
created_at / updated_at

约束: CheckConstraint(slot="homepage_primary"),
      UniqueConstraint(("slot",), condition=Q(status="active"))
索引: (slot, status, -created_at)
```

## 5. 服务层接口 (`editorial_headlines.py`)

```python
is_headline_eligible(article, *, now=None) -> bool
headline_candidate_queryset(*, now=None) -> QuerySet
get_headline_state(*, now=None) -> dict
select_automatic_headline(public_queryset, *, now=None) -> NewsArticle | None
resolve_homepage_headline(public_queryset, *, now=None) -> NewsArticle | None
set_manual_headline(article_id, *, user, expected_version) -> dict
cancel_manual_headline(*, user, expected_version) -> dict
generate_headline_recommendation(*, user, now=None) -> dict | None
accept_headline_recommendation(recommendation_id, *, user, expected_selection_version) -> dict
invalidate_headline_state_for_article(article_id, *, reason) -> int
```

### 并发安全设计

- 单例 selection 行通过 savepoint + get_or_create + IntegrityError retry 安全创建
- 所有写操作 `select_for_update()` 锁定 selection 行作为统一互斥点
- 锁顺序统一：`selection → recommendation → article`
- 版本号防止陈旧页面静默覆盖（不一致 → ValueError）
- 推荐生成也锁 selection 行但不修改它
- PostgreSQL 条件唯一约束是最后防线

### 资格校验

同时满足以下条件才算合格：
1. `workflow_status == published`
2. `published_to_web_at` 非空且 `<= now`
3. `effective_title.strip()` 非空
4. `effective_summary.strip()` 非空（注意：会回退到 `effective_body[:180]`）
5. `effective_body.strip()` 非空
6. article 有 pk

不要求封面。不检查 `published_at` 或 `withdrawn_at`。

### 候选扫描

- 数据库层预过滤（超集）→ Python 精确资格校验
- 预取 cover_media_asset + prefetch images 到 `prefetched_images`（按 sort_order, id）
- 三级窗口：72h → 7d → all
- 每窗口最多扫描 192 行，收集前 48 个合格候选
- 排序 key：`(race_priority, score_total, has_cover, published_at.timestamp, id)`

### 失效协调

- `post_save(NewsArticle)` → `transaction.on_commit()` → `invalidate_headline_state_for_article()`
- `pre_delete(NewsArticle)` → 在删除事务内清除 selection + 标记 active 推荐为 invalidated
- 幂等：重复调用零写入
- on_commit 异常被 logger.exception() 记录 + signal_error 审计，绝不重抛
- 公开 resolver 即使选择指向不合格文章也安全回退，不 500

## 6. 路由与权限

新增路由（均在 `/admin/` 下）：

```text
GET  /admin/headline/                           管理页
POST /admin/headline/select/                    设置/替换
POST /admin/headline/cancel/                    取消
POST /admin/headline/recommend/                 刷新推荐
POST /admin/headline/recommend/<id>/accept/     接受推荐
```

权限门禁（两层）：
1. `_ensure_staff(request)` — `is_authenticated` + `is_staff`
2. `request.user.has_perm("stable.change_homepageheadlineselection")` — superuser 隐含拥有

## 7. 审查重点

请特别关注以下方面：

### 正确性
- `is_headline_eligible()` 是否正确处理所有字段回退链（`effective_*` properties）？
- `select_automatic_headline` 的三级窗口逻辑是否与原 `_select_headline_article` 等价？
- 推荐生成是否正确保存 evidence 快照？
- `accept_headline_recommendation` 是否正确更新 selection 和 recommendation 两个模型？

### 并发
- `_ensure_selection()` 的 savepoint + IntegrityError retry 模式是否正确？
- 锁顺序是否正确且一致（selection → recommendation → article）？
- `invalidate_headline_state_for_article` 中的锁与写操作顺序是否与设计一致？
- 条件唯一约束（active 推荐）是否正确创建？

### 安全
- 所有带权限检查的入口是否有绕过风险？
- `headline_control` GET 是否只读？
- `public_news_feed` 的 `resolve_homepage_headline()` 是否真正不写数据库？
- Django Admin 的 `mark_pending_review` 修复是否正确触发 signals？

### 信号与失效
- `post_save` + `transaction.on_commit()` 模式是否正确？
- `pre_delete` handler 是否在 FK SET NULL 之前执行？
- 异常是否被正确捕获而不传播？

### 边界与回归
- 公开首页的来源/地区隐藏是否未被修改？
- `_headline.html`、`_article_card.html` 等公开模板是否未被改动？
- `public.css` 是否未被改动？
- 推荐卡是否在文章编辑 form 之外？

### 代码质量
- views.py 中新增视图的错误处理是否完善（try/except ValueError + PermissionError）？
- 审计日志是否完整覆盖？
- 是否有未清理的调试代码或注释？

## 8. 验证命令

```bash
# 进入 worktree
cd /Users/mentianlu/Code/umanews/.worktrees/add-editorial-headline-control/server

# Python 路径
PY=/Users/mentianlu/Code/umanews/.venv/bin/python

# Django check
DB_ENGINE=sqlite $PY manage.py check

# 迁移漂移
DB_ENGINE=sqlite $PY manage.py makemigrations --check --dry-run

# 聚焦头条测试
DB_ENGINE=sqlite $PY manage.py test stable.test_editorial_headlines --verbosity 2

# 公开页面回归
DB_ENGINE=sqlite $PY manage.py test stable.tests.PublicHomeInfoFeedTests stable.test_public_navigation_and_attribution --verbosity 2

# Git diff 检查
cd /Users/mentianlu/Code/umanews/.worktrees/add-editorial-headline-control
git diff --check
git diff --stat

# Fingerprint
python3 .codex/scripts/review_fingerprint.py
```

## 9. 方案审核历史

- 独立方案 reviewer：三轮审核，首轮 6 项 finding，全部关闭
- 最终：`VERDICT: APPROVED`，P0/P1/P2 finding 为 0
- 方案文件：`spec.md` / `design.md` / `test_cases.md` / `tasks.md` / `rollout.md`（同目录）

## 10. 实现自审历史

- 自审发现 4 项问题（2 P0 + 2 P1），全部已修复
- 修复内容：
  1. `signals.py` post_save handler 包裹在 `transaction.on_commit()` 中
  2. `headline_recommend` 视图修复 `None` 返回值的处理
  3. 所有管理视图添加 `try/except (PermissionError, ValueError)`
  4. 测试用例适配 `captureOnCommitCallbacks(execute=True)`
- 自审后 97/97 测试通过（55 OK + 40 回归 + 2 PG skip）

## 11. Review 要求

根据 `AGENTS.md` 和 `docs/codex_workflow.md` 第 7 节：

```text
codex review -c 'sandbox_mode="read-only"' --uncommitted
```

- reviewer 必须未参与实现
- 必须实际调用 Codex 原生只读 review（不是自行阅读 diff）
- 审前审后各运行一次 `python3 .codex/scripts/review_fingerprint.py`，fingerprint 必须一致
- 内层启动头必须为 `sandbox: read-only`
- 所有 actionable finding 必须清零
- 非 actionable 的残余风险可以报告，但不得掩盖范围缺失
- completed/exit 0 只表示执行成功，不等于审核门禁通过
