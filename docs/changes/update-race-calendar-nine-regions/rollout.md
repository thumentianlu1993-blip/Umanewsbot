# rollout — 九地区赛事日历发布包（2026-09-29）

## 发布包内容（精确绑定）

- 分支：`kimi/race-calendar-nine-regions`，合并后 main 目标 commit 以实际合并结果为准（合并前 HEAD `1d9ebf25`）。
- 迁移：无新增（新地区枚举在主线 0072 已存在）。
- 配置变化：`.env` 一枚钉扎 `RACE_DATA_SYNC_FUTURE_STANDING_POLICY_SHA256=e73a4e3b556cf1670caed6ca0cae46e5c01dbe711c74712a8fbe9c3fc527d679`。
- 服务重建：镜像重建（policy/fixture 烘焙）+ 重建 `web / worker / beat / race_sync_v2_worker`；db/redis/nginx 不动。
- 功能开关：`RACE_CALENDAR_REFRESH_BEAT_ENABLED` 默认关闭，本包不开启；其他开关不变。
- 生产数据动作（全部走门禁命令，逐条 dry-run→apply→verify）：
  1. 新四地区库存提交：`build_historical_race_inventory --commit`（artifact `inventory_new_regions_2025_2026_v2` + `inventory_new_regions_2027_v1`，approval 随工件）。
  2. 物化 draft：`materialize_dated_race_targets`（manifest sha 钉扎；预期 1180 + 29 场，全部 draft/incomplete，**不发布**）。
  3. 赛果导入：`import_race_event_detail_candidates`（germany 75 / ireland 357 / era 59 / jcsa 14 / australia 51+48，每文件 sha256 钉扎）。
  4. digest 轮换：`repair_data_sync_stalled_events` 先 dry-run 核对候选集再 apply（延续 #222 先例）。
- 明确不做：draft 批量公开（等用户单独确认）；阶段 1 五地区补缺候选 apply（另行确认）；184 组重复合并（逐组审核）；澳/德/中东 TRA 扩展（G3 未批）。

## 步骤

1. CI 绿后合并 PR #220 到 main。
2. 生产：备份 `.env`（`.env.backup.nine-regions-<ts>`）；按 #222 先例经 git bundle 建新 release 目录 `/opt/umanews-release-<sha>-nine-regions-20260929/umanewsbot`，checkout 精确到合并 commit；补齐持久化 runtime 符号链接（verify_persistent_release_mounts 门禁）。
3. 更新 `.env` 钉扎 → compose config 校验 → 重建镜像 → 重建四容器。
4. 部署后验证：`manage.py check`、容器健康、双域名 `/healthz/` 200、`audit_race_data_sync` ready/`route_drift=[]`、`_read_registry_contract(now)` 通过。
5. 数据动作 1-4 按序执行，每步 dry-run 输出与预期计数核对一致再 apply；每步 verify 留证。
6. 传输完整性：所有工件（库存 artifact、候选 jsonl、manifest、approval）经 scp 前本地 sha256 清单，上传后逐文件复验。
7. 回滚：恢复 `.env` 备份 + git revert 合并 commit 后重建回退；draft 赛事与库存行为可经既有 review 流程撤回（均为 draft/incomplete，无公开面影响）。

## 风险与边界

- 新地区赛事全部 `draft + incomplete`，公开面不可见；现有五地区公开内容不受影响。
- 澳洲/爱尔兰缺口为源端限制（RA 保留窗口、JHR 摘要格式、HRI 500 赛日），逐项挂账于 `final_ledger_20260928/`，不伪造。
- JRA multisource policy v2 2026-10-26 到期续期已入 runbook；TRA 月度续验截止 2026-10-27。
- 马匹采集暂停状态不受影响。
