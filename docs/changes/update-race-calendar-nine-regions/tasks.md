# tasks.md — update-race-calendar-nine-regions

## 阶段 0：来源、全集基准与对账（已完成 2026-09-27）

- [x] (application) 新建 worktree 基于 origin/main（c71dcdfc）
- [x] (application) 落盘 `docs/race_calendar_source_registry.md`（九地区多数据源 + 赛历公布节奏）
- [x] (application) 新增 ireland ICS catalog adapter（`hri_pattern_catalog`）+ 页头/标题/守卫适配 + 测试
- [x] (application) 修复澳洲 `open` 年龄解析丢失 25 场/年缺陷 + 守卫误判修复 + 回归测试
- [x] (application) ICS 2025/2026 入 source cache（SHA-256），生成九地区 derived CSV + manifest（5 项上游冲突经审批登记）
- [x] (application) 新增 `reconcile_race_calendar_vs_ics.py` + 8 项测试；生产导出（2,547 赛事 + 3,280 别名）只读对账，产出 gap_ledger/gap_review
- [x] (operations) 核对 TRA registry：2026-09-27 到期、staleness 门禁 2026-09-28——**待用户续验**

## 阶段 1：存量五地区 2025/2026 补缺与赛果（候选已产出 2026-09-27，待生产 apply）

- [x] (application) HK 2025/26 马季前半段 12 场补齐候选（HKJC 官方源，含赛果，已 APPROVED）
- [x] (application) 日本 2 场 J-G1 + NAR 12 场 Jpn1 2025/2026 候选（keiba.go.jp）
- [x] (application) 英国 2025 缺口核验：13 场为冠名变体身份挂接、Dick Poole 改期真实缺场（候选）、Classic H. Stp. 取消
- [x] (application) 美国 2025：Remsen/Matron HRN 候选；4 场障碍 NSA 官方 PDF 验证（新增 race_marker 分场解析）；4 场 2025 未举办标 not_held
- [x] (application) 2026 身份映射 artifact（法 67/英 183/日 65/美 48 未匹配行走系列映射）
- [ ] (operations) 184 组同日重复赛事 canonical 合并候选已产出，逐组审核
- [ ] (operations) 滞留/零赛果修复候选已产出（英5/法8/日3/美20），走 G3 门禁

## 阶段 2：新四地区建链路（进行中）

- [x] (application) 来源探测：四地区官方赛历+赛果源实测 PARSER_READY（产物 detail_probe_20260927/）
- [x] (application) 详情 adapter 接线完成：ireland(irishracing+hri_ras)、australia(racing_australia+just_horse_racing)、
      germany(deutscher_galopp)、middle_east(era+jcsa)；修复 ireland_irishracing 分派缺口与 ireland 归属（0599fdf7→d8a2ab5d→83116959）
- [x] (application) parser×8 测试先行（169 测试）+ 接线契约 17 测试；独立 Agent 两轮 ALL_PASS
- [x] (application) 四地区官方赛历装配：德国 43+42（renntermine 2026 + Wayback 快照链重建 2025）、
      爱尔兰 244+242（HRI 平地+NH 年册，2024/25+2025/26 障碍册经 Wayback 恢复）、
      澳洲 346+187（RA 两季表；2026-27 未发布，8-12 月 144 行挂账）、中东 78（DRC PDF+ERA+JCSA）；
      ICS 对账 review 逐项入册（agent-15 第三轮 ALL_PASS）
- [x] (application) 库存 v2 重建（catalog+timeline）：871 series / 1666 targets / 1180 dated / conflicts=0
- [x] (application) 新增 `materialize_dated_race_targets` 门禁命令 + `materialize_scheduled_historical_event`
      （未来日期→SCHEDULED draft）；26 测试；独立 Agent 第四轮 ALL_PASS
- [x] (integration) 本地 scratch DB 端到端：871 series + 1666 targets 提交、1180 dated 物化为 draft
      （1101 finished + 79 scheduled）、幂等复跑 0 新建、verifier 全绿（materialization_dryrun_20260928/）
- [ ] (application) 2025 全年 + 2026 已完赛赛果批量候选（分地区 discovery→fetch→parse→review）
- [ ] (application) 新地区 2026 剩余 + 2027 已公布赛历（HRI 2027 已公布、DRC/JCSA 2026-27、澳洲 2026-27）经 descriptor 门禁导入（draft）
- [ ] (operations) 逐地区 ICS 应办集合 vs 已采集集合 diff 归零或逐项挂账

## 阶段 3：持续更新机制（待进行）

- [ ] (application) 周期赛历刷新命令/任务：按各地区公布节奏从官方赛历 diff 新增/改期/取消 → 候选 → 门禁导入
- [ ] (integration) 日本登记修复（JRA 身份发现、census 赛后补入、SLO 覆盖应登记未登记）——承接 2026-09-20 根因报告
- [ ] (integration) TRA registry 续验流程入 runbook；新地区 TRA 路线 proof（ireland 可直接用；澳/德/中东评估 group 级 + 官方兜底）
- [ ] (operations) 2027 赛历按公布节奏滚动导入

## 阶段 4：公开与文档（待进行）

- [ ] (application) 前台四地区 tab/颜色/徽章支持；用户确认后批量发布 draft 赛事
- [ ] (operations) 文档回写：current_state/decisions/deploy_runbook/source registry 维护
