---
name: plan-eng-review
description: |
  Engineering review of OpenSpec implementation plans for this Django/Celery
  news platform. Lock in architecture, data flow, database migrations, task
  behavior, test coverage, performance, deployment safety, and documentation
  consistency before coding. Use when asked to review a plan, run architecture
  review, or gate an OpenSpec change before implementation.
user-invocable: true
allowed-tools: Bash, Read, Write, Edit, Grep, Glob, AskUserQuestion
---

# Engineering Plan Review (Umanewsbot + OpenSpec)

沿用 `/plan-eng-review` 工作流，但审查对象是当前仓库：Django 单体、
PostgreSQL/SQLite、Celery/Redis、Django 模板前端、Docker Compose、
Nginx、OSS/本地媒体存储，以及中文仓库协作规则。

核心原则：

- 先闭环可用，再优化扩展。
- 保留 Django 单体与 Docker Compose 主干，除非规格明确批准调整。
- 所有重要状态、决策、排查过程必须写回仓库文档。
- 生产相关结论必须区分“仓库预期”和“服务器真实运行态”。
- 新增协作文档、OpenSpec 产物和代理说明默认使用中文。

---

## Engineering Preferences

- 最小可行改动：优先复用现有模型、服务、任务、模板和部署脚本。
- 测试不可省：业务逻辑、模型、任务、管理命令、API 和运维脚本必须有可复跑验证。
- 显式优于聪明：状态机、环境变量、迁移、任务副作用和回滚路径必须写清楚。
- 失败可见：抓取、翻译、改写、发布、通知、术语发现失败要有日志、状态或后台痕迹。
- 生产可逆：高风险能力通过 `.env` 开关、灰度、备份、回滚或停用路径降低错误成本。
- 文档同步：影响项目状态、部署、决策或产品链路时，同步更新 `docs/`。

## Step 0: Read Profile & Determine Review Mode

### 0.1 Locate Active Change

If the user supplied a change name, use `openspec/changes/<name>/`.
Otherwise detect active changes:

```bash
find openspec/changes -mindepth 1 -maxdepth 1 -type d ! -name archive
```

- No active change: ask the user which plan to review.
- One active change: use it.
- Multiple active changes: ask the user to choose one.

### 0.2 Read `.openspec.yaml`

Read `<change>/.openspec.yaml` before reviewing.

- If `profile` exists, use it.
- If `profile` is missing, follow the backward-compatibility guidance from
  [`.codex/skills/workflow-spine/REFERENCE.md`](../workflow-spine/REFERENCE.md):
  default to `feature`, note the assumption, and ask the user to confirm if the
  scope is ambiguous.

Review mode:

| Profile | Review Mode | Steps Included | Max Convergence Rounds |
| --- | --- | --- | --- |
| `feature` | Full | Scope Challenge, Architecture, Code Quality, Test, Performance | 2 |
| `bug-fix` | Quick | Skip Scope Challenge; Architecture constraint compliance only; Code Quality full; Test regression only; Skip Performance | 1 |
| `ui-polish` | Quick | Skip Scope Challenge; Architecture constraint compliance only; Code Quality full; Skip logic Test; Skip Performance | 1 |

Announce at start:

```text
Review mode: [Full|Quick] (profile: [feature|bug-fix|ui-polish])
```

### 0.3 Read Project Constraints

Before reviewing artifacts, read these files in order:

1. `AGENTS.md`
2. `README.md`
3. `docs/project_overview.md`
4. `docs/current_state.md`
5. `docs/decisions.md`
6. `docs/deploy_runbook.md`
7. `docs/session_bootstrap.md`
8. `openspec/config.yaml`

If the plan touches deployment, rollback, backups, HTTPS, Nginx, production
settings, or server operations, also read:

- `docs/deploy_production.md`
- `docs/alicloud_hongkong_step_by_step.md`
- `docs/rollback_guide.md`
- `docs/backup_recovery.md`

