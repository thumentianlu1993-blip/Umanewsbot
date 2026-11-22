# 英国大收据读取内存修复（2026-11-22）

用户已选择同时修复英国OOM，再发布包含美国修复的完整候选。此前PR #329合并和两场名称写入的事实见
[交付记录](../race-monitor-gaps-20261122/release_evidence.md)。本轮复用本会话worktree，不接管其他会话。

## 根因与边界

生产英国目录收据约30MB。旧实现把整份OperationLog.detail带入worker，并在逐目标循环中反复json.loads。
合成30MB收据的同例RED测得Python新增峰值90,377,022字节，超过16MiB预算；生产此前384MiB worker
被OOM杀死并已回滚。修复仅改变既有收据的读取方式，不提高worker限额，不扩大来源、公开范围或付费额度。

PostgreSQL 16以json文本表示验证并提取本次日期/赛场目标所需的event_ids、report.events、
after.RaceEvent、after.HistoricalRaceEventTarget。仅返回目标ID片段；完整收据不进入Python。
数据库查询使用参数绑定和固定路径，保留重复行以继续拒绝歧义。每份有效且未撤销的唯一收据在一次调用内
仅查询一次，不跨调用缓存；旧有事件/目标身份、审核目录、名称、日期、赛场、冲突、人工锁和开关校验保留。

原件上限40MiB、客户端投影上限256KiB；超限、损坏JSON、缺少必需数组或错误行、重复收据/匹配行均拒绝身份。
使用json而非整文档jsonb对象树；顶层和after成员各展开一次，避免反复复制整份收据。SQLite开发环境使用最多256KiB的前缀读取，拒绝大收据；生产大收据路径只在PostgreSQL运行。没有迁移、依赖、配置或功能开关变更。

## 验证

- (integration) 大收据先取得真实RED，再验证数据库过滤后的Python峰值低于16MiB。
- (integration) 合成收据一半在无关before、一半在实际扫描的after赛事数组；测试不读取生产数据或访问第三方。
- (integration) PostgreSQL与应用使用各自的无网络容器，仅共享专用Unix socket；应用384MiB、无swap。
  21项身份回归通过，合成30MB样本Python峰值约109KB。此前合并容器384MiB试验在建数阶段OOM，
  不作为函数执行失败或通过证据；最终固定树CI与完整交付证据另行绑定候选。
- (integration) 覆盖损坏/空JSON、重复收据、重复赛事/目标行、丢失成员资格、字符串ID、错误数组形状、
  投影/原件超限、撤销即时生效、同收据多目标单次读取和强身份歧义。
- (integration) 独立review发现SQLite兼容性问题，已补有界前缀路径，并将大收据专属测试限定PostgreSQL；同review上下文发现的非规范数字ID隐藏重复行、SQLite NUL截断两项问题均新增真实RED并修复：拒绝整组非规范ID，并比较BLOB原件字节数与前缀字节数。最终SQL探针约0.284秒、数据库单进程采样峰值306.3MiB、应用cgroup峰值139MiB；生产当时MemAvailable约4.1GiB。中间SQL实现数据库峰值约564MiB，已由单次展开降低，不作为最终性能证据。
- (operations) 发布前在隔离候选一次性容器内只读核验真实收据片段，不做真实网络回放。

## 完整发布范围

包含已合并PR #329的美国修复、原PR #328英国冷启动及本轮OOM修复；最终PR、head、树、镜像及CI收据
固定在交付包。沿用此前六应用发布范围：web、worker、beat、race_realtime_worker、race_control_worker、
race_sync_v2_worker。无迁移、配置/开关变化、名称重复写入或批量历史数据修复；只观察既有自然调度。
保留完整Compose覆盖链、当前生产镜像和schema恢复面。原监测不停止、不重启、不改写游标/证据。

验收区分容器健康与业务：英国原缺口的身份准入、实际赛果、confirmed、公开记录及OOM/队列；美国三场
须由真实上架赛果验证，目录未上架仍应保留准确原因；Colonial Cup临时overnight不冒充正式名单。
爱尔兰缺少受审来源路由的边界保持。五场补时与两场已写中文名保持。

回滚仅恢复发布前冻结镜像和完整Compose链，保留本轮自然产生的数据与已写名称；不恢复整库、不回退补时。
故障时按根AGENTS.md及精确发布控制器执行，避免重发造成OOM的任务。
