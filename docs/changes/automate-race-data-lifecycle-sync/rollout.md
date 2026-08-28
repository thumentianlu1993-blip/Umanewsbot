# 赛事时间、出马表与赛果自动同步发布方案

## 1. 当前停点

- PR #108 已包含未来赛事自动纳管、时间与出马表、lifecycle、赛果、更正、容量账本和发布控制面。
- 最新生产只读快照：web/worker/Beat 为 `2833558a` / `sha256:4bc392…`，双 healthz 200，migration
  leaf `0073`，external started/lock 为 0，`celery=0`、`race_sync_v2=0`、`race_live=7543`。
- 生产磁盘可用 `12,214,140,928` bytes，backup 目录 `47,380,298,866` bytes；主 checkout 有 1,709 项
  历史 dirty，禁止直接 pull/checkout/清理，必须用隔离 release。
- `RACE_DATA_SYNC_*` 生产键尚不存在；现有 lifecycle 为 `true/enforce`，race-live network/scheduler 关闭。
- 尚未合并、备份、迁移、部署或开启任何新开关；等待用户唯一一次最终生产确认。

## 2. 用户覆盖的旧门禁

本发布以用户 2026-08-28 目标为最高产品口径：dry-run 通过后允许直接上线，不要求五个独立 PR、固定
7 天 shadow、逐地区 canary 或逐赛事人工确认。Racing API、官网/官方导入、可信第三方都属于正式来源，
按 `licensed_api > official_operator > trusted_publisher` 自动仲裁，前台统一显示“赛果”。

为控制故障半径，启用仍拆成可独立关闭的能力步骤；这是同一已确认发布中的自动验收/止损顺序，不是
新增人工批准点。任一步 fail closed 时停止后续步骤并保持当前或更窄开关关闭。

## 3. 发布身份

最终确认后才执行：

1. 合并 PR #108，重新 fetch `origin/main` 并记录 merge revision、tree、source archive SHA-256；
2. 从 merge revision 建立只读/隔离 build context，构建固定 `linux/amd64` 镜像；
3. 核对 OCI `org.opencontainers.image.revision`、镜像 ID、镜像内 policy/registry SHA 与 Git revision；
4. 保存旧生产 image ID 和 rollback tag，不以浮动 `prod` tag 作为恢复证据。

当前冻结输入：

- standing policy SHA：`60fe9230ca0e97d69a8406118b5d346649239f3f0699efe9a1d0c63972e44ba4`；
- TRA registry SHA：`24981f62e30e83e58fc82d4247560af35e4041b05857c287bd64430d0f2e2ecc`；
- reference registry SHA：`740a93774927765f9c848cc97e4b87b78ab36d473c4c3e2e644d56a6f856cff2`。

## 4. 写前恢复点

1. 重新确认所有 external import/run/lock、Celery active/reserved/scheduled、migration 和三个队列；
2. 创建 PostgreSQL custom-format 备份，要求 regular file、0600、非空；
3. 记录 byte size、mtime 和 SHA-256，并执行 `pg_restore --list`；
4. 备份 `.env`、Compose/release manifest 和旧 image ID；
5. 备份或构建后若磁盘低于 8 GiB，停止发布，不清理旧备份或 runtime 来绕过门禁。

## 5. 关闭态部署

1. 写入全部 `RACE_DATA_SYNC_* = false/空集合` 和容量 0，确认 `race_sync_v2_worker` 不运行；
2. 通过 deployment lock 和受审 release orchestration 停 Beat、完整 drain worker、迁移并重建服务；
3. 应用 migration 0074/0075，运行 Django check、migration drift、collectstatic；
4. 验证 web/worker/Beat 同 image/revision、双 healthz 200、普通新闻链路正常；
5. 运行 `audit_race_data_sync`：必须 `would_write=false`、network/request/business write/public change 全 0；
6. 核对 `race_live=7543` 未变化、`race_sync_v2=0`，旧 `race_live_worker` 不被启动。

## 6. 冻结容量与 admission

关闭态部署通过后写入：

