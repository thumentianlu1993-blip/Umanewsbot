# B100 单次生产只读计数执行包（固定宿主路径修正）

2026-10-10，Asia/Shanghai。状态：本地测试及原R独立审核通过，等待新精确包确认；尚未执行。人工确认依据仅为根 [AGENTS.md](../../../AGENTS.md) 的 G2/G3。

## 目的与交付选择

006 已执行并因 `metadata_budget` 失败，fresh=0；其授权已消费。本包仅执行一次数字计数，查明完整28天范围的规模及哪个既有预算被超过，为后续方案提供依据。结果可能失败或仍不足以解释全部根因；不保证取得样本，也不自动重跑006、放宽预算或触发内容读取。

PR248已只合并为 `1dd5e0a508957672bcddd1c33e454fbbef1b75c1`，未部署；本次不合并或发布代码。旧B034获准后因父目录不存在停在只读预检，暂存/锁/DB/count尝试均0，原单次计数未消费。本包仅修正固定H到已有标准临时目录下的专用路径，不创建祖先。用户可选择：

- A：保持当前状态，暂不执行生产计数。
- B（推荐）：批准本文件绑定的 B100 manifest，执行一次只读计数及下列必要准备、验证、收尾和限定恢复。

## 固定输入

| 对象 | 固定值 |
|---|---|
| 操作ID | `b030-count001`，最多一次计数，自动重试0 |
| 业务工具Git | `f87479c33a42871d7b913c83b9fd50c8d4f3bd0f` |
| 本地冻结包 | `/Users/mentianlu/.codex/runtime/b100-b034-host-path-repair-001/candidate` |
| execution manifest SHA256 | `8ed1d55bb73b6fa680637f8769f8e037113717f32d739fccf42b033203221325` |
| manifest及输入 | manifest45087字节；112输入共1889837字节 |
| commands SHA256 | `e15ca35a300f65447062d921cf0043854aec0752d9bc0f7d353709ecc19380d2` |
| 原R最终审核 | `00ddbb4ba9c19bb3828a98885ef25ecd55281d6a`，APPROVED，无finding；原R01/R02/R03保持关闭 |
| R最终receipt SHA256 | `5465da35d399ca7332a53eea2b93d8e986e75ef70ba0278f5d6ff6014cbc4167` |
| ROOT本地执行审计目录 | `/Users/mentianlu/.codex/runtime/b100-root-execution-001` |

ROOT已核112输入及11项作者证据hash、候选113项前后seal相等；原R报告Git字节、回执与5项独立证据hash均通过。作者真实旧mkdir RED、49 GREEN；R独立旧mkdir RED、新增5项GREEN及1777父目录夹具、生成闭包验证通过。原B034的111封存条目保持；这不证明生产现场资格。

## 目标与读取范围

现场必须匹配：boot `53b84ff5-f54b-4253-83df-c359e744c9a0`；CID `9f03d1faa0ccf681d50dd2a9db6018af55a33937bf94517b0d447f453ac2190c`；image `sha256:73ee1dcf7edb5b7c7bda49f5d6baedffe030d639fcc5bf191b831ece6e9f5930`；release marker `ad50abdb74b89669ab8ada2958b040877c1a1849`；DB/role OID `16384/10`，执行UID/GID `0/0`。host Python3.10.12、container Python3.12.13/psycopg3.2.6及绑定的socket、clock、路径、权限须现场复核；不匹配停止。

固定SQL在 `REPEATABLE READ READ ONLY` 事务中，以数据库产生的UTC cutoff及前28天起点，读取：7张表的必要字段/类型摘要；6个计数（文章cohort、来源、抓取作业、生产窗口、候选决策、首页曝光）；日本、香港、英国、法国、美国5区计数；7维完整分组的总组数。来源表按原SQL全表计数，其余范围严格遵循封存SQL。不得改为子集、抽样或截断成功。

不导出文章正文、标题、原始元数据行或分组维度明细，仅保留固定结构的数字/状态/关闭证据。输出最多65536字节；缺字段、类型或完整性不符即未知/失败，不伪造分母。数值超过旧预算仍如实记录，不因超额提早丢掉其余合法数字。

## 连续步骤与资源限额

