# 待确认发布包

当前仅完成准备，尚未执行生产 apply 或发布 NAR 修复。主线修复为 PR #312；生产候选固定为 `41d3f76cc8dd59bc61b2a0ceb474280db5099f7d`，仅包含 NAR 解析器与对应测试两文件，相对生产 `24de56e2cb321b102390409a6a57fb528b5dc333` 没有其他应用差异。

## 绑定范围

- NAR 解析器修复，无数据库迁移、配置或功能开关变化。必须继承当前 compose 文件链中的 `/opt/umanews-external-staging/disk-capacity-20261114/capacity-override.json`，四应用保持 `RACE_DATA_RAW_MIN_FREE_DISK_BYTES=3221225472`（3 GiB），不得回退至旧阈值。
- 从现有生产 `24de56e2` 构建包含本 PR 的窄候选；web、worker、race_sync_v2_worker、beat 使用同一固定镜像重建/重启。浏览器 sidecar、数据库、Redis 和其他项目服务不重建。
- 生产数据：旧赛事 4 的 6 对象归档后移除；20 个失败赛前来源只提前 next_poll_at，交回既有调度。已推进、已交接或被租约占用的目标跳过。
- manifest SHA：`f01c9d6c65bfd2441268d61a4fe03faecf51327963e4d32831caf7424d0e74fb`。
- 数据脚本 SHA：`cfefbb56d4bb2323e9bec93508693000e329f80a103564d80669eddf1e4d71be`。
- 产物根目录：`/Users/mentianlu/.codex/runtime/collection-recovery-arc-20261114/`，包括 `manifest.json`、`data_actions.py`、`test_data_actions.py`、只读核对及测试日志。含归档的文件保持私有，不提交仓库。

## 执行与验收

按现有发布协调锁排除冲突发布/写入，核对四应用当前 SHA、磁盘、活动任务及队列。按发布惯例建立数据库恢复点，构建固定候选、执行必要检查后重建四应用。在同一发布窗口执行 manifest 校验、prepare、精确归档及 apply；不得修改活动租约或清除失败证据。

等待正常调度接回目标，逐项记录成功、正常未发布、有效交接或独立来源失败；无新证据不得写“全部恢复”。NAR 验收要求报名候选完整 68 匹，12/56 分组保留，且不当作正式出马表。旧凯旋门 URL 应 404，新 URL 200 且 16 匹赛果保持；数据库/后台只查到新赛事。

SCMP 当前被源站 HTTP 403 阻断，本包不绕过访问限制，亦不把它记为恢复。

## 回滚

应用回滚到原固定镜像；无需回滚 schema。旧入口可由 manifest 中 SHA 对应的 `arc-before.json` 事务恢复 6 个对象；必须先验证旧主键和旧路径未被重新占用，新赛事不回滚。调度提前后已成功取得的正常数据不删除，保留每目标重试前状态与执行收据。归档、身份或关联漂移时立即停止，不盲目重试删除。
