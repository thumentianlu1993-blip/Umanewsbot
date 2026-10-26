# B028 修正输入后的单次首样本执行包 004

2026-10-06 00:28，Asia/Shanghai。**原 R 技术复审已通过，等待用户确认新包的单次生产执行。** 本文件沿根 [AGENTS.md](../../../AGENTS.md) 记录固定交付对象，不新增人工门禁。

## 本次需要决定的动作

PR238 已合并为 `ec0a12506cf2131eb6f6d774d9941f764f15c845`，不再请求合并。上一次 003 在数据库读取前因输入 JSON 编码摘要不一致而拒绝，原进程、专用目录及自有遗留锁均已清理，样本仍为 0；见[实际执行与恢复记录](B028-first001-execution-20261006.md)。

本次拟**按修正包 004 再执行一次首样本读取**：完整 28 天元数据，由原 R 选择最多 1 条内容并实际私有签收；无候选或失败时仍为 0。执行范围、限额、工具代码、生产目标和恢复面与[003完整交付材料](B028-first-sample-delivery-003.md)相同，以下仅替换固定输入和其派生摘要。003 不再执行，004 没有自动重试授权。

## 修复与不可变对象

修复使用原 exporter 的 JSON 编码函数生成 binding 文件，使文件原始 bytes 与 driver、container journal、status 使用的 bytes 相同。17 个字段及全部业务值保持原样；不降低摘要校验，不放宽任何时间或数据范围限制。

| 对象 | 004 固定值 |
|---|---|
| B 报告提交 | `62b52dbe163164702d76a83b9b0016c379d1ac71` |
| 完整 manifest | `b0c7f78a20872525ed2175cc4aca5439b6312a8cd8cba07341d3fc2e1af327ce`，12,449 字节，88 输入共 637,063 字节 |
| 完整包目录 | `/Users/mentianlu/.codex/runtime/b028-first-sample-binding-encoding-004/candidate` |
| binding 文件 | `bc2c999c34d8de32f0359a2f088d874b6b59e10656bd059f5d459c264f813c75`，865 字节 |
| owner config | `a36ed976a88f9ecb95b37564b9848fd44b9adb3a2e49e890efc1308195693cac`，1,091 字节 |
| 核心工具源码（不变） | `ff5344b4cd02606f3353a375b2bcaa1501f3db1a` |
| 工具 manifest（不变） | `6f26b7a36188ceef21714f1c85e07784e7515c4a95791b33b922e29caafe3825` |
| owner 源码（不变） | `3fc9858c82d6bf877283ce29f80e96d80cae87e31d8f3367820ad086ef75925d` |
| driver config（不变） | `6e201548c30695255e169681032a247cfdc426c8c35bbd638d32121bcc93231b` |
| ROOT 静态核验收据 | `a0fb73852e9fefe33f2af42544b1cd12ed64e8573855d7902f428d9d23acacdf` |

相对 003 的继承输入只有四项变化：binding、owner config 的派生 argv、执行 argv 和包说明。新增 15 项为修复生成/验证/测试代码与证据；完整 003、原 73 输入、全部历史失败日志保持封存。

原始 003 实际输入在原调用链取得 1 项目标断言 RED，0 error/skip。修正后 6 项本地检查全部通过，覆盖原 StageRunner、封存 entry、container_main、原 parent journal 到 status 的摘要链，以及旧 compact/tamper 仍被拒绝。Linux identity、clock、alarm 和 DB 边界使用受控夹具，不冒称本轮完成真实 PG 或生产采样。原 R 固定提交 `0a0018b077e47106d9941ef7a83fa5b94ba11252` 结论 `APPROVED_TECHNICAL_BINDING_REPAIR_004`，无 actionable finding，003 编码问题关闭。R 独立 6 项复验全部通过；官方前后指纹一致，89 项候选输入加 ROOT 收据共 90 项起止 seal 一致，ROOT 已逐项核实际文件。R 收据 SHA `618777c14bf25c75b02a5c8dca289278dfb79de6e96709170b26704d5df7cf8f`。

## 生产动作、限额与恢复

operation 仍为受审代码固定的 `b028-first001`，这是在旧尝试明确结束并清理后拟重新批准的单次尝试；旧执行证据留在独立审计目录，不覆盖、不复用旧结果。执行前必须确认所有新目标路径不存在，当前 CID/image/release、环境绑定与共享锁域仍匹配；否则停止，不接管任何已存在目录或锁。

- 目标仍为 CID `9f03d1faa0ccf681d50dd2a9db6018af55a33937bf94517b0d447f453ac2190c`，image `sha256:73ee1dcf7edb5b7c7bda49f5d6baedffe030d639fcc5bf191b831ece6e9f5930`，release/marker `ad50abdb74b89669ab8ada2958b040877c1a1849`，DB/role OID `16384/10`。
- 取得原 `/tmp/umanews-deployment.lock`，以同 owner 工具记录真实身份与心跳；仅新建 manifest 所列 host/Mac H 与 container BASE 私有目录、暂存固定工具和输入。Mac 新目录首次设置为 501:20、0700，文件 0600；host/container 为 0:0。既有祖先不改。
- 沿同包完成环境/工具核对及有限 native 四步，然后读取完整 28 天元数据；原 R 最多等待 600 秒选择 1 条或 no_candidate，等待时没有 DB 事务。另起内容阶段，私有传回 Mac 并通过原生 R 来源和实际读取 ACK 核验。
- 原阶段 `45/5/50/55/10` 秒、native 总窗 45 秒、owner 1800 秒与 ROOT 外层 1850 秒均保持。没有自动重采、延长上界、缩分母或截取成功子集。
- 仅在原合同条件满足时，对本次实际 seen-ready 的精确自有 `PID/backend_start/datid/usesysid` 四元组执行条件式 `pg_cancel_backend`，随后独立确认 gone。无 terminate、GRANT、角色切换或模糊取消。
- 失败即停止后续，保留原始收据；仅清理再次核实归属和闭合的自有目录/进程。未知保留锁与恢复事实，按原包的既有 manual stale-lock 恢复面处理，不能按 age 自动解锁或接管他人资源。

数据库迁移、业务配置/开关、业务镜像构建或替换、服务重建/重启、业务数据写删均为 **0**。无新增真实来源抓取、付费模型调用、QQ/邮件等外部消息。恢复面仍是原业务镜像与数据不动，清理本次专用暂存并保留审计；无需数据库或服务回滚。

成功最多证明 1 份真实样本交付，不代表 F02 全量、F03 45 项分母或整版公开验收完成。
