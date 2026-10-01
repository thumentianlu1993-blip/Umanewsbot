# 第一批发布包与执行记录

## 待发布包

用户已明确要求“先做 1，做完让它上线，然后设计 2”，本包在该授权范围内连续执行。发布前完成回归和独立只读 review；不扩大抓取权限、不启动马匹历史导入。

- 分支 `codex/race-coverage-recovery-20261002`，基线 `070eaeda`；[PR229](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/229)，固定代码提交由实际生产记录补记。
- 生产当前 `310588704a5dd2cef477300eff626987491411cb`，目录 `/opt/umanews-release-31058870-dateonly-fix-20260930/umanewsbot`，schema 0079。
- 无迁移；配置值不变化。沿用已启用的 coverage flag，新 Beat 任务每五分钟运行，原内部 coverage incident 增加汇总邮件投递，使用既有单个运营收件人；不输出邮箱/凭据。
- 经 `deploy/deploy_0079.sh` 同 schema 前向发布，重建/排空/重启 web、worker、beat、race_sync_v2_worker；DB、Redis、Nginx、OneBot 沿用，Nginx 按发布工具更新 upstream 解析。
- 数据动作仅固定七场 772/828/830/833/970/975/976，manifest SHA `f45f8043ffd3820305813d96aaeaae57d8aa5ce40c304eb04e06d59e7f1bd94a`，本地包 `runtime/race_coverage_recovery_20261002/manifest.json`。先 dry-run，再在数据动作锁保护下单事务执行，共 52 条受审参考结果；七个过期登记退役，owner 移交 historical，旧修订/来源保留。其他赛事业务表不写。
- 全覆盖监控会写 incident/通知收据；首次新缺口汇总 SMTP 投递属于本包验收，不能把 SMTP 接受声称为收件箱已读。

## 验证与恢复

上线前复核实际 commit、镜像、应用配置指纹、schema、活跃任务/导入、共享锁、资源与健康。0079 工具生成并验证专属 DB dump、TOC 和恢复意图，记录实际路径与 SHA；生产包另保存七场动作前相关行快照。无漂移才执行数据动作。

验收：四应用版本/健康、空迁移计划；coverage 分母和下一步后台入口；自然监控执行/通知成功收据；七场 confirmed canonical、历史 owner、登记退役、七个旧 incident 闭合；双域名公开页七场完整行数及两条跌倒显示。其他 11 个 publication_blocked 保留告警，不伪报全站无缺口。

回滚保持 schema 0079，不普通降级镜像、不全库覆盖运行中的新数据。新监控异常可关闭既有 coverage flag 并经受保护发布重载，保留 incident；代码问题用同 schema 前向修复。数据动作在单事务内失败自动回滚；完成后若发现来源事实错误，使用本次备份及 manifest/OperationLog 生成新的受审更正，不盲目重放过期 owner。精确发布恢复只使用本次 0079 intent/镜像/backup，实际路径待生成后补记。

## 当前状态

代码和恢复包已形成，尚未部署/执行生产数据动作。本地 85 项相关回归和 18 项发布合同通过，旧两项失败在原基线重现；最终复审与云端 CI 进行中。第二阶段尚未开始设计。

## 2026-10-02 05:56–05:59 北京时间：代码与七场结果上线

