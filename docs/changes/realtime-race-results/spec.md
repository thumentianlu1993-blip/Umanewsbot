# 准实时赛事赛果规格

## 文档状态

- 专项：准实时赛事赛果（不接管历史回填）
- 基线：`origin/main@700a2a961516464ecf93deb0f43a751718efaaca`
- 阶段：方案与前四个离线 TDD 切片复审 `APPROVED`；停在已审核开发检查点
- 生产状态：未实现、未部署、未购买订阅、未连接生产写入
- 在线资料核对日期：2026-07-16

## 背景与目标

本专项只处理 2025 年及以后重点赛事的赛前出马表变化和赛后赛果更新。目标是在完赛后数分钟内展示带明确标识的“暂定赛果”，随后由地区官方来源复核为“正式赛果”；若官方后续改判，则展示最新客观结果并保留完整修订审计。

本期不提供比赛进行中的逐秒位置、沿途排名、直播画面、赔率推荐、第三方评级、评论、预测或大段版权内容。公开页面只展示赛事、参赛马、骑师、练马师、马号/闸位、负磅、退赛/未完赛状态、名次、时间、马身差、来源和更新时间等客观事实。

历史赛事任务必须先完成并到达明确安全检查点。本专项在此之前只允许完成方案、条款人工核对、离线 fixture、合成数据、自动测试设计和不发真实请求的开发准备；不得执行任何真实网络 proof/contract test/shadow，不得启动 Celery live worker，不得写业务数据库、部署、购买订阅或打开公开开关。

安全 handoff 必须明确：历史 runner/container、active lease、checkpoint、未完成 targets、共享 host/限速状态、资源和维护窗口；并按 event ID/series/year 明确 2025+ 目标所有权。latest main 还要求 handoff 列出 `HistoricalRaceDetailImportReceipt` 的 STARTED/COMPLETED/ABANDONED 状态、尚未生产导入的 4652 场 bundle/chunk、2026 `current_year_due` 301 场及 remaining policy 中 1096 个 new formal targets。没有完整 handoff、receipt 未终态或所有权仍重叠时，准实时专项保持 network/write fail-closed。

## 覆盖范围

### 正式目标

- 英国、法国、美国：2025 年及以后 G1-G3 / Group 1-3 / Grade 1-3。
- 中国香港：`G1/G2/G3`，并与既有正式总账身份对齐。
- 日本：`G1/G2/G3`、`JpnⅠ/JpnⅡ/JpnⅢ`、`J-G1/J-G2/J-G3`，并与既有正式总账身份对齐。`J-G1/J-G2/J-G3` 默认进入原始目标池和原始合同分母；只有完成独立 proof、生成 deferred artifact 并由用户显式批准后，selector 才能在 artifact 的精确范围和有效期内暂缓。deferred 不阻塞其余日本平地/泥地范围，但必须报告缺口，且不得宣称日本完整范围完成。
- 重要白名单赛事可以纳入，但必须由用户显式审核，不能通过名称相似自动扩张。

### 排除范围

- 2024 年及以前的历史详情补齐和历史完整率证明。
- 全天全地区、全场次高频轮询。
- 没有明确赛事身份的同名赛事。
- 未经许可的付费墙、登录后数据、页面 scraping 或第三方专有内容复制。
- The Racing API 历史包、North America add-on 或任何其他付费订阅的自动购买。

## Requirements

### Requirement 1：赛事身份和选择必须先于轮询

