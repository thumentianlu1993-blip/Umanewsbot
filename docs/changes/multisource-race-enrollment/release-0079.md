> 本文为发布准备阶段记录。2026-09-22实际0079部署与JRA激活已完成，当前运行态及自然验收以[最终发布记录](release-20260922/README.md)为准。

# 0079 前向发布包（2026-09-22，准备中）

用户明确要求“上线并发布”。本包对应 PR212，在隔离分支补齐旧0078工具不支持的新迁移发布路径；原脏工作区不变。提交、镜像和最终验收SHA在执行后追加，准备状态不能视作已上线。

## 当前生产基线

本次只读核对：常驻应用 revision `3a174b1e93c499f293deeabfff4dfa71b427a684`，镜像 `sha256:1622560c7f522d5078adbed5049e7bf7ab57e537bff57b97b37df0c83aec57a2`，运行目录 `/opt/umanews-release-3a174b1e-prerefresh-20260919/umanewsbot`；`/opt/umanewsbot` checkout HEAD 不是运行镜像。DB stable leaf0078；web、worker、beat、race_sync_v2_worker运行，race_live_worker未运行，nginx/db/redis/onebot运行；两个域名健康200。103/104/105均未登记、无正式名单及赛果。导入/历史批次/P0/review的数据库活动计数为0；部署前仍需再次检查OS进程、锁和队列。

## 发布动作与边界

- 固定PR212候选commit与image；精确仅0078→0079或0079同schema前向重建。新增两表和四字段；旧登记兼容默认值为1/0/空字符串/空对象，不运行v1转换。
- 新三开关均关闭、独立policy路径/SHA为空；旧开关、预算、registry/policy与15条v1登记保持。
- 单一 `deploy/deploy_0079.sh` 获取共享deployment lock；先做精确schema/catalog预检与本次备份/TOC验证，冻结原服务状态、配置及writer flags。
- 停beat、排空worker、停应用；所有控制容器关闭旧及新writer开关。仅既有 `deploy/docker/run-release-tasks.sh` 拥有DDL：0079迁移、collectstatic、精确完成收据。锁等待5秒、单statement上限300秒。
- 恢复原运行集合，web健康后逐个恢复worker和beat；race-live不新开，基础设施不重建。核对实际镜像、flags、schema、配置、v1准入/公开和外网页面。
- JRA激活与103/104/105补入使用独立配置/固定清单意图，不能修改上述原发布manifest。schema3当前没有event-ID allowlist；关闭discovery的三场处理不能称为持续自动发现。其余地区缺少真实proof时保持关闭。

## 恢复和故障处理

迁移是原子DDL；实际PG16锁超时必须保持0078，重试原intent。禁止用旧0078工具fake、反迁移或通过修改旧contract绕过。中断仅 `deploy/deploy_0079.sh resume`，给原intent path/SHA、原candidate image，不能新建替代备份。原source已变化而marker/receipt丢失时拒绝；ensure→DDL→complete绑定同一device/inode。collectstatic失败保留关闭态，凭原marker继续；receipt存在则不重复DDL/static，验证后恢复余下原服务。启用v2后的异常先关新开关并保留0079和审计数据，不直接降旧镜像。灾难DB恢复仅使用经过真实隔离还原验证的本次dump，需避免覆盖备份后业务增量。

## 本地证据（持续更新）

新增合同覆盖精确migration文件/recorder/catalog、writer关闭、旧协议拒绝、marker丢失和替换、中断边界；PG16实际执行0078→0079、锁超时回滚、同schema重复、旧行默认值、catalog/未知0080拒绝及dump/restore。独立review发现的marker来源丢失、inode连续性、内部FK触发器缺漏和shell插值覆盖Compose四项已修复。新增18项合同/PG16真实升级和备份恢复测试全过；旧0078宿主机/合同43项回归全过；新Linux exact SHA CI尚待执行。生产尚未修改。

## 发布前实网发现并修复的JRA身份问题

2026-09-22 00:59–01:06北京时间从三场现有赛卡URL读取当前页面，真实href的CNAME展示模式已为10，旧缩减fixture为01。此前代码把展示模式并入强ID且用于链接筛选，会错失结果。现在统一完整正则解析，仅去首组01/10展示模式，保留场地/年份/会次/日次/场次/日期；URL场地与页头日文场地、年份/日期全部交叉核验。畸形、重复（含空）CNAME、错path/type及不认识展示模式均拒绝；只跟随唯一真实同场链接，不拼造URL。首次v2未在生产启用，无已有v2 ID迁移。

三场最新结果实际parser通过，103/104/105分别12/13/11匹，与各自赛卡的数量与赛事强ID一致；这只是来源proof，尚非生产A0和公开验收。新增两个回归含01→10同场去重、往绩链接过滤、URL/页头字段不一致与重复query拒绝；JRA+identity 45项通过。URL/抓取时间/字节SHA详见[jra-release-live-proof.json](jra-release-live-proof.json)。

两路独立复审APPROVED：发布marker/host中断、catalog/Compose配置增量与JRA身份修复均闭合。JRA审核实际复核三卡三果raw SHA、同场key及完整马号+规范化马名集合（12/13/11）；35项JRA模块独立通过。聚焦验证和摘要SHA见[本地记录](release-0079-local-validation.json)。接下来固定提交运行Linux发布合同及全量stable同base对照，尚不视作生产已发布。

发布配置补充：两种Compose中web/worker/beat/race-live worker只读挂载既有persistent race_data_sync到`/run/race-data-sync`，sync worker保留原rw；新policy放在其专用子目录，以固定SHA供所有应用读取，不写镜像内临时文件、不借用其他业务目录。初次迁移发布新policy仍为空、三新开关关闭。YAML解析已确认五app路径一致且仅sync worker为rw，Compose变更加入CI触发范围。

## 最终全量CI的静态合同返修

固定2a1c5d0的CI35630788106实际完成：主线5129项有16 failures+29 errors，候选5225项有19 failures+29 errors。逐ID共有45个历史失败，新增恰好3项；分别是同一release task新增0079分支后，旧测试仍预期两条migrate/一条collectstatic，以及用全脚本首个collectstatic错误比较旧分支migrate的顺序。其余新业务与0079真实PG回归没有新增失败。不能将这次CI记为通过。

返修仅调整两份测试：仍限制唯一迁移owner，额外精确枚举0079/0078/初装三个合法命令；分别验证两个世代的迁移、静态收集和完成顺序，0079还核对ensure、marker身份及提前退出。生产代码与发布脚本未变。三个失败用例及两项相邻owner合同共5项本地通过，独立复审与最终CI继续进行；运行服务尚未切换。
