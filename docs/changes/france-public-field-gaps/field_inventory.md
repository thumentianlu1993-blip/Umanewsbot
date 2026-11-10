# 法国字段缺口台账与示例

本轮为只读调查/方案。正式库快照：2026-11-10 09:20 北京时间；四个公网样例复查09:23。范围80场。原始来源档案主要采于11月9日，59场历史Geny与21场未来France Galop，不冒称本轮全部源站重新访问。

**更新：空中锦标开赛时间已由自然正式接管写入，当前公开23:25。上轮04:29的“待定”已不再成立。**

方案修订（2026-11-10，用户明确确定）：抓到有效开赛时间后同轮更新正式记录与详情/日历，不等待正式卡接管；下列09:20/09:23数据仍作为修复前事实快照。

“已采集”分别指：①原始可见页面/表格已保存；②已解析进入候选或来源观测；③已落正式业务字段。以下不会混用这三者。

| 字段 | 当前影响 | 是否采集/入库 | 具体示例与正确含义 |
|---|---|---|---|
| 距离/单位 | 80场都显示待核实 | 距离正式值已入库；单位来源证据未衔接展示 | [空中锦标](https://umafans.run/races/2026/fr-france-galop-2026-1111-111/)（[来源](https://www.france-galop.com/fr/course/detail/2026/P/KzBJdEZJZlVQWC9EbkRVZExvdnRBUT09)）：2100m已存，源为2.100 mètres，应显示2100米 |
| 历史开赛时刻 | 47场正式时间空；12场旧值待来源对照 | 59场归档有钟点，但没记录采集时区；历史observation的off_time为空，不能直接换算 | [雅兰堡大赛](https://umafans.run/races/2026/fr-france-galop-2026-0903-074/)（[来源](https://www.geny.com/course/1681046-2026-09-03-parislongchamp-prix-d-arenberg/arrivee-rapports)）：原文Départ15h40，网站待定；需新带时区证据后才能写北京时间 |
| 未来开赛时刻 | 当前空中锦标已正常；另20场源快照00h00 | 空中已从候选到正式库/公开23:25；其余00h00是未公布 | [空中锦标](https://umafans.run/races/2026/fr-france-galop-2026-1111-111/)（[来源](https://www.france-galop.com/fr/course/detail/2026/P/KzBJdEZJZlVQWC9EbkRVZExvdnRBUT09)）；未来未知不按午夜补值 |
| 冠军完成时间 | 59场冠军都显示待核实 | 59个原值已进入正式赛果；展示解析不支持法式格式 | [雅兰堡大赛](https://umafans.run/races/2026/fr-france-galop-2026-0903-074/)（[来源](https://www.geny.com/course/1681046-2026-09-03-parislongchamp-prix-d-arenberg/arrivee-rapports)）：Drazinda，0'55"10，应显示55.10秒 |
| 赛种及细分 | 50场空，30场仅泛称障碍 | 40场flat已结构化但展示未读；10AQPS未结构化；原文80场可分50平地、16栏架、14Steeple | [Robert Lejeune](https://umafans.run/races/2026/fr-france-galop-2026-0917-144/)（[来源](https://www.geny.com/course/1684415-2026-09-17-auteuil-prix-robert-lejeune/arrivee-rapports)）：Haies；[Avenir](https://umafans.run/races/2026/fr-2026-aqps-avenir/)（[来源](https://www.geny.com/course/1695527-2026-11-02-nantes-prix-de-l-avenir/arrivee-rapports)）：Plat/AQPS，应为平地，AQPS另列类别 |
| 场地材质 | 30场待核实、10场空 | 原文59历史场有Gazon；其中22场当前展示缺口；剩余18个未来缺口待取明确材质证据 | [Robert Lejeune](https://umafans.run/races/2026/fr-france-galop-2026-0917-144/)（[来源](https://www.geny.com/course/1684415-2026-09-17-auteuil-prix-robert-lejeune/arrivee-rapports)）：Gazon已抓原文，正式surface却为jumps；应草地，与栏架赛种分开 |
| 跑道方向 | 80场方向字段空，公开模板未展示 | 65场原文明确，未结构化；15场当前源档未明确 | [空中锦标](https://umafans.run/races/2026/fr-france-galop-2026-1111-111/)（[来源](https://www.france-galop.com/fr/course/detail/2026/P/KzBJdEZJZlVQWC9EbkRVZExvdnRBUT09)）：Corde à DROITE=右转；[Avenir](https://umafans.run/races/2026/fr-2026-aqps-avenir/)（[来源](https://www.geny.com/course/1695527-2026-11-02-nantes-prix-de-l-avenir/arrivee-rapports)）：Gauche=左转 |
| 场地状况/测量值 | going_text 80空 | 59历史场原文已保存Terrain及Pén，未解析；21未来快照无证据 | [雅兰堡大赛](https://umafans.run/races/2026/fr-france-galop-2026-0903-074/)（[来源](https://www.geny.com/course/1681046-2026-09-03-parislongchamp-prix-d-arenberg/arrivee-rapports)）：Souple(Pén:3.7)，不是“天气”；应保留法国尺度和原文 |
| 总奖金/币种 | 80场业务/公开无奖金 | 80场有原文金额；59Geny显式€，21FG需核币种合同；RaceEvent无奖金字段，模板无入口 | [空中锦标](https://umafans.run/races/2026/fr-france-galop-2026-1111-111/)（[来源](https://www.france-galop.com/fr/course/detail/2026/P/KzBJdEZJZlVQWC9EbkRVZExvdnRBUT09)）：€73,200；128,100/106,140是带马主补贴的不同金额，不能混用 |
| 完整参赛条件 | eligibility_text80空 | 80场原文已存，未结构化入库；现有255字符长度也不足承载部分完整条件 | [空中锦标](https://umafans.run/races/2026/fr-france-galop-2026-1111-111/)（[来源](https://www.france-galop.com/fr/course/detail/2026/P/KzBJdEZJZlVQWC9EbkRVZExvdnRBUT09)）：3岁及以上雌马、当年未赢G2及加磅条款 |
| 年龄/性别/资格限制 | minimum_age80空；sex为unknown或空；constraints80空 | 原始条件可解析，正式结构化未完成 | [Magalen Bryant](https://umafans.run/races/2026/fr-france-galop-2026-1114-159/)（[来源](https://www.france-galop.com/fr/course/detail/2026/O/czRJaXVnRmFLMnlyYStmblBLU2VtZz09)）：仅3岁雌马；[Avenir](https://umafans.run/races/2026/fr-2026-aqps-avenir/)（[来源](https://www.geny.com/course/1695527-2026-11-02-nantes-prix-de-l-avenir/arrivee-rapports)）：3岁AQPS马 |
| 旧卡表练马师 | 10场80匹空 | 独立卡源/赛果均已采并有结果入库，runner未补缺 | [Robert Lejeune](https://umafans.run/races/2026/fr-france-galop-2026-0917-144/)（[来源](https://www.geny.com/course/1684415-2026-09-17-auteuil-prix-robert-lejeune/arrivee-rapports)）：1号Huron Bleu应为D. Bressou，卡表空而赛果有 |
| 旧卡表负重 | 同10场80匹空 | 独立卡Poids已采，不能用结果实际负重盲填 | 同场Huron Bleu为68kg；[Bertrand de Tarragon](https://umafans.run/races/2026/fr-france-galop-2026-0919-088/)（[来源](https://www.geny.com/course/1684923-2026-09-19-chantilly-prix-bertrand-de-tarragon-fonds-europeen-de-l-elevage/arrivee-rapports)）：Gaga Girl分配58.5kg |
| 旧卡表赔率 | 同10场80匹空 | 独立卡/结果Genybet报价已采，runner未补值和平台/时刻 | 同场Huron Bleu为1.4；只补对应卡源报价并标时间，不冒充实时赔率 |

## 不应算作已确认漏采

- 热门排名：511行空，但目前Geny可见表不提供独立官方热门名次；不得直接用赔率排序补造。
- 非冠军完成时间：452行空，当前来源未给该字段，不由差距估算。
- 当前未来赔率：空中锦标源表当时也无报价，网站空值合理。
- 天气：现有证据没有独立天气字段；Terrain是场况，不能当作天气。
- 未出赛/差距：25个非完赛状态正确；2匹未出赛不要求赔率；冠军与非完赛无相邻差距不算缺口；427个非空相邻差距已可显示。
- 没有名单的10场：此次未新增逐场实时公告复查；保留自然调度not_published证据，不能在方案中改成漏采或造出马表。

## 来源另有、但需单独定义产品用途的扩展字段

Geny卡表保留了SA（性别/年龄）、Musique（往绩）、Valeur（评分）、配备栏目、PMU与Genybet双报价；France Galop原表还含马主、训练地/国家、奖金收入。当前法国解析器主要提取马名/号码/闸位/骑师/练马师/负重/单平台赔率，以上额外栏多停留在原始表。它们不等同本轮现有页面故障，也不自动扩大到马匹档案/身份合并/多平台报价产品。建议在本轮字段闭环后单列扩展，不把其完成作为本次修复前置。

## 旧卡表全部受影响赛事

| 赛事 | 行数 | 当前缺项 |
|---|---:|---|
| [PRIX ROBERT LEJEUNE](https://umafans.run/races/2026/fr-france-galop-2026-0917-144/)（[来源](https://www.geny.com/course/1684415-2026-09-17-auteuil-prix-robert-lejeune/arrivee-rapports)） | 7 | 练马师、负重、赔率 |
| [PRIX DE COMPIEGNE](https://umafans.run/races/2026/fr-france-galop-2026-0917-146/)（[来源](https://www.geny.com/course/1684418-2026-09-17-auteuil-prix-de-compiegne/arrivee-rapports)） | 5 | 练马师、负重、赔率 |
| [PRIX BERTRAND DE TARRAGON - FONDS EUROPEEN DE L ’ELEVAGE](https://umafans.run/races/2026/fr-france-galop-2026-0919-088/)（[来源](https://www.geny.com/course/1684923-2026-09-19-chantilly-prix-bertrand-de-tarragon-fonds-europeen-de-l-elevage/arrivee-rapports)） | 8 | 练马师、负重、赔率 |
| [PRIX DE MAISONS-LAFFITTE](https://umafans.run/races/2026/fr-france-galop-2026-0926-149/)（[来源](https://www.geny.com/course/1686555-2026-09-26-auteuil-prix-de-maisons-laffitte/arrivee-rapports)） | 8 | 练马师、负重、赔率 |
| [CRITERIUM DE MAISONS-LAFFITTE](https://umafans.run/races/2026/fr-france-galop-2026-1010-101/)（[来源](https://www.geny.com/course/1690162-2026-10-10-chantilly-criterium-de-maisons-laffitte/arrivee-rapports)） | 6 | 练马师、负重、赔率 |
| [PRIX PIERRE DE LASSUS](https://umafans.run/races/2026/fr-france-galop-2026-1017-155/)（[来源](https://www.geny.com/course/1691901-2026-10-17-auteuil-prix-pierre-de-lassus/arrivee-rapports)） | 7 | 练马师、负重、赔率 |
| [PRIX ORCADA](https://umafans.run/races/2026/fr-france-galop-2026-1017-156/)（[来源](https://www.geny.com/course/1691898-2026-10-17-auteuil-prix-orcada/arrivee-rapports)） | 7 | 练马师、负重、赔率 |
| [PRIX HEROS XII](https://umafans.run/races/2026/fr-france-galop-2026-1017-157/)（[来源](https://www.geny.com/course/1691902-2026-10-17-auteuil-prix-heros-xii/arrivee-rapports)） | 10 | 练马师、负重、赔率 |
| [PRIX DE FLORE](https://umafans.run/races/2026/fr-france-galop-2026-1025-106/)（[来源](https://www.geny.com/course/1693858-2026-10-25-saint-cloud-prix-de-flore/arrivee-rapports)） | 9 | 练马师、负重、赔率 |
| [PRIX BELLE DE NUIT](https://umafans.run/races/2026/fr-france-galop-2026-1025-107/)（[来源](https://www.geny.com/course/1693864-2026-10-25-saint-cloud-prix-belle-de-nuit/arrivee-rapports)） | 13 | 练马师、负重、赔率 |

## 全80场逐场台账

原文证据列不是上线完成列。“时刻未公布”指档案00h00；“有钟点/缺采集时区”必须重新取证，不能直接补写。原文列采用保存的页面头部，未将侧栏/广告内容当比赛字段。

| 赛事/来源 | 正式时间 | 原文有的基础字段 | 当前主要缺口 |
|---|---|---|---|
| [PRIX D’ARENBERG](https://umafans.run/races/2026/fr-france-galop-2026-0903-074/)（[来源](https://www.geny.com/course/1681046-2026-09-03-parislongchamp-prix-d-arenberg/arrivee-rapports)） | 待定/原文钟点缺时区 | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种、方向、场况 |
| [PRIX GERALD DE GEOFFRE](https://umafans.run/races/2026/fr-france-galop-2026-0903-075/)（[来源](https://www.geny.com/course/1681050-2026-09-03-parislongchamp-prix-gerald-de-geoffre/arrivee-rapports)） | 待定/原文钟点缺时区 | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种、方向、场况 |
| [QATAR PRIX NIEL](https://umafans.run/races/2026/fr-france-galop-2026-0906-076/)（[来源](https://www.geny.com/course/1681878-2026-09-06-parislongchamp-qatar-prix-niel/arrivee-rapports)） | 待定/原文钟点缺时区 | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种、方向、场况 |
| [QATAR PRIX DU MOULIN DE LONGCHAMP](https://umafans.run/races/2026/fr-france-galop-2026-0906-077/)（[来源](https://www.geny.com/course/1681877-2026-09-06-parislongchamp-qatar-prix-du-moulin-de-longchamp/arrivee-rapports)） | 待定/原文钟点缺时区 | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种、方向、场况 |
| [QATAR PRIX VERMEILLE](https://umafans.run/races/2026/fr-france-galop-2026-0906-078/)（[来源](https://www.geny.com/course/1681876-2026-09-06-parislongchamp-qatar-prix-vermeille/arrivee-rapports)） | 待定/原文钟点缺时区 | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种、方向、场况 |
| [QATAR PRIX FOY](https://umafans.run/races/2026/fr-france-galop-2026-0906-079/)（[来源](https://www.geny.com/course/1681879-2026-09-06-parislongchamp-qatar-prix-foy/arrivee-rapports)） | 待定/原文钟点缺时区 | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种、方向、场况 |
| [QATAR PRIX D’AUMALE](https://umafans.run/races/2026/fr-france-galop-2026-0906-080/)（[来源](https://www.geny.com/course/1681874-2026-09-06-parislongchamp-qatar-prix-d-aumale/arrivee-rapports)） | 待定/原文钟点缺时区 | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种、方向、场况 |
| [QATAR PRIX LA ROCHETTE](https://umafans.run/races/2026/fr-france-galop-2026-0906-081/)（[来源](https://www.geny.com/course/1681873-2026-09-06-parislongchamp-qatar-prix-la-rochette/arrivee-rapports)） | 待定/原文钟点缺时区 | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种、方向、场况 |
| [PRIX GLADIATEUR](https://umafans.run/races/2026/fr-france-galop-2026-0910-082/)（[来源](https://www.geny.com/course/1682652-2026-09-10-parislongchamp-prix-gladiateur/arrivee-rapports)） | 待定/原文钟点缺时区 | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种、方向、场况 |
| [PRIX DU PRINCE D’ORANGE](https://umafans.run/races/2026/fr-france-galop-2026-0913-083/)（[来源](https://www.geny.com/course/1683642-2026-09-13-parislongchamp-prix-du-prince-d-orange/arrivee-rapports)） | 待定/原文钟点缺时区 | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种、方向、场况 |
| [PRIX DU PIN](https://umafans.run/races/2026/fr-france-galop-2026-0913-084/)（[来源](https://www.geny.com/course/1683641-2026-09-13-parislongchamp-dubai-racing-carnival-prix-du-pin/arrivee-rapports)） | 待定/原文钟点缺时区 | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种、方向、场况 |
| [PRIX DU PETIT COUVERT](https://umafans.run/races/2026/fr-france-galop-2026-0913-085/)（[来源](https://www.geny.com/course/1683639-2026-09-13-parislongchamp-prix-du-petit-couvert/arrivee-rapports)） | 待定/原文钟点缺时区 | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种、方向、场况 |
| [PRIX ECLIPSE - FONDS EUROPEEN DE L ’ELEVAGE](https://umafans.run/races/2026/fr-france-galop-2026-0919-086/)（[来源](https://www.geny.com/course/1684921-2026-09-19-chantilly-prix-eclipse-tattersalls-fonds-europeen-de-l-elevage/arrivee-rapports)） | 20:33（北京时间） | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种、方向、场况 |
| [PRIX DES CHENES - FONDS EUROPEEN DE L ’ELEVAGE](https://umafans.run/races/2026/fr-france-galop-2026-0919-087/)（[来源](https://www.geny.com/course/1684920-2026-09-19-chantilly-prix-des-chenes-tattersalls-fonds-europeen-de-l-elevage/arrivee-rapports)） | 19:58（北京时间） | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种、方向、场况 |
| [PRIX BERTRAND DE TARRAGON - FONDS EUROPEEN DE L ’ELEVAGE](https://umafans.run/races/2026/fr-france-galop-2026-0919-088/)（[来源](https://www.geny.com/course/1684923-2026-09-19-chantilly-prix-bertrand-de-tarragon-fonds-europeen-de-l-elevage/arrivee-rapports)） | 21:50（北京时间） | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种、方向、场况、旧卡表三项 |
| [PRIX DE CONDE](https://umafans.run/races/2026/fr-france-galop-2026-1002-089/)（[来源](https://www.geny.com/course/1688147-2026-10-02-saint-cloud-prix-de-conde-jockey-club-de-turquie/arrivee-rapports)） | 待定/原文钟点缺时区 | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种、方向、场况 |
| [QATAR PRIX CHAUDENAY](https://umafans.run/races/2026/fr-france-galop-2026-1003-090/)（[来源](https://www.geny.com/course/1688533-2026-10-03-parislongchamp-qatar-prix-chaudenay/arrivee-rapports)） | 待定/原文钟点缺时区 | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种、方向、场况 |
| [QATAR PRIX DANIEL WILDENSTEIN](https://umafans.run/races/2026/fr-france-galop-2026-1003-091/)（[来源](https://www.geny.com/course/1688540-2026-10-03-parislongchamp-qatar-prix-daniel-wildenstein/arrivee-rapports)） | 待定/原文钟点缺时区 | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种、方向、场况 |
| [QATAR PRIX DOLLAR](https://umafans.run/races/2026/fr-france-galop-2026-1003-092/)（[来源](https://www.geny.com/course/1688534-2026-10-03-parislongchamp-qatar-prix-dollar/arrivee-rapports)） | 待定/原文钟点缺时区 | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种、方向、场况 |
| [QATAR PRIX DE ROYALLIEU](https://umafans.run/races/2026/fr-france-galop-2026-1003-093/)（[来源](https://www.geny.com/course/1688538-2026-10-03-parislongchamp-qatar-prix-de-royallieu/arrivee-rapports)） | 待定/原文钟点缺时区 | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种、方向、场况 |
| [QATAR PRIX DU CADRAN](https://umafans.run/races/2026/fr-france-galop-2026-1003-094/)（[来源](https://www.geny.com/course/1688539-2026-10-03-parislongchamp-qatar-prix-du-cadran/arrivee-rapports)） | 待定/原文钟点缺时区 | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种、方向、场况 |
| [QATAR PRIX JEAN-LUC LAGARDERE](https://umafans.run/races/2026/fr-france-galop-2026-1004-095/)（[来源](https://www.geny.com/course/1688797-2026-10-04-parislongchamp-qatar-prix-jean-luc-lagardere/arrivee-rapports)） | 待定/原文钟点缺时区 | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种、方向、场况 |
| [QATAR PRIX MARCEL BOUSSAC - CRITERIUM DES POULICHES](https://umafans.run/races/2026/fr-france-galop-2026-1004-096/)（[来源](https://www.geny.com/course/1688796-2026-10-04-parislongchamp-qatar-prix-marcel-boussac-criterium-des-pouliches/arrivee-rapports)） | 待定/原文钟点缺时区 | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种、方向、场况 |
| [PRIX DE L ’ABBAYE DE LONGCHAMP LONGINES](https://umafans.run/races/2026/fr-france-galop-2026-1004-097/)（[来源](https://www.geny.com/course/1688798-2026-10-04-parislongchamp-prix-de-l-abbaye-de-longchamp-longines/arrivee-rapports)） | 待定/原文钟点缺时区 | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种、方向、场况 |
| [PRIX DE L ’OPERA LONGINES](https://umafans.run/races/2026/fr-france-galop-2026-1004-098/)（[来源](https://www.geny.com/course/1688801-2026-10-04-parislongchamp-prix-de-l-0pera-longines/arrivee-rapports)） | 待定/原文钟点缺时区 | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种、方向、场况 |
| [QATAR PRIX DE LA FORET](https://umafans.run/races/2026/fr-france-galop-2026-1004-099/)（[来源](https://www.geny.com/course/1688802-2026-10-04-parislongchamp-qatar-prix-de-la-foret/arrivee-rapports)） | 待定/原文钟点缺时区 | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种、方向、场况 |
| [QATAR PRIX DE L ’ARC DE TRIOMPHE](https://umafans.run/races/2026/fr-france-galop-2026-1004-100/)（[来源](https://www.geny.com/course/1688800-2026-10-04-parislongchamp-qatar-prix-de-l-arc-de-triomphe/arrivee-rapports)） | 待定/原文钟点缺时区 | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种、方向、场况 |
| [CRITERIUM DE MAISONS-LAFFITTE](https://umafans.run/races/2026/fr-france-galop-2026-1010-101/)（[来源](https://www.geny.com/course/1690162-2026-10-10-chantilly-criterium-de-maisons-laffitte/arrivee-rapports)） | 21:32（北京时间） | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种、方向、场况、旧卡表三项 |
| [PRIX DU CONSEIL DE PARIS](https://umafans.run/races/2026/fr-france-galop-2026-1018-102/)（[来源](https://www.geny.com/course/1692084-2026-10-18-parislongchamp-prix-du-conseil-de-paris/arrivee-rapports)） | 待定/原文钟点缺时区 | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种、方向、场况 |
| [CRITERIUM INTERNATIONAL](https://umafans.run/races/2026/fr-france-galop-2026-1025-103/)（[来源](https://www.geny.com/course/1693859-2026-10-25-saint-cloud-criterium-international/arrivee-rapports)） | 待定/原文钟点缺时区 | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种、方向、场况 |
| [CRITERIUM DE SAINT -CLOUD](https://umafans.run/races/2026/fr-france-galop-2026-1025-104/)（[来源](https://www.geny.com/course/1693861-2026-10-25-saint-cloud-criterium-de-saint-cloud/arrivee-rapports)） | 待定/原文钟点缺时区 | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种、方向、场况 |
| [PRIX PERTH](https://umafans.run/races/2026/fr-france-galop-2026-1025-105/)（[来源](https://www.geny.com/course/1693860-2026-10-25-saint-cloud-prix-perth/arrivee-rapports)） | 待定/原文钟点缺时区 | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种、方向、场况 |
| [PRIX DE FLORE](https://umafans.run/races/2026/fr-france-galop-2026-1025-106/)（[来源](https://www.geny.com/course/1693858-2026-10-25-saint-cloud-prix-de-flore/arrivee-rapports)） | 19:48（北京时间） | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种、方向、场况、旧卡表三项 |
| [PRIX BELLE DE NUIT](https://umafans.run/races/2026/fr-france-galop-2026-1025-107/)（[来源](https://www.geny.com/course/1693864-2026-10-25-saint-cloud-prix-belle-de-nuit/arrivee-rapports)） | 23:25（北京时间） | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种、方向、场况、旧卡表三项 |
| [PRIX ROYAL-OAK](https://umafans.run/races/2026/fr-france-galop-2026-1025-108/)（[来源](https://www.geny.com/course/1693863-2026-10-25-saint-cloud-prix-royal-oak/arrivee-rapports)） | 待定/原文钟点缺时区 | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种、方向、场况 |
| [DARLEY PRIX DES RESERVOIRS](https://umafans.run/races/2026/fr-france-galop-2026-1026-109/)（[来源](https://www.geny.com/course/1693868-2026-10-26-chantilly-darley-prix-des-reservoirs/arrivee-rapports)） | 待定/原文钟点缺时区 | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种、方向、场况 |
| [PRIX DE SEINE-ET -OISE](https://umafans.run/races/2026/fr-france-galop-2026-1026-110/)（[来源](https://www.geny.com/course/1693873-2026-10-26-chantilly-prix-de-seine-et-oise/arrivee-rapports)） | 待定/原文钟点缺时区 | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种、方向、场况 |
| [PRIX FILLE DE L ’AIR](https://umafans.run/races/2026/fr-france-galop-2026-1111-111/)（[来源](https://www.france-galop.com/fr/course/detail/2026/P/KzBJdEZJZlVQWC9EbkRVZExvdnRBUT09)） | 23:25（北京时间） | 赛种、方向、奖金、条件 | 距离、奖金、条件、赛种、方向 |
| [PRIX THOMAS BRYON](https://umafans.run/races/2026/fr-france-galop-2026-1120-112/)（[来源](https://www.france-galop.com/fr/course/detail/2026/P/dnhhTFNvRWpNS0VqSE1CWTVZOVUzZz09)） | 待定/未公布 | 赛种、方向、奖金、条件 | 距离、奖金、条件、赛种、方向 |
| [PRIX MIESQUE](https://umafans.run/races/2026/fr-france-galop-2026-1120-113/)（[来源](https://www.france-galop.com/fr/course/detail/2026/P/V3p6QkRwQllwT1AvdkUvZ1pnOHd4dz09)） | 待定/未公布 | 赛种、方向、奖金、条件 | 距离、奖金、条件、赛种、方向 |
| [PRIX ROBERT LEJEUNE](https://umafans.run/races/2026/fr-france-galop-2026-0917-144/)（[来源](https://www.geny.com/course/1684415-2026-09-17-auteuil-prix-robert-lejeune/arrivee-rapports)） | 17:42（北京时间） | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种细分、场地、方向、场况、旧卡表三项 |
| [PRIX DE CHAMBLY](https://umafans.run/races/2026/fr-france-galop-2026-0917-145/)（[来源](https://www.geny.com/course/1684413-2026-09-17-auteuil-prix-de-chambly/arrivee-rapports)） | 待定/原文钟点缺时区 | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种细分、场地、方向、场况 |
| [PRIX DE COMPIEGNE](https://umafans.run/races/2026/fr-france-galop-2026-0917-146/)（[来源](https://www.geny.com/course/1684418-2026-09-17-auteuil-prix-de-compiegne/arrivee-rapports)） | 19:27（北京时间） | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种细分、场地、方向、场况、旧卡表三项 |
| [PRIX THE FELLOW - MARQUISE DE MORATALLA](https://umafans.run/races/2026/fr-france-galop-2026-0922-147/)（[来源](https://www.geny.com/course/1685617-2026-09-22-auteuil-prix-the-fellow-marquise-de-moratalla/arrivee-rapports)） | 待定/原文钟点缺时区 | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种细分、场地、方向、场况 |
| [PRIX RICHARD ET ROBERT HENNESSY](https://umafans.run/races/2026/fr-france-galop-2026-0922-148/)（[来源](https://www.geny.com/course/1685619-2026-09-22-auteuil-prix-richard-et-robert-hennessy/arrivee-rapports)） | 待定/原文钟点缺时区 | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种细分、场地、方向、场况 |
| [PRIX DE MAISONS-LAFFITTE](https://umafans.run/races/2026/fr-france-galop-2026-0926-149/)（[来源](https://www.geny.com/course/1686555-2026-09-26-auteuil-prix-de-maisons-laffitte/arrivee-rapports)） | 21:50（北京时间） | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种细分、场地、方向、场况、旧卡表三项 |
| [PRIX DE LA GASCOGNE](https://umafans.run/races/2026/fr-france-galop-2026-0930-150/)（[来源](https://www.geny.com/course/1687677-2026-09-30-compiegne-prix-de-la-gascogne/arrivee-rapports)） | 待定/原文钟点缺时区 | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种细分、场地、方向、场况 |
| [PRIX MONTGOMERY](https://umafans.run/races/2026/fr-france-galop-2026-1011-151/)（[来源](https://www.geny.com/course/1690432-2026-10-11-auteuil-prix-montgomery/arrivee-rapports)） | 待定/原文钟点缺时区 | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种细分、场地、方向、场况 |
| [PRIX MAGNE](https://umafans.run/races/2026/fr-france-galop-2026-1011-152/)（[来源](https://www.geny.com/course/1690433-2026-10-11-auteuil-prix-magne/arrivee-rapports)） | 待定/原文钟点缺时区 | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种细分、场地、方向、场况 |
| [PRIX GEORGES DE TALHOUET -ROY](https://umafans.run/races/2026/fr-france-galop-2026-1011-153/)（[来源](https://www.geny.com/course/1690435-2026-10-11-auteuil-prix-georges-de-talhouet-roy/arrivee-rapports)） | 待定/原文钟点缺时区 | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种细分、场地、方向、场况 |
| [PRIX CARMARTHEN](https://umafans.run/races/2026/fr-france-galop-2026-1011-154/)（[来源](https://www.geny.com/course/1690436-2026-10-11-auteuil-prix-carmarthen/arrivee-rapports)） | 待定/原文钟点缺时区 | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种细分、场地、方向、场况 |
| [PRIX PIERRE DE LASSUS](https://umafans.run/races/2026/fr-france-galop-2026-1017-155/)（[来源](https://www.geny.com/course/1691901-2026-10-17-auteuil-prix-pierre-de-lassus/arrivee-rapports)） | 22:35（北京时间） | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种细分、场地、方向、场况、旧卡表三项 |
| [PRIX ORCADA](https://umafans.run/races/2026/fr-france-galop-2026-1017-156/)（[来源](https://www.geny.com/course/1691898-2026-10-17-auteuil-prix-orcada/arrivee-rapports)） | 20:33（北京时间） | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种细分、场地、方向、场况、旧卡表三项 |
| [PRIX HEROS XII](https://umafans.run/races/2026/fr-france-galop-2026-1017-157/)（[来源](https://www.geny.com/course/1691902-2026-10-17-auteuil-prix-heros-xii/arrivee-rapports)） | 23:18（北京时间） | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种细分、场地、方向、场况、旧卡表三项 |
| [GRAND STEEPLE-CHASE DE COMPIEGNE](https://umafans.run/races/2026/fr-france-galop-2026-1024-158/)（[来源](https://www.geny.com/course/1693545-2026-10-24-compiegne-grand-steeple-chase-de-compiegne/arrivee-rapports)） | 待定/原文钟点缺时区 | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种细分、场地、方向、场况 |
| [PRIX MAGALEN BRYANT](https://umafans.run/races/2026/fr-france-galop-2026-1114-159/)（[来源](https://www.france-galop.com/fr/course/detail/2026/O/czRJaXVnRmFLMnlyYStmblBLU2VtZz09)） | 待定/未公布 | 赛种、奖金、条件 | 距离、奖金、条件、赛种细分、场地 |
| [PRIX SERGE LANDON - GRAND PRIX D’AUTOMNE](https://umafans.run/races/2026/fr-france-galop-2026-1114-160/)（[来源](https://www.france-galop.com/fr/course/detail/2026/O/VTRzZytHQjFZZmVPYlFLc0ZrRUlrUT09)） | 待定/未公布 | 赛种、奖金、条件 | 距离、奖金、条件、赛种细分、场地 |
| [PRIX CONGRESS](https://umafans.run/races/2026/fr-france-galop-2026-1114-161/)（[来源](https://www.france-galop.com/fr/course/detail/2026/O/d0tjUGhPRnlLUVdkUmpDZmdsNzJzUT09)） | 待定/未公布 | 赛种、奖金、条件 | 距离、奖金、条件、赛种细分、场地 |
| [PRIX CAMBACERES - GRANDE COURSE DE HAIES DES 3 ANS](https://umafans.run/races/2026/fr-france-galop-2026-1115-162/)（[来源](https://www.france-galop.com/fr/course/detail/2026/O/MFE5VlBLejJjcmdkUTVlbHpQL2Z6dz09)） | 待定/未公布 | 赛种、奖金、条件 | 距离、奖金、条件、赛种细分、场地 |
| [PRIX RENAUD DU VIVIER - GRANDE COURSE DE HAIES DES 4 ANS](https://umafans.run/races/2026/fr-france-galop-2026-1115-163/)（[来源](https://www.france-galop.com/fr/course/detail/2026/O/WksrU1d3MXN1ZjM3dFd1ZnM0NStIZz09)） | 待定/未公布 | 赛种、奖金、条件 | 距离、奖金、条件、赛种细分、场地 |
| [PRIX MAURICE GILLOIS - GRAND STEEPLE-CHASE DES 4 ANS](https://umafans.run/races/2026/fr-france-galop-2026-1115-164/)（[来源](https://www.france-galop.com/fr/course/detail/2026/O/Sk54SlYrTllGOWI4T1dRK2QyK2x3dz09)） | 待定/未公布 | 赛种、奖金、条件 | 距离、奖金、条件、赛种细分、场地 |
| [PRIX FONDEUR](https://umafans.run/races/2026/fr-france-galop-2026-1115-165/)（[来源](https://www.france-galop.com/fr/course/detail/2026/O/REJBenJSQkttMldKNmEvTlNzRmpkUT09)） | 待定/未公布 | 赛种、奖金、条件 | 距离、奖金、条件、赛种细分、场地 |
| [PRIX LA HAYE JOUSSELIN](https://umafans.run/races/2026/fr-france-galop-2026-1115-166/)（[来源](https://www.france-galop.com/fr/course/detail/2026/O/U2ljbXRmK3VsSC9Na2pURXR0ZExCQT09)） | 待定/未公布 | 赛种、奖金、条件 | 距离、奖金、条件、赛种细分、场地 |
| [PRIX GENERAL DE SAINT -DIDIER](https://umafans.run/races/2026/fr-france-galop-2026-1127-167/)（[来源](https://www.france-galop.com/fr/course/detail/2026/O/c29RTGZ4S20vZ3dMNDhEdDdzMWRjZz09)） | 待定/未公布 | 赛种、奖金、条件 | 距离、奖金、条件、赛种细分、场地 |
| [PRIX LEOPOLD D’ORSETTI - GRANDE COURSE DE HAIES DE COMPIEGNE](https://umafans.run/races/2026/fr-france-galop-2026-1127-168/)（[来源](https://www.france-galop.com/fr/course/detail/2026/O/ZDRWcldzSE5nQTFld3VPeW9VekRvQT09)） | 待定/未公布 | 赛种、奖金、条件 | 距离、奖金、条件、赛种细分、场地 |
| [PRIX SYTAJ](https://umafans.run/races/2026/fr-france-galop-2026-1129-169/)（[来源](https://www.france-galop.com/fr/course/detail/2026/O/TEZCbzBYbmEzR2doQmRlYlNVR2xqQT09)） | 待定/未公布 | 赛种、奖金、条件 | 距离、奖金、条件、赛种细分、场地 |
| [PRIX ANDRE MICHEL](https://umafans.run/races/2026/fr-france-galop-2026-1206-170/)（[来源](https://www.france-galop.com/fr/course/detail/2026/O/eUtvd2NOTHNJU1Z6ejBoN3RramZoUT09)） | 待定/未公布 | 赛种、奖金、条件 | 距离、奖金、条件、赛种细分、场地 |
| [PRIX LEON OLRY ROEDERER](https://umafans.run/races/2026/fr-france-galop-2026-1206-171/)（[来源](https://www.france-galop.com/fr/course/detail/2026/O/VHFGZTI5RzAzbzlUK0FIRm5JaTJGUT09)） | 待定/未公布 | 赛种、奖金、条件 | 距离、奖金、条件、赛种细分、场地 |
| [PRIX MORGEX](https://umafans.run/races/2026/fr-france-galop-2026-1206-172/)（[来源](https://www.france-galop.com/fr/course/detail/2026/O/ay95ZHpJK1VlelhQdGF5T0ZISUZiUT09)） | 待定/未公布 | 赛种、奖金、条件 | 距离、奖金、条件、赛种细分、场地 |
| [PRIX GEORGES COURTOIS](https://umafans.run/races/2026/fr-france-galop-2026-1206-173/)（[来源](https://www.france-galop.com/fr/course/detail/2026/O/bFRPOGpqWEpyVjFhck1COEZTakYxdz09)） | 待定/未公布 | 赛种、奖金、条件 | 距离、奖金、条件、赛种细分、场地 |
| [Prix de l'Avenir](https://umafans.run/races/2026/fr-2026-aqps-avenir/)（[来源](https://www.geny.com/course/1695527-2026-11-02-nantes-prix-de-l-avenir/arrivee-rapports)） | 待定/原文钟点缺时区 | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种、场地、方向、场况 |
| [Prix du Bourbonnais](https://umafans.run/races/2026/fr-2026-aqps-bourbonnais/)（[来源](https://www.geny.com/course/1689691-2026-10-08-saint-cloud-prix-du-bourbonnais/arrivee-rapports)） | 待定/原文钟点缺时区 | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种、场地、方向、场况 |
| [Prix de Craon](https://umafans.run/races/2026/fr-2026-aqps-craon/)（[来源](https://www.geny.com/course/1682653-2026-09-10-parislongchamp-prix-de-craon/arrivee-rapports)） | 待定/原文钟点缺时区 | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种、场地、方向、场况 |
| [Prix Glorieuse](https://umafans.run/races/2026/fr-2026-aqps-glorieuse/)（[来源](https://www.geny.com/course/1691031-2026-10-14-saint-cloud-prix-glorieuse/arrivee-rapports)） | 待定/原文钟点缺时区 | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种、场地、方向、场况 |
| [Prix Association des Aqps (Prix Richard de Gennes)](https://umafans.run/races/2026/fr-2026-aqps-richard-de-gennes/)（[来源](https://www.geny.com/course/1681867-2026-09-06-craon-prix-association-des-aqps-prix-richard-de-gennes/arrivee-rapports)） | 待定/原文钟点缺时区 | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种、场地、方向、场况 |
| [Prix du Tremblay](https://umafans.run/races/2026/fr-2026-aqps-tremblay/)（[来源](https://www.geny.com/course/1694866-2026-10-30-lyon-parilly-prix-du-tremblay/arrivee-rapports)） | 待定/原文钟点缺时区 | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种、场地、方向、场况 |
| [Prix Yves d'Armaille - Prix Cokoriko](https://umafans.run/races/2026/fr-2026-aqps-yves-d-armaille/)（[来源](https://www.geny.com/course/1684613-2026-09-18-moulins-prix-yves-d-armaille-prix-cokoriko/arrivee-rapports)） | 待定/原文钟点缺时区 | 赛种、场地、方向、场况、奖金、条件 | 距离、奖金、条件、冠军计时、赛种、场地、方向、场况 |
| [PRIX CHLORIS](https://umafans.run/races/2026/fr-2026-aqps-chloris/)（[来源](https://www.france-galop.com/fr/course/detail/2026/P/eE4raVpNY0xEczRZV0tjR2FkQjljQT09)） | 待定/未公布 | 赛种、方向、奖金、条件 | 距离、奖金、条件、赛种、场地、方向 |
| [PRIX DES GUILLEDINES](https://umafans.run/races/2026/fr-2026-aqps-guilledines/)（[来源](https://www.france-galop.com/fr/course/detail/2026/P/RzVIWXM4NTE1bVcxeHF6bTRhdTRpdz09)） | 待定/未公布 | 赛种、方向、奖金、条件 | 距离、奖金、条件、赛种、场地、方向 |
| [PRIX JACQUES DE VIENNE](https://umafans.run/races/2026/fr-2026-aqps-jacques-de-vienne/)（[来源](https://www.france-galop.com/fr/course/detail/2026/P/Wm1LNXNaZGdwcGxwZ0lqdnk0YXR3UT09)） | 待定/未公布 | 赛种、方向、奖金、条件 | 距离、奖金、条件、赛种、场地、方向 |

## 证据与设计

- 最新正式字段：production-fields.json；当前网页：public-current.json及public-*.html。
- 原文逐场头部：source-header-inventory.json；原始59赛果/卡表归档与21FG文档只读复用。
- 本机证据根：`/Users/mentianlu/.codex/runtime/france-field-gap-design-20261110/`。
- [修复设计](design.md)说明数据流、模型、单位/时区、字段权限与历史补缺；[用例](test_cases.md)定义验收边界。

本轮仅文档与只读诊断脚本，没有业务实现、生产修改或迁移执行。
