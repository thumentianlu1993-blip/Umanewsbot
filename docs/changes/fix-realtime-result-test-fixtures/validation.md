# 实时赛果测试夹具校正

## 范围与原因

只修改 `server/stable/test_realtime_race_results.py`。旧测试存在四处与现有合同不一致：

- Runner 测试的起始时间固定为 2026-07-20，但未提供默认请求后时钟，真实日期使夹具租约过期。
  helper 默认注入同一夹具时间；显式时钟仍优先，网络期间过期、claim 被替换等负向用例保持原样。
- 赛前赛卡用例通过 `QuerySet.update` 写入受保护的 `local_date`；改用模型 `save`，继续执行身份校验。
- 同一正向赛卡用例未打开共享字段准入；只为该方法授予 TRA、UK 和四个参赛者字段，不授予赛时字段。
- 生产 Compose 已使用可配置的持久 runtime 根；按各 Compose 文件核对对应路径，仍要求 secrets 只读、
  racecards 可写，且普通应用不能获得这些挂载。

应用、Compose、默认开关、权限检查和原结果断言不变；没有删测试或增加跳过。

## 验证记录

2026-09-10：既有 Linux/PostgreSQL CI 组合候选 `9ebdf65762a7ebdd0d1789f437b6733eb4dd92bc`
在这些路径有 12 条失败/错误记录，涉及 7 个逻辑测试。本修复尚未运行 Linux/PostgreSQL CI。

本机为 Windows，原测试直接运行还会遇到生产密钥读取器依赖的 POSIX `os.getuid` 不可用。
辅助验证仅在仓库外的 runner 替换密钥读取入口，严格核对固定的测试凭据文件内容；使用隔离 SQLite，
禁用真实网络、禁用 `.env` 加载，并启用 Python UTF-8 模式。此验证不覆盖 POSIX 权限或 PostgreSQL 语义。

- 有效 RED：原两类共 25 项辅助测试，11 条失败记录、1 条错误记录（含参数子用例）。
- GREEN：原两类加既有默认关闭零写入用例，共 26 项通过、零跳过，耗时 1.230 秒。
- 原网络中途租约过期、claim 替换、分页时限及默认关闭零写入检查通过。
- AST 对比确认仅三个原方法改变：部署挂载测试、Runner `_run` helper、赛前赛卡正向测试；
  其他测试与 helper 方法保持原样。
- `git diff --check` 通过。工作流检查仍报基线中的五处旧引用，配套四项测试为三项通过、一项错误；
  不涉及本次修改。正式指纹因 Windows 缺少 `O_NOFOLLOW` 拒绝运行，使用完整文件字节快照作补充，
  不将其等同于 Linux 原生指纹。

原始日志保存在本机专用 runtime 目录。Linux 密钥权限与完整 PostgreSQL CI 必须另行验证；
本记录不表示全量测试通过或已发布。交付遵循根 `AGENTS.md`，不包含生产操作。
