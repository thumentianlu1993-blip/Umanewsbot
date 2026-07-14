# 关键决策

## 2026-07-14：batch006 起扩大标准批次并使用独立 historical runner

- batch005 继续完整遵守旧标准，即单地区最多 50 场；只有 batch005 全部写入和验收结束后，batch006 及后续标准批次才把单地区上限提高到 250 场。
- 扩容不能只修改一个命令行默认值。选择器、地区进度护栏、artifact 摘要、测试和运行手册必须使用同一口径；既有排除 snapshot、100 场地区领先护栏和待审 gap 记账规则继续有效，除非后续产品审核另行修改。
- 后续历史批次使用独立 runner 容器，固定到已验收镜像 revision，显式挂载 runtime artifact，并设置资源限制。普通 web/worker/beat 部署不得重建、停止或接管 runner，也不得借此重建 DB、Redis 或共享网络。
- runner 必须具有数据库级与应用级互斥锁、心跳、可恢复 checkpoint 和失联接管门禁；迁移前必须安全暂停。抓取阶段只允许 `network=true / write=false`，落库阶段只允许 `network=false / write=true`，任何阶段都不能同时获得两种权限。
- 上述能力必须走 OpenSpec、工程评审、完整测试、实现和反复代码 review，并在部署验收通过后才允许启动 batch006。历史公开展示继续保持关闭。
- 实现采用三张独立控制表、PostgreSQL 租约与 `fcntl` 双锁；过期租约不能被普通启动覆盖。接管必须同时证明旧容器不存在、`pg_stat_activity` 无对应 `application_name`、runtime/DB checkpoint 一致，并写入操作者与原因。
- owner token 原文只能位于 artifact 外的 0600 文件；resume/takeover 也不得通过命令行传 token。crawl control role 对 event 表只允许 append，不能删除审计事件，更不能读取或写入赛事、新闻、术语等业务表。
- 普通部署首次引入 `0031` 时只能显式设置一次 initial-install 门禁；后续迁移必须让 active runner 安全暂停。数据库、Redis 和共享网络只允许由独立 bootstrap 首次创建，普通 deploy/rollback 永远不隐式补建。
- 子进程 stdout/stderr 不通过无界内存 pipe 累积，也不把未脱敏原文写入 artifact；先写入 runner 容器受限 `/tmp` tmpfs，结束后统一脱敏并原子写正式日志。stale takeover 只能核对 artifact 根目录固定 `runner-state.json`，不接受任意替代文件。
- crawl runner 不写旧的业务 `TaskExecutionLog`，网络步骤审计统一进入 append-only `HistoricalBatchRunEvent`；普通非 runner 管理命令仍保留原任务日志。这样 control role 无需获得任何业务表权限。
- stale takeover 必须从宿主执行 `historical_runner.sh takeover`：脚本先通过 Docker 实际确认固定名称旧容器不存在，再用同 revision、同 phase 数据库凭据、internal-only 网络和只读 artifact 挂载执行接管探针。不得直接把管理命令的 `--container-absent` 当成人工声明使用。

## 2026-07-14：国际新闻正文清理必须按可信容器与语义噪声 fail closed

- 国际来源正文选择器未命中时必须返回显式失败，不得回退页面 `body`；站点 DOM 漂移应在后台暴露，而不是把导航、推荐、社交和页脚误当新闻发布。
- 与新闻事实无关的独立 URL、`click here` 行动句、编辑注、完整赛果/活动跳转、责任博彩和博彩推广必须清理。博彩公司名称只有出现在赛事标题、马主等专名或赔率事实中才保留，不能用公司名本身作为整段删除条件。
- 历史公开文的修复必须使用已保存 HTML 离线重解析、显式文章 ID、默认 dry-run、事务 commit 和操作日志；强制重译只能更新译文，必须保持公开状态、原发布时间和 QQ 幂等状态。
- 翻译完整性不能只按英中字符数和标点数判断。日期表、出马表等结构化内容可用非空行覆盖证明完整，但阈值必须向上取整，且尾句完整性和显式列表标记门禁继续生效。

## 2026-07-14：官方来源不提供马号时允许留空，但必须显式记账

- `horse_number` 的完整性以来源实际提供字段为准，不能为了满足统一格式而按结果顺序伪造号码。官方结果文件没有马号时，可保留空值，但马名、骑手、名次和来源缓存身份仍必须完整。
- batch004 的 NSA `target_id=74171` 属于此例：官方 PDF 提供 8 匹出马和 7 条正式赛果，但不提供马号。导入器允许多个空马号，同时继续禁止同一赛事的非空马号重复。
- 这类来源格式差异不阻断其他正式总账数据收集；统一进入最终产品审核清单，后续若取得权威号码来源，再通过独立候选补充，不能回写推测值。

## 2026-07-13：原定场次弃赛不等于年度赛事取消

- 年度赛事身份判断必须继续追踪改期、移师和补赛。原定日期或场地页面标记 `ABANDONED`，只能证明该场次未按原计划举行；同届赛事在其他日期或场地正式跑完时，target 仍为 `held`。
- 2025 Hampton Novices' Chase 以 `2025-01-19 / Windsor / 3m53y` 的正式结果为准，Warwick 原定场次只保留为变更证据。以后遇到相同情形，必须先排查改期和移师，不能直接改成 `cancelled`。

## 2026-07-13：逐届距离必须保留批准来源的原单位

- 不同地区和年代使用公制、mile/furlong/yard 等不同单位；总账裸数字不能作为最终展示值，也不能按地区猜测单位。
- 日期 apply 后必须核对逐届来源距离并通过权威字段门禁写回原文。字段变化会改变 target SHA，后续详情来源和最终候选必须依次重新导出、重新打包。

## 2026-07-14：地区进度护栏只比较仍有可抓目标的地区

- 同一年代带的 100 场领先上限用于同步仍在抓取的地区，不是要求五地区拥有相同赛事总量；正式总账容量较小的地区抓空后必须退出比较，否则较大地区永远无法完成。
- “仍未完成”以本批选择后是否还有未排除、可选的 pending held/cancelled due 目标判断。任一未完成地区即使本批未被手工选中，也仍参与比较；只剩一个未完成地区时没有比较对象，不因护栏拒绝。
- selection snapshot 显式排除的歧义或缺口仍是 pending，继续计入总账分母、remaining pending 和最终统一审核清单；但它们不属于当前可抓集合，不能单独冻结其他地区。
- 批次选择和 artifact 写入前各自重算可抓分母并执行护栏，summary 保存可抓地区集合。该变更不修改 expectation/resolution、不自动解决歧义、不开放历史展示。

## 2026-07-13：年度日历的竞赛类型不得覆盖赛道表面

- `flat / jumps` 是竞赛类型证据，不等同于 `turf / dirt / synthetic` 赛道表面；年度日历未明确给出表面时，保留总帐已经审核的 `surface`。
- Newcastle 的 Hoppings Stakes 不得因为进入英国平地赛日历就被改为 turf；障碍赛也不得仅因实际在草地举行就把模型中的 `jumps` 类型改写为 turf。
- 日期发现 artifact 只处理日期、直接来源和带单位距离；surface 或场地的实质修订继续走独立字段候选、证据 SHA、dry-run 和审核门禁。

## 2026-07-13：新增详情来源必须在三层白名单保持一致

- 一个新来源只有同时登记到直接 URL 的 host/authority/region 校验、补充详情来源 artifact 服务和最终详情 packager 后，才算可用于生产；任一层缺失都应 fail closed。
- NAR `keiba.go.jp` 定义为日本官方来源；Zone-Turf 定义为法国第三方数据库来源。来源缓存必须逐文件绑定原始 URL、大小和 SHA-256，不能把缓存内容配给后来合成的 URL。
- ZEturf 发现器必须保存实际下载并缓存的 URL。即使页面内容匹配另一目标，也不得按命中目标重新合成 URL，否则来源 manifest 与候选身份会分离。

## 2026-07-13：已交代 gap 用历史选样证据排除，不改产品状态

- 上一批已经进入 gap ledger、但仍应保持 pending 的目标，不得反复占用后续标准批次的地区配额；生成新批次时显式传入既有不可变 selection snapshot，在地区 limit 前按 target ID 排除。
- 排除 snapshot 必须自证 schema、inventory SHA、内部 snapshot SHA、target 数量和唯一性，并与当前总账的稳定 series/year/region/inventory 身份一致；当前 target SHA 可因成功导入或权威字段更新而变化，不作为历史排除证据失效条件。
- 新 artifact 必须复制输入 snapshot 原字节，以固定单文件 artifact 键绑定路径、大小和 SHA-256。多份 snapshot 可重复输入，target ID 去重；最终 selection 与排除集合相交时 fail closed。
- 该入口只改变选样，不修改 expectation、resolution、event 或来源证据。被排除的 pending gap 继续留在 available/remaining 分母，直到另行完成产品审核、补源或永久不可得审批。

## 2026-07-13：详情来源审批与最终数据导入必须使用不同形态的候选

- `manage_historical_race_detail_sources` 必须读取仍带 `year / slug` 的原始解析候选，用于按年度赛事建立来源审批 artifact；不得把只含 target 绑定信息的最终导入包反向当作来源发现输入。
- 来源 artifact apply 会把批准证据写入 target 与 RaceEvent，并改变 target SHA。因此来源 apply 后必须重新导出 event input，再运行 `package_historical_race_detail_candidates.py` 生成新的最终导入包。
- `import_historical_race_event_candidates` 只接受这个写后重打包文件，并同时锁定文件 SHA-256、target SHA、inventory artifact SHA、来源 URL 和 source-cache identity。任何来源审批后的旧包都应因 target SHA 漂移而拒绝。
- 该分层只改变技术证据链，不改变产品语义：`ABANDONED`、`not run`、`cancelled`、`not_held` 仍按各自审核规则处理，不能因详情来源存在就自动修改总账。

## 2026-07-13：年度来源的 `not run` 只能生成审核证据，不自动改总账

- TOBA 等权威年度表若将某赛事明确标为 `not run`，来源发现工具应输出结构化 `source_reports_not_run`，保留来源赛事名、场地和状态。
- 该证据说明当前 `held` 预期可能有误，但来源发现阶段不得自行把 target 改为 `not_held`，也不得生成伪结果 URL、RaceEvent 或永久不可得结论。
- expectation 状态变化属于产品总账决策，需经审核后通过受控 artifact 更新；未批准前目标保持 pending，其他无关目标可继续抓取。
- TOBA 单场结果 URL 必须一对一绑定 target；同一 URL 若匹配多个系列，所有冲突候选均 fail closed。名称消歧中的 `Fillies`、`Turf`、`Sprint` 按完整单词判断，避免短名称包含或赞助词子串导致串场。

## 2026-07-13：法国新鲜度与多地区归属工程评审决策

- 归属采用 `MULTIREGION_ATTRIBUTION_MODE=off|shadow|enforce` 单一模式；旧布尔变量只作兼容映射，相关地区查询仍使用独立开关。
- 新增结构化文章状态字段与 `MultiregionAttributionRun/Lock`；不得复用外键指向术语门禁 run 的 `TermGateReprocessLock`。
- shadow 审计与 applied 审计分命名空间保存；归属 commit 必须绑定成功 dry-run 和 manifest，支持逐篇事务、断点续跑和重复提交幂等。
- gold set 使用真实生产输入快照、双人标注与裁决，至少 250 篇且五地区各 40 篇；任一地区样本或准确率不足均为 no-go。
- 批量归属必须预加载术语、别名和赛事证据；250 篇 PostgreSQL 验收目标为 SQL `<=30`、耗时 `<=30s`、RSS 增量 `<=256 MiB`。
- 部署后默认不启用：先 off 部署，再 shadow 验证，再仅新文章 enforce，观察至少 24 小时后才可逐步开放相关地区查询、近期回填和正式群。
- 本地实现完成不等于生产资格通过。测试 fixture 和 CSV 模板不能替代至少 250 篇真实生产输入的双人标注与裁决；该数据集未完成时，change 保持 `implementing`，生产归属必须为 `off`。
- 法国时间修复、翻译失败重试和历史归属回填均采用“先 dry-run 生成持久 run/manifest，再人工审核并锁定 commit”的路径；不得通过启动服务或迁移隐式修改旧文章、公开状态或 QQ 交付。
- manifest 必须同时绑定候选结果、规则版本、术语/配置/gold 快照和质量指标；commit 直接应用审核结果，不重新推断，并将归属写入、门禁重校验和 cursor 更新纳入逐篇原子流程。
- `new_articles` 及后续阶段的自然流只对新入库文章 enforce，旧文章重复抓取仅 shadow；历史修改必须走 manifest。`web_test_groups/recent_backfill` 阶段只有显式标记 `multiregion_test_enabled` 的 QQ 群读取相关地区，`formal_groups` 后才扩大到正式群。
- 翻译终态失败邮件默认启用并发送至用户确认的 `754652181@qq.com`；自动 selector 先原子 claim 再入队，避免 worker 积压时重复塞入同一篇文章。

## 2026-07-12：门禁补跑不得复活来源日期可信度不足的历史库存

- 英文术语门禁重处理只负责重新判断术语上下文，不改变来源新鲜度标准；候选仍必须满足其抓取时适用的来源日期和新鲜度要求。
- `NewsSource#21 / CrawlJob#9408` 创建于 TDN France 真实日期修复上线前，批内 `published_at` 为错误兜底时间，因此整批 `20` 篇视为不可信库存并进入 `withdrawn` 终态，不再参与后续自动补跑。
- 本次先发布后发现的 5 篇旧文立即撤回；QQ 未产生交付。其余地区 19 篇保留公开。
- 常驻生产仍使用 `shadow`；只有 manifest 锁定的单次 commit 可临时以 `enforce` 重校验，不能据此提前切换全局模式。

## 为什么英文术语上下文门禁先进入 shadow 而不直接 enforce

术语库中保留 `Exactly / Brilliant / Title` 这类合法单词型马名是正确的，问题应在文章命中级上下文中解决，而不是删除术语。新分类器按每次实际出现区分 `proper_noun / common_word / uncertain`，真实赛事、骑师、练马师和强实体证据继续保守保护；标题、导语 uncertain 仍阻断，背景 uncertain 只 warning。

生产固定 100 篇基准已证明重处理性能达标，但真实四地区小批中仍存在大量 uncertain，且本批 `common_word` 直接命中样本不足以单独证明零误放。因此当前只启用 `shadow`：计算和记录新旧差异，旧门禁仍决定文章状态。至少观察 24 小时并抽检普通词、真实单词型马名和 uncertain 后，才允许切 `enforce`；历史文章只能引用已审核 run ID 与 manifest commit，commit 只恢复发布候选，不直接公开或创建 QQ delivery。

性能门槛不通过时不得通过提高 60 秒或 256 MiB 上限掩盖问题。本次生产基准曾暴露全地区 26,713 条术语、37 万英文 alias n-gram key 和完整重复语料/文章字段加载，最终通过地区预筛、相关快照、字段投影和英文 alias 一次预取消除无效 CPU/内存，保留既定正确性边界。

## 为什么 P0 基础代码上线后不立即执行全量来源同步

生产 dry-run 显示当前范围包含 `21596` 条有译名马术语、`992` 场重点赛事，赛事证据已有 runner `5096` 条、result `4572` 条。直接执行 `p0_horse_profiles --sync-sources --commit` 会一次写入全量术语来源并分析数千条参赛身份，超出已经确认的“日本、中国香港、英国、法国、美国各先抽 10 匹人工跑通”范围。

因此 P0 基础代码和迁移可以先上线，但来源同步 commit 必须继续服从样本优先：先完成五地区 adapter、统一 artifact、每地区 10 匹 dry-run 和人工审核，再选择受控写入方式。上线本身不得隐式启用网络补全、全量来源写入或自动首次发布；当前生产保持 `HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=false`，`HorseP0Source` 为空属于有意状态，不是部署失败。
## 为什么美国历史平地赛优先使用Equibase单场standard PDF

