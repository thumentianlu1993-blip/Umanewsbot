# C025 PostgreSQL 线程连接清理回归

已有范围：定位PR238两失败分片031/032，只修测试线程自身连接生命周期，不改生产逻辑或共享runner。

| 用例 | 实际目标 / mutation | 证据安排 |
| --- | --- | --- |
| RED1 | 2026身份review双apply测试，两线程实际PG backend PID在join后必须消失；捕获finally只调用close_old_connections保留健康连接 | 原业务断言保留，新增server pg_stat_activity有界关闭断言；固定RED提交运行 |
| RED2 | repeatable-read导出线程在完成后关闭其自身PG会话，原快照一致性断言保留 | 同上，thread PID绑定，不按全DB杀会话 |
| RED3 | horse staging两并发线程完成后关闭其backend，原one applied/one replay断言保留 | 同上，成功/重放分支都覆盖 |
| GREEN | finally在工作线程调用connections.close_all，所有原断言及新增关闭断言通过，Django DROP test DB成功 | 同一PG16隔离image与标准runner，最小三方法 |
| 相关回归 | 原失败031/032完整188/184方法不缩分母，无新skip，全批teardown成功 | 仅必要两失败分片顺序执行，正式full仍由ROOT安排 |

PID在工作线程实际获取；parent只查询这些PID，2秒有界轮询避免正常断开异步竞态。关闭证据是pg_stat_activity无相应会话，不是线程已join或事务成功。失败输出保留准确PID、数据库与state。不得keepdb、skip、强杀PG会话或放宽runner。

标准已有isolated PG16/nonroot/network-none/read-only、2CPU/4GiB/256pids、单容器；本地diagnostic plan绑定固定Git/tree/image，不冒充GitHub formal证据。父线程DB仍用于业务断言与关闭观测；只关闭thread-local connections，不影响其他线程/合法DB测试。

真实RED必须新关闭断言实际失败，fixture/setup错误不算RED。异常退出也走finally；2026并发apply原有一个成功一个受控失败，连接规则两者都适用。不涉及模型/迁移、来源权限或生产数据；原始CI与新RED/GREEN均保留。
