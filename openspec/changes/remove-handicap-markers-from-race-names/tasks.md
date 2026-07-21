# 赛事展示名与术语库去让赛标记任务

## 规格与计划

- [x] (application) 生产只读盘点：赛事日历 19 条残留、术语 1701 条分桶基线（2026-07-21）。
- [x] (application) proposal/design/tasks 与 delta spec；openspec strict 校验。
- [x] (application) 规则修订（2026-07-21）：清理判定改为原文括号规则 + 京成杯唯一例外；`docs/decisions.md` 已记录。

## 实现（TDD）

- [x] (application) 删除机制、括号判定与分桶 RED 测试（四种标记、括号/非括号原文、锁定值例外、`H. Allen` 保护、Quality 类 kept）。
- [x] (application) 实现清理/分桶服务 `stable.services.race_name_handicap_cleanup`（dry-run v2：auto_clean/kept/review/locked）与管理命令 `clean_race_name_handicap_markers`。
- [x] (operations) gated commit：默认只读、显式 `--commit`、artifact+备份身份校验、单事务 before CAS、manual lock 整批阻断、幂等、OperationLog；写后 `verify_applied`。
- [x] (operations) SQLite `21/21`、PostgreSQL 16 `21/21`、完整 stable 回归通过（exit 0）、`openspec validate --all --strict` 31/31、`git diff --check`。
- [x] (operations) 生产只读 dry-run v2（只读导出 + 同一代码本地分桶）：autoClean `169`（19 赛历 + 150 术语：香港 134、英国 14、日本 1、空地区 1）、kept `1550`、review `1`（苏特恩杯同地区重名，保持原值）、locked `0`；artifact `outputs/race-name-handicap-cleanup/20260721T132331Z/dry-run.json`（SHA `007af0ec…`）。注：scp 注入被本机权限层拦截，dry-run 改为只读导出后本地计算；commit 路径（部署 vs 注入）在授权门禁前与用户确认。

## 审核与发布

- [ ] (operations) 用户审核 `review.csv`（重点：赛历 19 条、150 条术语、1550 条 kept、1 条 review 与京成杯例外）。
- [ ] (operations) 完整只读代码复审，APPROVED 且 finding 清零。
- [ ] (operations) 复审后取得用户对精确版本的发布授权，并确认 commit 执行路径。
- [ ] (operations) 生产备份（custom-format + `pg_restore -l`）→ 单事务 commit → 写后校验。
- [ ] (operations) 前台抽检：赛事日历香港区不再显示让赛、京成杯系列、首页与详情页回归。
- [ ] (application) evidence-only 文档回写与推送。
