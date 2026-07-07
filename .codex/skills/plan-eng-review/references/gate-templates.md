# Quality Gate Templates (openspec-propose skill)

本文件是 `openspec-propose` skill 的契约参考。SKILL.md 通过 markdown link 引用这里的模板和规则；不要把内容内联回 SKILL.md。

`slim-workflow-protocol` 已删除：constraints.json schema、map.json schema + reader contract、Schema versioning section、Self-Lint Rule 1 / 3 / 9、CLAUDE.md anchor format script contract。`ledger.json` 是唯一保留的 sidecar 文件。

---

## Alternatives Considered 模板（结构 A）

适合 single-pivotal change（整个 change 围绕一个总体方案选择）：

```markdown

## Alternatives Considered

### 方案 A (Recommended) <!-- adr: adr-NNN-<short-slug> -->

实现要点：...

风险点：...
改动范围：N 文件
可逆性：高 (feature flag: feature.xxx)

### 方案 B

实现要点：...
被否理由：...

### 方案 C (optional)

...
```

要求：

- ≥ 2 个候选；exactly 1 标 `(Recommended)`，且 `(Recommended)` 候选有 `<!-- adr: adr-NNN-<slug> -->` HTML marker
- 单方案 case 接受 `### 方案 B (不存在合理替代)` 占位 + 论证为什么 B/C 都不行
- bug-fix 接受 `### 方案 B (do nothing)` + 描述不修代价

---

## Decisions 模板（结构 B）

适合 multi-decision change（多个 fine-grained 选择）：

```markdown

## Decisions

### Decision 1: <title> <!-- adr: adr-NNN-<short-slug> -->

**Choice：** ...

**Why：** ...

**Alternatives considered：**

- 备选 1 — 被否理由
- 备选 2 — 被否理由

### Decision 2: <title> <!-- adr: adr-NNN-<short-slug> -->

...
```

要求：

- ≥ 2 个 `### Decision N`；每个有 `<!-- adr: adr-NNN-<short-slug> -->` HTML marker（紧跟标题）
- 每个 Decision 都有 `**Alternatives considered：**` 子段，列 ≥ 1 个被否备选 + 被否理由
- ADR id 在单个 change 内唯一（adr-001, adr-002, ... 顺序自增）

**结构选择**：同一份 design.md 二选一不要混用结构 A 与 B。单方案 → A；多 decision → B。

---

## ADR / req id HTML Marker Convention

设计动机：让 task 后缀引用稳定，不随 spec heading 改名而漂移；markdown 渲染时 HTML 注释不可见，git diff 可见。

### ADR id（design.md）

```markdown

### Decision 1: <title> <!-- adr: adr-NNN-<short-slug> -->
```

或结构 A 推荐方案：

```markdown

### 方案 A (Recommended) <!-- adr: adr-NNN-<short-slug> -->
```

约束：

- 格式 `adr-NNN-<short-slug>`：`NNN` 三位数字（001, 002, ..., 单 change 内顺序递增），`<short-slug>` 是 kebab-case ≤ 4 词
- short-slug 描述性而非全标题
- 单 change 内 adr-id 唯一（Self-Lint Rule 4 校验重复）；跨 change 不要求全局唯一

### Requirement id（specs/**/spec.md）

```markdown

### Requirement: <name> <!-- id: req-<short-slug> -->
```

约束：

- 格式 `req-<short-slug>`：kebab-case ≤ 4 词（不带数字编号）
- short-slug 描述性
- 单 change 内 req-id 唯一

### tasks.md 引用

```markdown

- [ ] 1.1 创建 SomeService.py             (adr: adr-001-some-service)
- [ ] 2.1 新增 spec: 上传幂等性            (req: req-upload-idempotent)
```

约束：

- 每个 `- [ ]` task 行末必须有 `(req: <id>)` 或 `(adr: <id>)` 后缀（`## 0. Pre-declared Hypotheses` 段例外，直到下一 `##` heading 之前）
- 引用的 id 必须真实存在于 design.md / spec.md 的 HTML marker（Self-Lint Rule 6 / 7 校验）
- 一个 task 可同时引用 ≥ 1 个 id：`(req: req-foo) (adr: adr-002-bar)`

---

## Self-Lint Rules

`self-lint.sh` 跑结构整合性规则，全部基于结构（grep / 集合比对 / 段落识别），不引入语义判断。成功输出为 count-free `LINT: PASS`。脚本接受两种调用：`--change <name>`（在 `openspec/changes/<name>/`）或 `--change-dir <path>`（任意目录，含 archive/）。

稀疏编号（2 / 4 / 5 / 6 / 7 / 8 / 10）保留，避免重新编号破坏既有引用：

