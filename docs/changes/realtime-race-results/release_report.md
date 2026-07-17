# 准实时赛事赛果生产发布报告

## 发布结论

2026-07-18 已完成最新整合冻结版本的生产安全基线发布。代码、迁移、独立队列 worker、secret 挂载与只读来源 proof 已上线；公开和调度保持关闭。首轮英国 shadow 因生产未来赛事均缺少 `race_datetime` 而 fail closed，没有生成或应用初始化 manifest，也没有 live 业务数据或公开赛果写入。

## 冻结版本与镜像

- revision：`4f11b2273fd167c69d54b338a4e627a77dd010c2`
- parent：`ccb56f7d526daf70357f193f716b23eacb26edbe`
- tree：`277cb10ad56aee9a3156fa2b1632dd73377054c8`
- review fingerprint：`01f8c7d3bd19a21a332d522c2186af551c6d1555182f2149bbf5e4d5989bff46`
- approved content manifest：`135733abd8c032ed3c6c4ac0667d5c12227368e4b6a83c7f6f9c0e3b091469af`
- source archive SHA-256：`e957e748b82b4933eeaab2f5721185e42e6f4e58b9e552ee10cfabace11ca2d5`
- production image：`sha256:c2b9e15e037406808bef1edbbef888728a8f0d6ae40c47418c6cd4e414803966`
- registry SHA-256：`1d801e95b2770c741503a75dbcba93aca407a6cd681f3471813f1e7d5586fa32`

生产 checkout、web、普通 worker、Beat 与 `race_live_worker` 均为上述 revision/image。镜像内 Django check、migration drift、初始化器与 TRA runner `13/13`、registry digest 和无 `.env`/TRA secret 检查通过。

## 恢复点

- 数据库备份：`/opt/umanewsbot/backups/db/pre-realtime-race-results-4f11b227-20260718_034437.dump`
- 大小：`195,161,786` bytes
- 权限：`root:root 0600`
- SHA-256：`f81a11ece1b75f5ff680e445b71b910ea453ee1fc26eeb24ac8df030daf72a01`
- 格式验证：`pg_restore -l` 通过
- 环境备份：`/opt/umanewsbot/.env.backup.pre-realtime-4f11b227-20260718_034437`
- 回滚标签：`umanewsbot:rollback-pre-realtime-4f11b227-20260718_034437`
- 回滚 image：`sha256:63cdfc131ebb4152f4f56740fe6f94f806f33139b9496f15679b184457397329`

## 数据库与运行态

- migration：由 `stable.0032` 前进至 `stable.0045`
- 业务总量：`9,867 events / 100,132 runners / 91,897 results`，与发布前一致
- live control/tracking/observation/revision/publication/incident：全部 `0`
- `RACE_LIVE_SCHEDULER_ENABLED=false`
- `RACE_LIVE_RUNNER_MODE=disabled`
- secret：`/opt/umanewsbot/runtime/secrets/the-racing-api-free.env`，`root:root 0600`
- 普通 worker queue：仅 `celery`
- 独立 worker queue：仅 `race_live`
- `race_live` 队列：`0`
- 四个 app 服务：running、restart count `0`
- app 近期 `Traceback/CRITICAL/ERROR/Exception`：`0`
- 本机及公网 HTTP `/healthz/`：200
- 根分区：40 GiB，约 2.6 GiB 可用；仍不得在生产执行重型历史抓取

恢复 Beat 后普通 `celery` 队列出现既有新闻任务并由普通 worker 自然处理；独立 live worker 保持空闲，不消费普通队列。

## 生产来源 proof

artifact：`/opt/umanewsbot/runtime/race_live_source_proofs/production-proof-20260718_035358`

- summary SHA-256：`13856005070721f12e3477573c6deb7570ad5b89f20247114238f91df4156937`
- manifest SHA-256：`5d6e458b50b96151dc0d7d8559d24776d70af60ef78236c74b37be9edba2bbae`
- requests metadata SHA-256：`421a3d7976fbaee0e5c2ed20caaf8fa7b7647895fed6e2666971248ecbb6fc59`
- regions：HTTP 200，55 rows，877 ms
- racecards today：HTTP 200，69 rows，1,458 ms
- results today：HTTP 200，50 rows，1,430 ms

proof 只保存响应 SHA、字段集合、计数、字节数和延迟；未保存 raw payload、赛事实体或凭据，也未写业务 DB。

## Shadow 停止门禁

生产 `2026-07-18` 起共有 `428` 条 future `RaceEvent`，其中英国 `72` 条；两组 `race_datetime` 非空数均为 `0`。当天英国 Group 3 event `924` 的 `race_datetime`、`local_start_time` 均为空，runners/results 均为 `0`。

冻结初始化器要求 manifest 中 aware `race_datetime` 与既有 event 精确匹配，并要求已审核的全部 participant identity。当前仓库没有获准写入这些赛前字段的同步路径，因此：

- 未生成 shadow manifest；
- 未运行 initialization dry-run/apply/verify；
- 未创建 control/tracking/source/participant/policy/allowlist/host budget；
- 未把 runner 切换为 `the_racing_api_free`；
- 未开启 scheduler 或前台 provisional read。

## 发布过程事件

base Compose 重建 web 后，现有 Nginx 仍缓存旧容器 IP，造成短暂 502。web 容器内 `/healthz/` 始终为 200；重启 Nginx 重新解析 `web:8000` 后，本机和公网 HTTP healthz 恢复 200。