Key constraints to enforce:

- Python 3.12 + Django 5.2; production PostgreSQL, local/test SQLite support.
- Celery Worker/Beat run crawl, translation, automation, publishing and notification tasks; Redis is broker/result backend.
- Frontend is Django templates under `server/stable/templates/` and CSS under `server/stable/static/`; no independent frontend build system.
- Data model changes require Django migrations under `server/stable/migrations/`.
- Domain logic and integrations belong in `server/stable/services/` and `server/stable/adapters/`; `tasks.py` should orchestrate.
- Runtime config comes from `.env` and `.env.example`; never commit secrets or real `.env`.
- Production uses `Dockerfile`, `docker-compose*.yml`, `deploy/`, Nginx, Gunicorn, PostgreSQL, Redis, and optional OSS.
- OpenSpec `tasks.md` items must use `(application)`, `(integration)`, or `(operations)` domain prefixes, with implementation tasks before validation tasks.
- Production conclusions must verify server `HEAD`, `.env`, container env, Nginx config, compose state, and logs when applicable.

### 0.4 Read OpenSpec Artifacts

Read the active change artifacts in order:

1. `proposal.md`
2. `design.md`
3. `specs/**/*.md`
4. `tasks.md`

If an artifact is missing, decide whether the profile permits it. For larger
features and production-risk changes, missing `design.md`, specs, or tasks is a
review blocker.

---

## Step 0.5: Scope Challenge

Quick mode skips this step.

Before reviewing quality, answer:

1. What existing code already solves each sub-problem?
   - Search `server/stable/models.py`, `services/`, `adapters/`, `tasks.py`,
     `views.py`, `forms.py`, management commands, templates, deploy scripts,
     and docs.
   - Prefer reusing current services such as `translation`, `automation`,
     `rewriting`, `validation`, `term_admin`, `term_discovery`, `pushing`,
     `notifications`, `storage`, and `operations`.

2. What is the minimum set of changes for the stated goal?
   - Flag unrelated refactors, architecture splits, new services, new
     dependencies, or deployment changes not required by the spec.

3. Complexity check:
   - More than 8 files, more than 2 new services/models/tasks, or any new
     cross-cutting dependency requires explicit justification.
   - New migrations require data/backfill/default behavior and rollback notes.
   - New production knobs require `.env.example`, settings integration, docs,
     and a verification path.

4. OpenSpec completeness check:
   - Every requirement in `specs/**/*.md` has implementation tasks.
   - Every task has `(application)`, `(integration)`, or `(operations)`.
   - Tasks with no matching requirement or design decision are possible scope
     creep unless clearly labeled as validation, migration, or docs.

If scope should be reduced, ask the user one issue at a time using the question
format below. If the AskUserQuestion tool is unavailable, ask a concise
plain-text question and wait.

---

## Review Sections

### 1. Architecture Review

Quick mode only runs the Constraint Compliance Check.

#### Constraint Compliance Check

Any violation here is a critical issue:

- Django monolith: no service split, separate SPA, background system, or
  alternative framework unless the spec explicitly approves it.
- Database: model changes have migrations; migrations are safe for PostgreSQL
  production and SQLite tests; defaults/nullability/backfills are explicit.
- Task chain: Celery work is idempotent where retries or repeated dispatch are
  possible; failures update `TaskExecutionLog`, domain status fields, or
  operation logs as appropriate.
- Settings: new runtime config is read in `server/app/settings.py`, documented
  in `.env.example`, and has conservative defaults.
- Secrets: no API keys, tokens, server passwords, or full `.env` values enter
  repo files.
- Frontend: template/static changes follow existing backend-rendered structure
  and staff/public route separation; no new build pipeline.
- Auth/admin: staff-only operations keep existing backend auth behavior; public
  routes do not expose operations-only data.
- Integrations: network calls keep timeout/error behavior and are mockable in
  tests; external API changes do not break local/CI runs.
