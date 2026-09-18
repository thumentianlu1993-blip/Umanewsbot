# 2026-09-19 PR209 生产发布与验收

PR209首次发布及失败记录保留于下文；PR210已完成前向修复及两轮自然验收，以本节为准。用户已明确授权上线，主线程执行、固定只读子代理审核。历史828/830/924继续暂缓。

## PR210 最终前向发布与自然验收

[PR210](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/210)合并`63e5b58a645b39b194c2d5c305e4530bf7d42c58`，固定应用`3a174b1e93c499f293deeabfff4dfa71b427a684`。本轮[完整CI](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/35396515963)5129项：16 failures / 29 errors / 20 skipped，无新增失败；发布合同45项通过。主线程与固定reviewer独立复算官方ZIP摘要、内部SHA、完整失败集合及指纹，APPROVED。三个测试作业完成成功，汇总job当时仍运行，未冒充通过。[工件摘要](ci-scope-fix-summary.json)。

22:05:10～22:09:22 UTC完成既有0078发布，根目录`/opt/umanews-release-3a174b1e-prerefresh-20260919/umanewsbot`，实际镜像`sha256:1622560c7f522d5078adbed5049e7bf7ab57e537bff57b97b37df0c83aec57a2`。配置与PR209完全相同；四应用实际版本和开关、八服务运行/健康、基础设施原容器保留、无迁移、锁及恢复标记收尾均验证通过。备份564247132字节，SHA256 `73d7bcf1976255f065bac31bfd589201bffa9384823abf878107760d22a1fa29`；intent SHA256 `4e6d9b564881b96c23037935ec2b7352a225683170c8550396b2b8d8bcdced3f`，完整私有备份/日志留服务器。核验队列{'celery': 23, 'race_sync_v2': 0, 'race_live': 7543}，不宣称普通队列无积压。

双域名26公开请求全部200，无当地时间/旧标题。492自然成功时间`2026-09-18T22:17:04.468985+00:00`→`2026-09-18T22:27:03.954342+00:00`，9匹表保留、3号退赛、8匹有效赔率；实际检查点、候选时间和公开更新时间推进，两次页面一致，不要求来源赔率数值凭空变化。未手工调用任务、重置时钟或人工回填参赛行。969也恢复长链接来源读取；103 JRA后续固定10min检查点正常。两次自然原始记录仅从服务器提取限定公开字段，[摘要](production-summary.json)保留完整时间。

纳管772于21:29:26成功、比旧到期21:21:42晚约8分钟；跨阶段22:00到期后22:15:15成功，期间经历发布暂停且普通celery队列有积压。记录实际延迟，不把队列积压视为已完全证明的唯一根因；本轮未扩展队列架构改造。772后续22:26:18再次成功，距22:15:15约11分钟；可确认D0持续推进，仍不称所有地区长周期均已完整验收。491已过赛前截止、不强行回到赛前；RP494/495的406、部分来源未发布价格及历史828/830/924仍按原范围保留。马匹采集不恢复。

## PR209 当时版本与全量测试

- [PR209](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/209) 已合并为`8e0e6c9f13b3a9709cd8b3e550745c14ba179b66`。
- 固定应用`2c8fa8e4ec91d0ba3a32529839cff8f1a4d68615`；[CI35391358462](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/35391358462)完整运行5128项，16 failures / 29 errors / 20 skipped。45个失败ID与当前生产参考完全一致，对同run历史基线也无新增；不是全量全绿。
- 45项发布与恢复合同全部通过，Django check正常、无迁移漂移，前后指纹均`368c39ea33f7b938409c1421a26343892043d71046c3ec2549619a878b65fd48`。
- 三份官方ZIP按摘要、run/head、工件内commit及完整结果独立复核，原reviewer APPROVED。三个测试作业completed/success；GitHub汇总job当时in_progress，未算作通过。完整公开摘要见[ci-summary.json](ci-summary.json)。
- 首完整候选801的旧Beat断言是唯一新增失败；修正测试为真实07/17节拍，并追加下一轮公平处理/快照复用，77项相关测试通过。最终全套已证明新增失败消除；没有改应用逻辑来迎合旧断言。

## 实际发布与恢复边界

