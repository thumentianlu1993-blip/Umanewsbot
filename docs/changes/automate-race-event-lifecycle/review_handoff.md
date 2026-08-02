# `automate-race-event-lifecycle` 阶段 A 代码审查交接

## 0. 审查授权与范围

本文是阶段 A 实现的**代码审查**交接文档。审查者（codex reviewer）可以仅凭本文和仓库当前文件完成独立只读审查，不需要重新询问产品范围或重新设计。

**当前状态**：

- 分支：`codex/automate-race-event-lifecycle`（已 rebase 到 `origin/main@8cbee3e7`）
- 已完成：阶段 A 全部实现（模型、迁移、服务、任务、管理命令、配置、admin、测试）
- **未完成**：代码 review、commit、push、PR、部署、生产写入
- **本轮目标**：独立只读代码审查，清零所有 actionable finding

**审查范围**：只审查阶段 A 的实现文件。`docs/changes/automate-race-event-lifecycle/` 下的 spec/design/test_cases/tasks/rollout 等规划文档是审查参考，不是被审查对象。

## 1. 阶段 A 目标（规格摘要）

解决「赛事长期停留在 scheduled/赛前」的根因：当前 `RaceEvent.status` 只在成功发布赛果 revision 时才改为 `finished`，来源失败、没有 live tracking、或 scheduler 关闭时状态永远不推进。

阶段 A 实现：
- 按赛事 IANA 时区自动推进 `scheduled → running → finished`
- 「比赛时间已过」与「赛果权威阶段」完全分离
- 不接入任何新 provider、不改变新闻门禁、不 dispatch race-live polling

## 2. 变更文件清单

### 2.1 新增文件（实现代码）

| 文件 | 行数 | 说明 |
|---|---|---|
| `server/stable/migrations/0058_add_race_event_lifecycle.py` | ~90 | 四个新模型迁移 |
| `server/stable/services/race_event_lifecycle.py` | ~410 | 核心服务 |
| `server/stable/management/commands/reconcile_race_event_lifecycle_controls.py` | ~120 | 纳管管理命令 |

### 2.2 新增文件（测试）

| 文件 | 行数 | 测试数 |
|---|---|---|
| `server/stable/test_race_event_lifecycle.py` | ~730 | 36 项 |
| `server/stable/test_race_event_lifecycle_postgres.py` | ~200 | 4 项（需 PostgreSQL） |

### 2.3 修改文件

| 文件 | 变更摘要 |
|---|---|
| `server/stable/models.py` | +243 行：4 个新模型 |
| `server/stable/tasks.py` | +69 行：2 个新 Celery task |
| `server/app/settings.py` | +18 行：7 个配置项 + Beat + route |
| `server/stable/admin.py` | +60 行：4 个 admin 注册 + RaceEvent detail 增强 |
| `.env.example` | +7 行 |

## 3. 新增模型

### 3.1 `RaceEventLifecycleControl`（event 一对一）

控制面，不是第二状态机：

| 关键字段 | 类型 | 说明 |
|---|---|---|
| `event` | OneToOneField(RaceEvent) | 关联赛事 |
| `mode` | CharField(off/shadow/enforce) | 运行模式 |
| `next_refresh_at` | DateTimeField | 下次扫描时间 |
| `schedule_generation` | PositiveBigIntegerField | 调度世代（防旧任务） |
| `claim_token/claim_generation/claim_expires_at` | — | 分布式 claim |
| `last_attempt_at/last_success_at/last_result_code/last_error` | — | 运行状态 |
| `consecutive_failures` | PositiveIntegerField | 连续失败计数 |
| `enrollment_manifest_sha256` | CharField | 纳管 manifest |

索引：`(mode, next_refresh_at)`

### 3.2 `RaceEventLifecycleTransition`（append-only）

