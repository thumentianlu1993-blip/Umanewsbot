# TRA 来源 registry 续期（2026-09-27）

## 背景

项目对 The Racing API（TRA）的自动化调用由一份自建 fail-closed 合同 registry 门禁
（`runtime/policies/race_live/source_registry_the_racing_api_free.json`，镜像内经 Dockerfile COPY
烘焙到 `/app/runtime/policies/race_live/`）控制：钉扎条款核验证据（`verified_at`）、硬有效期
（`valid_until`），并要求文件 SHA-256 与 settings/compose 钉扎一致。该门禁不随 TRA 账单自动续期，
需要周期性人工重新核验条款后更新。

- 上一周期：`verified_at=2026-08-28`、`valid_until=2026-09-27T00:00:00Z`。
- 2026-09-26 用户确认：TRA 条款仍允许当前自动化用途，可以续期到 12-31。
- 到期影响（若不续）：TRA 身份发现与 TRA 路线同步 fail-closed（`source_runtime_contract_rejected`），
  已登记的 18 个 TRA 赛事停止刷新；JRA 官方路线（multisource policy）不受影响。

## 变更内容（纯配置/治理，无 schema 迁移、无业务代码变化）

1. registry 两份仓库副本同步更新（`runtime/policies/race_live/` 与
   `docs/changes/realtime-race-results/`——后者是 Dockerfile 实际烘焙来源）：
   - `valid_until`: `2026-09-27T00:00:00+00:00` → `2026-12-31T23:59:59+00:00`
   - `evidence.verified_at`: `2026-08-28T00:00:00+00:00` → `2026-09-26T17:15:00+00:00`
   - 条款复核证据：terms-of-service 与 API documentation 于 2026-09-26T17:14Z 重新抓取
     （HTTP 200，内容 SHA 记录在本 change 的发布证据中）。
2. 新 registry SHA-256：`0e1cdff89052b7b5f482b4761f1e39e3f38eefdf30405ae6a5d45b64e737b322`。
   钉扎更新：`.env.example`、`docker-compose.yml`×3、`docker-compose.prod.yml`、
   `docker-compose.prod.lowcost.yml`×4、两个测试文件。
3.  standing policy 重新渲染（`render_race_data_sync_standing_policy`）：roster 摘要对全部条目闭集，
   TRA registry SHA 变化导致全部 13 条 route_digest 轮换（非 TRA 路线 digest 也随之变化属预期）。
   政策内容（地区/来源/资格/有效期 2027-08-28）不变；审批元数据更新为本次续期。
   新 standing policy SHA-256：`80fe5cf3383daf7d38ffa26b95cf815d6b7a3d0250ae07ca12ccbfb9a7828df2`。
4. 测试钉扎同步更新（`test_race_live_multiregion_pipeline.py`、`test_race_data_sync_audit.py`）。

## 验证（本地）

- `test_race_live_multiregion_pipeline`、`test_race_data_sync_audit`、`test_realtime_race_results`、
  `test_race_data_sync_*`（providers/admission/pipeline_a/results/result_admission/repair/
  lifecycle_advance/chain_e2e）356 项通过；`test_race_data_sync_policy`、`test_race_data_sync_policy_v2`、
  `test_race_multisource_enrollment` 34 项通过；`manage.py check` 通过。
- 旧 SHA 渲染 standing policy 与仓库既有文件逐字节一致（工具链可复现性证明）。

## 生产发布包（G2，见 rollout.md）

镜像重建（registry 烘焙进镜像）+ `.env` 两枚钉扎更新 + 四容器重建 + 部署后
`repair_data_sync_stalled_events` 轮换 18 个 TRA 登记到新 route digest + 验证同步恢复。
