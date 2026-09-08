# 0078 发布时保留生产开关

2026-09-08 发布前只读核验发现：PR #181 已合并为 `51c0cf2377a00002c87011aad17c4d65a90b9fe7`，但尚未部署。生产应用为 `ca6e9d06`，数据库完整 0078、迁移计划为空，十项 RACE_DATA_SYNC 开关为 true。原实现从要求全部关闭的 admission 容器推导常驻服务恢复值，无法表达当前生产配置。

## 修正范围

- 保留 `collect_writer_activity` 的全关闭及在途任务为零检查。
- 仅在新 0078 的临时检查和 release-task 容器中通过 `compose run -e` 关闭十四项 writer 开关，覆盖完整 verify/ensure/migrate/static/complete 链。
- 从实际 Compose 配置冻结常驻服务原开关，首次停服前与原运行容器逐项一致，再写入原有 manifest。宿主环境与 `.env` 不为临时容器改写。
- 续跑始终复用原 manifest；恢复前、逐个启动后仍检查实际容器镜像与原开关。保留 Compose 覆盖值、project、镜像、备份、数据库和文件身份的漂移拒绝。
- 不增加 migration、业务功能、通用配置框架或普通代码 rollback；旧固定 control-image 路径保持原约束。

## 验证与交付

先补原十项 true 配置下的失败测试，再验证正常发布、中断续跑、控制容器全关闭、常驻容器原值恢复以及开关漂移拒绝。独立测试 agent 仅负责测试文件，生产代码与发布由主 agent 负责；独立代码 review 继续使用只读原生 reviewer。

本补丁通过验证和 review 后重新绑定 PR、commit、镜像与发布包。生产操作继续遵守根 `AGENTS.md`。当前只有只读核验，没有清理遗留锁、备份、停服、构建生产镜像、迁移或业务数据写入。

线上已有发布锁的 PID 2632893 不存在，锁始于 2026-09-06T15:42:38Z；本次未修改它，实际进入发布窗口前须重新核对存活、runner 与容器状态。当前应用使用 `/opt/umanews-release-95fc8726-PR177-20260906T1400Z/umanewsbot`；原 `/opt/umanewsbot` 有历史改动，不得覆盖。使用新独立发布目录并保留实际持久化挂载和现有开关。
