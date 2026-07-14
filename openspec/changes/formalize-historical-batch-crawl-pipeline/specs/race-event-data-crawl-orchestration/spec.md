## ADDED Requirements

### Requirement: 生产 historical crawl plan 必须由受控生成器创建
生产 historical runner 的正式 crawl plan MUST 由受版本控制的生成器根据 approved selection、typed recipe 和 stage descriptor 创建，并通过现有 runner plan validator。artifact 自带代码、未跟踪脚本、任意 argv 或无法证明实际工具输入完整 scope 的人工 JSON 不得启动正式 crawl。

#### Scenario: 受控 plan 启动 crawl
- **WHEN** plan generator 输出已绑定固定镜像、不可变工具 SHA、请求预算和完整 shard scope 的 plan
- **THEN** historical runner 可按既有双锁、心跳、checkpoint 和网络权限执行该 plan，且每个 shard 使用独立 artifact 根和聚合请求账本

#### Scenario: 计划引用 tmp 脚本或 artifact 工具根
- **WHEN** stage step 引用 `tmp/`、artifact 内脚本或不在显式白名单的 Python tool
- **THEN** generator 或 runner 在创建业务运行前拒绝该 plan

### Requirement: 暂停恢复保持分片输出和请求账本身份
正式 shard 在暂停、失败或恢复时 MUST 继续绑定原 plan、selection scope、请求账本和 source-cache manifest。已完成 target 不得因会话、部署或重启而重复抓取。

#### Scenario: shard 在 step 边界暂停后恢复
- **WHEN** 操作者请求暂停且当前 step 完成 checkpoint，随后以同一 image、plan 和 owner 恢复
- **THEN** runner 跳过已完成 step，继续未完成输出，并保持原请求账本与 cache identity

#### Scenario: 恢复前资源 artifact 漂移
- **WHEN** 请求账本、source-cache manifest 或已完成输出在暂停期间被删除、缩小或改写
- **THEN** runner 转为 blocked，禁止创建新 run 绕过已消费预算
