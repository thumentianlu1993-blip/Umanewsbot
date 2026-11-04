# B106：M03 真实 RED 首两方法源码交接

状态：SOURCE_PREPARED_ONLY。未 collect、未运行 Django/PG/Docker、未分配资源；尚无实际 RED/GREEN 结论。业务模块未改。

起点：ROOT 指定 main `1dd5e0a508957672bcddd1c33e454fbbef1b75c1`，tree `67e755d385725fa7404cba822bf65d74f50403cf`。分支 `codex/b106-article-term-receipt`，worktree `/Users/mentianlu/.codex/worktrees/b106-article-term-receipt/umanews`。应用 create_worktree 因 chat 旧 cwd 无效返回 Not a git repository；使用有效 B 仓库的 git worktree add 建立，原树未切换或修改。

## 继承对象

只原字节继承 B105 `bb252cd4216d07c431188b3e66676bfe98a4c599` 的 design.md、test_cases.md、tasks.md。设计目录 b105-article-term-receipt，三个 SHA256 依次为 `baf9b43ef28cb6664b19982040caf0e535aa521f03f630f1031e200e7b059d97`、`27bc5d3ef29e62c52b45d2fddcc0c37643b1d432d46e324ea413b362a08b2c02`、`7ad86517e9910e0ba6efb18c9804bdbbbf812af995789882cbaaf46687cb7119`。

R 固定对象 `6a769501731ac43d98be2a270286a97464629cea` 已获 APPROVED；report SHA256 `03a23b800466caa9c3566b8c782f0564a99e2cd3fb05df9888da8c2de4f6185c`，receipt SHA256 `5add3e38303c613121c4f417b2eacd1d4b7a19c79d54fd32e59f53f5fceaedf1`。此状态由 ROOT 的交接给定，本卡不重做 review。

## 精确两方法

1. `stable.test_managed_readonly_steps.ManagedReadonlyStepTests.test_article_term_receipt_v2_real_orm_missing_candidate_material`：真实 TermEntry/TermAlias 入库、原 resolver 确认人物进入 accepted，再实际初始化 v2 和 ORM read。完成 step、一次 read、零 model 请求是前置；目标断言为持久化 result 包含 term_snapshot，原 v2 应在此 FAIL。
2. `stable.test_managed_readonly_translation.ManagedReadonlyTranslationEndToEndTests.test_article_term_receipt_v2_resume_uses_frozen_resolution_without_dictionary_select`：真实 admin → due/claim → register → v2 read 提交后 ReadFixtureExit，确认零 model 请求/无 checkpoint；真实更新 TermEntry.target_zh，原消息在全新合法 scope 恢复。实际 provider 的 translate 参数用透明 observer 记录，原 factory/provider/resolver/授权/保存均照常执行。离线 SDK 人物占位符用于通过原质量门禁。实际 Article translated、一次 read/create、原 step 原字节重放是前置；目标为实际 provider resolution 等于 read 前原 resolver 解析，且恢复过程中 TermEntry/TermAlias/ExternalHorseAlias SELECT 为零。

两方法串行，原共享 TransactionTestCase 夹具/固定时钟/闭合 SDK/禁止真实 SDK 构造仍生效。版本不支持、导入/夹具、质量/保存链失败、provider 没有到达皆 ERROR，不计目标 RED。目标 FAIL 必须落在 term_snapshot 缺失或冻结解析/额外词典 SELECT 断言；运行日志打印实际证据。只观察真实解析，不手填 resolution/终态。

本次实际 v2 仅用于证明旧行为缺口；B105 v3 尚未实现。后续 GREEN 卡须明确选择 v3 并继续核验 v1/v2 兼容，不能把此 v2 缺口直接当 v3 验收。40 同 span 双 target、65th append valid 及完整复杂边界保留后续 GREEN，不加入首两方法。

## 原 PG 入口和资源交接

冻结清单在 `/Users/mentianlu/.codex/runtime/b106-m03-real-red-prepare-001/`：receipt.json 绑定 candidate commit/tree、全部六文件 SHA；plan.json 绑定唯一 exact2；resource-request.json 只申请资源；launcher-command.txt 给出原 official_host_bootstrap.py → 原 scripts/run_test_plan.py 的精确参数。新 runtime 的 bootstrap 原字节复制 B098；controls 从固定 main 同一文件清单复制，唯一变动 controls tools/test_impact/rules.json 的 current-main 字节单独记载。未新增 runner/settings/替代框架。

ROOT 在原有独占窗口监督、FD flock、容器 create/start 边界及清理证明中执行 launcher-command.txt；该命令仅为原入口的内层 argv，不得脱离窗口直接运行。原 B098 run_window.py 已执行记录不可重跑；ROOT 如需沿用其模板，只做新 repository/runtime/plan/hash/目标 FAIL 分类绑定。没有重新资格证明 OS 隔离能力。

资源上限继承原窗口：PG16，单容器，network none，readonly rootfs/source/controls，UID10001:10001，cap-drop ALL/no-new-privileges；CPU2/4GiB/256pids/3GiB tmpfs，600秒总窗口、570秒停止测试、30秒清理，最多3 PG clients（本次串行，无新增 worker）。image `sha256:fcf8cdaf63af51b1b8a6e30e3d2fdf871d127c3c1461bfd00c9fc6d610eab905`，endpoint `unix:///Users/mentianlu/.colima/umanews-impact-ci/docker.sock`、context c025-local，仅为继承请求，未查询当前 image/endpoint/容器。ROOT 配置现有受信控制字节并验证，再分配新 owner/operation/SHA/heartbeat，结束须 owned-only 容器/process/FD 释放和重新获取证明。

静态验证只有 AST 两方法唯一存在、旧方法 AST 不变、业务 Git diff 为零、三文档 SHA 原字节一致、git diff --check。实际 RED 由 ROOT 新窗口返回后才可进入实现。
