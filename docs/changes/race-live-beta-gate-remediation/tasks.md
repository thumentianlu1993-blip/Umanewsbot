# 准实时公开 Beta 上线门禁修复任务

## 1. 方案

- [x] (integration) 固化 coupled-entry 生产去标识证据与范围。
- [x] (operations) 固化 rollback manifest 缺口、下一次发布前门禁和恢复顺序。
- [x] (integration) 完成 spec/design/test_cases/tasks/rollout 审核，关闭 P0/P1。

## 2. RED

- [x] (integration) 新增 coupled number 接受、duplicate horse ID 拒绝和无关赛事不污染
  target prepare 的 RED。
- [x] (application) 新增 legacy external runner identity migration、initializer/refresh
  coupled 落库和动态更新歧义零写入 RED。
- [x] (operations) 新增 rollback bundle 生成、权限/原子性/secret 排除 RED。
- [x] (operations) 新增四层 maintenance dry-run/apply/replay/漂移零写入 RED。
- [x] (operations) 新增 PostgreSQL 并发和 one-shot 分层恢复 RED。
- [x] (operations) 新增 enabled-regions、tracking 全关、分阶段 replay/乱序和 artifact
  UID/GID/fsync/no-replace RED。

## 3. 实现

- [x] (integration) 仅移除 runner number 唯一假设，保留 runner ID 及其他严格门禁。
- [x] (application) 增加 legacy external runner ID、替换唯一约束、惰性旧身份兼容和
  动态更新歧义门禁。
- [x] (operations) 实现严格 rollback bundle 生成器和 management command。
- [x] (operations) 实现四层 maintenance 单事务 CAS command 与 OperationLog。
- [x] (operations) 补齐命令帮助、运行手册和 fail-closed 错误分类。

## 4. GREEN/REFACTOR

- [x] (integration) 逐项取得最小 GREEN 并运行 racecard/initializer 相邻回归。
- [x] (operations) 运行 rollback/official/publication 相邻 SQLite 组合。
- [x] (operations) 运行 PostgreSQL 竞争和 read-only validator 专项。
- [x] (operations) 运行 Django/migration/compile/Compose/JSON/shell/diff 门禁。
- [x] (integration) 为首次 review 的 3 个 P1、3 个 P2 补真实 RED，并完成直接路径
  GREEN；未扩大生产或迁移范围。
- [x] (integration) 为限定复审新增的 2 个 P1、3 个直接 P2 补真实 RED，并完成
  runner/result 身份、source_key 命名空间、current pointer CAS、validator 开关和
  racecard identity 冲突零写 GREEN。

## 5. 审核与发布

- [ ] (integration) 未参与实现的 reviewer 执行原生 review，修复 P0/P1。
- [ ] (integration) 复用同一 reviewer 限定复审首次 6 项及后续 2 个 P1/3 个直接 P2、
  对应修复和直接回归。
- [ ] (operations) 冻结 parent/content/fingerprint，取得该精确版本用户授权。
- [ ] (operations) 构建并验证 AMD64 image，生成绑定新 image ID 的 rollback bundle。
- [ ] (operations) 在全关维护窗口执行 maintenance/validate/coarse/validate/event restore。
- [ ] (operations) 备份、切换镜像并验证 event 924 和全部 fail-closed 开关。
- [ ] (integration) 重新执行法国 733–735 prepare；仅在无 blocker 时初始化 shadow。
- [ ] (operations) evidence-only closure 和同 reviewer 审核。