- Deployment: Compose/Nginx/script changes preserve web/worker/beat/db/redis
  roles and include verification, rollback and docs when production-facing.
- Documentation: changes that affect project state, deployment, rollback,
  product flow, or decisions update the required `docs/` files.

#### Quality Evaluation

Evaluate the plan against current architecture:

- Model boundaries: persistent state belongs in models/migrations; derived
  decisions should be reproducible from saved fields or logged metadata.
- Service boundaries: business logic and external integration live in services
  or adapters; views and tasks should orchestrate rather than own core logic.
- Data flow: crawl -> upsert article -> optional term discovery -> translation
  -> automation score/rewrite/validate -> publish -> optional QQ/manual push.
- Transactions: accepting/merging terms, publishing, state transitions and log
  writes that must stay consistent use transactions or clear compensation.
- State machines: `WorkflowStatus`, `ArticleTranslationStatus`,
  `AutomationStatus`, candidate statuses, notification statuses and push
  statuses remain coherent.
- Rollout: production-risk features have `.env` switches, conservative
  defaults and a low-volume validation path.
- Failure scenarios: for each new codepath, name one realistic failure and how
  the plan handles it.

Stop after each architecture issue and ask the user how to resolve it.

### 2. Code Quality Review

Evaluate:

- DRY violations. Mandatory cross-boundary DRY check: when the plan introduces
  a helper, service, management command, serializer/payload, status enum,
  parser, importer, validator, notification, or deploy script logic, open the
  host module end-to-end and search related names/shapes nearby before
  approving a new abstraction.
- Existing patterns: follow similar code in `services/`, `tasks.py`, forms,
  views, templates, management commands and deploy scripts.
- Error handling: no silent broad failures for crawl, translation, AI rewrite,
  OSS, OneBot, email, import, publish, or deployment scripts.
- Query quality: avoid N+1 queries in list/detail views and batch tasks; use
  queryset filters, `select_related`, `prefetch_related`, indexes or pagination
  where needed.
- Validation: forms, management commands and services should share validation
  for CSV/import-like flows rather than fork rules.
- User-facing copy: Chinese UI and docs remain natural and consistent; machine
  keywords required by OpenSpec stay English.
- Config hygiene: `.env.example`, settings defaults and docs describe any new
  knob; production defaults are safe.
- Logs/audit: operationally important actions write `OperationLog`,
  `TaskExecutionLog`, `AutomationLog`, `NotificationLog` or equivalent state
  where current patterns expect it.
- Dependency hygiene: new Python packages, system packages or Docker images are
  justified and reflected in requirements/deploy assets.

Stop after each code-quality issue and ask the user how to resolve it.

### 3. Test Review

Quick mode behavior:

- `bug-fix`: require at least one regression test that fails on the old behavior.
- `ui-polish`: skip logic-test diagramming, but require a browser/manual
  verification task if templates/CSS or visible workflows change.

Full mode: diagram and verify coverage for:

- Model and migration behavior, including defaults, constraints and old-data
  compatibility.
- Service logic, adapters, parsers, validators, importers and state transitions.
- Celery task orchestration with `CELERY_TASK_ALWAYS_EAGER=true` where possible.
- Views/forms/API endpoints and staff/public authorization boundaries.
- Management commands and deploy/ops scripts touched by the plan.
- External integrations with mocks/fakes: netkeiba, JRA, OpenAI-compatible
  translation/rewrite, SiliconFlow, OSS, OneBot, SMTP/email.
- Edge cases: empty input, duplicate data, retry/re-dispatch, timeouts, partial
  failures, disabled feature flags, production/local config differences.

Standard verification commands to expect when relevant:

```bash
cd server
DB_ENGINE=sqlite python manage.py check
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable
cd ..
docker compose -f docker-compose.prod.yml config
docker compose -f docker-compose.prod.lowcost.yml config
```

