# 2026-09-18 线上验收与回填结果

本次只统计03:08 UTC冻结的132场历史有效缺口及未来7天22场；155条采集输入另含一条正常对照。结果按真实公开状态区分，不把采集、候选入库或代码审核算作上线。所有生产写入均由主线程操作，固定子代理只读审核。

## 已完成

- 历史129/132场、1209行赛果回填：日本20/256、参考来源102/865、尚布利1/7、已退役历史对象6/81。每批固定来源/manifest/脚本SHA、数据库before、逐场事务、备份与生产锁，apply和完整after重放均通过。旧行ID和非目标字段保留，非完赛不伪造名次；第三方不标官方。
- 主域名129个详情页逐页核对全部赛果行，无缺行/排名/马号/显示名错误；验证使用实际公开译名，早期按英文原名匹配的误报已排除。
- JRA103/104/105赛时及12/13/11条名单在两域名公开，105保持“参赛名单，马号待公布”。JRA开关在已发布d0bb40fb的四应用启用；3h/1h/10min和预算不变。人工补跑成功不能算自然tick验收。
- 另9场空赛时与77条已审核候选入库并重放通过：491、492、969、770、771、772共45条，494/495共20条，191共12条。两个域名18页均显示正确北京时间；当前旧应用仍无这77条公开名单，必须待PR205应用发布。
- 191使用NAR正式12匹卡，金沢9月22日18:00日本时间；枠5/6/7/8各两匹按原表rowspan继承，原骑师/练马师简称保留。494/495使用RP单场JSON-LD带时区时间，纽约9月19日16:58/17:48；会议汇总页18日标题错误不采用。495的8号骑师空缺保留。

## 尚未完成

| 范围 | 赛事 | 实际原因与后续约束 |
|---|---|---|
| 历史3场 | 828、830 | 已纳管；TRA原始race_status仍空，暂定行不能冒充正式结果；须原claim/receipt/revision/publication链闭环 |
| 历史3场 | 924 Hackwood | 旧LIVE归属；跟踪关闭且授权/allowlist过期，已有观察不等于发布权；须有效恢复与精确发布合同 |
| 未来10场 | 493 Turf Monster | 商业来源称本届不举办、草地工程推迟；未取得明确官方取消证据，不填假卡也不改cancelled |
| 未来10场 | 496 Gallant Bob | 2026参考卡12条，DRF报道4号Bravaro拟退出；官方营销页却沿用2025十匹名单。来源与最终退赛状态尚未闭环 |
| 未来10场 | 831、832 Auteuil9月22日 | 官方日历确认身份，但11h30为会议时间；单场入口返回登录页，未取得完整名单/精确赛时，不宣称未公布 |
| 未来10场 | 192 NAR9月23日 | 当次仍D−5，尚未取得本场完整正式卡；9月19日进入D−4 |
| 未来10场 | 971 Newmarket9月24日 | 当次D−6，资料取得/核验未完成；9月20日进入D−4 |
| 未来10场 | 972、973、974 Newmarket及497 Beldame9月25日 | 当次D−7，资料取得/核验未完成；9月21日进入D−4 |

当前未来范围22=JRA3+已入库候选9+未补齐10。JRA窄路径不代表NAR/海外持续自动补卡已实现。原表额外9条旧scheduled记录均有active canonical映射，已排除重复缺口；未逐条验证其HTTP重定向与目标内容。

## 来源边界

- [白山大赏典官方卡](https://www.keiba.go.jp/KeibaWeb/TodayRaceInfo/DebaTable?k_babaCode=22&k_raceDate=2026%2F09%2F22&k_raceNo=11)
- [Cotillion单场](https://www.racingpost.com/racecards/578/parx/2026-09-19/928918/)及[Pennsylvania Derby单场](https://www.racingpost.com/racecards/578/parx/2026-09-19/928919/)
- [Gallant Bob当届参考卡](https://truenicks.com/articles/294552/bravaro-takes-on-sprinters-in-gallant-bob-stakes)、[DRF退赛报道](https://www.drf.com/news/sadler-shipping-captivator-crosscountry-gallant-bob)与[2025旧卡对照](https://cms.equibase.com/node/305172)
- [Turf Monster停办线索](https://usracing.com/turf-monster-stakes)、[PTHA延期报道](https://paulickreport.com/news/the-biz/return-of-turf-racing-at-parx-delayed-until-spring-2027)
- [Auteuil官方日历](https://www.france-galop.com/fr/hippodromeauteuil)

完整before、审计PK、控制链/运行态详情与原始源缓存保留在服务器受限artifact目录，不公开提交。仓库仅存公开身份、批次SHA、数量、验证结论。

## 运行态及验证

04:18 UTC八服务running、restart=0、OOM=false，web/db/redis healthy；四应用同677fe69f镜像、web实际d0bb40fb/JRA=true，DB只读SELECT通过。队列celery18、race_sync_v2=0、旧race_live7543；这是单次采样，未据此宣称队列全链无积压。采样时部署锁已释放。103下一due04:23，104/105为06:23；该时点尚未自然tick验收。

PR205加入参考及NAR人工核验候选的只读展示，正式卡接管整份隐藏；通用apply服务层按source_name或raw_payload标记拒绝，防止后台绕过候选路径写canonical。NAR官方label与参考域authority双向约束。无新表、无迁移、无新的定时来源系统。独立代码/source审核通过；测试和CI最新状态见发布包，不把旧提交CI当最终提交全绿。
