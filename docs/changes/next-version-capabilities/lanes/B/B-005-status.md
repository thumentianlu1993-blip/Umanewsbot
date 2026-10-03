# B-005 / F02 本地实现与短窗口申请

日期：2026-10-03，Asia/Shanghai。阶段：本地候选，原R代码review及真PG/Docker验证待进行。
承接原R1485deea对1e36c9af的方案APPROVED；本次固定SHA由阶段消息绑定。人工门禁仍仅引用根AGENTS.md。

## 已完成（本地）

- argv Runner用实际Popen新session、非阻塞有界stdout/stderr、主预算+TERM/KILL/wait；本地Python忽略TERM的父/孙进程实际被回收，洪泛不会deadlock或输出原文。
- DockerAdapter不在constructor调用Docker，固定Unix socket/absolute binary/container/image/revision/source path，合并实际inspect与probe字段；daemon未知与确认missing分开。pending helper先落私有控制文件，重启后仍阻止copy；secondary helper本身未知时保存两operation并隔离，不自动猜停。
- standalone Linux probe从实际私有文件核script/marker/manifest/UID，绑定self SHA与路径；wall timer覆盖读取/控制记录，PID/start ticks/argv/op-id防复用。此Linux生命周期尚未真Docker验证；本地PID重用反例是parser/fake测试，不能称container helper已被现场回收。
- 不可变tool包从固定Git对象构建，精确六模块+空init+entry；bootstrap标准库先核所有文件与0600/0700/SHA/3.12，再导入私有scripts，-I/-B避免环境或pycache污染。当前没有安装主机运行时。
- Root/R bridge只接受受信reader的精确thread/turn/message/payload承诺和实际收包标记，再核host包；仅内存短时HMAC桥接，独立R.source/R.received、幂等不重新发key，无长期账号/密钥/CLI身份入口。真实trusted reader仍需root现有调用面绑定；本地合成来源不声称真正R收包。
- PG driver与静态typed DDL已写：六表+django_migrations、专用manifest/源码/DDL/hash/目标名保护；连接后先核PG16/独立control guard nonce，reader角色仅SELECT，admin角色用于合成DDL和READ ONLY拒写证明。12条PG用例未运行，缺manifest时全部skip。
- 原exporter/verifier字节均与1e36c9af一致；原transfer测试只改catalog实际fixture消费者断言，映射proposal涵盖新路径/SQL fixture/Python profiles、真实fixture消费者在catalog与rules同步。shared rules/catalog、PR235未改。

## RED / GREEN

- Runner正常receipt RED：not_implemented!=ok；GREEN真实进程及回收/洪泛/无shell4项。
- inspect/probe合并 RED：unknown!=complete；pending restart RED：None!=原operation；probe控制目录755 RED：未拒绝；对应GREEN。
- 包 RED：manifest仍not_implemented；GREEN精确文件/hash/权限、缺/extra/links/不覆盖、isolated bootstrap真实子进程。
- R来源 RED：producer错误thread未拒绝；GREEN精确来源、错包/非收包拒绝、实际host包核验/幂等/材料不落文件。
- PG保护 RED：production/空manifest未拒绝；GREEN静态目标保护。PG12 skip不是PG GREEN，也不是SQL RED。
- B005 proposal新增fixture消费者后原单域断言失败；修为真实三域消费者合同，不删映射或测试，root selector既有RED/30例证据独立。
- 最终本地集：原46+新增17=63 PASS，12 PG SKIP，总75项（约2.1秒）；workflow contract PASS、4契约tests PASS、diff check PASS。尚无Linux正式delivery receipt。

## 缓存只读证据与缺件

B独立DOCKER_CONFIG `/Users/mentianlu/.codex/runtime/b005-impact-docker`，仅本机Unix endpoint `unix:///Users/mentianlu/.colima/umanews-impact-ci/docker.sock`；没有改C或全局context，调用清除DOCKER_HOST/DOCKER_CONTEXT。
只读image inspect实核组合镜像ID `sha256:fcf8cdaf63af51b1b8a6e30e3d2fdf871d127c3c1461bfd00c9fc6d610eab905`、linux/arm64；没有启动/创建容器。
root/C时点证据：该同一镜像包含PG16.15、Python3.12.3、Django5.2.1。不是独立PG服务镜像；PG/Python manifest可绑定同一digest，但仍需B窗口实核二进制/版本、进程隔离与guard。
q01 execution-plan/batch log未找到psycopg版本安装收据；requirements只有3.2.6声明，不证明镜像实际安装版本/RECORD digest。依赖receipt是缺件，不能假称已满足。首次专用窗口建议先≤8秒纯版本/依赖RECORD自检；若不是3.2.6或缺package，停止、不联网安装、不启动PG，向root报阻塞。

## 精确短窗口申请（尚未执行）

- fixed candidate SHA与固定tool package manifest SHA由阶段消息绑定；fixture SQL SHA和driver SHA以该Git对象提取重算。完整源包不从可变main/worktree读取。
- run-id `synthetic-b005-v1`；container/hostname `f02-pg-synthetic-b005-v1`；DB `f02_synthetic_b005_v1`；labels包含task=B005、synthetic=true、run-id、candidate SHA与fixture SHA。
- C已释放；申请单批、单组合镜像容器，≤2CPU/896MiB，总≤8分钟（含自检与清理），无暴露端口、独立internal网络、无production env/network/volume/credentials。使用镜像内现有postgres账号，专属临时PGDATA/控制schema；不启动默认业务服务或借既有数据库。
- runtime产物专属 `/Users/mentianlu/.codex/runtime/b005-validation/`，container对应独占/b005路径，tools从固定对象readonly输入；PGDATA为本次自有容器目录，密码/guard nonce只在私有执行manifest或内存，不进argv/stdout/仓库。
- root需固定具体PG/Python binaries、组内运行方式、internal网络/实际mount证明、依赖receipt SHA、总deadline与自己的进程/container回收证据，再下发manifest SHA。root未核定前不启动。
- PG12真实结果、metadata/content host核验与本机synthetic Docker probe/cp/helper退出烟测分层记录；Docker烟测另申请窗口，不能用单元mock代替D09。生产SSH/staging/查询/真实样本一律未进行。

