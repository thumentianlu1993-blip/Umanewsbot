# 逐场身份与覆盖收口证据

这是候选台账，不是生产身份写入或来源准入。原[79场基线](targets.md)保持历史原样；本轮补原始等级/来源和两个既有未匹配目标，未来已知目标下限变为**81场**（79 canonical + 2 historical target）。全部仍BLOCKED。完整地区目录及来源自动用途/额度尚未证明，不能称81为全地区最终N。

## 优先级、子区与目录核对

德国3场、爱尔兰22场逐一以日期+名称+场地+原等级匹配已保存官方日历行，并验证各行原始提取文本SHA。新增4场重点依据：20233（G1）、20619/20660/20689（Gr 1）。当前79场的证据候选分类为29重点、50非重点；加两场英国G3后为29/52。**未写回normalized_grade**；候选代码对运行时缺规范等级仍要求60秒重点预算，不能拿本报告直接让25条缺规范等级记录按120秒准入。全套证明未完成前，即便使用保守预算也不放行。

JRA12场包含京都ジャンプS（JG3，原normalized_race_type仍unknown），NAR6场依据其NAR来源目录分层；不是按中文名称猜测辖区。AU各州、AE与SA分别保持覆盖UNKNOWN，零canonical记录不等于无赛事。25条旧等级证明来自保存日历，不冒充今日更新或运行态证明。

## 新取得的两个来源身份候选

