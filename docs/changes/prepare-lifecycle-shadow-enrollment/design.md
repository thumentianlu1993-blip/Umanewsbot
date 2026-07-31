# Lifecycle shadow 纳管准备设计

## 1. 复用边界

继续复用：

- `RaceEvent`：赛事资格、地区、时间、时区和公开状态；
- `RaceEventLifecycleControl`：逐场 mode、generation、claim、next refresh 和 manifest 绑定；
- `RaceEventLifecycleTransition`：shadow proposal / enforce applied 审计；
- `decide_race_lifecycle()`：唯一时间决策函数；
- `claim_due_lifecycle_controls()`：`select_for_update(skip_locked)` 批量 claim；
- 既有每 5 分钟 scanner 和普通 Celery worker。

不新建第二套 control、状态历史或调度器。race-live 继续只处理 provider/racecard/result，
lifecycle scanner 不 dispatch race-live。

## 2. 新组件

建议新增：

- `server/stable/services/race_event_lifecycle_enrollment.py`
  - strict JSON loader；
  - schema v2 validator；
  - event snapshot、schedule hash 和 control fingerprint；
  - prepare、preflight、dry-run、atomic apply、verify 共用逻辑。
- `server/stable/management/commands/prepare_race_event_lifecycle_enrollment.py`
  - 明确 event IDs；
  - 只读 DB；
  - 原子生成 `manifest.json` 与 `summary.json`。
- 扩展
  `server/stable/management/commands/reconcile_race_event_lifecycle_controls.py`
  - v2 manifest 走共享 loader/preflight；
  - 保留现有 v1 dry-run 兼容读取，任何 v1 apply 永久拒绝；
  - `--apply` v2 需要 expected commit 和 shadow 确认。

不新增 migration。若实现中发现必须新增字段，应停止并回到方案审核，不得顺手迁移。

## 3. 数据流

```text
显式 event IDs
  -> prepare 只读锁前快照
  -> 地区/时区/资格/control 门禁
  -> manifest.json + summary.json
  -> 人工核对 + 独立 review + 精确 SHA 授权
  -> reconcile dry-run（共享 loader + 当前 DB preflight）
  -> false/off 下 atomic apply
  -> 独立 verify
  -> 新授权
  -> true/shadow
  -> scanner claim -> per-event task -> proposal only
```

## 4. 一致性与并发

prepare 不是写入锁；真正安全边界在 apply：

1. 解析完整 manifest 后进入单个 `transaction.atomic()`；
2. 按 event ID 升序 `select_for_update()` 锁定所有 `RaceEvent`；
3. 同序读取/锁定已有 control；
4. 对比 `event_updated_at`、资格、status、region、timezone、日期/时间、schedule hash、
   expected control；
5. 任一漂移抛出领域错误，事务零写；
6. 全部通过后 bulk/create control，或确认全部 replay；
7. 不允许“部分 create + 部分 error”。

批次上限 20，避免长事务和大锁集合。prepare 与 dry-run 可分批读取，但 apply 不分页提交。
进入事务前还必须硬校验当前管理命令进程 settings 严格为 `false/off`；其他组合或无法判定
均零写拒绝。生产 preflight 还需证明 Beat/普通 worker 使用相同关闭态配置且没有 lifecycle
active/reserved/有效 claim，避免旧 worker 在 apply 后立即 claim。

## 5. 时间语义

- `race_datetime` 非空：必须 aware；next refresh 为该 instant；
- `race_datetime` 为空：next refresh 为 `local_date + 1` 在赛事 IANA 时区的当地午夜；
- `local_start_time` 只作为冻结展示证据，不参与 instant 推导；
- 日本/香港无 DST；英国/法国和美国由 `zoneinfo` 按日期处理 DST；
- 美国不从 `country_region` 猜一个统一时区，逐场 allowlist 只能包含当前获批的 `America/*`；
- manifest 过期或 DB 时间字段变化后必须重新 prepare，不能沿用旧 schedule hash。

生产 6 个 `Asia/Shanghai` 错误地区样本应在 prepare 阶段被拒绝，而不是被自动修正。

## 6. Dry-run parity

当前 v1 manifest dry-run 只提取 event IDs，没有完整 schema 校验，也没有把美国 allowlist、
冻结 eligibility 和 schedule hash传入决策；apply 才执行这些门禁。实现后 v2：

- `load_manifest()` 只实现一次；
- `preflight(events, manifest, now)` 只实现一次；
- dry-run 与 apply 的差异仅是最后是否创建 control；
- dry-run 也检查 SHA、schema、expiry、expected commit、美国 zone、DB drift 和 existing control；
- dry-run 的 predicted decision 调用既有 `decide_race_lifecycle()`，并传入相同 US zones。
- v1 仅用于读取历史 manifest 和 dry-run；v1 `--apply` 不再路由到旧分页 reconciler。

## 7. Replay 与更新

本 change 只处理首次 shadow enrollment：

- control 不存在：create，generation=1；
- control 与 manifest SHA、mode、generation、next refresh、manifest data 完全一致：replay；
- control 存在但 manifest 不同或内容漂移：拒绝。

它不复用旧 reconciler 的“新 manifest 更新现有 control”分支。延期、时间补齐、取消或
重新纳管需要新的 manifest/change 设计；不能在首次纳管入口静默更新 schedule generation。

## 8. 开关与故障恢复

全局 mode 是逐场 mode 的上限：

- `false/off`：scanner 零 claim；
- `true/shadow`：仅 manifest 中 mode=shadow 且 due 的 control 可被 claim；
- `true/enforce` 不属于本 change，发布检查必须拒绝。

v2 enrollment apply 也只能在严格 `false/off` 下执行。该检查是代码门禁，不是 runbook
提示；它与生产 Beat/worker 运行态只读 preflight 共同保证“先纳管、verify、再启用”。

紧急停止顺序：

1. 把 `RACE_EVENT_LIFECYCLE_ENABLED=false`、mode=off；
2. 重建 Beat/普通 worker 使配置生效；
3. 验证 scanner 返回 disabled；
4. 已排队 per-event task 会在事务内复查开关并零写退出；
5. 保留 control/proposal，不删除审计，不反向改赛事状态。

shadow 不改公开状态，所以不需要数据反向迁移。

## 9. 性能与观测

- prepare/apply ≤20 场；
- scanner 继续 batch 100、claim TTL 240 秒、任务 soft/hard 120/150 秒；
- 观察 due、claimed、dispatched、proposed、duplicate、error、claim expiry；
- 对每场记录 manifest SHA、generation、last result/error、next refresh；
- 观察普通 Celery queue age、active/reserved、数据库等待锁；
- `RaceEvent.status`、result、news、QQ 前后计数/摘要必须不变；
- race-live scheduler/worker 状态单独核对，禁止把 lifecycle proposal 当赛果触发。
