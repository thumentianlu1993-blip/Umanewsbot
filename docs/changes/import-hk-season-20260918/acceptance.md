# 香港2026/27赛季生产验收

2026-09-18 05:50 UTC（北京时间13:50）已完成本轮资料导入及线上验收。仅执行固定数据脚本，应用仍为`7e111914d57083299ce452b6222ab9d38476e420`，未部署或重启。

## 范围与结果

- 官方PatternRace共35场：G1 12、G2 7、G3 13、4YO 3；新建34，保留既有香港杯event2。
- 公历2026年13场、2027年22场。仅行政长官杯已结束：新增event19603，香港时间2026-09-06 13:30，沙田草地A栏1200米，6匹参赛和正式赛果完整写入；冠军嘉应高升，1:06.11。
- 其余33个新建赛事为scheduled，无单场赛时或出马表时保持未填，不使用日历零点。既有香港杯的16:40仅保留原数据，本轮没有新增该赛时的官方核验。
- 双域名70个详情页逐场状态/身份通过；行政长官杯六匹名次、马号、马名及完成时间全部一致。两域名2026年各匹配13场（2页），2027年各匹配22场（1页）；2027年份筛选可见。
- event2完整业务快照SHA保持一致；用户暂缓的828/830/924逐条前后SHA一致。未修复旧年度重复项，也未导入普通赛事。

## 固定包和恢复证据

- 独立分支`codex/import-hk-season-20260918`，执行代码提交`3fe5ac89`。
- seal文件SHA：`85dfb05f157dc6d566b9919c9e05aed8de5a26518e2ee2fec68d817157dd2643`。
- manifest规范化SHA：`7ea7d5c387e2ab56450017431fd26588bdc7a5a4d1893c52a55bab89f010eaab`；文件SHA：`c88f11d1b3c70a0ebcc06c009ea4b77014d539dd0be6a20ce79bd9344d6fd3f0`。
- 操作审计`108715`；apply返回34新建，立即重放验证`already_applied`，无重复行。
- 生产备份：`560628521`字节，SHA256 `79a67f47520ab03cd843448e25153808b2d84bad7bb341e64f01b8fb291febdd`；0600、custom格式、pg_restore目录验证通过。完整备份及私有before仅留服务器固定包目录，不进Git。
- 8个既有服务运行、已配置健康检查的均healthy；无容器重启/重建。共享部署锁已释放，无不确定操作收据。收尾队列celery=7（普通运营流量）、race_sync_v2=0、race_live=7543；未清队列。
- 固定方案代理与固定代码代理均APPROVED。代码代理两轮finding（测试译名、异常保留锁、Healthcheck）均已闭合；12项隔离PG/故障测试通过。
- 生产包：`/opt/umanewsbot-persistent/runtime/artifacts/hk-season-20260918`；导入/宿主脚本只接受seal固定文件，不改变通用历史import门禁。
- 首次GitHub push被自动审批因缺少明确目的地授权拒绝，未绕过；随后用户明确授权推送`thumentianlu1993-blip/Umanewsbot`的`codex/import-hk-season-20260918`分支。仅提交脚本、公开资料清单和公开验收证据，不上传生产备份、私有快照或凭据。生产验收证据另经固定代码代理只读复核APPROVED。

## 逐场清单