Equibase旧 `eqbPDFChartPlus.cfm` 和整日PDF索引可能返回防护HTML或失效链接，但同一官方体系的单场standard PDF仍可稳定提供完整实际出走、马号、闸位、骑手、练马师、负磅和官方赛果。因此美国历史平地赛继续以Equibase为主源，日期发现阶段直接绑定可验证的单场PDF，不把HTTP 200防护页或404整日索引视为成功证据。

详情生成必须使用target在日期apply时记录的唯一source-cache manifest，并逐文件匹配批准URL、大小和SHA-256；随后再复核PDF页眉日期、赛场和场次。每次只允许一个已批准manifest，禁止把批准manifest与其他manifest中的PDF混用。`1a`等联合投注编号独立保留，runners按马号排序，results按官方完赛顺序保存。

## 为什么 materialize 后发现的详情页使用独立补充来源 artifact

日期发现 artifact 已经批准并把目标 materialize 后，后续可能找到更完整的专业数据库详情页。此时重做原日期 artifact 会破坏既有审批身份，也会让日期证据与详情正文混在一起。因此补充详情页使用独立 detail-source artifact：绑定当前 target SHA、inventory SHA、provider/authority、直接 URL，并复制批准的 source-cache 字节；apply 只向 target 与 RaceEvent 的 `detail_discovery.approved_detail_sources` 追加证据，不改变赛事身份、ready 状态或 draft 可见性。

详情打包必须同时匹配批准 capture 的 `source_url / size / SHA-256`。即使 URL 相同，只要缓存正文不同也必须拒绝，避免网站后来更新的页面无声替代人工批准版本。提交时同时锁定 target 与 RaceEvent，防止并发来源维护互相覆盖。

## 为什么赛事详情来源必须按地区分层，并区分赛前声明与实际出走

不同地区的历史赛果权威入口和保存深度不同，不能使用一个第三方站点覆盖所有地区。日本采用 JRA 主源、netkeiba 历史补源和 JBIS 血统/沿革补源；中国香港采用 HKJC 官方 Race Card / Results；英国采用 Racing Post Full Result 作为历史实际出走与赛果主源，Sky Sports Racecard 补赛前页面，BHA 只承担 2014 年后官方校验；法国采用 France Galop 主源、PMU 补源；美国采用 Equibase historical charts 主源，BRISnet、DRF、BloodHorse 交叉校验，美国障碍赛事补用 NSA。

数据层必须分别保存 `declared_runners_source`、`actual_runners_source`、`non_runner_source` 和 `result_source`。Full Result 或 chart 中的 runners 只证明实际出走，不能冒充赛前声明出马表；找不到历史 racecard 时应明确标记赛前表缺失，而不是从赛果反推。所有来源还需保留原始 URL、抓取时间、来源权威级别和解析版本。

## 为什么同名赛事审核结论要生成新总账而不覆盖原始目录

TJCIS 的简写、赞助名和场地/距离字段会把同名不同赛、迁场沿革及年度改场混在一起。`2026-07-13` 的人工审核把 `102` 个临时 Key 归入 `58` 条正式赛事线，并修正京都雌马、Bristol届次、Louisville 2008、Keeneland First Lady年度名和NYRA Matron 2018等已确认异常。为保留可追溯性，原始 v10 总账保持不变，审核结果写入独立 v11；每个年度目标保留 `provisional_series_key`、正式 `series_key`、身份决策来源和别名。

赛事身份判断以沿革、场地、距离原单位、竞赛类型、年龄性别条件和同年并存情况共同决定，不能仅按裸赛事名或裸距离自动合并。实际年份与届次年份必须分开，例如 Bristol Novices' Hurdle 的 2001 届实际于 `2002-01-11` 举办。Ascot约3m金杯线中文主名确认为 `阿斯科特秋季金杯让磅障碍追逐赛`。高相似名称最终采用“15对名称变体合并、Prince of Wales's与Princess of Wales's保持独立”的审核结论，原始写法继续作为别名留存。

## 为什么历史赛事身份审核必须提供逐届参赛证据并保留距离原单位

同名赛事只比较名称、赛场和裸距离，容易把不同赛事错误合并，也可能把真实举办年份误判为 `not_held`。因此身份审核表必须把系列展开为逐年届次：能取得正式赛果时展示冠军马，能取得出马表或赛果明细时展示1号马；两者都不能可靠取得时保留该年度官方目录链接，不用模糊匹配填充空白。目录状态与官方赛果冲突时只标记待审，不自动修改总账。

不同地区和竞赛类型的距离单位不同，任何身份规则都不得直接比较 `distance_text` 裸数字。审核产物先保留 TJCIS 原始距离文本和竞赛类型；后续标准化模型必须分别保存原始数值、原始单位、统一换算值及换算规则来源，只有单位明确后才允许参与距离一致性判断。

## 为什么技术审查问题默认直接修复，产品能力与交互仍需用户审核

后续 code review 发现的纯技术问题，例如正确性、安全门禁、并发、性能、测试缺口、状态一致性和可维护性问题，默认由 Codex 直接修复、补测试并完成验证，不再逐项等待用户确认。这样可以减少已经明确方向后的重复审批，让技术返修持续推进到全绿。

涉及产品能力、数据范围、运营规则、用户流程、页面交互、公开可见性或文案体验的变更，仍必须先说明影响并交由用户审核。技术修复如果会实质改变上述产品行为，也按产品问题处理，不得借“技术优化”名义直接改变既定能力边界。

## 为什么马匹详情页使用 ID URL、草稿默认不可见并由后台审核发布

马匹名称存在多语言、重名、改译、别名和后续术语合并风险。若把公开 URL 绑定到马名或 slug，后续改名会带来重定向、重复页面和 SEO/缓存一致性问题。

因此马匹详情页 MVP 使用稳定唯一 ID：

- 公开索引：`/horses/`
- 公开详情：`/horses/<HorseProfile.id>/`
- 关注管理：`/horses/follows/`

P0 马匹页可以从 active horse `TermEntry` 默认生成，但生成后状态为 `draft`，前台返回 404；只有后台 `/admin/horse-profiles/` 人工审核、补充资料并手动发布后才公开展示。为了支持运营抢先建入口，管理员即使在资料完全空壳时也可以强制发布，但该动作会记录发布人、发布时间和备注。

## 为什么马匹关注对普通用户开放且只保存 token hash

关注功能的产品目标是让用户在新闻首页看到“关注马及其子孙代”的相关新闻，而不是后台运营专属标记。因此普通未登录用户也可以关注马匹。

实现采用匿名签名 cookie：

- cookie 保存签名后的随机 token，`HttpOnly`、`SameSite=Lax`，HTTPS 配置下启用 `Secure`。
- 数据库 `HorseFollow` 只保存 `token_hash`，不保存明文 token。
- 关注 POST 保持 CSRF 保护。
- 子孙代新闻只通过 `sire_horse_profile` / `dam_horse_profile` 的直接 profile 关系递归查询，纯文本血统不参与后代查询。

## 为什么用 HorseRaceRecord 承载完整参赛履历

马匹页第一版需要展示主胜鞍，但后续目标是每匹马的完整参赛履历。如果只建“主胜鞍表”，未来会重复建模参赛事实，也难以表达参加但未获胜、退赛、未上名等结果。

因此本轮新增 `HorseRaceRecord` 作为马-比赛事实表：

- 可选关联 `RaceEvent` / `RaceEventResult`，同时保存比赛快照字段。
- 覆盖参加过的比赛，不限于赢过的比赛。
- 主胜鞍由最高等级胜利和人工 `is_major_win` 标记共同决定。
- 无胜利、新马/未胜利、无重赏和人工指定场景都可以保守展示。

## 为什么外部血统补全走 dry-run artifact 而不是直接写公开数据

马匹资料需要尝试从外部数据补完整二代血统，但来源覆盖率、命名歧义、地区差异和反爬/限流都会影响准确性。直接从公开页或审核页实时请求第三方，会放大延迟、稳定性和来源合规风险。

因此补全策略是：

- 公开 `/horses/`、`/horses/<id>/`、首页关注模块和新闻详情 tag 只读本地数据库，不访问外部网络。
- `complete_horse_profiles --dry-run` 基于本地 `ExternalHorse` / `ExternalHorseAlias` 缓存生成 artifact、CSV 和 summary。
- summary 必须包含全局/按地区完整二代成功率、未补全占比、逐马失败原因、source URL 和候选 diff。
- `--commit` 必须读取已审核 artifact，并显式提供 `--confirm-reviewed-artifact`，不允许边抓边写。
- `new-village/KeibaScraper` 只作为受控 netkeiba 导入链路的可信数据源参考；项目当前采用本地缓存和低频导入，避免公开请求路径触网。

## 为什么马名和术语匹配一律大小写不敏感

外部赛马数据和新闻源对英文马名、赛事名、骑师名等术语的大小写并不稳定：HKJC 可能使用全大写，新闻标题可能使用标题式大小写，人工术语库也可能保留来源原始写法。如果按大小写精确匹配，会导致同一匹马在补全、新闻关联、术语替换和翻译保护链路中被误判为未命中。

因此所有含拉丁字母的术语匹配采用大小写不敏感规则：

- 术语解析、术语替换和单条术语应用对拉丁字母忽略大小写，并保留英文词边界保护。
- 外部马名 alias 和 `HorseProfile` 补全匹配使用大小写不敏感的规范化 key。
- 前台展示仍保留数据库中的原始写法；大小写不敏感只影响匹配与替换，不自动改写术语主数据。
## 为什么赛事信息编排工具第一版只服务 RaceEvent 产品层

赛事历史回填有两套容易混淆的数据层：

- `RaceEvent*`：产品层赛事，服务 `/races/`、赛事详情页、后台赛事工作台、出走表、赛果、历届冠军和相关新闻组织。
- `ExternalRace*`：外部来源缓存层，服务真实赛马数据库导入、外部马名索引和原始来源证据。

本轮 OpenSpec change `orchestrate-race-event-data-crawls` 的第一版目标是补齐赛事页可展示和可运营的结构化赛事信息，因此只服务 `RaceEvent*`，不写 `ExternalRace*` / `ExternalHorse*`。这样可以避免把“产品层赛事历史回填”和“底层外部数据库导入”混成一个过大的系统，也能让 apply 门禁聚焦在 `RaceEventRunner`、`RaceEventResult`、`RaceEventHistoryWinner` 和 `RaceEventDataCandidate` 的完整性与覆盖风险上。

对应边界：

- 五个目标地区为日本、香港、英国、法国、美国。
- 第一版同时覆盖 `runners`、`results`、`history_winners`，且同一目标范围内三模块历史深度一致。
- 第一阶段只追核心 Group / Grade / Jpn / 交流分级 / 障碍分级等重点赛事，不包含 Listed，也不追所有普通比赛。
- 历史赛事系列必须显式 `series_key` / mapping；名称模糊匹配只能进入待审候选，不得直接写正式赛事详情数据。
- 长周期抓取默认手动分批或一次性容器执行，不加入 Celery Beat，不做无人值守自动 apply。

## 为什么赛事信息编排工具需要 adapter manifest 和目标赛事行预检

现有 `runtime/tools` 详情脚本已经能生成不少候选数据，但它们不是统一命令行接口：有的依赖 `--review-csv`，有的需要 `--source-html`、`--runner-jsonl` 或 `--pdf-dir`，部分产物还使用固定年份或来源特有文件名。因此第一版编排工具不假设所有脚本都有统一 `events_csv/output_dir` 契约，而是通过 adapter manifest 逐个声明脚本路径、参数映射、依赖产物、必需输出、source authority 和输出归一化规则。

深历史详情导入还受现有 importer 约束：`import_race_event_detail_candidates` 在 dry-run 阶段也会按 `year + slug` 查找 `RaceEvent`。如果某个历史年份的目标 `RaceEvent` 行尚不存在，详情候选即使抓到了也不能直接 dry-run 或 apply。因此编排工具必须先做目标赛事行预检；缺失时输出 draft seed review artifact 和 `missing_race_event` blocker，经人工确认或导入目标赛事行后，才能进入详情候选 dry-run 与 apply-check。这个规则避免把“抓到详情候选”误判为“已经可以安全写入公开赛事页”。

## 为什么 coverage、dry-run 和 apply-check 必须绑定候选文件哈希

赛事详情批量 apply 会按模块替换已有正式行，仅凭文件路径或“某个 dry-run 文件存在”不足以证明最终导入的就是已经审计的数据。候选文件可能在 coverage 后被修改，也可能在 apply-check 时通过另一个路径替换；旧日志、空文件或其他批次结果也不能证明当前候选 dry-run 通过。

因此编排工具把候选 JSONL 的绝对路径、大小和 SHA-256 作为批次证据身份：coverage audit、结构化 `dry_run.json` 和最终 apply 文件三者哈希必须一致。adapter manifest 同时作为 provenance 权威声明，标准候选由编排层注入 `adapter_key`、`source_provider`、`racing_region` 和 `source_authority`；缺失、非法或与 manifest 冲突的来源信息直接阻断。若同一赛事的模块使用不同来源或权威等级，coverage 生成稳定策略哈希，apply-check 只有在人工确认显式包含这些哈希时才放行。

同一原则也用于 resume：跳过 adapter 不只依赖输入未变化，还必须确认上次所有必需输出仍存在且哈希一致。这样可以避免运行目录被清理或产物被修改后，state 仍错误地声称该 adapter 可以复用。

## 为什么法国 TDN broad 上线时同时允许 `tdn_france:access` 和 `tdn:access`

`tdn_france_broad` 是法国新闻补充来源，但为了和既有 TDN 去重共用同一篇原文，入库时会使用 canonical source site `tdn`，同时通过 `source_config` 保留“这是法国来源发现的文章”。

生产发布白名单判断会先看文章主来源 `article.source_site:article.source_mode`，不匹配时再看 `source_config_id`。如果只允许 `tdn_france:access`，抓取可以成功，但自动发布策略可能看到文章主来源 `tdn:access` 后判定为 `source_not_allowed`。

因此 `2026-07-07` 上线法国 TDN broad 时，生产 `.env` 同时加入：

- `tdn_france:access`：表达运营意图，即法国补充来源被允许。
- `tdn:access`：匹配 canonical 入库后的文章主来源，避免发布策略误挡。

这不会放开所有 TDN 普通新闻；它只匹配 access 模式，并且文章仍需满足地区、评分、术语门禁、发布窗口配额和 QQ 限流。

## 为什么使用香港 ECS

当前阶段选择香港 ECS，主要基于以下考虑：

- 面向中文用户，访问延迟相对可接受
- 与大陆相比，部署与公网访问流程更直接
- 不需要先被大陆备案流程阻塞
- 适合项目早期先验证真实可用性

## 为什么当前阶段不做大陆备案路线

当前目标是先把产品链路跑通，而不是先投入备案周期。

不优先走大陆备案路线的原因：

- 备案流程会显著拉长首个可用版本上线时间
- 当前更需要先验证抓取、翻译、后台、前台、域名接入是否闭环
- 项目仍处于迭代和修正阶段，先以可运行、可验证为主

后续如果产品稳定、需要大陆更优访问体验，再评估备案与境内部署。

## 为什么继续使用 Django 单体 + Docker Compose 主干

当前继续保留 `Django 单体 + Docker Compose` 主干，而不做大分离或复杂服务化，原因是：

- 后台、前台、任务调度、模型管理都可在 Django 内保持高协同
- 当前团队规模与项目阶段更适合低复杂度架构
- Docker Compose 足以支撑单机阶段的生产部署与维护
- 当前瓶颈主要是上线稳定性与运维闭环，而不是架构扩展性

## 为什么项目记忆要写入仓库文档，而不是只依赖聊天上下文

这是本项目的重要协作原则。

原因包括：

- 聊天上下文天然易丢失，不适合承载长期项目状态
- 新 session 或新协作者需要能从仓库直接恢复上下文
- 生产问题、运行态差异、关键决策必须可追溯
- 文档化后的项目记忆更容易和代码、配置、部署资产一起演进

## 为什么术语合并后保留 inactive 历史主术语