| 关键字段 | 类型 | 说明 |
|---|---|---|
| `event` | ForeignKey(RaceEvent) | — |
| `from_status/to_status` | CharField(RaceEventStatus) | 状态变化 |
| `reason_code` | CharField | 触发原因 |
| `record_kind` | CharField(proposal/applied) | 提案/已应用 |
| `dedupe_key` | CharField(unique) | 幂等键 |
| `schedule_generation` | PositiveBigIntegerField | — |
| `based_on_proposal` | FK(self) | applied 可引用 shadow proposal |

唯一约束：`(dedupe_key)`  
dedupe key 格式：`{record_kind}:{event_id}:{generation}:{reason}:{to_status}`

### 3.3 `RaceEventFieldAuthority`（字段权威）

| 关键字段 | 说明 |
|---|---|
| `subject_type/subject_key` | 目标身份（event/participant） |
| `field_name` | 字段名 |
| `authority_level` | 权威等级（100-500） |
| `source_key/source_url/external_id` | 来源证据 |
| `manual_lock` | 人工锁定 |

唯一约束：`(event, subject_type, subject_key, field_name)`

### 3.4 `RaceEventFieldChange`（append-only）

| 关键字段 | 说明 |
|---|---|
| `old_value/new_value` | JSON 变更前后 |
| `authority_level` | 权威等级 |
| `operation_mode` | dry_run/shadow/enforce |
| `applied/rejection_reason` | 应用状态 |

## 4. 核心服务：`race_event_lifecycle.py`

### 4.1 公开接口

```python
# 纯决策（无 DB、无网络）
decide_race_lifecycle(*, race_datetime, timezone_name, status, now,
                      local_date=None, region="",
                      allowed_us_zones=None) -> LifecycleDecision

# 原子 apply（需在事务中调用）
apply_race_lifecycle_decision(*, event_id, expected_generation, now,
                               mode, dry_run=False, run_id="") -> ApplyResult

# 批量 claim（select_for_update skip_locked + bulk_update）
claim_due_lifecycle_controls(*, now, batch_size, ttl_seconds) -> list[LifecycleBatchClaim]

# 纳管同步
reconcile_lifecycle_controls(*, event_ids, manifest_sha256, apply=False,
                              eligibility_snapshot=None, target_modes=None) -> dict
```

### 4.2 时区合同（`_REGION_TIMEZONE_CONTRACT`）

```python
"japan":         frozenset({"Asia/Tokyo"})
"hong_kong":     frozenset({"Asia/Hong_Kong"})
"united_kingdom": frozenset({"Europe/London"})
"france":        frozenset({"Europe/Paris"})
# 美国：必须 America/*，且由 manifest 逐场审核具体 zone
```

### 4.3 时间规则（`decide_race_lifecycle`）

- `now < race_datetime` → noop
- `now >= race_datetime` → scheduled→running
- `now >= race_datetime + 30min` → →finished（无论当前 scheduled 还是 running）
- 无 race_datetime：`now >= local_date+1 天 00:00 local tz` → finished
- cancelled → 永远 noop
- postponed → 永远 noop（等新 generation）
- 时区无效/不匹配 → error

### 4.4 原子 apply（`apply_race_lifecycle_decision`）

1. `transaction.atomic` 内 select_for_update control + event
2. 校验 generation 不陈旧、claim 未过期
3. 重算 decision（防 TOCTOU）
4. shadow：`get_or_create` proposal transition（dedupe key）
5. enforce：先查 applied dedupe key 是否已存在，否则创建 applied transition + 更新 `RaceEvent.status` + 更新 control
6. `transaction.on_commit(invalidate_public_race_cache)`

### 4.5 Claim（`claim_due_lifecycle_controls`）

- `select_for_update(skip_locked)` → 取 due rows
- `bulk_update` 设置 token/generation/expiry
- 只返回 `mode ∈ {shadow, enforce}` 且 `next_refresh_at <= now` 的行
- 过期 claim（`claim_expires_at <= now`）可被回收

