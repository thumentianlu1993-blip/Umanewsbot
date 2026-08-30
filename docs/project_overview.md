# 项目总览

2026-08-30 result/public 赛前窗口因真实内存门禁失败已自动关闭。普通 Celery worker 在 concurrency=1 下
增长到约 1.344 GiB，使 `MemAvailable` 降到 751020 kB；数据库、Redis、Swap 和磁盘不是主因。已在共享锁
内完成 10 false、移除专用 worker并重建 Web/普通 worker/Beat，终态内存恢复约 2.05 GB，队列为
`0/0/7543`、公网正常。correction 从未开启，result checkpoint 未提前执行。下一步先给普通 worker 增加
任务后回收与 512 MiB cgroup 上限，以关闭态发布并通过新热身，再从 future discovery 全量重走；暂不扩容。

2026-08-30 PR `#127` 已以 `a040af3c…257f` / `7eb5c329…9628d` 上线，migration leaf 为 `0075`。
future discovery、赛时/出马表和 lifecycle 已按冻结容量依次通过，generation 2 只纳管仍有效的 event 956；
已结束的 predecessor 不复制到 successor cohort。result apply/public 已开启并等待 event 956 的真实 T+3，
correction 仍关闭，只有真实 provider、数据库、publication 与公网结果页全部一致后才会单独放行。旧
`race_live=7543` 全程未动；当前资源高于冻结门槛，无需扩 RAM。任一后续门禁失败仍执行 10 false、移除
专用 worker并恢复普通 worker/Beat。

2026-08-30 proof-only PR `#125` 合并后、部署前发现与现有生产边界冲突：generator 原本要求所有 Redis 队列
为 0，但旧 `race_live=7543` 是明确不得消费或清理的冻结 backlog。部署已暂停并改为证明“不可执行”而非
删除历史：默认/新同步队列必须为 0，live/data-sync 网络开关全关，不得存在专用 worker 容器，Celery 只能
有普通 worker 且只订阅 `celery`。修正回归 `9/9` 通过，尚未部署、调用 TRA 或写库。

2026-08-30 经用户单独授权，旧 Created `race_live_worker` 容器及其 image 已精确删除，Redis
`race_live=7543` 不变；随后逐层清理 82 个零 tag、零容器引用 image manifest/layer，最终 dangling=0，
磁盘回升到约 10.07 GB，当前与 PR117 即时回滚 image 均保留。新 Phase 2 的普通任务 drain 已通过，但
普通/专用 worker 在 240 秒内没有输出 wrapper 要求的 `ready.` 日志文本，故在热身与 selector 前
fail-closed。普通 worker 事后实际 pong、Redis/DNS 正常且队列 5 分钟归零，说明 readiness 入口误判；仍不
追溯改写失败。当前 10 false、专用 worker absent、`celery=0 / race_sync_v2=0 / race_live=7543`，公网与
资源正常。下一窗口改用目标 hostname 的 Celery ping/inspect 判定，再从停 Beat/drain 全量重走。

2026-08-30 用户授权的 dangling image 清理在容器引用门禁处收窄：4 个零 tag、零容器引用 image 已精确删除，
但其层由旧 `race_live_worker` 的 Created 容器所引用 image 共享，仅回收 60 KiB。该 legacy 容器未运行，
队列仍为 `race_live=7543`；未取得删除容器的单独授权，因此未强删。磁盘当前
`8572174336 < 8589934592` bytes，Phase 2 没有重启，10 个新开关继续全 false。下一步需明确选择删除该
Created 容器及旧 image，或扩磁盘；不能降低门槛或动备份。

2026-08-30 PR `#120` 已以 revision `409f2ac6…2121`、image `74465006…d8df` 关闭态上线，leaf 保持
`0075`，既有 468 MiB 恢复点与 PR #120 zero-write audit 已重新验证。Phase 1 已真实纳管 event 956；旧
wrapper 把预期 enrollment delta 错判为失败后，用户确认保留，后续只读重放证明 114 blocked、1 enrolled、
0 candidate、0 provider request 且状态 SHA 不变。中断恢复又在全关状态消费了一条 Beat 竞态旧消息，
没有网络或 apply。恢复后的 Phase 2 在开任何 network/apply 前，因普通新闻任务 180 秒内未 drain 而按
门禁停止；任务稍后 SUCCESS 不使失败窗口追溯通过。当前 10 个新开关全 false、专用 worker absent，
`celery=0 / race_sync_v2=0 / race_live=7543`，公网正常。2+1 内存仍通过，无需扩 RAM；实际新约束是磁盘
`8606695424` bytes，仅比 8 GiB 底线多约 16 MiB，下一次灰度前须先经授权恢复磁盘余量或扩磁盘，不能降门槛。

2026-08-29 PR `#119` 的 Meta/Facebook 精确 `/races/`/字体 `429` 已上线；六轮约 5 分钟公网窗口通过，
目标请求不再进入 Django，普通页面、Nginx/Web 稳定性和内存门禁正常。Phase 1 重新通过后，Phase 2
专用 worker 仅约 124.7 MiB，证明现有主机无需扩容；但首次真实 discovery 的 Celery `SUCCESS` 业务上是
`blocked/future_discovery_contract_invalid`，自动保护已恢复 10 false、停止专用 worker并保持旧
`race_live=7543`。根因是 apply 错误要求 roster 路径列表字典序，而 builder 保留合法声明顺序。最小 hotfix
只禁止重复并保留与 resolved route 的逐项精确比对，不改 provider、digest、policy 或 transport；聚焦回归
`77/77` 通过。关闭态合并/发布后必须从 Phase 1 重走，不能继承失败阶段。

