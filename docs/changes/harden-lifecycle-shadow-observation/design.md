# Lifecycle shadow 观察加固设计

## 1. 当前数据流

```text
Beat(true/shadow)
  -> scan_due_race_event_lifecycle_task
  -> claim control
  -> advance task(queue=celery)
  -> worker settings gate
  -> apply_race_lifecycle_decision
  -> proposal audit only
```

配置漂移事故中 Beat 和 worker 来自同一 Compose project 的不同 working directory。Beat
继续派发，而 worker 的本地 settings 已变成 `false/off`，因此 task 在事务内 gate 提前返回。
该返回既没有 transition，也没有明确的跨容器不一致错误；操作者只看 Beat 或队列无法定位。

## 2. Shadow 结果记录

不新增字段。复用 `_record_attempt(..., success=True)`：

- 新 proposal 调用 `success=True`；
- proposal duplicate 同样调用 `success=True`，因为它证明本次决策、数据库和去重合同均成功；
- error/noop 的既有分类不变。

此修改只影响 control 的运行统计和成功时间，不改变 proposal 内容、去重键、下一刷新时间和公开
状态。真实错误仍走 `success=False`。

## 3. Scanner 与 worker 的运行配置握手

scanner 构造 dispatch kwargs 时增加：

```python
expected_runtime_enabled=True
expected_runtime_mode=settings.RACE_EVENT_LIFECYCLE_MODE
```

task 参数提供向后兼容默认值，用于吸收部署前已排队的旧消息。默认值代表“未携带期望”，旧消息
继续走原 gate，不因签名升级反序列化失败；只有新 scanner 消息执行强一致比较。

worker 顺序固定为：

1. 读取实际 enabled/mode；
2. 若消息携带期望且不一致，写 error log 并零业务写返回；
3. 再执行现有 enabled/mode gate；
4. 一致且启用时进入 `transaction.atomic()` 与 apply。

日志字段使用固定 event 名称 `lifecycle_runtime_config_mismatch`，不包含凭据或 `.env` 内容。
不在漂移路径释放 claim：关闭态写 control 会破坏现有 fail-closed 合同；claim TTL 240 秒是有界恢复
机制，下一轮 scanner 可重试。

## 4. 宿主机一致性检查

新增 `deploy/verify_lifecycle_runtime_coherence.sh`。生产调用的 expected project、release
directory、image ID 和 release commit 均不可省略。它只调用：

- 宿主级 `docker ps`（全量运行容器 label census）；
- `docker inspect` 与 `docker image inspect`。

实现先枚举所有带 `com.docker.compose.service` label 的 running 容器。对
`web/worker/beat`，任何 project 下的额外常驻容器、运行 one-off、label 缺失或异常都失败；预期
project 内每类必须精确一个。随后拒绝 inspect 失败、状态未知、环境键缺失/重复、image ID/
OCI revision 不等于预期、project/working directory 不等于预期。环境只提取两个允许键，不打印
全部 `.env`。

脚本是部署后、shadow enable 前、手工 scanner 前和观察快照的硬验收工具；它不直接加入 Celery，
避免给容器挂 Docker socket。

## 5. 专用 lifecycle mode 切换

不消除现有两份 `.env`，而是新增唯一受支持的切换入口。原因是生产 Compose 当前以相对 `.env`
作为 service `env_file`，直接改成外部单一 env source 会扩大所有服务的配置加载和回滚边界。

`deploy/switch_lifecycle_mode.sh` 接受两个精确绝对路径：

- canonical state：`/opt/umanewsbot/.env`；
- active release：`$EXPECTED_RELEASE_DIR/.env`。

脚本扩展 deployment lock action 为 `lifecycle-mode-switch`。取得锁后先停 Beat；对两文件以
`lstat/stat` 检查 regular、non-symlink、owner 和 0600，解析两个 lifecycle key 且各恰好一次。
每个源文件在同目录创建 mode-600 高熵备份和临时文件，保持其他字节不变，只替换两个键。临时
文件 fsync 后 rename，逐文件重新读取验证。备份是取证和人工恢复材料，不是无条件自动回写源。

两文件完成后以 `up -d --no-deps --force-recreate web worker` 重建，先用一致性脚本的
`EXPECTED_BEAT_STATE=stopped` 形态核验 web/worker 的新 flags/image/release，并确认宿主没有
running Beat；停止的旧 Beat 容器不参与 flag 判定。随后以
`up -d --no-deps --force-recreate beat` 启动新 Beat，最后用 `EXPECTED_BEAT_STATE=running`
做全量 census。只有最终核验成功才置 committed、保留备份并释放锁。

