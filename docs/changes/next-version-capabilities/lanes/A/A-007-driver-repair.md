# A007 项目驱动合同返修

root 在首次真实窗口失败后明确批准纯技术返修：使用项目已声明的 `psycopg[binary]==3.2.6`，不补第二套驱动，不改 requirements、镜像、映射与资源边界。

## 真实失败与修正

固定集成 `6c6280b977dd97fd190c2afa69978462901b7ff4`、镜像 `fcf8cdaf`、执行包 manifest `81f50257` 的 collect 在 2.652 秒失败：PG harness 导入 `psycopg2`，固定镜像没有该模块。CLI 真连接路径也错误依赖 psycopg2。该轮没有成功 collect 或执行五项测试；原包与失败收据保留在宿主私有 runtime，guest PG/worker 已停止，owned 容器删除并由成功空查询确认。

本次修改仅为 reader、reader 单元测试、PG harness 及本 lane 文档。原“四 Python 冻结”约束由 root 这次明确技术返修授权局部替代；库存 planner 与其测试不变。SQL 模板、19 表 schema 合同、只读角色、独立观察者、deadline、kill 屏障和回滚因果断言保持。

- CLI 真连接使用 psycopg3；首个 SQL 前依次设置 autocommit=False、read_only=True、IsolationLevel.REPEATABLE_READ。设置失败仍 rollback/close、脱敏 partial，不执行 SELECT。
- harness 使用 psycopg3 的 SQLSTATE、info.backend_pid、make_conninfo 与 connect(cursor_factory=...)；真实阻塞 cursor 仍执行 pg_sleep(10)，并保留客户端阻塞以验证父进程期限。
- 不改变 120 秒 reader 合同、五项默认 PG method、单次 2 CPU/2 GiB/900 秒监督包资源与 network-none 边界。

## 本轮证据

使用现有宿主项目虚拟环境的 psycopg 3.2.6，所有本轮开发测试均无数据库/网络连接。

1. 新增两项驱动行为测试：旧实现返回 connection_failed/partial，真实 RED 为 2 failures；返修后同两项 GREEN。最终相同测试也对旧固定 reader 重放，仍 2 failures。
2. 受影响 reader 类 13 项通过，包含驱动设置阻塞、CLI 父进程终止、只读/schema/事务、期限/截断与脱敏清理。未重跑库存 planner 或旧 32 项合集/full。
3. 私有 AST 提取实际 harness 三个类，基于真实 psycopg3 接口做三项无 PG 检查：事务设置与 backend PID 转发、57014 SQLSTATE、实际阻塞 cursor 保留 PG sleep 与客户端阻塞，均通过。这不是 Django collect 或 PG 五项 GREEN。
4. 源码解析、SQL/schema 模板与旧 reader 对比不变、git diff --check 通过。

私有证据目录：`/Users/mentianlu/.codex/runtime/a007-psycopg3-repair/`；包含 red.log、red-final-tests-baseline.log、green.log、reader-regression.log、check_harness_driver.py、harness-driver-check.log、evidence.json。

## 交付边界

固定源码提交交 root 转原 R 的 A007 上下文复审。root 在复审后生成后续集成 SHA 与新执行包，再单独分配真实 collect/run 五项窗口。首次 6c 故障绑定和原包不覆盖；当前 PG5 仍未验证。无生产、合并、发布或外部业务发送动作。

驱动接口核对依据：项目本地 psycopg 3.2.6 源码，以及 [官方连接接口说明](https://www.psycopg.org/psycopg3/docs/api/connections.html)。
