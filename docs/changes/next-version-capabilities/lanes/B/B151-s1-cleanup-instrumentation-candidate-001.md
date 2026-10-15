# B151 — S1 owner/close/observer 仪表候选

状态：`INSTRUMENTATION_CANDIDATE_ONLY_PENDING_ORIGINAL_R_REVIEW`。没有导入候选、运行测试/collect、PG/DB、CI、容器或网络；没有关闭 B149 四项 cleanup blocker，也没有根因结论。只基于固定 `0b12a857c0ed10a7244401e5494f04d0733b082b` / tree `28819ddec2ac7be610cd19cc4214cf51e8818350` 修改测试 helper 与本说明，不叠 B150/O02，不改应用、PG14、catalog、CI 或 C163。

全文输入为 C162 `a32296c6387db42108e890614349c58b83d05fa8` 的 diagnosis/source-facts，以及原 R `7b1a33fccf1e14b17e1a5dae9319106d4569ac6a` 报告（SHA256 `08dfa3d1b7ac80519f3eacff5e5435389f690cb5ec720505976a11a2c98be0be`）。C162 receipt `dd32576e541f8e9ed5be267fbcd2d22297add659253c708e1a71ccc6357e17d0`、13-member seal `7c09c99988794eaef5cb3f08aa931735e611e85a080858c8c8702dd558588999` 与 R receipt `ea6b80aa8f21cb9838ecc37e974fd9a9fa2fcbfec342b01c5ccae14a121d926a`、6-member seal `4ac5360992d9602552adce153c7c01b28c5d1798722009f01391b83daa618557` 静态核验。

## 目的与保留面

原 constraint 失败 PID88/96/108 与 worker PID114 的服务端 absence 未在首次检查成立；114 的后次成功不改原 FAIL。两个 helper 已有 clear snapshot。本候选为下一次标准 CI 取得时序事实，不实现轮询、不追加 sleep/kill，不以 local closed 替代 backend absence，不预认连接池或服务端退出延迟为根因。

39 个 AST test IDs 与各方法原字节保持不变；`sqlstate()` 分类函数及所有其他原 helper 保持不变。只有 `constraint`、`worker` 的 owner-close 观测点、`finish_worker` 与新增诊断 helper 改动。原业务断言、CHECK DROP/catalog absence、local None/closed、一次 PID 查询/absence、原 clear 顺序和数量、join15s/ready5s、statement10s/lock2s 及其他原预算常量保留。新增查询仍受原 statement timeout 约束，没有另行延长预算。新增诊断本身会消耗现有 worker join/ready 窗口，属于未运行的兼容风险。

## 精确局部设计

1. **目标身份来自原有 owner cursor。** worker 在原 set_config 之后、action 之前采集；constraint 在原 cleanup SET timeout 之后、DROP 之前采集。只查询当前 owner PID，保存 PID/backend_start/datname/usename/application_name/backend_type 与 state/wait_event_type/wait_event/xact_start。保留该 owner 本地 driver 引用直到 close，但不把它放入共享字典；close 前核对仍为同一 driver，避免把开过新连接的 wrapper 冒充原身份。身份不是 close 瞬间的新服务器采样，事件时间明确保留。
2. **close 前后只取白名单本地状态。** 直接读取 wrapper 已有 `__dict__` 的 alias、线程、autocommit/in_atomic/needs_rollback/closed_in_transaction、connection 是否 None；读取保存 driver 的本地 closed 标志；pool 仅记录 settings OPTIONS.pool 的布尔启用状态，不读取 `.pool` 属性。记录 close_start/close_end 单调时间、close 是否正常返回及错误身份。成功 close 时不把上层仍活跃的 body 异常误标为 close_error。
3. **observer 只用原有连接与 cursor。** 在原 clear 后、原 SELECT pid 前，额外查询 `pid=target OR pid=pg_backend_pid()` 的身份/状态白名单，不查询 SQL 文本或其他会话。要求已有连接、同 owner 线程、autocommit 且不在 atomic/needs_rollback；不安全则诊断 ERROR，原 SQL/断言继续原路径。只记录同轮实际 rows 与时刻；身份漂移为 ERROR，不过滤成空行。原 PID 查询和原 absence 断言仍执行，没有 polling 或额外 clear。
4. **记录实际业务 CHECK 错误，保持原分类。** constraint 仅在 yield 期间增加局部 execute_wrapper，透明调用原 execute，异常时记录 cause/context 链的类型、SQLSTATE、driver constraint_name 与函数/行号后 bare raise。既不读取/输出 SQL 或 params，也不改 `sqlstate()`、23514/55P03 分类、测试 body 或异常对象。
5. **线程边界。** worker 在自己线程中调用本地状态与 owner 查询；新增 `cleanup_diagnostic` 仅含 JSON 兼容数据。主线程等待原 join 后才使用 observer；不从主线程访问 worker wrapper/driver。原 facts.errors 传递原异常的既有行为保持不变。

