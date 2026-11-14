# P01 上线、回滚与交接

本轮已进入实现和隔离验证。真实调用、部署和生产验收均NOT_RUN。人工确认唯一依据为[根 AGENTS.md](../../../AGENTS.md)，本文件只描述技术检查与交付内容。

## 1 工作树与恢复交接

- 本线程：`/Users/mentianlu/.codex/worktrees/9c8c/umanews`，`codex/p01-news-quality-design-20261027`。
- 固定代码基线：`e4df6bdaf85318eb9588489807e4b9a40bb01665`，原业务交接worktree/分支保留且不修改。
- 实现范围覆盖 `server/stable/` 新闻服务/页面/测试、settings、迁移0083–0085、独立worker Compose和Nginx曝光日志。原卡及原百分比保持不变。
- 原8线、定时调度、生产采集仍暂停；新方案不恢复旧任务。P02/P03/P04其他工作树若后续并行，只通过固定提交和schema合同集成，不竞争生产发布面。
- 已知B285/B286：原direct-PG停止上限与修复资格未关闭；后续执行真实PG测试前只读审查该修复及停止/清理证明，使用新隔离环境。不能用本次文档检查当其复验，也不能让该执行环境缺口阻止纯设计。

## 2 发布前必须取得的实际证据

1. 最新主线差异/迁移图与本候选无冲突；源码固定SHA，独立代码review和受影响测试通过，镜像与结果可追溯。旧候选结果不自动继承。
2. 来源清单含五地区当前启用来源、许可/用途、频率、时间证据、模板fixture及失败路径；存在缺口就报告范围，不以扩抓补齐本包。
3. 20篇小样例模型评估、100篇固定质量集/保留集、完整链路回归；模型ID/prompt/schema/价目/日月上限填实。无模型可用性或费用证据不能开启自动链。
4. 隔离PostgreSQL证明并发、迁移、旧worker隔离和恢复；公网形状环境验证实际effective全文、首页/缓存/分页/更正链接。
5. 验证源时间到首次公开可见的延迟；不把内部处理1小时替换端到端。五地区来源频率不支持目标时明确阻断时效项。
6. 发布现场再核运行镜像/schema、DB/Redis/active/reserved队列、磁盘内存、备份及现有release coordinator/资源锁。方案未进行生产检查，旧快照不作现态。

## 3 精确交付包内容

后续由release coordinator填写实际值：PR/head SHA和镜像digest、迁移列表与兼容矩阵、来源范围/输入创建边界、policy及模型版本、日/月预算、worker/Beat/Nginx缓存配置差异、服务重建/重启清单、生产数据动作（旧公开索引backfill、新discovery/run、处理/公开版本及条目）、功能开关、公开探针和失败恢复步骤。按根AGENTS办理，不把本次产品访谈或方案评审当生产启用授权。

预计新增八表、NewsArticle nullable路由字段及两张头条表nullable receipt FK，迁移只有schema。另有首批必需的旧公开条目索引backfill，仅复制ID/原发布时间/地区等到NewsPublicEntry，不修改新闻正文或重新发布；须在精确交付包列明行数、分批/指纹、幂等验证与回退面，不能与后续N07/N08正文修复混淆。生产若大表ADD FK/索引有锁风险，拆成加nullable字段、建索引/约束（必要时并发索引+NOT VALID后validate），在生产形状副本测量锁等待；迁移图/编号由候选确定。旧应用读取旧字段应兼容新schema，但旧writer不认识P01，所以不能直接回滚旧程序继续工作。

预期配置三态：`NEWS_QUALITY_MODE=off/shadow/enforce`、冻结来源/policy、模型与额度、P01 queue并发/调度周期。默认off和预算0；mode为off仍保留active_news_run路由拦截，禁止把P01稿退回旧自动化。shadow对缓存/候选生成结果，不公开、不外发；是否调用真实模型取决于单独实际评估/发布包范围。