2026-08-29 PR `#117` 已以 revision `6e6d7977…e04`、image `cb3852e4…663c` 关闭态上线，migration no-op、
leaf `0075`，PR #116 rollback tag 已固定。正确的 sync-mount zero-write audit 为 ready/valid，畸形赛事
query 已在数据库前 301，正常赛事页约 0.036 秒；三服务一致、10 个新开关全 false，旧
`race_live=7543`。但 Meta/Facebook crawler 5 分钟仍产生 464 个请求、468 个 `/races/`，其中 321 个
虽已快速 301，crawler 仍跟随 canonical 页面并抓取大字体。冻结的 20 秒公网复测首请求即以 HTTP 000、
0 bytes 超时，故未开启 Phase 1、专用 worker或 provider 网络。主机负载、约 1.76 GiB 可用内存和完整
swap 余量正常，当前无需扩内存；后续需先单独决定 Nginx UA block/429 或 CDN/WAF 入口策略，再从全关
状态重验，不从本次失败中间续跑。

2026-08-29 PR `#116` 已以 revision `5863afae…3870` 关闭态上线，leaf 保持 `0075`。zero-write audit 与
Phase 1 的 115 场无网络 census 通过；Phase 2 的专用 worker 12 个样本稳定约 123.3 MiB，主机最低仍有
约 1.81 GiB 可用、swap 未动，现有 3.4 GiB 主机无需扩容。但公网根页在随后 20 秒门禁中超时，自动保护
已恢复 10 个开关全 false、停止专用 worker并恢复普通 worker/Beat，真实 discovery 未派发，旧
`race_live=7543` 未触碰。日志显示 20 分钟 1970 次 Meta/Facebook crawler 请求；畸形 `®ion=` query 被旧
赛事日历复制进筛选链接，放大了慢 `/races/` 请求并耗尽 2×2 Gunicorn 槽。当前 follow-up 只在 DB 查询前
规范化畸形/未知 query，并让链接只复制规范字段；不增加 Web 进程、不改 schema/provider/容量。修复仍须
关闭态发布并重新通过公网窗口，随后从 Phase 1 建立新鲜激活证据。

2026-08-29 PR `#115` 已完成关闭态生产发布与新鲜备份，migration leaf 保持 `0075`。Phase 1 的无网络
census 通过；Phase 2 专用 worker 资源热身也通过，现有 3.4 GiB 主机暂不扩容。第一次真实 discovery
暴露固定 transport 的用途名 allowlist 缺口：调用方使用 `racecards_identity_<region>_<day>`，transport
只允许旧 `racecards_sync_<day>`，因此按合同止损。生产现已恢复 10 个开关全 false、专用 worker 停止、
旧 `race_live=7543`。当前 follow-up 仅补冻结 region/day 的精确 endpoint-name + URL 二元组，不放宽网络边界；
关闭态发布后仍须从 Phase 1 重放。

2026-08-29 五阶段激活已完成 frozen admission 与 0-network future census，但 Phase 2 在发出第一个
provider 请求前因共享 host budget 的 1050ms/2000ms 精确值冲突止损。生产已恢复所有
data-sync 开关 false、专用 worker 停止，`race_live=7543` 不变。hotfix 不改 schema，将同一
provider host 的共享请求预算改为只可单调收紧，新 data-sync 可原子提高下限，legacy 可兼容
更严格但不可兼容更宽松的值。完成关闭态发布后才从 Phase 1 重放，不从失败任务中间续跑。

截至 2026-08-29，PR `#108` 的功能与 PR `#109/#110` 的 migration/release 修复已作为精确 revision
`a063ecf985539fc2d82a27170c7d634e0f7e5fc8`、image `sha256:4a5f34b1…078eb` 关闭态部署到生产。
数据库已从 leaf `0073` 正常应用 additive migration `0074/0075`，最终 leaf 精确为 `0075`；新鲜 custom
backup、隔离 release、持久 runtime/TLS、回滚镜像、服务身份和 HTTP/HTTPS 四入口均完成生产验证。
候选覆盖 future discovery、时间/出马表、lifecycle、赛果公开与更正，
并使用 `data_sync` 持久 owner、exact enrollment/source/route、provider checkpoint、DB snapshot single-flight、
`race_sync_v2` 隔离 worker 和证据绑定的 publication audit。历史 prepare exception 留下的 14 条过期
claim 已有 SHA-bound、advisory-lock-bound 的精确收口候选；不生成 bundle/delivery/赛果。全 diff 审查
发现的 migration `0075`、公开读取、shadow promotion、门禁重放、exact TRA source、snapshot
retention、终态 polling 和 T+30 alert 问题已修复并通过 SQLite/PostgreSQL 聚焦门禁。最终增量又把
future discovery/cleanup 绑定总开关、覆盖完整 snapshot lease 并消除公开批量读取 source N+1；完整
diff 独立复审最终为 `No findings`。第一次发布暴露的 no-intent 状态机和 isolated runtime/TLS 问题已经
修复，并由真实 `0073 -> 0075` 生产发布验证。候选 `dd67c789…8aa0` 此前已在停止 Beat 的关闭态窗口创建并验证 custom
backup，以 SHA-bound manifest 把 14 条过期空证据 claim 精确收口为 failed；claimed 已归零，队列、
审批、赛果、投递和 pending 集合不变，旧 Beat 已恢复。既有 lifecycle `enabled/enforce + 6 controls`
保持原授权状态；新 data-sync lifecycle 和其余新开关仍关闭。隔离 release 还暴露 Nginx 证书及历史任务
runtime 位于旧 release 相对目录的问题，已在 drain 普通任务后从原目录恢复全部服务、挂载和公网。
PR `#109` 已合并为 `69e87c44…e8ec8e`，把迁移前 leaf 精确绑定到验签 handoff artifact，迁移后仍严格要求 0075；Compose
改用 release 外稳定 runtime/TLS 根，并在停服前验证 rollback compatibility link、证书 containment 和
`nginx -t`。真实 PostgreSQL 与完整部署编排回归已通过。首次准备 isolated release 又识别出 Git tracked
`horse_profile_completion` parent 不能整目录链接；PR `#110` 只链接其四个运行态子目录并完成发布。
激活前资源门禁一度停止了启用；创建 1280 MiB 临时 swap、临时停 OneBot 和精确镜像清理仍未稳定达到
1536 MiB。后续 PSS/cgroup 拆账证明根因是常驻 Python 进程数，生产已灰度为 Web 2 workers、普通 Celery
concurrency=1。15 分钟热身与三轮调度后最低 `MemAvailable=1662256 kB`；后续繁忙窗口最低进一步到
`1639612 kB`，仍高于门槛，且队列均在 5 分钟内归零。现有
resident stack 暂不扩容。Web 切换时发生的 14 次短暂 5xx 已如实保留，稳态随后零新增 5xx。frozen
capacity 仍未注入，`race_sync_v2_worker` 未启动，future discovery、时间/出马表、data-sync lifecycle、
赛果公开及更正全部保持关闭；OneBot 已恢复，`race_sync_v2=0`、旧 `race_live=7543` 不变。下一步从
admission 第一阶段重新开始，并在专用 worker 启动/热身后重新验收；只有该门禁失败才扩容至 8 GiB。