## 诊断失败如何不替换原异常

每个记录在主线程预先注册一个 unittest cleanup。`_cleanup_diagnostic_step` 的 action、字段读取及 JSON 检查中的异常不会直接越过 owner finally，而是立即保存独立 errors 项（phase、异常类型、SQLSTATE/constraint_name、最多8层 cause/context、每层最多16帧函数/行号）；不保存消息、args、SQL、params、异常/traceback 对象。格式化失败也记录原错误类型及 formatter 错误类型。包括诊断自己的 BaseException 都走这个显式延后 ERROR 路径，确保不会凭诊断中断而跳过原 close；不是静默 best-effort。

原 close/close_all 在原 finally 中执行；新增 close_end 位于其内层 finally，原 close 异常继续传播。SQL 透明 wrapper bare raise 原异常。最后注册的 cleanup 输出 `B151_CLEANUP_DIAGNOSTIC` JSON；只要有诊断 errors，强制独立 `RuntimeError`，由 unittest 记为 ERROR，不能变成业务 FAIL/PASS。这样原 body 或原 helper 的 FAIL/ERROR 与新增诊断 ERROR 可以同时报告，不以仪表异常覆盖原终态。跨线程不重抛诊断原对象，因此该独立 ERROR 的 traceback 是报账处，原诊断错误来源只保留白名单结构化帧；此限界须由原 R 审核。

输出失败本身也作为 cleanup ERROR；errors 已存在时 finally 仍强制报账，输出错误保留在其异常上下文。不声称异常内存耗尽、进程被强杀或还未 join 的失控 worker 可可靠落盘；本轮没有新增资源处理或超时恢复策略。

## 静态核验与待审风险

只使用 AST/JSON/hash、Git 引用与 diff check；精确 diff、原39方法逐段 hash/AST、原 helper 调用/断言/clear/预算保留、七个源 pin、输入 seal 和依赖静态参考记录在独立 runtime `b151-s1-approved-cleanup-instrumentation-candidate-001`。用户指定的候选范围优先于技能中的 TDD 执行、额外工作流和代理建议；只交当前字节给原 R，不代签 review 或执行。

新增 SQL、CursorWrapper.db、wrapper.__dict__、psycopg closed 与本地安装 Django5.2.1/psycopg3.2.6 源可静态对照，但不是 CI 运行兼容性证明。额外 pg_stat_activity 查询会扰动时序并先于原 PID 查询形成观察快照；任何后续 PASS 都不能反推原失败无害。owner 身份在 action/DROP 前采集，close 前用同一 driver 绑定；不能称 close 前瞬间服务端状态。新增诊断错误保留策略、局部 execute_wrapper 对异常链的透明性、线程未退出时 JSON 记录完整性，均需原 R 看具体字节；没有 runtime 验证。

下一步仅原 R 代码审，再由 ROOT 排唯一标准 CI 观察。原 B149 的21 FAIL（17 body/4 cleanup）、18 PASS、原 ZIP/receipt/seal 保留；S1整体、G159-01/02、全局 cleanup/fulltrusted 等仍开放。没有修复轮询、业务实现或发布动作。