## 4 技术上线顺序

1. 获取符合根规则的release锁，记录固定SHA/资源域/存活；核对生产旧worker和队列，不消费或清理无关旧race_live消息。
2. 对新闻写入短时暂停认领并drain相关旧任务，保留broker消息；取得数据库备份SHA、TOC与隔离恢复证明、配置快照及当前镜像证据。
3. 应用增量schema并部署包含P01路由拦截的新web/worker/Beat；开关off。旧版可能写新闻的worker全部退出，不能新旧混跑。核对schema/镜像/队列和原公开站正常；新写路径即使off也为legacy公开动作维护entry，旧writer无索引写能力则不得混跑。随后分页幂等backfill旧公开索引，提交时再次锁article核对公开状态/时间与版本，保护并发新发布；集合一致检查通过后才切snapshot读取。
4. 固定样本shadow验证整链与纯网页writer副作用隔离。预算与模型/来源策略填实后才可按包切enforce；记录启用时刻及新文章纳入边界。
5. P01 run只接新边界后文章，旧队列对已绑定文章转路由，不为全部旧稿创建新run。单篇失败不阻塞其他稿，budget/供应商故障不自动切回旧发布。
6. 实测首页/详情receipt版本（legacy仍effective字段）、更新与缓存失效、费用预约、无QQ/mail调用；建立自然周起点。新管线完整运行并非已经通过周验收。

## 5 停止与恢复

技术停止条件：错误实体/关键事实公开、清洗误删、旧worker越权提交、双主稿/更正被吞、外发副作用、预算超限或unknown费用失控、数据库/队列资源越界。停止新认领与新发布，保留待处理稿及所有证据，不删除failed/unknown账。

恢复优先使用当前候选的off模式：停scheduler、提高generation使旧claim失效、drain/终止P01 worker，确认零active后核receipt/公开差异；网页保留已验证内容，受影响P01稿按精确receipt ID撤回；不把新稿内容回写到旧文章。单独历史修复包若需恢复则按其已核前后版本执行，禁止整库恢复覆盖无关业务。

回滚代码只用事先经过隔离兼容测试且仍理解active_news_run拦截的镜像。若没有这种镜像，保持当前关闭态并前向修复；不运行当前运维策略已禁用的通用rollback脚本，不降迁移/drop审计表。当前 `docs/rollback_guide.md` 的禁止普通代码回滚事实需在发布现场重新核对，不能假定已有合法回滚目标。

已公开字段的恢复是独立数据恢复动作，必须精确绑定after_sha与版本；修复后人工变化阻断覆盖。历史修复包复用该原则，不重发、不刷新初次公开时间；完整库备份仅作为灾难恢复面，验证只在隔离实例进行。

## 6 真实周验收与后续交付

从完整五地区策略启用时刻连续168小时；冻结版本/来源/预算，独立记录candidate/qualified/published/feed seats/成功响应曝光机会/重大事件清单。未抓取、未选中、质量阻断、预算阻断、无供给分别对账；不能以候选数代替重大事件分母。

相关policy/模型版本或来源范围发生变化时保留旧窗口，不把不可比片段拼成通过；受影响指标重新起算。目标达成率与例外如实报告，不暗加100%时效成功率；固定质量、分母完整和曝光账等硬检查须通过，168小时结束不会自动通过。完整新增链路候选可先交付，N09保持观察中；历史N07/N08在其后独立形成manifest与备份恢复包。

## 7 本轮评审与验证记录

