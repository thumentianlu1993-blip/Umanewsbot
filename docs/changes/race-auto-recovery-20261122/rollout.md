# 发布包边界

按根AGENTS.md交付，最终PR/head、镜像digest、基线Compose链和配置摘要绑定在专用runtime交付包。

## 操作

- 在固定候选SHA构建linux/amd64镜像，保存并校验归档；无迁移，发布前核对迁移图和空计划。
- 单一release coordinator取得生产发布锁；锁内复核六应用版本、完整Compose配置摘要、资源、active/reserved及冲突任务。保留旧完整Compose链、容器/镜像身份和数据库备份/TOC。
- 停Beat并温和排空四worker；不清队列。现有完整配置链仅追加固定镜像及UMANEWS_RELEASE_COMMIT，重建web、worker、race_sync_v2_worker、race_control_worker、race_realtime_worker，队列消费者和health就绪后重建Beat；Nginx检查并重载。
- 业务开关、2048次/4GiB额度和来源/覆盖范围不变，无新增外部消息。生产数据动作仅上述自然发现恢复和既有采集发布：登记/集合收据、跟踪/检查点、OperationLog，以及正常观测/名单/时间/正式结果/内部incident；无指定赛事手工回填，无批量历史修复。

## 验收与回退

六应用同一候选镜像；四worker队列就绪；自然发现产生恢复审计、next_poll_at及新claim，已公布赛事的正式结果和公开页一致，原故障incident解除。重点127/21005验证完整结果公开，20902/20904验证当前有效来源和检查点恢复；尚未公布正式结果则保留赛前状态，不伪造完赛。未来结果仍须自然赛事发生后验证。

回退：停Beat、温和排空worker，保存失败证据；用包内旧完整Compose链和旧镜像重建同六应用、核验队列/健康再启动Beat。schema不变，保留期间正确观测、名单和结果，不整库覆盖、不清Redis。恢复能力随旧代码回退而失效，故必须明确报告；若已出现错误公开写入，停止有关任务并保留现场，按实际影响准备精确数据修复，不自动覆盖新数据。

基线/配置/镜像/人工锁/owner或schema不符合获准包时，在切换前停止。当前仅准备，本轮未合并、未发布、未修改生产数据。
