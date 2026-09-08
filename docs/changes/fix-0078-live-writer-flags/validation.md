# 0078 生产开关兼容修正验证

## 已验证的生产实现

提交 `70d6bccf55553a9bd30f3b2887a9177b31e278c7`，tree `aab6850b919dcaa2d026d8be73add368e72d0c4d`；相对已合并 PR #181 的补丁由主 agent 实现，测试由独立 agent 编写。没有新增 migration 或业务功能。

- Windows 首条 schema 控制环境测试实测 RED→GREEN：宿主十项 true 保持，实际传给 one-shot 的十四项开关全部 false。Python/嵌入脚本解析、Shell 语法和 `git diff --check` 通过。
- 原生只读 reviewer 复用原上下文 `01a07b1d-7de0-7d10-a1a2-505f62a51bc2`，审查八文件差量及直接调用路径，无 actionable findings。额外定向检查 140 种 Compose/实际容器开关漂移、首次和部分恢复、两种 shell 参数构造；前后固定 HEAD/tree、工作树 clean。
- [CI run 34179340979](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/34179340979)，release-contract job `101915043103`：Ubuntu 24.04、Python 3.12.14、PostgreSQL 16.15，45/45，478.535 秒，零跳过。Django check 无问题、makemigrations --check 无变化。
- 独立 agent 下载并复核专项 artifact `10038508836`，SHA256 `1f7f1fddd24c61afbaca628a2cae7bbdc2f11d70f747ace95f070865b7a4c40c` 与 GitHub digest 一致，commit 精确匹配。Linux 原生前后 fingerprint 字节相同，内部值 `e7044166f4236f68560f67e6daba922d1fe3a3fbb2a8357d147f34f5a21fad87`。

## 全量对照的实际结果

同 run 固定基线 `a88bcbf6`：4886 项、68 failures、258 errors、15 skips；候选 `70d6bccf`：4931 项、31 failures、257 errors、20 skips。候选 274 个唯一失败 ID 与上一已验证候选 `966e3455` 完全相同，新增和减少均为零。

本轮 comparison job **失败**：唯一相对本轮基线新增的 ID 是 `PerformanceBaselineTest.test_100_article_dry_run_within_10_seconds`。候选本轮 14.692740 秒，上轮 `966e3455` 为 13.714987 秒，均超过既有 10 秒阈值；本轮旧基线恰好通过，因此相同旧问题被差集列为新增。未修改、跳过该测试，也未为追求绿色反复运行完整套件。

性能测试、`term_consistency.py`、models/settings 和 requirements 均未被本补丁修改。该性能类继承 Django TestCase，新增六项继承 unittest.TestCase；实际 DiscoverRunner 默认按 TestCase、SimpleTestCase、其余分组，未使用 shuffle/reverse，因此该性能测试先于新增发布测试。此结论来自 runner 源码与类继承，verbosity=1 的日志不提供逐项时间线。

候选 artifact `10038868300` 的 SHA256 为 `bfd3779c0df3dba8a1cfa316dad6febf836feebeb637837220ae480c16f90ad2`；comparison job `101919719730` 保持真实失败状态。

逐原因核验还发现旧 `SupportedDeployOneOffInventoryTests` 的静态扫描器只能识别 wrapper 与 `run` 同行，漏认了本补丁合法的 `set -- "$@" run --rm --no-deps` 后调用 wrapper 的形式。对此仅修正测试内识别逻辑并补正负 fixture，不改预期入口集合，不清理四项原有 inventory 差异。新增真实测试方法通过 AST 提取执行取得 RED→GREEN：直接/构造调用两个正例，以及未调用、echo、注释、未传 `$@`、非追加 set 重置五个负例。真实 deploy 目录扫描恢复为与 `51c0cf` 相同的九个入口，无新增或遗漏，原四项 extra 保留。

扫描器修正和文档回写不改变 `70d6bccf` 的生产实现或六项新发布测试；增量独立复审与最终提交记录见 PR #182。Windows 完整 Django 导入受既有 Linux 专用 `fcntl` 依赖限制，未声称在 Windows 跑过整个测试模块。

工作流合同 checker/test 在原版本和候选均失败：五份既有历史文档残留 legacy token。该问题不是 Windows 专属，也不是本次新增。

## 验证边界

新增 host 场景执行实际 preflight、宿主 release-task、容器 release shell 和 coordinator；Docker/Compose/Git/Django/数据库边界为明确替身，按照实际 `run -e` 生效方式保存控制环境，并独立保存容器 Env。真实 PG 场景执行实际管理命令、迁移和备份恢复，未模拟数据库；不把这些结果称为真实生产 Docker 全流程验证。

生产只读核验确认当前 0078、实际十项 true、候选 Compose 解析一致、`.env` SHA 未变及网站四个入口 200。尚未构建或运行生产候选镜像、创建本发布备份、停服或执行发布。SSH 私钥和生产配置未写入仓库或输出。
