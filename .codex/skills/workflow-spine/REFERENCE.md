# Workflow Spine — Protocol Reference

Canonical reference for the **cross-skill coordination layer** of OpenSpec workflow skills. Referenced by `openspec-propose`, `plan-eng-review`, `openspec-apply-change`, `review`, `openspec-verify-change`, `openspec-archive-change`, `openspec-continue-change`, and `push`.

Design principle: **one SOP, one straight line — each step writes exactly one event**. Absence of the next event means the flow is paused; no explicit pause event needed.

---

## 1. Journal Write Protocol

Every OpenSpec change directory contains a `.openspec.yaml` with top-level metadata + a `journal` append-only event log.

### 1.1 Top-level fields

| Field | Type | Required | Values |
| --- | --- | --- | --- |
| `schema` | string | yes | Currently always `spec-driven` |
| `created` | string | yes | ISO 8601 datetime, e.g. `2026-04-19T14:30:00+08:00` |
| `profile` | enum | yes after propose | `feature` \| `bug-fix` \| `ui-polish` |
| `phase` | enum | yes after propose | `proposed` → `reviewed` → `implementing` → `archived` → `shipped` |
| `journal` | list | yes | Append-only event log; see 1.2 |

Phase transitions (linear, 5 states):

| Phase | Entered by | Meaning |
| --- | --- | --- |
| `proposed` | `openspec-propose` | Proposal artifacts written, awaiting review |
| `reviewed` | `plan-eng-review` | Plan approved, awaiting implementation |
| `implementing` | `openspec-apply-change` (first run) | Tasks in progress — covers apply + review + verify |
| `archived` | `openspec-archive-change` | Change moved to `openspec/changes/archive/YYYY-MM-DD-<name>/` |
| `shipped` | `push` (post-archive) | Branch merged to main |

If apply discovers a design issue mid-task: pause (just stop writing events), bump `phase` back to `reviewed`, re-run `plan-eng-review` which appends a new `plan-reviewed` event, then `openspec-apply-change` resumes. No separate `amending` phase needed.

### 1.2 Pre-write discipline (MANDATORY for every agent)

Before writing any entry to `.openspec.yaml`:

1. **Read the full current file first.** Use the Read tool; do not Edit blind. Verify:
   - Current `phase` and whether your write is a legal transition.
   - Prior events of the SAME event type you're about to append. Repeated event types (`plan-reviewed`, `code-reviewed`, `verified`) appear multiple times across sessions — you must know how many already exist to number the new one correctly.
   - Any existing counters (`tasks_total`, `rounds`, `issues_resolved`) so you don't mis-baseline.

2. **Obtain the timestamp by running `date -Iseconds` (or equivalent system clock call) IMMEDIATELY before the write.** This is non-negotiable.

   - **MUST**: run `date -Iseconds` (Linux/macOS) or `date '+%Y-%m-%dT%H:%M:%S%z' | sed 's/\(..\)$/:\1/'` (POSIX) within the same tool-call window as the YAML edit. Capture the output. Use the captured string verbatim as the `date:` field value.
   - **MUST NOT**: hand-type a "looks plausible" timestamp, round to the nearest minute for tidiness, or copy the previous event's timestamp + offset a few minutes. Any of those falsifies the audit trail — `journal[].date` is the single signal readers use to reconstruct cross-event timing, and integer-minute / copy-paste timestamps quietly break that.
   - **MUST NOT**: re-use a stale timestamp captured at the start of the skill run for an event written near the end. Each journal event written gets its own fresh `date -Iseconds` call.
   - **If the inline writer uses an env var like `NOW_ISO8601`** (plan-eng-review / review ledger writers), export it as `NOW_ISO8601="$(date -Iseconds)"` in the same command line. Never pass a literal string.
   - **For Python heredoc writers** that compute timestamps in-process (e.g. `datetime.now(timezone.utc).isoformat()`), the in-process call satisfies this rule — no shell `date` call needed since the timestamp comes from the system clock at write time. The forbidden pattern is the LLM agent typing a literal timestamp into the YAML.

