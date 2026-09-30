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

## 执行结果（2026-09-29，生产 47.239.167.86）

- **合并**：PR #220 → main `3ef45b42`（CI 全绿：release-contract、stable 全量对照 baseline/candidate、新增失败检查全部 pass）。
- **部署**：release 目录 `/opt/umanews-release-3ef45b42-nine-regions-20260929/umanewsbot`（git bundle 传入、checkout 精确 3ef45b42、持久化符号链接按 #222 先例补齐）。首次误走 `deploy_lowcost.sh` 被 Release-B preflight fail-closed 拦下（该入口不含 0079 schema 代际）；改走正确入口 `deploy_0079.sh deploy`（0079 同 schema 前向发布），备份/意图/排水/schema/静态/恢复全过。
- **验证**：四容器自新 release 重建、web healthy；`manage.py check` 通过；本机与双域名 `/healthz/` 200；`audit_race_data_sync` ready、`route_drift=[]`；standing policy 14 条含 ireland TRA 一等路线（钉扎 `e73a4e3b…` 生效）。
- **数据动作（全部门禁命令，dry-run→apply→verify）**：
  1. 库存提交：v2 `series_created=871 / targets_created=1666`；2027 `series_created=1 / series_updated=28 / targets_created=29`。
  2. 物化：1180（finished 1101 + scheduled 79）+ 29（scheduled），verifier 双 `ok=true, error_count=0`。
  3. 赛果导入（sha256 钉扎逐文件）：德 75 / 爱 357 / ERA 59 / JCSA 14 / RA 51 / JHR 48，共 604 场、赛果行 5448。
  4. digest 轮换：`repair_data_sync_stalled_events` dry-run 0 个可修复候选（3 个 `source_identity_expired` 为 #222 已记录遗留，走 PR #221 换绑路径另行处理），audit 无漂移，未发生写入。
- **生产终态**：2025+ 赛事按地区 australia 533 / germany 85 / ireland 486 / middle_east 105（含 2027×29）；新地区 1209 场全部 `draft+incomplete`（finished 1101 + scheduled 108）；抽查 Lambourn/Goliath/Forever Young 冠军正确；公开面 ire­land tab 200 且 draft 不可见。
- **健康观察**：7 个 open incident 全部为 9-17/19/26 的既有 provisional_overdue（与本次无关）；最近 TRA 记账 01:19 UTC（部署前，当前时段无窗口内赛事属正常安静期）。
- **传输完整性**：release bundle 40 文件 SHA256SUMS 宿主机与容器内双侧核验通过（仅清单自引用除外）。

## 阶段 1 补缺 + 批量公开发布：生产执行结果（2026-09-30）

用户批准"阶段 1 五地区补缺候选生产 apply + 新地区 draft 批量公开"。全部经门禁命令与带 OperationLog 的受审修正完成；装配计划与验证证据在本地 `runtime/race_calendar_nine_regions/phase1_apply_20260930/`（APPLY_PLAN.md / REPORT.md / SHA256SUMS.txt，scratch 全链验证通过）。

### B0 数据修正（OperationLog 审计）

- HK 11 target（49452 等）：`year` 2026→2025（马季跨年按 `local_date.year` 归档，证据 HKJC 官方结果页日期）；
- JRA 2 target（53232/53233）：`expectation_status` not_held→held（JRA 官方 jyusyo_2025.html 证实两场 2025 J-G1 均举办）；
- 清理 12 条陈旧 `legacy` 公开路径重定向（year=2025，旧马季错位修复的历史遗留，遮挡真实 2025 版赛事的 canonical 路径）。

### 批次结果（dry-run→apply→verify，计数与 scratch 逐格一致）

| 批次 | 结果 |
|---|---|
| B1 HK 11 | date-discovery commit applied=11（READY+finished draft event）；详情 11 scopes（135 出走/132 赛果） |
| B1b 香港杯 2025 | 新建 event（2025-12-14，冠军 浪漫勇士，7 赛果）；target 49460 属 2026 版既有赛事，不动 |
| B2 JRA 2 | applied=2 + 详情（エコロデュエル×2 冠军，22/21） |
| B3 NAR 12 | created=12（published）+ 详情 163/160（川崎纪念 メイショウハリオ ✓） |
| B4 US×2 | created=2 + 详情 24/19（Paladin/Final Accord） |
| B5 障碍×4 | created=4 + 详情 31/28（NSA 官方 PDF，4 冠军全对） |
| B6 UK×1 | created=1 + 详情 13/11（Dick Poole 改期场 Anthelia） |
| B7 not_held×5 | created=5（cancelled+draft，UK Classic 冰冻取消 + US×4 2025 未举办） |
| B8 stuck 25 | bundle（sha 829bbf66…）dry-run 196 行 → apply 25/25 → verify 25/25 verified；12 场挂账不臆造 |

### 发布（draft→published）

- 状态归一（OperationLog）：604 个有赛果 target 置 `imported`（赛果实经 slug 键控详情导入）；6377+168 runner 补 `derived_from_results` 溯源标记。
- 门禁发布：`publish_historical_race_targets`（eligible manifest 617 场：604 新地区 + 13 阶段1），dry-run 0 blocked → apply `published_count=617` → verify `ok=true, error_count=0`。
- scheduled/targetless：108 场未来赛事（2026×79 + 2027×29）+ 8 场无 target 赛事（香港杯/US×2/UK×1/障碍×4）按既有 published+partial 口径发布（116 场，OperationLog 逐条）。
- **保持 draft**：497 场已完赛但无赛果的新地区赛事（澳洲 434 / 爱尔兰 59 / 中东 3 / 德国 1，逐项挂账于 final_ledger）——不与既有"finished 零赛果"反模式同流。

### 公开面终验

爱尔兰 2025 日历（Curragh/Leopardstown 内容渲染）、Irish Derby 详情 200（Lambourn）、Melbourne Cup（HALF YOURS ×4）、香港杯 2025（浪漫勇士）、Saudi Cup 200（Forever Young）、中东 2027 日历（Dubai World Cup 在列）；draft 赛事公开面不可见（发布前实测）。TRA 同步/审计无新增 incident；`audit_race_data_sync` ready。
