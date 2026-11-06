# 0079 → P02 关闭态升级与恢复流程

这是可评审流程，尚非已批准生产发布包。候选镜像、DB 身份、备份 SHA、配置摘要、锁预算的实测值未冻结前禁止执行。门禁仅引用根 [AGENTS.md](../../../AGENTS.md)。

1. 固定 commit 和镜像；实时核生产代码/schema、旧 intent/marker、服务和所有写入入口。单一 coordinator 持有自动释放的 production release lock，记录 owner/thread/operation/SHA/resources/开始及存活。其他生产任务须避开相同资源。
2. 在隔离副本测六步迁移的 SQL、耗时、锁与磁盘增量。默认锁等待上限 5 秒、单语句 120 秒，仅为预设失败预算；超限中止，不自动扩大。按真实数据量确认停写窗口和恢复 RTO/RPO。
3. 先持久化不可变初始 intent（候选/数据库/配置/本次唯一备份目标目录，尚不声称备份完成），再关闭赛事调度及网络入口、P02 write/delivery；停止 Beat 新投递，排空在途写任务并停全部 DB writer（包括 web 管理入口及新闻/术语写入），保留 Redis 消息。确认无残留进程/活跃事务后产生关闭态 handoff；不能仅凭 env=false 判定已停写。
4. 在同一停写切点备份 DB、角色/权限、持久配置、静态/媒体引用和旧镜像身份。私有文件权限、SHA、TOC、完整隔离恢复与 catalog 校验全部通过后才准入 DDL；已知旧恢复约束问题必须在演练中解决，TOC 成功不替代恢复成功。完成后生成不可变 backup receipt，绑定初始 intent SHA、实际备份 SHA 和恢复证明；最终 closed handoff 绑定两份凭据及停写证据。不得回写初始 intent 来补备份 SHA；DDL 入口必须同时核验三者。
5. 单一迁移 owner 在同候选镜像逐步执行精确前向计划，每步原子提交后持久回执。六步顺序固定，不 fake、不跳过、不改 recorder。失败保留 intent/marker 和原备份，服务保持关闭。
6. 检查精确目标 recorder/catalog、collectstatic、四应用有效配置。先用可验证的只读数据库连接启动 web 探针，管理写入口保持不可访问；worker 仅做导入/配置检查，不连接 broker、不消费任何业务队列，Beat保持停止。验证 HTTPS/旧业务读取及队列保留状态；P02 write/delivery 保持关闭。全部检查成功才写 complete 凭据，随后按包内清单恢复正常 web 连接、worker 消费和 Beat；恢复后再验证健康及旧业务，失败保留关闭态/恢复阶段凭据，不把 complete 当作已恢复成功。关闭态恢复旧 writer 与后续激活 P02 是两个明确状态。

## 中断续跑

- intent 未完成、尚无 DDL：验证同一绑定、服务停写及备份，再继续；不能新建发布覆盖原记录。
- 部分迁移完成：核对同一 intent 的 recorder 前缀与 catalog，事务中未提交迁移由 PostgreSQL 回滚；只执行后缀。catalog/recorder 不一致则保持关闭，走受审修复。
- schema 完成但 static/服务未完成：验证目标 catalog 后只继续 static/服务，不重复 DDL。
- 新 writer 曾产生 epoch：保留新 reader 和不可变证据，关闭 write/delivery 并前向修复；不能只换旧镜像而绕过公开读闸。

## 精确恢复

需要旧版本时，先保留失败现场备份；所有写入继续停止。使用 intent 绑定的升级前完整备份恢复到隔离的新数据库，校验0079 recorder/catalog、约束/触发器、关键数量和旧镜像读取，随后按精确发布包切连接并恢复旧配置/镜像。不得对0085执行逆迁移或删除新观测来满足旧唯一约束。切点之后业务写入的丢失范围必须量化；存在新增不可逆影响时遵循根 AGENTS.md。恢复检查失败时维持关闭态，不能猜测成功。


## 独立执行入口实现状态

新增入口为deploy/release_p02.py，参数为--plan（私有plan路径）、--plan-sha256（精确摘要）、--directory（checkout外私有目录）；中断续跑必须附--resume-intent-sha256（原意图摘要）。不使用旧0079执行器放行新迁移，不提供跳过证明参数。plan绑定字段由release_p02_recovery.BINDINGS定义，另包含精确Compose项目、Docker engine、HTTPS origin、操作者/线程/资源域及同候选生产形状演练凭据。

目前未形成生产plan，不能把示例参数或本地合成证据作为发布授权。实现与验证层级见[执行器验证边界](executor-validation.md)。原始材料保留，失败后只停写，不自动逆迁移、回灌或恢复旧镜像；写入已恢复后的灾难恢复仍按本文件既有损失量化流程处理。
