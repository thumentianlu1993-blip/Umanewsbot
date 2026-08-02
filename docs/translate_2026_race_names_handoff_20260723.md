# 交接文档：2026 赛历赛事中文展示名补齐（translate-2026-race-display-names）

> 写于 2026-07-23，供后续接手的模型/会话续接。本文件是唯一权威交接入口。
> 状态：**生产写入已完成并验收；evidence 文档已随 main 更新提交，本交接文档为最终归档。**

## 1. 项目整体背景

- **Umanews**（生产站点 https://umafans.run）：Django 赛马新闻 + 赛事日历应用。
  生产主机 `root@47.239.167.86`，仓库 `/opt/umanewsbot`，Docker Compose
  （web/worker/beat/db(PG16)/redis/nginx/race_live_worker），部署入口 `bash ./deploy_lowcost.sh`。
- **赛事日历**（`/races/`）：主显示字段是 `RaceEvent.chinese_name`
  （`server/stable/templates/stable/public/race_calendar.html:56,103`），空或非中文时用户看到原文。
- **协作工作流**：`docs/codex_workflow.md` 是全项目强制纪律——
  探索 → docs/changes/<slug>/ 五文档（spec/design/test_cases/tasks/rollout）→ 方案审核 →
  测试先行 → 子代理实现 → 独立 reviewer 复审（fingerprint 前后一致、actionable 清零）→
  用户明确发布授权（"发布吧"级措辞，只对精确版本有效）→ 部署/写入 → evidence-only 回写
  （allowlist 仅 `docs/current_state.md`、`docs/project_status.md`、`docs/deploy_runbook.md`、
  `docs/decisions.md`、`docs/changes/<slug>/release_report.md`）。
  任何生产写入必须：备份（custom-format + `pg_restore -l`）→ 单事务 CAS → OperationLog 审计 → verify。
- **环境注意**：
  - 生产 SSH 需用户点名授权主机（权限分类器会拦 agent 自发现的目标）。
  - 生产 `git checkout/pull` 后 `deploy/*.sh` 执行位被重置，部署前必须
    `chmod +x deploy_lowcost.sh deploy/*.sh deploy/docker/*.sh`。
  - 本机 Docker 走 colima（`colima start`）；PG16 测试用一次性容器
    `postgres:16-alpine`（端口 55432，env：`DB_ENGINE=postgres POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=55432 POSTGRES_SSLMODE=disable`）。
  - 本地 venv：`/Users/mentianlu/Code/umanews/.venv/bin/python`。
  - 主仓库 `/Users/mentianlu/Code/umanews` 检出在另一分支（codex/deploy-news-gates-france，有大量脏文件），**不要动它**；所有工作在 `.worktrees/` 下进行。
  - P0 马资料会话高度活跃，频繁推进 origin/main 并切换生产检出分支；合 main 前务必先
    `git fetch` 核对生产当前检出（`ssh ... 'cd /opt/umanewsbot && git log --oneline -1'`）。

## 2. 该需求要做什么

2026-07-22 核验发现：已发布赛事 9,820 场中 **573 场（全部 year=2026）**的 `chinese_name`
是原文回退（美 242/英 171/法 152/日 8；香港 0），赛历直接展示英文/日文假名。
本 change 为这 573 场补齐中文展示名：

- 只写 `RaceEvent.chinese_name`（573 场 2026 已发布赛事）；不动系列/术语库/原文/历史文章。
- 候选四级来源：L0 系列继承 → L1 术语库 → L2 历史译名（含去冠名基名匹配）→ L3 新翻译（Claude 生成）。
- 风格锁定：冠名一律不进中文名；括号让赛标记不进名，**未括号让赛指标（handicap/H'Cap/裸 H）
  = 赛事名组成部分可保留**；歧义一律转人工，用户对工作簿逐行定稿后才可写入。
- change 文档：`.worktrees/translate-2026-race-names/docs/changes/translate-2026-race-display-names/`
  （spec/design/test_cases/tasks/rollout + release_report）。

## 3. 已经做了什么（全部完成）

1. **探索**：573 场盘点；563/573 所属 2026 日历系列同为原文回退（双卡片问题，另案）；
   历史译名风格确认（`Cleeve Hurdle[McCoy Contractors]`→「克利夫跨栏锦标」，冠名全剥）。
2. **方案**：五文档 + plan-eng-review 首轮 REVISE（11 findings）→ 修订 → 复审 **APPROVED**。
3. **实现**（测试先行）：`server/stable/services/race_display_name_translation_2026.py`、
   `server/stable/management/commands/translate_2026_race_display_names.py`、
   `server/stable/test_race_display_name_translation_2026.py`（61 测试，SQLite/PG16 双绿）。
4. **候选与工作簿**：生产只读导出（573 目标 + 3570 术语 + 8411 历史）→ 本地分桶
   （series 2/term 76/history 168/needs_translation 326/manual 1；H1/H2/H3 PASS）→
   4 个地区翻译代理生成 L3（326/326 全覆盖）→ 工作簿
   `runtime/artifacts/translate-2026-race-display-names/20260721T200746Z/review.csv`。
5. **代码复审四轮**（同一 reviewer 限定复审）：R1 REVISE（工作簿 5 行让赛标记、decision 列契约）
   → R2 APPROVED → R3 REVISE（用户定稿触发：让赛例外、Excel BOM utf-8-sig、verify_applied 例外未同步 P1）
   → R4 **APPROVED**（build/commit/verify 三层例外一致，actionable 清零）。
