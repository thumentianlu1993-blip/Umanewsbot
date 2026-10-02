# 交付与恢复

PR #232 已于 2026-10-02 合并并上线，最新执行与验收见文末；下列候选阶段文字保留为历史。人工门禁只引用仓库根 AGENTS.md。

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


## 2026-10-02 17:52–18:03 北京时间：PR #232 上线完成

用户在具体发布包之后明确要求“先把当前这个版本上线，再设计以上方案”。本次按该包执行，未扩大生产范围。

- PR #232 合并为 `fc1eed938beb8b431e0d4b37953f7599a40a72ce`；合并树与受验候选
  `ad50abdb74b89669ab8ada2958b040877c1a1849` 相同，tree 为 `92e272232b54f0ebb43d40ec321316a028ed4740`。
- Linux CI [36976989113](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/36976989113)
  501 项四批相关回归、12 项入口自测、67 项发布合同和完整性聚合均通过；两个全量分支明确 skipped。
  发布期间没有重跑全量，也不声称全量通过。
- 实际目录 `/opt/umanews-release-ad50abdb-test-fixes-20261002/umanewsbot`，固定镜像
  `sha256:73ee1dcf7edb5b7c7bda49f5d6baedffe030d639fcc5bf191b831ece6e9f5930`。
- `deploy/deploy_0079.sh deploy` 于 18:00:42 正常结束。web、worker、race_sync_v2_worker、beat
  均为候选 SHA/同一镜像，restarts=0、OOM=false；web/db/redis healthy。
- 数据库仍为 `0079_multisource_race_enrollment`，迁移计划为空；配置 SHA
  `3ed8596fee3558fb1efe9a6adc22c40cc08a4d320cc9043bbd04808784e2f789` 不变。
  race_live_worker 仍未启动；没有批量数据修复、手动抓取或对外发送。
- 本次自然排空成功，不需要 cancel_consumer。新普通/赛事节点为 `celery@78c9d141f636` /
  `celery@63983e585693`，分别消费 celery / race_sync_v2；队列未清空，任务未撤销。
- 18:02 起只读验收：双域名 healthz、马匹列表、46588/3866 详情均 200；46588 显示
  “资料补全中/中文译名待补”，3866 显示“完整二代血统”且无待译提示；没有公开“空壳”用语。
  两个生产服务文件、两个模板的实际镜像内 SHA 与候选相同；Django check、Nginx 检查通过。
  发布锁和 active intent 指针已释放。证据见 [production-validation.json](production-validation.json)。

本包恢复记录在上述目录 `runtime/migration_history_repair/release-0079-recovery/` 下，release ID：
`9285ebdebdb14105f864aea4b04d7704a90a196bd89a8bc49735f407beefc6a9`。

| 证据 | SHA-256 |
|---|---|
| intent.json | `255fb5f0d9033e5a02f1a857992c1212f8fdc005ebe42986ceee242454e75cbb` |
| manifest.json | `1d876b00883c5dc865156d5cce4e7e34d4ead82d275157d42e9b48507f7c472e` |
| complete.json | `aa511dbe55fb1137f623708e120d7eb34ed172f0fd5c978887840bdf57ca2834` |
| backup/rds_horse_news_20261002T095603Z_2744535.dump | `57a3c698c72854eade3ba60c8fbb02fa8b81a780c53f0d8547e524013e3abd2a` |

备份大小 639666774 字节，TOC 有 1386 个非注释条目。只验证归档、摘要及目录，
不声称此前整库恢复的两项数据约束缺陷已解决。

若原发布中断，恢复入口须绑定本目录、上述 intent 路径/SHA、固定镜像和 `COMPOSE_FILE=docker-compose.prod.lowcost.yml`，
使用 `deploy/deploy_0079.sh resume`；本次已正常完成，无需执行。完成后若出现新代码故障，
按同 schema 前向修复流程处理，不盲目降旧镜像或全库覆盖。

下一步仅设计 [按改动范围测试](../impact-based-testing/spec.md)，尚未改变默认 PR 全量规则。