```dotenv
RACE_DATA_RAW_MAX_COMPRESSED_BYTES=2097152
RACE_DATA_RAW_MAX_UNCOMPRESSED_BYTES=8388608
RACE_DATA_RAW_DAILY_PROVIDER_REGION_BYTES=1073741824
RACE_DATA_RAW_DAILY_PROVIDER_REGION_REQUESTS=192
RACE_DATA_RAW_ROOT_HIGH_WATER_BYTES=536870912
RACE_DATA_RAW_ROOT_LOW_WATER_BYTES=268435456
RACE_DATA_RAW_MIN_FREE_DISK_BYTES=8589934592
RACE_DATA_RAW_CLEANUP_MAX_ROWS=100
RACE_DATA_RAW_CLEANUP_MAX_BYTES=67108864
RACE_DATA_RAW_HOLD_ALERT_BYTES=268435456
RACE_DATA_RAW_ARTIFACT_ROOTS=/run/race-data-sync
```

同时写入精确 provider、region、field/data-kind allowlist、policy/registry 路径和 SHA。保持 network/apply/
public/lifecycle/future discovery 关闭，再次运行审计；必须 `configuration_status=ready`、`capacity=valid`、
`route_drift=[]`、daily ledger 未超限、free disk >=8 GiB。

## 7. 同一确认内的直接启用顺序

1. 启用总开关、scheduler、future discovery，network/apply/public 仍关闭；运行一次 census，确认范围只含
   standing policy 内 published/scheduled/postponed 赛事，无 legacy owner 接管。
2. 启用 `race_sync_v2_worker` 与受限 network，再启用 schedule/racecard apply；检查时间补齐、出马表完整性、
   每日 <=12 小时 cadence、request/byte ledger 和 claim terminal state。
3. 启用 data-sync lifecycle apply；验证 T/T+30 规则、postponed/cancelled 分支和唯一 transition。
4. 启用 result apply/public；验证 T+3 起 checkpoint、完整 roster、不可变 revision、并列名次和公开页统一
   “赛果”，不出现来源/阶段标签。
5. 启用 correction apply；验证同源更新或高优先级来源更正创建 superseding revision，保留旧证据。

每一步至少检查：任务 terminal state、claim/token 清空或明确 due、provider 请求数、not-found/fallback reason、
observation/revision/projection 数、公开 DB/页面一致性、worker/queue、磁盘、error/traceback 和新闻/QQ side
effect=0。HTTP 200、queue 下降或 task exit 0 不能单独证明成功。

## 8. 自动止损

下列任一情况立即停止后续启用并关闭最窄相关开关：

- identity 多解/跨 event、manual lock 覆盖、stale/expired claim 发生 canonical 写入；
- route/registry/contract drift，响应 schema/大小越界，redirect/host/path 越权；
- 错误或部分赛果公开、重复 current revision、投影与页面不一致；
- provider/day 预算、artifact high-water/hold、free disk 8 GiB 门槛失败；
- `race_live` 队列被消费/改变，或普通 worker/新闻/QQ 发生越界副作用。

止损顺序：单 provider -> 单 region/data kind -> result public/correction -> result/racecard/schedule apply ->
lifecycle -> network -> future discovery/scheduler -> 停 `race_sync_v2_worker`。不清空 Redis，不删除 observation/
revision/transition，不批量反向赛事状态。

## 9. 回滚

- 行为回滚优先使用开关收窄；错误结果以新 correction/reverse manifest 修复，不静默删除历史证据。
- 代码回滚前先关闭全部新开关，完整 drain 新 worker，再恢复精确旧 image；additive schema 默认保留。
- 只有新 schema 与旧代码不兼容且尚无新审计数据时，才在单独授权和已验证备份下考虑 reverse migration。
- 数据库损坏才使用 custom-format 恢复，属于独立高影响操作，不包含在普通应用回滚中。

## 10. 发布完成证据

只有以下全部有生产实证才结束本目标：

- merge revision/image/migration/flags/capacity 与 release manifest 一致；
- future discovery 能纳管新赛事，时间和出马表路径有真实成功与明确 blocked 分类；
- lifecycle 自动任务正常，赛果任务在自然到期或受控 fixture smoke 中完成 immutable revision 与公开投影；
- kill switch 实测在一个 selector 周期内停止新 dispatch/write；
- `race_live=7543` 保持不变，race_sync 新队列/worker 可观测；
- current_state、decisions、deploy runbook、project status 和 release evidence 与生产运行态一致。
