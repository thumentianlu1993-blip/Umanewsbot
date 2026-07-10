# Workflow Spine

This skill uses a small OpenSpec workflow state convention.

Each change has:

```text
openspec/changes/<change>/.openspec.yaml
```

Expected fields:

```yaml
schema: spec-driven
created: "2026-06-09T15:00:00+08:00"
profile: feature
phase: reviewed
journal:
  - event: plan-reviewed
    date: "2026-06-09T15:10:00+08:00"
    session: 1
    mode: full
    rounds: 1
    issues_resolved: 0
    artifacts_modified: []
    note: "Plan reviewed; no blocking issues."
```

Phase meanings:

| Phase | Meaning |
| --- | --- |
| `proposed` | Proposal/design/specs/tasks are ready for review |
| `reviewed` | Plan has passed engineering review |
| `implementing` | Implementation has started |
| `archived` | Change has been archived |

Journal write rules:

1. Read the full `.openspec.yaml` before editing.
2. Use `date -Iseconds` immediately before writing any new event.
3. Number repeated event types with `session: N`.
4. Journal is append-only. Do not rewrite older entries except for narrow timestamp correction.
5. After writing, read the file back and check counters match the summary.

`plan-reviewed` event fields:

| Field | Required | Meaning |
| --- | --- | --- |
| `event` | yes | `plan-reviewed` |
| `date` | yes | ISO 8601 timestamp with timezone |
| `session` | yes | increments per plan review session |
| `mode` | yes | `full` or `quick` |
| `rounds` | yes | convergence rounds in this session |
| `issues_resolved` | yes | resolved findings count |
| `artifacts_modified` | optional | changed artifact paths |
| `note` | optional | short review summary |