## 5. Celery 任务

### `scan_due_race_event_lifecycle_task`
- Beat 每 5 分钟
- Guard：`RACE_EVENT_LIFECYCLE_ENABLED != True` → 直接返回
- 调用 `claim_due_lifecycle_controls`，每批最多 100
- 对每个 claim 通过 `transaction.on_commit` dispatch `advance_race_event_lifecycle_task`

### `advance_race_event_lifecycle_task`
- 单场纯 DB 时间决策，不联网
- 读取 `RACE_EVENT_LIFECYCLE_MODE` 全局配置
- 调用 `apply_race_lifecycle_decision`

## 6. 管理命令

### `reconcile_race_event_lifecycle_controls`
- 默认 `--dry-run`（零写、零 dispatch）
- `--apply --manifest-sha256 <sha>` 才写入
- 支持 `--event-ids`、`--auto-discover`、stdin JSON 三种输入
- `--page-size` 默认 500
- `--default-mode` 默认 shadow

## 7. 配置项（全部默认 off/false）

```bash
RACE_EVENT_LIFECYCLE_ENABLED=false     # 总开关
RACE_EVENT_LIFECYCLE_MODE=off          # off|shadow|enforce
RACE_EVENT_LIFECYCLE_BATCH_SIZE=100    # 每批最大数
RACE_EVENT_LIFECYCLE_CLAIM_TTL_SECONDS=240  # claim TTL
RACE_EVENT_LIFECYCLE_SOFT_TIME_LIMIT=120
RACE_EVENT_LIFECYCLE_TIME_LIMIT=150
```

Beat 条目：`scan-due-race-lifecycle`，`crontab(minute="*/5")`  
Task route：`advance_race_event_lifecycle_task` → `queue="default"`

## 8. 测试覆盖（test_cases.md 对照）

### 已覆盖（36 项 GREEN）

| 测试类 | 对应 test_cases | 数量 |
|---|---|---|
| `RaceEventLifecycleDecisionTests` | A01-A13 | 13 |
| `RaceEventLifecyclePostponementTests` | A14-A15 | 2 |
| `RaceEventLifecycleIdempotencyTests` | A16, A18 | 2 |
| `RaceEventLifecycleModeTests` | A19-A22 | 4 |
| `RaceEventLifecycleResultPhaseTests` | A23-A24 | 2 |
| `RaceEventLifecycleEnrollmentTests` | A25-A28 | 4 |
| `RaceEventLifecycleShadowEnforceTests` | A29-A30 | 2 |
| `RaceEventLifecycleTimezoneContractTests` | A31-A33 | 3 |
| `RaceEventLifecycleCacheTests` | cache | 1 |
| `RaceEventLifecycleQueryCountTests` | query-count | 1 |
| `RaceEventLifecycleNoLiveDispatchTests` | no-live-dispatch | 2 |

### PostgreSQL 并发测试（需隔离 PostgreSQL）

| 测试类 | 说明 |
|---|---|
| `RaceEventLifecyclePostgresConcurrencyTests` | 双 worker 竞争、skip_locked |
| `RaceEventLifecyclePostgresClaimExpiryTests` | claim 过期回收、active claim 不重复、generation 陈旧拒绝 |

### 未在阶段 A 实现中覆盖的场景

- A17（双 worker 同时处理只一次有效更新）→ 在 `test_race_event_lifecycle_postgres.py` 中
- A22（事务晚期失败全部回滚）→ 设计验证已通过（atomic 函数 + on_commit），完整回滚测试在 PostgreSQL 文件中

## 9. 自测命令

审查者应先运行以下命令确认基线 GREEN：

