# rollout — TRA registry 续期发布包（2026-09-27）

## 发布包内容（精确绑定）

- 分支：`kimi/tra-registry-renewal-20260927`（基于 origin/main `15c79f22`，含 PR #221 换绑工具）。
- 无迁移、无业务代码变化；配置/治理文件 + 测试钉扎。
- 生产配置变化：`.env` 更新两枚钉扎
  - `RACE_LIVE_TRA_REGISTRY_SHA256=0e1cdff89052b7b5f482b4761f1e39e3f38eefdf30405ae6a5d45b64e737b322`
  - `RACE_DATA_SYNC_FUTURE_STANDING_POLICY_SHA256=80fe5cf3383daf7d38ffa26b95cf815d6b7a3d0250ae07ca12ccbfb9a7828df2`（若生产 .env 存在该项）
- 服务重建：镜像重建（registry 文件经 Dockerfile COPY 烘焙），随后重建 `web / worker / beat / race_sync_v2_worker`；db/redis/nginx 不动。
- 生产数据动作：部署后 `repair_data_sync_stalled_events` 先 dry-run 核对候选集恰为 18 个 TRA 登记
  （旧 route_digest `7591a4f2834c…`），再 `--apply` 轮换到新 digest；dry-run 与 apply 绑定同一候选 SHA。
- 功能开关：不变更任何开关。

## 步骤

1. 合并 PR 到 main。
2. 生产备份 `.env`（`.env.backup.tra-registry-renewal-<ts>`）；本包不写业务表，数据库备份按部署脚本既有行为执行。
3. 更新 `.env` 两枚钉扎 → compose config 校验。
4. 按既有 `deploy_lowcost.sh` 流程拉取 main、重建镜像、重建四容器。
5. 部署后验证：
   - `manage.py check`、容器健康、双域名 `/healthz/` 200。
   - 生产 shell 内 `_read_registry_contract(now=timezone.now())` 通过且 `valid_until=2026-12-31T23:59:59+00:00`。
   - `audit_race_data_sync` 的 `standing_policy.route_drift=[]`、`configuration_status=ready`。
   - `repair_data_sync_stalled_events` dry-run 候选恰为 18 个 TRA 登记 → apply → 复跑 audit 验证轮换完成。
   - 观察下一个同步周期产生新的 `RaceDataTransportCapacityLedger` 行（TRA 请求恢复）。
6. 回滚：恢复 `.env` 备份 + git revert 本 PR 后重建镜像回退。

## 风险与边界

- 不换绑 JRA multisource 登记（proof `bbdfb414…` 独立于 TRA registry）。
- 18 个 TRA 身份（`RaceResultSourceIdentity` registry_digest 为旧 roster 摘要）在轮换后由换绑链
  重新绑定；缺身份/缺登记的赛事维持 fail-closed，不伪造。
- 本包不扩大任何来源、地区或能力范围；TRA 套餐内容与权限不变。

## 执行结果（2026-09-26 UTC / 2026-09-27 北京凌晨）

- PR #222 合并为 main `9c8891b8`；新 release 目录
  `/opt/umanews-release-9c8891b8-tra-registry-20260927/umanewsbot`（git bundle 传入，checkout 精确到
  `9c8891b8d0bbfdd0ccb277d18e548888c909f418`）。
- 首次 deploy 因新 release 目录缺持久化 runtime 挂载绑定被 `verify_persistent_release_mounts.sh`
  fail-closed 拦下（"tracked horse-profile rollback state is not bound to persistent runtime"）；
  按现行 release 目录同款方式补齐 `runtime/{race_data_sync,race_live_publications,race_live_racecards,
  secrets,upcoming_racecard_urls}`、`runtime/horse_profile_completion/{cache,batches,review,budget}` 与
  `deploy/certs/letsencrypt` 的持久化符号链接后通过。
- `deploy_0079.sh deploy` 完成：镜像 `37c044485231`（umanewsbot:prod），0079 协调器完成备份/schema/静态
  检查并恢复原服务集合；四容器（web/worker/beat/race_sync_v2_worker）在新 release 目录重建，web healthy。
- 验收：合同检查通过（`valid_until=2026-12-31T23:59:59+00:00`、`verified_at=2026-09-26T17:15Z`）；
  `audit_race_data_sync` 为 `configuration_status=ready`、`route_drift=[]`、`would_write=false`；
  `manage.py check` 通过；本地与双域名 `/healthz/` 均 200。
- 同步恢复证据：部署后（17:40 UTC 后）`RaceDataTransportCapacityLedger` 持续出现新的 TRA 记账
  （17:47、18:07 UTC），JRA 赛前路线同步活跃；检查点 `consecutive_failures` 全部为 0，部署后无新 incident。
- 公网抽样：今日赛事 975/976（英国）与 106（天狼星锦标）页面 200 且状态 finished；
  明日 107（短途锦标 G1）scheduled 正常在历。

## 遗留边界（如实记录）

- 18 个续期前登记的 TRA enrollment 仍携带旧 route_digest/standing_policy_digest。其中 15 场为已完赛且
  赛果早已发布的历史赛事（8/30–9/19），digest 失配后 fail-closed 不再有写入，无数据风险；其中
  772/828/830/833/970/975/976 七场在部署前就有 open incident（含 828/830 缺正式结果的既有缺口），
  续期未新增。census 自动换绑只覆盖当前窗口内赛事；窗口外已完赛登记的换绑/收口需另行按
  PR #221 换绑路径或后续小工具处理，本次未强行写库。
- JRA multisource 登记（5 个，proof `bbdfb414…`）不受 TRA registry 影响。
- 下一次月度续验截止：`verified_at` + 31 天 = 2026-10-27（早于 `valid_until` 2026-12-31，
  staleness 门禁先到期）。
