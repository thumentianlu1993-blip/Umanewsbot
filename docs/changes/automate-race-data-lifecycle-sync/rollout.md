# 赛事时间、出马表与赛果自动同步发布方案

## 1. 当前停点

- PR #108 已包含未来赛事自动纳管、时间与出马表、lifecycle、赛果、更正、容量账本和发布控制面。
- 最新生产只读快照：web/worker/Beat 为 `2833558a` / `sha256:4bc392…`，双 healthz 200，migration
  leaf `0073`，external started/active lock 为 0（2 条 lock 占位行均未持有），`celery=0`、
  `race_sync_v2=0`、`race_live=7543`。
- 关闭态修复及候选构建后生产磁盘可用约 `11.3 GB`；主 checkout 有 1,722 项
  历史 dirty，禁止直接 pull/checkout/清理，必须用隔离 release。
- runtime 仅有旧版 `RACE_DATA_SYNC_ENABLED=false` 与 provider/region/field 三个空集合键；本 change 新增的
  scheduler/network/apply/capacity 等键尚不存在。现有 lifecycle 为 `true/enforce`，race-live network/scheduler
  关闭。
- PR 仍未合并，migration/部署/新开关均未执行。原先阻断发布的 14 条过期 `claimed` 已在停 Beat 的
  关闭态窗口按 manifest `5897db0d…76d1a5` 精确收口为 `failed/stale_claim_reconciled`；写前 custom
  backup 为 `484192137` bytes、SHA `64d72011…44bdc`、0600/TOC 有效。独立 verifier 证明队列、pending、
  delivery、approval、赛果和旧 lifecycle 均未越界，原 Beat 已恢复。下一步只在真正合并/部署/启用前
  请求一次最终生产确认。

历史收口不得通过修改 writer 门禁或忽略过期 lease 完成。只有 selector/bundle/terminal/finished 全空且
cursor 形态精确的已过期 claim 可转为 `failed/stale_claim_reconciled`；任何活租约、异常字段或 SHA 漂移
立即停止，Beat 恢复原状且所有新写入开关继续关闭。

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

- standing policy SHA：`07013655d4e0ae4bd5688b9a5dc447d759c0effa4b5393ec198f48bf961a1888`；
- TRA registry SHA：`3bac3b644c631ed165b8430343822b2c70c5a88c5036b63dcb557c83c0e0a6da`；
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

本发布冻结的 allowlist 来自 standing policy 与当前唯一 roster，不包含尚未实现的 official-provider route：

```dotenv
RACE_DATA_SYNC_ENABLED_PROVIDERS=horse_racing_nation,sporting_life,the_racing_api,zeturf
RACE_DATA_SYNC_ENABLED_REGIONS=france,hong_kong,ireland,japan_jra,japan_nar,united_kingdom,united_states
RACE_DATA_SYNC_ENABLED_FIELDS=local_start_time,off_time,participants.carried_weight,participants.draw,participants.horse_name,participants.jockey_name,participants.number,participants.odds,participants.popularity,participants.status,participants.trainer_name,status,timezone_name
RACE_DATA_SYNC_ENABLED_DATA_KINDS=race_time,racecard,result
```

任一 policy route 在 `configuration_only` 解析下不唯一、未 admitted 或 digest 漂移时，必须缩窄到实际通过的
provider/region/data-kind，不能临场加入 JRA/HKJC 等 `proof_required` route 或放宽字段集合。

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

本次生产证据统一追加到 `release_evidence.md`；不得用聊天记录、HTTP 200 或 Celery `SUCCESS` 替代其中的
数据库、任务、队列、资源和公开页逐层验收。

## 11. PR 全量复审增补门禁

- 当日 results 无 terminal marker 只能记录 provisional；赛后 7 天只允许
  `/v1/results/{race_id}`，404 明确 not-found。
- shared snapshot complete TTL 为 150 秒，必须完整分页；owner 预留一次容量，event 复用同一 artifact。
- terminal result 必须覆盖 canonical runner 全集。结果型 fallback 只有马号和 NFKC 规范化马名构成唯一
  全双射时，才在投影事务原子绑定来源 runner ID。
- enrollment 保留已有 lifecycle mode/pause；新 control 从 off 建立；所有写路径 lifecycle -> event。
- data-sync T+30 只在普通队列生成不可发送 incident；旧 `race_live` 队列和 delivery 均为零副作用。
- audit 的 ready 是配置就绪，不要求运行开关打开；实际 apply 仍重验 source expiry/registry/contract 和
  exact claim。
