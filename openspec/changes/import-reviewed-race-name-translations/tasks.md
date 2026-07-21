# 已审核赛事中文名统一导入与生产写入任务

> 映射 `docs/race_name_translation_handoff_20260720.md` 步骤 1–9；权威契约见 design.md 所列文档。

## Phase 0：本地基线（不触生产）

- [x] (operations) 恢复并确认生产只读访问：SSH `printf ready`、`/opt/umanewsbot` HEAD、web 容器 image/started-at、`/healthz/`、容器状态（2026-07-21 通过，HEAD `7ad6ade`）。
- [x] (operations) 核验仓库内两份输入 SHA（日本修订版 `e244a0fb…`、美国 `f2481cde…` 匹配）。
- [x] (operations) 解决 `~/Downloads` 四份输入读取问题：用户同字节复制到 `outputs/translate-race-names-20260719/`，SHA 全部匹配，生成器锁定路径已切换（2026-07-21）。
- [x] (application) 重跑本地基线：Node 16/16、XLSX 布局 2/2、SQLite Django 20+4skip、OpenSpec 30/30。
- [x] (application) 创建本 OpenSpec change 薄层并记录审核链替换决策。

## Phase 1：候选重生成（交接步骤 2–6）

- [x] (operations) 修复生产快照脚本内存问题（第一轮 content 显式释放后再取第二轮；此前 exit 137 OOM fail closed），并重生成新候选 `unified-import-preview-20260720T205650Z`：五输入 SHA、C68 单点变化、snapshot 前后 metadata、双轮快照、`applyReady=true`、`blockerCount=0`、计数（1300/8883/1/2/101）、`eventScope` 1301/8885、Event 96/16446/Target 49052 全部验收通过（2026-07-21）。
- [x] (operations) Excel QA：8 张表齐全、openpyxl 重载、公式错误 0、布局测试 2/2、概览阻断项 0、建议名无让赛残留、京成杯/香港修正/身份修正行抽检通过（2026-07-21）。
- [x] (operations) deterministic bundle：`runtime/artifacts/race-name-translations/20260721/race-name-translation-bundle.tar.gz`，重复打包逐字节一致（archive `3ac595c2…7eb7`，bundle-index `2877af06…d111`）（2026-07-21）。
- [x] (operations) 全量测试：Node 16/16、XLSX 2/2、SQLite 20+4skip、PostgreSQL 16 24/24（31 queries / 2.815s / 92,372,992 bytes）、`openspec validate --all --strict` 31/31、`git diff --check`、bundle 成员/receipt 一致、apply/verifier CLI 到达预期数据库连接边界；临时容器与文件已清理（2026-07-21）。
- [ ] (application) 更新 `docs/current_state.md`、`docs/project_status.md`、交接文档与本 change；运行 review fingerprint。

## Phase 2：复审与授权（交接步骤 7–8）

- [x] (operations) Claude Code 等价复审第一轮：四聚焦门禁直接验证通过；8 项行动 finding 修复并补负向测试；候选重生成 `T220245Z`、QA/bundle/全量测试通过（2026-07-21）。
- [x] (operations) 复审第二轮：聚焦修复 diff 的完整只读复核，结论 APPROVED、actionable finding 清零；顺手修复修订工具自闭合单元格正则一处；审后指纹已冻结（2026-07-21）。
- [ ] (operations) 向用户报告新候选目录、全部 SHA、目标计数与复审结论，取得用户对该精确版本的明确发布授权（“发布吧”/“上线”）；此前任何授权不替代本门禁。

## Phase 3：发布（交接步骤 9）

- [ ] (operations) staging transition，创建不可变提交，从该提交导出 bundle 并核对 archive SHA/receipt。
- [ ] (operations) 按 rollout 固定脚本创建 current custom-format 备份：`.incomplete` 原子改名、权限 0600、大小、SHA-256、PostgreSQL 16 版本、`pg_restore -l`。
- [ ] (operations) 宿主与容器复算 bundle index；verify-only 必须仍为 `apply_ready=true`；commit 前再次复算；单事务 `--commit` apply。
- [ ] (operations) 独立 verifier、OperationLog 精确批次与八项 SHA 绑定、让赛零残留、计数复核、`/healthz/` 与页面抽检。
- [ ] (operations) 清理服务器/容器临时文件；仅按 evidence-only allowlist 回写文档，经 review 后提交推送；不部署或重启服务。