- reviewer：`/root/p01_plan_reviewer`，按plan-eng-review只读，前后指纹一致，后续同一上下文复审。
- 首轮结论：REVISE，5 high + 2 medium；没有新增需用户决定的产品取舍。
- R1 修订身份：补source/target/publication三种版本、人工精确目标重审、同URL新稿receipt/独立链接及全部公开入口，T26–T28。
- R2 事件键：补三类规范元组、跨源映射、source-scoped主体、uncertain人工绑定、候选溢出，T29。
- R3 预算：准入与事实账分开，真实超额/跨期/迟到usage原子结算，T30。
- R4 发现分母：解析前discovery与整listing缺口，T31。
- R5 首页：重大优先24小时初值、分地区取池、overflow诊断，T32。
- R6 分页：不可变public entry、提交水位、首部/尾部互斥和响应generation，T28/T33。
- R7 时效：区分产品目标/真实达成率/硬检查，不暗增时效阈值，T34。
- 文档检查：修正后workflow contract PASS、4项契约测试PASS、五文件相对链接/行尾空白与P01–P10、T01–T34映射PASS；git diff --check通过。
- 第二轮结论：原reviewer对R1–R7全部关闭，未发现尚未修正的必要问题或新增直接P0/P1；VERDICT: APPROVED。前后只读指纹一致 `514d7617af8bf8ad0b997e96d215406ffa7a52fb9570253cfc278dce2cad88fa`（记录评审结论前的五文件状态）。T26–T34仍是待执行测试设计，不是应用测试已通过。
- 应用测试/CI/真实模型/生产：NOT_RUN（本轮仅方案）。
- 用户追加决定：“单独发一篇新稿件，不修改旧文章”。据此所有日常重大更新/需公开的实质更正都独立receipt+entry+URL，新稿引用旧稿，旧稿内容与原公开时间不变；取消current_receipt原位替换和旧稿URL切换。存储仍保留来源唯一锚点，不要求用户选择数据库模型。
- 追加修正：source重抓在upsert前转discovery/run，prompt消费新快照；按独立稿件撤回；重复实质更正幂等。同步T27/T28/T35和任务。第三轮原reviewer认为独立稿件/重抓/撤回/分页合同已闭合，但发现新稿继承anchor旧关联的直接high问题（指纹 `3c79412d8bee9841357f48895fd9136ee80e83ce1b5711ad3eb0eb398d8cc68d`）。已补每份receipt独立occurrence/关系证据、当前可见性与T36，第四轮定向复审已关闭该high，最终VERDICT: APPROVED，无新增actionable finding。

### 方案阶段结论（2026-10-27）

原reviewer共4轮：首轮7项（5 high/2 medium）经第二轮关闭；用户追加“独立新稿，不修改旧文章”后，第三轮发现1项直接关联high，经第四轮关闭。当前没有未关闭finding或待用户决定的产品/架构问题。独立稿件使用完整不可变公开记录，旧稿不原位替换，关联证据也按稿件隔离。

第四轮前后只读指纹一致 `27eceec5d49a276afa39e5d6be3e587d51afb92dff010f3d21b189fff72e6b13`（写入最终状态前的方案版本）；最终状态回写只登记结论，不改变被审技术合同。

最终文档检查：workflow contract PASS、4项契约测试PASS、五文档链接/格式与T01–T36映射PASS、git diff --check通过。36组是实施阶段待执行的测试设计；应用测试、CI、真实模型/生产/168小时观察仍NOT_RUN。下一阶段为依本方案进行测试与实现，当前请求到设计和独立方案评审为止。

## 8 实现候选与本地验证（2026-10-27）

实现基线为方案提交 `c71d99ce4788c151d66f4770208b2b02c71fcc89`。20个专项模块在固定源码、Linux离线容器、独立PG16上执行，不连接生产DB/Redis/供应商。各轮RED/GREEN原始日志保存在本线程runtime的完整SHA目录。`7d0e0e8b` 的3项RED在 `e9afdbbc` 的21项测试中全部转GREEN；`a3f4556b` 证明不相关race span会进入旧关联查询，随后收紧为精确block/start/end交集，109项组合复验通过。

