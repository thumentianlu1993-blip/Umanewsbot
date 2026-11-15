# 验证记录

2026-11-15，原分支起点 633f80ce，已整合最新主线 67a97939（PR #320）。只修改公开时间 SQL，本轮没有生产动作。

## 最小 RED / GREEN

无网络、非 root Linux/amd64 容器，PostgreSQL 16、Django 5.2.1，合成数据、本地 loopback 数据库。镜像 `umanews-impact-base:verified`；正式交付由固定 Git 树运行器记录完整 image ID。

- RED：`stable.test_race_public_time.PublicTimeQueryPerformanceTests.test_timezone_directory_evaluated_once`，exit 1，15 个目录 Function Scan，预期 1。
- 第一轮 GREEN 揭示 EXPLAIN 前缀必须在 WITH 外层，已定点修正。
- 同例及完整 `stable.test_race_public_time`：10 项通过（0.823 秒，不含数据库迁移）。投影/过滤/嵌套/union 的目录 Function Scan 均为 1、Actual Loops 为 1。
- 覆盖旧 SQL 全列对照、DST/跨年/冲突/date-only、count/exists/aggregate、分页、相关子查询、重复编译/编译异常恢复、业务更新立即可见。未声称全站或线上提速。

开发测试最初遇到 Docker 可写层空间不足；改用现有隔离测试惯例的 tmpfs 临时数据库，不删除他人镜像、不扩容。其后测试入口的合成数据库用户名校验错误已纠正。这两次环境失败不计为 RED。

## 选测与审核

公开时间文件在旧规则中被保守归类为高风险；本次采用精确绑定全部路径/字节与基线的单次范围清单，覆盖其首页、日历、分页、时间、公开可见性消费者，另跑映射工具自身回归与核心检查。不修改全局高风险规则，不改变 Django backend 或全站编译器。

固定候选 `278dc38b832898878f2775cb95b3383d1a606436`（tree `822cfd8bd941282c02f2734648a678555c4c95db`）在无网络 Linux 容器执行370项：Django 284项、Python/SQLite/工具链86项，3批，全部通过、零跳过。`verify_test_plan.py` 汇总 passed。镜像完整ID为 `sha256:ab8494e6202dced04a6c2b5b885b3d1f2d9c80776ec8ae8d97f3552aae6b3ecc`。正式运行器第一次遇到 macOS 默认临时目录不能被 Docker 挂载，改用任务专属 TMPDIR 后通过，未更改执行器或测试隔离规则。

独立只读 `codex review --base 67a9793997d1d57944842d22053d89b3c5a73d96` 未发现 actionable finding。reviewer另行验证 SQLite 执行及五类 PostgreSQL 编译形状、参数与上下文清理；实际 PostgreSQL执行证据来自上述370项，reviewer未重复运行它们。

审查前后完整内容manifest与scope一致，内容SHA为 `ca1c35179abb3da6f34dbfb374a6bcabaf7ce2b1be931d5834f089bd9d7d05b6`；完整fingerprint仅因本线程push建立了upstream/ahead-behind元数据而不同，工作树、commit、diff与文件内容均未变。

Draft PR [#321](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/321) 已创建。370项证据绑定上述候选；后续仅更新交付说明和对应字节绑定清单，不重复本地业务测试，最终远端CI以PR当前head结果为准。第一轮远端执行因本次文档收尾主动取消，最终push后重新运行当前head的范围检查。合并与生产发布尚未执行，按根 AGENTS.md 交付。