- 轮询对象必须已经绑定现有 `RaceEvent` / `RaceSeries`，并具有地区、官方年度、实际日期、场地、等级和可核对的外部赛事 ID 或来源 URL。
- 英法美必须符合 2025+ G1-G3 或显式白名单；香港必须符合 G1-G3；日本 G1-G3/JpnⅠ-Ⅲ/J-G1-3 全部默认属于目标池。所有赛事都必须与既有正式总账身份及首发 allowlist 对齐。J-G1-3 在没有有效、用户批准的 deferred artifact 时不得因“能力待验证”被 selector 静默排除。
- J-G1-3 proof 从历史 handoff 后首个可观测日开始连续覆盖 90 天，并抓取窗口内正式总账的全部合资格赛事；通过至少需要 3 场已完赛样本，并覆盖窗口内实际举办的每个 J-G 等级。样本不足时延长至最多 180 天；届时仍不足只形成 `availability_gap`，不能算 proof 通过。
- J-G1-3 的通过门槛与正式范围一致：identity precision 100%、完整赛果至少 99%、暂定/正式分类错误 0、必要状态/字段可表达，并满足已确认延迟 SLO。第 30 天记录来源审计 checkpoint，但独立 proof 未满 90 天不得结束；满 90 天仍无获准自动化来源、达到 180 天仍无足够样本，或至少观察 90 天且达到最低样本后任一质量门槛失败，才可提出 deferred。
- deferred artifact 必须保存原始目标数、active 数、deferred 数、精确赛事/等级、证据 SHA、失败门槛、批准人/时间和 `review_due_at`；`review_due_at` 不得晚于批准后 180 天，并须在下一场合资格赛事前复评。过期、范围外或未获用户批准的 artifact 不得影响 selector。
- 选择器只生成未来 24 小时至已完赛修订窗口内的有限目标，不扫描全量数据库或全站赛程。
- 名称、日期、场地、场次号、距离或赛事系列冲突时进入 `identity_review`，不得自动写结果。

### Requirement 2：状态机必须表达暂定、正式和改判

赛事准实时状态固定为：

`scheduled -> racecard_ready -> awaiting_result -> provisional_result -> official_result -> corrected_result`

- `RaceEvent.status` 继续承担赛前/进行中/结束/延期/取消的粗粒度状态；新的准实时状态不得破坏历史页面语义。
- 首次完整且通过身份/字段校验的非官方结果可以成为 `provisional_result`。
- 对 The Racing API 已证明覆盖并完成赛事/参赛马身份绑定的目标赛事，完整 API 赛果是暂定赛果公开主链；在 `provisional_public` 门禁开启时，不等待官方二次复核即可投影到前台，但必须明确标注“暂定赛果”和来源更新时间。
- 只有地区官方机构、监管机构或经方案审核批准的正式官方 feed 才能推进到 `official_result`。
- `corrected_result` 必须来自官方来源，或由管理员根据可追溯官方证据手动确认。
- 状态只能按允许的转移前进；延期、取消、来源回撤和人工 override 使用显式旁路状态/原因，不能静默倒退。

### Requirement 3：写入必须幂等、可审计且防冲突

- 每次来源响应先形成不可变 observation，保存来源、赛事外部 ID、抓取/来源时间、HTTP 元数据、规范化事实、内容哈希和解析版本。
- 相同 `event + source + external_revision/content_hash` 重放不得新增 canonical revision 或重复变更页面。
- racecard 与 result 都必须形成不可变 canonical revision；相同业务内容和相同 phase 去重，phase 从 provisional 变为 official 时形成新的状态 revision。
- 现有 `RaceEventRunner` / `RaceEventResult` 只作为当前投影；所有历史 importer、后台 candidate 和准实时入口必须经过同一个事件 projection control/ownership 仲裁服务，不能绕过 canonical current pointer。
- latest main 的 `historical_race_detail_chunk_import._execute_chunk()`、`apply_historical_target_candidate()`、`apply_data_candidate()` 和后台 inline 写入都属于投影写入口。receipt/chunk importer 仍需保留其 bundle/chunk/target/candidate 身份与原子 COMPLETED 语义；接入 arbitration 后，receipt completion/verifier 还必须绑定 owner generation、racecard/result revision IDs 与 content hash，避免 receipt 验证只证明旧 candidate 存在而不能证明当前投影身份。
- 2025+ live-owned event 上，旧历史 importer 和后台直接 apply 默认拒绝；人工修订必须转换为 manual observation/revision。若以后需历史修复，必须先暂停 live 并通过显式 manifest 转移事件所有权。
- 任何官方/非官方、来源间或现有人工锁字段冲突必须保留双方证据，默认不覆盖人工锁。
- 正式/改判应用与当前投影刷新在同一数据库事务完成；中途失败不得留下半张赛果。
- adapter 只能提交 observation，不能传入或决定 `project_current`。所有 shadow promotion 和新 revision 公开必须经过唯一 publication admission service；该服务在同一锁事务中读取持久化 global/region/source/event mode、条款/registry digest、地区 coverage proof、精确 event allowlist 和版本，派生是否允许公开。
- 公开 admission 必须从获准 racecard revision/expected-participant manifest 计算完整性，并读取真实 participant review 状态与人工锁；调用方提供的 `identity_valid`、`payload_complete`、`manual_lock_conflict` 布尔值不得作为最终授权依据。
- `source_key=the_racing_api` 的 authority 必须在模型、PostgreSQL 约束和 apply 三层固定为 `supplemental`；初始化、后台或调用方都不能把它提升为 official。authority decision 绑定受审 source registry digest，变更必须审计。

