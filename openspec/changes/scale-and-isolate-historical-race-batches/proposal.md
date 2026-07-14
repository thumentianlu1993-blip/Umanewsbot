## Why

2016-2025 年代带前五个标准批次已经稳定导入 1291 场，但旧的“单地区最多 50 场 + 临时 `docker run --rm` + 人工协调 web/worker/beat”方式会让 1998 年以来 29626 个待处理目标需要过多批次，并使长时间抓取容易受普通部署、Codex 会话和新闻生产窗口影响。batch006 前需要同时提高吞吐量并把历史批次运行隔离成可恢复、可审计且不会重建生产基础设施的独立执行面。

## What Changes

- batch005 保留原有每地区最多 50 场口径；batch006 及后续标准批次将单地区上限提高到 250 场，并让选择器、地区进度门禁、artifact 摘要、测试和运维文档使用同一口径。
- 新增独立 historical batch runner 容器，以固定已验收镜像 revision、显式 runtime artifact 挂载和资源限制运行长周期批次，不加入 Celery Beat，也不由普通 web/worker/beat 部署管理。
- 新增数据库级与应用级互斥锁、心跳、checkpoint、失联租约和恢复流程，保证同一时刻只有一个可写历史运行，并能在容器或会话中断后从已验证阶段继续。
- 将抓取阶段限定为 `network=true / write=false`，将落库阶段限定为 `network=false / write=true`；runner 不允许同时获得网络和写入权限。
- 普通部署必须忽略 runner、DB、Redis 和共享网络；数据库迁移前必须先安全暂停 runner，并验证不存在可写阶段或未完成事务。
- 保持正式总账、待审 gap、来源证据、备份、dry-run、哈希、人工批准和公开开关的既有门禁；零星赛事歧义继续累计到最终统一审核，不阻断无关目标。

## Capabilities

### New Capabilities

- `historical-batch-runner`: 规定独立历史批次容器的生命周期、固定镜像、互斥锁、心跳与恢复、权限分阶段、资源限制、部署隔离和迁移安全暂停。

### Modified Capabilities

- `race-event-data-crawl-orchestration`: 将 batch006 起的标准批次单地区上限改为 250，并要求选择、进度护栏、artifact 和执行命令按新口径一致工作。

## Impact

- Django：历史批次运行/锁/心跳/checkpoint 模型、迁移、管理命令和服务层。
- 批次编排：`build_historical_race_band_batch`、进度护栏、选择快照、manifest/summary 和历史专项测试。
- 运行环境：新增独立 runner 的启动/暂停/恢复脚本或专用 Compose profile/config，但普通生产部署脚本不得处理 runner、DB、Redis 或共享网络。
- 运维：新增 runner 启停、迁移前暂停、故障接管、备份、日志、健康与资源验收步骤；生产历史公开、常驻网络和常驻写入开关继续关闭。