1. 复核manifest、现场身份、唯一release coordinator、目标路径不存在及锁归属。新鲜只读核 `/tmp` 为真实非symlink目录、root可信属主；共享可写权限必须有sticky保护，任一不符停止。独占创建 host `H=/tmp/umanews-f02-count-b030-count001`；通过8个固定块传入完整archive，校验62叶及全部祖先/文件身份，目录0700、文件0600。既有祖先不改、已有路径不覆盖。
2. 使用固定owner及既有helper `/opt/umanews-release-ad50abdb-test-fixes-20261002/umanewsbot/deploy/deployment_lock.sh`（SHA `66fa6d1b7de4789c185b2ac3f99702e77f1aeb3059962d2b2a4413e6de63387e`）持有 `/tmp/umanews-deployment.lock`，记录真实owner/token归属及心跳。不能接管他人锁。
3. 执行固定pre4资格检查；live owner/prepare/无count条件成立后，同CID创建 container `BASE=/app/runtime/f02-count-b030-count001`，固定8块安装。再完成post7资格检查，包含必要native/import/catalog验证。资格数据库连接正常共2个，实际关闭及本方actor回收须确认。
4. 资格全通过才向原owner发一次count请求；计数阶段正常2个只读连接（producer与observer）。工作40秒、close预留5秒、父进程45秒、Docker50秒、客户端55秒、状态10秒；SQL statement上限15秒并按剩余工作预算收紧，lock timeout1秒。最多额外1个只读恢复observer用于精确自有seen tuple核对。不会启动第二次count或自动重跑资格。
5. 核实际summary及其SHA、自有producer/observer/driver/parent退出、精确backend gone等全部关闭证据；拷贝本方审计，绑定本次真实summary后才可清理container，再收尾host并由原owner凭本人token释放锁，核真实final及锁确无。测试中的 `b`×64 summary不能执行清理。

prepare共用300秒；资格controller每阶段110秒（pre客户端45秒、post85秒）；owner总1800秒、ROOT外层1850秒。ROOT逐步显式调度sealed adapter并约束全局时限，不因命令数累加而延长；超时停止后续。42条命令为含正常/失败分支的白名单，不是全部无条件执行。每步exclusive started禁止重试；SSH client回收不等于远端或PG闭合。

## 失败收尾与回退

版本、身份、路径、锁、资格、超时或关闭证明不符，停止后续计数。仅按封存恢复输入处理本operation的实际已知对象：ledger记录的dev/inode/owner/mode/bytes/SHA必须一致，actor必须已停止，未知文件/缺ledger/未登记中断/state.next保留。仅对已复核完整身份的本方进程执行既定TERM/KILL/reap，不处理他人进程。

数据库恢复仅沿已批准合同，对实际seen的精确 `PID/backend_start/datid/usesysid` 四元组作条件式cancel并独立核gone；不模糊取消、不terminate、不改权限或角色。关闭未知时不得宣称成功或擅自清锁。

若pre已通过、BASE部分安装经限定恢复确认不存在且count尚未启动，可按本包显式 `owner-stop → cleanup_wait → precount-abort → final`：核全部六个真实pre产物及actor/owner/token，保留完整H审计，原owner自行释放本方token，final重新核BASE无及锁确无；结果仍为count未完成、PG闭合未声明。其他未pre合格、post失败、owner过期、未知树等不符合分支的情况保留事实与资源，按已有恢复面处置；不自动finish、按age删锁或扩展恢复范围。

正常回退为清理本次已确认关闭、归属明确的专用暂存，保留H审计及ROOT原始收据；失败时只执行满足条件的同包恢复。业务数据库无写入，故无业务数据恢复动作或新数据库备份；保护面为固定输入、独占暂存、现场身份及原始审计，不以备份替代关闭验证。

迁移0、业务配置/功能开关变化0、业务镜像发布0、服务重建/重启0、生产业务数据写删0。无扩大抓取、付费调用、QQ/邮件外发、自动发布或旧暂停任务恢复。

## 成功的含义

成功仅证明本次固定范围的数字计数和本方资源收尾，fresh仍为0；不是首样本交付、容量通过、F03的45项完成或整版公开验收。结果出来后再据实际分母提出后续方案，不自动放宽预算。10/06 18:00容量节点目前仍有风险，后续观察窗口与质量线不变。

## 本次重新绑定原因

固定H和manifest已变化，依据根AGENTS.md“PR、commit、manifest、目标环境或发布包与获准版本不一致”须针对本包确认。可选A暂不执行，或B批准本页新manifest的一次只读计数及完整准备、验证、收尾和限定恢复。无需重批原PR248合并、A/C本地实现；本包不授予任何额外付费、抓取或第三方发送。
