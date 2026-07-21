# 赛事去让赛清理任务断点续接文档（2026-07-21）

> 用途：电脑重启后从断点继续。本文件是当前唯一权威续接入口。

## 当前状态：等待用户审核 dry-run 清单 + 选定 commit 路径

- worktree：`/Users/mentianlu/Code/umanews/.worktrees/remove-handicap-markers`
- 分支：`codex/remove-handicap-markers-from-race-names`（基于 `origin/main`）
- OpenSpec change：`openspec/changes/remove-handicap-markers-from-race-names/`（proposal/design/tasks + delta spec，strict 31/31 通过）
- 代码（已实现、未提交进生产）：`server/stable/services/race_name_handicap_cleanup.py`、`server/stable/management/commands/clean_race_name_handicap_markers.py`、`server/stable/test_race_name_handicap_cleanup.py`
- 测试：SQLite `21/21`、PostgreSQL 16 `21/21`、完整 stable 回归 exit 0、`git diff --check` 通过
- **未写生产、未部署、未合并 main**

## 已锁定的规则（用户 2026-07-21 决策，`docs/decisions.md` 已记录）

1. 原文名（original_name / canonical_name_original / source_ja）中 handicap/让赛 **被括号圈住** → 补充说明，清理中文展示名标记；**未被括号圈住** → 赛事名组成部分，保留进 `kept`。
2. 京成杯唯一例外：`京成杯秋季让赛` 一律 → `京成杯秋季赛`（与已上线的 6125/Event 96/16 场历史一致）。
3. 删除机制只删不补：四种中文标记 + 包裹括号 + 括号前单分隔空格；不造词。
4. 范围：赛事日历对象 + race 术语 target_zh；不新增术语（1300 系列同步不在本 change）、不回填历史文章。

## 当前有效候选（用户审核中）

- `runtime/artifacts/race-name-handicap-cleanup/20260721T132331Z/dry-run.json`，SHA-256 `007af0ec1f9ad905449257fdeca8eebf6e9e726f2a26e45c0a1fbfc7f42ee373`
- 同目录 `review.csv`（全量 1721 行），SHA-256 `f13980c149346885992fd1536142cdb8eb03ad6f8e108613dcd5c54cef881394`
- 分桶：autoClean `169`（19 赛历：Event 145-163 九场、Series 175-193 九个香港 + 285 京成杯例外；150 术语：香港 134、英国 14、日本 1（15215）、空地区 1（1972））、kept `1550`、review `1`（term 5570 苏特恩杯同地区重名，保持原值）、locked `0`
- 旧候选 `outputs/race-name-handicap-cleanup/20260721T125549Z/`（旧"一律删除"规则）**已失效**
- dry-run 计算方式说明：scp/base64 注入被本机权限层拦截，改为生产只读导出（只读 Django 查询，无写）+ 同一代码本地分桶；commit 前的 before CAS 会再次以生产实时值校验，漂移即整批回滚。

## 断点后的下一步（顺序不可跳）

1. 用户抽看 `review.csv` 并确认（重点：150 条术语清理、1550 条 kept、1 条 review、京成杯例外 3 对象）。
2. 用户选定 commit 执行路径：
   - (a) 合并部署到生产（推荐：正式管理命令，标准部署流程）；
   - (b) /tmp 注入先例（届时需用户对上传动作单独放行——本机权限层今日已两次拦截 scp/base64 注入）。
3. 我做完整只读代码复审（参照 `docs/codex_workflow.md` 与上一任务的复审纪律），APPROVED 且 finding 清零。
4. 复审后对精确版本重新取得用户发布授权。
5. 生产 custom-format 备份（`pg_restore -l` 校验）→ `--commit` 单事务写入（带 artifact SHA `007af0ec…` 或届时重新生成的等价 artifact、备份身份、授权信息）→ `--verify` 写后校验。
6. 前台抽检：赛事日历香港区不再显示"精英杯 （让赛）"等、京成杯系列、首页/详情回归。
7. evidence-only 文档回写、提交、推送；清理生产 /tmp 临时文件（`race_name_handicap_cleanup.py`、`handicap-dry-run-output.txt`——注意：今日 scp 被拦截，这些文件实际未上传成功，生产 /tmp 无残留需要清理，届时先确认再清）。

## 相关断点（另一任务，已完成无需续接）

- 五区赛事中文名导入：已于 2026-07-21 正式写入生产并验收（worktree `.worktrees/translate-collected-race-horse-names`，分支 `codex/translate-collected-race-horse-names` 已推送；证据 `docs/changes/import-reviewed-race-name-translations/release_report.md`）。
- 遗留后续项（未立项）：2026 赛历与历史系列双卡片问题、1300 系列术语同步、新闻历史文章让赛回填。需要时另起 OpenSpec change。
