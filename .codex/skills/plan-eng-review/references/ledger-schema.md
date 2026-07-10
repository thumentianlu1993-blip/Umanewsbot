# Ledger Schema v1.0

`plan-eng-review` writes review audit data to:

```text
openspec/changes/<change>/.sidecar/ledger.json
```

The container shape is:

```json
{
  "schema_version": "1.0",
  "entries": []
}
```

Each plan review session appends one entry:

```json
{
  "source": "plan-eng-review",
  "session": 1,
  "round": 1,
  "timestamp": "2026-06-09T15:00:00+08:00",
  "last_updated": "2026-06-09T15:00:00+08:00",
  "mode": "full",
  "artifacts_modified": ["design.md", "tasks.md"],
  "rounds_total_for_session": 1,
  "issues_resolved": 1,
  "findings": [
    {
      "id": "F-001",
      "severity": "warning",
      "category": "test",
      "summary": "Missing vertical Chinese text export fixture",
      "resolution": "Added task 8.x for fixture coverage",
      "status": "resolved",
      "round_found": 1,
      "round_resolved": 1
    }
  ]
}
```

Finding fields:

- `id`: stable session-local ID such as `F-001`
- `severity`: `critical`, `warning`, or `info`
- `category`: `scope`, `architecture`, `code-quality`, `test`, `performance`, or `consistency`
- `summary`: one-line issue
- `resolution`: one-line fix, decision, or `N/A`
- `status`: `resolved`, `deferred`, or `open`
- `round_found`: review round number
- `round_resolved`: review round number or `null`

Readers should treat the latest `source == "plan-eng-review"` entry for a change as the active plan review.
