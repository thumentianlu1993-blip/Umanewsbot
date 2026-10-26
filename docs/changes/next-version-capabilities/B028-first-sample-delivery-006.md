# B028 单次诊断与首样本读取包 006

2026-10-06，Asia/Shanghai。**原R技术复审通过，等待本包单次生产执行确认；目前未获批准。** 本文件固定本次拟执行的对象和范围；人工确认唯一依据为根 [AGENTS.md](../../../AGENTS.md) 的 G2/G3。

## 动作目的与已知限制

004 已实际执行一次，在 metadata producer 内失败，样本为 0；自有进程、暂存目录和锁均已清理，原 R 已独立核验，见[004实际执行记录](B028-004-first001-execution-20261006.md)。其现场根因仍未知，不能把本次修改写成生产故障已修复。

006 拟执行**一次带有限错误分类的诊断与首样本读取**：读取完整 28 天元数据，若成功，由原 R 选择最多 1 条内容并实际私有签收；若再次失败，保留固定类别与闭合证据，停止本次执行，不自动重试。它可能只取得更明确的失败类别，不能保证得到样本或确定全部根因。

相比已执行的004，005增加固定本地错误码并在父进程严格校验后保留；006修复原 R 的 `DIAG-R01`，在 collect 和 publish 成功返回后立即复位通用错误码，避免把后续 close、deadline、schema访问故障误归到已经成功的阶段。不输出异常正文、数据库连接信息、SQL或文章内容到诊断消息。最后收尾 close 失败仍优先报告 `producer_close_unknown`。

本包不包含PR合并或整版业务镜像发布。若另行合并PR239，仍使用本表封存工具执行006，不从可变工作树取程序。003、004、005不再执行，所有历史输入和失败记录保留。

## 固定对象与验证

| 对象 | 006固定值 |
|---|---|
| 操作ID | `b028-first001`，旧尝试结束并清理后的一次新尝试 |
| B报告提交 | `76df1879a75d4ff1e92dfb62b8bab0a59beb9f34` |
| 工具代码提交 | `b0995a7264e505e84bd9464ce198372364484cb4` |
| 完整manifest | `3e561f256030c8d13695764ffbe07d7069b2dabcdbbd019120fba2f9559e6b28`，17,307字节，125输入共1,070,848字节 |
| 包目录 | `/Users/mentianlu/.codex/runtime/b028-producer-diag-r01-fix-006/candidate` |
| 工具manifest | `b38a6266946f434434584d3912aaf6b22c3e84b9972fd67d1f4ca2f1382ed430` |
| capture程序 | `7eb53f61bfa5eac5392219abf6d10d7eefaf9647b560e49bd531fb854e22cdf2` |
| canonical binding | `0a79b156f08e1c77daa291766d29f726fb4059124f82a145f7a5b88b502996e2` |
| driver config | `1632e8532bf7fcc6e6cb77a804ec71fe68c9b166e6e34c55fba1992011093b02` |
| owner config | `6de95c4c0e430cca36cd0dffae7215931adaa2a5312f0aeef9ec1a40120e4214` |
| owner源码（不变） | `3fc9858c82d6bf877283ce29f80e96d80cae87e31d8f3367820ad086ef75925d` |
| ROOT静态核验收据 | `de8baa811ad8b3d6ab7a7d269a27226374482d38668461a43c37afdb999cdfdc` |

ROOT实际核对125输入的bytes/SHA、固定4文件Git差异、工具与native源码、canonical编码及派生argv；相对005仅声明的9项继承输入变化。旧003的73项、004的88项和005的109项及各manifest逐项复验不变。006只增加两行阶段复位；owner、exporter、transfer、driver、helper及其余13项native源码保持原字节。

作者对原 R 两个反例及publish同类边界取得3项真实目标断言RED，修复后同3项GREEN；包含原诊断6项的有限影响集共9项实际通过，0失败、0错误、0跳过。全部为合成边界测试；未重复旧PG/Linux/native/owner/profile整组，也未连接生产。本包新源码的现场import/native资格仍属于获准后的前置步骤。