`TermEntry.is_active=false` 不只表示“废弃错误词条”，也可以表示某个历史主术语已经被更完整的正式概念吸收。

HKJC 日语 alias 合并采用这个语义：

- 英文 HKJC 官方概念作为主概念保留 active
- 同一中文译名、同一类型的日语主术语被转换为该主概念的 active alias
- 原日语主术语设为 inactive，并在 notes 中记录 `hkjc_ja_alias_merged_into_term_id=<target>`

这样做可以避免同一马名在后台搜索、翻译替换和文章回填中形成两个 active 概念，同时保留来源可追溯性。后续排查 inactive 术语时，优先看 notes 是否存在合并标记；有标记的记录应视为“已合并历史概念”，不是需要恢复的漏导入。

## 为什么当前先做 HTTP，再补 HTTPS

正式域名接入阶段先做 HTTP，再补 HTTPS，是为了降低并发排障维度。

原因是：

- 如果 DNS、Nginx、Django Host、反代、证书同时变化，定位问题会更困难
- 先完成 HTTP 域名打通，可以确认：
  - DNS 正常
  - 域名已到服务器
  - `nginx` 反代链路正常
  - Django 域名配置正确
- 在 HTTP 稳定后，再接入 HTTPS / Certbot / 强制跳转，排障范围更清晰

## 为什么自动化运营采用“规则优先 + AI 改写 + 校验”

自动发布会直接影响前台内容质量，因此不能把“是否发布”完全交给黑盒模型。

当前实现选择：

- 规则先判断硬性忽略项和必须人工审核项
- 再按来源、内容价值、P0 马、赛事优先级、时效性和结构完整度评分
- AI 负责把基准翻译稿改写成中文资讯稿
- 改写后再做术语、数字、未收录马名、引语等一致性校验

这样可以做到自动化可解释、可回看、可人工接管。

## 为什么自动化默认通过 `.env` 开关灰度启用

自动发布属于生产风险较高的能力，代码完成不等于应立即在线上全量打开。

因此新增 `AUTOMATION_ENABLED` 开关：

- 生产可以先部署迁移但保持关闭
- 后台确认字段、日志和任务正常后再开启
- 如果自动化效果不稳定，可以不回滚代码，只关闭开关

## 为什么通知 MVP 只真实发送邮件

PRD 提到邮件、短信、微信或 QQ 通知，但首版只接入邮件，其他渠道先写 `NotificationLog` 并标记为 `skipped`。

原因是：

- 邮件成本低、接入稳定、适合异常告警 MVP
- 短信需要服务商、费用和模板审核
- QQ / 微信通知涉及账号、风控和协议稳定性
- 先把异常通知留痕和最小真实发送跑通，比一次性接入多个不稳定渠道更可靠

## 为什么 QQ 群自动推送使用独立交付记录

自动推送需要处理多群、重复触发、有限重试和部分失败。如果直接复用手动推送的 `PushLog`，同一篇文章对同一群可能因为 Celery 重试或重复发布触发而产生多条发送尝试，难以保证“只自动推一次”。

因此自动推送新增以“文章 x 群”为唯一粒度的交付记录：

- 成功后后续自动编排不会重复发送到同一群
- 多个群可以分别成功、失败或重试
- URL 检查失败和 OneBot 发送失败可以分开排查
- 手动推送保留原有日志语义，不受自动推送状态机影响

`sending` 只表示当前有任务正在领取并尝试交付，不作为永久锁。若 worker 异常退出或任务在外部 I/O 中断，记录超过 `QQ_PUSH_SENDING_STALE_SECONDS` 后允许后续任务重新领取；这样可以在有限重试内恢复，而不是长期卡在“发送中”。

OneBot HTTP API 的 HTTP 200 也不直接等于发送成功。应用会继续检查 OneBot JSON 中的 `status` / `retcode`，业务失败按 `send_failed` 记录，避免 QQ 群实际未收到消息但交付记录显示成功。

OneBot 网关离线或登录态失效时，自动推送会在真正调用 `/send_group_msg` 之前暂停本次交付，并记录 `send_failed` 错误摘要，但不会增加 `attempt_count`。这样做是因为 QQ 重新扫码登录后，原文章仍然可以继续发送；如果把离线状态当成一次真实发送尝试，短时间内的队列重试会把可恢复交付快速打到失败上限。

## 为什么 QQ 群自动推送默认关闭且默认只推高价值新闻

QQ 群是强打扰分发渠道，上线初期如果全量推送，容易刷屏，也更容易暴露 QQ 账号风控和 OneBot 网关稳定性问题。

因此生产默认：

- `QQ_PUSH_ENABLED=false`：先部署代码和迁移，再配置 Bot、测试群和灰度
- `QQ_PUSH_SCOPE=high_value_only`：首版只推 `score_total >= AUTO_REVIEW_THRESHOLD` 的新闻

如需验证链路或临时全量推送，可以显式切换为 `QQ_PUSH_SCOPE=all_public`。

## 为什么 QQ 重点推送要拆分范围配置和策略配置

QQ 自动推送后续会存在多种“重点”口径：本期按 netkeiba 访问量榜 / 注目数榜推送，后续可能扩展为“榜单 + 每场比赛当天高频推”或重新支持“按分数推”。

因此后续配置需要区分两层含义：

- `QQ_PUSH_SCOPE` 表示推送范围：例如 `high_value_only` 只推重点，`all_public` 临时推所有公开新闻。
- `QQ_PUSH_IMPORTANCE_STRATEGY` 表示“重点如何判定”：本期统一为 `ranked`，即 netkeiba 访问量榜和注目数榜。

这样可以避免把 `high_value_only` 永久绑定到某一个算法，也能让后续策略扩展只修改重点判定函数，而不破坏自动推送交付、去重、重试和多群配置。

无论采用哪种重点策略，QQ 推送都不得绕过自动发布门禁。阻断问题以 `NewsArticle.gate_blockers` 或 `gate_issues.severity=blocker` 为准，QQ 服务只消费现有结构化门禁结果，不重新实现一套独立 blocker 规则。

## 为什么 OneBot API 不公网裸露

OneBot HTTP API 可以直接发送群消息，一旦公网裸露且 token 泄露或配置不当，就可能被滥用。

因此生产部署约束为：

- 优先使用 Docker 内网 `http://onebot:3000`
- 临时宿主机映射只能绑定 `127.0.0.1`
- 必须配置 access token
- 应用日志不得输出 token

## 为什么保留 fallback 改写 provider

真实 AI 改写依赖模型 Key、余额、网络和供应商稳定性。

因此保留 `fallback` 改写 provider：

- 本地测试和 CI 不依赖外部 API
- 模型不可用时仍能保守生成改写稿快照
- 生产可通过 `REWRITE_PROVIDER` 切换到 SiliconFlow 或 OpenAI-compatible provider
- 自动化主流程可以先验证状态机、日志和发布闭环，再优化真实改写质量

## 为什么赛事日历新增“复合赛道”surface

2026 美国 TOBA Grade 批次中存在 `Sur=A` 的 all-weather / synthetic 赛事，例如 Turfway Park 的 Jeff Ruby Steaks。若把这些赛事硬映射为 `dirt`，前台会显示“泥地”，与官方赛道类型不一致。

因此 `RaceEventSurface` 新增 `synthetic=复合赛道`：

- 可以准确承载美国 all-weather / synthetic 赛事。
- 后续英国、法国或其他地区出现 Polytrack、PSF、Tapeta 等复合赛道时可复用同一字段值。
- 仍保留官方原始 surface code 到 `source_refs`，便于之后做更细的赛道材质标准化。
- 这是枚举与展示层补充，不改变 `RaceEvent` 主表结构或现有 turf/dirt/jumps 数据语义。

## 为什么赛果同着使用唯一排序位写库并保留官方名次

JRA 官方赛果会出现同着，例如两匹马同为第 `2` 名。当前 `RaceEventResult` 对 `(event, finish_position)` 有唯一约束，不能直接写入两条相同 `finish_position`。

因此 2026 JRA 详情导入采用两层口径：

- `RaceEventResult.finish_position` 保存唯一排序位，用于数据库约束、排序和稳定渲染。
- `source_refs.official_finish_position` 与 `source_refs.jra_finish_position_text` 保存官方名次。
- 前台赛事日历和赛事详情页优先展示官方名次；没有官方名次时才展示排序位。

这样既不破坏当前数据库约束，也不会在用户可见页面把同着第 `2` 名错误展示成第 `3` 名。后续若要彻底支持同着、DNF、取消和除外的完整赛果语义，可以再扩展 `RaceEventResult` 的展示名次字段或调整唯一约束。

## 为什么法国 2026 赛事详情暂用 ZEturf 作为公开结果源

France Galop 官方结果入口当前会重定向到认证页，不能稳定批量读取出走表和赛果；Geny 对本批 France Galop Groupe 赛事覆盖不足，不能作为唯一来源。ZEturf 的 race detail 页面当前可通过日期和 R/C 编号访问，并提供出走表、非出走标记和到达顺序，因此本轮法国 2026 详情先用 ZEturf 作为可访问公开来源。

## 为什么英文术语发布门禁先用地区过滤和配置化高歧义词清单

多地区英文新闻中，`CLASS`、`CONTENT`、`LINK`、`AGENT` 等既可能是正式术语，也常常只是普通英文词。如果把所有地区、所有英文正式术语都拿来做硬门禁，香港马名会阻断英国新闻，普通词也会把可发布文章打入人工审核。

因此 `fix-english-term-gate-region-filter` 第一版采用保守止血策略：

- 英文文章只校验同地区术语和 `racing_region=""` 全局术语。
- 需要跨地区通用的词条先治理为全局术语，不通过 notes 或 metadata 做隐式跨地区契约。
- 高歧义英文词先由 settings / 环境变量清单控制，降级为 warning/info 并保留审计 payload。
- 短词 / 全大写等自动派生歧义规则只用于非核心命中；未配置的同地区 / 全局高可信核心实体缺失仍然阻断。
- 不新增 `TermEntry` 字段，避免为止血引入迁移和后台维护成本；后续如运营需要可再设计 `publish_gate_level` 等字段。
- 真正同地区或全局高可信核心赛事、马名、骑师名、练马师名缺失仍然阻断自动发布。

为降低同日同场多场赛事误匹配风险，法国详情导入必须用页面 title 的日期、场地和赛事名共同确认；赛事名 token 匹配排除赞助词和场地词，并对短赛事名使用更严格匹配。若后续 France Galop 官方结果页恢复可访问，应优先切回官方源或用官方源复核 ZEturf 数据。

## 为什么已确认非术语进入发布门禁忽略清单

候选池 raw 抽取会保留所有可能触发术语识别的原文片段，其中一部分已经由运营确认不是术语，例如源站导航、产品名、HTML/布局片段、普通赛马词、马名/人名片段或广告文本。这些词如果被误建成 active `TermEntry`，或者被后续规则误识别为核心术语，就会让国际新闻源因为“假术语缺失”进入人工审核。

因此 `2026-07-10` 本地新增 `MULTIREGION_TERM_GATE_IGNORED_SOURCE_TERMS`：

- 命中该清单的 source term 在发布校验中记录为 `non_term_gate_ignored` / `info`。
- 它不产生 `core_term_missing` 或 `background_term_missing`，不阻断自动发布，也不触发高价值 warning 邮件。
- 该机制独立于英文高歧义词清单；高歧义英文词仍用于“可能是术语但风险高”的降级，非术语清单用于“运营已确认不是术语”的忽略。
- 清单通过 settings / 环境变量可调整，便于后续把误加入的项移除，或继续从 raw no 类样本补充。
- 真正同地区或全局高可信核心赛事、马名、骑师名、练马师名缺失仍然阻断自动发布。

## 为什么历史冠军先写当前年度冠军作为第一层

`RaceEventHistoryWinner` 当前用于前台“近年冠军”模块。完整过去年份历届冠军需要按地区继续接入不同官方历史源，范围远大于 2026 当年赛事详情填充。

因此本轮先从已确认 `RaceEventResult` 中抽取每场 `2026` 年冠军写入 `RaceEventHistoryWinner`：已有赛果的已完赛赛事不会再显示“暂无历史冠军资料”，也不会猜测缺赛果赛事。这个数据层只代表当前年度冠军，不等同于完整历届冠军；后续补齐过去年份时，应以地区官方历史源生成完整 `history_winners.items` 后覆盖同一赛事的历史冠军列表。

## 为什么引入 OpenSpec + Codex 领域代理

项目已经进入自动化运营、HTTPS、部署稳定化和运维完善并行推进阶段，跨模块与生产高风险改动会逐渐增加。

因此仓库引入 OpenSpec 作为较大改动的规格驱动工作流：

- 在实现前先形成可版本化的 proposal、spec、design 和 tasks
- 通过 `tasks.md` 保留进度，使新 session 可以从仓库恢复上下文
- 使用 `application / integration / operations` 三个真实仓库领域拆分任务
- 子代理只在明确要求时启用，避免无控制的并行修改
- 小型修复不强制创建 OpenSpec change，但仍遵守现有阅读、验证与文档回写要求

OpenSpec 项目上下文与任务规则以 `openspec/config.yaml` 为准；项目全局状态仍以 `docs/current_state.md` 为准。

## 为什么仓库协作文档默认使用中文

项目面向中文用户，当前主要协作者也以中文进行需求、运营和生产排障沟通。为了降低新 session 恢复上下文、人工审阅规格和运维执行时的理解成本，仓库内由 Codex 新增或维护的协作文档默认使用中文。

具体约定：

- OpenSpec proposal、spec、design、tasks 的说明性内容使用中文
- Codex 代理描述、项目上下文和面向协作者的说明使用中文
- 命令、代码标识符、协议字段、第三方工具强制要求的机器语法可以保留英文
- OpenSpec 规格校验依赖的 `ADDED Requirements / Requirement / Scenario / WHEN / THEN` 等结构关键字保留英文，具体标题和内容使用中文
- 上游工具自动生成且约定不手工修改的文件维持原样

## 为什么术语发现结果必须先进入候选池

专有术语会直接影响翻译、改写、自动分流和重点赛事识别。自动识别仍可能存在误报、实体类型混淆和同名冲突，因此首版采用“发现与确认分离”：

- 规则发现器只创建或更新 `TermCandidate`，不能直接创建 `TermEntry`。
- 与正式术语同类型命中时不创建候选，跨类型命中时保留冲突信息供管理员判断。
- 接受、修改后接受和合并必须由工作人员在后台逐条完成。
- 合并到正式术语时，只有管理员明确勾选后才把候选文本加入日文别名。
- 拒绝和忽略状态在后续重复发现时保持稳定，避免候选池反复污染。

该设计优先保证正式术语库可信，并为后续接入模型识别或更多信息源保留可审计证据。

## 为什么国际化术语库采用“正式术语概念 + 多语言原文别名”

接入日本、中国香港、英国、法国和美国新闻后，同一匹马、同一场赛事或同一个人物可能同时出现日文名、英文名和繁体中文名。如果把每种语言都建成一条独立 `TermEntry`，后台会出现多个“同一实体”，自动评分、标签、翻译校验和候选合并也会越来越难解释。

因此本轮国际化返修采用两层模型：

- `TermEntry` 表示正式术语概念和标准简体中文译名，例如一匹马“春秋分”。
- `TermAlias` 表示该概念在不同原文语言下的名称或别名，例如 `イクイノックス / Equinox / 春秋分`。

文章匹配时只使用与文章 `source_language` 一致的原文别名，避免英文文章误命中日文别名；命中后仍回到同一个 `TermEntry`，用于统一的中文译名、标签和评分。

本轮保留 `TermEntry.source_ja / aliases_ja` 作为兼容字段，迁移会把旧数据回填为 `ja` 别名。后续如果要彻底重命名旧字段，应另起清理 change。

## 为什么 HKJC 日语 alias 合并会停用冗余日语主术语

HKJC 官方英文概念和既有日语主术语如果拥有同一术语类型和同一中文目标，继续保留两个 active `TermEntry` 会让后台搜索、文章术语替换和后续审计出现“同一实体多概念”的歧义。

