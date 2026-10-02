# 交付与恢复

本地实现、501项相关回归及独立代码复审已完成；固定SHA云端验证待执行，未合并、未发布。人工门禁只引用仓库根 AGENTS.md。

## 候选交付

固定本分支 commit，提供 PR、独立审核记录、50项映射及逐组验证结果；标明未运行全量。
CI 用明确的 known-failures 手动入口，核验 workflow 实际 head SHA 与候选一致。
实施完成后更新 current_state；CI 手动入口文档回写 deploy_runbook，公开提示恢复依据既有 decisions。
不把本轮实现误记为通用 CI 分层优化全部完成。

## 精确发布包（候选完成后填写）

- PR/SHA/镜像：待测试与代码审核完成后绑定，不提前授权任意未来提交。
- 数据库：沿用0079，无新迁移/数据迁移；发布时核验实际迁移图。
- 配置：无生产环境变量/业务 flag 变化；测试 runner 和 CI 配置不进入运行服务配置。
- 服务：使用现有0079 coordinator，按实际镜像变化重建/重启 web、worker、race_sync_v2_worker、beat；
  发布前核验锁、生产目录/镜像、在途脚本固定 SHA、队列和任务影响，列明确切服务集合。
- 数据：无批量写入、修复、删除、真实抓取和对外发送；不主动触发马匹导入验证。
- 验证：既有 preflight、check、nginx、HTTP健康、四服务同镜像/0079；公开马匹页仅只读抽样。
- 回滚：按现有0079 runbook guarded resume/forward-fix；不得回到0078或撤销约束。
  候选未迁移时保留发布前同 schema 的健康镜像/目录，记录精确恢复入口与实际允许模式。

## 安全检查点及并行任务

开始发布前实时核验 production release lock 和 coordinator；其他发布在途则等待，
不竞争或清除他人的锁。固定 SHA 抓取脚本不会因为远端合并而换代码，但数据库、队列、
配置或服务会受部署影响时必须先排除互斥。备份/健康/镜像或恢复条件不满足则停止发布。

恢复 handoff 必须保存本分支 SHA、已通过分组、失败组、原 reviewer 上下文、PR与生产状态。
部署失败只报告已证实的步骤；不得把部分服务更新称为成功。发布验证失败按绑定包执行恢复，
需要扩大动作时回到根 AGENTS.md。现有历史补齐缺口和生产数据修复不纳入本任务。

## 2026-10-02 14:52 生产只读快照

实际四应用为 web/worker/race_sync_v2_worker/beat，同镜像
`sha256:6bcae2608d47a0a184a3daf4ae65c99f645a551ebf70634bef2ec4be423658e6`、
revision `95edc4c2901d2ccf428e1c497c4fcfc37ff567ed`；web/db/redis healthy，部署锁不存在。
这是只读快照，不代表发布时仍无锁；执行前必须重新检查。本轮未改生产。

15:02只读核对：schema0079；普通worker active=1，赛事worker active=0，reserved均0；
部署锁不存在，/opt可用28.77GiB。实际发布必须等待在途任务完成并重新核验，不能强停或清队列。
