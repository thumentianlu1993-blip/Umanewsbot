# 设计

在 annotate_public_time 返回的克隆 Query 上使用专用 Query/SQLCompiler，仅 PostgreSQL SELECT 使用。不替换数据库 backend、不 monkeypatch Django、不使用执行期字符串替换。

专用 compiler 在 SQL 编译时建立 ContextVar 作用域；_PublicInstant 注册所需目录并引用固定保留别名。最外层专用 compiler 在 SQL 前添加 WITH ... AS MATERIALIZED (SELECT name FROM pg_timezone_names)。嵌套专用 compiler 复用同一编译作用域；finally 恢复上下文。参数顺序不变，SQL 主体由 Django 原编译器生成。没有时间表达式时不添加目录。未进入专用 SELECT compiler 的表达式维持原始 SQL，避免更新/聚合等其他编译器引用未定义 CTE。

Query 克隆保留子类；count/exists/聚合/切片/union/嵌套 Subquery 在测试中真实执行。外层为普通 Query 的独立子查询分别拥有自己的局部 CTE，不改全局编译器；当前公开调用点须验证不存在因此重复目录的形状。SQLite 沿用原 UDF。

仍使用数据库同一份时区名称与 AT TIME ZONE；不硬编码地区集合、不用 Python tzdata 代替 PostgreSQL。不改任何 WHEN 条件。无迁移、配置、数据写入或新依赖。