- 2026-09-18 21:05:45～21:09:57 UTC（北京时间9月19日05:05～05:09）通过`deploy/deploy_lowcost.sh`及0078协调器完成发布，无模型迁移。
- 运行目录`/opt/umanews-release-2c8fa8e4-prerefresh-20260919/umanewsbot`；实际四应用镜像`sha256:214537d25f1e0adf6a740e724be627835ab5287a07fe3a6d56a6c5a8220648f2`。四应用image label、版本文件、有效Django设置均匹配固定应用提交。
- 本次仅改变`RACE_DATA_SYNC_PRE_RACE_REFRESH_ENABLED=true`及`RACE_DATA_RAW_DAILY_PROVIDER_REGION_REQUESTS=512`。日字节上限仍1073741824，JRA和展示开关继续开启，其他配置一致。全局每provider/region桶请求上限512兼容同桶多场和按2MiB计的失败预留；不增加3h/1h/10min频率，不新增付费服务或搜索覆盖。
- 预检确认旧433de627仍在运行，无活动导入、未完成导入、历史运行批次、采集进程及发布锁；磁盘45.6GiB可用。先创建并核验专属备份，再停Beat、排空两个worker、闭合写入、执行空迁移/静态文件并恢复服务。
- 备份564044366字节，SHA256 `da1a4666ad2839b909bbb4dfffb7c71312e356bc6c6ace40fa20faacbde449ac`。intent目录`5217aec9f1361783b73ec3d5904c8909101a60fcdf4b23512d29be0de862acf6`，intent SHA256 `964108e92d2cd6a887e942c4864013aaef412fcb1098262ebb8f64bd147f5bb3`；完整备份/manifest/complete及日志留服务器，不上传仓库。
- 八服务运行、Web/DB/Redis健康，DB/Redis/Nginx/OneBot容器保留；迁移计划为空，锁、active和restricted恢复标记均清理。初始队列celery=18、race_sync_v2=0、旧race_live=7543未消费，不能把启动快照称全部队列为空。
- 停用新刷新需关闭flag，经受保护流程重载四应用并确认旧在途任务退出；不普通切旧镜像或恢复整库。马匹采集保持暂停。

## 真实来源与公开页面

Sporting Life真实HTTP预演暴露UTC日期及退赛后的有效计数差异，先补RED测试、再修合同并由同一reviewer复审。491原来源能明确给出3/5/6号退赛，故取消NYRA人工绑定；生产NYRA403，未执行该绑定写入。最终候选镜像真实只读预演：492为9行、3号退赛且9条来源价格；NAR191为12行、来源未发布价格。生产业务写入为0的预演不等于自然任务已经工作。

切换后双域名26个请求（健康、首页、日历及10场详情）全部200；详情无当地时间或旧出马表标题，未知条件隐藏。491公开北京日期9月19日04:14，状态“赛期已过，资料待补”；已经越过预览公开/刷新窗口，不强行改回赛前，赛后资料仍缺。492为9月19日08:36，772为9月19日21:50。候选数据库查询已核对跨地区北京瞬时排序；默认日历仍保留既有筛选口径。

## PR209 首次自然周期验收（修复前记录）

初始快照21:10 UTC：492尚无新刷新状态，公开9匹仍为旧名单/空赔率并正确提示更新延迟；772保留8条正式runner、预览刷新不符合条件。后续按真实Beat触发观察，不手工调用刷新、不改赛事时间或调度时钟。

- 未纳管D0两轮：等待实际检查点和双域名字段证据。
- 已纳管772：次轮计划21:21:42 UTC，D−1按小时；尚未证明两轮自然周期。
- JRA103旧检查点为21:17:02，第一次新节拍仍可能遇到旧持久化到期秒数；以实际后续检查为准，不提前宣称已连续10分钟。
- Racing Post494/495生产HTTP406仍为覆盖缺口；不得把身份检查或HTTP失败当成出马表成功更新。
- 没有可用来源、未发布价格或未观察完整长周期的范围继续明确保留，不称所有赛事资料已补齐。

机器可读运行摘要见[production-summary.json](production-summary.json)，测试摘要见[validation-summary.json](validation-summary.json)。

## 首轮自然失败与最小前向修复

21:17 UTC定时任务自动触发，492在约70ms内失败，reason=refresh_source_parse_failed，无新自动卡，两个域名仍保留旧名单并提示更新延迟。只读证据确认492/969 URL长度分别140/154，Sporting Life美国无新增请求预算记录；共享缓存scope限制128，在HTTP前即报ValueError。其他来源及旧卡未被错误覆盖。

修复仅对超过128字符的URL取`html:`+SHA256作scope，合法短key维持原样；HTTP地址、registry digest、来源/身份/退赛规则不变。新增真实discovery→lease→预算→临时落盘→解析→候选/公开预览的集成测试，只替代HTTP响应。原版本1项RED复现checked=0；修后67项相关GREEN，覆盖同URL缓存复用、观测时间、不同长URL隔离、原URL证据及完整退赛行；同一reviewer APPROVED。当时新提交全量CI及前向发布待执行（后续结果见顶部PR210记录），不把2c8fa8e4的完整结果冒充新版本验证。
