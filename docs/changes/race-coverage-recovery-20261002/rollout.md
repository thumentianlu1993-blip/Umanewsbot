# 第一批发布包与执行记录

## 待发布包

用户已明确要求“先做 1，做完让它上线，然后设计 2”，本包在该授权范围内连续执行。发布前完成回归和独立只读 review；不扩大抓取权限、不启动马匹历史导入。

- 分支 `codex/race-coverage-recovery-20261002`，基线 `070eaeda`；PR/固定提交待冻结后补记。
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

代码和恢复包已形成，尚未部署/执行生产数据动作。独立复审及基线失败归因进行中。第二阶段尚未开始设计。
