# PR238 合并交付确认材料

2026-10-05 15:00，Asia/Shanghai。建议只合并 [PR #238](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/238)，不发布。当前为 Draft / OPEN / MERGEABLE，测试和独立审核已完成，尚未取得本次 G2。人工确认依据根 [AGENTS.md](../../../AGENTS.md)。

## 固定对象与代码范围

- head：`78c65869166d3f56b0f8fc8469e8415dd78be121`。
- base / 当前 main：`22e130adf4464fd3c5dd63ccd3f508c4a853d464`。
- 受验 merge/test SHA：`3d6e7e289cf0c8bf7350651ba9aad8d5880a1ba0`；两个 parent 为上述 base、head。
- 受验 tree：`605e94c51c557edff19e0c348c80f881fb0ad411`，与候选 head 的 tree 相同。

相对 main 共 33 个文件：公开赛事日历与赛事详情的可比较内容标记，离线 HTML 解析器、模板适配器及冻结合成样本，三个标准测试模块、独立测试辅助包和类级环境恢复验证，以及共享测试路径/领域映射。大部分新增行属于冻结 JSON 样本。

另修复两个 PostgreSQL 并发测试模块在线程退出后遗留健康连接的问题：在创建连接的线程内执行 finally 关闭，并检查 backend PID 已退出。保留业务断言和测试方法，修复测试库清理失败。

没有新增迁移、生产 settings/Compose 配置或功能开关。本次不包含 C026 真实 ORM loader、B020 Responses/mock 适配器，也不宣称真实公开探针、来源采集、浏览器视觉或 SLA 自然观察已完成。

## 验证与审核

- 原独立 R 对离线业务、装配接线及映射审核通过；装配审核 `da61d001`，映射审核 `c44ae561`。C025 连接清理修复经 `8d69f508` 批准，官方范围指纹补充 `02a825c3` 的前后文件逐字节一致。补充是固定差异的本次复核证据，不倒写历史审前状态。
- PR 事件正式 [CI 37270807349](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/37270807349) 于北京时间 14:36:33 完成。full 6,530 项 / 47 批：6,520 通过、10 项许可跳过、0 失败、0 错误、0 意外成功；6,530 个实际 ID 唯一，全部 batch 生命周期 complete、退出码 0。`tests` 与 `test-plan-gate` 成功。
- 10 项 skip 保持既有清单：8 项缺真实缓存输入、1 项镜像修复契约未启用、1 项要求 root EUID；均有 10/16 复核期限。跳过不计通过，也不据此缩小后续验收分母。
- 候选目录外的 main 原 verifier，以 Python isolated 模式下载本轮实际 CI 镜像、独立重收集并比较完整 ID/分批，核实际报告、受审控制、base/head/tree 和分支保护，最终 exit 0、`status=verified`。未修改 verifier 或绕过检查，未重跑业务全量。
- 主线保护实时核验：必需检查 `test-plan-gate`，`strict=true`，`enforce_admins=true`。最终 head/base 未变。

| 证据 | 固定值 |
|---|---|
| 可信 verifier SHA256 | `7e58cb72042dd76ef064f9121589f1a06655aad6befc1278d389ffc8799c7d7d` |
| 正式收据 | `/Users/mentianlu/.codex/runtime/fourth-integration-evidence/delivery-78c65869.json` |
| 正式收据 SHA256 | `538244375fd40eaadc74d5b8f3b19623e6897adc20de1697310f331690678c7b` |
| 正式 plan digest | `41d3f9e72d0d06b16f074ddcce23f5c7a6f3981d0e4cd8d4d38b353fb29d82a1` |
| plan content digest（不同字段） | `41c640c949564c9c5e7e682dc59f6f28d5fb4f933b62b0ea027bddb4e1d4d2c5` |
| 实际 CI image ID | `sha256:645ad69fad9a22683b9e0eb0d06f45d7553fa2ccf929146ef9176060cae8ce32` |
| 测试 artifact / ZIP SHA256 | `11329182178` / `ba0cc687588f320818bff75d60ba2be1a32989d03316ed8563bff6847d9762cb` |
| 镜像 artifact | `11329077423`，396,303,840 字节 |
| 原始 CI 输入副本 SHA256 | `b86fac057f56814bf96da5ecb2c507eea3d7d2614c7492538f0a877d32be70a2` |

原失败 CI `37266491076` 的 6,530 项及 batch-031/032 清理失败记录保留；通过结论来自修复后新一轮完整 CI。镜像前两次下载被 ROOT 因耗时主动中断，当时未测网络进展，不能据此认定服务端故障；第三次传输确认进展后完整结束。原始日志保留，第三次没有改变核验规则。结束后自有核验进程退出、专用 daemon 无运行容器，仅保留无关历史退出容器。

## 建议确认与执行范围

建议批准“只合并 PR238 的上述固定 head，不发布”。获准后先重核 head、main/base 和必需检查，再通过正常远端合并，核 merge commit、parents、tree 和 main，回写真实结果；不用管理员绕过，不改动其他工作树。结果未知先查实际状态，防止重复副作用。

本包生产动作全部为 0：迁移、配置/开关应用、服务构建/重启、生产数据写入、真实抓取、付费调用及对外发送。生产维持现有版本。撤回代码应按实际 merge commit 准备 revert PR；本包不授权 force-push 或生产回滚。

“合并并发布”的精确包尚未就绪，O02 完整恢复、真实来源/样本和自然观察证据仍缺；不能预批准未定义的生产动作。若用户希望连同发布，先补齐实际服务/配置、备份、验证和回滚的固定清单，再依根 AGENTS.md 确认。本次合并通过也不等于整版完成或公开验收。
