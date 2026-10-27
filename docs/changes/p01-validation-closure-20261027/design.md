# 全仓验证收尾设计

## 日志根因与修复

本机隔离诊断在固定3f21f41f重现约4.2MiB PG日志，其中一条约4.19MiB的INSERT源于 `HorseArticlePairReceiptIndexTests.test_positive_ID_hash_and_byte_checks_reject_actual_bad_INSERTs`。该用例有意构造MAX_BYTES+1值，DB正确拒绝后记录完整SQL。将Python端巨型literal换成SQL `repeat('x', MAX_BYTES+1)` 表达式，DB仍实际处理相同超限值，原SQLSTATE/constraint/零写断言不变。PG LOG_LIMIT=512KiB、完整日志保存及失败规则不变。诊断脚本因未注入部分旧用例所需源码SHA有9项额外失败，仅用于日志定位，不算业务测试通过。

## 真实缓存

保留已有三份资源的摘要、来源、descriptor和重定位验证，不修改缓存字节。新增按精确native ID分配的三个Django缓存profile；最长精确匹配优先于模块默认profile，canonical ID去重不变。每批只能包含对应冻结组的非空子集。资源加载在envclear和源码绑定核验之后，以固定/source只读输入验证，不接受宿主缓存路径；收集阶段不启用缓存、不访问外网。

原targeted exact3/exact2准入API保持不变，抽出资源内容核验供新profile调用。对应组3+2+3合计8个原native ID只改变执行前提，原测试断言不改。普通full计划中自动选用这些profile；不把full伪装为targeted。

## root文件权限合同

仅原精确native ID `stable.test_race_live_gate_remediation.RollbackGateBehaviorRemediationTests.test_root_artifact_is_exact_0700_0600_secret_free_and_no_replace` 分配 `django-root-artifact` profile。保留原真实ORM、bundle生成、0700/0600、uid/gid=0、秘密扫描和禁止覆盖断言；其他同类用例仍非root。

宿主执行器为该批创建独立 network-none 容器，根文件系统只读、source/control只读、无Docker socket/宿主凭据、pids/CPU/memory/tmpfs和deadline仍有界。容器以0:0运行supervisor/worker，只授予SETUID、SETGID、KILL，使PG及其控制工具以10001:10001运行，并可在失败时终止子进程。PG不以root启动；不授予SYS_ADMIN/NET_ADMIN、不使用privileged或host网络。普通profile继续uid/gid10001且cap-drop ALL。

entrypoint、request、batch、worker隔离检查及receipt核验均拒绝root profile混入其他ID或普通profile以root执行；PG子进程退出和stop回执规则保持。root范围只到这个本地容器，不是宿主或生产root。

## 真实镜像合同

原镜像测试内直接调用docker与普通无daemon测试容器矛盾。将建镜像/读镜像的准备步骤移到宿主执行器的固定准备阶段，复用原固定源码SHA/tree/5个字节pin、私有archive上下文、镜像digest/OCI revision/运行时marker和唯一audit文件检查。辅助模块只用标准库，测试和准备阶段共用严格校验函数；不放宽任何旧pin。

准备阶段只操作本地daemon及自己创建的镜像，构建依赖下载属于准备，实际镜像读取network none。输出有界JSON证据绑定当前test_sha/tree、合同版本/固定原始源码、image ID、inspect和镜像内读取值。文件hash进入计划，证据以只读专用挂载进入普通非root测试容器；worker先核字节hash与来源绑定，原native测试验证完整真实镜像结果，缺失/伪造/漂移失败。普通测试始终无daemon。批次重入只读已绑定证据，不重复构建；独立重收集不把材料当执行结果。

正式收据仍逐批绑定当前执行计划和SHA，不拼接旧通过结果。最终移除已闭合10项skip豁免，执行全量并核验；如新执行条件存在问题，保留失败记录后修复。

## 首轮代码审核返修

21d7f17b 的独立审核提出 C1–C7，均属执行器技术合同：贯通 serial CI/候选外验证的原始镜像proof及collection输入摘要；PID文件检查由有界10001子进程执行；源码复制不保留宿主所有权；准备进程接入OwnedObserver预算与reader精确CID登记；普通collect-only无镜像动作，初次CI显式使用prepare-images；恢复旧exact3 API并验证三份资源；兼容旧server-only入口。受限root能力仍为0xe0，不增加DAC/CHOWN能力。

镜像构建增加随机操作所有权label，避免并发相同构建误删他人镜像；只删除本操作新建的精确image ID。reader失败和清理失败均保留主异常，仍尝试镜像清理；不以缓存、模拟receipt或collection代替原native执行。

## 最终清理合同返修

C8只兼容实际Docker精确返回的 `no such object` 小写文案，完整目标ID、退出码1和空stdout约束保留；额外错误、错误ID、权限或daemon错误均不能当作已清理。C9让无OwnedObserver的准备入口也使用共同的精确容器名称清理函数和既有deadline；不追加重试时间或清理无关资源。
