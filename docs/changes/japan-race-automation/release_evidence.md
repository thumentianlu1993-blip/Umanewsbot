# 2026-11-08 日本赛事发布与线上验收

## 已发布对象

[PR #283](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/283) 于 UTC 13:04:53 合并，主线合并提交为 `a25e62869cf471f9e25820a8c241e4b035271a36`。
生产按获准的窄发布包运行 `69947674bbebff917cc9080cdda6298e81b0e49c`，不包含主线其它变更或本次 CI 治理代码；schema 保持 `0079`，无新迁移。

- 应用镜像：`sha256:1d5c696d23814be81360ed16fec4d499ceaf4033ebcbe15ec98ff53989a5867e`。标准 Compose 构建仅比预构建镜像增加 `com.docker.compose.image.builder=classic` 标签，RootFS 与其它 Config 相同，固定 revision 未变，绑定经独立复审。
- 浏览器获审配置摘要：`sha256:3913469a50c8d719d89dc919d088b3d8d890aca0fb32710908dcd9ef9bfa046d`；服务器使用 OCI manifest 摘要 `sha256:453f11ceb9c1e79be9d2395756d9d67f739ed338176a4ebf22be6717a8cdfe9a` 引用同一配置与文件层。已在目标主机完成非 root、sandbox、只读根目录的真实冷启动取数。
- 运行目录：`/opt/umanews-release-69947674-japan-20261108/umanewsbot`；Compose project 为 `umanewsbot`。日本服务使用基础 `docker-compose.prod.lowcost.yml` 加 `docker-compose.japan-browser.yml`。
- 历史 manifest：`3a9b870ed13f42525ae21573c22acb3a518f2728cd7582eba687186315a3710f`；来源 policy：`7ac88a1bedc38da0747b4ca188f509d9c546c033c947124ac9b22a8b875b05c1`。
- 证据包：`dfc916f36d6389ef20a72d96443d9e9baf24eb4efde117874bffb47ea7130f79`，63 文件。生产公开取数证据在持久目录 `runtime/race_data_sync/japan-69947674`。

## 验证与实际执行

[范围 CI 42481070958](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/42481070958) 对固定 head `c85990c7d0a3e8934cf0d3fad3918038d29896f2` 执行 854 项，全部通过、零跳过。
候选目录外核验器完成提交、工件、主线保护与控制文件绑定，独立收集的 6 个批次、854 个测试与 CI 完全一致。首次范围 CI 的两项工具夹具失败已真实复现并修复，未放宽断言或跳过规则。
生产窄基线另有此前 182 项 PG 范围回归、82 项 review 增量和最后 5 项回归，以及整包回滚、幂等和真实浏览器链路证据；这些计数不相加冒充唯一用例数。

标准 `deploy_0079.sh` 完成专属备份、关闭态校验、静态文件准备和原服务恢复。备份为 934338010 字节，SHA-256 `5536f73e154a4f9c9ef7e75c4095a0f21b30a5100e489662ac53167593653ce5`，TOC 1401 行。本次生产备份验证了摘要与目录，未执行全量隔离还原。
发布意图 SHA 为 `4a2b284dc0857b1662c105bcecdde513e8781fc195408cce2ea658cd5fcdd171`，对应 release ID `fac4d07240780e562a0967c0141be1d40a1743f9f237d5cf2faf7c57a79323b2`。

日本激活重新核对实际镜像、四应用、原配置与 0079 完成收据后，停止 Beat，确认两个 worker 的 active/reserved 均为零并停写。
固定清单先在生产事务内回放 43 场、571 行并整体回滚，再正式提交；70 个系列名称、12 个来源别名及已批准的生命周期接管同包执行。
随后依次恢复 Web/健康检查/Nginx、两个 worker、Beat，UTC 13:16:09 完成激活并释放发布锁。

## 线上验收

- 数据库只读核对：70 场样本中的 43 场历史赛事均 finished，571 行赛果与各自已发布 revision 一致。
- 公网逐页核验：70 个赛事 URL 全部 HTTP 200，公开赛果行数合计 571，与数据库一致。
- UTC 13:17 的自然定时任务完成 12 场 JRA、2 场 NAR 赛前检查；本轮失败数均为零，没有人工触发采集任务替代自然调度。
- 四场 JRA 报名名单分别为 event 124：20 匹、125：13 匹、126：23 匹、128：21 匹，共 77 匹。自然成功时间为 UTC 13:17:39 至 13:17:57，四个公网页面的“报名名单”和行数均已核对。
- 其余 8 场 JRA 以及 NAR 204/205 正确记录 `not_published`、failures=0；未制造尚未公告的名单。NAR 两场自然检查在 UTC 13:18:05 完成。
- 自然周期后，四应用和浏览器均 Running、restart=0、OOM=false；双域名 healthz 均 200，发布锁空闲。观察点可用内存约 5397 MiB、磁盘约 12 GiB；不将单次观察写成长期容量验收。

70 场是本次验收样本，不是通用采集能力的 event-ID 限制。JRA 10 场地、NAR 15 场地的通用适配与政策范围保持获准版本。
正式出马表自然发布和赛后状态变化尚未发生的部分，按用户约定留待下一场实况回归；本记录不宣称这些未来状态已经验证。

## 恢复与证据位置

原应用镜像 `sha256:3fcf9090af794f98fffa0f33f110e02126b491fd0caab5df6b9dd1be69bc20f9` 及 `umanewsbot:rollback-before-japan699` 标签保留。
原配置位于运行目录的私有 `runtime/japan-release/pre-japan.env`，不提交仓库。
标准备份、intent/manifest/complete 位于同目录的 `runtime/migration_history_repair/release-0079-recovery/<release-id>/`；不能套用其它发布的收据。
回退边界沿用[获准发布包](rollout.md)：同 schema 校验后恢复原应用与日本配置，停止新浏览器；已经验证正确的官方赛果保留，不整库覆盖其它业务。

本机原始验收材料保存在 `/Users/mentianlu/.codex/runtime/japan-race-automation-20261108/`：`delivery-verification.json`、`production-deploy.log`、`production-activate.log`、`production-backfill-applied.log`、`postdeploy-natural-census.json`、`public-production-verification.json`、`natural-public-previews.json` 和 `production-health-natural.txt`。
本文记录本次事实，人工门禁统一引用根 `AGENTS.md`。
