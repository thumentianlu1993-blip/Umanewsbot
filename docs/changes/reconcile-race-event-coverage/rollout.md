# 发布与运行边界

## 当前状态

本 worktree 仅完成应用代码、测试和本 change 文档；没有连接生产、没有生成生产 artifact、没有提交、推送、构建镜像或部署。

## 后续安全顺序

1. 先修复或更新既有 `RaceEventPageMVPTests.test_csv_import_candidate_fetch_and_candidate_apply` 的日期门禁夹具，再完成全量 `stable` 回归。
2. 由独立 reviewer 审核当前代码与 change 文档；内容变化后重新审核。
4. 生产先停 historical runner 并确认无 live lock，再生成只读 artifact；普通新闻服务无需停机。
5. 独立审批必须绑定 manifest SHA-256；apply 必须同时提供 manifest 与 approval 的精确 SHA-256。
6. apply 后运行 verifier，保持历史公开开关关闭；异常时优先使用 rollback ledger，若目标、赛事或详情已漂移则停止并走人工补偿或数据库恢复。

## 本次明确未做

- 未修改数据库模型或迁移。
- 未创建、删除或合并任何生产 `RaceEvent`。
- 未改变任何生产 target/event 状态、可见性、详情或发布开关。
- 未执行 tasks 9–12 的 operations 工作。