## 历史背景（以下状态以各段日期为准）

八地区链路与 migration `0072` 已关闭态发布；当前生产代码 revision 为 PR `#98` 的精确 merge SHA
`127d4833…9528`，统一 image 为 `sha256:37f84597…8852`。2025 范围暂收缩为日本、中国香港、英国、法国和美国，
并通过 source-bound participant batch 接入既有 P0 补全、审核、release 与 verifier。首批日本 r2 已
得到 34 个完整参赛 occurrence / 16 blocker；新增桥接以 provider identity 将其保守归并为 32 个唯一
HorseProfile draft，同时保全全部 occurrence evidence。production draft 已在零网络、零数据库写入下
生成并通过语义 verifier。用户随后批准 32 个 identity 的四模块并继续冻结 16 个 blocker；production
mapping bundle 与 immutable release candidate `fc7962c3…e16e` 已生成并通过只读核验。当前仍为零业务
写入。精确 G3 随后执行，但因已有 Netkeiba 履历与 JBIS candidate 同场记录未跨来源等价，严格出赛数
守恒门禁在事务内拒绝并完整回滚。第一轮跨来源事实修复已闭锁部署，随后新候选生成又在零写入阶段识别出
Netkeiba `3中京8`/`芝2000` 与 JBIS `中京`/`2000m` 的严格表示差异；当前正以已知日本场地和公制距离
语法做最小修复。该修复已部署并生成新 candidate `d95b580b…a418a` / artifact `f74c116f…6ce0c`，内置
dry-run 把同场证据收敛为 180 create + 230 update，独立静态复审通过。线上健康，当前仍无本批业务写入；
旧 candidate 禁止重试，新对象等待精确 G3，`full_network` 未启动。

## 2026-08-09 八地区单年度分级赛参赛马补全链路（实现中）

- 既有 UmaFans 五地区 artifact 与 TJCIS 官方年度 G1/G2/G3 目录分层；新增地区的实际参赛事实只接受
  provider-bound 官方赛果，不用 Wikipedia/Wikidata，也不把报名或退赛当作参赛。
- 官方赛果通过 reviewed manifest、逐跳 HTTPS allowlist、请求预算、原始 response SHA、parser/policy
  SHA 和精确 checkpoint 运行；临时网络错误安全续跑，确定性解析/身份错误立即停止。
- 正式年度 workflow 将既有 UmaFans 七文件与新增地区 official results 作为两条独立分支；只有二者
  都完成才生成逐文件 SHA 绑定的 completion bundle，缺受审官方三文件包时禁止 full-network。
- 生产侧候选按单一年份和实际起跑生成，只允许 provider ID 或完整身份事实绑定/新建；纯马名保持
  blocked。完整资料、二代血统、全生涯和由履历重算的主胜鞍仍须通过 reviewed apply/verifier，当前
  本地实现不会自动公开或写入生产。
- 澳洲、德国和中东的资料标准化器只接受已审核的 canonical v2 cache；常驻旧五地区网络批次不因
  新增适配器自动扩围。生产 apply 已沿用同一 reviewed mapping、release manifest 和 verifier 合同，
  不为新地区另开低门槛写入入口。
- 当前生产推进范围已按用户决定暂时收缩为既有五地区。年度实际起跑 census 通过 source-bound v2
  participant batch 接入现有 P0 profile adapter；弱身份只允许由 provider profile 完整身份事实补强，
  不以马名直接合并。每批仍须经过 module review、production snapshot、release candidate 和 verifier。
- 澳洲单年 G1/G2/G3 目录不能直接使用 TJCIS 的跨年赛季章节；当前由 Racing Australia 两份相邻
  赛季官方日历拼成 2025 自然年 `346` 场，并以赛名、途程、级别从 `117` 个 meeting page 精确选表。
  Qatar 则由官网展示页派生到官方 API，临时认证信息不落盘。

## 2026-08-09 Release B 数据治理当前边界

Release B 已将赛事系列唯一身份切换到 edition，并把 duplicate equivalence 的最小身份锚点收敛为
唯一受审的官方结果 provider、HTTPS URL 与缓存内容 SHA；season catalog 等 provenance 仍完整参与
漂移校验，但不再把同一实际赛事误判为不同比赛。生产发布和新全库只读 census 已完成，后续产品
数据变化仍必须经过 14 个 series action 的人工 survivor、届次、target 与公开路径审核；在 reviewed
manifest、独立 approval 和 maintenance gate 齐备前，不会改写公开赛事或启动联网回填。
canonical path staging 原子性修复发布后，reviewed manifest 已完成生产 apply 和独立 verifier；
receipt 为 verified，maintenance 已退出且相关全局开关继续默认关闭。随后 2025 单年度正式研究
workflow 首轮成功生成七文件 artifact；artifact 诚实标记为 partial，澳洲、德国和中东的公开分类
覆盖以及大量英文名/profile 仍需后续数据来源改进，不能视为八地区完整语料。

## 日本重赏 P0 身份来源

日本马一期候选范围为 1998–2026 年的 G1/G2/G3、J-G1/J-G2/J-G3、
JpnⅠ/JpnⅡ/JpnⅢ，以及身份和训练证据完整的日本训练马海外 G1/G2/G3。系统从重赏赛事
反向取得官方马匹锚点，以 Netkeiba 与 JRA/NAR 的马名、父、母、完整出生日期共识建立待审核
身份底稿；JRA/NAR 冲突、官方锚点缺失或只有单一来源时保持阻断。