- PR229 于 05:46 合并为 `3afde43abfd2df98744bf092f5f9839b5eae9409`；合并树等于固定候选 `ec461daad2001806b1cd00e548243ff3a76d3343`。CI 完整对照新增失败 0，两端仍各有 50 项既有失败；详见 validation.md。
- 实际运行目录 `/opt/umanews-release-ec461daa-coverage-20261002/umanewsbot`，四应用镜像 `sha256:4f835498e9f2f20af4e41d433094d3ddd70c4de6a279e5ee55859765033fd87d`。与预构建镜像文件层和运行配置相同，仅增加 Compose builder 标签。
- `deploy_0079.sh` 完整结束，schema 保持 `stable.0079_multisource_race_enrollment`，迁移计划为空；web/db/redis healthy，其余既有服务 running。配置 SHA `3ed8596fee3558fb1efe9a6adc22c40cc08a4d320cc9043bbd04808784e2f789` 不变，锁已释放。
- 本次 release ID `0ae487115cb6761469c05595729b9cd47637a4fffc4b28e66459f08933f30423`；intent SHA `15a8b24715f5fc1a1b5e91c183d3d7d852186424d1b8ab29632a488feb210a90`，manifest SHA `d0efff676f3d389aae49e6d2a569a94e9a9d3afbcf930ebdaf5d94c4b123ba7e`，complete SHA `4ee7f0114ad7b0b0c0f42b6b2b01bfb49e16a45ec87b348fc9e8b4742fd249c2`。文件位于运行目录的 `runtime/migration_history_repair/release-0079-recovery/<release ID>/`。
- 专属备份 `backup/rds_horse_news_20261001T214748Z_2536395.dump`，636805442 字节，SHA `1194646293fdf071577d372896e6e89555a83ae3e3d5218913f10396b52e5582`，TOC 1401 行；该合同不等于整库恢复成功，已知限制见恢复缺陷报告。
- 排空时普通队列有 558 条待处理，旧 worker 在完成当前任务后暂停消费，队列由新 worker 接续；未清空队列或终止在途任务。旧 race_live 队列仍 7543 条。
- 七场数据动作前保存 911 行相关对象快照，SHA `c444c3b223c05aea312d0efeadcf68f1233864bddb415fee5e756c3975131635`，私有文件在发布目录外层 `production-recovery/seven-events-before.json`。固定 manifest 执行 ready → applied → already_applied；七场 owner=historical、generation=3、登记 retired、tracking 关闭、next_poll_at 为空，52 行确认且没有伪造 official 名次，两条跌倒的 reported 名次为空。
- 双域名七场共 14 页、每域名 52 行全部核对通过；浏览器实访中央公园锦标冠军“正统”和罗伯特·勒热讷跨栏锦标“Supreme Light 跌倒”。缺失的完赛时间等仍显示待核实，不把完整名次表等同于全部字段齐全。
- 全覆盖分母 10578，confirmed 从 10208 增至 10215；issue 从 45 降至 38（日期/时刻 21、登记 5、公开门禁 11、owner 冲突 1）。后台匿名访问正确跳转管理员登录页。
- 此时自然监控与邮件回执仍待验收，七场旧 incident 尚未闭合；后续结果另记，不将代码上线等同于监控执行成功。

## 首发验收发现的监控队列阻断与补正

22:03 UTC 只读 Redis 检查：新 Beat 任务 `227cd181-71ac-48eb-a92f-03a5ed5fba53` 已进入 celery，前方还有 452 条任务，expires 为 06:04:30 北京时间；队列共 477 条。不是任务未注册或开关关闭，实际 Beat 配置 coverage=true、每五分钟、ordinary queue、expires=270。容器 stdout 没有调度日志不能单独证明未调度，任务日志另写 app_logs。

为完成本次已授权投递，在 manual-release 锁保护下手动执行当前版本 monitor 函数一次，返回 delivered=true / delivery_completed / count=44；未清空队列、未改写其他赛事业务事实。这是**手动首投**，不能声称自然任务已经通过。欧洲当地日期跨午夜后新增 6 项近期登记缺口，因此从 05:57 的 38 项增为 44 项，与七场恢复无冲突。

补正发布范围：只把新监控的 Beat options 和直接 dispatch route 改到现有 race_sync_v2 队列，更新函数说明与隔离回归；业务处理、SMTP 收件人、开关值、数据库 schema 和七场恢复数据不变。仍按固定提交/镜像、无迁移的 deploy_0079 前向发布，排空和重建原四应用；**不再次执行七场写入**。配置无需变更，发布前确认赛事 worker 消费该队列；发布后用自然执行收据和第二周期无重复投递验收。队列回退同样需受保护发布，不修改或删除消息。
