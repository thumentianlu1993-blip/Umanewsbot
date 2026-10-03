# A007 真实PG测试源码准备（未执行）

方案a2c6005c已原R在8b50d4cdb5650c7157f78b7e19a413627b7992ce批准；新增授权源码server/stable/test_h01_count_postgres.py，原4e86466f四Python逐字节保持。五default TransactionTestCase methods对应已审方案，复用django profile，无skip/opt-in env/manifest。仅当前固定Linux、network-none/非root/无Docker socket、127.0.0.1:5432、bounded_ci管理员及test_bounded_ci接受，其他运行目标失败。

实现：真实迁移19表固定12SQL/日期及新闻边界/UNION去重/分层计数；随机SELECT角色、schema权限与表write权限负例、PUBLIC CREATE保存恢复并核完整有效ACL；RR snapshot后的另连接已提交修改；schema已提交可逆RENAME→reader新RR精确schema_mismatch/selects1无其他SELECT→finally恢复commit/独立19表列核对；未提交ACCESS EXCLUSIVE单列lock_timeout、真实statement_timeout错误码；实际main摘要绑定入口调用与阻塞query/driver；独立observer进程fork后新建libpq，实查backend/role/db/query活动与锁，再观察query结束、同PID消失/锁释放；未commit诊断事务强制终止后原值恢复，对照主动rollback。父进程fork前关闭Django连接，不共享libpq。异常后台遗留需管理员terminate时仍判FAIL，不把收尾成功当通过。

当前静态AST解析PASS、5method、无skip decorator、git diff --check PASS；实际Django runtime collect与PG均未执行，也未重跑32既有有效测试。私有静态证据 /Users/mentianlu/.codex/runtime/a007-h01-source-preparation/static-evidence.json；5个预期IDs与新path/domain/profile见A-007-mapping-proposal.md，root负责共享mapping及正式影响计划。源码SHA：1b8661bd7e90e71b8182d25a113057e70f587107a827b17445434f40ccb82c79

预算执行提案：复用既有镜像sha256:fcf8cdaf63af51b1b8a6e30e3d2fdf871d127c3c1461bfd00c9fc6d610eab905（曾用于本线固定Linux开发专项，PG依赖实际仍需窗口核对），single-combo network none、2CPU/2GiB、非root/read-only source archive，tmpfs中真实迁移与synthetic DB，无宿主端口/凭据/生产挂载。root可指定更近的已核受信镜像并重新绑定执行包；不得临时pull/build。整窗15分钟含迁移/清理，五例90秒预算（每例15秒事后断言，observer8秒、接收与回收有界；外层须为整批施加实际执行超时），无并发。reader原120秒/5秒上限不扩大，故障例缩至400ms/1.5秒并明确实际值；终止后的3秒observer是证明窗口，不增加DB执行预算。角色/observer/worker/连接/ACL恢复失败均FAIL，最后既有entrypoint停PG并--rm容器。

准备包不是GREEN或正式收据；无行为实现变更，不虚构RED。实际PG首次失败若来自环境/迁移/fixture，先精确归类，不能冒充业务RED；若真实行为缺口需要原4文件返修，先保存最小失败证据交root/原R判断。未运行容器/生产SQL/full/来源采集、未合并发布。下一步原R源码审核及root映射/准确collect就绪后，申请B后窗口执行五PG methods。