赛事等级只决定处理顺序，不替代身份证据。JRA-VAN 预留为 Windows 离线补证来源，不进入
常驻采集；整个流程继续经过显式清单、有界 prepare、人工审核、精确 SHA 和原子 commit。
当前生产没有直接官方马匹锚点，因此首个 PoC 从第二层赛事上下文开始：赛事索引最多跟随一个
唯一详情页，再以马号和精确马名锁定唯一参赛行及同 provider 马匹链接；不使用站内马名搜索。
本地实现现已完成候选选择、三套来源适配器、网络预算/缓存、双/三源比较、离线审核 artifact、
JRA-VAN 交换校验合同，以及不可变批准事件、唯一 commit receipt 和严格幂等复验。正式写入
命令要求操作者显式确认精确批准 artifact；重复提交必须完整匹配 receipt、证据摘要、结果和
审计记录才允许返回零写。来源客户端逐跳强制 HTTPS，并要求 JRA/NAR 官方锚点携带非空来源 ID；
approve 会从冻结的双/三源身份重新计算共识，不能通过修改候选字段并重算文件 SHA 自证。
真实 prepare 候选还会保存 commit 所需的完整冻结选择字段；approve 要求内嵌 candidate/blocker
与已哈希 JSONL sidecar 规范字节一致，避免审核包与待写候选脱钩。当前仍处于未部署、未触网、
未写生产的实现验证阶段，代码审查问题已修复，待原生 reviewer 会话复审。
## 2026-08-01 历史赛历 Release B 本地链路

- 历史自然年修复改为按完整赛事系列生成 v2 census；人工审核 survivor、届次、target、公开路径和
  依赖策略后，才允许进入 manifest-bound apply。
- Release B 只切换 series/edition 与 active target schema 身份；数据修复继续受默认关闭开关、
  实时 maintenance gate、独立 reviewer approval、receipt、verifier 和 exact rollback 控制。
- deploy/rollback 在 DDL 前用候选/当前 Release B image 运行只读 schema preflight；commit、image、
  migration leaf 与目标数据库 identity 任一不匹配均在应用停服前拒绝。
- 通用 rollback 只处理以 `0072` 为精确终态、同时保留受审 `0071` 依赖字节的目标，并用目标 image
  做 forward preflight；pre-0072 reverse migration 是独立停服恢复流程，不与普通回滚混用。
- schema preflight 的 leaf 来自目标库已应用的 `django_migrations`，不是候选代码图；v2 重复边界、
  target 审计、published canonical path 与 artifact no-replace 均按独立审核结论 fail closed。
- exact duplicate 同时绑定来源身份、核心字段和 runner/result；canonicalize 前必须进入确定性的
  draft/detached tombstone 终态，不能让仍公开或仍属于系列的 event 只靠 link 隐藏。
- duplicate 来源身份优先使用唯一受审的 official result provider、URL 与内容 SHA；完整 catalog
  provenance 继续进入 census precondition，但不再整体充当赛事身份。没有受审官方结果时仍按赛事名
  与完整 `source_refs` 严格拒绝。
- migration-history repair 的 recovery intent 在关闭态 verifier 后、任何 migration 前 durable
  持久化，并绑定 candidate/action/original artifact/DB identity/初始 leaf；active marker 期间只允许
  同候选 forward resume。受审 audit 以最小单文件进入候选 image；rollback 在 checkout/build 前保全
  marker provenance。`0069` decision、guard function signature/overload 与 `0071` partial predicate
  使用精确 catalog 合同。
- marker 完成转换使用 active→transition→completed 双原子 rename 状态机，不执行 path unlink；
  artifact 同时绑定 intent 是否 required。路径替换/冲突 fail closed 并保留现场，两个 rename 崩溃
  边界均可幂等恢复；Linux/macOS 均要求内核 no-replace，原语不可用即停止；final forward-resume
  仍受 reviewed-static 生产 audit 约束。
- attempt mode 仅由实际含该绑定字段的精确 artifact 激活；旧/non-Release-B 重试不会因继承陈旧环境
  值而改变 race-live freeze/restore 或 stopped-release recovery 行为。
- B→B rollback 在 checkout 前固定 v2 控制脚本与镜像；pre-v2 目标只提供最终应用镜像，artifact 仍
  精确绑定目标 commit/image，而 verifier/intent/completion 不降级到目标旧 helper。控制镜像只经
  immutable-ID Compose override 使用，不覆盖 `umanewsbot:prod`；失败续跑由受信任 control-state 固定
  同一 control/target/compose 绑定。markerless `not-required` 失败使用 checkout 前保存的唯一 control-dir
  retry script，普通 stopped-service resume 也不能绕过 active marker/control-state gate；通用 rollback
  仅支持 forward，reverse 参数显式拒绝。control-state canonical SHA 完整绑定所有 copied helper 与
  override 的 path/mode/content SHA，resume 以 nofollow fd 在 lock 前和锁内双验后才进入控制面。
  completed receipt 以 target OID、初始 artifact SHA、state SHA 标识 attempt；no-clobber/idempotent
  completion 允许未来新 attempt 再次回滚同一 target，同时 active state 单槽继续禁止并发。
- B→B rollback 目标资格现同时绑定 target commit 内 `0071` 与 `0072` 的 exact bytes SHA 和 dependency
  contract：`0071` 仅允许显式受审的 legacy/repaired 两个兼容版本，`0072` 必须为唯一受审终态；路径
  存在不再足够。receipt schema preflight 同时把 PK、两个 unique、FK 及四个 backing/pattern index
  当作完整集合校验，额外对象也会 fail closed。
- rollback 控制面与静态资源写入现明确分权：冻结的 control image 只负责 schema/migration/intent，
  artifact 绑定的 target image 通过仅改 image 的 Compose override 写同一 static volume，成功后 control
  image 才完成 intent 并允许启动服务；失败沿用同 control-state 精确重试。normal deploy 不拆分。
