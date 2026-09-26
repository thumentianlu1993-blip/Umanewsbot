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