3. **Number repeated events with an explicit `session: N` field.** For event types that can legally appear more than once (`plan-reviewed` after apply-pause re-review; `code-reviewed` after each /review run; `verified` if verification is re-run), add `session: 1` on the first occurrence and increment for each subsequent occurrence within the same change. Without `session`, readers cannot distinguish "two independent sessions" from "one session that wrote twice by mistake".

4. **Post-write self-check.** After writing the entry, Read it back and verify every numeric field is self-consistent with its `notes` narrative:
   - If `notes` says "Round 1 → 2 → 3 converged", `rounds` MUST equal `3` (not `2`, not `4`).
   - If `notes` lists 6 resolved issues, `issues_resolved` MUST equal `6`.
   - If `artifacts_modified` is claimed, each file MUST actually be on disk and non-empty post-write.
   - **Timestamp sanity**: the new `date:` MUST be strictly later than the previous event's `date:` (or `created:` for the first event). If you see an integer-minute timestamp (`HH:MM:00`) or one that pre-dates the prior event by any amount, it was fabricated — re-run `date -Iseconds` and overwrite before moving on.

5. **Never rewrite past entries for content.** Journal is append-only. If a prior entry was wrong, append a new one that supersedes it AND add a parenthetical in the old entry's `notes` field pointing at the corrected entry. (Editing a prior entry's `notes` to add a correction reference is the one allowed retroactive write.) **Timestamp correction is the one explicit exception**: if a prior entry's `date` was fabricated (caught by the post-write self-check above OR flagged by the user), you MAY overwrite that single field to a more accurate value — never widen the edit beyond the one stale field. Add a `# corrected via <reason>` end-of-line comment to mark the audit lineage.

### 1.3 Journal events (8 canonical)

Each entry is a dict with `event` + `date` + event-specific fields.

- `date` is **ISO 8601 with timezone offset**: `YYYY-MM-DDTHH:MM:SS±HH:MM` (e.g. `2026-04-19T14:30:00+08:00`). UTC form `YYYY-MM-DDTHH:MM:SSZ` is also acceptable.
- Journal is **append-only**: never rewrite past entries for content. See 1.2 for the one allowed retroactive write (correction pointer in `notes`).

#### `proposed`

Fired by `openspec-propose` after artifacts complete. → phase: `proposed`

| Field | Required | Purpose |
| --- | --- | --- |
| `profile` | yes | Confirms inferred/user-chosen profile |
| `artifacts` | yes | List: `[proposal, tasks]` or `[proposal, design, specs, tasks]` |
| `tasks_total` | yes | Count of `- [ ]` items in tasks.md |
| `note` | optional | One-liner context |

```yaml

- event: proposed
  date: "2026-04-19T14:30:00+08:00"
  profile: bug-fix
  artifacts: [proposal, tasks]
  tasks_total: 20
  note: "one-line summary"
```

#### `plan-reviewed`

Fired by `plan-eng-review` after completion summary. → phase: `reviewed`

| Field | Required | Purpose |
| --- | --- | --- |
| `session` | yes if ≥2nd occurrence | Session number for this event type; `1` on first, increment for re-reviews. See 1.2 #2. |
| `mode` | yes | `full` (feature) \| `quick` (bug-fix / ui-polish) |
| `rounds` | yes | Convergence round count **within this session** (1 = single-pass converge). Must match `notes` narrative. See 1.2 #3. |
| `issues_resolved` | yes | Total issues found & fixed in this session |
| `artifacts_modified` | optional | Files edited during review |
| `note` | optional | Issue summary |

A second (or later) `plan-reviewed` may be appended if apply paused mid-task and `plan-eng-review` ran again, or if the user invokes a sanity re-review. Each occurrence MUST carry an incrementing `session: N` field. The **latest entry** supersedes prior ones for gate-check purposes.