因此 `hkjc-ja-alias-article-backfill` 采用保守合并策略：

- HKJC 英文 `TermEntry` 作为正式概念承载标准中文译名。
- 日语 source text 写入该概念的 `TermAlias(source_language=ja)`。
- 原独立日语主术语停用，并在 notes 记录合并目标 term id。

这样做不会删除历史记录，也解释了术语库中少量 inactive 术语的来源：它们可能是已经被更完整概念吸收的历史主术语，而不是应继续参与匹配的正式概念。若中文目标、术语类型或 active owner 存在冲突，系统只输出人工复核记录，不自动合并。

## 为什么已发布文章术语回填不重新翻译整篇文章

术语补齐后，历史已发布文章中可能仍保留日文或英文 source text。这个问题的修复目标是“精确替换术语”，不是重做内容生产。

因此文章回填采用字段级 diff/apply：

- dry-run 输出完整 before/after 字段值和人工复核 CSV。
- apply 只替换明确命中的 source text。
- 默认跳过人工编辑过的发布字段。
- 不重新抓取、不重新翻译、不调用 AI 改写、不改变发布、审核、workflow 或 QQ 推送状态。

这能把生产写入范围限制在可审计、可恢复的最小改动内；大范围内容重译或风格重写应另起 change。

## 为什么公开首页升级先做主 OpenSpec change

公开首页从 MVP 页面升级为 Web + 移动 H5 成熟资讯流，虽然主要发生在模板、样式和视图层，但它会影响前台信息架构、后续子能力边界和用户内容消费路径，因此先创建主 OpenSpec change `upgrade-public-home-info-feed` 作为指导规范。

这样做的原因：

- 首页不再只是“已发布文章列表”，而是要定义头条、普通流、热门代理、详情页和响应式布局的长期基础。
- 后续手工置顶、搜索频道、专题、赛事日历、站内热度等能力都可能接入首页，如果没有主规范，容易把不同问题混在一次实现里。
- 当前前台模板直接引用后台 `console.css`，需要先确立公开站点样式解耦方向，避免后台和前台继续互相牵连。
- OpenSpec 主 change 可以明确本轮只做公开资讯消费体验，不改抓取、翻译、自动发布和部署主链路。

## 为什么第一版首页不新增手工置顶或赛事日历模型

第一版首页升级选择复用现有 `NewsArticle`、`NewsSnapshot`、自动评分和赛事优先级字段，先完成算法化头条、普通新闻流和热门代理展示，不新增首页运营控制或赛事日历数据模型。

## 为什么赛事日历 MVP 使用年度 RaceEvent 产品层

赛事日历第一版采用“每年一个赛事页”的 `RaceEvent` 产品对象，而不是直接公开 `ExternalRace` 或把现有 `MajorRaceEvent` 扩成前台赛事页。

原因是：

- 前台赛事页需要可见性、资料完整度、候选确认、人工锁定和新闻纠偏，这些属于产品运营语义。
- `ExternalRace` 继续表示外部原始数据，不能直接承担“已确认可公开”的状态。
- `MajorRaceEvent` 继续服务抓取 / 发布窗口升频，不写入公开可见性、候选资料或赛果。
- 年度粒度符合赛前资料、出马表、闸位、赛果和相关新闻都随年份变化的产品形态。

第一版保留 `series_key`，只作为未来跨年系列聚合的内部伏笔，不提供系列页。

## 为什么赛事候选资料必须人工确认后再公开

赛事信息整体稳定，但指定网站抓取仍可能出现字段缺失、格式差异或来源冲突。第一版因此采用“公开字段”和“候选资料”分离：

- CSV 或后台创建的赛事满足名称、日期、马场、等级等最小条件后可展示。
- 指定网站抓取结果只写入 `RaceEventDataCandidate`，不自动覆盖公开结构化字段。
- 后台按模块应用候选，应用行为写入操作日志或任务日志。
- 已人工编辑或锁定的字段不被普通候选覆盖。

这让自动化能减轻录入工作，但最终可公开资料仍由运营人员拍板。

## 为什么赛事动态字段只对白名单自动刷新

赔率、热门度、出走状态和退赛状态变化快，适合在详情页出马表中作为动态字段刷新；赛事名称、日期、马场、等级、surface、距离、参赛条件等基础资料相对稳定，自动覆盖会增加误伤风险。

因此第一版动态刷新只允许：

- `odds_value`
- `popularity`
- `running_status`
- 退赛 / 取消出走类状态

刷新失败时保留最后一次成功值和更新时间，只在后台记录错误。

## 为什么赔率只放在赛事详情页而不进赛事日历

赛事日历的目标是按时间快速扫描赛事，不承担投注或赔率导向。赔率信息敏感且变化快，放进列表会放大合规和误读风险。

因此第一版约束为：

- 赛事日历移动卡片和 PC 表格不展示赔率。
- 赔率只在赛事详情页概览的出马表中作为普通动态字段展示。
- 赔率不进入详情页 Header，也不建设独立赔率模块。

## 为什么马匹数据库延期

赛事日历 MVP 只需要展示年度赛事、出马表、前几名赛果、历史冠军和相关新闻。完整马匹数据库、马匹详情页、血统、历史战绩会显著扩大数据建模和导入复杂度。

因此第一版只在 `RaceEventRunner`、`RaceEventResult` 和 `RaceEventHistoryWinner` 中保存展示所需的马名文本，不建立独立马匹产品页。未来如要抽出马匹数据库，应另起 change 处理。

原因是：

- 现有字段已经足够支撑“重点内容突出 + 普通内容高密度”的第一版体验。
- 手工置顶会引入推荐位模型、后台表单、排序冲突、开始/结束时间和运营权限规则，更适合作为后续独立 change。
- 赛事日历需要结构化赛事、场地、开跑时间和数据源，不应伪装成已有新闻标签或术语数据。
- 热门榜当前只能使用 netkeiba 上游访问/注目快照或自动评分回退，不能包装为本站浏览量或本站评论。

因此后续规划拆为：

- `upgrade-public-home-info-feed`：主首页与详情页信息流升级。
- `add-homepage-editorial-placement`：手工头条、推荐位和置顶。
- `add-public-topic-search-navigation`：搜索、标签页、频道页和专题页。
- `add-race-calendar-sidebar`：结构化赛事日历和今日重要赛事模块。

## 为什么 QQ 群空地区配置按旧日本行为处理

国际赛马资讯扩展后，QQ 群级配置需要区分“系统能不能推”和“这个群想看什么”。如果把旧群的空 `allowed_regions` 解释为所有地区，部署后既有群会在没有明确订阅的情况下突然收到中国香港、英国、法国和美国新闻。

因此本轮约定：

- `QQ_PUSH_ENABLED` 仍是总开关，只决定是否运行自动推送。
- `PushTarget.allowed_regions` 决定该群允许接收哪些地区。
- 迁移会把既有群回填为 `["japan"]`。
- 运行时如果仍遇到空 `allowed_regions`，也按旧行为仅允许日本新闻，而不是默认允许全球新闻。

这样能让国际新闻源上线后按群灰度启用，不打扰只想继续看日本新闻的旧群。

## 为什么公开首页资讯流升级要求严格 TDD

公开首页升级虽然主要是前台视图、模板和样式改动，但它会改变已发布文章在用户侧的呈现规则，包括发布过滤、头条选择、普通流排序、热门代理和详情页有效稿件字段展示。为了避免实现过程中只凭视觉调试而破坏已有发布链路，`upgrade-public-home-info-feed` 后续实施要求严格 TDD。

执行原则：

- 每个可测试行为单独执行 RED -> GREEN -> REFACTOR：先在 `server/stable/tests.py` 中新增一个失败测试并确认红，再实现该行为的最小代码并确认变绿，最后做局部重构。
- 禁止一次性批量写完全部测试后再实现；发布过滤、普通流排序、头条选择、热门代理、详情页字段和公开静态资源都必须按行为分轮推进。
- 热门代理实现必须在有限已发布候选集内批量读取 `NewsSnapshot` 或使用等价预取方式，避免无上限扫描或逐篇文章查询最近快照。
- 所有 TDD 循环通过后，再跑完整 `stable` 测试。
- CSS 和响应式体验不适合全部单元测试化，因此用桌面/移动浏览器视口验收作为补充验证。

该决策只约束本 change 的实施顺序，不要求为纯视觉像素差异编写脆弱测试。

## 为什么外部赛马数据采用离线低频导入

未知马名识别需要更可靠的马名来源，但不能把新闻抓取、翻译或自动发布链路绑定到实时访问 netkeiba。

因此外部赛马数据采用离线低频导入与本地索引方案：

- 使用 `keibascraper` 作为可替换适配层的数据来源，不让业务代码直接依赖第三方库返回结构。
- 先按近两年比赛、出走、赛果、马匹和履历建立本地缓存，保存结构化字段与原始 payload。
- 从出走表、赛果和可信单马参数派生本地马名索引，后续再让未知马名识别消费该索引。
- 生产默认关闭网络导入，必须人工显式触发，并且强制限速、抖动、批量上限和同一来源互斥。
- 导入失败只写入导入错误记录，不影响新闻抓取、翻译、AI 改写、自动发布和公开前台。

这个方案优先保证生产主链路稳定，也为后续替换为 JBIS、JRA-VAN 或本地公开数据库保留边界。

## 为什么外部马名索引不等同于正式术语库

外部赛马数据导入得到的 `ExternalHorseAlias` 只证明某个日文文本是外部数据源确认过的马名，不证明系统已经有可信中文译名。因此后续接入文章准备、翻译和校验时，必须把“确认是马名”和“有中文译名可替换”拆开。

设计边界如下：

- `TermEntry` 继续作为正式术语库，保存有中文译名、固定译法或人工确认别名的词条。
- `ExternalHorseAlias` 作为本地马名索引，只用于识别、保护、校验和候选发现，不批量写入 `TermEntry`。
- 如果同一马名同时命中 `TermEntry` 和 `ExternalHorseAlias`，以 `TermEntry` 为准，进入中文术语提示和译后替换。
- 如果只命中 `ExternalHorseAlias`，翻译阶段应保护原始日文马名，不能擅自生成或替换中文译名。
- 术语候选池应把新闻中出现、外部索引命中但缺少正式中文译名的马名均作为高置信候选，包括正文背景段落中的马名，让工作人员决定是否补入正式术语库。
- 普通词与外部马名同名时不能无条件信任数据库，必须结合强马名上下文消歧；缺少强马名上下文时不得把普通词当马名。
- 同一日文马名可能对应多个外部 horse ID，识别结果必须保留全部匹配 ID，并只把主 ID 作为展示辅助，避免静默丢弃同名歧义。

## 为什么国际赛马资讯扩展先做多地区承载和 HKJC 导入

项目下一阶段需要从日本赛马资讯扩展到日本、中国香港、英国、法国和美国，但不同地区的新闻语言、数据库开放度、审核可读性和 QQ 群偏好差异很大。因此国际化第一期不直接追求全地区全量抓取，而是先建立可承载多地区、多原文语言和多群推送偏好的主干能力。

具体决策：

- 前台先提供 `综合 / 日本 / 中国香港 / 英国 / 法国 / 美国` 地区 tab，综合流第一期使用已发布文章倒序，不先做复杂推荐或地区打散。
- 新闻正文第一期只支持日文、英文和繁体中文；法国新闻只接英文来源，法语正文不进入人工审核和自动发布主链路。
- 术语库先从 UI 和服务语义上改为“原文术语 -> 简体中文译名”，并增加原文语言；现有 `source_ja / aliases_ja` 物理字段暂时保留兼容，避免在同一阶段做高风险重命名。
- QQ 自动推送从全局范围配置扩展为群级配置，因为不同 QQ 群可能只想看不同地区或不同范围的新闻。
- 外部数据库第一期正式实现 HKJC，因为香港官方数据集中、字段完整、中文用户价值高；美国 `Equibase`、英国 `Sporting Life + BHA`、法国 `France Galop` 先做小样本 spike，确认字段、入口和反爬/语言风险后再进入正式导入。

该决策最初只对应 OpenSpec change `expand-international-racing-coverage` 的规划边界；`2026-06-25` 已在独立 worktree 开始本地实现。当前仍不表示国际化能力已经生产上线，后续部署需要完成完整测试、OpenSpec 校验和生产窗口确认。

review 返修后补充实现边界：HKJC 外部数据导入必须参考 netkeiba 的单来源互斥锁语义，已有运行中导入时拒绝并发写入；在真实网络抓取实现前，`--commit` 不允许写入占位 payload，必须通过 `--payload-file` 提供真实小样本；payload 超过 `max_races / max_horses` 时直接失败，不静默截断或部分写入；`max_horses` 的统计口径必须覆盖顶层 `horses`、赛事 `entries` 和 `results` 中实际会写入缓存或别名的唯一马匹，避免 entries/results 绕过批量上限；多语言术语后处理和自动化评分必须按文章 `source_language` 隔离，避免英语、繁中、日语术语在翻译、改写、重点马和赛事优先级判断中串用。

公开文章 ID 和来源去重键必须分离：公开详情页继续使用本地全局自增 `NewsArticle.id`，减少标题 slug 或上游 ID 变化带来的公开 URL 问题；但抓取入库仍需要稳定的 `source_article_id` 识别同一上游文章，否则重复抓取无法幂等更新。国际新闻源的 `source_article_id` 因此使用完整 URL 派生的低碰撞键，而不是只取 URL 最后一段 slug。

原始 HTML 和轻量 metadata 必须分离：整页 HTML 只保存到 `original_content_html`，`translation_metadata` 只保存来源语言、作者、抓取 URL、模型和 warning 等轻量元信息，避免同一份 HTML 在文本字段和 JSON 字段中重复保存。

排序型入口采用逐源确认策略：类似 netkeiba 访问量榜/注目榜的来源，只有公开 HTML 或公开 API 能稳定慢速抓取并能拿到真实文章时，才作为独立榜单源接入并记录原站排名。本轮只确认 `Sponichi 新闻ランキング` 可稳定抓取，因此先作为 `source_mode=access` 榜单源加入，默认关闭；该页面混有ボート等非赛马内容，适配器必须过滤非赛马文章并保留原站排名，不按过滤后的列表重新编号。`HKJC Racing News`、`SCMP Racing`、`BHA` 暂未发现等价公开热门新闻榜单；`Sporting Life` 有 `MOST READ RACING` 骨架容器但未确认稳定公开 API；`At The Races`、`Paulick Report` 当前 403，`BloodHorse` 有反机器人/空样本风险，均不作为生产自动榜单源启用。

上线前最终新闻源清单以真实 dry-run 可抓到两篇正文为准。第一版生产候选为：日本 `Sponichi latest/access`；中国香港 `HKJC Racing News`、`SCMP Racing`；英国 `Sporting Life Racing`、`Sky Sports Racing latest/access`，官方补充 `BHA official`；法国仅英文来源 `France Galop English News official`、`TDN France keyword`；美国 `TDN`、`Horse Racing Nation latest/access`。其中 `Sky Sports Racing Top Stories` 和 `Horse Racing Nation Trending` 作为弱热门/编辑排序信号，按页面顺序写入 rank；`At The Races`、`Paulick Report`、`BloodHorse` 保留为可单独探测候选，但不进入第一版默认清单或生产启用计划。

`TDN France keyword` 本质上仍来自 `thoroughbreddailynews.com`，与美国 `TDN` 普通源可能发现同一篇 URL。为避免同 URL 在两个 `source_site` 下重复入库，本轮采用简单 canonical 去重：文章主键使用 `TDN + source_article_id`，快照仍记录实际发现来源 `TDN France keyword`，且法国关键词来源会优先保留法国地区归类。这样既减少重复文章，也不丢失“这篇是法国相关稿”的审核和推送信号。

这样可以利用本地马名数据库降低普通词误报和真实马名漏报，同时避免把没有中文译名的外部数据污染正式术语库。

## 为什么自动发布门禁要区分 blocker / warning / info

