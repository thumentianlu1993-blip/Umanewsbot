# A007 真实PG测试源码准备（未执行）

方案a2c6005c已原R在8b50d4cdb5650c7157f78b7e19a413627b7992ce批准；新增授权源码server/stable/test_h01_count_postgres.py，原4e86466f四Python逐字节保持。五default TransactionTestCase methods对应已审方案，复用django profile，无skip/opt-in env/manifest。仅当前固定Linux、network-none/非root/无Docker socket、127.0.0.1:5432、bounded_ci管理员及test_bounded_ci接受，其他运行目标失败。

实现：真实迁移19表固定12SQL/日期及新闻边界/UNION去重/分层计数；随机SELECT角色、schema权限与表write权限负例、PUBLIC CREATE保存恢复并核完整有效ACL；RR snapshot后的另连接已提交修改；schema已提交可逆RENAME→reader新RR精确schema_mismatch/selects1无其他SELECT→finally恢复commit/独立19表列核对；未提交ACCESS EXCLUSIVE单列lock_timeout、真实statement_timeout错误码；实际main摘要绑定入口调用与阻塞query/driver；独立observer进程fork后新建libpq，实查backend/role/db/query活动与锁，再观察query结束、同PID消失/锁释放；未commit诊断事务强制终止后原值恢复，对照主动rollback。父进程fork前关闭Django连接，不共享libpq。异常后台遗留需管理员terminate时仍判FAIL，不把收尾成功当通过。

当前静态AST解析PASS、5method、无skip decorator、git diff --check PASS；实际Django runtime collect与PG均未执行，也未重跑32既有有效测试。私有静态证据 /Users/mentianlu/.codex/runtime/a007-h01-source-preparation/static-evidence.json；5个预期IDs与新path/domain/profile见A-007-mapping-proposal.md，root负责共享mapping及正式影响计划。首轮f26准备源码SHA：1b8661bd7e90e71b8182d25a113057e70f587107a827b17445434f40ccb82c79

预算执行提案：复用既有镜像sha256:fcf8cdaf63af51b1b8a6e30e3d2fdf871d127c3c1461bfd00c9fc6d610eab905（曾用于本线固定Linux开发专项，PG依赖实际仍需窗口核对），single-combo network none、2CPU/2GiB、非root/read-only source archive，tmpfs中真实迁移与synthetic DB，无宿主端口/凭据/生产挂载。root可指定更近的已核受信镜像并重新绑定执行包；不得临时pull/build。整窗15分钟含迁移/清理，五例90秒预算（每例15秒事后断言，observer8秒、接收与回收有界；外层须为整批施加实际执行超时），无并发。reader原120秒/5秒上限不扩大，故障例缩至400ms/1.5秒并明确实际值；终止后的3秒observer是证明窗口，不增加DB执行预算。角色/observer/worker/连接/ACL恢复失败均FAIL，最后既有entrypoint停PG并--rm容器。

准备包不是GREEN或正式收据；无行为实现变更，不虚构RED。实际PG首次失败若来自环境/迁移/fixture，先精确归类，不能冒充业务RED；若真实行为缺口需要原4文件返修，先保存最小失败证据交root/原R判断。未运行容器/生产SQL/full/来源采集、未合并发布。下一步原R源码审核及root映射/准确collect就绪后，申请B后窗口执行五PG methods。

## 原R提前P2：回滚因果checker返修（PG仍未执行）

首轮管理员诊断statement/idle=1000ms早于1.5秒父期限，确实可能自然超时先回滚而误通过。现改为客户端阻塞/idle未提交事务：管理员UPDATE确认rowcount1后等待独立observer Event，然后仅客户端sleep；两个诊断server timeout均10000ms，晚于2秒父kill，不改readonly reader或120秒合同。observer核同PID/db/role的idle事务、最后UPDATE标记、目标表RowExclusive锁，并以另连接FOR UPDATE NOWAIT失败证明精确synthetic行锁、旧已提交值不变；在予定kill前200ms内重新确认后才设置barrier。父进程记录实际worker.kill调用时点/client PID/barrier状态；checker用实际kill时点，要求近kill前屏障与同PID、事务结束和backend消失均不早于kill，之后锁0/新事务旧值恢复。提前rollback、提前消失、缺屏障/错PID均拒绝。CLI active-query检查单独保持原路径，不混成管理员idle事务。

纯AST提取实际_check_observation的最小checker测试（无Django/PG import）得到真实RED：首轮允许上述4种坏证据，5例中4失败；返修后同5例GREEN。证据 /Users/mentianlu/.codex/runtime/a007-rollback-causality/check_observation.py、checker-red.log、checker-green-final.log。此GREEN仅证明checker判定，绝不证明PG屏障/断连回滚已执行。AST五默认PG methods保持，原4已审字节保持，diff检查通过。当前harness SHA256：4a8b17cbc8c6ed25b5d0157645cb41d7e1453c728f570b18914c4a9670b7a232。首轮f26准备包不修改；新固定包等待原R全部finding及复审，无PG容器执行。