| # | 规则 | 实现 | 失败信息模板 |
| --- | --- | --- | --- |
| 2 | design.md 满足结构 A 或结构 B（B 接受 ≥2 Decision 各带 Alternatives，或 1 Decision + Alternatives 子段含 ≥2 bullets） | grep + python 段落分组 | `LINT: FAIL Rule 2 — design.md needs ≥2 Alternatives (...); found <count>` |
| 4 | design.md 至少有一个 `<!-- adr: adr-NNN-<slug> -->` HTML marker；同 design 内重复 → fail | regex + python 集合 | `LINT: FAIL Rule 4 — design.md needs ≥1 <!-- adr: ... --> marker` 或 `duplicate adr id: <id>` |
| 5 | tasks.md 每个 `- [ ]` 行末有后缀；Hypotheses 段例外 | grep + python 段落识别 | `LINT: FAIL Rule 5 — N tasks missing req/adr suffix: <line numbers>` |
| 6 | tasks.md 引用的 req-id 全部存在于 specs/**/*.md 的 HTML markers | python 集合比对 | `LINT: FAIL Rule 6 — task <line> references undefined req: req-X` |
| 7 | tasks.md 引用的 adr-id 全部存在于 design.md 的 HTML markers | python 集合比对 | `LINT: FAIL Rule 7 — task <line> references undefined adr: adr-X` |
| 8 | 每个 spec `<!-- id: req-X -->` 至少有 1 个 task 引用 | python 集合比对 | `LINT: FAIL Rule 8 — requirement req-X has no implementing task` |
| 10 | delta-spec MODIFIED 段标题必须存在于主 spec；ADDED 段标题不得已存在 | python 集合比对 | `LINT: FAIL Rule 10 — modified requirement '<heading>' not found in main spec specs/<cap>/spec.md` |

**已删除**：Rule 1（constraints.json 校验，文件已删）、Rule 3（"对照 constraints.json" 子段计数）、Rule 9（字面量违反 grep，AI 判断替代）。

### `--explain` 模式

对每条 fail 额外打印 3 行：

```text
WHY: <为什么这条规则存在 / 为什么这次 fail>
HOW TO FIX: <一句话动作>
EXAMPLE: <最小修复示例>
```

---

## Sidecar File Layout

每个采用本协议的 OpenSpec change 包含 `.sidecar/` 子目录：

```text
openspec/changes/<name>/
├── proposal.md
├── design.md
├── specs/
├── tasks.md
├── .openspec.yaml
└── .sidecar/
    └── ledger.json     ← plan-eng-review / review / verify 累加
```

**白名单**：`.sidecar/` 只允许 `ledger.json`。其它 evidence / baseline / 中间数据文件放在 change 根目录或 `evidence/` 子目录。

详细 writer/reader 矩阵见 `.codex/skills/workflow-spine/REFERENCE.md` §7。

### Legacy Change Behavior

老 change（创建于 slim 之前的 4 文件 sidecar 阶段，或更早无 sidecar）的处理路径：

1. 所有 ledger reader 检测 `.sidecar/` 不存在 → fallback 到 "no dedup / no audit-table"
2. 不 auto-create sidecar
3. 老 change 内遗留的 `constraints.json` / `context.json` / `map.json` / `*.bak.*` 文件不再被读取，留作历史记录

---

## ledger.json schema v1.0

由 `plan-eng-review` / `review` / `verify` 写入 `openspec/changes/<change>/.sidecar/ledger.json`。容器形态固定 `{"schema_version":"1.0","entries":[]}`；每个 entry 描述一次 skill session 的审查产物。

`schema_version` 字段保留作为 future-proof 标记，但 reader 不强制校验。

### Top-level container

```json
{
  "schema_version": "1.0",
  "entries": [
    /* 每个 session 一条 entry */
  ]
}
```

### Entry shape

每个 entry 是一次 plan-eng-review / review / verify session 的快照（非 per-round；per-session = per-entry）：

```json
{
  "source": "plan-eng-review",
  "round": 2,
  "session": 1,
  "timestamp": "2026-04-28T11:21:20+08:00",
  "last_updated": "2026-04-28T13:05:00+08:00",
  "mode": "delta",
  "artifacts_modified": ["design.md", "tasks.md"],
  "rounds_total_for_session": 2,
  "issues_resolved": 5,
  "findings": [
    {
      "id": "F-001",
      "severity": "critical",
      "category": "architecture",
      "summary": "ledger.json malformed JSON 未防御",
      "resolution": "Decision 4 加 defensive read 段；spec.md 加 scenario；tasks.md 7.2 更新",
      "status": "resolved",
      "round_found": 1,
      "round_resolved": 1
    }
  ]
}
```

### Field reference

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `source` | string | skill name：`plan-eng-review` / `review` / `verify` |
| `round` | int | 当前 round 号（plan-eng-review 上限 2） |
| `session` | int | session 序号；同 change 重新审查时递增 |
| `timestamp` | string | entry creation time，ISO 8601 |
| `last_updated` | string | most recent write timestamp |
| `mode` | string | `full` / `delta` |
| `artifacts_modified` | string[] | 当前 session 累计修改的 artifact path 列表 |
| `rounds_total_for_session` | int | 当前 session 累计 round 数 |
| `issues_resolved` | int | 当前 session 累计 resolved findings 数 |
| `findings` | object[] | 见 finding shape |