自动化评分已经能识别高价值新闻，但近期候选池样本显示，很多高分文章不是因为内容不可发布而进入人工审核，而是被低确定性校验误伤：片假名普通词被识别成未收录马名，背景术语在摘要化稿件中被省略，数字一致性校验要求过严，长采访或引语较多也被当成硬失败。

因此后续自动发布门禁采用三层严重级别：

- `blocker`：明确不可自动发布的问题，例如缺标题、缺正文、正文过短、乱码、广告导航页、翻译失败或高度重复内容。
- `warning`：需要人工关注但初期不阻断自动发布的问题，例如疑似未收录马名、背景术语缺失、数字省略或引语较多。
- `info`：仅用于诊断和回看的问题，不影响发布分流，也不触发告警。

初期策略是 warning 不阻断自动发布，但高价值文章出现 warning 时必须邮件告警给工作人员。这样可以让自动化发布先跑起来，同时保留人工接管入口和质量抽检线索。

高价值来源只影响评分阶段放行，不绕过 blocker。首批高价值来源规划为 `netkeiba` 访问量榜和 `netkeiba` 注目数榜；如果这类文章缺正文、乱码或与已发布内容高度重复，仍然不得自动进入前台。

重复内容属于发布安全门禁：高度重复内容使用独立重复状态阻断自动发布，中等相似内容转人工审核，不归入初期不阻断的 warning。

短期默认发布内容源采用基准翻译稿，`AUTO_REWRITE_ENABLED=false` 且 `AUTO_PUBLISH_CONTENT_SOURCE=base_translation`。AI 改写字段和任务不删除，后续质量稳定后可通过配置恢复为 `rewrite` 内容源。

## 为什么原文选区快速加入术语库首版不自动重翻译

后台工作人员在候选详情页或编辑台发现新马名、赛事名、固定译法时，需要一个低摩擦入口把原文片段加入正式术语库，但“保存术语”和“让当前稿件重新应用术语”是两个风险不同的动作。

因此 `add-selection-term-quick-add` 首版只做文章上下文快速创建正式术语：

- 术语类型默认 `horse`，因为当前最常见问题是未知马名漏识别；但后台表单必须允许改类型，避免把普通词误写成马名。
- 快速入口复用正式术语校验，不绕过重复、类型、比赛等级和启用状态规则。
- 创建成功只写入 `TermEntry` 和操作日志，并记录来源文章 ID/标题；不改当前文章中文稿、基准翻译稿或改写稿。
- 不自动触发 `translate_article_task`，避免管理员只是补库时意外覆盖正在编辑的稿件。
- 编辑台页面已有外层文章编辑表单，快速术语按钮必须绑定到独立表单，避免浏览器把“加入术语库”误提交成“保存文章”。

后续如果要“新增术语后自动重新应用术语/重翻译”，应作为独立 change 处理，并显式设计覆盖字段、人工确认、失败提示和可回退路径。

## 为什么新增术语后的当前稿联动采用显式动作

`reapply-terms-after-quick-add` 继续沿用“保存术语”和“改当前稿件”分离的原则。新增术语成功后，工作人员可以通过一次性浮层选择“应用该术语到当前稿”；重新翻译保留为页面级能力，不属于术语成功浮层。系统不在保存术语后自动覆盖稿件。

这样设计的原因：

- 创建 `TermEntry` 是低风险补库动作；修改 `NewsArticle` 中文稿是内容编辑动作，应由工作人员明确触发。
- 编辑台里可能已有人工修改，默认覆盖会破坏工作人员刚完成的校对。
- 用户心智是“刚建一个新术语，就把这个术语应用到本文”，因此轻量动作只应用刚创建的指定术语，不重扫整个正式术语库。
- 指定术语应用会替换当前文章相关字段中的所有匹配位置，不限于创建术语时选中的原文片段，因为同一术语可能在文章中出现多次。
- 轻量术语应用不能等同于模型重新理解日文原文，因此需要和页面级“重新翻译”能力保持区分。
- 人工编辑字段由 `manually_edited_fields` 保护；默认指定术语应用只更新机器翻译字段、基准翻译稿和未标记人工编辑的发布稿字段。
- 快速创建成功后的应用入口只出现一次；刷新、离开页面或错过成功反馈后不补常驻入口，避免后台长期暴露容易误点的稿件修改按钮。
- 重翻译继续复用现有 `translate_article_task`，避免新增任务类型，也让最新正式术语库自然进入现有翻译提示和译文纠偏链路；若页面已有重新翻译按钮，不为术语成功浮层新增重翻译入口。

首版不做全站批量重翻译，不自动重新跑自动发布门禁，也不因指定术语应用或重翻译自动发布文章。后续如需要字段级 diff、强制覆盖人工字段或自动重跑门禁，应继续拆独立 change。

## 为什么英法美数据库源本轮仍保持 needs_more_spike

`start-hkjc-data-import-and-global-spikes` 对 `Equibase`、`Sporting Life + BHA`、`France Galop` 做了 2026-06-26 read-only spike。三地公开页面均能返回 `200`，且没有观察到明显访问阻断，但本轮只确认了浅层 HTML 入口和字段信号，没有确认稳定的结构化 API、完整单赛日/单马 URL 参数、分页/历史范围、PDF chart 解析成本或官方补字段路径。

因此本轮准入判断统一保持 `needs_more_spike`：

- 美国 `Equibase`：entries/results 有信号，但 horse profile 与 chart/PDF 仍需更具体小样本验证。
- 英国 `Sporting Life + BHA`：Sporting Life racecards/results/profile 信号较好，优先级最高；BHA 官方搜索、监管和补字段入口仍需单独复验。
- 法国 `France Galop`：英文站浅层页面可访问，但结构化赛程、报名、出马、赛果和马匹资料的稳定查询入口仍未确认；法语新闻正文仍不进入新闻审核、翻译、自动发布或 QQ 推送主链路。

后续如要正式导入英法美数据库源，必须另起 OpenSpec change，先把每个地区的具体 URL 参数、字段映射、限速、失败恢复、正式表写入边界和回滚口径设计清楚。

2026-06-26 `connect-real-global-racing-databases` 追加只读复核后，英法美仍不进入正式写库，但职责边界更清晰：

- 英国优先以 `Sporting Life` 作为正式导入主候选，因为 `racecards`、`fast-results` 和 horse profile 均可访问，且 results 页面暴露具体 racecard/profile 链接；`BHA` 作为官方补字段候选，负责复核 horses、fixtures、feed/search 等权威入口。
- 美国 `Equibase` 可继续作为唯一主候选推进 fixture spike；entries、chart/PDF index 和 horse profile 均可访问，但正式导入前必须先证明 chart/PDF 或 HTML chart 解析成本可控。
- 法国 `France Galop` 仍停留在官方页面浅层信号阶段；在定位稳定结构化查询参数前，不进入正式 parser/importer TDD。

## 为什么本轮全球赛马数据库目标关闭在“能力可用”

`2026-06-27` 用户将本轮目标从“完成最近 2 个月完整大量爬取”调整为“先保证所有地区的数据爬取能力真实可用”。因此本轮完成口径不再要求香港、英国、法国、美国都完成最近 60 天全量赛事与所有涉及马匹 profile 的真实爬取，也不要求生产 `--commit`。

本轮关闭目标的依据是：

- HKJC 已有生产真实 dry-run 批次证据，证明官方 HTML 入口、race batch、马匹详情补抓、低频请求和 dry-run 安全边界可用。
- UK / France / US 已有少量真实 proof，证明 Sporting Life、Geny、Horse Racing Nation 的赛事、赛果和马匹详情入口可访问并可解析。
- 四地 importer 均保留默认 dry-run、显式 `--allow-network`、请求上限、限速、精确批次和严格 `--commit` 门禁。
- proof-only 离线审计可以证明“能力可用”，同时完整 commit 候选审计会继续阻断缺少 plan、混合来源或马匹详情未补齐的输出。

后续若重新追求最近 60 天完整大量抓取，应作为新的执行窗口处理，并从最新 plan-only、逐批 dry-run、离线审计、备份、锁检查和用户显式确认重新开始。

## 为什么多地区新闻常态生产第一期使用配置化策略

日本以外的香港、英国、法国、美国新闻源已经接入，但真实运营仍需要先解决常态调度、人工审核边界、地区观测和 QQ 灰度，而不是马上新增一套地区策略后台模型。

因此第一期选择：

- 使用 `NEWS_SOURCE_POLL_*` 配置驱动通用 enabled 来源轮询，生产默认关闭。
- 继续保留 netkeiba / JRA 固定 Celery Beat，通用轮询默认排除这些固定调度来源，避免重复高频抓取。
- 使用 `MULTIREGION_AUTO_PUBLISH_*` settings 表达地区 / 来源 allowlist、每轮上限、每日上限和术语候选积压阈值，不新增 `RegionPublishPolicy` 模型。
- 非日本新闻默认转人工审核；只有显式配置允许的地区和来源才可能进入自动发布。
- QQ 推送继续以 `PushTarget.allowed_regions` 为群级边界；旧群空地区或非法地区配置仍只按日本兼容，不自动扩展到全球新闻。
- 外部赛马数据库 importer 继续只作为受控数据导入和马名识别底座，不进入新闻 Beat，不自动生成公开新闻、赛果页或 QQ 推送。

这样能先把“可常态运行但默认安全关闭”的闭环落地，后续若运营确实需要后台维护地区策略，再另起 change 设计模型、迁移和 UI。

## 为什么地区生产概览区分今日产能和当前积压

`operate-multiregion-news-production` 代码审查后明确：后台地区生产概览不能把历史累计发布数当成今日生产状态，否则工作人员会误判某地区今天是否真的在持续产出。

因此地区生产概览采用两类口径：

- `今日新增`、`自动发布`、`人工发布`、`公开` 表示服务器当前日期窗口内发生的生产结果。
- `待翻译`、`翻译失败`、`待审核` 表示当前仍需处理的积压队列。

这个口径能同时回答“今天有没有生产”和“现在还堵在哪里”，也避免页面默认依赖全量历史发布计数。

## 为什么正式术语地区字段为空表示全局通用

多地区新闻常态生产需要知道香港、英国、法国、美国各自的术语库准备程度，但现有正式术语长期作为全站词库使用，不能在迁移时强行归属到单一地区。

因此 `TermEntry.racing_region` 采用可选字段：

- 空值表示全局通用术语，适用于所有地区的审计统计。
- 设置地区值时，表示该术语主要用于对应地区，可在术语列表、表单、API、CSV 导入和多地区审计中按地区筛选。
- 本轮先不改变翻译/术语替换的匹配范围，避免因为加地区字段而破坏既有术语应用链路；如果后续要让翻译提示严格按地区匹配，应另起 change 设计回退和兼容规则。

## 为什么多地区新闻增量使用窗口账本而不是直接提高旧任务频率

`increase-multiregion-news-volume` 的核心目标不是单纯“多跑几次爬虫”，而是让抓取、发布和 QQ 推送都能回答同一类运营问题：这个 15 分钟或 5 分钟窗口有没有执行、为什么 0 篇、是否触发上限、能否安全重跑。

因此本轮采用 `ProductionWindow + WindowCandidateDecision + WindowTargetDecision + QuotaLedger`：

- 抓取窗口按来源建账，只有已启用、生产批准、未暂停且未 backoff 的来源进入 15 分钟调度。
- 发布窗口按地区建账，硬门禁、去重、评分、保底和配额都写入候选决策，0 发布不再只能从日志猜。
- QQ 窗口按地区建账，目标群跳过原因、群小时上限和全站小时上限都有持久化记录。
- 重要赛事只改变频率，不叠加单窗口上限；同地区重叠赛事合并为同一个 5 分钟模式。
- 新窗口 Beat 可以常驻，但生产总开关默认关闭；部署、迁移和重启不会自动切入高频生产。

旧 `auto_publish_batch_task` 在新发布窗口开启时直接跳过，避免旧任务和新窗口同时抢发文章。

抓取和 QQ 推送恢复时只执行最近一个缺失窗口，较早缺失窗口只写 `SKIPPED` 账本并标记合并到最新窗口。这样做是因为停机或 worker 堵塞后，连续补跑多个历史窗口会在真实时间内集中请求新闻源或集中发送 QQ 消息，容易触发来源站和 QQ 风控；运营仍能从窗口账本看到哪些窗口被合并跳过，而不会误以为它们正常生产。

已有 `SKIPPED` 或仍可重试的 `FAILED` QQ delivery 再次被窗口选中时，也要重新占用群小时和全站小时配额。原因是这类记录代表“又要尝试一次真实发送”，对 QQ 和用户群的打扰成本与新建 delivery 相同；只有 `PENDING / RETRYING / SENDING / SENT` 这类已经排队、正在处理或已成功的记录，才可以跳过配额，避免重复记账。

抓取窗口不能把“Celery 任务已投递”当成“抓取成功”。投递成功只说明任务进入队列，真实抓取可能仍在排队、运行或最终失败；如果此时窗口已记为成功，而来源 `last_crawl_at` 尚未更新，下一轮调度可能继续派发同一来源，反而提高抓取频率和封禁风险。因此抓取窗口由真实抓取任务完成后回写结果，来源存在 lease 未过期的运行中抓取窗口时直接跳过。

QQ 窗口同样不能把“delivery 已入队”当成“QQ 已成功发送”。OneBot 离线或登录态失效时，真实发送任务会失败，若窗口仍显示成功，运营会误判本轮 QQ 正常。因此 QQ 窗口在占用配额和创建发送任务前先做 OneBot 在线预检；离线时窗口直接记录失败原因，不消耗发送尝试，也不制造新的群消息任务。

## 为什么 ops 摘要通知先接入 UmaFans 测试群

`increase-multiregion-news-volume` 上线后，运营需要能感知窗口失败、0 发布原因和恢复情况；但生产暂时没有单独的内部运营邮箱或专用 QQ 群配置。

因此本次上线先将 `MULTIREGION_OPS_NOTIFICATION_QQ_GROUP_ID` 配置为现有 `UmaFans测试群(1026525240)`：

- 该群已经用于生产 QQ 推送验证，且已显式允许五地区新闻。
- ops 通知服务有独立开关和 30 分钟冷却，不占用用户新闻 QQ 推送配额。
- 本次只验证一次 `production_summary_task`，确认 `NotificationLog #13051` 发送成功，避免上线时额外刷屏。

后续如有正式运营群或邮件地址，应只调整 ops 通知目标，不需要改窗口调度代码。

## 为什么榜单二次命中只唤醒未发布文章而不直接发布

新闻从普通来源进入访问量榜、注目榜或国际榜单，说明它的价值可能被首次评分低估，但榜单本身不等于内容已经适合公开发布。

因此 `revive-ranked-news-for-publish` 的产品语义是“榜单唤醒”，而不是“榜单直发”：

- 榜单命中可以复活低分忽略、价值不足转人工、待翻译或翻译失败的未发布文章。
- 翻译失败或待翻译文章进入榜单后，应自动重试翻译。
- 已翻译文章进入榜单后，应重新评分，并让高价值来源信号参与自动发布判断。
- 发布仍必须经过翻译成功、自动评分、发布校验、发布窗口候选选择、配额和 QQ 限流。
- 人工拒绝、撤回、已发布、高度重复、正文缺失、核心术语缺失等硬门禁不被榜单绕过。

这样可以把榜单价值信号用在“重新认真处理”上，同时保留现有自动发布体系的可解释性和安全边界。

## 为什么榜单唤醒时间使用 `ranked_revived_at` 字段而不是只写 JSON

发布窗口需要稳定查询“最近 3 小时首次入库或最近 3 小时被榜单唤醒”的候选。如果只把唤醒时间写在 `decision_reason` JSON 里，SQLite 测试和 PostgreSQL 生产在 JSON 时间比较、索引和查询性能上都更容易分叉。

因此 `revive-ranked-news-for-publish` 采用双轨记录：

- `NewsArticle.ranked_revived_at` 是候选窗口查询和排序使用的 nullable/indexed 时间字段，历史文章默认 `NULL`，不做回填。
- `decision_reason.ranked_revival` 保存可读审计信息，包括唤醒时间、来源站点、来源模式、原 workflow/automation/translation 状态和执行动作。