- canonical119：官方JRA专题页链接到[出马表](https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dde0105202604111120261101%2FA6)，可见2026-11-01、东京、第11场、天皇賞（秋）；按既有CNAME规则读取赛事键`05202604111120261101`。它是本轮浏览证据，不是已写入source identity；随后本机匿名原文请求403，停止，未绕行或将浏览成功称为producer可用。
- canonical199：[NAR公开出马表](https://sp.keiba.go.jp/KeibaWebSP_IPAT/TodayRaceInfo/S_DebaTable_ipat?k_babaCode=36&k_raceDate=2026%2F10%2F29&k_raceNo=11)对应2026-10-29、门别、11R、エーデルワイス賞；候选自然键`2026-10-29 / baba36 / race11`。原source_refs.race_number=29是“第29回”的届次，不能当11R的场次使用。该SP页面路径/host与现有desktop parser合同不同，未假装已解析或批准新自动路由。

两场均只到“身份候选可复核”，runtime_verified仍false。其余79条未来候选（含两个未建canonical目标）只有日历定位或缺口，没有已审核可执行provider ID。HK季表source_index不是场次，内部historical_target_id也不是provider race ID；不得拼造来源URL或把它们当完成身份绑定。

## 完整逐场台账

来源定位简称：JRA年表、NAR年度目录、HKJC季表、TOBA年表、FG日历PDF、DE官方缓存、HRI官方缓存、TJCIS历史目标；它们只说明日历来源，不代替实时名单、退赛、赛果和更正能力。

| 目标key | 子区 | 当地赛日 | 原等级证据 | 重点候选 | 日历定位/内部目标 | provider身份状态 |
|---|---|---|---|---|---|---|
| canonical:199 | japan_nar | 2026-10-29 | JPN3 | 否 | NAR年度目录 | 身份候选待绑定 |
| canonical:549 | united_states | 2026-10-30 | G1 | 是 | TOBA年表 | 缺可执行provider ID |
| canonical:550 | united_states | 2026-10-30 | G1 | 是 | TOBA年表 | 缺可执行provider ID |
| canonical:551 | united_states | 2026-10-30 | G1 | 是 | TOBA年表 | 缺可执行provider ID |
| canonical:552 | united_states | 2026-10-30 | G1 | 是 | TOBA年表 | 缺可执行provider ID |
| canonical:553 | united_states | 2026-10-30 | G1 | 是 | TOBA年表 | 缺可执行provider ID |
| canonical:20565 | ireland | 2026-10-30 | Gr 3 | 否 | HRI官方缓存 / target:76136 | 缺可执行provider ID |
| canonical:20614 | ireland | 2026-10-30 | Listed | 否 | HRI官方缓存 / target:76208 | 缺可执行provider ID |
| canonical:118 | japan_jra | 2026-10-31 | G3 | 否 | JRA年表 | 缺可执行provider ID |
| canonical:554 | united_states | 2026-10-31 | G1 | 是 | TOBA年表 | 缺可执行provider ID |
| canonical:555 | united_states | 2026-10-31 | G1 | 是 | TOBA年表 | 缺可执行provider ID |
| canonical:556 | united_states | 2026-10-31 | G1 | 是 | TOBA年表 | 缺可执行provider ID |
| canonical:557 | united_states | 2026-10-31 | G1 | 是 | TOBA年表 | 缺可执行provider ID |
| canonical:558 | united_states | 2026-10-31 | G1 | 是 | TOBA年表 | 缺可执行provider ID |
| canonical:559 | united_states | 2026-10-31 | G1 | 是 | TOBA年表 | 缺可执行provider ID |
| canonical:560 | united_states | 2026-10-31 | G1 | 是 | TOBA年表 | 缺可执行provider ID |
| canonical:561 | united_states | 2026-10-31 | G1 | 是 | TOBA年表 | 缺可执行provider ID |
| canonical:562 | united_states | 2026-10-31 | G1 | 是 | TOBA年表 | 缺可执行provider ID |
| canonical:563 | united_states | 2026-10-31 | G3 | 否 | TOBA年表 | 缺可执行provider ID |
| canonical:20250 | germany | 2026-10-31 | G3 | 否 | DE官方缓存 / target:75655 | 缺可执行provider ID |
| canonical:20619 | ireland | 2026-10-31 | Gr 1 | 是 | HRI官方缓存 / target:76215 | 缺可执行provider ID |
| canonical:20711 | ireland | 2026-10-31 | Gr 2 | 否 | HRI官方缓存 / target:76356 | 缺可执行provider ID |
| canonical:119 | japan_jra | 2026-11-01 | G1 | 是 | JRA年表 | 身份候选待绑定 |
| canonical:564 | united_states | 2026-11-01 | G3 | 否 | TOBA年表 | 缺可执行provider ID |
| canonical:565 | united_states | 2026-11-01 | G3 | 否 | TOBA年表 | 缺可执行provider ID |
| canonical:566 | united_states | 2026-11-01 | G2 | 否 | TOBA年表 | 缺可执行provider ID |
| canonical:20623 | ireland | 2026-11-01 | Gr 3 | 否 | HRI官方缓存 / target:76222 | 缺可执行provider ID |
| canonical:20646 | ireland | 2026-11-01 | Gr 3 | 否 | HRI官方缓存 / target:76258 | 缺可执行provider ID |
| canonical:20740 | ireland | 2026-11-01 | Listed | 否 | HRI官方缓存 / target:76398 | 缺可执行provider ID |
| canonical:200 | japan_nar | 2026-11-03 | JPN3 | 否 | NAR年度目录 | 缺可执行provider ID |
| canonical:201 | japan_nar | 2026-11-03 | JPN1 | 是 | NAR年度目录 | 缺可执行provider ID |
| canonical:202 | japan_nar | 2026-11-03 | JPN1 | 是 | NAR年度目录 | 缺可执行provider ID |
| canonical:203 | japan_nar | 2026-11-03 | JPN1 | 是 | NAR年度目录 | 缺可执行provider ID |
| canonical:20539 | ireland | 2026-11-05 | Gr 2 | 否 | HRI官方缓存 / target:76093 | 缺可执行provider ID |
| canonical:20719 | ireland | 2026-11-05 | Listed | 否 | HRI官方缓存 / target:76368 | 缺可执行provider ID |
| canonical:120 | japan_jra | 2026-11-07 | G2 | 否 | JRA年表 | 缺可执行provider ID |
| canonical:121 | japan_jra | 2026-11-07 | JG3 | 否 | JRA年表 | 缺可执行provider ID |
| canonical:567 | united_states | 2026-11-07 | G2 | 否 | TOBA年表 | 缺可执行provider ID |
| canonical:20233 | germany | 2026-11-07 | G1 | 是 | DE官方缓存 / target:75631 | 缺可执行provider ID |
| canonical:122 | japan_jra | 2026-11-08 | G2 | 否 | JRA年表 | 缺可执行provider ID |
| canonical:123 | japan_jra | 2026-11-08 | G3 | 否 | JRA年表 | 缺可执行provider ID |
| canonical:19608 | hong_kong | 2026-11-08 | G3 | 否 | HKJC季表 | 缺可执行provider ID |
| canonical:20527 | ireland | 2026-11-08 | Listed | 否 | HRI官方缓存 / target:76076 | 缺可执行provider ID |
| canonical:20681 | ireland | 2026-11-08 | Gr 3 | 否 | HRI官方缓存 / target:76309 | 缺可执行provider ID |
| canonical:795 | france | 2026-11-11 | G3 | 否 | FG日历PDF | 缺可执行provider ID |
| canonical:124 | japan_jra | 2026-11-14 | G3 | 否 | JRA年表 | 缺可执行provider ID |
| canonical:125 | japan_jra | 2026-11-14 | G2 | 否 | JRA年表 | 缺可执行provider ID |
| canonical:843 | france | 2026-11-14 | G2 | 否 | FG日历PDF | 缺可执行provider ID |
| canonical:844 | france | 2026-11-14 | G1 | 是 | FG日历PDF | 缺可执行provider ID |
| canonical:845 | france | 2026-11-14 | G2 | 否 | FG日历PDF | 缺可执行provider ID |
| canonical:20240 | germany | 2026-11-14 | G3 | 否 | DE官方缓存 / target:75642 | 缺可执行provider ID |
| canonical:20570 | ireland | 2026-11-14 | Gr 3 | 否 | HRI官方缓存 / target:76145 | 缺可执行provider ID |
| canonical:20571 | ireland | 2026-11-14 | Gr 2 | 否 | HRI官方缓存 / target:76146 | 缺可执行provider ID |
| canonical:20643 | ireland | 2026-11-14 | Gr 2 | 否 | HRI官方缓存 / target:76254 | 缺可执行provider ID |
| canonical:126 | japan_jra | 2026-11-15 | G1 | 是 | JRA年表 | 缺可执行provider ID |
| canonical:846 | france | 2026-11-15 | G1 | 是 | FG日历PDF | 缺可执行provider ID |
| canonical:847 | france | 2026-11-15 | G1 | 是 | FG日历PDF | 缺可执行provider ID |
| canonical:848 | france | 2026-11-15 | G1 | 是 | FG日历PDF | 缺可执行provider ID |
| canonical:849 | france | 2026-11-15 | G3 | 否 | FG日历PDF | 缺可执行provider ID |
| canonical:850 | france | 2026-11-15 | G1 | 是 | FG日历PDF | 缺可执行provider ID |
| canonical:20505 | ireland | 2026-11-15 | Listed | 否 | HRI官方缓存 / target:76041 | 缺可执行provider ID |
| canonical:20658 | ireland | 2026-11-15 | Gr 3 | 否 | HRI官方缓存 / target:76276 | 缺可执行provider ID |
| canonical:20730 | ireland | 2026-11-15 | Gr 3 | 否 | HRI官方缓存 / target:76382 | 缺可执行provider ID |
| canonical:796 | france | 2026-11-20 | G3 | 否 | FG日历PDF | 缺可执行provider ID |
| canonical:797 | france | 2026-11-20 | G3 | 否 | FG日历PDF | 缺可执行provider ID |
| canonical:127 | japan_jra | 2026-11-21 | G3 | 否 | JRA年表 | 缺可执行provider ID |
| canonical:568 | united_states | 2026-11-21 | G3 | 否 | TOBA年表 | 缺可执行provider ID |
| canonical:20567 | ireland | 2026-11-21 | Gr 2 | 否 | HRI官方缓存 / target:76139 | 缺可执行provider ID |
| canonical:20660 | ireland | 2026-11-21 | Gr 1 | 是 | HRI官方缓存 / target:76279 | 缺可执行provider ID |
| canonical:128 | japan_jra | 2026-11-22 | G1 | 是 | JRA年表 | 缺可执行provider ID |
| canonical:569 | united_states | 2026-11-22 | G3 | 否 | TOBA年表 | 缺可执行provider ID |
| canonical:19609 | hong_kong | 2026-11-22 | G2 | 否 | HKJC季表 | 缺可执行provider ID |
| canonical:19610 | hong_kong | 2026-11-22 | G2 | 否 | HKJC季表 | 缺可执行provider ID |
| canonical:19611 | hong_kong | 2026-11-22 | G2 | 否 | HKJC季表 | 缺可执行provider ID |
| canonical:20545 | ireland | 2026-11-22 | Gr 2 | 否 | HRI官方缓存 / target:76102 | 缺可执行provider ID |
| canonical:20589 | ireland | 2026-11-22 | Listed | 否 | HRI官方缓存 / target:76174 | 缺可执行provider ID |
| canonical:20689 | ireland | 2026-11-22 | Gr 1 | 是 | HRI官方缓存 / target:76320 | 缺可执行provider ID |
| canonical:129 | japan_jra | 2026-11-23 | G2 | 否 | JRA年表 | 缺可执行provider ID |
| canonical:204 | japan_nar | 2026-11-25 | JPN2 | 否 | NAR年度目录 | 缺可执行provider ID |
| historical_target:60870 | united_kingdom | 2026-11-15 | G3 | 否 | TJCIS历史目标 | canonical与provider均未匹配 |
| historical_target:60871 | united_kingdom | 2026-11-14 | G3 | 否 | TJCIS历史目标 | canonical与provider均未匹配 |

### 两个漏出canonical的目标

- historical_target60870：[Oddschecker] H. Stp，Cheltenham，2026-11-15，G3；现存状态not_due/source_unavailable，日期更正有旧coverage_adjudication摘要，但本轮未取得比赛级新provider ID，保持未匹配。
- historical_target60871：[Paddy Power] Gold Cup H. Stp，Cheltenham，2026-11-14，G3；[赛场公开日程](https://www.thejockeyclub.co.uk/cheltenham/events-tickets/the-november-meeting/saturday/)支持日期与Paddy Power Gold Cup场次活动关联，仍不是最终出赛名单或稳定race ID。名称/赞助变动待正式身份核验。

两者均来自当前数据库的年度目标，未新增生产记录。尚未找到所有地区完整独立日历，其他漏项数量仍UNKNOWN，不能只保留这两场就声称全覆盖。

## 来源证据与失败记录

JRA年表和TOBA年表已通过浏览工具读取。NAR旧2026/racelist入口直接读取404，搜索缓存仍有内容；没有用缓存的可见性冒充当前入口200。JRA浏览可见正文但本机直接下载两次（年表、已发现卡页各一次）都403，之后停止该host。TOBA一次直接下载超过2MiB边界后停止；未抬高边界重试。NAR SP与Cheltenham公开页各一次匿名请求200，原始响应摘要见下。没有登录、会员、Cookie注入或付费调用。

- jra-calendar：`2026-10-29T07:57:06.699653+00:00`，HTTP Error 403: Forbidden；无成功原文摘要。
- jra-119-card：`2026-10-29T07:57:07.889274+00:00`，HTTP Error 403: Forbidden；无成功原文摘要。
- nar-199-card：`2026-10-29T07:57:08.921569+00:00`，200；SHA256 `bb290d515c66828a192c1a1af0078a38a6c79cebd31a674600956851fdca5c91`。
- us-calendar：`2026-10-29T07:57:10.772432+00:00`，response_limit；无成功原文摘要。
- uk-60871-day：`2026-10-29T07:57:14.565245+00:00`，200；SHA256 `3342f92a3cf5e8e7414a2cd54de0e547d265978b72ea5797c07d7a7550d982d4`。

已核对缓存：

- germany：3条，`/Users/mentianlu/Code/umanews/runtime/race_calendar_nine_regions/calendar_official_2025_2026/germany/2026/calendar_timeline_candidate.jsonl`，SHA256 `c5292ee3b57a47414668d68e89dcaa4a39e4057240e410951901c6952b9ba57d`；逐行引用原始文本摘要全部相等。
- ireland：22条，`/Users/mentianlu/Code/umanews/runtime/race_calendar_nine_regions/calendar_official_2025_2026/ireland/2026/calendar_timeline_candidate.jsonl`，SHA256 `9ea4473f52e4df33e9efa7ff992a94ef0fe878d6bb33acaa2724c6090f43535f`；逐行引用原始文本摘要全部相等。

生产只读导出：

- `/Users/mentianlu/.codex/artifacts/p02-capacity-20261029/identity_hints.json`，SHA256 `cfba514631de50fa7f4ccd7e7af37ab38235155ff00fd16107dbed6327bdb812`。
- `/Users/mentianlu/.codex/artifacts/p02-capacity-20261029/catalog.json`，SHA256 `144bc77e45d01ccb55385fa2203e8eab18451dd184ea60e11a4ef51b4ea747f9`。

本轮已知未来81场加19场在管未完成、2场七天候选、1场provisional不一致，形成103条已知工作候选；另10,114条legacy义务UNKNOWN仍阻断库存完成。容量诊断不设proof、额度或生产有效期，不能转作可执行manifest。
