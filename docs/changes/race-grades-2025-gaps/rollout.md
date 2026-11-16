# 合并与发布包准备

本分支基于 `c3e4c9ad5b4134fc9bc0156fd4fa2e9f1e17fa0e`；尚未合并、部署或生产补写。42 条等级和 11 项目录的来源核对、隔离演练详见 [对账记录](audit.md)。最终固定提交、CI 收据、独立审核日志、镜像和发布包 SHA 留在专用运行目录，最终交付时一起绑定，未通过前不视为可发布。

数据 manifest SHA256：`daf90b020708a8c278d0eb2181db32e01f9719ea96d24af7e94acc1c0c7b29c8`。11 个目标和 event 固定见 audit；4 场已有完整数据只补关联、2 场 NSA 补 3 条未完赛结果及对应名单状态，Classic 标取消，Brooklyn/Cougar/Frankel 标当年未办，Tokyo 原记录补 4 条名单与 4 条赛果并公开。42 条等级不做原始数据重写。

## 发布动作

- 发布六应用 web、worker、beat、race_sync_v2_worker、race_control_worker、race_realtime_worker；固定镜像从当前已上线法国身份候选 `dc6deb72` 增量构建，只带本次受测服务器文件。
- 无迁移；额度、来源 policy、公开自动化与 QQ 开关不变，不发送外部消息，不扩大抓取。
- production release lock 下核对完整 Compose 链、服务/配置身份、无冲突任务与磁盘最低 3 GiB。停止 Beat、正常排空四 worker，备份配置、受影响数据与恢复收据；不清队列。
- 重建六应用。独立一次性容器按同一 manifest 先 dry-run 再 apply，整批事务；任何前值、来源摘要、人工锁、字段级锁、在线 writer 或已有绑定变化均停止。
- 验证 42 条显示与筛选、11 项目录状态、Tokyo 公开页面全部四匹结果、原有 50 条赛果摘要、2026 Frankel 相关记录不变；验证健康、队列、Nginx 后恢复 Beat。

## 恢复

2026-11-16 17:07 只读确认六应用运行 `dc6deb72`，runtime image `sha256:9abacd2c454c3c73f34a69ae8f5d33831c9a2ced001158cdaefb488c158d170a`，web healthy，磁盘可用约 20.7 GB。最终执行前重新核对，不能只依赖此时点。

应用恢复沿完整旧 Compose 链和固定旧镜像；不修改数据库 schema。数据恢复使用同一 manifest 和 apply 收据，比对完整 after-image，仅删除本包新建的 Tokyo 八行及 NSA 三条赛果，并恢复三条名单状态并恢复原字段/目录关联；新增生涯或来源引用、字段锁、在线 writer、数据漂移时拒绝恢复并保留现状，不全库回滚。隔离演练已证明 apply/replay/restore/replay，恢复后同一 manifest 不可再 apply。

最终人工交付选择按根 AGENTS.md G2，由用户确认“只合并”或“合并并执行精确发布包”；本轮准备不执行生产动作。