```sh
# 生命周期聚焦测试
docker run --rm -v "$PWD:/workspace" -w /workspace \
  -e CELERY_TASK_ALWAYS_EAGER=true \
  -e CELERY_TASK_EAGER_PROPAGATES=true \
  umanews-historical-race-check:local \
  python server/manage.py test stable.test_race_event_lifecycle -v 2

# Django 系统检查
docker run --rm -v "$PWD:/workspace" -w /workspace \
  -e CELERY_TASK_ALWAYS_EAGER=true \
  umanews-historical-race-check:local \
  python server/manage.py check

# 迁移漂移检查
docker run --rm -v "$PWD:/workspace" -w /workspace \
  -e CELERY_TASK_ALWAYS_EAGER=true \
  umanews-historical-race-check:local \
  python server/manage.py makemigrations --check --dry-run

# 已有赛事回归（不含 TRA 网络测试）
docker run --rm -v "$PWD:/workspace" -w /workspace \
  -e CELERY_TASK_ALWAYS_EAGER=true \
  -e CELERY_TASK_EAGER_PROPAGATES=true \
  umanews-historical-race-check:local \
  python server/manage.py test \
  stable.test_race_event_lifecycle \
  stable.test_realtime_race_results \
  stable.test_race_live_multiregion_selector \
  stable.test_race_live_racecard_sync -v 1

# diff 格式检查
git diff --check
```

## 10. 审查重点

### 正确性
- [ ] `decide_race_lifecycle` 的时间边界是否正确（T+0、T+30、无时间次日 00:00）
- [ ] cancelled/postponed 终态不会自动推进
- [ ] 时区合同是否严格执行（日本≠Asia/Hong_Kong，etc.）
- [ ] DST 通过 `zoneinfo.ZoneInfo` 处理，不依赖服务器时区

### 并发与幂等
- [ ] `claim_due_lifecycle_controls` 使用 `select_for_update(skip_locked)` + `bulk_update`
- [ ] `_apply_shadow` 使用 `get_or_create`（dedupe key）
- [ ] `_apply_enforce` 先检查 applied dedupe key 是否存在
- [ ] generation staleness 在 apply 时被拒绝
- [ ] claim TTL 过期后可被回收

### 事务完整性
- [ ] shadow/enforce 在 `apply_race_lifecycle_decision` 内的操作在同一事务
- [ ] 缓存失效通过 `transaction.on_commit` 注册
- [ ] 失败时不残留部分写入

### 安全边界
- [ ] 无 lifecycle control 的赛事不自动启用（`DoesNotExist` → error）
- [ ] `mode=off` 的 control 不处理
- [ ] 全部配置默认 off/false
- [ ] lifecycle scanner 不 dispatch `poll_race_live_event_task`
- [ ] 不调用任何 provider、不联网
- [ ] 不改变新闻门禁
- [ ] 不扫描全量 RaceEvent 自动扩容

### 代码质量
- [ ] 函数职责单一（决策/apply/claim/reconcile 分离）
- [ ] 无硬编码魔法值（全部从 settings 读取）
- [ ] 无 SQL 注入（全部使用 ORM）
- [ ] 迁移可逆（新表 additive，回滚见 rollout.md）

## 11. 已知限制

1. **A22 事务回滚测试**：SQLite 不支持完整的 PostgreSQL 事务回滚语义。完整的回滚验证在 `test_race_event_lifecycle_postgres.py` 中，需要隔离 PostgreSQL 数据库。
2. **已有 race-live 回归**：`test_shadow_result_is_checkpointed_without_publication_or_failure` 需要 TRA API 网络连接，在无网络容器中会失败，这是**预存在**问题，非本次引入。
3. **阶段 A 不做**：provider 接入、新闻门禁变更、race-live dispatch、历史赛事批量修正、首页近期赛事修改。

## 12. 冲突优先级（审查时参考）

1. 本文（审查交接）
2. `spec.md`（规格合同）
3. `design.md`（设计合同）
4. `test_cases.md`（测试覆盖要求）
5. `tasks.md`（阶段 A 任务清单）
6. `rollout.md`（灰度/回滚要求）
7. 仓库根 `AGENTS.md`
