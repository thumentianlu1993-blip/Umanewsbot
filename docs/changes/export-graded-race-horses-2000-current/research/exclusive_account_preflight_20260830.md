# The Racing API exclusive-account proof 现场生成链

状态：实现与离线测试完成；未在 production host 执行，未生成真实 proof，未访问 TRA 或写业务数据库。

## 目的

此前 `racing-api-exclusive-account-proof.v1` 只有 consumer/validator，没有可信 generator；手写 JSON 即使
字段正确也不能证明同一账号没有 race-live、race-data-sync 或其他 backfill caller。当前 credential/runner
在本机、production runtime 在服务器，因此 proof 必须由三类时间相邻的只读现场证据生成：

1. role=`runner` 的本机 process evidence；
2. role=`production` 的服务器 process evidence；
3. production Django/DB/Celery/Redis runtime evidence。

任一来源 unavailable、stale、partial 或非零都不输出 proof。

## Host 证据

在本机 runner 尚未启动时运行：

```bash
python3 runtime/research/capture_racing_api_host_process_preflight.py \
  --host-role=runner \
  --scope-id=<exact-scope-id> \
  --scope-manifest-sha256=<montjeu-seed-or-batch-proposal-sha> \
  --output-file=<new-private-runner-host-evidence.json>
```

在 production host 同样运行一次，参数改为
`--host-role=production --output-file=<new-private-production-host-evidence.json>`。两份 evidence 必须绑定相同
scope/manifest SHA、capture 间隔不超过 2 分钟且 hostname 不同；不得复制同一文件改 role。

collector 只执行 `ps`、`docker ps`、`docker top`。它扫描仓库中已知的 TRA one-shot runner；命中时只保存
PID、来源、marker 和完整命令 SHA-256，不保存可能含路径或参数的原始命令。host 或 Docker process listing
失败时不生成可用证据。输出为 `0600`、`network_requests=0 / database_writes=0`。

## Django proof 生成

两份 host evidence 必须在 2 分钟内以 `0600` 普通文件提供给运行同一 production 配置/数据库/broker 的
web 容器：

```bash
python server/manage.py generate_racing_api_exclusive_account_proof \
  --credential-alias=tra-primary \
  --scope-id=<exact-scope-id> \
  --scope-manifest-sha256=<same-exact-sha> \
  --runner-host-evidence=<mounted-runner-host-evidence.json> \
  --runner-host-evidence-sha256=<exact-runner-sha256> \
  --production-host-evidence=<mounted-production-host-evidence.json> \
  --production-host-evidence-sha256=<exact-production-sha256> \
  --expected-worker-node=<expected-worker-hostname> \
  --reserved-by=<operator> \
  --decision-source-reference=<approved-G3-reference> \
  --valid-minutes=15 \
  --output-file=<new-private-exclusive-proof.json>
```

命令只读核验：

- `RACE_LIVE_SCHEDULER_ENABLED`、monitor 和 enabled regions 均关闭；
- race-data-sync enabled/scheduler/network 均关闭；
- `RaceEventLiveTracking` 与 lifecycle claim 均为 0；
- `ExternalDataImportLock(the_racing_api)` 为 0；
- Celery ping/active/reserved/scheduled/第二次 active 返回相同 worker 集合，expected workers 全部存在且所有
  task list 为空；
- Redis `celery`、`race_live`、`race_sync_v2` 三个队列均为 0；
- 两份 host evidence role/scope/SHA 精确、hostname 不同、capture 不超过 2 分钟且 matching process 均为 0；
- manual window 有明确 operator 与 G3 decision reference。

proof 最长 15 分钟，文件固定 `0600`。输出额外保存脱敏 evidence summary，但继续兼容现有
`load_exclusive_account_proof`；验证器仍要求六个标准 checks 精确为关闭态。

## 失败与竞态边界

- proof 不是长期锁；生成后仍必须立即启动同 scope 的 file account budget，过期即重建。
- 任一 host evidence 之后若人工启动未使用本项目 limiter 的任意脚本，proof 无法技术上阻止；因此
  `manual_caller_window_reserved=true` 是必须由值班人维护的操作门禁，而不是自动发现的事实。
- collector 只识别已知 runner/host marker；Celery/Redis/DB 检查负责项目常驻 caller。未知外部账号调用者仍
  需要账号团队的独占窗口约束。
- 默认要求所有 Celery active/reserved/scheduled 和三个队列完全为空，可能因无关任务造成保守阻断；不得
  为追求速度把 unknown/partial reply 当作 0。
- proof 成功只授权对应 G3 scope 的零业务写入请求；不授权下一批、staging、canonical apply 或发布。

## 验证

- host collector：`2/2`；
- Django proof generator：`6/6`；本地 consumer/account-budget/horse runner 合并 `34/34`；
- latest-main race-data/race-live/deployment contract 相邻回归：`123/123`；
- 输出权限、stale/matching process、runtime flag、Celery partial worker snapshot 均有 fail-closed 测试；
- 没有 migration 变化。
