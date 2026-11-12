# 美国年度目录快照发布证据

## 2026-11-12 发布完成，首轮自然检查36/40成功

用户批准 PR #303 精确发布包后，源提交 `dcf31eff7eab7401f8c9f8e92cbf50c1cc477e8b` 合并为
`aa264d3b73f4ff30ace0da47ca44345675e4ab96`，合并树与范围 CI 的测试树一致。
北京时间17:15:26，四应用完成切换至候选 `73f47c292bae3df74e960b397cc30c4e52351a25`，
OCI 为 `sha256:4d8e4602b47989236bcd7110a286ec665d3481cbb0d5e1f7db3f8573e16370f3`。
发布计划 SHA256 为 `f6f9d1e3ba7bd0a2df2e2e90b0d19d247566bb8b6024e20a8a30ecf6803197be`。

- 固定候选 PostgreSQL 95 项、范围 CI 669 项均通过且零跳过；可信交付核验、独立代码和发布包复审通过。
- 无新增迁移或历史重导，schema0084 保持；两个 worker 就绪后恢复 Beat，QQ 关闭，法国浏览器未重建，发布锁已释放。
- 生产快照入口解析 606 条年度记录，零网络请求，保留真实采集时间 `2026-11-11T19:45:10.803577+00:00`。
  这是历史目录，不代表最新赛前资料或新赛果；原件和清单摘要见 [发布包](release_calendar.md)。
- 排空后重新取得本次业务基线，再验证 153 个 Django 页面、1071 行赛果、101 个来源时刻及109条旧地区换绑记录；服务切换期间业务数据一致。
- 发布后浏览器重新加载并观察赛马会金杯赛果、格伦科夫分场父页及日历、草地怪兽未举办状态，展示保持。

公网153/153详情、分场日历和历年冠军回归通过。北京时间18:22:55收齐首轮40目标：36个检查成功，其中35个记录当前目录覆盖尚未核实；Commonwealth Turf由自然任务写入18匹预想名单（candidate41893，来源USRacing，采集18:15:54）。未手动触发或重置退避。

4个失败目标是Pebbles、Manila（现行策略遗漏两个赛事路径）、Native Diver（Del Mar未发布报名表的 `-` 占位符解析错误）、Colonial Cup（NSA赛事索引HTTP403）。零网络缓存回放已定位；Red Carpet仅是同一Del Mar目录的另一未发布行，不是本轮失败目标。年度快照入口已恢复，但不能声称美国自动采集全部验收。后续修正见[剩余缺口方案](preview_source_gaps.md)，新增包尚未合并或发布。
未来正式卡、赛后节点和完整七天自然观察仍待实况。

## 首次启动中断与同包重试

首次候选只读启动遇到只读父 bind 下缺少子挂载目录，发生在暂停 Beat 或改变现有服务之前。
隔离环境用同一候选镜像复现失败，创建空子目录后通过；生产在发布锁内仅创建
`/opt/umanewsbot-persistent/runtime/race_data_sync/us-calendar` 空挂载点。
镜像、配置、快照、发布计划及全部执行脚本摘要均未改变，两层挂载继续只读。

随后重试原包。既有 `crawl_netkeiba_latest` 新闻任务约12分钟后自然结束，排空验证通过；
未中断任务、未延长900秒上限，也未执行回滚。原件和失败记录保留供追查。

## 证据位置与维护入口

本机收据目录为 `us-calendar-snapshot-20261112`，生产运行收据位于固定发布根目录下的
`runtime/us-calendar-73f47c29/`。关键文件为 `services-verified.json`、`snapshot-verified.json`、
`business-before.json`、`public-verified.json`、`workers-ready.json` 与发布日志。
维护必须使用现行完整 Compose 链，包含 `us-346-20261112/release-identity.json` 和
`us-calendar-73f47c29/release-identity.json`，不可使用旧宿主 checkout 推断运行版本。
回滚仍按原批准包恢复 `cba39875` 镜像和配置；人工门禁统一引用根 `AGENTS.md`。