失败恢复是单向收敛状态机，唯一自动安全目标为 `false/off + Beat stopped`：

- enable 前置要求两文件和三服务均为 `false/off`。从首次写文件起到最终 census 的任一失败，
  trap 先停止 Beat，再从原 false/off 内容生成两份安全临时文件并原子替换，强制重建 web/worker，
  最后做 Beat-stopped census；即使 Beat 已启动后最终核验失败，也走同一路径。
- disable 不把原 shadow 备份写回。失败后继续以原文件的非 lifecycle 内容为基底，把两个键写成
  false/off，强制重建 web/worker，并做 Beat-stopped census。
- 发生 web 已重建、worker 只重建一半等中间态时，恢复器不推断当前 flags，仍执行完整 off
  收敛。若文件替换、重建或恢复 census 再失败，执行 `stop beat worker`；停止探测也必须
  fail closed。此时不释放锁、不删除备份/临时证据，打印不含环境值的人工接管提示并退出。

因此“恢复成功”必须同时证明两 env 为 false/off、web/worker 为预期 release/image/commit 且
false/off、宿主无 running Beat；仅文件恢复不构成成功。

## 6. Compose one-off 防护

在 `compose-wrapper.sh` 中实现小型、fail-closed 的 canonical parser，而不是尝试复制全部
Compose grammar：

1. 只为识别子命令消费当前仓库使用的 global options：`-f/--file`（分离值或 `=` 值）、
   `-p/--project-name`、`--project-directory`、`--env-file`、`--profile`；
2. 子命令前的任何 option 必须在该 allowlist，缺值、未知 option、`--` 均失败；在 canonical
   global grammar 内识别出的非 `run` 子命令才原样 exec；
3. `run` 后前两个参数必须精确为 `--rm --no-deps`；
4. 继续消费 allowlisted run flags 及带值参数，包含 Release B 所需的重复 `-e VALUE` /
   `--env=VALUE`；
5. 第一个非 option 是 service，此后的任何 `--no-deps` 都只是 command argv；未知 option、缺值、
   `--` 前无 service 或 service 缺失均在 Docker 调用前失败。

实现前先以最新 main 的全部 wrapper one-off 调用生成合同清单，避免漏掉真实语法。

共享锁仍由上层生产入口负责：`run_release_tasks.sh` 和
`deploy_race_live_p0_closed.sh` 已在调用前验证/持有锁。本 change 不把 wrapper 改成完整授权系统，
因为它还服务于本地开发和只读命令；直接原生 Docker 命令属于明确的运维边界和残余风险。

## 7. 并发、幂等与失败恢复

- proposal 仍由唯一 `dedupe_key` 幂等。
- mismatch task 零业务写，claim 最多保留到原 TTL；不会产生重复 proposal。
- 完整恢复链为：原 claim 在 TTL 前不可重领；TTL 后 scanner 生成新 token/claim generation；旧
  消息因 identity/generation 不匹配零写；新消息成功后释放 claim。
- 宿主脚本只读，可并发执行；任一快照不一致即失败，不尝试自愈。
- one-off 缺 `--no-deps` 在 Compose 调用前失败，不会重建依赖。
- 关闭 lifecycle 的紧急止损路径不变：统一 `.env` 后在共享部署锁内从隔离 release 重建
  web/worker/beat，再用一致性脚本确认 `false/off`。

## 8. 性能

- dispatch 仅增加两个小参数。
- worker 比较常量 settings，不增加数据库查询。
- 宿主检查只在发布/观察时运行，对 3 个容器执行有界 inspect，不进入 Beat 高频路径。
- 不新增表、索引、全表扫描或高频日志；只有真实配置 mismatch 记录 error。

## 9. 兼容与回滚

- 无 migration。
- task 新参数必须有默认值，旧 broker 消息可被新 worker 消费。
- 代码回滚前先把生产统一恢复 `false/off`，再回滚镜像；不删除 control/proposal。
- wrapper 防护回滚只恢复旧 wrapper，不需要数据回滚。
- shadow 统计修复写入的是准确运行事实，不反向修改历史 `consecutive_failures`；现有 16 场只在
  后续成功处理时自然归零。

## 10. 预计文件

- `server/stable/services/race_event_lifecycle.py`
- `server/stable/tasks.py`
- `server/stable/test_race_event_lifecycle.py`
- `deploy/docker/compose-wrapper.sh`
- `deploy/verify_lifecycle_runtime_coherence.sh`
- `deploy/switch_lifecycle_mode.sh`
- `deploy/deployment_lock.sh`
- `server/stable/test_single_migration_owner.py` 或独立部署合同测试文件（实现前由测试边界决定）
- 本 change 五份文档及项目状态/决策/部署文档。
