# 固定候选验证

- 候选提交：`ec461daad2001806b1cd00e548243ff3a76d3343`；基线 `070eaedac1c7b81104a1431b28316ed77fa69f6d`。
- 镜像：`sha256:5b39cd82079443ababcefb076f1fbe5faddf7f4e2fc0f9f7ab45fa4b65ba308d`；标签 revision 与候选一致。
- 恢复 manifest：`f45f8043ffd3820305813d96aaeaae57d8aa5ce40c304eb04e06d59e7f1bd94a`，七场 52 行；本地原始证据重新解析和 production read-only dry-run 均通过。

## 回归与独立复审

本地隔离 PostgreSQL：85 项受影响回归通过，含真实并发 census 和 SMTP lease；18 项 0079 合同通过。完整业务回归扩展中两项旧 repair 失败已在未修改 070eaeda 隔离代码重现，细节见 test_cases.md。

独立只读 reviewer 保持原上下文 `01a0f924-8cc7-7473-8c44-89ae9846cf18`，两轮共 5 项发现均补 RED 后修复。最终在固定候选返回“通过，无剩余 actionable findings”，独立内存验证 31 项通过、2 项 PostgreSQL 并发用例跳过，并核验主执行者真实 PostgreSQL 日志；额外验证 13 类恢复状态漂移。没有连接生产、修改文件或启动子代理。

固定 base scope 的前后指纹一致：`efc67ebe3e76e29aa82bb67c8252fe2c2479b70a8f08c5d5fc88f648bc454a05`。review 原始日志含与本任务无关的上下文，不上传仓库；仅记录结论和输入绑定。

[云端 CI36924688047](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/36924688047) 已完成：49 项 0078 合同、18 项 0079 合同，Django check 和迁移漂移均通过。stable 全量基线 5653 项、候选 5678 项，两端均 22 failures、28 errors、21 skipped，失败名称完全一致，新增 0、修复 0；这不是全量零失败。artifact 中 commit.txt 分别绑定上述基线和候选，工作流合同检查两端均为 0。机器摘要及产物 SHA 见 [ci-validation.json](ci-validation.json)。

2026-10-02 05:46 北京时间 PR229 合并为 `3afde43abfd2df98744bf092f5f9839b5eae9409`，合并树与候选树均为 `409222f8ffefc6f598b558ae715b6e21e9df8065`。实际发布仍绑定受验候选 `ec461daa`。Compose 增加 `com.docker.compose.image.builder=classic` 后，最终镜像为 `sha256:4f835498e9f2f20af4e41d433094d3ddd70c4de6a279e5ee55859765033fd87d`；已核对文件层和除标签外的运行配置与预构建镜像完全一致。

候选镜像隔离网络检查：开启 coverage 后任务已注册、Beat 排程存在、路由为 celery；关闭后排程不存在、任务返回 disabled。makemigrations --check --dry-run 无变化。

## 真实数据形态演练

生产 dump 在隔离副本恢复时发现两处既有非赛事唯一约束问题，详见[恢复缺陷记录](../../reports/2026-10-02-backup-restore-findings.md)。整库恢复不计通过。

在仅排除上述两个失败约束的副本中，赛事表的 340 约束/244 索引/7 触发器通过比较；固定恢复包 ready → applied → already_applied，七个公开详情共 52 行、两条“跌倒”均正确，覆盖报告七场 confirmed，新后台 200 且没有 incident 写入。演练没有连接生产 Redis、队列或第三方服务，没有修改生产业务数据。
