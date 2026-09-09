# 历史迁移测试隔离

## 根因与范围

PR #188 候选 `61afbf59` 的 [Linux/PG16 全量结果](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/34329843286)
有 28 条 `IrreversibleError` 记录，涉及 5 个模块、16 个测试，部分同时在测试和 teardown 报错。
它们尝试把测试运行器准备好的 0078 数据库退回旧状态；若干 teardown 还只恢复到旧 leaf。
0078 保留 provider profile snapshot 的不可逆保护是预期行为，不能为了旧测试放开。

本修复只改变六个历史迁移测试类的数据库准备方式。它们通过一个测试专用 context 使用新连接：
PostgreSQL 创建本次测试专属随机 schema，并在连接选项中固定无 public fallback 的 search_path；
SQLite 使用独立内存库。auth/contenttypes 等依赖先真实迁移，stable 从空白状态由各测试自行迁移。
不使用 fake migration、不改 MigrationRecorder 记录、不替换或修改 0078，也不删旧迁移断言。
正常退出、测试失败或 bootstrap 失败后恢复原连接，只删除本次成功创建的 schema／内存库。
现有测试不在子线程使用此 context；它只替换调用线程的 default 连接。

## 已有验证与后续验收

- 以 AST 核对 5 个修改模块，所有既有 `test_*` 函数体及断言保持原样。
- 新增隔离回归验证：真实执行旧迁移后原测试库的表和迁移记录不变，bootstrap 异常恢复原连接；
  PostgreSQL 还核验新连接重连后仍进入私有 schema，清理后该 schema 不存在。
- Windows/SQLite 的两项隔离回归与三项原历史迁移回归共 5 项通过（90.199 秒）。
  原始 Linux RED、完整本机日志分别保留在 `runtime/diagnose-migration-test-fixtures/` 和
  `runtime/fix-historical-migration-test-isolation/`。PostgreSQL schema 与其他旧 PG 测试仍须 CI 验证。
- 交付前核对固定候选的 Linux/PostgreSQL 16 全量失败集合及独立只读审核。错误越过 setup
  后若继续暴露旧合同或应用缺陷，必须保留真实结果，不能把准备阶段修好等同于所有测试通过。

生产数据库、迁移文件、服务、配置和业务数据均不变。人工交付边界统一见根 `AGENTS.md`。