### Requirement 4：来源必须经过能力和条款双重验证

- 每个来源分别验证赛前出马表、退赛、暂定赛果、正式赛果、改判、字段、实际延迟、历史保留、限速、条款和故障模式。
- “网页可访问”不等于“可稳定自动化”。所有自动真实网络模式——proof、contract test、shadow 和 production——都必须先通过条款门禁。
- 常态网络需要 `terms_status=approved + automation_allowed=true`；仅 proof 获准时还必须有独立 `proof_network_allowed=true`、批准证据、有效期、请求预算和用途边界。unknown、expired、digest drift、manual 或 blocked 在所有自动网络模式均 fail closed。
- 未获网络许可的 fixture 只能使用合成数据、获许可快照或最小且经审核的客观样本；“只读”“不公开”不能替代访问许可。
- Sporting Life 当前条款明确禁止 screen scraping；Racing Post 当前条款限定个人非商业使用。这两者在取得书面许可/正式 feed 前不得建立自动生产适配器。
- Horse Racing Nation 当前公开页面对自动读取存在 robots 阻断，且未核实生产复用授权；在许可和稳定接口明确前不得成为自动主源。
- Equibase 作为美国官方数据库核验来源，但公开页面/PDF和电子产品各有使用限制；自动生产必须先取得适用许可或正式数据 feed。
- JRA、NAR、HKJC、France Galop、BHA、PMU、Geny、赛马场官网也必须完成各自条款审计；客观事实展示不替代访问/复制许可。
- 官方来源在本期承担异步二次复核，不是 The Racing API 暂定赛果首发的同步前置条件。每个进入 `provisional_public` 的赛事仍必须绑定明确的官方复核路由；官方数据未到时保持 provisional，官方一致时升级 official，官方不一致时以新 revision 原子替换并保留两份证据。
- official/corrected 判定只能消费持久化的地区级 marker contract 和不可变 marker evidence（marker 类型、响应 SHA、parser version、source timestamp）；adapter 不能只传一个布尔值。首次官方结果即使与 TRA 暂定不同也进入 `official_result`；只有已经存在 official 后的官方变化才进入 `corrected_result`，且 corrected 自动公开另受默认关闭的 source/event gate 控制。

### Requirement 5：The Racing API 必须先 Free proof、后评估 Basic

- 当前官方价格核对为 Free `£0/月`、Basic `£27.99/月`；North America add-on 为 `£49.99/月`，不在当前购买范围。价格可能变动且可能另含税，购买前必须再次联网核对。
- Free 计划使用官方 `/v1/racecards/free` 和 `/v1/results/today/free` 做真实但低频 proof；凭据只放 secret/environment，不写仓库和 artifact。
- 当前官方文档给 Free 默认 1 req/s；官网 FAQ 说当日 racecard/odds/results 约每 3 分钟更新，文档另称 Core 最新数据约每 5 分钟更新，条款又说明频率不保证。验收以实测 p50/p95 为准，不把营销数字写成 SLA。
- Basic 只有在 Free 的覆盖/延迟达到门槛，但基础字段确实阻塞产品验收时才建议升级；不得为了“可能更完整”先购买。