```yaml

- event: plan-reviewed
  date: "2026-04-19T15:00:00+08:00"
  session: 1
  mode: quick
  rounds: 1
  issues_resolved: 2
  artifacts_modified: [tasks.md]
  notes: >
    Round 1 resolved 2 issues (...). No delta — converged first pass.
```

#### `apply-started`

Fired by `openspec-apply-change` on first apply invocation. → phase: `implementing`

| Field | Required | Purpose |
| --- | --- | --- |
| `tasks_total` | yes | Snapshot at start |
| `branch` | optional | Git branch name for traceability |

```yaml

- event: apply-started
  date: "2026-04-19T15:10:00+08:00"
  tasks_total: 20
  branch: "chore/my-change"
```

#### `apply-completed`

Fired when all non-deferred tasks in tasks.md are done. Phase unchanged (still `implementing`).

| Field | Required | Purpose |
| --- | --- | --- |
| `tasks_done` | yes | Final count |
| `tasks_total` | yes | |
| `tasks_deferred` | optional | Count marked `[~]` with rationale |
| `note` | optional | Outcome summary |

#### `code-reviewed`

Fired by `review` skill after emitting `<!-- review-checkpoint: HASH -->`. Phase unchanged.

| Field | Required | Purpose |
| --- | --- | --- |
| `session` | yes if ≥2nd occurrence | Session number for this event type; `1` on first, increment for re-reviews. See 1.2 #2. |
| `checkpoint_hash` | yes | Git HEAD at review time |
| `findings` | optional | Summary count (e.g. `"0 critical, 2 warnings"`) |
| `resolution` | optional | How findings were handled |
| `scope` | optional | Domain scope |
| `note` | optional | |

Multiple `code-reviewed` entries commonly appear (first review + post-fix re-review). Each must carry an incrementing `session: N`.

#### `verified`

Fired by `openspec-verify-change` after report. Phase unchanged.

| Field | Required | Purpose |
| --- | --- | --- |
| `session` | yes if ≥2nd occurrence | Session number for this event type; `1` on first, increment for re-verifies. See 1.2 #2. |
| `dimension` | yes | `completeness` \| `correctness` \| `coherence` \| `all` |
| `result` | yes | `passed` \| `failed` |
| `note` | optional | Issues summary if failed |

If `failed`: fix issues then append a second `verified` with `session: 2`, `passed`. The latest event wins for gate-check.

#### `archived`

Fired by `openspec-archive-change` after `mv` to archive directory. → phase: `archived`

| Field | Required | Purpose |
| --- | --- | --- |
| `archived_to` | yes | New path |
| `verify_result` | yes | Snapshot from last `verified` event |
| `specs_synced` | yes | Whether main specs were updated |
| `specs_sync_reason` | optional | If not synced, why |

#### `pushed`

Fired by `push` skill when the archived change reaches main. → phase: `shipped`

Pushes during `reviewed` or `implementing` (doc-only push, intermediate WIP push) are **not** journal events — they are git operations, not SOP nodes. Only the post-archive push that ships code to main gets journaled.

| Field | Required | Purpose |
| --- | --- | --- |
| `branch` | yes | Git branch that was merged |
| `mr` | optional | MR / PR URL or number |
| `note` | optional | |

```yaml

- event: pushed
  date: "2026-04-19T17:00:00+08:00"
  branch: "chore/my-change"
  mr: "!627"
```

### 1.3 Rules

1. **Append-only**: journal events are never edited or deleted. If correction needed, append a superseding event.
2. **AI writes, users don't**: `.openspec.yaml` is maintained **by AI during skill execution**. The project `openspec/CLAUDE.md` rule "不要手动修改" applies to **users**, not AI.
3. **Timestamp format**: always ISO 8601 with timezone (`YYYY-MM-DDTHH:MM:SS+HH:MM` or `...Z`). Generate with:

   ```bash
   date "+%Y-%m-%dT%H:%M:%S%z" | sed 's/\(..\)$/:\1/'    # local time + offset
   # or:
   date -u "+%Y-%m-%dT%H:%M:%SZ"                           # UTC
   ```

