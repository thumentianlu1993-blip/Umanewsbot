# tasks：2026 赛历赛事中文展示名补齐

## 0. Pre-declared hypotheses（PASS/BLOCKER 阈值）

- H1：生产只读导出目标行数 == 573；不等于 573 → BLOCKER（范围漂移，回到探索）。
- H2：候选分桶（series+term+history+new+manual）计数之和 == 573；不等 → BLOCKER。
- H3：去冠名基名匹配只增不抢——任何 L2 命中行的基名必须与原名差异仅为名单内冠名/括号/ Presented-by 尾缀；出现名单外剥离 → BLOCKER。
- H4：commit 写入数 == 用户审核通过数；kept/veto/manual 行零改动；否则 verify 失败即回滚。

## 1. 实施任务

- [x] (application) 服务层单测先行：匹配（含 aliases_ja 与 translation_status 条件）/冠名剥离/歧义转人工/让赛守卫/系列继承（L0）/manual_lock 拒绝/CAS/幂等/bulk_update 列约束（RED→GREEN 54/54）
- [x] (application) 实现 `stable/services/race_display_name_translation_2026.py`（L0/L1/L2/L3 + manifest + commit/verify；复审后追加 decision 列一致性校验）
- [x] (application) 实现管理命令 `translate_2026_race_display_names`（默认 dry-run；--build-manifest/--commit/--verify 需 artifact SHA + 备份身份 + 授权信息）
- [x] (application) SQLite + PostgreSQL 16 双跑全绿（54/54）；去让赛回归 26/26
- [x] (integration) 生产只读导出 573 场（含 `manual_lock_flags`）+ 术语库 3570/历史 8411；本地 dry-run：series 2/term 76/history 168/needs_translation 326/manual 1（H1/H2/H3 PASS）
- [x] (integration) L3 新翻译候选（4 个地区代理，326/326 全覆盖）合入审核工作簿（high 280/medium 81/low 212）
- [ ] (integration) 独立 reviewer 只读复审：首轮 REVISE（P2-1 工作簿 5 行让赛标记→已转 manual；P2-2 decision 契约→已加校验+spec 文档化），待限定复审（fingerprint 前后一致，APPROVED 且 actionable 清零）
- [ ] (operations) 合并 main → `deploy_lowcost.sh` 部署 → 生产核验（`git rev-parse HEAD`、容器状态、`/healthz/`、命令 `--help` 可用）
- [ ] (operations) 生产备份（custom-format + pg_restore -l）→ --commit → --verify（H4）
- [ ] (operations) 前台抽检（DB verify 为主；命中目标赛事的 region/year/q 视图 + ≥5 场详情）→ evidence-only 回写：release_report 落 `docs/changes/translate-2026-race-display-names/release_report.md`，同步 `docs/current_state.md`、`docs/project_status.md`、`docs/deploy_runbook.md`，新锁定规则（如有）记 `docs/decisions.md`

## 执行记录

- 2026-07-22：change 建立；方案审核首轮 REVISE（F-001 部署 task 缺失、F-002 series 来源不一致、F-003 缺 manual_lock 守卫、F-004 L1 别名/状态条件，及 F-005~F-011 低优先级项），已全部修订，待同一 reviewer 复审。