6. **用户定稿**：`review_573条赛事中文名_复核完成.csv`（同目录，SHA-256
   `47ba2e32fb96675ffe77888466dfb93f47c34e2489f5888d32fafe140b1d5d7d`）：
   573/573 填名、209 改名、6 人工裁决、8 重名处理、0 否决、0 重名、before 零漂移。
   关键裁决：仅 id 666 保留「让赛」（「新手让赛跨栏锦标」，防撞名）；
   重名用地区括注/区别译名（日蚀大赛英/日蚀锦标法等）；两条 Bayakoa 系列允许同名。
7. **发布**（用户 2026-07-23「发布吧」授权）：
   - 提交 `bd03b100`（INDEX_TRANSITION_OK，approved content hash `edb1f5c2…`），推送分支；
   - 合并 main（`cc88da3a`；P0 的 `codex/recover-publish-ready-discard` 随后并入为 `6167b6c0`）；
   - 生产切 main 快进 `6167b6c0` + `deploy_lowcost.sh`（无迁移，healthz 200）；
   - 生产现场 `--build-manifest`（实时 before，零漂移），manifest SHA-256
     `b9f1e8b73e84da9df141a78081a1da2ba29d727539f12ce2fb708a95df4375c8`；
   - 备份 `backups/db/pre-translate-2026-race-names-20260723_012307.dump`
     （232,399,205 bytes，SHA-256 `cdcc751ed852019830721ddea0894afe04c0fcf7f7c5223921ca947c66edd04c`，pg_restore -l 1018 项通过）；
   - `--commit` 单事务 **written=573**，batchId（OperationLog）
     `d2e2b203d9c3e67f683650c397ed6af038c17123d9c54cf71bdb302b784ce673`；
   - `--verify` → `{"ok": true, "written": 573, "veto": 0}`。
8. **抽检**：DB 全量复扫 published 非 CJK 0、空名 0；美/英/法/日/港五视图卡片标题 0 非 CJK；
   详情页 4 场（巴亚科亚锦标/卓定咸金杯/新手让赛跨栏锦标/凯旋门大赛）均 200 渲染中文名。
9. **清理**：web 容器 /tmp 定稿与 manifest 临时文件已删除；manifest 副本留存本机
   `/tmp/translate2026-manifest-production.json`（SHA 同上 `b9f1e8b7…`）。

## 4. 文档提交后续

origin/main 在后续演进中已纳入 2026 赛事中文名补齐的 evidence 更新（`current_state.md`、
`project_status.md`、`deploy_runbook.md`、`decisions.md`、
`docs/changes/translate-2026-race-display-names/release_report.md`），并补充了
治理证据缺口说明（详情页抽检数量不足、Claude Code 等价复审不等于现行 Codex 原生只读 review、
`bd03b100` 与最终部署集成版本 `6167b6c0` 的差异等）。

本交接文档为最终归档项，记录完整背景、定稿裁决、生产执行指纹与遗留事项。

## 5. 下一步要做什么

1. 提交本交接文档到 main（docs-only，fast-forward）。
2. 推送后：生产 `git pull --ff-only origin main` 同步 docs（无需重建容器）。
3. worktree 切回 `codex/translate-2026-race-display-names` 或按用户指示清理 worktree。
4. **遗留事项（均不在本 change，需用户立项）**：
   - 2026 日历系列与历史系列双卡片问题（563 个 2026 系列名仍为原文；系列级中文化随该案）；
   - 1300 系列术语同步；新闻历史文章让赛/译名回填；
   - 未来新增赛事原文回退会重新累积（本批为一次性，无自动通道）；
   - 去让赛遗留：term 5087「广东让赛杯(让赛)」、5570「苏特恩杯（让赛）」保持原值待人工定名。
5. 复审沿留 P3（记录即可）：裸 H 正则人名首字母潜性误放行（本批暴露为零）、
   `APPROVE_DECISIONS` 常量未引用、畸形输入原生异常、OperationLog 幂等无 DB 唯一约束。

## 6. 关键上下文速查

| 项 | 值 |
|---|---|
| worktree | `/Users/mentianlu/Code/umanews/.worktrees/translate-2026-race-names` |
| 功能分支 | `codex/translate-2026-race-display-names`（已推送，`bd03b100`） |
| evidence 分支 | `docs/translate-2026-release-evidence`（本地，未提交内容在工作区） |
| 部署 main | `6167b6c0`（含本 change + P0 discard 分支） |
| 定稿工作簿 SHA | `47ba2e32fb96675ffe77888466dfb93f47c34e2489f5888d32fafe140b1d5d7d` |
| 生产 manifest SHA | `b9f1e8b73e84da9df141a78081a1da2ba29d727539f12ce2fb708a95df4375c8` |
| 备份 SHA | `cdcc751ed852019830721ddea0894afe04c0fcf7f7c5223921ca947c66edd04c` |
| OperationLog batchId | `d2e2b203d9c3e67f683650c397ed6af038c17123d9c54cf71bdb302b784ce673` |
| 测试 | `cd server && /Users/mentianlu/Code/umanews/.venv/bin/python manage.py test stable.test_race_display_name_translation_2026`（61 个） |
| 生产回滚 | `deploy/restore_db.sh backups/db/pre-translate-2026-race-names-20260723_012307.dump`（需另授权） |

- 本会话的 reviewer/实现 subagent 会话（Agent 工具）不可被其他模型恢复；
  如需复审，按 `docs/codex_workflow.md` 记录的原因新建 reviewer 会话并交接本文件。
- 跨会话记忆：`~/.claude/projects/-Users-mentianlu-Code-umanews/memory/`（MEMORY.md 索引）。
- 相关已完成 change：去让赛清理（`docs/changes/remove-handicap-markers-from-race-names/release_report.md`）、
  五区赛事中文名导入（分支 `codex/translate-collected-race-horse-names`，未合 main）。