这样既保证发布窗口查询简单可靠，也保留后台和窗口账本排查所需的上下文。
## 为什么术语种子数据准备先用 HKJC 体系和 WP Stud 且先审核不入库

当前多地区新闻源已经上线，但正式术语库和术语候选池仍主要是日文内容。为了补齐香港和国际赛马新闻的中文译名基础，第一批术语种子数据准备选择 HKJC 体系和 WP Stud：

- HKJC 体系包含较权威的中英文、繁中/英文对照，适合作为香港和国际赛马译名的主来源。
- WP Stud 属于高质量民间整理，适合作为别名、补充候选和译名冲突佐证，但不直接等同官方译名。
- 当 HKJC 和 WP Stud 都有译名时，以 HKJC 作为主译名，WP Stud 进入别名或备注；只有 WP Stud 时，作为需要人工审核的主译名候选。

第一版只输出 `seed_candidates.csv` 和 `seed_conflicts.csv`，不直接写入 `TermEntry`，原因是：

- 术语会影响翻译、自动评分、标签和发布校验，必须保持正式库可信。
- 种子候选需要人工审核冲突、繁简转换、地区归属和术语类型。
- `seed_candidates.csv` 严格兼容现有 `import_terms` 字段，便于复用已验证的 dry-run 与幂等导入流程。
- 所有中文目标译名统一输出简体中文；来源为繁体中文时，先做繁简转换并保留原始繁体证据。

`2026-07-03` plan-eng-review 后补充锁定：

- 第一版 HKJC 只做稳定 HTML/文本入口，`racecards` PDF、排位表 PDF 或网页排位表全量抽取延后。
- 实现前必须先做 HKJC 与 WP Stud source discovery，固定 URL、字段、fixture 和不可用入口。
- 默认输出目录为 `runtime/termbase_seed/<timestamp>/`，不得覆盖正式 `server/stable/data/terms_seed.csv`。
- 若新增繁简转换依赖，必须同步 `requirements.txt` 并测试；触网执行必须记录 timeout、非 2xx、解析失败和 incomplete 来源。

`2026-07-04` `prepare-hkjc-overseas-termbase-seeds` plan-eng-review 后补充锁定：

- HKJC overseas 精确 Race Card 输入使用可重复的 `--hkjc-overseas-race RaceDate=YYYY-MM-DD,Racecourse=<code>,RaceNo=<number>`，参数格式错误时必须拒绝执行，不能静默回退到自动发现。
- 渲染 fallback 只作为人工审核种子准备的可选能力；本变更默认不把 Playwright、浏览器二进制或图形系统依赖加入生产镜像。
- 若直接请求无法得到 Race Card 内容且没有可用渲染器或渲染后缓存，命令必须记录 `render_fallback_unavailable` 或等价原因，并把结果标记为 `incomplete=true`，不能把缺失当作空数据成功。

## 为什么术语最终导入不强行合并既有日文 alias 占用

HKJC 官方来源适合作为国际和香港赛马术语主译名，但生产库中已经存在大量日本日文主词和自动维护的日文 `TermAlias`。当 HKJC 日本马英文词条需要补日文 alias 时，如果对应日文名已被既有词条或 alias 占用，直接把 alias 迁移或复制到英文词条会产生两个风险：

- 中文目标一致时，强行合并会破坏既有日文词条的历史引用和审核痕迹。
- 中文目标不一致时，例如 `Raijin / ライジン` 或 `Scintillation / シンチレーション`，强行合并会把不同概念或地区译名折叠到同一个词条，影响翻译保护和术语应用。

因此 `2026-07-06/07` 最终术语导入采用保守策略：

- HKJC 英文词条保留官方主译名和地区。
- 只在无冲突时补充日文 alias。
- 已被既有日文主词或 alias 占用的日文名记录为 skipped，不自动迁移、不停用官方英文主词。
- 后续如果要合并个别概念，必须通过人工审核确认是同一匹马、同一中文目标和同一适用地区后，再单条处理。

## 为什么文章地区采用“主地区 + 关联地区”而不是覆盖原字段

`NewsArticle.racing_region` 已被发布窗口、配额、QQ、公开筛选和历史数据大量使用。直接把它改成多值字段会让配额归属和旧查询同时变复杂，也会影响已经发布文章的兼容性。

因此 `2026-07-10` 的多地区归属实现采用：

- `NewsArticle.racing_region` 继续代表主地区，决定发布窗口配额由哪个地区消耗。
- `NewsArticleRelatedRegion` 记录关联地区，用于地区 tab 可见性、QQ 群订阅匹配和运营汇总。
- 自动归属把赛事/赛场信号和国家、对象、机构上下文分开：只有明确赛事或赛场证据可进入“赛事地优先”，一般国家形容词只作为对象/上下文地区；来源 URL 和来源备注不参与内容归属，避免来源路径污染判断。
- 默认开启关联地区查询，但保留 `MULTIREGION_RELATED_REGION_QUERIES_ENABLED=false` 作为回退开关，可以临时让首页地区查询、公开卡片/详情地区展示、发布窗口、QQ 即时推送/窗口和地区审计全部退回只看主地区；关联地区数据不删除。
- 发布窗口可以看见关联地区候选，但未发布文章只由主地区窗口真正发布，避免同一文章被多个地区窗口重复发布。
- 后台归属锁定使用显式开关：勾选后后续自动归属和补跑不得覆盖运营最终判断；取消勾选后允许后续自动识别，普通正文编辑不会强制把开关重新打开。
- 文章编辑页把“新版字段存在但没有选择任何关联地区”解释为明确清空；只有完全没有新版字段哨兵的旧请求才保留已有关联地区，避免兼容逻辑阻止运营纠错。
- 对外展示必须以主地区为第一语义：列表使用“主地区 · 相关：…”紧凑格式，详情页和 QQ 分开显示主地区与关联地区；固定地区排序只用于关联地区内部排序。
- `2026-07-10` 审查决定：本轮不禁止后台将 `other` 保存为关联地区，保持现有兼容行为；服务层仍不把 `other` 当作有效地区集合成员。
- 重处理命令的 `--limit` 表示最多处理多少篇有效门禁候选，而不是最多扫描多少篇人工审核文章；审计输出必须说明扫描数和是否仍有更多候选。

这个设计让法国来源报道英国赛事、法国育马/拍卖相关海外赛事、爱尔兰内容暂归英国等场景可以进入多个地区池，同时保持配额和发布责任单一。

## 为什么 QQ 推送默认不放行所有内容类别

多地区新闻池扩大后，如果 QQ 按“地区命中即可推送”，普通 tips、营销投注建议、一般官方公告、拍卖/育马机构新闻会显著增加群消息量，且比网页发布更容易触发用户疲劳和平台限流。

因此本期 QQ 自动推送采用配置白名单：

- 默认允许 `news / preview / result_brief / feature` 和必要的旧兼容分类。
- 默认不允许 `tips / sales_breeding / official_notice / racecard_update` 自动群推。
- 无法可靠分类的 `other` 默认也不自动群推，必须由生产配置显式放行。
- QQ 群订阅匹配按“群允许地区”和“文章主地区 + 关联地区”求交集；同一文章对同一群仍由 `QQPushDelivery(article, target)` 唯一约束保证只发一次。

如后续运营确认某类内容适合群推，只需调整 `MULTIREGION_QQ_ALLOWED_CONTENT_CATEGORIES`，不需要改代码。

## 为什么人工审新闻补术语先写 pending 文件

逐篇检查已发布新闻时，单篇文章可能同时包含新增词条、既有词条缺跨语言 alias、以及其实已入库但已发布稿未回填的情况。如果每篇都立即写线上术语库，会增加频繁备份、dry-run、导入和回填的操作成本，也更容易把待确认译名与已确认译名混在同一次生产变更里。

因此 `2026-07-07` 起，人工审新闻补术语采用“审阅与生产写库分离”：

- 审新闻时先把待入库记录写入 `runtime/termbase_seed/manual-pending-terms.csv`，记录来源文章、参考源、动作类型、术语类型、原文语言、目标译名、待补 alias 和既有词条 ID。
- `action=create_term` 表示新增正式词条候选；`action=add_alias` 表示只给既有正式词条补跨语言 alias，不能重复建概念。
- 攒够一批后再统一执行生产备份、dry-run、正式导入和验收。
- 成功写入线上库的记录必须从 pending 文件清理或改状态，避免下一批重复导入。
- 已发布文章展示是否更新是另一件事：术语入库后仍需显式回填或重应用术语，不假设历史稿会自动变化。

## 为什么美国 2026 赛事详情先用 TOBA + HRN，而不强抓 Equibase chart

2026 美国分级赛基础范围以 TOBA 官方 American Graded Stakes 表为准；TOBA 表提供赛事、日期、赛场、等级、字段和部分 Equibase chart URL，适合定义“哪些比赛应进入赛事日历”。

赛后详情方面，Equibase chart HTML/PDF 入口当前返回 `Pardon Our Interruption` 防护页，不应尝试绕过风控或把防护页当作可解析来源。因此本轮详情导入采用：

- TOBA 官方表确定 2026 已完赛 Grade 1/2/3 范围，并优先使用 TOBA `chart_url` 中的 RaceNo 辅助匹配。
- Horse Racing Nation track-day 页面作为可访问公开来源，提供出走表和可见结果顺序。
- HRN 马名展示字段剥离 `(IRE)/(GB)/(SAF)` 等国籍后缀，原始写法保存在 `source_refs.horse_name_raw`。
- HRN 未公开 payout / also-rans 结果块的赛事，只导入出走表，不从 TOBA `winner` 字段猜完整名次。

这样能先让前台展示美国已完赛分级赛的出走表和可确认赛果，同时保留来源边界；后续若 Equibase 或赛场官方 chart 有稳定可访问入口，再用更权威来源覆盖对应 `results` 模块。

## 为什么 2026 赛事详情补齐允许显式映射和取消状态修正

2026 年五地区重赏赛事详情补齐时，部分基础赛程表与赛后结果页存在真实世界差异：赛事可能取消、延期、改场地，或者赞助名 / 标题发生变化。如果继续只靠日期、场地和标题模糊匹配，会有两类风险：

- 真正取消或废止的比赛被错误标记为“已完赛但缺赛果”，导致前台长期显示不完整。
- 法国、英国这类标题变化较多的赛事被漏配，或者在同一天多场同级赛之间误配。

因此本轮采用以下规则：

- 源站明确 `ABANDONED` 或 meeting abandoned 的赛事，改为 `cancelled`，不再追赛果；前台显示“取消”，且不显示赛果表。
- 改期 / 改场地赛事，以结果页实际出走日期和场地修正 `RaceEvent.local_date / racecourse`，同时在 `source_refs.manual_detail_import_audit` 留下证据摘要。
- 法国 ZEturf 对漏配的 8 场使用显式 R/C 映射，不再扩大模糊扫描；显式映射只用于已经通过页面标题核对的缺口场次。
- 美国 Equibase chart PDF 后续恢复可访问后，用于补齐 HRN 未公开完整名次的四场赛果；马名仍通过既有 HRN 出走表按马号对齐，避免 PDF 抽取中的缩写或排版误读。
- `RaceEventHistoryWinner` 本轮只从已确认赛果第一名补 2026 当前年度冠军，用于避免前台“近年冠军”空白；这不代表完整历届冠军已经完成。完整历届冠军仍需后续使用地区官方历史源补齐。

## 为什么 2026 历史冠军按地区分层导入

`RaceEventHistoryWinner` 会直接影响赛事详情页的“近年冠军”展示，因此历史冠军不能只靠模糊搜索或二手页面批量填充。本轮采用按地区可信源分层的方式：

- 日本 JRA：JRA 官方年度重赏一覧历史页覆盖 `2002-2026`，可稳定按赛事名和历史别名映射，因此导入完整年度范围。
- 日本 NAR：`keiba.go.jp` ダートグレード特设页只稳定公开“過去5年の競走成績”，因此导入近 5 年，并为已完赛 2026 场次补当前年度冠军。
- 香港：HKJC 官方 `getSeasonRaces` 接口和繁中单场赛果页能稳定覆盖当前 2025/26 马季对应赛事的 `2023-2026` 结果，因此导入 4 年近年冠军，并统一繁简转换。
- 美国：TOBA 官方年度分级赛表能稳定提供 `2023-2026` 的 Grade 1/2/3 winner 字段，因此导入近 4 年；赛事名变体只处理可解释的赞助前缀、`Invitational`、`S.` 尾缀和 `formerly` 前身，不使用模糊匹配直接写库。
- 英国、法国：官方结构化历史源仍未找到；`2026-07-07` 后续先用 Sporting Life previous-winners 链和 Wikipedia winners table 作为可追溯补充源扩展近年冠军，并保留 `source_refs`，未来找到 BHA / France Galop 官方结构化源时优先覆盖。

美国 `INDIAN SUMMER S.` 在 TOBA `2023-2026` 分级表中没有可靠历史前身，本轮保留为空，后续交由人工或新增官方来源确认后再补。

## 为什么英国 / 法国近年冠军先使用可追溯补充源

`2026-07-07` 继续补齐 2026 年重赏赛事近年冠军时，英国和法国没有找到能批量、稳定映射到现有 2026 底表的官方结构化历史冠军源：

- 英国 BHA 当前官方资料主要适合定义赛程、等级和基础赛事范围；未提供可直接批量解析并映射到 2026 每个赛事 series 的 previous winners 表。
- 法国 France Galop 官方结果入口当前重定向到认证页；官网 `Historique` 页面多为叙述文章，适合人工佐证，不适合作为统一结构化导入源。

为了让赛事详情页先具备可用的“近年冠军”展示，本轮采用以下补充策略：

- 英国使用 Sporting Life 结果页里的 `last_years_winners / previousWinners` 链。该来源已经用于英国出走表 / 赛果补齐，页面可缓存、可追溯；Flat 页面部分可回溯至 `2020`，Jump 页面多数只稳定提供当前年度冠军。
- 法国使用英文 Wikipedia race page 的 winners table，并合并已确认 2026 当前冠军。该来源明确标记为 `wikipedia_winners_table`，不视为 France Galop 官方数据。
- 所有补充来源都写入 `source_refs`；后续若找到 BHA / France Galop 官方结构化历史冠军源，应优先覆盖同一 `RaceEventHistoryWinner` 模块。
- 对无可靠匹配或无结构化表的赛事保留为空，不使用模糊搜索结果强行写库。

## 为什么赛事编排必须使用独立应到清单和运行级请求预算

实际候选不能作为覆盖率分母：抓取器整体失效时，候选文件可能为空；若审计只遍历候选，反而会把“什么都没抓到”误判为没有缺口。因此 `orchestrate-race-event-data-crawls` 在真实网络请求前只根据已校验 plan 与正式 `RaceEvent` 生成不可静默缩减的应到快照，并绑定 plan SHA-256。coverage 必须逐项对照应到清单，空候选、缺失目标、计划外候选和 series 不一致都阻止后续流程。

应到清单本身仍可能因为运营计划漏项而不完整，因此第一批真实抓取增加人工复核层：review CSV 展示赛事中英文名、年份、地区、slug 与预检状态，由用户确认范围；没有确认就不启动首批网络抓取。程序负责发现结构错误和底表缺失，人工负责判断产品范围是否少了或多了赛事，两层彼此独立。

限流必须按整个 run 计算，而不是给每个 adapter 各发一份额度。否则 adapter 越多，总请求量越可能按倍数放大。所有默认网络 adapter 因此共享持久化 `request_budget.json`，失败请求也占额度，resume 继续累计；预算证据损坏时 fail closed。prepare 另行生成 run 级 combined candidate，避免人工拼文件时漏掉某个地区或模块，并让 coverage、dry-run 与 apply-check 始终绑定同一候选身份。

同时，前台模板已调整为只有存在 `history_winners` 时才展示“近年冠军”区块，避免无数据赛事出现空标题。

## 为什么马匹详情页先走受审核的产品层，而不是直接暴露术语或外部表

