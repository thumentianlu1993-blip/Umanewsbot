# 交付准备

当前为开发中，未合并、未部署。交付授权按根 `AGENTS.md`，本文件不新增门禁。

发布涉及一条增量 JSON 字段迁移，以及当前六个应用/调度/worker 服务重建；浏览器、数据库、Redis、Nginx 配置和监测服务无业务变化。不改变功能开关或抓取配额，不进行批量数据回填，不发送 QQ。
上线须固定最终 PR/commit、镜像和发布包，验证生产版本与锁，备份数据库，在 worker 排空后迁移并切换服务，核验队列、内存、健康与原监测持续性。
回滚恢复原应用镜像，保留兼容的新增 JSON 字段与私有证据文件；不得为回滚删除诊断或业务数据。上线后通过自然任务验证新诊断与退避，不以强制重试增加抓取。


## 只读诊断

`python server/manage.py inspect_race_collection_failures --event-id <赛事编号>` 返回正式采集、赛前检查和来源发现的诊断。`needs_attention` 是内部处理标记，不会发送通知。`evidence.status` 表示当时留存结果，`evidence_now` 才表示本次读到的原件状态。
原件在既有私有根目录的 `failures/<sha256>.json`；读取或复制前先确认 `evidence_now=verified`。命令不打印响应体、不更改状态、不触发重试。
