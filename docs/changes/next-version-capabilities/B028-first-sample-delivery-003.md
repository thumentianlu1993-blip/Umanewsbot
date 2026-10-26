# PR238 与 B028-003 首样本执行确认材料

2026-10-05 23:28，Asia/Shanghai。当前为**待用户选择，未获批准**。本文件汇总固定交付对象，不改写人工门禁；唯一依据为根 [AGENTS.md](../../../AGENTS.md) 的 G2/G3。

## 一次选择

- **A：只合并 PR238，不执行生产操作。** 沿 [原合并交付材料](fourth-integration-delivery.md) 的固定 head/base 与正常远端合并流程。B028 样本继续为 0。
- **B：合并同一个 PR238，并连续执行下述 B028-003 首样本包（推荐）。** 只运行一次完整 28 天元数据读取，原 R 最多选择 1 条并读取其内容，完成私有交接与清理。现场前置失败即停，不能把获准执行记作取得样本。

B 不包含整版业务镜像发布。PR238 的 Git 合并与首样本工具的生产暂存是两个明确动作：PR238 不包含 B028 全部工具源码；首样本只使用下表封存工具，不从合并后的可变工作树取代码。若用户只批准其中一个动作，按其明确实际范围执行，不推定另一项也获准。

## 已完成的测试和独立审核

PR238 固定 head `78c65869166d3f56b0f8fc8469e8415dd78be121`，base/main `22e130adf4464fd3c5dd63ccd3f508c4a853d464`。23:27 实时仍 OPEN/Draft，`tests` 和 `test-plan-gate` SUCCESS，head/base 未变。原正式 CI 6,530 项：6,520 PASS、10 项明确许可 SKIP、0 failure/error；候选外可信 verifier 与独立审核证据见原交付材料。执行合并前再核实际 head/base、必需检查与保护，不用管理员绕过。

B028 原审核会话固定 `d3f801963a123a66681ba8d38829729d720e2656` 结论 `APPROVED_TECHNICAL_FIRST_SAMPLE_PACKET`，FINAL-01/02 关闭、无剩余 actionable finding。作者 5 项真实目标断言 RED 后，最终 9 项本地测试 PASS；R 独立复核 2 条原缺陷路径 PASS。ROOT 已读实际源码差异、原始日志、Git 报告及回执，核审前后官方指纹和 75 项输入起止一致。它们证明本地受控行为；Linux 现场 owner、真实共享锁和 native 四步仍是本包执行前置，尚未完成。

## 不可变对象

| 对象 | 固定值 |
|---|---|
| 操作 ID | `b028-first001` |
| B 报告提交 | `7a4f7c04bd270de4f896f19ad40af8e695502b9d` |
| 受验工具源码提交 | `ff5344b4cd02606f3353a375b2bcaa1501f3db1a` |
| 完整执行 manifest | `d93094c293d5742ad20ac9da426223947116b99f00c5ac9e0c0e350628055b9b`，11,770 字节，列出 73 份输入共 592,434 字节 |
| 工具 manifest | `6f26b7a36188ceef21714f1c85e07784e7515c4a95791b33b922e29caafe3825` |
| owner 源码 | `3fc9858c82d6bf877283ce29f80e96d80cae87e31d8f3367820ad086ef75925d`，15,901 字节 |
| owner config | `6a128e8893b2ac133ce9ea8dd88c2609541d057c1ae6c86353c9448b6b6d5bd1` |
| capture binding | `2cf201f30e3f3cc17cd1a0d8faf99ed687d891dfe4eadc1fc3e1d502625f4adb` |
| driver config | `6e201548c30695255e169681032a247cfdc426c8c35bbd638d32121bcc93231b` |
| R 审核收据 | `0ab076abd621b49003883066b1534f80121622024570ef68f8b7b29185514953` |

完整输入位于 `/Users/mentianlu/.codex/runtime/b028-first-sample-profile-execution-003/`；其中 `EXECUTION_PACKAGE.md`、`directory-plan.json`、`native-argv.json`、`owner-call-plan.json`、`manual-release-lock-plan.json` 与 11 文件工具包均受同一 manifest 绑定。本文只是该已审包的用户可读汇总，不替换或重生成它；最终获准 manifest SHA 作为独立可信参数传给 owner。

## 目标与允许的变化

目标是 Umanews 现有生产 web 容器及其既有数据库，只读数据范围为完整 28 天元数据与原 R 从该集合选出的最多 1 条内容。现场绑定必须仍为：

- 容器 `9f03d1faa0ccf681d50dd2a9db6018af55a33937bf94517b0d447f453ac2190c`；镜像 `sha256:73ee1dcf7edb5b7c7bda49f5d6baedffe030d639fcc5bf191b831ece6e9f5930`。
- 业务 release 与 resident marker 为 `ad50abdb74b89669ab8ada2958b040877c1a1849`；数据库 OID `16384`，既有 role OID `10`。本包不会扩展该角色权限。
- host `/usr/bin/python3` 精确 3.10.12；container `/usr/local/bin/python3` 3.12.13/psycopg 3.2.6；Mac 3.14.6。host/container UID:GID 为 0:0，Mac 为 501:20。boot、时钟 namespace、Docker socket、路径和健康状态均按已绑定完整配置实时复核。