`2026-07-07` 马匹详情页 MVP 提案已锁定为独立 `HorseProfile` 产品层，不能把 `TermEntry` 或 `ExternalHorse` 直接当成公开详情页。原因是术语库负责翻译保护和概念识别，外部表负责来源抓取证据；公开马匹页需要审核状态、展示名快照、简介、重点新闻、血统、参赛履历、关注关系和人工覆盖痕迹，这些都属于产品层能力。

因此第一版采用以下规则：

- P0 马默认由 active `TermEntry(term_type=horse, target_zh nonempty)` 生成 `HorseProfile` 草稿，但前台不可见；后台审核补充后手动发布，状态为 `draft -> ready -> published -> hidden`。
- 管理员允许强制发布空壳页；未发布或隐藏的马匹详情页在前台返回 `404`。
- 公开 URL 只使用唯一 ID：`/horses/<id>/`，不使用 slug，避免马名、多语言和改名带来的长期兼容问题。
- 展示字段优先使用 `HorseProfile` 快照，再回退到绑定的 `TermEntry`；术语变化不应自动改写已人工确认的马匹页展示。
- 文章马匹关系使用 `ArticleHorseLink`，前台和关注流只消费 `auto/manual`，不重新扫描正文；人工移除写入 `removed` 并保护不被自动重建。
- 关注功能对匿名普通用户开放，使用 `follower_token + cookie`；首页新增“我的关注”模块，展示关注马匹及可选子孙代的相关新闻。
- 马匹与比赛关系使用 `HorseRaceRecord` 记录参加过的比赛，并从获胜记录派生重点胜利；第一版前台先展示重点胜利和关联赛事，不做完整履历表。
- 血统展示必须尽力补齐完整二代，六个文本字段齐全才算补全成功；文本足够用于展示，只有能高可信绑定时才链接 `TermEntry` / `HorseProfile`。
- 外部资料补全覆盖所有地区 P0 马，必须先 dry-run，输出补全成功/失败占比和具体失败原因；高置信唯一匹配才写草稿字段，歧义或冲突进入 `HorseProfileDataCandidate` 供后台审核。
- 日本来源优先参考 `netkeiba` / `JBIS`，并把 GitHub `new-village/KeibaScraper` 作为可信参考来源或可选依赖候选；香港、英国、法国、美国分别以 HKJC、Sporting Life / Racing Post、Geny / France Galop、Horse Racing Nation / Equibase 为第一批候选来源。

## 为什么马匹关注 token 只在 cookie 明文存在，数据库只存 hash

马匹关注第一版不引入注册账号，但匿名 `follower_token` 仍然代表当前浏览器的关注身份。如果把明文 token 写进数据库、日志或 artifact，一旦后台导出、错误日志或调试文件泄露，别人就可能复用该 token 查看或修改关注列表。

因此 `horse-profile-page-mvp` 工程审查后锁定：

- 浏览器 cookie 保存签名随机 `follower_token`。
- cookie 使用 `HttpOnly`、`SameSite=Lax`，并随 HTTPS 安全 cookie 配置启用 `Secure`。
- 数据库 `HorseFollow` 只保存不可反推的 `token_hash`，不保存明文 token。
- 关注 POST 继续使用 Django CSRF；服务端从 cookie 解析 token，前端脚本不读取 token。
- 页面 HTML、URL、日志、补全 artifact 和运行报告都不得输出明文 token。

这样可以保留匿名关注的低门槛，同时降低数据库或运营 artifact 泄露后的横向风险。

## 为什么马匹外部补全 commit 必须读取已审核 artifact

马匹资料补全会写入 `HorseProfile`、`HorseProfileDataCandidate` 和 `HorseRaceRecord`，一旦把错误血统、错误马匹匹配或错误参赛记录写入产品层，会影响公开详情页、关注流和后续人工审核。外部来源又存在限流、同名马、地区差异和字段缺失，不能让 `--commit` 一边实时抓取一边直接写库。

因此本变更要求：

- dry-run 先输出 source evidence、before/after diff、补全状态、失败原因和未补全占比。
- commit 必须读取同一批次已审核 dry-run artifact，并要求显式确认参数。
- commit 只能写入 artifact 覆盖的马匹和字段，不得重新抓取外部来源后绕过审核直接写库。
- artifact 缺少 batch id、生成时间、source 摘要、diff 或审核确认标记时，命令必须拒绝写入。
- 回滚优先使用 commit artifact 中保存的 before 值；大范围异常再使用生产数据库备份。

这个约束和现有术语合并、文章术语回填的“先生成可审 diff，再 apply 已审核 artifact”保持一致。

## 为什么赛事历史抓取必须从已审批应到清单生成输入

赛事抓取器原先可以读取工作区共享 `events.csv`。即使 coverage 最后能发现多抓或漏抓，让真实网络请求先访问计划外赛事仍会浪费请求额度并增加被来源限流的风险。因此 `orchestrate-race-event-data-crawls` 锁定以下门禁：

- run 创建时从 plan 与正式 `RaceEvent` 生成不可静默缩减的 `expected_targets.json`。
- 运营审批固定的 `review/expected_targets_approval.json`；批准状态、批准人、批准时间和应到文件 SHA-256 缺一不可。
- 网络 prepare 从已审批应到清单按地区生成 `input/events_<region>.csv`，adapter 不再以共享旧 CSV 决定范围。
- coverage 只接受显式 `approved` mapping；空模块、缺来源 URL 都视为 blocker。
- apply-check 再次对账应到 SHA-256，完整读取 gzip 备份，并要求每个实际写入范围都有完整批准元数据。

这样即使赛事抓取工具、应到清单或人工文件任一环节损坏，系统也会停止，而不是以不完整数据继续写库。

## Code review 的协作边界

- 纯技术问题，包括正确性、安全性、数据一致性、测试、性能和可维护性，由 Codex 在审查后自行判断并直接修复，不再逐条要求用户批准。
- 会改变产品能力、运营口径、用户交互、公开展示或业务规则的问题，仍需先向用户说明并确认。

## 2026-07-11 赛事抓取第六轮审查取舍

- 修复批量 importer 的部分提交风险：候选保存和正式 apply 必须整批事务化，任一后续模块失败时全部回滚。
- 修复审批后抓取输入漂移：完整 adapter 输入进入应到快照，当前 `RaceEvent` 与快照不一致时必须重新生成和审批。
- 修复混合来源批准拼接：策略 SHA 只认完整 `approved` confirmation。
- 暂不强制所有 importer apply 提供 `--expected-sha256`，保留当前单场人工修复兼容入口；规范流程仍使用 apply-check 生成的带哈希命令。
- 暂不增加请求预算文件锁或 run 并发锁，继续按当前手动、单进程分批方式运行。

## 为什么多地区新闻归属迁移上线后仍保持关闭

`2026-07-11` 生产五地区真实文章 dry-run 表明，当前实体信号可能把来源主地区文章改到另一地区，并可能一次生成三至四个关联地区。例如法国样本 `article_id=7031` 被推断为英国主地区，日本样本也出现改为中国香港主地区。该结果会改变公开地区 tab、发布窗口配额和 QQ 群匹配，属于产品归属口径问题，不能作为纯技术修复自动启用。

因此决定：

- 迁移 `stable.0023_multiregion_news_attribution` 和代码保留在线，避免重复部署与迁移风险。
- `MULTIREGION_ATTRIBUTION_ENABLED=false`、`MULTIREGION_RELATED_REGION_QUERIES_ENABLED=false`，旧行为继续生效。
- 不执行 `reprocess_multiregion_attribution_gates --commit`，不向 `NewsArticleRelatedRegion` 写入本批结果。
- 先由产品侧确认主地区优先级、关联地区最大范围和弱实体信号是否允许改变主地区，再修改规则并重新执行五地区 dry-run。
- 赛事信息编排工具不依赖这两个开关，可独立上线和开始后续应到清单验收。
## 为什么赛事页保留原始人马名并在展示时关联术语库

赛事抓取数据需要保留来源原文，便于去重、追溯、重新匹配和处理术语库后续修订；若把中文译名直接覆盖进赛事明细，术语更新后会产生历史脏数据，也会丢失原始证据。因此赛事页采用展示时批量解析：马名和骑师名精确命中 active 正式术语主原文或别名时显示 `target_zh`，冲突时优先赛事同地区，其次全局，再次其他地区；未命中时原样展示，不自动编造译名。

出马表与赛果是两个不同视图。赛果继续按完赛名次排列；出马表当前五地区按马号自然升序排列，马号缺失时回退闸位，最后才使用来源行序。地区排序映射显式保留，后续若某地区以闸位为主，只调整该地区规则，不改写已抓取数据。
## 五地区分级赛事追溯至 1984 年的范围与完成口径

历史赛事目标采用以下锁定口径：

- 覆盖日本 JRA/NAR、中国香港、英国、法国和美国在 1984 年以来全部 graded/pattern 系列，包含历史停办和降级退出系列，不包含普通赛、让赛和未胜利赛。
- 入选系列从 `max(1984, 创办年)` 保存完整系列史，包含升格前和降级后连续届次，各年使用真实等级。
- 已排期后取消创建 cancelled 年度赛事；当年未举办只记 not-held 证据，不创建虚假 `RaceEvent`。
- 可信完整赛果可派生 runners 并标记来源；年度正式赛果是冠军主事实，缺完整赛果时才使用冠军补位，历届冠军按稳定系列动态汇总。
- 字段冲突按官方当年结果、官方档案/年鉴、高可信专业库、参考来源排序；低级来源只补空，同级或高级冲突人工审核。
- 完整目标可先按批准 scope 写入，暂时不可用和身份待审持续挂账；永久不可得必须双来源证据和人工批准。
- 最终同时报告 accounted rate 和 data complete rate；闭环要求全部年度目标有明确结论，不把永久缺档伪装成数据完整。
- 历史数据不自动创建 HorseProfile、不自动音译正式术语；前台不新增系列页，赛事日历增加年份和名称搜索。
- 达标 historical publication scope 可公开年度赛事并进入分片 sitemap；资料不足、冲突和 not-held 不进入索引。

工程实现使用稳定 `RaceSeries`、年度总账 `HistoricalRaceEventTarget` 和真实年度 `RaceEvent` 三层身份。年度总账拆分客观 expectation 与处理 resolution 状态；逐年分级目录发现入选系列，再通过 lineage/timeline 补足前分级、后降级、取消和缺届。生产网络和 commit 默认关闭，所有批量行为继续绑定 artifact、请求/磁盘预算、备份、原子写入和写后核验。

# 2026-07-12 历史赛事生产执行授权

- `backfill-race-events-to-1984` 准备任务全部完成、测试通过且最终 code review 无 actionable finding 后，Codex 可自主执行生产备份、部署、历史目录抓取、详情抓取、dry-run、分批落库和写后核验，无需逐批再次取得用户确认。
- 自主执行不取消既有安全门禁：总账和批次 artifact 必须锁定 SHA，网络和写入必须受请求/cache/磁盘预算、coverage、备份、原子 scope 和写后计数约束；失败批次停止扩大并保留 gap ledger。
- 生产抓取/写入期间可临时开启 `HISTORICAL_RACE_BACKFILL_ENABLED` 与 `HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK`，但本轮结束时必须恢复关闭。历史年度赛事默认保持 draft，最终线上展示开关暂不开放。

## 2026-07-12 现有年度重复赛事的主记录选择

- 同一年、同一地区的两条记录经官方名称、日期、场地和来源证据确认属于同一届赛事时，不得为了通过系列唯一约束而创建两个伪系列。
- 合并时优先保留已经长期公开、可读且被用户使用的主 slug；后导入记录的官方字段、出马表、赛果、历届冠军、候选和别名迁入主记录，重复子记录在事务断言和备份后删除。
- 本次英国 Gold Cup 保留 `/races/2026/gold-cup/`，BHA 自动 slug 作为搜索别名留存；该规则不授权批量模糊合并，名称相似但实际不同的赛事仍须显式区分。

## 2026-07-12 以 TJCIS 年鉴作为 1998–2026 跨地区目录骨架

- 1998–2026 五地区年度 graded/group 目录先以 TJCIS 官方 International Cataloguing Standards 当年整本年鉴建立共同骨架，再由地区主办方/监管机构正式结果和 timeline 证据补充日期、结果、改名、迁场与前后等级。
- 年鉴是目录权威来源，不凌驾于当年主办方正式赛果；同级冲突继续阻断。Listed/LR 不直接进入本目标 catalog，障碍赛按独立 discipline 解析。
- 该决定不缩短历史深度。1984–1997 必须使用相同产品完成口径继续补源；旧年代未补齐前不得批准完整总账或把部分账本描述为全量完成。
## 2026-07-12 先完成并上线 1998–当前独立年代 scope

- 用户最新执行顺序明确拆为两个完整年代 scope：先补齐并审核 `1998–当前` 总账，再按该总账抓取和写入全部赛事详情，验收后打开该 scope 的正式展示；随后继续调研 `1984–1997` 完整目录。
- 该决定覆盖此前“1984–1997 未齐前不得批准任何总账或详情批次”的门禁，但不降低最终历史深度。`1998–当前` 只有在自身逐年五地区分母完整、来源冲突和身份冲突审核完成、manifest 独立批准后才能写入或公开。
- `1984–1997` 仍是同一长期目标的必做 scope，不得因 1998–当前上线而标记 OpenSpec change 全部完成或归档。
- 两个年代 scope 必须分别保存 source cache、manifest、approval、请求预算、备份和写后核验；公开开关只能在 1998–当前数据全部验收通过后开启。
## 为什么 P0 马范围扩展到五大地区重点赛事参赛马

`horse-profile-page-mvp` 第一版把 P0 马定义为 active 且有中文译名的 horse `TermEntry`，适合先批量生成后台草稿，但会漏掉没有稳定中文译名、却已经参加五大地区重点赛事并具备资料补全价值的马。P0 马资料补全专项的目标不是只补已有中文译名术语，而是为用户提供重点马匹资料入口。

因此 `complete-p0-horse-profile-data` 规划将 P0 马定义扩展为：

- 当前范围：active 且有中文译名的 horse `TermEntry`。
- 重点赛事参赛马：日本、中国香港、英国、法国、美国全部历史与未来已知 `G1/G2/G3/J-G1/J-G2/J-G3/JpnⅠ/JpnⅡ/JpnⅢ` 赛事参赛马。

重点赛事参赛马必须能追溯到结构化赛事、出赛表或赛果证据，不能仅因外部马名搜索命中就进入 P0。Listed、Open、`LOCAL_GRADE` 和其它等级暂不纳入本次 P0 扩容，后续如需扩大范围另起 change。

## 为什么暂无中文译名的马名术语仍可 active

新版 P0 范围会自然引入一批暂时没有合适中文译名的海外马。如果继续要求 horse `TermEntry.target_zh` 必填，系统会被迫在资料补全前先造一个不稳定中文译名，或者让这类马完全绕开术语体系。前者会污染翻译和前台展示，后者会削弱马名识别、翻译保护、文章关联和 P0 同步。

因此后续实现应升级术语库语义：

- `is_active=True` 表示可信实体可被识别，不再等同于“可中文替换”。
- 暂无中文译名的 horse term 可保持 active，但应有 `translation_status=pending` 或等价状态。
- 翻译、改写和发布校验命中这类马名时，必须保留原文，不得音译、意译或替换为空值。
- 只有 `target_zh` 非空或 `translation_status=translated` 的术语才参与中文替换和中文译名保留校验。

这样无译名马可以进入资料补全、ready 和人工发布流程，前台用外文原名展示并提示“中文名待补”；正式中文译名确认后，再自然升级为普通正式术语。

## 为什么马匹地区不属于身份唯一键

马匹会跨地区参加重点赛事，日本马可以参加美国、香港、英国或法国赛事。`HorseProfile.racing_region` 表达马匹自身归属，赛事地区表达一条参赛证据发生在哪里，两者不是同一个维度。因此 P0 同步不得使用“马名 + 地区”直接创建新身份，也不得因海外参赛覆盖马匹自身地区。