目前能力包括：冻结输入与policy/人工目标、5阶段固定模型任务、日/月预约和unknown对账、原文清洗/全文/占位专名/事实审校、证据事件身份和新增事实判断、只发布独立不可变稿件、各公开入口的精确关系、5区快照/签名水位分页、匿名实际响应曝光、后台人工恢复、只读质量报告、固定旧索引和历史修复工具。所有生产开关默认关闭。

本地已盘点7份DOM fixture，`local-input-inventory.json` 明确真实来源样本为0；20篇真实评估、100/25 gold/holdout、可用模型与费率、来源许可/真实频率及完整168小时验收仍缺证据。默认policy样例不包含模型、来源和预算，不能用于启用。新增命令只生成离线评估包，不执行付费请求。

独立代码review首轮 REVISE 9项，补测提交 `2143f73d` 在隔离PG复现10个失败与9个错误（含子案例）；修复后46项相关回归通过。问题涉及人工终态 fencing、旧writer锁范围、异常模型返回隔离、额度配置、认领stage绑定、更正幂等、reason长度、off/null策略和身份请求schema，均在原reviewer上下文关闭。最终代码复审覆盖 `517f79cc`→`3f21f41fa24943249511939e6d63f21b6727b4df` 的20个变更文件及调用链，结论 APPROVED，无新增可操作finding；只读前后指纹相同 `b706954d4f8aaaf6c212fdc5b1c7c5c7d3e1a269589783a012a4653a7761221c`。

`46ab97a7` 固定源码上的273项隔离PG回归通过（包含20个P01模块、旧头条、历史日历、managed-readonly业务和部署生命周期）；`3f21f41f` 的4项迁移/恢复身份测试通过。历史迁移测试结束时恢复当次入口leaf，不再遗留旧schema影响后续用例；生产迁移修复的SHA/身份约束没有放宽。

测试环境为本地 Colima 中原生 ARM64 Linux 镜像 `sha256:5fa59696f087c4ba2fdc0fde4e6c95d484e660334332a0256ba739a911766d42`，测试容器 network none、独立PG16。初次 AMD64 模拟镜像不能满足PG进程身份核验，已停止该诊断运行并保留原始结果，不记为通过；未修改安全核验来适配模拟进程。Compose离线解析证明四类进程默认off、共享policy只读挂载。全量测试在固定 `3f21f41f` 上执行，结果在下文登记；不声明PR已可合并或生产可启用。


### 实施收尾与全量核验结果（扩围前历史）

本节保留扩围前的结果与当时授权状态；用户随后批准验证扩围，最新结论见第10节。

- 后续只读复审：`3f21f41f`→`152bd19a`（F02 fixture和5份文档）APPROVED，指纹 `04de2fdd156c3bc45dfadc58c62957d3989316915e1b81e677e14192acc78741`；`152bd19a`→`69bfc4e1f3996c5996879610e663978529ab966d`（采集兼容和测试夹具）APPROVED，指纹 `1bdaa3e9aff21522b8ec6bd51a534f1fbee0915d41c45c03ca7bc7be06687318`。前后均clean，无新增可操作finding。
- 全量固定 `3f21f41f`：53批，7,662个唯一ID，无重复或遗漏执行。原生结果7,644成功、5失败、3错误、10跳过。52批具有完成报告；batch-012的198项原生断言通过，但PG日志超过既有512KiB总限额，收尾失败，只有部分证据。主执行器中断后，仅继续原计划中从未运行的批次，没有重写既有报告。
- 8个失败/错误用例：F02新插入行落在观察截止附近；旧采集URL-only stub的错误被来源ID缺失覆盖；工具链AST fixture缺新依赖/参数、可信依赖闭包遗漏。分别修正测试时间、URL回退和测试夹具；组合测试又暴露失效SHA案例污染进程环境，已加测试环境恢复。没有修改导出上限、生产执行器、PG身份/收尾约束或安全门禁。
- 修复后独立证据：`6e540964` 的原F02 batch-003共12项PASS；`0602f1787e2faa9e1f68a34be76b697c8f9b82dd` 的全部20个P01模块124项+旧采集13项，共137项PG PASS；`69bfc4e1` 的两工具链模块31项PASS。`0602f178` 的 `makemigrations --check --dry-run --noinput` 返回 No changes detected；全量最后49项发布恢复合同PASS。
- 正式 `verify_test_plan.py` 退出1：`missing/duplicate/unexpected batch`（batch-012缺完成回执）。10项真实缓存/root/镜像用例仍跳过，catalog的2026-10-16复核期限已过。后续定向通过不能替换原全量回执，故正式状态仍 **BLOCKED**。未提高日志限额、缩减断言、自动延期skip或把合成样本替作真实缓存。
- 原始日志及机器摘要位于本机 `/Users/mentianlu/.codex/runtime/p01-news-quality/`，摘要为 `final-evidence-summary.json`；各原生/定向结果分别保留固定SHA和镜像身份。P01测试容器已全部退出，其他线程容器未操作。工作流契约及其4项测试、相对链接和 `git diff --check` 通过。
- 本轮源码和代码复审完成，完整交付验证尚未通过；仓库级证据管线/真实样本补证是否扩围已询问用户，未获得选择前保持现有边界。未push共享主线、未合并/部署、未调用真实模型、未生产回填/启用或外发消息。