| 项目 | 本包动作 |
|---|---|
| 数据库迁移、业务配置、功能开关 | 无 |
| 业务镜像构建、替换、服务重建/重启 | 无 |
| 业务数据新增、修改、删除 | 无；只读完整元数据及最多 1 条内容 |
| 临时文件与进程 | 新建下述专用目录，暂存固定工具/输入；运行单次 owner、有限资格和读取进程 |
| 互斥 | 复用既有 `/tmp/umanews-deployment.lock` 与已核 `deployment_lock.sh`，仅本次 acquire/verify/release；补实际 owner/心跳/恢复记录 |
| 失败恢复中的 DB 动作 | 仅对本次实际观察到的自有精确四元组，在原合同条件全部满足时 `pg_cancel_backend`；取消返回 true 后仍须独立确认 gone |
| 传输与消息 | 产物私有传回本机并交已有原 R 会话；无 QQ、邮件等对外发送 |
| 外部来源与付费 | 不新增真实网络抓取或付费模型调用，不恢复旧暂停任务 |

## 包内连续步骤

1. **确认版本与互斥。** 复核完整 manifest、现场身份、有效共享锁域和唯一 release coordinator；以固定源码启动单次 owner，实际取得既有共享锁。占锁、身份或路径歧义均停止，不接管他人的锁。
2. **创建专用暂存。** host 和 Mac 的共同根 `H=/private/tmp/umanews-f02-first-b028-first001`；container 根 `BASE=/app/runtime/f02-first-b028-first001`。host 首次增加 `/private`、`/private/tmp` 及 H 的 artifacts、adapter-control、operation、tools/scripts、native-source/scripts/tests、native-results/tmp；Mac 仅新建 H、artifacts、tools/scripts；container 仅新建 BASE、tools/scripts、inputs、driver-control、probe-control、runtime/next_version/F02。逐级独占创建，新目录 0700/新文件 0600；完整中间目录与 owner/recovery 临时文件见受 hash 绑定的目录清单。既有祖先权限保持，任一目标已存在即停止。
3. **验证同一工具与现场资格。** 按 manifest 逐文件暂存/核 bytes、SHA、owner、mode、常规单链接；执行 host verify、7 模块纯导入、原 Runner 的 3 个有限方法和真实 timer 控制，四步总窗 45 秒。container 执行相同工具 verify/import。全部成功且自有测试进程回收后才开始业务读取。
4. **取得第一份候选。** 只读完整 28 天 metadata，阶段 45 秒、清理预留 5 秒、外层 50 秒、客户端 55 秒和后续状态核验 10 秒保持。独立确认生产者/观察者/自有 backend 已闭合后，核完整文件集合并私有传回 Mac。
5. **由原 R 选择并实际签收。** 最多等待 600 秒，期间不开 DB 事务；原 R 从完整 metadata 选 1 条 exact 候选，或明确 no_candidate。另起独立 content 阶段，执行相同时间与闭合规则，核完整 source chain 后私有传回 Mac。ROOT 以原生会话 turn/message 来源和实际读取 ACK 完成受审 bridge；只有实际 `delivered_to_R` 才计 fresh=1。无候选、超时或未知维持 0。
6. **核验和清理。** 记录本次真实进程与 backend 身份、读取结果、R 来源、前后 CID/image/health、文件 SHA 和清理回执。仅在归属及闭合明确后清理自有专用暂存、保留审计证据，并向 owner 写实际 cleanup 确认。owner 只有自有执行成员闭合、身份无 unknown 且 ROOT 确认时才释放本人 token 的锁。

owner 总上限 1800 秒，ROOT 外层监督 1850 秒（30 分 50 秒）；它是停止上界，不能据此保证取得样本。原期限不延长，不自动重采、不缩 28 天、不以成功子集替代完整分母。

## 条件式取消与停止恢复

允许的取消只限本 operation 实际 seen-ready 的 `PID/backend_start/datid/usesysid` 四元组，经生产者归属回收、独立 observer 精确重查后才使用原受审条件式取消；随后独立确认 gone。不能按角色名或模糊 PID 取消，不使用 terminate/GRANT/换角色。

版本/身份/目录竞争/锁/native 资格、进程回收、DB 闭合或 R 来源任一失败即停止后续。对已记录且再次匹配 PID/start/UID/pgid/sid 的自有成员按原 TERM4/KILL3 窗定点清理；未知不误杀。未知或缺 ROOT 清理确认保留共享锁和 owner/recovery/最终收据，不按 age 自动删锁、不自动重试副作用。

恢复面为原业务镜像、release、配置、DB 业务行及 flags 保持不变；无需迁移回滚或服务重启。只清理已确认本次新建且归属明确的 H/BASE 后代；host 新增 `/private/tmp`、`/private` 仅在记录为本次创建且实际为空时逐级 rmdir。存在未知进程/会话时保留对应资源与锁，按既有人工 stale-lock 恢复面处理，不强制解锁。PR238 若需撤回，另按实际 merge commit 准备 revert PR，不 force-push。

本包成功最多证明第一份真实样本闭环，不等于 F02 全量完成、F03 的 45 项分母达成或整版公开验收。当前状态仍为未合并 PR238、未执行首样本包、fresh=0。
