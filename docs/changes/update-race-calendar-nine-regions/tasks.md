# tasks.md — update-race-calendar-nine-regions

## 阶段 0：来源、全集基准与对账（已完成 2026-09-27）

- [x] (application) 新建 worktree 基于 origin/main（c71dcdfc）
- [x] (application) 落盘 `docs/race_calendar_source_registry.md`（九地区多数据源 + 赛历公布节奏）
- [x] (application) 新增 ireland ICS catalog adapter（`hri_pattern_catalog`）+ 页头/标题/守卫适配 + 测试
- [x] (application) 修复澳洲 `open` 年龄解析丢失 25 场/年缺陷 + 守卫误判修复 + 回归测试
- [x] (application) ICS 2025/2026 入 source cache（SHA-256），生成九地区 derived CSV + manifest（5 项上游冲突经审批登记）
- [x] (application) 新增 `reconcile_race_calendar_vs_ics.py` + 8 项测试；生产导出（2,547 赛事 + 3,280 别名）只读对账，产出 gap_ledger/gap_review
- [x] (operations) 核对 TRA registry：2026-09-27 到期、staleness 门禁 2026-09-28——**待用户续验**

## 阶段 1：存量五地区 2025/2026 补缺与赛果（待进行）

- [ ] (application) HK 2025/26 马季前半段 12 场补齐（HKJC 官方源，含赛果）
- [ ] (application) 日本 2 场 J-G1（中山大障害/中山グランドジャンプ 2025）确认匹配或补齐；NAR Jpn1 2025/2026 从 keiba.go.jp 单补（ICS 不收地方级）
- [ ] (application) 英国 2025 缺口 15 场逐项确认（让赛家族冠名版本 vs 真实缺场）后补齐
- [ ] (application) 美国 2025 缺口 10 场（Matron S. 由 TOBA 补；4 场障碍确认）补齐
- [ ] (application) 2026 未匹配 ICS 行（法 67/英 183/日 65/美 48）走系列身份映射，禁止盲目新建
- [ ] (operations) 145 组同日重复赛事按既有 canonical 合并流程处理（逐组审核）
- [ ] (operations) 24 场 stuck_scheduled + 9 场 finished 零赛果按 2026-08-16 流程补赛果/修状态（G3 门禁）

## 阶段 2：新四地区建链路（待进行）

- [ ] (application) 详情 adapter：ireland(hri_ras/irishracing)、australia(racing_australia)、germany(deutscher_galopp)、middle_east(era/jcsa)——空结果 fail closed，保留 provider ID/SHA
- [ ] (application) 四地区 inventory/series 建立（approved）+ 2025/2026 赛事物化（draft）
- [ ] (application) 2025 全年 + 2026 已完赛赛果导入（bundle/dry-run/apply/verify，分地区成批）
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
