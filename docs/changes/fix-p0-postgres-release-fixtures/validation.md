# P0 PostgreSQL 业务测试发布夹具修复

## 范围与根因

基于 main `ced88882152729c8e31a9cddb5fd83094e30d196`。五个 PostgreSQL
锁、并发与回滚用例仍直接信任旧 v1 manifest，在进入目标数据库操作前被当前
`legacy v1 release is read-only and cannot be committed` 规则拒绝。
原始 CI 失败证据保存在本机 `runtime/fix-p0-postgres-release-fixtures/baseline-red.json`。

将已有业务测试 `_commit` 内的发布夹具抽取为 context manager，五个 PostgreSQL 用例
复用同一夹具。并发测试由父线程持有一次 patch 生命周期，所有工作线程结束后再恢复。
数据库事务、锁、写入、异常注入及原断言保持原样；没有修改应用、发布授权或迁移。
该夹具模拟已验证的发布边界，不能作为真实发布授权通过的证据。既有真实授权拒绝测试保留。

## 验证记录（2026-09-10）

- 两份测试文件的断言调用集合保持不变；普通测试类的 28 个测试方法均未改动，
  PostgreSQL 类仅修改五处夹具上下文。方法及 SHA-256 对照保存在 `scope-proof.json`。
- 原生独立只读审核无 actionable finding。审核认为数据库锁、并发、回滚执行路径保留，
  发布授权仍由独立测试覆盖。2026-09-10 会话接续时再次核对两文件 SHA-256 与审核候选一致。
- Windows/SQLite 本地执行 36 项：25 通过、3 错误、8 条 PostgreSQL 条件跳过。
  三条错误涉及当前平台文件身份/符号链接以及真实 POSIX 锁限制，不能称本地全绿。
  runner 禁止外部网络；Windows 的 fcntl 替身在执行 flock 时主动拒绝，不模拟成功。
- Windows 无法完成仓库正式 POSIX 文件指纹；已保存审核前后相同的补充字节快照，
  不将其声明为正式指纹通过。正式文件指纹及数据库行为需固定候选的 Linux/PostgreSQL CI。
- 两模块仍有未改动的 TestCase 事务隔离旧失败，已有独立事务测试修复；本分支不掩盖它们。
  后续组合必须重新验证，不能累计独立分支的通过或失败数量。
- 工作流合同检查仍命中基线中五份文档的旧流程引用，四项检查器测试为三通过、一错误；
  与本机原记录一致，由独立 #186 修复。此分支未改动检查器或这些旧文档。

## 待完成

- 固定候选 Linux/PostgreSQL 16：五个受影响用例及其余 PostgreSQL 回归、真实授权拒绝、
  45 项发布合同、Django check、migration drift 和正式前后指纹。
- 核验全量失败集合及相对基线差异；保留旧失败及平台限制。
- 本变更拟以 Draft PR 交付，未合并或部署；交付按根 AGENTS.md 执行。