- 2026-08-08 生产已应用 migration-history repair 与 Release B `0068/0069/0071`，schema/code 发布完成；
  当时数据阶段仍受 reviewed v2 census gate 约束。
- 首份生产 v2 census 当时完整但不可执行：12 对 HKJC 同赛因相邻 TJCIS catalog provenance 不同而
  完整 identity SHA 不同。该检查点保持零 overlay/approval/apply/full-network；其后稳定赛事身份与
  来源 provenance 已分层、重新发布并生成新 census，最终 apply/verifier 和 2025 正式 run 的现状
  以本节顶部 2026-08-09 记录为准。

## P0 马资料生产批准链路

P0 滚动批次的内容审核与生产批准现在是两层门禁：

`触网 prepare/xlsx -> 人工确认完整子集 -> bundle -> 无写入 prepare-release candidate ->
用户按 candidate SHA 独立批准 -> commit -> 幂等复验 -> 仅按冻结范围自动首发`

`prepare-release` 只把不可变输入、预计数据库动作和发布范围封进 SHA，不代表批准，也不写业务
数据。正式提交只接受真实、active、未 supersede/abandon 的 candidate；自动首发范围来自人工通过的
artifact 行，不能因为同属一个地区 batch 就把未完成对象带入。历史 v1 release 只保留验证兼容，
新发布统一使用绑定 candidate 的 v2。

完整度语义也属于候选绑定的一部分。没有实际胜绩时，只有最新 `major_wins` 候选已 applied、
审核为 approved、payload 精确为空且带执行人/时间，系统才解释为“已确认无胜绩”；无审核、
非空 payload 或冲突仍阻断。artifact 与 candidate 携带显式完整度策略版本，策略变化会强制
产生新 SHA，旧批准不能跨版本复用；历史 v1 artifact 仅保留只读验证兼容。
历史 v1 release 只允许 dry-run，不能 commit。手工 ready 复审无胜绩档案时继续保存空列表证据，
避免复审动作自身使档案重新不完整。

## 新闻发布资格与积压链路

新闻的“抓到时间”和“通过发布门禁时间”是两个独立事实。`first_seen_at/ranked_revived_at` 负责
最近 3 小时的实时发现，`publish_ready_at` 负责 24 小时内的发布资格积压。发布窗口合并两类
有界候选后，仍统一执行主地区、来源许可、翻译与术语门禁、内容去重、评分和配额。

超过 24 小时的 ready 稿不再自动公开：24–72 小时进入人工复核指标，超过 72 小时进入过期
处置；历史无资格时间稿保持 fail-closed。旧稿只有经过逐篇审核、内容/门禁指纹和 SHA 清单锁定、
完整重校验后才能刷新资格时间，并仍须等待正常窗口；恢复动作不直接发布网页或创建 QQ 交付。

## 2026-07-20 P0 首批资料链路已进入生产

- 日本、中国香港、英国、法国、美国各 `10` 匹的完整基础资料、三代血统和完整生涯履历已按
  审核 artifact 写入生产，共 `50` 个完整档案、`1439` 条履历和 `50` 条 P0 来源。
- 马匹资料生产链路现在是
  `重点赛事参赛马确定 P0 范围 -> 按马从权威/批准来源采集完整生涯与资料 -> 字段级证据和人工审核
  -> 精确 SHA artifact dry-run/commit -> 后台复核 -> 人工首次发布`。重点赛事总账只负责确定
  P0 范围，不反推完整生涯；普通比赛履历可以不关联 `RaceEvent`。
- 暂无中文译名的 P0 马允许资料完整并在后台审核，术语保护要求译文保留原始马名；本批仍有
  `25` 匹待译。资料落库不会自动首次发布，本批 `50` 匹当前全部未公开。

## 2026-07-20 历史节点：P0 Phase A 迁移状态

- 首次生产迁移因 PostgreSQL 待处理触发器事件拒绝同事务 `CREATE INDEX` 而完整回滚；生产
  未应用 `0049`，旧服务已恢复。
- career schema、数据回填、索引约束和 authority 现拆为原子 `0049-0052` 顺序链；修复后的
  二次 Phase A 尚未执行，生产继续 **NO-GO**。

## 2026-07-20 历史节点：P0 马首批状态分层

- 冻结数据层保持不变：v1 SHA-256
  `55d80abed2b76a2d7fcf0cb97aadff800c3130c3815e84d8e6eb5b1c16b4befd`，v2 SHA-256
  `a1184dbfb0257ecbe2a4ddbc4e729b0a74d73f911c8d52a20ab65854520325b7`；v2 仍按原口径记为
  `40/50`。
- 审核研究层通过当前批次限定的美国组合来源达到 `50/50`：HRN 为主记录，Fort George
  由 Sporting Life 与 Racing Post 补充，Equibase 只用于官方总出赛数、身份和颜色对账。
  v3 研究派生物 SHA-256 为
  `98a7019a400f10a4bf961d869f38f770e9e98afab76b557a3c784d4eff6e470e`。该结论不是
  Equibase 官方逐场履历，也不全局放宽 HRN 或 `count_aligned_records_unverified`。
- 生产层仍为零写入且 blocked：readiness 只完成静态 schema 兼容检查，没有 safe simulation，
  也没有 commit-compatible artifact。正式生产 dry-run、运行态门禁和针对精确 artifact /
  集成版本的新授权均未完成，生产保持 **NO-GO**。

## 产品目标

构建一个面向中文用户的日本赛马新闻平台，将日文赛马资讯整理、翻译并发布为中文可读内容，兼顾后台运营、网页分发和后续社群推送能力。

## 核心链路

项目主链路为：

`抓取 -> 翻译 -> 术语纠偏 -> 人工编辑审核 / 自动发布 -> 发布网页端 -> QQ 群自动推送`

每一环的职责：

