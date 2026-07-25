# 发布与回滚

## 当前状态

本变更仅完成本地实现和验证。尚未提交、推送、部署、触网或写生产马匹数据。

## 发布前门禁

1. 独立 reviewer 在只读沙箱中通过，并冻结受审 fingerprint、approved parent 和 content hash。
2. 获得 review 后针对精确受审版本的发布授权。
3. 部署时常驻 `web/worker/beat/race_live_worker` 的马匹网络开关保持 false。
4. 生产迁移只新增 `HorseIdentityEvidenceCommitReceipt`；先验证迁移计划和备份，再执行。

## 生产 PoC

1. 从最新生产只读快照选择 20 匹第二层对象，冻结赛事 URL、日期、场地、马号、精确马名和
   唯一 Netkeiba ID。
2. 另获当次触网授权后，在一次性容器低频执行 prepare；结束立即关闭网络。
3. 20/20 必须归入 pass、partial 或稳定 blocker，未知异常为 0，至少 1 匹完成
   “赛事上下文 → 唯一官方锚点 → 双源完整一致”。
4. PoC 不写业务表；人工审阅 xlsx、来源证据和请求账本后，才可扩大到最多 100 匹 prepare。

## 正式写入

正式写入需要绑定精确批准 SHA 的新授权、数据库恢复点和竞争任务排空。commit 只写获批且仍为空、
未人工锁定的父、母、出生日期及来源引用、receipt 和 OperationLog。写后执行幂等重放、公开状态、
履历、P0 来源和网络 false 复验。

## 回滚

- prepare/PoC 无业务写入：停止一次性容器、关闭网络并保留审核 artifact。
- 迁移失败：停止发布，使用既有部署回滚流程恢复旧镜像；不得在失败事务上继续写数据。
- commit 失败：整批事务应自动回滚；核对 receipt、OperationLog 和目标字段均无部分写入。
- commit 成功后发现问题：按批准 artifact 的 before/after 和数据库恢复点制定精确回滚，不删除
  审计证据，不用猜测值覆盖。

## 审查记录

- 首轮只读审查会话：`019f9970-cc09-74f0-99d8-514586296a86`。
- 首轮 finding：迁移主线冲突、批准前未重算共识、未强制 HTTPS、直连锚点可缺 ID、请求无超时、
  新 change 误放 OpenSpec 目录。全部已修复。
- 完整范围原生 review 会话 `019f99c5-9fa6-7022-a0a6-c999e1dbd68d` 发现两项 P1：真实
  prepare 候选缺少 commit 冻结字段，approve 未把内嵌候选绑定到已审核 sidecar。两项均已补
  RED 并修复；身份模块 `46/46`、相关主链 `551/551`、Django、migration drift、`0058`
  往返迁移、Compose 和 diff check 通过，同一会话随后确认无 actionable finding。
- 2026-07-26 发布前完整指纹因 `origin/main` 新增 HRN 修复与发布证据而变化；未进入 staging。
  本分支已安全同步 `origin/main@0aeb0ed7660746bdcdcbad0343aad771b1324918`，自动合并状态文档
  且无冲突。合并后身份模块 `46/46`、相关主链 `551/551`、Django、migration drift、Compose
  和 diff check 通过；须生成新指纹并由同一 reviewer 会话复审，成功后重新取得提交/推送授权。