### Requirement 6：轮询必须按重点赛事和 host 限速

- 一个 host 的所有 adapter 共用限速器、退避状态和 circuit breaker；不能按 Celery worker 各自计数。
- 优先调用可一次返回当天多场赛事的批量 endpoint，再按赛事匹配，禁止每场重复拉同一 host 的全天数据。
- 默认窗口：T-24h 至 T-2h 每 60 分钟；T-2h 至 T-30m 每 15 分钟；T-30m 至预计开跑每 5 分钟；预计开跑后至首个暂定赛果每 3 分钟；暂定后至 T+2h 官方复核每 5-10 分钟；之后 T+24h、T+72h、T+7d 做修订探针。
- 具体间隔只能在来源条款和 proof 允许的范围内收紧；429/403/robots/许可不明必须降级或停用，不能换 User-Agent 绕过。

### Requirement 7：调度与历史/新闻资源隔离

- 采用 Celery Beat 的轻量 due-selector 加独立 `race_live` queue/worker；Beat 不直接做网络请求或解析。
- `race_live` worker 独立进程/容器、并发默认 1、显式 CPU/内存限制、独立 soft/hard time limit；新闻 worker 不消费该队列。
- 历史 runner 继续是独立原生 Docker runner，不加入 Celery/Beat；准实时任务不得读写其 runtime、租约、checkpoint 或网络预算。
- 网络 task 使用两阶段协议：短事务 claim tracking generation/attempt token 并立即释放；网络请求期间不持 event row/advisory lock 或数据库事务；响应回来后用短事务 CAS generation，迟到响应只可留 observation，不能覆盖新 revision。
- 历史任务完整 handoff 前，不执行任何真实网络 proof/contract/shadow，不启动任何环境的 `race_live` worker，也不写业务数据库；生产部署窗口还必须再次确认历史 runner、新闻任务和共享维护窗口状态。

### Requirement 8：公开页面必须准确标识状态

- 暂定赛果显示“暂定赛果”、来源类别和更新时间，不使用“官方”“已确认”等措辞。
- 正式赛果显示“正式赛果”和官方确认时间；改判显示“赛果已更正”和更正时间。
- 冲突、字段不完整或来源过期时保留上一版已发布结果并显示 stale/待复核提示，不把空结果覆盖到页面。
- 页面只显示当前 canonical revision；后台保留完整 revisions/observations 和人工处置入口。
- 不展示第三方评论、评级、tips、逐马分析、图片、视频或赔率衍生分析。

### Requirement 9：可观测、回滚和 fail-closed

- 指标至少包含每地区/来源目标数、请求数、成功率、429/403/5xx、解析失败、身份冲突、首次暂定延迟、官方确认延迟、修订数、stale 数、队列深度和最长任务时间。
- 告警至少覆盖：重点赛事 T+15m 无暂定结果、T+2h 无官方结果、连续来源失败、host circuit open、身份冲突、canonical apply 失败、队列积压和 worker 资源超限。
- 每个 provisional event 持久化官方复核 route/version、deadline、incident 状态、最后/下一探针。T+2h 以最新有效 off time 为锚点，延期时在审计事务内重算；同一 `event + provisional_revision + official_route_version` 只开一个 incident，官方一致时关闭、官方冲突时升级，随后仍按 T+24h/T+72h/T+7d 探针。
- deployment mode 唯一枚举为 `off < shadow < provisional_public < official_public`，默认 `off`；六态 tracking state 与 deployment mode 分离。global、region、source、event 的值都是“最大允许权限”，effective mode 取所有适用层级的最小值，而不是用下层覆盖上层；任一层 `off` 都是不可被下层解除的硬门。global 缺失/未知为 off，其余层缺失表示继承当前上限；显式 unknown、冲突或过期按 off。来源许可再收紧网络权限，公开 mode 还要求 event allowlist 和对应 phase gate。任何下层配置都不得把 effective mode 提升到任一上层允许范围之外。
- 回滚优先把全局切至 off，并在短事务中把 current pointer 恢复到持久化 last-known-good revision 后重投影；不删除 observations/revisions。数据库异常按备份恢复，不用反向迁移抹除审计。
- 公开读取使用独立、默认关闭的 fail-closed read gate；详情页、结果列表、sitemap/缓存都必须在读取既有 published revision 时重新计算 effective mode。global/region/source/event 任一 off 必须立即隐藏已经发布的准实时赛果，重新开启时只恢复当前获准 revision。

