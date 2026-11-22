# 11 月 22 日剩余缺口修复发布实况

## 精确交付身份

用户对本轮明确回复“合并并发布”后，PR [#332](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/332) 合并为 `dedb9f9c77d9a5b13dea9f4ece7e17053553737d`。合并树与已验证 CI 树 `26dc210e89dd9534164473abf67f4edd24da0241` 一致，生产运行固定候选 `e4623dae16658f99fc3d21777e4406aa6e5fc6ec`。

发布包 SHA：`f689039ac0d5aabb822290a9c2d5b7d816a9bb4288c43025d5ce39919f7960e8`。数据清单 SHA：`c0025d2fb39e20c1b931c91124be99be8a7e1a161e725a23b92f9a107da2621f`。24 份绑定文件及应用归档上传后逐项复核，浏览器候选镜像在既有固定基础镜像上断网构建并核对源码。未增加来源、凭据、额度或公开地区。

- 六应用 OCI：`sha256:3b3483ea484c38e05913e3a51b3ee2b29ddadc0239cea605e3fc52f018c10f20`。
- 浏览器 OCI：`sha256:307c04e968ca69aff4a0c08577609d76911cf9e78687b3d6d4897b4e68c1f642`。
- 云端证据目录：`/opt/umanews-external-staging/remaining-e4623dae`。
- 本机证据目录：`/Users/mentianlu/.codex/runtime/race-gaps-20261122/remaining-gaps`。

## 执行和恢复面

发布控制器持有生产锁，完成身份与只读预检、停 Beat、排空 worker、完整 PostgreSQL 备份、更新既有浏览器及六应用、队列就绪、Nginx 检查与 reload、两项数据修复，再恢复 Beat。控制器退出 0，状态为 `services_ready_business_pending`，锁已释放。该状态只证明发布步骤完成，业务结果另验。

备份 1,274,732,367 字节，TOC 有效，SHA `3b93aa52f489aad408834bbfc008ceb0f4b202df865b418ca2ae098ed359e9d6`，已 fsync。无迁移、业务开关或额度调整、无 QQ 发送。绑定的业务回滚脚本可将应用恢复 `bdf9c99d`、浏览器恢复 `15289f11120dae09c4fe0ecf0a8bb2a4148c47fb4a5e77579e212fd9ed986042` 并保留已核实数据；本次未触发回滚。

## 业务验收（北京时间 17:23—17:27）

| 对象 | 已确认结果 | 限制 |
| --- | --- | --- |
| 英国 21005 | 补当地 11 月 21 日 15:00 / UTC 15:00 / 北京 23:00；字段审计 149613、149614；7 条确认赛果与公开版本保持 | 不表示实际开跑时间另作校准 |
| 美国 20926 Colonial Cup | 临时候选 42880，9 匹 overnight；网页 HTTP 200、临时标签、逐马姓名/骑师/练马师及空马号/档位核对通过 | 正式 runners、identity、enrollment、results 均为零；不能宣称正式名单恢复 |
| 美国 568 / 598 / 602 | 共 27 条结果再次逐马核对身份、名次、退赛、确认与 publication，实际网页一致 | 598 为 7 完赛 + 2 退赛 |
| 保护字段 | 569/20545/20589/20689/20926 五场人工时间、10 条权威和 10 条原审计与发布前完全相同；两场法国中文名称保持 | 不重做原补时 |
| 服务与监测 | 7 服务身份匹配、运行正常、OOM/重启 0；原监测 active、重启 0，17:27 持续采样 | 保留原 11 月 23 日 08:30 截止及原游标 |

英国和 Colonial Cup 网页验证比较数据库投影与实际 HTML 的逐行字段，不只比较数量。英国 7 条原始结果、确认位及可见性保持；Colonial Cup 明示“临时出马资料”和“更新延迟”，不伪造当前采集成功。

## 仍未关闭的边界

NSA PDF 403 已通过既有受限浏览器路径修复并发布。发布前云端隔离普通浏览器对同一官方原件返回 200、字节摘要一致；发布后 17:27 尚未取得自然采集成功收据。原预览失败退避下一次为北京时间 18:09:17，本次未清游标、提前触发或提高额度。离线候选保留原观测时间，因此不能把网页恢复等同自动刷新已验收。

Colonial Cup 正式编号证据仍不足；overnight PP 不提升为正式马号。爱尔兰三场保持既有未支持路由/非公开范围，本轮未扩区。马尼拉及尚未举行的法国场次不能提前宣称赛果链路已验收；后续由原监测继续记录。

## 验证证据

- 英国时间写入先得到真实 RED，再验证 GREEN，包括同值重放、锁、冲突、选源权限和幂等审计。
- Python / Node 离线测试覆盖 NSA PDF 来源目录精确链接、响应身份、文档预算与真实容量账本、2 MiB 上限及拒绝条件；数据脚本另验证事务、幂等和篡改拒绝。
- 固定候选 [CI 45005017079](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/45005017079)：1,437 项、零跳过，通过。主线可信外部核验器确认 PR head、合并树及交付收据；业务代码、运行脚本和一次性影响清单独立只读 review 通过。
- 更早全量 CI 45002036894 执行 7,756 项，93 条失败/错误及 10 跳过；在固定旧主线 `0e45b16d` 复现相同失败标识多重集合。它仍是失败记录，不以相关回归通过替代全量通过。
- 生产证据包括 `result.json`、`data-repair.log`、`backup-identity.json`、`services-after-2.json`、`public-verification-final.json`、`us-verification-remaining.json`、`protected-before.json` / `protected-after.json`。这些证据留在专用运行目录，仓库仅记录摘要。
