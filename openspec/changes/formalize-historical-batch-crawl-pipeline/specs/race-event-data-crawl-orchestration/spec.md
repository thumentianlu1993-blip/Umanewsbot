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

### Requirement: 年度赛历缓存与解析必须分 stage 冻结
生产年度赛历 MUST 先用受控请求 artifact 完成 runner `crawl` phase 的 network=true/write=false cache stage，再将已完成 cache manifest、ledger 和文件作为不可变输入生成 runner `verify` phase 的 network=false/write=false parse stage。正式 plan 不得引用尚未生成的前序输出或在解析 step 临时访问网络。

#### Scenario: cache stage 完成后生成 parse plan
- **WHEN** cache runner 已完成且 artifact 文件身份与账本一致
- **THEN** plan builder 复制并绑定这些输入，为解析 shard 生成固定 tool SHA 与地区/年份 scope 的 plan

#### Scenario: 解析 plan 尝试联网或消费活动 cache 目录
- **WHEN** parse stage 声明 network=true，或输入 cache 尚在运行/未形成完成 checkpoint
- **THEN** plan 生成或生产门禁拒绝启动

#### Scenario: verify descriptor 携带 crawl 资源预算
- **WHEN** 离线解析 descriptor 声明 `resource_limits` 或 shard 非零 request budget
- **THEN** builder 拒绝生成 plan，不能借 verify phase 获得新的网络请求额度

### Requirement: runner checkpoint 必须区分输出文件与输出目录
正式 plan MUST 把目录型输出声明为 `output_directories`。runner MUST 在 step 成功后递归绑定目录内全部普通文件的相对路径、size 和 SHA，并在恢复时复核；目录不得包含 symlink、特殊文件或未记录成员。

#### Scenario: 原子目录输出完成
- **WHEN** parser 成功发布非空 output directory
- **THEN** runner 将目录及确定排序的全部成员身份写入 checkpoint，并可在同一身份下恢复跳过已完成 step

#### Scenario: 完成后目录成员漂移
- **WHEN** checkpoint 后目录新增、删除、替换文件或出现 symlink
- **THEN** resume 视为 checkpoint 不一致并 blocked，不把漂移目录当作已完成输出

#### Scenario: 跨 step 输出路径重叠
- **WHEN** 任意两个 step 声明相同输出，或一个 step 的输出目录包含另一个 step 的输出文件/目录
- **THEN** plan 在创建 run 前拒绝，避免后续 step 改写已经 checkpoint 的输出

#### Scenario: 普通输出文件被同内容 symlink 替换
- **WHEN** step 完成后普通文件输出被替换为指向同内容文件的 symlink
- **THEN** resume 拒绝 checkpoint，不能仅凭 size/SHA 把 symlink 当作原普通文件
