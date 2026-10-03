# Q02 调度与 Compose 声明退出：协调者实现切片

2026-10-03，Asia/Shanghai。依原 R 已审 Q02 方案 `7e3f70c22c2a83558b0b7623711a6fba70760afc`（结论 `e97406d7a0392dd0efd6e8793725798d42078a05`），实施基线 `3a7026c2`。本切片由协调者负责，C008 独立负责 UI/action；不覆盖 C 的文件。

## 范围与实现

- `server/app/settings.py` 仅删除 `qq-production-regions-window` 周期任务声明。
- 两份 production Compose 仅删除可选 `onebot` / `with-onebot` 占位服务。
- 旧 task 注册名、guard、共享通知/日志、请求库、队列和登录卷均未改。代码移除声明不等于已停真实网关，不能用本切片证明生产零发送。
- 不新增迁移、开关或生产动作。完整 Q02 需与已审 Q01 和 C008 一并集成；实际 OneBot 资源身份、持久 Beat schedule 和恢复面仍由 O06 精确包处理，遵循根 AGENTS.md。

## 测试与证据

依据总 `test_cases.md` TC-Q01 及已审 C/Q02-plan 第 6 组。本次采用仓库 tdd：先改两个既有 Compose 合同、增加一个 Beat 合同，再运行真实 RED；未改测试 ID 或放宽 skip。

首轮发现 `compose config` 默认隐藏未启用 profile，使两项 Compose 检查意外通过；在生产配置修改前将解析范围增强为 `--profile '*'`。最终 RED 是 3 tests / 3 failures / 0 errors / 0 skips，分别因两份 Compose 仍包含 OneBot、Beat 仍包含 QQ 周期而失败。随后最小删除三个声明块，相同 3 项 GREEN，0 failures/errors/skips。

宿主诊断命令：

```text
/Users/mentianlu/Code/umanews/.venv/bin/python -I /Users/mentianlu/.codex/runtime/q02-operations/run-contracts.py
```

runner 先复用 `test_plan_worker.setup('python')` 清理宿主环境、禁用 dotenv，测试基于 SimpleTestCase 不用数据库；socket connect/connect_ex 被禁止，Compose 仅离线 `config --format json`，无 daemon/container/网络操作。此为宿主局部诊断，不是正式 Linux PR delivery。

- `test_t16_standard_compose_config_is_valid` / `test_t16_lowcost_compose_config_is_valid`：枚举所有 profile 后不含 OneBot 服务、相关 profile 或依赖；网站/worker/beat/redis/nginx 服务仍在。能捕获恢复占位服务或共享组件继续依赖 OneBot 的 mutation。
- `test_q02_beat_keeps_web_pipeline_without_qq_schedule`：五旧 QQ task 均没有周期入口，网页发布/抓取/翻译任务保留；能捕获恢复 QQ 周期或误删网页主链的 mutation。
- 额外按基线逐字比对，三个配置文件唯一变化恰为预期删除块；AST 与 diff check 通过。

源码位于既有 `stable.test_single_migration_owner` 模块，其 module domain/django profile 已登记；新增 1 method 会自动进入 module collect，原 2 个 environment_contracts IDs 保持。settings 与两 Compose 为现有 high_risk 路径，下一固定集成候选须按原策略 full，不修改策略、不另跑未集成重复 full。精确控制映射待最终组合统一审核。

私有运行证据目录：`/Users/mentianlu/.codex/runtime/q02-operations/`。RED/GREEN/static 哈希见下表；日志未纳入仓库。

| 文件 | SHA256 |
|---|---|
| run-contracts.py | `8e086b474ccbf0f1886a4d7498e49ef6cc64cfe3bfa616c772268bc29ea4e37c` |
| red-all-profiles.log | `70b0b3a669220489be3c8bba6bbf2029900cf9410663476dfa1b5fb72db0dcf1` |
| green.log | `78c07902eaa97823ac52d349e574ca1695844e3cbcc60d5b81791a04bfe186a3` |
| static-scope.json | `27fd77a3af8b6730447d400df702e2e9a4d3054b11488181b46e858bc895814a` |

当前本地切片已实现、最小检查通过，独立代码 review 和正式组合交付尚待；没有合并或部署。
