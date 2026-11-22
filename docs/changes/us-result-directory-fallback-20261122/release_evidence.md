# 美国三场正式赛果恢复发布实况

## 固定版本与交付证据

2026-11-22用户批准合并并执行精确发布包后，PR #331合并为
`0e45b16d945ca0d300c79becddc729f292d0479e`；合并树与CI受测树
`3f5ed5b3285494776d56cf5f1f4765c0d2219632`一致。生产六应用运行候选
`bdf9c99df39b3df4709e23a5d6f320e13fcd1723`。

- Linux隔离CI run44987166515：440项全部通过，零跳过；受信外部核验器收据verified。
- 独立只读代码与发布脚本review通过；代码指纹前后相同。
- 候选镜像1398个仓库运行文件与固定Git提交逐字节一致。
- 发布包SHA：`12e4f27e304a7bffbcf5abeddbe9d90ac4fe1609a4027b88a5b647349e2673a2`。
- OCI运行镜像：`sha256:baed84a54959ce18bbfb8abe2284fc022d48648e40439fc720bf4ff435ecf6e1`；
  镜像config digest：`sha256:4545b3c7e22d02e280911d397be8ad2c47f5054b80f09192545988e302e7e3a4`。

## 发布与恢复面

在精确生产配置/基线核验、schema及384MiB英国收据只读预检通过后，停Beat并等待worker自然排空。
完整数据库备份1,270,304,177字节，TOC校验通过并fsync，SHA：
`2be26a629dd364c39df64b2beced89bc7c1483416165c7075224287c23d18e5c`。
随后重建web、default/collect/control/live worker及Beat，Nginx配置检查/reload、公网health通过。
北京时间13:56前服务切换完成、发布锁已释放。无迁移、业务配置、配额或功能开关变化，未重置退避。

云端私有目录 `/opt/umanews-external-staging/us-directory-bdf9c99d` 保存绑定包、控制器收据、
备份/TOC、完整旧Compose和镜像身份；独立业务回滚入口为该目录的 `business_rollback.py`，
参数必须为上述完整包SHA。回滚目标为之前的a601d973，OCI镜像
`sha256:ff646044d79a97593eff2beb9998f91f72e7d7b7b9de1eef14c61623a694d3cc`；
应用回滚保留已正确自然产生的数据。此次未执行回滚。

## 实际业务验收

三场按既有自然轮询于北京时间13:56:28、13:56:47、13:57:03完成正式确认；
全部status=finished，结果检查点成功且错误清零。没有手工插入赛果或重置检查点。

| 赛事 | 完赛 | 退赛 | 当前正式revision | 公网验证 |
| --- | ---: | ---: | ---: | --- |
| 568 小石子锦标 | 10 | 0 | 1925 | [公开页](https://umafans.run/races/2026/us-toba-2026-1121-359/) |
| 598 英联邦草地锦标 | 7 | 2 | 1926 | [公开页](https://umafans.run/races/2026/us-toba-2026-undated-389/) |
| 602 本土潜水员锦标 | 8 | 0 | 1927 | [公开页](https://umafans.run/races/2026/us-toba-2026-undated-393/) |

逐马核对27条记录的马号、姓名、状态、骑练、报告名次、官方名次与is_confirmed；
当前公开revision存在正式确认时间和publication，公开读判定visible且为official。
对实际公网HTML的27行名次、马号、显示马名逐项比较，全部一致且HTTP200。
英联邦草地锦标退赛为6号Beautiful War和9号No Joke Joe，未伪装成完赛名次。

13:57:42六服务镜像/提交一致、健康检查通过、重启和cgroup oom/oom_kill均0。
五场既有补时、10条时间权威及10条变更审计完全保持；法国20902/20904名称未变。
569保留6匹名单，未来结果尚未到期；JRA128与香港三场及法国两场名单保持。
原监测 `umanews-monitor-20261122.service` 持续active、NRestarts=0，未改其证据或报告游标。

## 保留的其他缺口

Colonial Cup仍未有正式名单，本次平地赛目录回退不解决NSA正式卡表的来源403；
既有9匹overnight原件不能充当带正式马号的卡表。未来赛事无赛果不是异常。
英国21005仍待既有14:17发现退避到期后的业务消费；本次没有加速其检查点。
爱尔兰三场仍没有受审来源路由，并维持既有非公开范围。

本地审计原件与收据位于本任务runtime的 `race-gaps-20261122/us-followup/`；
包括delivery-receipt、release-package、backup-identity、us-after-2、us-verification-final、
三份公网HTML、protected-before/after和services-after-2。后续实时状态以新采样为准。
