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

固定树回归、独立 review 与交付结果待追加；按根 AGENTS.md 判断交付。
