# 历史义务只读分类

快照时间`2026-10-29T07:51:08.838073+00:00`；生产revision`ad50abdb74b89669ab8ada2958b040877c1a1849`。REPEATABLE READ READ ONLY、单语句8秒、12,000场上限；10,215场未截断。本轮没有更改确认标记、迁移、调度或任何生产数据。

## 10,134场空确认标记守恒

| 分类 | 场数 | 可证明事实 | 仍不能推断 |
|---|---:|---|---|
| legacy_results | 9,995 | 存在canonical赛果行；无本次查询到的纳管、控制及修订发布记录 | 完整终态、首次确认时间或历史义务已经解除；is_confirmed默认true不代替证据 |
| legacy_no_results | 119 | 无canonical赛果、无纳管/控制/修订发布 | 永久无资料或无需追踪；其中取消状态也需取消证据 |
| enrolled_no_results | 19 | enrollment=enrolled且control=enforce，canonical赛果行为空 | finished状态不证明完整赛果；不能将其视为已完成 |
| published_inconsistent | 1 | event924有provisional修订/发布、赛事确认时间为空 | 临时公开不等于正式确认；保留待核对义务 |

合计9,995+119+19+1=10,134，所有ID保存在固定原始快照，不能删除或用新清单覆盖历史失败。119场中117场scheduled、2场cancelled；取消状态不自动免除公开取消信息的义务。

上述分类解决了“不能把全部空标记当作高频存量”的混淆，但**未证明其中10,114场无旧义务或已完成**。它们保留为legacy义务UNKNOWN集合，阻断全库存完成声明；不擅自批量重抓或修复。19场已纳管未完成、1场临时发布异常、2场七天候选需列入近期容量核对，不能只预算未来79场。

## 19场显式在管且无赛果

全部mode=enforce、state=enrolled；已有来源身份为既有TRA路由，本轮没有调用TRA或将它当作获准免费源。以下是现状核验，不是修复清单批准。每场仍需免费替代来源的身份/能力、原纳管权和补偿范围审核。

| ID | 地区 | 当地赛日 | 名称 |
|---|---|---|---|
| 785 | france | 2026-10-10 | CRITERIUM DE MAISONS-LAFFITTE |
| 790 | france | 2026-10-25 | PRIX DE FLORE |
| 791 | france | 2026-10-25 | PRIX BELLE DE NUIT |
| 839 | france | 2026-10-17 | PRIX PIERRE DE LASSUS |
| 840 | france | 2026-10-17 | PRIX ORCADA |
| 841 | france | 2026-10-17 | PRIX HEROS XII |
| 977 | united_kingdom | 2026-10-03 | BetMGM CUMBERLAND LODGE STAKES |
| 978 | united_kingdom | 2026-10-03 | JOHN GUEST RACING BENGOUGH STAKES |
| 979 | united_kingdom | 2026-10-03 | BetMGM SUN CHARIOT STAKES |
| 980 | united_kingdom | 2026-10-09 | bet365 FILLIES' MILE |
| 981 | united_kingdom | 2026-10-09 | THOROUGHBRED INDUSTRY EMPLOYEE AWARDS CHALLENGE STAKES |
| 982 | united_kingdom | 2026-10-09 | NEWMARKET PONY ACADEMY PRIDE STAKES |
| 983 | united_kingdom | 2026-10-09 | GODOLPHIN LIFETIME CARE OH SO SHARP STAKES |
| 984 | united_kingdom | 2026-10-09 | NEWMARKET ACADEMY GODOLPHIN BEACON PROJECT CORNWALLIS STAKES |
| 985 | united_kingdom | 2026-10-10 | DARLEY DEWHURST STAKES |
| 988 | united_kingdom | 2026-10-10 | EMIRATES AUTUMN STAKES |
| 993 | united_kingdom | 2026-10-24 | WILLIAM HILL FUTURITY TROPHY STAKES |
| 994 | united_kingdom | 2026-10-24 | BetVictor ST SIMON STAKES |
| 995 | united_kingdom | 2026-10-24 | BetVictor HORRIS HILL STAKES |

## 首次确认与七天窗口

event116及117的数据库确认时间与最早official修订的official_confirmed_at、published_at及独立publication表相同。读取包含该集合全部48条revision和3条publication；没有找到更早的official修订。本轮支持以这些现存凭据计算候选观察窗，但没有将P02部署、激活或追溯为自然运行。

| ID | official revision | 首次确认 UTC | 7×24小时截止 UTC |
|---|---|---|---|
| 116 | 119 | 2026-10-24 07:13:00.178156 | 2026-10-31 07:13:00.178156 |
| 117 | 121 | 2026-10-25 08:09:04.847924 | 2026-11-01 08:09:04.847924 |

event924的revision2为provisional，published_at=2026-07-19 04:37:17.201536 UTC，official_confirmed_at为空，不能据此开启一个新的七天窗口或声明正式义务完成。

生产0079对应的Control缺first_result_confirmed_at/correction_until/next_correction_at三个候选字段。第一次只读查询因FieldError退出，事务没有写入；随后按实际模型字段读取并将缺失字段显式记录，未将其填零或假装生产已升级。

## 固定证据

- `/Users/mentianlu/.codex/artifacts/p02-capacity-20261029/obligations.py`，SHA256 `808573a5661a12dd46f667f557aafc441b614b8d83cb7c94ddc44d525db3ba07`。
- `/Users/mentianlu/.codex/artifacts/p02-capacity-20261029/obligations.json`，SHA256 `f74c21709febf09c9b0b57f8b805147368edff55c793524a48803dc29d341882`。

原始数据只在本机持久artifact目录，不包含凭据或患者数据，不随仓库发布；交付执行方需取得同摘要文件，不能只靠文件名复现。