身份判定采用两层证据。第一层是来源命名空间内的 external horse ID，它只证明该来源中的身份；同一来源不同 ID 的同名马可以建立独立资料，不同来源的 ID 则不能仅因相同或不同就自动判断为同一匹或不同匹。第二层用于跨来源归并数据库已有马，必须完整且唯一命中“马名 + 父名 + 母名 + 出生年份”。马名和父母名通过正式术语主名、中文译名和多语言 `TermAlias` 归一，因此 `Forever Young` 与 `青春永驻` 可参与同一身份判断。

`racing_region` 不参与身份唯一性，只表达马匹自身地区；重点赛事地区只写入对应 `HorseP0Source.racing_region`。同一赛事参赛者先按马号、再按来源身份分组，不能在身份分析前按同名折叠。跨来源四元组字段不全、命中多匹或只有同名证据时，系统必须写入专用 `HorseIdentityConflict`、不写主表；该记录允许尚无 profile，保存多个候选术语/资料页、原始身份字段、来源证据和人工解决状态，并每天汇总 pending 冲突通知管理员。全量来源对账遇到仍存在但身份待处理或 URL 暂缺的输入时，不得把既有来源误撤销。暂无中文译名 horse term 的原文保护跨地区生效；同一原名命中多个 active horse term 时也必须保留原文，不能任选一个中文译名替换。

同场参赛身份必须持久化为 `HorseP0Source.participant_key`，不能在内存分组后退化回“赛事 + 马名”查询。该键表达某场赛事中的参赛者，不是马匹全局身份：优先使用规范化马号，其次使用来源身份集合摘要，只有赛事内马名唯一时才使用规范化马名。runner/result 采用马号、来源 identity、赛事内唯一马名的分阶段配对；无法唯一配对时保留独立证据并进入歧义处理。同一个 `participant_key` 最多有一条 active 重点赛事来源，身份纠正时撤销旧绑定并新增 active 绑定，以保留历史审计。

人工审核来源不属于某场赛事参赛身份，不能复用空 `race_event + participant_key` 查找。每匹马最多保留一条 active 人工 P0 来源，应用已审核 artifact 时按 `profile + source_type=manual` 独立 upsert，并由数据库条件唯一约束兜底；审核后一匹马不得撤销前一匹马的人工来源。

P0 补全队列的资料缺口优先级必须显式建模，不能直接按 `completeness_status` 字符串排序。顺序为：空资料、仅基础资料、部分血统、完整二代血统、完整资料但需刷新、完整且无需刷新；需刷新包含在役履历过期或缺同步日期、退役同步日期早于最新赛绩，以及生涯状态未知。同一缺口等级内再按人工标记、pending/conflict 候选、近 30 天公开新闻、重点赛事证据、非空外部身份和术语优先级排序。空 `horse_identity_keys` 不得算作外部匹配信号。

`participant_key` 允许随证据增强从 identity 键升级为 number 键，但升级不能新建第二条 active 来源。同步必须同时使用现有键、`race_runner`、`race_result` 和来源 identity 查找旧绑定：同一资料页原地迁移键，另一资料页则撤销旧绑定后新建。runner/result 两边都有马号且不同属于硬冲突，不能再降级按 external ID 或同名合并，必须写 `HorseIdentityConflict` 保存两边马号和原始记录。

马号硬冲突检查必须覆盖整个赛事 participant 集合，而不只覆盖 runner-result 配对。同一来源 identity 关联两条 runner、两条 result 或混合记录时，只要出现多个非空马号，就汇总成一条 pending `HorseIdentityConflict`，保存全部 runner/result ID 与马号，并阻止该冲突组写入 active P0 来源。

马号冲突不能仅凭 `resolved_profile` 恢复写入，还必须填写 `resolved_horse_number`，且该值必须属于 evidence 中的候选马号。共享任一来源身份键的参赛记录必须先形成完整连通组，再生成一条包含全部成员和马号的冲突，不能按身份键顺序覆盖证据。同步只采用最终马号对应的 runner/result；只有所选成员自身或赛事具备来源 URL 时才允许 resolved。若所选成员无法在本轮证据中定位、URL 后续消失或数据绕过后台校验，下一次同步统一恢复为 pending、清空无效解决选择并记录失败原因，使其继续进入管理员通知。冲突 evidence 保存所有成员和 URL，即使全部无 URL也必须落库；URL 等可补充证据不参与 fingerprint，避免证据完善后复制一条新冲突。

## 为什么 P0 commit 必须逐行逐模块审核

artifact 顶层“已审核”只能表示整份文件进入 commit 阶段，不能替代每匹马、每个模块的人工结论。正式写入必须同时满足：有效审核人、行级 `reviewed=true`、模块级 `approved`、最低置信度、无冲突/失败标记和来源 URL 规则。基础资料、血统、赛事履历、主胜鞍四个必需模块都留下 applied 审计后，系统才允许标记 `complete_profile_full`。

旧 `HorseRaceRecord` 在迁移时优先从 `raw_payload`、其次从 `source_refs` 读取 external race/result ID，并为唯一记录回填同一套幂等键；两处都没有外部身份时才使用自然键，已有重复组保持空键等待人工处理。来源命名空间从 `record.source_name` 或证据中的 `source/source_name/provider/adapter` 推导，用于身份键时统一去空格和 `casefold()`；external ID 统一字符串化并去首尾空格，避免来源大小写或证据空格变化生成不同键。运行期接管空键旧记录时也必须先扫描 `raw_payload/source_refs` external identity：唯一命中时接管并补齐来源名，多条命中时在 importer 与后台编辑路径都停止写入并报告歧义，完全无外部身份命中时才退回比赛名、日期、马场和 URL 等自然字段，避免事实字段修正后生成第三条重复记录。新增、修正、未变化必须分别统计，修正必须保留 before/after。P0 普通同步采用追加式更新，不执行撤销；只有操作者显式选择全地区完整对账时，本轮不再成立的受管来源才标记 `revoked`，并保留撤销时间和原因，不删除历史来源。

所有赛绩写入口必须复用共享的 `stable.services.horse_race_records.upsert_race_record()`，包括 P0 artifact、后台人工候选和后续批量导入；不得另行直接 `create()`。共享服务统一校验比赛名、来源名和来源 URL，生成幂等键，接管唯一旧记录，并在多个旧记录同时命中时停止写入。这样“人工审核”和“批量补全”不会因为走不同代码路径而生成重复赛绩。

后台手工新增和编辑也属于上述统一入口。编辑已有赛绩时需要指定原记录，按编辑后自然键重新生成幂等键；若新键或旧自然键已经属于另一记录，应拒绝保存而不是合并或覆盖。当前不额外实现并发请求争用时的自动重查，数据库唯一约束仍作为最终防重复边界。

人工编辑既有 importer 赛绩不得覆盖 `source_refs/raw_payload`；这些字段保存原始来源证据，不是表单当前值的镜像。手工修改的 before/after 应进入 `OperationLog`，只有从后台新建的赛绩才初始化 `entry_method=manual_console`。

若既有赛绩的 `raw_payload/source_refs` 含 external race/result ID，人工编辑普通事实字段时幂等键必须继续使用该 external ID 和原 source namespace，不得退化为比赛名/日期自然键。只有显式更正外部身份的专门操作才可改变外部身份键。

在役马履历新鲜度只使用一个公共截止日期函数，读取 `HORSE_PROFILE_ACTIVE_RECORD_FRESHNESS_DAYS`。完整度判断、后台待刷新筛选、后续队列和定时任务不得各自硬编码“早于今天”。

## 2026-07-13 法国新鲜度与归属能力采用先部署、后资格灰度

- 允许先将 `badc10e0` 和 `stable.0029` 部署到生产，但归属模式保持 `off`，相关地区查询、翻译自动重试和失败邮件保持关闭。
- 归属能力必须先完成至少 250 篇有效、五地区覆盖且双人审核裁决的 gold set，并通过既定准确率、扩散率、锁定覆盖与性能门槛；不得以代码已部署替代生产资格。
- 失败邮件固定发往 `754652181@qq.com`，但只有在生产 SMTP 参数配置完成并通过测试发送后才允许开启；无 SMTP 时保持关闭并依赖现有后台/运行日志感知失败。
- 本次验收以 HTTP 运行态为准。HTTPS server 块仍未启用，证书接入继续作为独立运维事项，不与本 change 的代码部署混为一谈。
## 2026-07-13 历史第一批允许完整子 scope 独立写入

- 第一批 45 场不要求为了等待某一地区来源而冻结其他已完整目标；满足当前 target/inventory SHA、审核直链、source cache identity、完整 runners/results 和 production dry-run 的 27 场可作为完整子 scope 正式写入。
- 法国 9 场详情缺口、英国 2000 年 3 场日期缺口和美国 2000/2012 年 6 场日期缺口必须继续留在总账，分别保持 `ready` 或 `pending`，不得用空候选、仅冠军信息或推测日期标记完成。
- 本次写入只改变结构化数据状态，不构成 publication scope 批准。36 个已建赛事继续保持 draft，两个历史开关保持关闭；只有补齐五地区样本并完成前台、搜索、历届冠军、可见性和 sitemap 验收后，才讨论扩大公开范围。

## 2026-07-13 IrishRacing 作为英法历史详情备用源

- 当 Racing Post / France Galop / PMU 等主源只提供沿革证据或当前受反爬限制时，允许 IrishRacing 作为较低权威的正式详情备用源。主源链接与交叉核验证据仍保留，不将备用源提升为地区第一权威。
- IrishRacing 结果页只证明 actual runners 与 results，不冒充 declared runners/racecard。马号和闸位分字段保存，出马表按马号排序；并列官方名次保存在 `official_finish_position`。
- 工程上拆为 `uk_irishracing` 和 `france_irishracing`，即使 host 相同也不允许跨地区候选或 artifact apply。HTTP 200 但显示 `Information Not Available` 的页面必须视为抓取失败。

## 2026-07-13 近年日美来源与字段口径

- 2025 美国平地分级赛由 TOBA 年表定位，直接结果使用可缓存的 Equibase Yearbook 单场页；旧 `tvg` 静态整日 PDF 规则只用于已验证旧年份。
- TJCIS 裸距离按地区显式补单位：日本、香港、法国为米，美国平地为 furlong；美国障碍和英国保存来源中的 mile/furlong/yard 组合。
- Equibase 退赛程序号 `SCR` 内部保存为稳定 `SCR-n`；官方并列名次写入 `official_finish_position`，唯一 `finish_position` 仅作稳定存储顺序。
- 年度权威表赛事名唯一且有工程期移师证据时，允许以当年实际场地定位结果，不因此拆分稳定赛事系列。

## 为什么迁移前进后禁止部署旧应用底座

- 历史赛事能力可以在独立分支长期迭代，但每次生产构建前必须先合入最新 `origin/main`，检查当前生产已应用迁移及所有新增非空字段的创建路径，并运行历史链路与新闻主链路组合回归。
- 数据库已应用 `stable.0027–0029` 后，缺少对应模型/服务写入逻辑的旧镜像即使 healthz 正常，也可能让新文章在数据库约束处失败；因此 healthz 不能替代真实新增 smoke 或近期任务错误日志检查。
- 生产发生 schema/application 不兼容时，优先停止新的 one-off 写入、构建和重启，由单一生产协调线程选择短时回滚或兼容镜像替换。历史批次不得抢占新闻主链路恢复。
- 生产兼容镜像已由单一协调线程完成切换；历史回填线程后续只能在既有镜像上执行已批准的数据操作，不得自行重建、retag 或重启生产服务。任何后续代码部署必须先合入最新 main 并重新交付镜像 ID。
- 历史详情来源必须在整个批次内一对一绑定目标；同一详情 URL 即使仅 fragment 不同也视为同一来源页面，发现复用必须阻断，不得用同日同场相似赛事填充。
- 生产当前运行的组合镜像在历史源码完整进入 Git 前属于临时可运行状态；法港英 150 场日期 apply 完成后暂停详情写入，优先提交源码、推送分支、合入最新 main，并从可复现 Git tree 重建 AMD64 镜像。

## 2026-07-13 生产镜像必须同时绑定最新主线和构建上下文

- 服务器 Git HEAD 最新不代表运行容器最新。每次生产切换必须同时核对容器 image ID、镜像内最新迁移、Django settings 和关键管理命令；任一项不一致即停止切换。
- 多个 worktree 并行开发时，后部署任务必须先合入最新 `origin/main` 并跑组合回归。禁止使用旧分支构建后直接覆盖共享 `umanewsbot:prod`，即使该镜像只想修复另一个模块。
- 暂未全部提交的生产镜像必须至少记录内容 commit、构建上下文树 SHA、完整 image ID 和回滚 tag，并尽快将真实生产源码提交推送。它只能作为短期过渡，不能成为长期部署方式。
- 切换共享 worker 前先暂停 beat，等待 active/reserved/one-off 清空；切换完成后立即恢复 beat，并验证自然抓取、数据库非空约束、五地区页面和错误日志。

## 2026-07-14 新闻实体采用文章级统一仲裁与显式重处理

- 同一篇文章的翻译术语、马名标签、发布校验和自动马匹关联必须消费同一份带跨度、实体类型、证据与冲突结果的文章级解析，禁止各链路独立扫描全术语库后得到互相矛盾的实体。
- 英文人物全名及篇内唯一姓氏回指优先于内部马名候选；普通词和高歧义单词型马名只有在强马名语境中才接受。日文连续完整未知马名先整体占位，接受术语只在占位前应用，恢复后不得再次全库扫描而把父马、冠名或普通短词嵌入完整名。
- 历史误识别只通过显式文章 ID 的管理命令修复，默认 dry-run、逐篇事务和操作日志；提交时可清理本轮机器 provenance 与明确目标旧 `AUTO/CANDIDATE`，但必须保留人工标签、`MANUAL/REMOVED` 关联、公开状态/时间及 QQ 幂等。自然流入规则修复不授权全库批量回填。
## 为什么历史赛事基础字段校正必须独立于详情候选

年度清单和日期来源可能只提供裸数字或地区特有的距离写法，直接物化后不能假设数值单位相同。法国、香港的距离证据通常以米为单位，英国则可能使用 mile、furlong 和 yard；任何统一猜测都会把正确数字写成错误语义。

因此基础字段校正采用独立、哈希锁定的 JSONL artifact：每个目标绑定当前 target/inventory 身份和逐来源快照，dry-run 展示 before/after，apply 保护人工锁并整批原子写入。字段变化后 target SHA 必须改变，已有详情候选必须重新导出、重新打包和重新 dry-run，禁止直接复用旧审批结果。场地、surface、等级、日期和名称的权威修正也复用同一门禁，不允许生产 shell 手改。

## 为什么英制距离必须接受来源紧凑写法但保留原文

英国来源会把 mile、furlong、yard 连写为 `2m4f`，也会把四又二分之一 furlong 写为 `41/2f`，组合后出现 `2m41/2f`。这些是带明确单位的来源格式，不应因为缺少空格而进入距离缺口，也不能先改写为裸小数再猜测单位。

正式解析先保留原始 `distance_text`，再把紧凑 token 和粘连分数拆成结构化 mile/furlong/yard 组件并按固定公式派生米值。香港赛季目标若届次年度与实际比赛自然年不同，必须显式保存 `actual_year` 和跨年原因；不得仅靠日期或 season label 隐式推断。

## 为什么生产备份必须验证恢复文件而不能相信脚本成功文案

低成本 Compose 的 PostgreSQL 主机名 `db` 只在容器网络内可解析，宿主机直接运行备份脚本可能在 `pg_dump` 阶段失败；脚本后续依赖或错误处理不完整时，仍可能打印看似成功的备份路径。部署门禁因此以命令退出码、文件非空、`gzip -t` 和 SHA-256 四项为准，缺一项都不能继续 retag 或重建生产容器。

在备份脚本修复前，允许使用数据库容器内 `pg_dump`、宿主机只负责压缩落盘的回退路径。该路径仍必须生成独立的 `pre-<change>-<timestamp>.sql.gz`，完成完整性校验并记录 SHA-256；失败文件不得覆盖或冒充有效恢复点。