### Finding shape

```json
{
  "id": "F-001",
  "severity": "critical",
  "category": "architecture",
  "summary": "<1-line description>",
  "resolution": "<1-line how-fixed or N/A if not yet>",
  "status": "resolved",
  "round_found": 1,
  "round_resolved": 1
}
```

| 字段 | 类型 / 取值 | 含义 |
| --- | --- | --- |
| `id` | string | session-local id (`F-001`, `F-002`, ...) |
| `severity` | enum | `critical` \| `defensive` \| `warning` \| `suggestion` |
| `category` | enum | `architecture` \| `code-quality` \| `test` \| `performance` \| `consistency` \| `scope` |
| `summary` | string | 一行简述 |
| `resolution` | string | 一行修复说明；deferred / skipped 时写理由 |
| `status` | enum | `resolved` \| `deferred` \| `skipped` |
| `round_found` | int | 该 finding 首次出现的 round 号 |
| `round_resolved` | int \| null | resolved round 号；deferred / skipped 时为 null |

### Writer 顺序约定

1. **一 session = 一 entry**：plan-eng-review 一次完整执行写一条 entry
2. **Round 1 写后，Round 2 update 同 entry**：不 append 第二条
3. **Re-review 单独写 entry**：`session = max(entries.session) + 1`，append 新 entry
4. **journal `plan-reviewed` 字段同源**：`rounds` / `issues_resolved` 必须与当前 entry 对应字段相等

### Round 2 dedup 规则

Round 2 启动时：

1. 读当前 session entry 中 `status: resolved` 或 `status: deferred` 的 findings
2. 提取 `(category, summary)` pair set，summary 做 normalize
3. Round 2 生成新 finding 时，若命中此 set → 不 emit
4. 未命中 → emit 为 `round_found: 2` 新 finding

### Defensive recovery on malformed ledger.json

writer 写入前 `try json.load() except (JSONDecodeError, OSError)`。命中异常：

1. 备份 broken file：`os.replace(ledger.json, ledger.json.bak.<unix-ns>)`
2. stderr 警告
3. in-memory 重置 `{"schema_version":"1.0","entries":[]}`
4. append 当前 session entry，继续流程不 abort

### Backward compat

- legacy change（无 `.sidecar/`）→ writer skip ledger entirely
- 老版本 ledger.json 缺 `entries` 字段 → 触发 defensive recovery 视为 malformed

---

## ledger.json reader contract

由 `review` (dedup gate)、`push` (audit-table) 和 `archive` (one-shot audit) 消费。reader 必须 read-only。

### Required fields read

| 字段路径 | 用途 | 缺失行为 |
| --- | --- | --- |
| `entries` (list) | 遍历审查 sessions | not-a-list 或缺失 → fallback |
| `entries[i].source` | 区分 writer | 必填 |
| `entries[i].findings[j].status` | dedup filter（仅 `resolved`） | 必填 |
| `entries[i].findings[j].category` | dedup key 第一组件 | 必填 |
| `entries[i].findings[j].summary` | dedup key 第二组件 | 必填 |
| `entries[i].rounds_total_for_session` | push audit table 计数 | 可缺失（默认 1） |
| `entries[i].issues_resolved` | push audit table 计数 | 可缺失（默认 0） |

### Shared dedup normalization

`(category, normalize(summary))` 是 ledger reader 的 canonical dedup key：

```python
def normalize(s):
    return re.sub(r'[^\w\s]', '', s).strip().lower()
```

### Resolved set build protocol

reader 仅消费 `status == "resolved"` 的 finding 进 dedup pool：

```python
resolved_set = {
    (f["category"], normalize(f["summary"]))
    for entry in ledger["entries"]
    for f in entry.get("findings", [])
    if f.get("status") == "resolved"
}
```

`deferred` finding 必须在新 review session 重新出现 —— 这是 "deferred to next session" 的本意。

### Fallback decision table

| 条件 | review reader 行为 | push reader 行为 |
| --- | --- | --- |
| `.sidecar/` 不存在（legacy change） | stderr warning；`resolved_set = set()` 继续 Pass 1/2/3 | stderr warning；MR description 不含 audit lineage table |
| `.sidecar/ledger.json` 不存在 | 同上 | 同上 |
| `json.loads()` 抛 `JSONDecodeError` | stderr warning；dedup disabled | stderr warning；audit lineage skipped |

### Read-only contract

reader 严禁以下操作：

- `os.replace(ledger_path, ...)` / 任何形式的 backup
- `ledger_path.write_text(...)` / 重写 schema fix
- 自动触发 plan-eng-review 重写
- 修改 `entries` in-memory 后回写

writer-side 责任（plan-eng-review / verify / review-as-writer）才能 backup / reset；reader 只能报告问题。
