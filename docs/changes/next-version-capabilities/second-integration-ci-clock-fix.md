# 第二批 CI 的首页测试时钟修复

2026-10-04，Asia/Shanghai。正常 PR236 CI run `37135439940`、attempt 1 在固定 head `bdfb5c9c2c1595982da818a49cfd5549fe581f05`、merge `9237ef85a4a93e8aa36458296b48538d88e5805d`、tree `e9465a01d65b89498f959db94bbcfa44d7391cf7` 执行 full 6378 项、46 批，记录 1 failure、0 error、10 个 skip，所有 native batch lifecycle complete。失败证据保留，不标记正式交付通过。

唯一失败为 `stable.test_realtime_race_results.RaceResultRevisionApplyTests.test_homepage_today_race_winner_prefers_reported_position`，batch-032 中首页条目数 `0 != 1`。原测试用例将赛事置于固定 2026-07-20，并只 mock `timezone.localdate()`；已审 U02 首页从 `timezone.now()` 推导北京日期，旧 mock 不再固定受测时钟，赛事因此落在当前七天窗口外。这是测试时间控制问题，不能将其称为新增业务功能的 RED。

最小修复仅将该用例的 mock 改为 `timezone.now() = self.NOW`。赛事/赛果数据、公开条件、fallback 断言、条目数量和 `Reported Winner` 断言全部保留；业务实现、其他测试及控制映射未改。

修复前在隔离 Python3.12.13 / Django5.2.1 / SQLite memory 环境复现同一 `0 != 1`，精确 1 项、退出 1。修复后同一方法通过、退出 0；测试方法耗时 0.020 秒，含数据库准备/销毁的完整进程 7.379 秒。执行前清空继承环境、禁用 dotenv，所有 socket connect/create_connection 均阻断；没有真实数据库、Redis、网络或 Docker 操作。原有赢家断言仍可捕获把 reported 顺位改回 legacy 顺位的错误。

私有证据位于 `/Users/mentianlu/.codex/runtime/pr236-homepage-clock-fix/`：`before.log` SHA256 `1fb522379db134d8dec532eb5cfb4600987dec883219f635ee5c306e56a764e1`，`after.log` SHA256 `cd49789f858f8a68ced79796d5b246e04ba3d1764248529a1ee65ada7c847d25`。原 CI 工件在 `/Users/mentianlu/.codex/runtime/second-integration-evidence/ci-37135439940-attempt1/`，plan digest `378174315d72b09db42b24b7db6afa6e3a43dbceaba014f4714818fd04cabc70`。

该单项本地补验不是新候选 Linux/PG 全量证据。固定提交交原 R 只读复审后，再推送同一 PR 触发正常组合 CI；不对旧受测树盲重跑，不借旧绿项拼接新版本全通过。合并与生产发布继续按根 AGENTS.md。