4. **Absence ≠ error**: if an expected next event is missing, the flow is simply paused between steps. No explicit pause event is written.
5. **Missing REFERENCE.md ≠ skip**: if this file seems missing, read sibling `.openspec.yaml` files under `openspec/changes/` for format cues — do not stall.

---

## 2. Dual-Channel Gate Check Protocol

Used by skills that gate on a prior step being complete:

- `openspec-apply-change` requires `plan-reviewed`
- `openspec-archive-change` requires `verified` with `result: passed`

### 2.1 Order of checks

1. **Channel 1 (persistent)** — Read `.openspec.yaml` → scan `journal` (most recent matching event wins).
2. **Channel 2 (fallback)** — Search conversation history for the required skill's distinctive output marker (`"Plan Engineering Review Summary"`, `"Verification Report"`, etc).
3. **Neither found** — Use `AskUserQuestion` to let user either run the missing skill or skip with a warning.

### 2.2 Why two channels

- Channel 1 is authoritative across sessions — a session days later can still check.
- Channel 2 covers cases where the file wasn't written but the user did run the skill in the current conversation.

### 2.3 Gate action when PASSED

Skip the ask, log a one-liner (`Gate: <name> PASSED via Channel 1 (journal)`) and continue.

---

## 3. Session Resume Protocol

Used by `openspec-apply-change` when re-entering a change across sessions.

### 3.1 Source of truth

**`tasks.md` checkbox state is the authority** — journal events are informational.

1. Parse tasks.md:
   - `- [x]` = done
   - `- [ ]` = pending
   - `- [~]` = deferred with rationale (count as done for completion, note in output)
2. Compute progress: `done / (done + pending)`.

### 3.2 Presentation

If some tasks are `[x]` and `apply-started` is in the journal:

```text
Resuming: {done}/{total} tasks complete (from tasks.md).
Next: {first unchecked task}.
```

If the gap between `apply-started` and now is large (e.g. days), include the start timestamp for context. Otherwise stay terse.

### 3.3 Phase behavior on resume

| Current phase | Action |
| --- | --- |
| `proposed` or `reviewed` | First apply — set phase to `implementing`, append `apply-started` |
| `implementing` | Resume — continue silently (no new event). Progress comes from tasks.md |
| `archived` / `shipped` | Refuse — change is sealed; suggest a new change |

---

## 4. Next-Step Output Template

Every skill that completes a step emits a `## 下一步` block.

### 4.1 Format

```text

## 下一步

Profile: <profile> | Phase: <phase> | [extra status]

✅ 推荐: /<next-skill> — <one-line reason>

[🟡 可选: /<alt-skill> — <alt reason>]

[⚠ 不建议: /<discouraged-skill> — <why discouraged>]
```

### 4.2 Skill chain

| Just completed | Phase after | Recommended next |
| --- | --- | --- |
| `openspec-propose` | `proposed` | `/plan-eng-review` |
| `plan-eng-review` | `reviewed` | `/opsx:apply` (or `/push` to hand off docs to another dev) |
| `openspec-apply-change` (all tasks done) | `implementing` | `/review` |
| `openspec-apply-change` (session ending mid-task) | `implementing` | `/opsx:apply <name>` (resume next session) |
| `review` | `implementing` | `/opsx:verify` |
| `openspec-verify-change` (passed) | `implementing` | `/opsx:archive` |
| `openspec-verify-change` (failed) | `implementing` | Fix issues → re-run `/opsx:verify` |
| `openspec-archive-change` | `archived` | `/push` |
| `push` (post-archive) | `shipped` | ✅ Done |

Mid-implementation pushes (docs-only after plan-review, or WIP commits during apply) do not need a journal event and are not "SOP steps" — run them as plain git operations.

### 4.3 Discouragement rules

When the user is about to take an out-of-order action, include `⚠ 不建议`. Examples:

- `/opsx:archive` before `/opsx:verify` passed
- `/push` for final-ship before `/opsx:archive`
- `/opsx:verify` before any `apply-completed`