- 抓取：从上游来源拉取新闻列表与详情
- 翻译：先按来源正文边界移除网页框架、编辑注、无关链接和博彩推广，再将正文翻译为中文；赔率与作为赛事标题、马主等专名组成部分的博彩公司名称允许保留。日文普通赛马词、拍卖产驹、追切、访谈和出马表等场景使用字段级占位符与确定性格式保证完整、统一输出
- 术语纠偏：通过术语库保护专有名词和完整未知马名，未知马名不得按已知子术语拆译；人物、机构、普通词和英文单词型术语按文章上下文区分专名、马匹、普通词和不确定用法。不同来源语言只使用相应来源名匹配，中文译名仅用于中文文章反向识别
- 人工编辑审核：在后台修订标题、正文、摘要、标签
- 发布网页端：通过前台页面对外展示
- QQ 群自动推送：通过 OneBot 链路向启用群推送公开可访问的中文最终稿，保留后台手动推送作为补充操作

## 当前核心来源

- `netkeiba`
  - 新着顺
  - 访问量榜
  - 注目数榜
- `JRA`
  - 官方新闻

## 多地区新闻生产边界

项目当前仍以日本赛马新闻为主线，但已经具备中国香港、英国、法国、美国新闻源承载能力。多地区常态生产遵循灰度原则：

- 通用 enabled 来源轮询默认关闭，启用时按地区、来源、抓取间隔和每轮上限运行。
- 非日本新闻默认人工审核，只有显式配置允许的地区和来源才进入自动发布。
- QQ 群推送继续按群级 `allowed_regions` 灰度，旧群不会自动接收全球新闻。
- 外部赛马数据库 importer 只作为受控数据导入与马名识别底座，不属于新闻常态调度。
- 代码侧支持按赛事、马匹、骑师、正文语境和来源证据计算主地区与相关地区，并以 `off|shadow|enforce` 分阶段启用；相关地区页面和 QQ 查询另有独立开关。
- 法国来源发布时间分为已验证时间与 fallback 时间，未验证时间不得绕过新鲜度门禁；瞬时翻译失败可有界重试，但自动调度默认关闭。
- 这些能力只有通过真实 gold set、生产 dry-run 和灰度验收后才可开启，迁移和部署本身不会改变现有线上归属或自动重试行为。
- QQ 测试群通过 `PushTarget.multiregion_test_enabled` 单独灰度；该字段默认关闭，正式群在最终阶段前继续只按主地区判断。
- 翻译自动重试耗尽或永久失败会记录终态并发送运营邮件，邮件包含后台快速处理入口；自动重试总开关仍默认关闭。

## 准实时赛事赛果链路

准实时赛果与新闻、历史回填分离。来源事实先保存为 append-only observation 和 immutable
revision，再经四层 policy、逐赛事 allowlist、来源条款/authority、participant 完整性和
owner/claim CAS 决定是否形成公开 projection。The Racing API 只提供快速
`provisional_result`；官方来源的独立 evidence 才能支持后续 `official_result` 或
`corrected_result`。

定时赛果审核运行记录也采用显式终态：prepare 异常由原 token CAS 写 `failed`，租约过期且没有形成
selector、bundle 或 terminal 证据的空 claim 由严格 sweeper 收口。发布门禁仍统计所有 claimed；畸形、
活跃或已有证据的记录不会因租约过期被忽略，历史修复必须绑定 canonical manifest SHA 并整批事务执行。

首个公开候选只覆盖英国 event `924` 的已存 shadow revision，使用无网络、可哈希的
promotion/disable/restore manifest。暂定赛果可以先公开，但页面必须清晰显示“暂定”与
“尚待官方来源复核”；BHA 当前只采用人工浏览器复核和离线 evidence receipt，不自动抓取，
也不复制第三方评级、评论、赔率或页面正文。scheduler 默认关闭，其他赛事和地区不会因
部署代码自动进入公开范围。

## 历史赛事数据链路

历史赛事与新闻常态任务分离，按“正式总账 -> selection artifact -> 网络抓取 artifact -> 离线打包/dry-run -> 受控落库 -> 逐场验收”推进。batch006 起标准批次为单地区最多 250 场，仍保留地区进度、排除 snapshot、来源身份、审批 SHA、写前备份和 draft 可见性门禁。

正式批次使用 typed recipe 的分片计划：每个 shard 从实际输入内容证明 target scope，plan 同时绑定 selection、approval、manifest、镜像、工具和资源预算。日期与详情碎片只产生完整候选或带证据 gap；数据库写后由只读 verifier 核对来源、模块、数量、provenance 和 draft 状态。地区距离单位按来源原文保留，不在编排层统一换算。

长周期历史任务由独立原生 Docker runner 执行，不加入 Celery/Beat，也不属于普通 Compose project。crawl 与 apply 使用不同网络和数据库角色；runner 只按固定镜像和结构化 plan 执行，依靠数据库租约、runtime 文件锁、心跳和双 checkpoint 恢复。普通应用部署不得处理 runner、DB、Redis 或共享网络。

正式 artifact 流水线已在生产镜像 `main@ab95c6ef` 部署并通过隔离、暂停恢复和工具根拒绝 smoke。年度赛历 request/cache/parse 扩展已完成本地验收，法国 2023-2024 达到 `250/250`；batch006 将按冻结的 1061 场 selection 拆为 11 个地区×年份 scope，待新镜像部署后开始抓取，历史公开继续关闭。

单年度八地区分级赛参赛马研究是独立、只读、artifact-only 的 GitHub Actions 链路，不连接
生产数据库。它从 UmaFans sitemap 和公开赛事/马匹页生成 checkpoint 与七文件 artifact；
当前正式来源 origin 为 `http://umafans.run/`，因为生产 Nginx 尚未启用域名 HTTPS。
collector 仍以精确 host、scheme、path/query 和逐跳校验限制请求边界，base URL 同时绑定
checkpoint identity；未来切换 HTTPS 必须作为独立运维变更，并从 fresh checkpoint 开始。

## P0 马资料链路

P0 马范围由“active 且有中文译名的正式 horse term”与“五地区全部重点分级赛参赛马”组成。赛事产品覆盖只负责确定 P0 候选来源；马匹基础资料、二代血统和完整生涯必须继续按马匹主来源采集，不能从重点赛事总账反推。