| 公历日期 | 赛事 | 等级 | 处理 |
|---|---|---|---|
| 2026-09-06 | [香港特区行政长官杯](https://umafans.run/races/2026/hong-kong-hksar-chief-executives-cup-2026/) | G3 | 已完赛，6匹正式结果 |
| 2026-09-27 | [庆典杯](https://umafans.run/races/2026/hong-kong-celebration-cup-2026/) | G3 | 新增赛历，赛时待公布 |
| 2026-10-01 | [国庆杯](https://umafans.run/races/2026/hong-kong-national-day-cup-2026/) | G3 | 新增赛历，赛时待公布 |
| 2026-10-19 | [沙田锦标](https://umafans.run/races/2026/hong-kong-sha-tin-trophy-2026/) | G2 | 新增赛历，赛时待公布 |
| 2026-10-25 | [精英碗](https://umafans.run/races/2026/hong-kong-premier-bowl-2026/) | G2 | 新增赛历，赛时待公布 |
| 2026-11-08 | [妇女银袋赛](https://umafans.run/races/2026/hong-kong-ladies-purse-2026/) | G3 | 新增赛历，赛时待公布 |
| 2026-11-22 | [马会杯](https://umafans.run/races/2026/hong-kong-jockey-club-cup-2026/) | G2 | 新增赛历，赛时待公布 |
| 2026-11-22 | [马会一哩锦标](https://umafans.run/races/2026/hong-kong-jockey-club-mile-2026/) | G2 | 新增赛历，赛时待公布 |
| 2026-11-22 | [马会短途锦标](https://umafans.run/races/2026/hong-kong-jockey-club-sprint-2026/) | G2 | 新增赛历，赛时待公布 |
| 2026-12-13 | [香港杯](https://umafans.run/races/2026/hong-kong-cup/) | G1 | 保留既有赛事 |
| 2026-12-13 | [香港一哩锦标](https://umafans.run/races/2026/hong-kong-hong-kong-mile-2026/) | G1 | 新增赛历，赛时待公布 |
| 2026-12-13 | [香港短途锦标](https://umafans.run/races/2026/hong-kong-hong-kong-sprint-2026/) | G1 | 新增赛历，赛时待公布 |
| 2026-12-13 | [香港瓶](https://umafans.run/races/2026/hong-kong-hong-kong-vase-2026/) | G1 | 新增赛历，赛时待公布 |
| 2027-01-01 | [华商会挑战杯](https://umafans.run/races/2027/hong-kong-chinese-club-challenge-cup-2027/) | G3 | 新增赛历，赛时待公布 |
| 2027-01-10 | [洋紫荆短途锦标](https://umafans.run/races/2027/hong-kong-bauhinia-sprint-trophy-2027/) | G3 | 新增赛历，赛时待公布 |
| 2027-01-13 | [一月杯](https://umafans.run/races/2027/hong-kong-january-cup-2027/) | G3 | 新增赛历，赛时待公布 |
| 2027-01-24 | [百周年纪念短途杯](https://umafans.run/races/2027/hong-kong-centenary-sprint-cup-2027/) | G1 | 新增赛历，赛时待公布 |
| 2027-01-31 | [董事杯](https://umafans.run/races/2027/hong-kong-stewards-cup-2027/) | G1 | 新增赛历，赛时待公布 |
| 2027-01-31 | [香港经典一哩赛](https://umafans.run/races/2027/hong-kong-hong-kong-classic-mile-2027/) | 4YO | 新增赛历，赛时待公布 |
| 2027-02-14 | [百周年纪念银瓶](https://umafans.run/races/2027/hong-kong-centenary-vase-2027/) | G3 | 新增赛历，赛时待公布 |
| 2027-02-21 | [女皇银禧纪念杯](https://umafans.run/races/2027/hong-kong-queen-s-silver-jubilee-cup-2027/) | G1 | 新增赛历，赛时待公布 |
| 2027-02-28 | [香港经典杯](https://umafans.run/races/2027/hong-kong-hong-kong-classic-cup-2027/) | 4YO | 新增赛历，赛时待公布 |
| 2027-02-28 | [香港金杯](https://umafans.run/races/2027/hong-kong-hong-kong-gold-cup-2027/) | G1 | 新增赛历，赛时待公布 |
| 2027-03-21 | [香港打吡大赛](https://umafans.run/races/2027/hong-kong-hong-kong-derby-2027/) | 4YO | 新增赛历，赛时待公布 |
| 2027-04-04 | [短途锦标](https://umafans.run/races/2027/hong-kong-sprint-cup-2027/) | G2 | 新增赛历，赛时待公布 |
| 2027-04-04 | [主席锦标](https://umafans.run/races/2027/hong-kong-chairman-s-trophy-2027/) | G2 | 新增赛历，赛时待公布 |
| 2027-04-25 | [女皇杯](https://umafans.run/races/2027/hong-kong-queen-elizabeth-ii-cup-2027/) | G1 | 新增赛历，赛时待公布 |
| 2027-04-25 | [冠军一哩赛](https://umafans.run/races/2027/hong-kong-champions-mile-2027/) | G1 | 新增赛历，赛时待公布 |
| 2027-04-25 | [主席短途奖](https://umafans.run/races/2027/hong-kong-chairman-s-sprint-prize-2027/) | G1 | 新增赛历，赛时待公布 |
| 2027-05-02 | [皇太后纪念杯](https://umafans.run/races/2027/hong-kong-queen-mother-memorial-cup-2027/) | G3 | 新增赛历，赛时待公布 |
| 2027-05-23 | [冠军暨遮打杯](https://umafans.run/races/2027/hong-kong-hong-kong-champions-chater-cup-2027/) | G1 | 新增赛历，赛时待公布 |
| 2027-05-30 | [沙田银瓶](https://umafans.run/races/2027/hong-kong-sha-tin-vase-2027/) | G3 | 新增赛历，赛时待公布 |
| 2027-05-30 | [狮子山锦标](https://umafans.run/races/2027/hong-kong-lion-rock-trophy-2027/) | G3 | 新增赛历，赛时待公布 |
| 2027-06-20 | [精英杯](https://umafans.run/races/2027/hong-kong-premier-cup-2027/) | G3 | 新增赛历，赛时待公布 |
| 2027-06-20 | [精英碟](https://umafans.run/races/2027/hong-kong-premier-plate-2027/) | G3 | 新增赛历，赛时待公布 |
