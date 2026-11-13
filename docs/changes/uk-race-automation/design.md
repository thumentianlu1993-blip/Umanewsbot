# 英国实现设计

## 当前证据

- 2026-11-13 只读生产快照：英国 2026 年 296 个 event；9—12 月仅 39 个公开赛事、20 场有赛果，11—12 月没有赛事。此为当前快照，不使用旧全批报告推断。
- BHA 平地 2026 目录（PDF 物理页 21—23）核对 9—12 月 44 场 Group 赛事；2026/27 障碍目录（物理页 19—20）56 场 Grade 1/2、Premier Handicap，共 100 个赛程目标。
- TRA 历史 Class 1 查询返回 92 场，排除 Listed 后 55 场：44 平地、7 Grade 2、4 Premier Handicap。55 场历史 Pro 卡表全部 HTTP 200；478 个赛果参赛者 ID 与卡表非 NR 集合逐场一致，另 34 匹退赛，共 512 匹，field_size 也逐场一致。
- 其余历史目标 Old Roan 10月25日有明确停赛证据；44 个目标在 11月13日及以后。未来日期仍以最新公告/来源修订，不能宣称未来正式名单已公布。
- 今天、明天 Pro 卡表实测可读，包括 Shloer、Hyde、Prestbury、November Novices 和 Paddy Power Gold Cup。

## 已知语义与缺口

- St Simon / Horris Hill 原 Newbury 10月24日已分别移至 Newmarket 10月30／31日补赛，不能沿用旧取消草案。
- Haldon Gold Cup、Rising Stars、原 Wincanton Premier Handicap 已由 BHA 10月27日公告转移至 Aintree，身份匹配须保存公告和对应年度赛事关联。
- 历史卡表的 34 匹 NR 原马号已由 23 场 Sporting Life 全名单逐场补证；核对同场日期、UTC 时刻、马场、完整马名集合、实际参赛人数、名次和已知马号。原始 NR 字面量不作为马号。
- 卡表 prize（例如 St Simon £42,532）是冠军奖金，不能覆盖 BHA 总奖金。赛果 time 字段保留 API 提供值及来源，不能称为实测计时。
- 旧 TRA 多源 adapter 使用 Free 路由和最小解析器；付费接口探测成功不代表现行自动调度已经可用。

## 实施顺序

1. 对官方 100 场目录建立年度身份、现有 event/series 关联及改期证据，固定清单并列明新增/更新/停赛。
2. 增加英国 TRA 付费解析与采集：完整卡表、按 ID 赛果与历史卡表合并、字段单位/语义、分页、错误边界；既有 Free 路由保持原合同。
3. 接入多源身份、字段权威、公开写入及未来赛事发现/调度；复用现有锁、请求预算和来源缓存。
4. 构建只包含英国数据及必要策略换绑的固定 SHA 发布包；离线重放、定向测试和独立只读审核完成后提交 G2。
5. 获准后部署、事务应用、公开页与自然调度验收。实现与离线验证已推进，生产发布和自然验收尚未执行。

## 来源与证据

- https://www.britishhorseracing.com/about/publications/
- https://media.britishhorseracing.com/bha/Publications/Pattern_Listed_Books/British_Flat_Pattern_Listed_2026.pdf
- https://media.britishhorseracing.com/bha/Publications/Pattern_Listed_Books/British_Jump_Pattern_Listed_2627.pdf
- https://www.britishhorseracing.com/press_releases/bha-confirms-aintree-and-sandown-jumps-programme-amendments/
- https://www.racingtv.com/news/old-roan-chase-day-at-aintree-abandoned-due-to-storm-boelo-2026
- https://api.theracingapi.com/documentation

私有原件存放在任务 runtime 目录，不包含凭据；仓库只保存必要合成测试 fixture 和汇总证据。

## 2026-11-13 实现与基线修正

- 独立英国模块接入付费采集、完整名单、赛前候选、公开单位与基础资料；默认开关关闭。
- 新增精确原子数据包、原件摘要校验、旧登记接管、提交查询与完整 before/after 恢复。
- 8 条旧障碍年度记录被旧模糊匹配串到其他赛事。以官方目录重新绑定该年度身份，47 个既有目标的公开投影替换在包中逐项声明，原审计版本保留。
- 复用现有发布恢复器时只增加显式 action/snapshot 参数，美国默认行为保持，已纳入美国原有测试回归。
- BHA 计划总奖金和 TRA 冠军奖金分别保留。Champion Stakes 手册金额存在印刷缺零，按主办方 https://britishchampionsday.com/race-information/ 核实 130 万英镑，不按 OCR 直接写入。