## 验收 SLO（待用户审核）

- 目标池命中率：正式 allowlist 赛事 100% 被选择，非目标赛事 0 次高频轮询。
- 暂定赛果：有可信 `source_updated_at` 时，来源可用到本站观察 p50 不超过 5 分钟、p95 不超过 10 分钟；没有可信时间时记录 `[previous_successful_poll_at, first_seen_at]` 区间并以区间上界作为保守采购/灰度门槛，不伪造精确时间。
- 正式赛果：有可信官方时间时，官方首次可用到本站确认 p95 不超过 15 分钟；人工外部观测与区间删失样本分层报告。失败轮询跨越的区间不得混入主 SLO，只作降级指标。
- 写入幂等：同一 observation 重放 10 次，canonical revision、当前投影和操作日志的业务变更各只发生一次。
- 错误公开：shadow/灰度样本中赛事身份错配、把暂定标为正式、静默覆盖人工锁均为 0。
- 资源：`race_live` worker 不消费新闻队列，不触碰历史 runner；压测下 web p95、新闻队列和历史 checkpoint 不出现可归因回归。

## 当前在线证据

- The Racing API plans/FAQ：<https://www.theracingapi.com/>
- The Racing API 文档：<https://api.theracingapi.com/documentation>
- The Racing API 覆盖：<https://www.theracingapi.com/data-coverage>
- The Racing API 条款：<https://www.theracingapi.com/terms-of-service>
- JRA 赛果与使用说明：<https://www.jra.go.jp/JRADB/accessS.html>、<https://www.jra.go.jp/use/index.html>
- NAR CSV 下载说明与条款：<https://www.keiba.go.jp/pdf/manual/data_pdf_manual.pdf>、<https://www.keiba.go.jp/terms.html>
- HKJC 赛果/规则/免责声明：<https://racing.hkjc.com/en-us/local/information/localresults>、<https://www.hkjc.com/English/racinginfo/racing_rules_instr.asp>、<https://www.hkjc.com/home/english/corporate/corp_disclaimer.aspx>
- France Galop 官方公报：<https://www.france-galop.com/en/node/7172>
- Sporting Life 条款：<https://www.sportinglife.com/terms-and-conditions>
- Racing Post 赛果/条款：<https://www.racingpost.com/results/>、<https://help.racingpost.com/hc/en-us/articles/208996085-Terms-and-conditions>
- PMU 规则：<https://www.pmu.fr/turf/static/reglement.pdf>
- Geny 条款：<https://www.geny.com/conditions-generales>
- Equibase 条款示例：<https://www.equibase.com/premium/eqpRegistrationTermsAndConditions9.html>

以上链接只证明 2026-07-16 可见的官方说明，不证明已经获得自动化或再发布许可。来源 proof 必须保存当次条款快照 SHA、核对时间和许可结论。

## 用户已确认的产品决定

1. 首个单地区 shadow 默认选英国；若 The Racing API Free proof 不满足覆盖/延迟，经确认后改为香港。
2. 香港范围为 G1/G2/G3；日本范围为 G1/G2/G3、JpnⅠ/Ⅱ/Ⅲ、J-G1/2/3。J-G1/2/3 实现困难时可显式延期，其余范围继续推进。
3. 暂定结果在官方延迟时继续展示并明确标注，不自动撤下；冲突时冻结上一版并提示待复核。
4. 改判页面只显示当前正式名次和“已更正”提示，详细 revision 只在后台保留。
5. 用户已授权项目方自动化接入和联系来源；来源自身的访问/再发布许可仍按 Requirement 4 逐源留证，不能由项目授权替代。
6. 接受上述暂定 p50/p95、正式确认延迟和 0 错配门槛。
