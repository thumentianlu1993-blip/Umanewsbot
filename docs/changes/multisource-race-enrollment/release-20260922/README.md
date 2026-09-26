# PR212 生产发布与验收（2026-09-22）

本文记录本次运行态；同目录上级的“准备中”记录仅作历史。主分支合并为 `6ec41fc25751352f5aab7945dcec306e93ef089d`，与实际候选 `2670660205fbee04b882dd7d01030c52788b5faf` 的 Git tree 完全一致。实际镜像 `sha256:6b26b2a80d466f8af7ab1f5119742fa85df2ee70d776abd1f88a3ef67a5902dd`，运行目录 `/opt/umanews-release-26706602-multisource-20260922/umanewsbot`。

## 测试与独立审核

[最终 CI35636669435](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/35636669435)通过。基线5129项、候选5225项，均保留相同16 failures+29 errors；新增失败0，不能称全量全绿。发布合同49+18全部通过且无skip；全量新增的1项skip已在同次独立PG合同通过。固定SHA/输入指纹/迁移漂移/失败ID均由独立Agent复核，见同目录两份CI独立审核JSON。

激活脚本 `activate-jra.py.txt` 的SHA为 `a5a54a06fdd9a60cc165b52db957a831e50888956564c87e03b4410df5276206`。独立Agent先完成10项真实进程/锁故障注入，再核对完整生产生成意图，原始文件及规范化SHA均为 `4cbe4fdf33ce5bc9cfa7059b25243ae55b54129858c27be56e4d569de3c14174`。实际commit/image/DB/policy、6配置变化、before/target flags、备份、服务集合和scope均APPROVED；审核者未连接生产。

## 迁移与关闭态验收

北京时间03:07开始、03:12前完成精确0078→0079，四应用切换至受验镜像；web健康，根域与www HTTPS健康200。新3开关仍false时独立读取实际schema：leaf0079、空迁移计划、catalog/迁移文件合同一致，完成收据和共享锁闭合。数据库、Redis、Nginx、OneBot的container ID和启动时间未变；race_live_worker未启动，导入进程仍为0。

迁移备份577708844字节，SHA `550350d4176f9ef41f636756c85f12b5ae35900d59857c2140da708a378b76dd`；激活前另备份577720879字节，SHA `ca560d67478c7f7fa24ae6f7664e261d8318df98746b32dd7caaa8251b453dc1`。两份生产归档均检查文件身份、SHA及pg_restore目录；本次未对这两份生产dump进行全量隔离还原，不将本地合同的还原测试表述成生产dump还原验收。路径、TOC与意图见同目录JSON，原始备份和私有.env留在服务器。

旧15条v1登记不转换：固定参考时间对比，登记/来源/投影/生命周期权限及公开判定无变；兼容默认值为1/0/空串/空对象。956的enrollment_policy_drift是发布前既有，不声称15场全部准入。只排除正常调度可变的时间/计数，详见legacy对照JSON。

## JRA范围与恢复

策略 `d28a690bfc7ed326f8b675775f48764d874ed4024d8414fbe2b6ec700d47f993` 只启用JRA、阪神/中山、result能力，已发布canonical赛事当地T−7日至T+30日。初始目标103/104/105；策略不具备event-ID allowlist，因此后续同范围赛事也会自然发现。106/107当时没有有效赛卡候选，其他地区真实多来源proof仍缺，不宣称七地区均已启用。策略到期北京时间2026-10-22 01:14:43；续期需重新核对来源proof。

激活以实际常驻.env为基线，只改变新3开关、policy路径/SHA和providers追加jra共6项；canonical.env原先滞后的配置同步到实际基线。原512请求/来源地区/日、1GiB预算保留。race-live调度/监测false，无新QQ/邮件发送路径，覆盖告警为内部记录。

如需关闭新功能，使用服务器已审核 `runtime/migration_history_repair/activate-jra.py rollback` 并提供原 `EXPECTED_ACTIVATION_INTENT_SHA256=4cbe4fdf33ce5bc9cfa7059b25243ae55b54129858c27be56e4d569de3c14174`。脚本复核原备份/意图，排空并恢复各自原.env；不依赖现时policy有效性。任何失败保留共享部署锁，仅同脚本原意图恢复。保留0079与v2审计数据，不降旧镜像、不反迁移、不删除v2登记。私有env快照和锁token不进入仓库。

服务器恢复命令：

```sh
EXPECTED_ACTIVATION_INTENT_SHA256=4cbe4fdf33ce5bc9cfa7059b25243ae55b54129858c27be56e4d569de3c14174 python3 /opt/umanews-release-26706602-multisource-20260922/umanewsbot/runtime/migration_history_repair/activate-jra.py rollback
```

## 激活完成

实际apply完成时间为 `2026-09-21T19:21:03.500646+00:00`（UTC），意图与收据匹配；四应用同受验镜像且新3开关true，policy挂载/SHA有效。actual与canonical环境SHA均为 `bd27b65b7c3a1df2ff2c51afdf6ace8c5b471e425f77f63b6fecaa319eac7042`；共享锁释放，原服务集合恢复，web健康。自然调度验收另列，激活本身不证明赛事已登记。

## 自然运行验收

首轮自然发现时间为2026-09-21T19:27:00.009865Z。无人工调用discovery/selector/provider业务任务；三场各取得1条v2登记和1个来源绑定，随后自然领取并正式发布：

| event | 赛事 | 官方确认（UTC） | 名单/结果行 | result revision / publication |
|---|---|---|---|---|
|103|阪神跳跃赛|19:27:22.255|12 / 12|60 / 13|
|104|产经赏All Comers|19:27:23.557|13 / 13|61 / 14|
|105|神户新闻杯|19:28:00.659|11 / 11|62 / 15|

三场均finished、admitted、official_public且visible；每场1个official observation、1个result revision、1次publication。raw SHA分别与发布前真实官方proof一致。公网HTTP200，hero为state-finished，赛果表和参赛名单均分别12/13/11行，双域名健康200。见business-first.json和public-first.json。

首轮coverage先于登记执行，初始3条result_overdue内部incident为open。9月26日只读复核发现它们均在2026-09-21T19:37:00.037Z自动resolved，补证第二调度周期的覆盖收敛；当时未取得第二轮公网页面快照，不倒填该证据。未来106/107返回source_identity_missing，未创建空登记；其他135个覆盖项不在当前policy路线范围，分类unsupported_region不等于这些赛事的旧v1功能被关闭。

2026-09-26 17:51北京时间再次核验：四应用仍运行受验26706602镜像、新3开关true、web健康、部署锁不存在。三场均保留单登记、单publication和12/13/11行公开赛果；两个域名healthz为200。结果provider最后成功时间（UTC）分别为9月25日19:32:13.967、9月26日07:35:09.559、9月26日07:41:01.757，consecutive_failures均0，证实首轮之后持续自然刷新。原始HTML哈希已变化但正式revision/publication未重复增长，当前公开页HTML SHA与首轮相同。

发现流程原next_poll字段停留在初次并不代表结果provider停止；已确认赛事由provider检查点持续更新。见business-followup-20260926.json、runtime-followup-20260926.json和public-followup-20260926.json。此次为中断后的当前追验，不能声称连续值守到第二周期。

当前覆盖缺口仍存在：106（シリウスS，9月26日）和107（スプリンターズS，9月27日）仍source_identity_missing、0登记/0结果，内部enrollment_missing incident open。先前的未来赛卡缺口未自然消除，必须另行补齐来源身份发现入口；本次已修复三场不等于JRA全赛程已覆盖。
