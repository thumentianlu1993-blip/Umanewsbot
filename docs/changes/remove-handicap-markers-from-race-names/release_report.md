# 赛事去让赛清理发布报告（2026-07-22）

## 结果摘要

赛事中文展示名与 race 术语的去让赛清理已写入生产并验收通过：**168 条**（19 赛历对象 `chinese_name` + 149 条术语 `target_zh`）单事务写入，1550 条 kept 与 2 条 review 零改动，写后独立校验通过。

## 审核链

1. 首轮独立只读代码复审（Claude Code 等价复审，替代无法恢复的 codex reviewer 会话，沿用 2026-07-21 决策先例）：**REVISE**，1 项 P1——term 5087（`THE KWANGTUNG HANDICAP CUP (HANDICAP)` / `广东让赛杯(让赛)`）原文同时含未括号与括号 handicap，末尾兜底删除会错改为「广东杯」。
2. 修复：新增未括号 handicap 守卫（混合标记一律进 review 保持原值；京成杯锁定例外豁免），测试 21→26，RED→GREEN。
3. v3 artifact：2026-07-22 生产只读导出（1720 对象，与 v2 零漂移）+ 修复后代码本地分桶；v2→v3 唯一差异为 5087 移入 review。
4. 同一 reviewer 限定复审（仅 P1 修复及直接触及路径）：**APPROVED**，P0/P1/P2 清零；审前/审后完整 fingerprint `2889f4b2b88fa2f3efbec618f245edf54534cb7667458e13bf7cf66f516ed2a5` 逐字节一致。

## 发布版本

| 项 | 值 |
|---|---|
| 发布提交 | `5b491561`（approved parent `73113639`，INDEX_TRANSITION_OK，approved content hash `4b40a5c9…`） |
| main 合并 | `cce280a7`（与 P0 马资料批次分支合并后部署） |
| artifact | `runtime/artifacts/race-name-handicap-cleanup/20260721T154923Z/dry-run.json` |
| artifact SHA-256 | `30d85d1a925dded235b577553d18dc321f8ef32e661a4c352684aad638d258ac` |
| contentSha256 / batchId | `23eddf04404ba416da124ad178df7f2e9707253083457806575534ae88aecbab` |
| 分桶 | autoClean 168 / kept 1550 / review 2（5087 广东让赛杯、5570 苏特恩杯，均保持原值）/ locked 0 |
| 用户授权 | 2026-07-22 用户针对上述精确版本回复「发布吧」 |

## 生产执行

- 部署：生产 `/opt/umanewsbot` 切 main 快进到 `cce280a7`，`bash ./deploy_lowcost.sh`；无迁移，web/worker/beat 重建，`/healthz/` 200。
- 写前备份：`backups/db/pre-handicap-cleanup-20260722_023308.dump`，228136448 bytes，SHA-256 `23fc73ee8277e2dfc936df1f1d217e7b85235409d70e85d5abf6a489e2a5176b`，`pg_restore -l` 通过（1017 项）。
- 写入：`clean_race_name_handicap_markers --commit`（artifact/备份 SHA + 授权信息），结果 `written=168`，batchId `23eddf04…`；OperationLog 审计条目已落库。
- 校验：`--verify` → `{"ok": true, "written": 168, "kept": 1550, "review": 2}`。
- 前台抽检：赛事日历（默认/香港/日本视图）无「让赛」残留；精英杯详情页 `/races/2026/hkjc-2026-0621-18/` 200 且显示「精英杯」；京成杯系列 285 与术语 15215/1972 = 「京成杯秋季赛」；5087/5570 保持原值；首页 200、金杯详情 200。
- 清理：web 容器 `/tmp/handicap-dry-run-v3.json` 已删除；历史拦截的注入文件经确认从未上传，无残留。

## 遗留（不在本 change）

- term 5087「广东让赛杯(让赛)」与 5570「苏特恩杯（让赛）」保持原值，待人工决定展示名（5087 正确清理结果应为「广东让赛杯」，需确认后走单独受控流程）。
- 2026 赛历与历史系列双卡片、1300 系列术语同步、新闻历史文章让赛回填：另起 change。
- 复审 P3 建议（不阻塞）：verify 覆盖 locked 桶、备份 SHA hex 校验、赛历 action 记录 original、CSV kept reason 一致性、bulk_update 信号交互、全角/多空格、`(h)` 误伤面、京成杯豁免测试改用真实原文形态。
