# QQ下线精确发布包（待G2）

本包只进入准备阶段，未执行生产。授权边界引用根[AGENTS.md](../../../AGENTS.md)。

- 固定候选：`680639625dee9d6ab70ae31f7e095cd5f0c85155`，生产ad50abdb的QQ窄回移包。
- manifest：[release-manifest.json](release-manifest.json)，SHA256 `a38b36aa2c5c1d6cdef1ce02eafb5078c224e28dbe606984b50e1fefc3419e8e`。
- 主线PR包含并发修复与资料；合并该PR不等于部署整个main。生产只构建上述候选，记录实际镜像ID和标签核对后再切换。
- 迁移：无新增迁移，维持stable.0079；继续使用受保护0079同schema发布流程，不绕过历史保护标记。
- 配置：QQ_CHANNEL_ENABLED、QQ_PUSH_ENABLED、MULTIREGION_PRODUCTION_WINDOWS_QQ_ENABLED全部false；其他flag保持原值。
- 服务：web、worker、beat、race_sync_v2_worker按既有受保护顺序排空/重建；Nginx按原流程恢复。DB/Redis不重建。独立OneBot `9f77b49ec509a223cf30a9360350dfc6b358a193126afb1ba278b61f2cc2c98c` 取消自动重启并停止，不删除容器和挂载。
- 数据：不批量删除/清队列；旧消息自然消费时将符合条件的非sent投递标为skipped/qq_channel_disabled，保留sent、消息回执、历史请求/响应载荷。先私有保存相关投递状态快照。

## 预检、备份与切换

1. 核对manifest、候选源码、当前应用镜像、四应用、DB身份/schema、配置摘要与OneBot身份；任何漂移先重新绑定，不默认授权。单一release coordinator遵守现有生产release lock；发现P04/其他任务持锁不抢占、不代释放。本包没有向其他会话发送消息的动作。
2. 连续三次有界采样（间隔20秒），1分钟负载不超过2核、可用内存至少2GiB、SwapFree至少1GiB，磁盘空间足够备份和镜像。条件不满足不启动重型备份/构建、不停止服务。构建和备份继续受限时及资源观察约束，失败仅停止本包。
3. 私有保存现有.env、Compose配置、旧应用镜像身份/保留tag、OneBot inspect/挂载/重启策略、相关投递记录；凭据不入库或输出。用固定候选和复制后的运行配置显式设置三false。受保护`deploy/deploy_0079.sh`负责候选构建、自己的新备份/摘要/TOC、schema与在途状态检查、停止Beat、排空worker、关闭态发布与同intent恢复，禁止跳过preflight。
4. 新备份TOC通过不等于完整恢复通过。生产历史唯一索引异常及P02完整恢复缺口仍存在；本包无schema/历史批修，不以数据库整体恢复作为常规回退手段。若受保护发布步骤拒绝或备份预算失败，保持未切换状态，不能改hash/阈值放行。
5. 候选四应用启动后逐一确认版本和三false、旧QQ任务仍注册；验证网页/后台与Beat无QQ周期。若需要读取Beat持久schedule，待Beat停止后保存副本，只在副本或受保护检验中检查，不在线改共享shelve或删除全部定时任务。
6. 固定OneBot身份、无共享挂载使用者再次核实后，在现有生产release lock保护的独立短操作中执行：按完整容器ID将restart设为no，再正常stop；验证Stopped和restart=no。保留全部挂载与日志。若锁被其他任务持有则等待，不能无锁操作。

## 验收与异常恢复

通过只读任务日志/数据库计数/队列注册信息，观察至少10分钟：旧QQ任务可被消费为停用，但无新派生QQ重试、OneBot探测及新增sent事实。不要通过实际发送消息测试下线。保留停用前的sent分母与已有在途未知状态，无法归因时不宣称零发送已证实。UI无发送/重跑入口，公开网页、后台、新闻发布和非QQ通知的只读状态正常；比较DB/worker CPU与负载，不把QQ下线等同赛事术语查询已优化。

异常沿原固定intent、镜像与false配置执行`deploy/deploy_0079.sh resume`或前向修复。普通旧代码回滚仍被既有策略禁止；不自动恢复OneBot、QQ开关或重新投递历史消息。服务不能恢复时按受保护流程保持失败状态并报告，不用删除恢复标记/迁移记录强行启动。未来重新启用QQ不在本包范围内。

## 证据及剩余条件

私有目录`/Users/mentianlu/.codex/runtime/qq-retirement-20261103/`保存生产身份、配置摘要、RED/GREEN、固定源PG收据与原reviewer复审。发布方案审核及主线PR检查收口后才能提交G2选择；当前不得称生产已下线。