原 R 固定复审提交 `7e065c7aa96b95f1f32cf6704658c5bf0d21b174` 结论 `APPROVED_TECHNICAL_DIAGNOSTICS_006`，`DIAG-R01 CLOSED`，无新finding。独立9项诊断测试实际全部通过，0失败/错误/跳过，包含三个反例；官方同base起止指纹一致，129项私有输入seal字段一致，ROOT已核Git报告及全部实际原件。R报告SHA `429b7e584ce9243a3fff87d94560ecf7fc2bacff9fb989360f345e9a4f54ba4c`，收据SHA `da5b389fe093e425d4df824e3078549f8a910e5ae70728ea95180d67f6d72642`。这仅关闭本地技术finding，004现场根因和006现场资格的限制保持。

## 生产目标、连续步骤与限额

现场目标必须仍为CID `9f03d1faa0ccf681d50dd2a9db6018af55a33937bf94517b0d447f453ac2190c`，image `sha256:73ee1dcf7edb5b7c7bda49f5d6baedffe030d639fcc5bf191b831ece6e9f5930`，release/marker `ad50abdb74b89669ab8ada2958b040877c1a1849`，DB/role OID `16384/10`。host Python3.10.12、container Python3.12.13/psycopg3.2.6、Mac Python3.14.6和完整配置中的boot/clock/socket/身份条件须现场复核；改变即停止。

1. 复验完整manifest、现场版本、唯一release coordinator、锁域和目标路径不存在。以不变owner工具取得既有 `/tmp/umanews-deployment.lock`，记录真实owner和心跳；占锁或归属歧义停止。
2. 按固定directory-plan独占新建host/Mac的 `H=/private/tmp/umanews-f02-first-b028-first001` 与container的 `BASE=/app/runtime/f02-first-b028-first001` 及所列后代，暂存工具和输入。新目录0700、新文件0600，host/container为0:0、Mac为501:20；仅对自己刚创建的目录设置权限，既有祖先不改。旧执行证据另存，不能复用旧结果或接管既有目录。
3. 核逐文件SHA、bytes、归属、权限及单链接，执行host verify、有限纯导入、原3个Runner方法和真实timer；native四步总窗45秒。container执行同包verify/import。全部通过且自有资格进程回收后，才能进行业务读取。
4. 一次读取完整28天metadata；原阶段45秒、清理预留5秒、外层50秒、客户端55秒、状态核验10秒保持。独立核producer/observer回收与精确自有backend gone，核完整文件集合，私有传回Mac。
5. 原 R 最多600秒选1条exact候选或明确no_candidate，等待时不开DB事务。另起一次content阶段，使用相同限额和关闭规则；私有传回后，ROOT核原生R会话来源、实际内容读取ACK及受审bridge。只有真实 `delivered_to_R` 才记fresh=1，其余保持0。
6. 核前后CID/image/健康、自有进程/backend身份和结果；归属及关闭明确后清理专用暂存，保留新独立审计目录。ROOT写实际cleanup确认后，owner按不变条件释放本人token的锁。

owner总上限1800秒，ROOT外层1850秒。沿manifest中的原数量、行数、字节、完整集合及有限等待规则，不缩28天、不截取成功子集、不延长时限，也不自动重采。

## 停止、恢复与未包含动作

版本、身份、路径竞争、锁、native资格、回收、数据库关闭或R来源任一失败即停止后续。只在原合同全部满足时，对本operation实际seen-ready的精确 `PID/backend_start/datid/usesysid` 四元组执行条件式 `pg_cancel_backend`，其后仍独立核gone；不使用模糊取消、terminate、GRANT或角色切换。

仅对再次核实PID/start/UID/pgid/sid的自有成员按原TERM4/KILL3窗清理；身份未知不误杀。仅删除本次实际新建且再次核对归属、清单和关闭证据的H/BASE后代；host新建 `/private/tmp`、`/private` 只有本次创建且实际为空时才逐级rmdir。未知保留对应资源、锁及恢复事实，按既有manual stale-lock恢复面处理，不按age自动解锁、不接管他人token。失败收据完整保留，不能覆盖为成功。

迁移、业务配置/开关、业务镜像替换、服务重建/重启、业务数据写删均为0；无新增来源抓取、付费模型调用、QQ/邮件等外发或旧暂停任务恢复。回退面为清理本次专用暂存并保持原业务镜像、配置与数据，不需要数据库迁移回滚或服务重启。

成功最多证明1份真实样本私有交付，不代表F02全量、F03的45项分母或整版公开验收完成。
