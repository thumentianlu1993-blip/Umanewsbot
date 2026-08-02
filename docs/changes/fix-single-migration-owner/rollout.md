# 单一迁移执行者修复发布与回滚

## 1. 发布边界

本 change 本身不包含 Django migration，但会改变未来 migration 的执行入口。发布属于高风险
运维变更，必须单独授权。实现、commit/push/PR、合并、生产备份、部署和生产 migration 是不同
门禁。

发布窗口不得与以下动作并发：

- 新闻正文/历史赛事批量数据库写入；
- lifecycle、race-live、result-review 启用或 enforce；
- Celery 调度修改；
- 服务重建或其他部署；
- 新来源联网 proof 或 record/apply；
- 数据库维护或恢复。

## 2. 分阶段发布

### 2.1 本地 dry-run

1. 冻结 review fingerprint。
2. fake harness 运行标准/lowcost deploy 与 rollback，不接触 Docker/数据库。
3. 在隔离 Compose 启动临时 DB/Redis。
4. 验证正常 release、migration no-op 重放、失败注入和锁竞争。
5. 确认 web 日志不执行 migration。

### 2.2 生产只读预检

重新读取当前运行态，不使用历史文档代替证据：

- 生产 HEAD、image ID/revision、Git dirty 状态；
- Compose 版本和 wrapper 选择；
- web/db/redis health；
- migration plan 和 `showmigrations`；
- PostgreSQL 活动事务、DDL lock、空闲事务；
- 普通与 race-live Celery active/reserved/scheduled/queues；
- historical runner、新闻正文批次、赛事导入和 one-off；
- lifecycle、race-live、result-review 及网络开关；
- 磁盘、static volume、备份目录；
- 内外 healthz。

任一未解释异常即停止。

### 2.3 备份与冻结

1. 记录旧 HEAD、旧 `umanewsbot:prod` image ID、OCI revision。
2. 给旧镜像创建不可变 rollback tag，并记录这是 pre-contract bridge 的唯一允许目标。
3. 创建数据库逻辑备份。
4. 校验备份非空、SHA-256、`pg_restore -l` 可读。
5. 保存脱敏 `.env` 配置键集合/安全开关值，不输出值。
6. 确认没有另一个 deployment lock。

### 2.4 功能关闭状态部署

1. 所有业务开关保持当前关闭/既有值，不顺带启用任何功能。
2. 执行标准或 lowcost 的唯一正确入口，本次生产以实际 Compose 拓扑为准。
3. 观察日志阶段：
   - lock acquired；
   - preflight passed；
   - Celery drained；
   - race_live_worker 原始运行态已冻结并按需停止；
   - old web stopped；
   - release one-shot started/completed；
   - web healthy；
   - downstream services started；
   - race_live_worker 仅按原始 running 状态恢复；
   - lock released。
4. 确认 migration 输出只来自 one-shot container，web 主日志没有迁移执行。

### 2.5 发布后验收

- web/db/redis healthy，worker/beat/race_live_worker 状态符合部署前预期；
- web/worker/beat image ID 和 revision 一致；
- Django check、migration plan、`showmigrations` 正常；
- Celery ping，active/reserved 和 queue 无异常；
- 内部/正式域名 healthz、首页、赛事日历和一个赛事详情返回正常；
- 近 15 分钟无 `DuplicateTable`、migration error、Traceback、502 残留；
- lifecycle、race-live、result-review、网络/写入开关未被改变；
- 未产生赛事、新闻或 QQ 业务写入。

观察至少一个自然 Celery 周期，确认没有因为停启次序造成重复任务或重复 QQ。

## 3. 失败恢复

### 3.1 migration 尚未开始

保持旧服务或恢复先前停止的 beat/worker/race_live_worker。修复 preflight/build/drain 问题后
重新申请窗口。

### 3.2 migration/collectstatic 失败

- 不启动 web/worker/beat/race_live_worker；
- 保存 one-shot 日志、migration plan、DB lock/transaction 快照；
- 判断是否有部分 migration 已提交；
- 不盲目重跑，不自动恢复备份；
- 由 reviewer/用户选择修复后重跑或恢复备份。

### 3.3 web 未健康

若回退目标含 `release_contract_v1` 且 schema 兼容，使用通用 rollback。若回退目标是本 change
发布前的 pre-contract image：

1. 保持新控制面 checkout，不运行通用 rollback；
2. 使用受审的 `rollback_pre_single_owner.sh` 和冻结旧 image；
3. 不运行新 one-shot，也不执行旧脚本的显式 migrate；
4. 启动一个旧 web 并等 healthy；
5. 再启动 worker/beat/nginx，race-live 仅按原始状态恢复。

若不兼容，必须恢复匹配备份或执行已审核的反向 migration。不能只 checkout 旧代码。

### 3.4 遗留部署锁

只读核对：

- lock 中 PID/action/start time；
- 主机对应进程；
- Compose one-shot 容器；
- Git/build/deploy 进程；
- DB migration/DDL 活动。

全部确认不存在后才允许人工删除锁目录。删除本身属于生产状态变更，需要当前窗口授权和记录。

## 4. 回滚验收

- 精确旧 image/revision 已恢复；
- DB schema 与旧代码兼容或备份已校验恢复；
- post-contract 回滚的 release owner 仍只有共享 one-shot；pre-contract bridge 只有旧 web owner；
- web healthy 后才启动 worker/beat/nginx/race-live；
- Django check、migration 状态、Celery、healthz 和日志通过；
- 所有业务开关回到部署前值；
- race_live_worker 未被部署或回滚意外启用；
- deployment lock 正常释放；
- 记录是否恢复数据库、恢复点、备份 SHA 和数据影响。

## 5. 后续解锁

该修复成功发布并观察通过后，只解除“部署入口存在双 migration owner”这一基础设施 blocker。
它不自动授权：

- lifecycle shadow/enforce；
- B0.1 多日来源观察；
- 赛果 apply；
- 网络请求；
- 新闻门禁变更。

后续项目必须从最新 production HEAD/运行态重新预检并取得各自授权。