重点赛事参赛记录先进入只读候选层：同场 runner/result 按马号或来源身份配对，跨赛事只使用既有 profile、来源内 external horse ID 或完整“多语种马名+父名+母名+出生年份”归并。只有马名时保持独立并交由人工补强，避免同地区同名马误并。候选审核后才允许创建 P0 来源和资料补全队列。

`HorseRaceRecord` 是单马参赛事实层，允许普通比赛不关联 `RaceEvent`；完整生涯页面按本地数据库分页展示全部履历。公开页面不请求第三方来源，资料抓取、审核写入和首次发布是三个独立门禁。

马匹来源缓存必须由来源自身马名或 alias 绑定候选身份，并为总出赛数保留来源名、URL 和带时区核验时间。受控网络客户端仅访问各地区实现登记的 HTTPS 主机并逐跳校验重定向；缺少身份或计数证据时保持部分完成，不以请求值回填或猜测资料。

同一 provider 可用其 external horse ID 绑定身份；跨 provider 必须完整命中马名、父名、母名和出生年份，不能只凭同名。生涯数据库、研究 JSON 和审核工作簿分别执行同一 fail-closed 完整度语义，只有逐场来源已核验才能显示完整。

父母实体身份使用全局一致的 provider namespace 与不透明 external ID；v2 `source_identity`
必须同时含马名、父名、母名和出生年。出生年证据是独立人工来源审核 artifact，不等同于项目
负责人逐字段审核。自动 Netkeiba 父母候选只接受无凭据、端口、query、fragment 的精确 horse
详情 URL；同名纠错必须在新版本显式留痕且不得改写冻结 v1。审核工作簿默认从 v2 JSON 生成到
独立 v2 输出和预览目录，冻结 v1 工作簿与预览不得覆盖。

## 技术栈主干

- Web / 后台：`Django`
- 数据库：`PostgreSQL`
- 异步任务：`Celery`
- 队列 / Broker：`Redis`
- 容器编排：`Docker Compose`
- 反向代理：`Nginx`
- 翻译接口：`OpenAI-compatible`，当前已支持 `SiliconFlow`
- 媒体存储：`本地磁盘 / 阿里云 OSS`

## 后台、前台、分发渠道定位

### 后台

后台承担运营与审核职责，主要用于：

- 查看抓取文章
- 维护术语库
- 编辑译文
- 审核发布
- 查看来源状态与任务状态
- 手动触发推送

当前业务后台入口为：

- `/admin/`

`Django Admin` 作为框架自带原生后台保留，用于底层数据排查与管理，不作为日常运营主入口。

### 前台

前台承担内容展示职责，主要用于：

- 展示已发布新闻列表
- 展示文章详情
- 展示赛事日历与年度赛事详情页，用于把赛前资料、赛后赛果和相关新闻按赛事组织
- 展示已发布马匹资料页，并支持用户关注马匹及其子孙代相关新闻
- 对外提供正式访问入口

当前正式域名：

- `umafans.run`
- `www.umafans.run`

赛事数据在后台分为三层口径：截至 2024 年的历史正式总账、2025 年以后的当前/未来正式赛程，以及超过宽限期后的赛果完成度。公开日历可以包含展示扩展赛事，但不得因此改变正式总账或赛果完整率；正式目标与公开赛事通过赛事系列和官方届次唯一关联。

### 分发渠道

当前分发渠道分为两类：

- 网页端公开访问
- QQ Bot 自动推送（默认灰度关闭，基于 OneBot；后台手动推送保留）
# 赛事生命周期规划

赛事产品将补齐一条与新闻、历史回填和准实时赛果相互解耦的自动生命周期：

`重点赛事时间扫描 -> 当地时区状态推进 -> 赛前结构化候选 -> 赛事影响新闻候选 ->
复用 race-live 暂定/正式赛果 -> 字段与状态审计`

赛事是否已经发生继续由 `RaceEvent.status` 表达；暂定、正式和更正赛果继续由现有 live
revision 表达。来源失败不会使赛事永久停留赛前，也不会被解释为已有赛果。该能力按生命周期、
赛前资料、新闻联动、赛果四阶段独立灰度；当前仅完成规划，生产行为未改变。

赛前资料和赛果允许采购商业 API，但订阅价格与来源权威分开判断。低成本聚合 API 可做
supplemental/provisional，只有逐地区、逐字段、逐结果阶段的官方合同或 rights-holder 证明才能
取得 official authority；合同、proof、registry 和生产启用分别授权。

# 历史赛果缺口恢复链路

赛果缺口恢复与 race-live 分流：先冻结 event/race-group 双层 inventory，再按地区生成
results-only 候选，由官方 route receipt 和 participant identity 审批后逐场原子投影。
重复赛事通过显式 canonical link 在公开入口去重，旧详情 URL 保留。historical owner
不得把第三方候选直接提升为 confirmed，也不得接管 live owner 的暂定赛果。

实现、部署、联网 candidate prepare、人工 official 审批和生产 apply 分别授权；默认状态下
不会联网或写业务数据库。
同一地区存在多个候选来源时，恢复 adapter 输入按 `region + source` 精确分片。JRA 年度列表
和详情页由 runner 物化受控上下文，每个初始请求与 redirect 都同时受全批次共享预算与
JRA-only host/path/间隔策略约束；显式 recovery mode 才能消费冻结的过期 scheduled 目标，
人工官方路由仍不得由该链路自动请求。

阶段 A schema/code 已以功能关闭状态部署，shadow/enforce 尚未启用。阶段 B0.1 将 Sporting Life、
ZEturf、Horse Racing Nation 作为独立内部参考层：保留现有解析器，只供有权限的后台交叉核验，
不进入公开赛事、正式/暂定赛果、新闻、QQ、搜索或公开 API。内部观察与可应用字段候选使用不同
模型和命令，避免把“抓取成功”误当成“可以公开”。首版只处理赛后 finished 入口，以逐日
one-shot 观察，不增加自动调度。

后续定时审核层已有默认关闭实现：每天北京时间 06:30/18:30 从最近 72 小时赛事和 14 天
pending 中生成不可变审核包并发给唯一审核人。第三方内部参考只有在审核人明确批准完整
bundle SHA、event 和行摘要后，才以“已人工审核赛果”投影；它不会因此成为官方来源。