## 仍待完成

原R代码review；镜像内psycopg3.2.6实装/依赖digest、真实短窗口manifest和PG12；Linux helper生命周期与synthetic Docker烟测；真实Root/R接收来源绑定和正式执行包。F02新真实样本仍0/M01未解锁，DDL2026-10-05 18:00 Asia/Shanghai。
最近周剩余2%，每工具批次复核，≤1立即按既定规则保存最小断点并停工；当前无子代理/模型CLI/后台长进程。

## B005 CI-v2 接通实现（2026-10-03 恢复后）

原 R v2 方案 APPROVED / P2 CLOSED@aebe8e2a；固定方案 SHA3994cb9a。仅修改本线测试源码、tests-only helper、B映射提案和测试设计；共享runner/workflow/core/catalog/rules零修改。

- 原 PGGuardTests 1 + PG12 原 IDs 全保留。移除import-time skip，内部模式默认走自包含fixture；collect不准备/连接；外部manifest独立保留原严格validator。proposal改django/profile+dedicated batch，正式整合归root。
- 新 helper `scripts/tests/f02_pg_fixture.py` 在任何连接前核私有PGDATA目录fd/O_NOFOLLOW、tmpfs mountinfo/statfs/device、config权限、actualsocket inode↔postmaster fd/PID/start、四namespace一致与双采样；未知/错项拒绝。bootstrap fixed loopback/postgres/tester，连接后核SQL目标/PG16、后端父PID/namespace，再创建独立DB与非superuser admin/reader及nonce；每次新连接重新核binding。
- 新 `InternalCIGuardTests` 12个ID已报root（此前预报PGGuardTests类名已纠正）。攻击端点、inode owner、PID稳定性、4种namespace、tmpfs、权限/owner、symlink、嵌套mount、propagation、device、未知字段；connect spy零调用。原13+新增12=25。
- RED：12/12失败（class skip True；未实现guard未抛错误）；GREEN：新12+原manifest guard=13 PASS，0.033秒。当前主机默认fixture在Linux前置失败，未调用DB；离线collection 25 unique IDs/12旧PG保留；compile/diff检查PASS。原63和成功v2依赖证据不重复。
- Linux真实socket/mount/PID guard、内部DB权限/部分创建清理和PG12尚未执行；模拟快照不冒称Linux通过。正式full是否通过仍须root整合mapping并取得formal collect/run，无skip/分母缩减。
- 成功准备stdout只输出allowlist `F02_CI_BINDING`：process/source/dependency摘要与nonce hash；密码/原nonce仅私有binding。cleanup先核server/DB OID/owner/guard及角色OID，未知不删除，报告fixture_cleanup_unknown，最终自有容器销毁。
- 下一步固定新SHA提交原R代码review；候选480秒包待root核定与窗口，无PG启动/transport/生产授权。额度恢复实时remaining99%；新检查遵循5分钟/低阈值规则，无子代理/模型CLI/后台任务。

### 原 R P2：创建成功但回执/OID丢失的清理状态

1928代码review发现CREATE ROLE/DB后OID读取失败会误报complete。返修在每次CREATE前落0600/0700、fsync/rename的pending intent journal；可靠角色OID或DB OID+owner确认后才写known并清pending。未知intent存在则cleanup零连接/零DROP，保留私有runtime/journal、标unknown_container_cleanup_required，由自有容器生命周期回收，不按名字恢复/接管。

新增FixtureFailureTests 6精确IDs已报root。RED首次5fail/1已有unknown；强化pending持久证据后6fail（5误complete，1缺intent）。GREEN新6+原13守卫=19PASS（31total/12PG未跑），CREATE之前journal存在、pending与unknown状态落盘、零DROP均证明。测试macOS路径resolve仅mock临时目录，用于私有文件验证；生产Linux helper保留严格/tmp路径，不放宽symlink保护。外部manifest/原13ID/runner不变，旧runtimev1/v2固定包冻结不执行。下一包v3须以新SHA/31IDs重绑。

### v3 首次真实 Linux PG 候选执行与 P08 fixture 参数返修

固定42a92650 / plan a15196bd 的唯一窗口实跑36.033秒，31项全部执行/零skip；30PASS、1ERROR：P08在smallint参数的generate_series重载上遇AmbiguousFunction。batch-0006/00112/0021均PASS，PGbatch003 12执行中11PASS+P08error。actual socket↔postmaster PID/start/fd/inode、四namespace、UID10001/0700/private /tmp tmpfs guard真实通过；fixture cleanup complete、PG stop true、host reaped/container removed true。receipt SHA da0c9c273ec3eb65d06523e68201cfcd523ce78bfb006532cf139c54e2ca2431，位于本机runtime b005-pg-window-v3。不是PG12完整GREEN，不冒称正式full已通过。

最小纯技术修复仅为P08的generate_series两个参数显式::bigint，保留每dataset limit/limit+1及原31 IDs，不改业务SQL/生产代码/validator/权限/runner。真实失败即该缺陷RED，GREEN待新固定包核定后的PG复验；不重复已有19守卫或11PG证据。旧v1/v2/v3均保留，不覆盖收据或盲重跑。
