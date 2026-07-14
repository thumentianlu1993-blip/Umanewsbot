## Why

batch005 虽已完整导入五地区 250 场，但日期证据合并、详情候选合并、详情来源绑定和阶段验收仍依赖写死批次路径及 target ID 的 `tmp/` 脚本。batch006 扩大到 1061 场并由独立 runner 长时间执行后，继续复用这些脚本会使计划无法绑定 approved selection、无法可靠分片恢复，也可能诱使操作者绕过镜像工具白名单。

## What Changes

- 新增受版本控制的历史批次 artifact 编排工具：以 approved selection、重复输入的地区证据碎片和 source-cache manifest 为输入，生成完整、确定、可审计的日期候选、详情候选和阶段摘要。
- 新增 batch shard/runner plan 生成与校验能力：每个 shard 使用受支持工具的 typed recipe，显式绑定目标 ID、selection/approval/manifest SHA、固定 image revision、工具 SHA、实际输入目标集合、输入输出及不超过 250 次的请求预算；所有 shard 合计必须不重不漏覆盖批准范围。
- 将 batch005 临时脚本中的通用校验提炼为正式实现，包括稳定身份唯一性、地区/年份分母、来源优先级冲突、距离单位、跨年届次、完整 runners/results、详情来源写后重打包和逐 target 阶段验收。
- 支持稀疏人工证据覆盖，但覆盖必须使用结构化文件、绑定旧值/新值/来源 URL/理由和 SHA；不得在代码中写死 target ID，也不得静默覆盖冲突。
- 将新工具加入 historical runner 显式白名单，保持 crawl、apply、verify 三阶段网络/写入权限隔离；生产公开及常驻历史网络/写入开关继续关闭。
- batch006 先以已批准的 1061 场作为验收批次，完成后同一工具用于后续 1998-2026 标准批次。

## Capabilities

### New Capabilities
- `historical-race-batch-artifact-pipeline`: 定义 approved selection 到分片 crawl、日期/来源 artifact、详情候选、阶段验收及可恢复 runner plan 的完整契约。

### Modified Capabilities
- `race-event-data-crawl-orchestration`: historical runner 的正式 crawl plan 必须由受控生成器绑定批准目标、请求预算与镜像工具身份，不再接受人工拼接的批次计划作为生产入口。

## Impact

- 主要影响 `runtime/tools/`、historical runner 计划校验/白名单、相关 Django 管理命令与 `server/stable` 测试。
- 不新增模型或迁移，不改变公开页面、新闻链路、Celery 队列和常驻生产开关。
- 运维文档将新增 batch006 分片、暂停/恢复、artifact 审批、备份、apply 和逐场验收步骤；旧 `tmp/` 脚本保留为历史证据但禁止用于新批次。