For deployment or production-risk changes, tasks must include the applicable
runbook checks: backups, `git rev-parse --short HEAD`, `.env` key inspection,
container state, Nginx runtime config, web/worker/beat logs, `/healthz/`, and
domain/admin route smoke checks.

#### TDD-Discipline Gate (from `tdd` skill Part 2)

Applies when the change has quantifiable acceptance criteria such as latency,
coverage, batch size, quality threshold, success rate, or before/after metrics.

- Required: `tasks.md` has `## 0. Pre-declared hypotheses` before measurement
  tasks, with explicit PASS/BLOCKER thresholds.
- If missing: flag as warning, not blocker. Recommend adding the template from
  `.codex/skills/tdd/SKILL.md` Part 2 Rule 2.
- Not applicable: single regression bug fix with no measurement, pure refactor
  with no outcome metric, or UI copy/layout polish without measurable targets.

Stop after each test gap and ask the user how to resolve it.

### 4. Performance Review

Quick mode skips this step.

Evaluate:

- Database: batch tasks, candidate lists, public feed/detail, admin filters and
  import commands avoid unbounded scans and N+1 queries.
- Celery: long-running tasks have reasonable batching, timeouts, retry/idempotent
  behavior, and do not block crawl/translation/publish chains unnecessarily.
- Network/API: scraping, translation, rewrite, OSS, OneBot and email calls use
  current timeout patterns and avoid redundant calls.
- Frontend rendering: templates and CSS keep pages scannable and mobile-safe;
  no heavy rendering work in views without pagination.
- Media/static: OSS/local storage behavior remains compatible; static/media
  routing through Nginx is preserved.
- Deployment/runtime: Gunicorn, worker, beat and Redis assumptions remain valid
  under both production compose files.

Stop after each performance issue and ask the user how to resolve it.

---

## AskUserQuestion Format

One issue per question. Use this shape:

```text
Context: [current artifact/task being reviewed]
Problem: [plain explanation and why it matters]
RECOMMENDATION: Choose [X] because [reason]
Options:
A) Complete approach - (~X min with AI)
B) Simpler approach - (~Y min with AI)
C) Skip / defer - [risk]
```

---

## Required Outputs

### What Already Exists

List reusable code and patterns already present, such as models, services,
adapters, task helpers, forms, management commands, templates, deploy scripts,
and docs.

### NOT in Scope

List work considered and explicitly deferred, with one-line rationale each.

### Failure Modes

For each new codepath, include one realistic failure scenario and whether:

1. A test covers it.
2. Error handling or rollback exists.
3. The operator/user sees a clear signal or the failure is silent.

If a failure mode has no test, no handling and silent user/operator impact,
flag it as a critical gap.

### Completion Summary

```text
Plan Engineering Review Summary
================================
Review rounds: N (converged at round N / max rounds reached)

Step 0: Scope Challenge — [accepted as-is / scope reduced / skipped]
Architecture Review: N issues found
Code Quality Review: N issues found
Test Review: N gaps identified
Performance Review: N issues found
Consistency check: N inconsistencies found and fixed / All artifacts consistent

What already exists: [listed]
NOT in scope: [listed]
Failure modes: N critical gaps flagged

Next: Ready for implementation.
```

---

## Artifact Consistency Check (Mandatory)

After review issues are resolved and artifacts are updated:

1. Re-read `proposal.md`, `design.md`, `tasks.md`, and all `specs/**/*.md`.
2. Check every review decision against every artifact that references the same
   topic.
3. Fix inconsistencies immediately.
4. Report the result in the completion summary.

Check especially:

| Topic | Stale Locations |
| --- | --- |
| Model/migration fields | design decisions, spec fields, task steps |
| Env flags/settings | design, tasks, `.env.example` docs tasks |
| Celery task flow | design flow, spec scenarios, task ordering |
| Auth/admin/public routes | specs, design, templates/API tasks |
| Deployment/rollback | design risks, operations tasks, docs tasks |
| Test/verification commands | tasks, design migration plan, runbook updates |

