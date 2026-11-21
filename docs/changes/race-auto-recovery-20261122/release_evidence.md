# 自动恢复发布与自然验收

## 固定交付与发布

用户批准等待采集锁释放后合并发布，并验证四场自然恢复。PR #327 合并为
`05f87e17d5d5574dd126e1f8b81fab3ebb56b993`；受测树与合并树一致。
候选 `ceb7737ddb9bd30d910145a648c9c32fe1362508`，范围 CI 938 项、零跳过，
164 项模块回归及代码/发布控制独立 review 通过。
发布包 SHA256 `eefbd51ea4c8c4e8d7c358bdc1d01a52a582cf6c81d566649c153a48ff24df89`。

北京时间 2026-11-22 01:30 开始发布；旧采集锁已释放且基线复核一致。
候选 schema 检查通过、迁移计划为空，未运行迁移。停 Beat 并温和排空四 worker；
生成 1,253,343,809 字节 PostgreSQL custom-format 备份，TOC 校验通过。
六应用于 01:39 前完成切换，四 worker 队列、Nginx 和公网 healthz 通过，Beat 恢复。
镜像 OCI digest 为 `sha256:6e5011aedff0aee240324ef1f60758eb3f293ff1e0f90bf3ceefae5154480261`。
2048 次/4 GiB 额度及业务配置保持；发布锁已释放，无 recovery marker，未执行回滚。

## 自然业务验收（截至北京时间 02:32，仍在观察）

- 福岛纪念 127：01:39:15 正式确认 16 条结果记录，01:40:02 原告警自动 resolved。
  公开读取合同通过，公网 HTTP 200，显示已完赛及结果表。
- 英国 21005：01:47、01:57 自然发现均返回 `strong_identity_required`，仍未登记。
  已批准系列缺少系列名称，且无来源身份/身份键；详见 [后续缺口](uk_followup.md)。
- 法国 Chloris 20902：01:57 自动恢复，恢复审计为 `legacy_rotation`，准入及检查点有效；
  自然轮询已执行，02:00:41 原告警 resolved。当前仍属赛前状态。
- 法国 Jacques de Vienne 20904：原退避到 02:17:22，实际自然发现于 02:28:29
  完成 `legacy_rotation` 恢复，准入、审计及检查点通过；02:32 原告警仍未解除，
  轮询仍等待消费，不能宣称该场完整闭环通过。

本次未手动补采、修改 next_poll_at 或手工修复赛事记录。
两场法国赛事尚未开赛，赛后正式结果验收须等真实比赛后完成。

## 证据位置

本机专用 runtime `race-update-diagnosis-20261122` 保存 approved.json、固定发布包、
CI 收据、production-after.json、business-after-*.log、recovery-observation-*.json
及四页 public-after-*.html。生产私有包目录为
`/opt/umanews-external-staging/race-auto-recovery-ceb7737d`，含 result.json、
controller.log、备份及 TOC、完整旧配置与镜像身份。备份和完整运行配置不入仓库。