## 9 配置与停止操作说明

- 使用 `docker-compose.news-quality.yml` 叠加现有生产Compose；新worker仅在 `news-quality` profile启用，固定候选镜像通过 `UMANEWS_NEWS_QUALITY_IMAGE` 传入；队列为 `news_quality`，并发2。
- `NEWS_QUALITY_POLICY_DIR` 是宿主只读目录，容器中以 `/run/news-quality` 挂载。全部web/worker/Beat使用相同 `NEWS_QUALITY_POLICY_FILE` 和 `NEWS_QUALITY_POLICY_FILE_SHA256`；文件超限、SHA不符或非对象导致启动失败。API凭据只注入环境，不进入policy/仓库。
- `NEWS_QUALITY_MODE=off` 阻断新认领/公开；`NEWS_QUALITY_DISPATCH_ENABLED=false` 停止扫描投递。旧writer对已绑定P01稿仍拦截。`NEWS_QUALITY_FEED_ENABLED` 可保持true以继续显示已公开回执并每5分钟刷新快照，不能用关闭feed代替逐稿撤回。
- 索引切换分离：先 `NEWS_QUALITY_INDEX_ENABLED=true` 保证旧writer维护条目，feed仍false。`backfill_news_public_index --max-id N --after-id M --limit 100 --output manifest.json` 只准备固定页；apply带manifest及原文件SHA。每页最多500篇，整页锁定并核原文/公开版本，漂移整页拒绝；重复应用不重复建索引。首次全量集合核对后再开feed。本轮未对生产运行该命令。
- `prepare_news_evaluation` 固定本地manifest/根目录/SHA，校验真实来源与人工标注；输出始终NOT_RUN。缺模型/费率或真实样本时package_ready=false。
- `report_news_quality` 输入事件JSON、应用曝光JSONL、访问对账JSON、窗口证据JSON分别绑定SHA，最多32MiB；窗口至多31天。缺独立清单/窗口/访问证据时保持unknown或未通过，管理页7日即时统计不等于自然周验收。
- 应用在 `LOG_DIR/news-exposure.jsonl` 写响应ID、generation和实际条目；Nginx在 `news-exposure-access.jsonl` 写匿名响应ID/状态/时间，保留原combined access log。发布包必须含两端日志持久化、轮转和至少覆盖观察窗口的保留期，核实际磁盘边界。应用handler支持外部轮转；Nginx轮转须重新打开日志。
- 访问对账输入不是原始Nginx JSONL：需从固定完整窗口文件筛选成功200响应，提取唯一response_ids，记录start/end/provenance及complete。先证明日志无丢失/轮转缺口再设complete；重复响应ID、集合不一致均失败。不能仅凭程序生成日志而声称浏览器已收到，也不把snapshot席位当曝光。应另保留原始日志SHA及汇总过程。
- 迁移0083建表/字段，0084保护公开回执及已发表锚点，0085保护已结算任务/已发表run。仅PG具有DB级保护；生产不可替换为SQLite。停用后保留表和receipt，不降迁移、不回滚不理解P01的旧writer镜像。