# Race-data-sync 切片 A（本地候选，尚未发布）

赛前结构化资料新增 provider-neutral observation -> contract/authority -> field ledger -> canonical
racecard projection 候选链路，复用现有 race-live、赛事参与者身份和 revision，不新建第二套状态机或
调度器。赛事时间、取消和延期在生命周期集成切片 C 前只记候选，不直接改变 `RaceEvent` 或 control。
所有 provider/region/field 开关默认关闭；当前仅复用已有 The Racing API adapter，其余来源需完成各自
parser/proof 后才可进入运行时准入。该候选尚未 commit、PR、迁移或部署，生产行为没有变化。

## Migration-history recovery 控制面补充（本地候选）

repair runtime directory 本身是发布安全边界：普通 deploy/rollback/manual release 只在持锁后安全
初始化并复验，stopped-service resume 对缺失或不可信 parent fail closed。markerless rollback 的专用
retry 以 target、artifact SHA、state SHA 精确标识 attempt；completed-only 重放验证 exact receipt 后
不再执行 Git、Docker 或 Compose。该变化尚未 commit、PR 或部署，生产行为没有变化。

historical runner 首次纳管继续兼容 pre-0070 既有安装：只有显式 flag 与数据库/host trace 双重证明
首次安装时才跳过 Release B handoff；0070+ 永不允许此旁路。旧镜像 partial-schema 兼容 smoke 的零写
边界由 PostgreSQL 专用只读角色和权限撤销同步强制，不再依赖异步统计推断。

Release B preflight 采用 recorder/catalog-first：只有对象、列与类型合同安全后才读取 receipt 业务数据。
已知 schema drift 是稳定 JSON，连接故障仍是明确运行错误，避免把损坏 schema 误报为采集异常。
在 recorder/catalog 之前还有不可绕过的 PostgreSQL vendor 门禁；SQLite 或未知引擎不会进入生产
handoff、migration 或停服路径，catalog 未实际检查也不能产生绿色结果。
pre-0070 historical initial-install 也使用同一 durable recovery 控制面：唯一批准起点为 0067，artifact
和 marker 绑定 candidate/DB/lock/catalog；迁移中断只允许沿实际 Django plan 的 exact 单调前缀继续，
成功到 0071 后完成 marker 才可启动应用。
completion 的审计策略由已验证 artifact/marker 共同声明的 recovery origin 决定：initial-install
验证空 receipt 与 legacy 数据不变，migration-history repair 保留 reviewed-static 基线，二者不可由 CLI 切换。
所有生产 preflight 在 leaf/plan 之前验证完整 migration recorder dependency history；pre-0071 的两个
legacy uniqueness 对象则分别遵循 0024 的真实 PostgreSQL 形态（event partial index、target constraint
+ backing index），防止同名但语义错误的对象进入 0071。
rollback 控制面现在明确分为两个阶段：durable control-state 前保持原 HEAD/image 可恢复且不停服；
验签成功后只沿 content-bound pinned resume 前进。通用 migration-history resume 不直接解释 state
自述路径，先由当前 host verifier 验证 state 与完整 pinned catalog，再交给 preserved control plane。
固定旧镜像的 partial-schema compatibility smoke 还包含独立数据库认证层：临时只读角色必须先从
fixture TCP 入口证明密码、身份与 read-only default，再允许旧镜像执行任何 check 或启动服务；认证层
故障与应用兼容性结论分离。
该兼容层现已用固定生产旧镜像 `sha256:b1fecc…341a73` 在 PostgreSQL 16 的 `{0068,0070}` 与
`{0069,0070}` 两态完成真实容器验证，零写 digest、服务健康与日志门禁均通过；这关闭了技术证据缺口，
不改变生产发布仍需单独授权的治理边界。

## 马匹履历跨来源去重边界

马匹完整履历允许把不同 provider 对同一次实际出赛的证据聚合到一条 `HorseRaceRecord`，但不会按马名、
赛名或模糊文本直接合并。只有精确日期、场地、公制距离、名次和结果事实全部一致且不存在 race number/
event 冲突时才采用跨来源 fallback；多解与不完整事实继续人工阻断。正式导入在写前验证合并后的出赛数与
受审来源计数守恒，并把首次写入和重复提交使用的身份语义锁定为同一实现。

## 赛事数据全生命周期自动化

未来公开赛事现在具有一条统一的 `race_sync_v2` 数据链：standing policy 自动发现并纳管赛事，provider
checkpoint 动态抓取赛时、出马表和赛果，lifecycle control 在 T/T+30 推进状态，immutable revision
投影到公开赛果并继续观察更正。远期赛时/出马表间隔不超过 12 小时，临赛和赛后自动加密。

来源仲裁统一为 licensed racing API > 已导入官方赛事事实 > 可信第三方；公开页不暴露来源或内部确认
阶段。自动链由来源 proof、固定路由 digest、standing policy、CAS generation、请求/数据库容量和独立
kill-switch 约束，仓库默认关闭，生产启用必须绑定精确发布版本并另行确认。

批量 racecard/当日 results 在短 TTL 内按地区和日期共享完整分页快照；赛后历史结果只走 registry 明确
登记的 race-id 路由。无终态标记的结果只形成内部 provisional revision，正式/更正公开还必须覆盖完整
canonical runner roster。只有结果型 fallback 与现有 runner 通过马号和规范化马名形成唯一全双射时，
才可在同一事务补足来源身份；缺行、多解和来源合同漂移均保持零公开写入。

## 赛事数据自动化的生产运行形态

生产链现以普通 `celery` worker 与专用 `race_sync_v2` worker 隔离运行；旧 `race_live` 遗留队列不接入、
不消费。普通 worker 和 Web 已按小站负载压低并发并设置子进程回收/cgroup 上限，以资源门禁和 fail-closed
优先替代主机扩容。赛前 future discovery、赛时/出马表、lifecycle 与 result/public 已按序启用；更正自动化
仍需真实赛果公开验证后单独开启。