---

## 5. Multiple Active Changes Detection Protocol

Used by `push` and `review` to identify the relevant change.

### 5.1 Discovery

```bash
openspec list --json
```

Returns all changes in `openspec/changes/` (excluding `archive/`) with `name`, `status`, `completedTasks`, `totalTasks`, `lastModified`.

### 5.2 Selection logic

| Condition | Action |
| --- | --- |
| 0 active changes | Treat as "regular" push / review (no change context) |
| 1 active change | Auto-select — announce `Using change: <name>` |
| 2+ active changes | Read each `.openspec.yaml` `phase` field. Prefer the change whose phase matches the current skill's stage (e.g. `push` prefers `archived`). If still ambiguous, use `AskUserQuestion` to let user choose. |

### 5.3 Conflict resolution

```text
Found 2 active changes:

  1. foo-feature (phase: implementing, 12/20 tasks)
  2. bar-fix (phase: reviewed, 0/8 tasks)

Which applies to this push?
```

---

## 6. Backward Compatibility Protocol

For reading older changes that predate this REFERENCE.md format.

### 6.1 Missing `profile`

1. Default to `feature` (safest — most rigorous flow).
2. Inform the user: `⚠ Legacy change without profile. Defaulting to feature flow. Set 'profile: <bug-fix|ui-polish|feature>' explicitly for lighter flow.`
3. Do not auto-modify the yaml.

### 6.2 Missing `phase`

Infer from the latest journal event:

| Latest event | Infer phase |
| --- | --- |
| `proposed` | `proposed` |
| `plan-reviewed` | `reviewed` |
| `apply-*`, `code-reviewed`, `verified` | `implementing` |
| `archived` | `archived` |
| `pushed` | `shipped` |

Write the inferred `phase` field. One-time backfill is acceptable.

### 6.3 Missing journal

Infer from artifact file existence:

- Has `proposal.md` only → `proposed`
- Has `proposal.md` + `tasks.md` → `proposed` (awaiting review)
- Has committed tasks and `[x]` checkboxes → `implementing`

### 6.4 Unknown event types in legacy archives