## 10 扩围后的完整验证

用户已批准修复PG日志证据超限并补齐10项真实执行条件。候选 `e16a0cb2` 的扩围代码通过同一独立reviewer复审，C1–C9全部关闭；固定SHA完整串行回归7681项、57批全部通过，0失败、0错误、0skip，正式计划及owned生命周期核验通过。59个自有容器和临时历史镜像均完成清理并只读复查。完整结果及与真实业务验收的边界见[扩围验收记录](https://github.com/thumentianlu1993-blip/Umanewsbot/blob/e4d67caa087ff95b171700daeb63ae0ad1831012/docs/changes/p01-validation-closure-20261027/validation.md)。第8节原始失败保留，不改写成通过。本轮不合并、不部署。

## 11 真实来源诊断（2026-10-27）

用户要求先验证来源，并确认已有所有来源授权。生产只读盘点15条启用配置、9个提供方；30份真实缓存重放P01正文检查，20份结构通过，8份缺HTML、2份无正文边界。日本候选已接通HTML保存，本轮另取两页真实页面均200且离线重放通过，生产旧缓存结果不改。另确认国际来源时间证据、Sporting Life发现链和TDN地区归类缺口。见[来源验证报告](https://github.com/thumentianlu1993-blip/Umanewsbot/blob/e4d67caa087ff95b171700daeb63ae0ad1831012/docs/changes/p01-source-verification-20261027/report.md)。这轮完成诊断，尚未修复发现的问题，未形成gold或执行真实模型/生产发布。前述离线全仓通过记录仍有效，不能替代本轮发现的真实输入问题。


## 12 来源问题修复与复验（2026-10-28）

用户要求先修复来源验证发现的问题并再次验证。最终业务代码 `741334cc` 修复SCMP正文、国际来源时间、Sporting Life发现和TDN逐稿地区证据；原off/shadow、仅新稿应用和人工锁保护经反例验证保留。独立review三轮后R1–R3全部关闭。22份国际缓存正文/时间、14条Sporting Life候选及两页日本缓存重放通过；原8份日本缺HTML缓存不回填或伪造。

固定SHA完整本地离线回归7696项、57批全通过，无失败/错误/跳过；正式集合核验、owned生命周期及59个自有容器/历史合同镜像清理复查通过。旧67c03164被替代运行单独保留，不计入该结果。详细证据与限制见[来源修复报告](https://github.com/thumentianlu1993-blip/Umanewsbot/blob/e4d67caa087ff95b171700daeb63ae0ad1831012/docs/changes/p01-source-verification-20261027/repair.md)。未合并、部署、生产修复或调用模型；模型/gold/真实覆盖与168小时验收保持未执行。


## 13 真实模型评估停止记录（2026-10-28）

用户批准后实际发起56次请求，55次有usage；18篇完成且实体校验均阻断，第19篇unknown，第20篇未开始，已按包停止，未进入翻译/事实审校。已知usage费用约0.703694美元，未明预约0.03872088美元。字段形状、实体跨度、调用参数差异及对账要求见[报告](https://github.com/thumentianlu1993-blip/Umanewsbot/blob/e4d67caa087ff95b171700daeb63ae0ad1831012/docs/changes/p01-model-evaluation-20261028/report.md)。真实模型验收未通过，不配置正式预算，不启用生产。
