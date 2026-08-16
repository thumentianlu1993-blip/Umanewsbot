# 生命周期全量 enforce cohort 任务

## 测试

- [x] (application) 新增 selector、3+成员、多 enrollment SHA、原子 promotion、O(1) 单场验证 RED。
- [x] (integration) 新增 scanner 分页、stale task、legacy provenance 和范围外零写 RED。
- [x] (application) 新增 PostgreSQL promotion/claim/apply 并发与回滚 RED。
- [x] (operations) 新增 registry env/coherence、shared lock、失败恢复和 predecessor rotation RED。

## 实现

- [x] (application) 新增 registry/membership 模型、migration、约束与索引。
- [x] (application) 实现 registry artifact、cutoff selector、membership、promotion/activation/replay。
- [x] (integration) 将 scanner/task 切到 active registry + O(1) per-event validation，保留 legacy 兼容。
- [x] (operations) 实现 prepare/promote/verify 命令与 registry wrapper，扩展 mode switch/coherence。
- [x] (application) 实现人工 successor candidate 的离线 prepare/dry-run；生产自动 admission 不在本 change。
- [x] (operations) 更新 env 示例和受影响运行文档，不改 race-live/provider/新闻/QQ。

## 验证

- [x] (application) 运行聚焦、相邻 lifecycle、缓存与 Django 回归。
- [x] (integration) 运行 PostgreSQL 并发、查询数/锁范围和 Celery route 测试。
- [x] (operations) 运行 shell contract、workflow contract、Django check、migration drift、diff check。

## review

- [x] (application) 冻结 fingerprint，由未参与实现的 reviewer 执行只读代码 review；前四轮结论为 REVISE，
  findings 均已修复。
- [x] (operations) 修复 findings 后复用同一 reviewer 会话复审并冻结最终 fingerprint；结论 `APPROVED`，
  审前审后均为 `9d2cb55d6125310e114e381cc91359eae5b06f695136059bad2e2e1cc0c871c8`。

## 发布

- [ ] (operations) 提交 G2 发布包：代码/迁移/env/服务/备份/回滚/验证精确绑定。
- [ ] (operations) 关闭态部署并生成生产只读 census/dry-run；不自动启用全量。
- [ ] (operations) 经 G3 依次发布 7 天、30 天、全部当前合格赛事 generation；race-live 保持关闭。
- [ ] (operations) E1 稳定后另立 E2 自动 admission change，不在本任务宣称永久自动全量。

## 后续非阻断建议

- [x] (application) prepare 明确拒绝未来 `census_cutoff`，避免操作员冻结尚未发生的 census。
- [x] (integration) Celery 单场结果保留 `registry_root_stale` / `registry_runtime_expired` 等 noop reason_code，
  提高轮换与到期诊断可观测性。
- [ ] (application) 后续收紧 `no_time_canary` 的 explicit IDs：缺失或不合格时 fail closed，不静默省略。
- [ ] (integration) 后续为未发布、人工锁或暂停的 early return 增加 claim 释放或退避，减少 TTL 后重复调度。