If an old archive contains events not in §1.2 (this protocol's predecessor used different names), treat them as **informational-only** — do not gate on them. For gate-check semantics, look for the canonical 8 names only. Do not rewrite legacy events.

---

## 7. Sidecar Protocol

Structured per-session audit data lives in a single file `openspec/changes/<name>/.sidecar/ledger.json` alongside the journal. Sidecar holds **finding/decision content**; journal holds **flow position**. The previous 4-file sidecar matrix (constraints / context / map / ledger) was slimmed to ledger-only by `slim-workflow-protocol` — Decisions 1-4 deleted hash invalidation, schema-version enforcement, constraint+context indices, and the map.json writer entirely.

### 7.1 Sidecar 文件矩阵 + 白名单

Path: `openspec/changes/<change-name>/.sidecar/` (with `.openspec.yaml` as a sibling).

| 文件 | Writer | Reader | 写入时机 |
| --- | --- | --- | --- |
| `ledger.json` | `plan-eng-review` (inline Python in SKILL.md); `openspec-verify-change`; `review` (inline Python in SKILL.md) | `review` (inline read gate); `push` (Step 10a inline audit-lineage renderer); `openspec-archive-change` | 每个审查 session 结束时 append findings + decisions；reader 契约见 [`gate-templates.md ## ledger.json reader contract`](../openspec-propose/references/gate-templates.md#ledgerjson-reader-contract) |

**白名单**：`.sidecar/` 目录只允许 `ledger.json`。任何其它 evidence / baseline / 中间数据文件 MUST 放在 change 根目录或 `evidence/` 子目录。已 archived changes 中违反白名单的遗留文件不强制迁移，仅约束未来新写入。

`ledger.json` 顶层字段 `schema_version: "1.0"` 作为 future-proof 标记，但 reader 不强制校验（per `slim-workflow-protocol` Decision 2）。Entry shape 在 [`gate-templates.md § "ledger.json schema v1.0"`](../openspec-propose/references/gate-templates.md#ledgerjson-schema-v10) —— 容器 + entry + finding 三层结构、Round 2 dedup 规则、defensive recovery 行为均在该处文档化。

### 7.2 与 Journal 协议的关系

§1 Journal 记录 **phase 转换事件**（proposed / reviewed / implementing / archived / shipped）和量化摘要（rounds、issues_resolved、tasks_done 等数值）。§7 Sidecar `ledger.json` 记录 **结构化 finding 数据**（findings 内容、resolution、status）。

**不重叠原则**：

- 一份 finding 的"标题 + severity + resolution 详情"属于 ledger.json，不属于 journal `notes`
- 一次 phase 转换的"事件类型 + 时间戳 + 量化摘要"属于 journal，不属于 sidecar
- review 找到的 N 个 finding：journal 写 `issues_resolved: N`，ledger.json 写 N 条 entries（标题 + resolution）

### 7.3 Backward compatibility

老 change（创建于本协议落地之前，或本次 slim 之前的 4 文件 sidecar 阶段）的处理路径：

1. 所有 ledger reader 必须 fallback 到"无 dedup / 无 audit-table"行为；不抛错
2. 不 auto-create sidecar；保持老 change 不被无声修改
3. 老 change 内遗留的 `constraints.json` / `context.json` / `map.json` / `*.bak.*` 文件不再被读取，留作历史记录
4. 老 change reader 路径 fallback：`.sidecar/` 不存在 → 直接读原文（design.md / tasks.md / specs / CLAUDE.md）

---

## Cross-reference index

Which skills use which protocols / sidecars:

| Skill | Protocols used | Sidecar reads / writes |
| --- | --- | --- |
| `openspec-propose` | Journal Write (write `proposed`), Next-Step | **Writes** empty `ledger.json` skeleton inline (no constraint/context/map files) |
| `openspec-continue-change` | Journal Write (informational only), Multiple Active Changes | (None — fluid action) |
| `plan-eng-review` | Backward Compatibility (read profile), Journal Write (write `plan-reviewed`), Next-Step | **Writes** `ledger.json` entries inline (one session = one entry; Round 2 updates same entry). No sidecar reads — reads CLAUDE.md / design.md / tasks.md / specs/ originals directly |
| `openspec-apply-change` | Dual-Channel Gate Check (require `plan-reviewed`), Session Resume, Journal Write (write `apply-started` / `apply-completed`) | (None — reads tasks.md original; no map writing) |
| `review` | Multiple Active Changes, Journal Write (write `code-reviewed`), Next-Step | **Reads** `ledger.json` inline gate (build resolved_set for dedup; legacy fallback to no-dedup full scan; read-only). **Writes** `ledger.json` entry inline (one session = one entry, `source: "review"`, defensive recovery mirrors plan-eng-review writer) |
| `openspec-verify-change` | Journal Write (write `verified`), Next-Step | **Reads** specs/tasks/design originals via `verify-bidirectional.py` set-based check (no map.json read; no sidecar reads). **Writes** `ledger.json` verdict + `verified` journal event |
| `openspec-archive-change` | Dual-Channel Gate Check (require `verified`), Journal Write (write `archived`) | **Reads** `ledger.json` for one-shot audit |
| `push` | Multiple Active Changes, Journal Write (write `pushed` only when phase was `archived`), Next-Step | **Reads** `ledger.json` for MR audit lineage table (Step 10a inline; legacy fallback omits table; read-only) |

---

## Maintenance

Update this file when:

- A new canonical `event` type is introduced (add schema + example to §1.2)
- A new canonical `phase` value is introduced (update §1.1 table)
- A skill starts / stops referencing this file (update Cross-reference index)

Do NOT update for:

- Transient facts (current change states)
- Historical / legacy event names already covered by §6.4
- Convenience events used ad-hoc in a single change (they belong in that change's `note` field, not here)