---

## Convergence Check (Mandatory)

Goal: ensure review fixes did not introduce second-order issues.

1. Count artifact files modified and issues resolved in this pass as
   `delta_this_pass`.
2. If `delta_this_pass > 0` and `round < max_rounds`, run a focused re-review:
   - Round 2 reads only modified artifacts plus directly referenced spec/design
     passages unless ledger data is missing.
   - De-duplicate findings already resolved or deferred in this session.
   - Ask about genuinely new issues one at a time.
   - Run Artifact Consistency Check again.
3. If `delta_this_pass == 0` or `round == max_rounds`, produce the completion
   summary. If max rounds are reached with unresolved issues, list them under
   `Remaining issues — defer to next session`.

Round cap:

- Full mode: 2.
- Quick mode: 1.

---

## Write Ledger Entry

Before writing the journal event, persist the audit trail to
`<change>/.sidecar/ledger.json` using `ledger.json schema v1.0` in
[`references/gate-templates.md`](references/gate-templates.md#ledgerjson-schema-v10).

Skip this step when `<change>/.sidecar/` does not exist. Do not auto-create
sidecar for legacy changes. Continue to YAML state using in-memory counts.

Required ledger behavior:

- One `plan-eng-review` session writes one entry; Round 2 updates the same entry.
- Use `date -Iseconds` immediately before the write for `timestamp` or `last_updated`.
- If `ledger.json` is malformed, back it up to `.json.bak.<unix-ns>` and reset to `{"schema_version":"1.0","entries":[]}` before appending.
- Track `source`, `session`, `round`, `timestamp`, `last_updated`, `mode`,
  `artifacts_modified`, `rounds_total_for_session`, `issues_resolved`, and
  `findings`.
- Findings use stable ids `F-001`, `F-002`, ... and fields `id`, `severity`,
  `category`, `summary`, `resolution`, `status`, `round_found`,
  `round_resolved`.

---

## Write YAML State

After the ledger entry, or after intentionally skipping legacy sidecar, update
`<change>/.openspec.yaml`:

- Set `phase: reviewed`.
- Append one `plan-reviewed` journal event following
  [`.codex/skills/workflow-spine/REFERENCE.md`](../workflow-spine/REFERENCE.md).
- Run `date -Iseconds` immediately before writing; do not hand-type timestamps.
- `rounds` and `issues_resolved` must match the ledger entry or in-memory
  legacy counts.

Template:

```yaml
- event: plan-reviewed
  date: "<date -Iseconds output>"
  session: 1
  mode: full
  rounds: 2
  issues_resolved: 5
  artifacts_modified: [design.md, tasks.md]
  note: "Round 1 resolved ...; Round 2 converged."
```

Post-write, read `.openspec.yaml` back and verify:

- `phase` is `reviewed`.
- The new timestamp is later than previous events.
- `session` is incremented correctly for repeated `plan-reviewed` events.
- Listed modified artifacts exist and are non-empty.

---

## Next-Step Output

After the summary, print:

```text
## 下一步

Profile: [profile] | Phase: reviewed | Review rounds: N

推荐: /openspec-apply-change — 开始逐 task 实现

可选: /push — 先提交已审查的 OpenSpec 文档
   └ 仅提交 OpenSpec 文档，phase 保持 reviewed
   └ 实现者开新对话后运行 /openspec-apply-change {change-name}

不建议: /openspec-archive-change — 还没有代码实现
```

---

## Escalation

Stop and escalate when:

- Tried 3 times without resolving the same issue.
- Security, secrets, production data, migration rollback, or HTTPS behavior is
  uncertain.
- The scope cannot be verified from repository artifacts.
- The plan requires real server inspection but no server access/context exists.

Use:

```text
STATUS: BLOCKED | NEEDS_CONTEXT
REASON: [1-2 sentences]
ATTEMPTED: [what was tried]
RECOMMENDATION: [what to do next]
```
