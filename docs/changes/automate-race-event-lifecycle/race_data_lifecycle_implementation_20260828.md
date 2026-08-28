# 赛事数据全生命周期自动化实现报告（2026-08-28）

## 1. 结论

本轮已经在代码侧闭环未来赛事发现、时间补全、出马表更新、赛事状态推进、赛果抓取、正式投影与
更正观察。实现不要求逐场人工确认，也不在公开页面标注来源或“暂定/正式”等内部阶段；所有生产
写入仍由总开关、分项开关、冻结 standing policy、来源 proof、路由 digest、容量上限和数据库控制面
共同约束，仓库默认保持关闭。

实现已提交并创建 PR #108。本轮未部署、未迁移生产数据库、未启用生产开关。生产动作必须在 PR
合并并绑定精确 revision 后，另行取得最终确认。

## 2. 自动化链路

1. `discover_future_race_data_sync_task` 每小时扫描 standing policy 覆盖的未来公开赛事，确定性解析
   地区、来源和身份；The Racing API 通过“规范化赛名 + 场地 + 当地日期”唯一匹配建立 source identity。
2. 纳管事务同时建立 `race_sync_v2` projection owner、enrollment、provider checkpoints 和 lifecycle
   enforce control；claim/complete 使用 enrollment、owner、claim generation、attempt token 和计划 SHA
   做 CAS，过期 worker 不能完成新 claim。
3. 赛时与出马表在远期至少每 12 小时一次，临近比赛逐步缩短到 6 小时、1 小时、15/10 分钟；满足
   “每天至少两次”且不会用固定高频轮询消耗所有配额。
4. 到开跑时间自动 `scheduled -> running`，T+30 自动 `running/scheduled -> finished`；延期赛事不误推，
   每 12 小时等待新赛时。状态迁移有唯一 dedupe key 和审计 transition。
5. 赛果从 T+3 开始按 T+5/10/15/20/25/30、随后 15/30 分钟、3/6 小时等动态检查点抓取；已有确认
   结果仍保留 7 天更正观察。原始 observation、不可变 revision、projection 和公开缓存失效分离。
6. 并列名次保留来源报告名次 `reported_finish_position`，内部 `finish_position` 继续唯一，避免 dead heat
   被误判成冲突；更正新增 revision，不覆盖历史证据。

## 3. 来源优先级与边界

字段仲裁固定为：

1. `licensed_api`（The Racing API）= 300；
2. `official_operator`（赛事官网或官方导入）= 200；
3. `trusted_publisher`（Sporting Life、ZEturf、Horse Racing Nation）= 100。

更高等级可覆盖低等级；同等级先比 observation 时间，再用 provider key 稳定决胜；人工锁永远优先。
主 API 返回 result not-found 时，先投影数据库中已经由 HKJC/France Galop 导入的完整官方结果，再尝试
相应地区的可信第三方 immutable receipt。部分结果、身份多解或 route drift 均不投影。

The Racing API 是本轮唯一新增的联网主适配器，单 task 最多 3 个 provider 请求，并由 host/path allowlist、
令牌桶、地区/数据类型 allowlist 与有效期 proof 限制。当前 source registry SHA-256 为
`24981f62e30e83e58fc82d4247560af35e4041b05857c287bd64430d0f2e2ecc`，有效至 2026-09-27。

本轮没有新增 JRA、NAR、HKJC、France Galop 官网的常驻联网抓取。现有官网条款/免责声明不能单独证明
自动化许可；因此官网层只消费仓库既有官方导入事实。这不阻断 Racing API 主链自动化，但若以后新增
官网 transport，必须先登记独立 proof、固定 host/path/request budget，再进入相同仲裁器。

## 4. 配置与迁移

- migration：`0075_race_data_source_priority_and_reported_position`；
- standing policy：`runtime/policies/race_data_sync/standing_policy.json`；
- policy SHA-256：`60fe9230ca0e97d69a8406118b5d346649239f3f0699efe9a1d0c63972e44ba4`；
- 新任务路由到 `race_sync` queue；Beat 增加未来发现和 lifecycle tick；
- `.env.example`、普通 Compose 和 low-cost Compose 已同步 registry/policy、mount、flags 和 task route；
- 所有 runtime/apply/network/future-discovery/lifecycle 开关默认 `false`，容量默认 `0`，防止代码发布即写入。

生产启用至少需要同时设置总开关、scheduler、network、对应 apply/public/lifecycle/future-discovery 开关，
并为 provider/region/data kind、host/request、event/enrollment/checkpoint/revision 配置正容量。任何缺项均
`blocked` 或 fail closed。

## 5. 可观测性与 dry-run

新增只读命令：

```bash
python server/manage.py audit_race_data_sync
python server/manage.py render_race_data_sync_standing_policy --digest-only
```

审计输出 runtime flags、provider roster、route admission、未来赛事 inventory、缺失赛时、未绑定身份、
enrollment、due checkpoints、policy census/blocker 和 route drift，并固定 `would_write=false`。

2026-08-28 在全新临时 SQLite 数据库完成 migration 与全开配置审计：`configuration_status=ready`、
`capacity.status=valid`、`route_drift=[]`；审计前后数据库 SHA-256 均为
`3339d40728f8b0eb4310e97efb6f169f3f4c52625fa8a3b6c94bd2e3492caea0`，证明该命令零写入、零联网。

## 6. 验证结果

- `manage.py makemigrations --check --dry-run`：No changes detected；
- `manage.py check`：0 issues；
- Python `compileall`：通过；
- 聚焦回归：169/169 通过；覆盖来源仲裁、动态 cadence、future discovery、CAS、lifecycle、TRA transport、
  官网/第三方 fallback、不可变赛果 revision、dead heat、更正、审计、route drift、公开页去来源标签；
- zero-write dry-run：通过，数据库 hash 不变。

## 7. 发布门禁与回滚

代码 PR 不等于生产启用。最终发布必须绑定合并后的精确 revision/image、migration 0075、registry SHA、
policy SHA 和开关/容量清单；先备份并验证 `pg_restore --list`，再迁移，保持全部新开关关闭完成 web/worker/
Beat 验收，最后才可按确认的灰度顺序启用。

一级止损是关闭 `RACE_DATA_SYNC_ENABLED`、`RACE_DATA_SYNC_FUTURE_DISCOVERY_ENABLED`、
`RACE_DATA_SYNC_LIFECYCLE_APPLY_ENABLED` 和各 apply/public 开关；已经形成的 revision 与 transition 保留，
不得通过批量反向状态或降级结果回滚。
