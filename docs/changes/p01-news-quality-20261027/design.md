# P01 开发设计

状态：用户已明确独立新稿、旧文章不修改；原 reviewer 第四轮最终 APPROVED，全部已发现方案问题关闭。基线及产品决策见 [spec](spec.md)，授权统一引用[根 AGENTS.md](../../../AGENTS.md)。以下新接口/模型均是拟议实现，不是当前已具备能力。

## 1 实际代码基线与复用边界

| 当前入口 | 已核对的内容 | 本轮增量 |
|---|---|---|
| `services/article_content.py:clean_international_article_body` | 来源清洗、稳定区块与去留原因 | 覆盖五地区模板、完整性判定及模板变化异常 |
| `content_review_decisions.py:review_candidate`、`content_review_shadow.py:shadow_review_draft` | 纯候选校验与有界拷贝；明确无 provider/持久化/发布权限 | 复用纯函数；增加新闻业务 caller，不把 shadow/profile 当生产授权 |
| `terms.py:resolve_article_entities_for_article`、`translation.py` | occurrence、确定性映射、占位保护及现有翻译 provider | 强模型独立发现遗漏实体，验证后输入现有保护层 |
| `article_entity_binding.py:plan_article_entity_bindings` | 纯绑定规划器 | 只复用身份证据规则，不顺带写全站关系 |
| `numeric_surface_audit.py`、`validation.py` | 数值表面诊断，`fact_verdict=not_assessed` | 不当完整事实检查；补语义审校与有界修复 |
| `translation_recovery.py`、`TranslationRun` | 认领、checkpoint、过期恢复、错误分类 | 普通翻译重用 provider/恢复约束；新流水线统一去重与版本检查 |
| `managed_readonly_steps.py`/`managed_readonly_translation.py` | 绑定既有只读预算、限定工具/fixture 合同 | 不扩大这些表和 scope，不借用其 grant 驱动生产流水线 |
| `automation.py` | JRA 固定 15 分、其他 10 分；榜单抬分；自动发布后 QQ 入队 | 新链改事件价值决策；独立网页提交入口禁止外发副作用 |
| `publishing_windows.py` | 地区窗口、候选/配额、soft_fill | 新链移除低分补量，按事件与时限调度；旧链只处理未纳入新链的文章 |
| `views.py:public_news_feed`、`RaceNewsExposure` | 赛事两槽过滤、头条/热门、分页 | 新链事件增量不能被旧赛事两槽吞掉；首页分地区排位和稳定分页 |
| `NewsArticle.effective_*` | `rewrite_*` 优先于翻译字段，人工字段又优先 | 新链已审核全文直接进入最终展示层，阻止旧改写覆盖 |
| `news_body_history.py` | 原 HRN 来源限定、每批≤10、前后指纹/回滚 | 后续按固定来源范围推广，不直接宣称现工具覆盖五地区 |

上述仅为源码事实。未运行真实组合、业务测试、CI或生产检查。旧 B285/B286 直接 PostgreSQL 执行问题不能忽略，后续 PG 测试先核固定环境，见 rollout。

## 2 端到端路径及接口

保持 Django/PostgreSQL/Celery。新增 P01 专用 service 模块，不建 agent 平台。

`discover_observation → ingest → claim_revision → clean → classify_event → protect_entities → translate_full → audit_facts → select → publish_web → build_feed → weekly_report`

- 每个listing stub在fetch_detail/parse之前先写 `NewsDiscoveryObservation`；详情失败也逐条留存。listing整体失败写同表的source-window记录，无URL的项目不伪造文章；成功后关联article/run。独立重大事件盘点作为另一分母，不能只靠抓到的stub证明没有漏采。
- 复用采集适配器；新链只接纳冻结来源/地区策略匹配且创建时间在启用边界后的文章。旧稿走历史清单，不自动补纳入。
- 所有阶段输入为 `run_id + generation + input_sha + policy_sha`；载荷中的网页/模型文字均为数据，不得改变工具权限、预算或发布条件。
- `clean_news(run)` 输出有顺序的原文区块、保留/删除原因、source_sha、clean_sha。采用确定性清洗，污染/模板疑点才追加模型区块判断；关键正文未能证明完整则 block，不做宽容器全文兜底。
- `classify_news_event(run)` 输出事件候选、事实条目、major/regional/reject/uncertain、主/相关地区与证据。完整可信正文用于判定，不能仅凭标题或旧低分提前扔掉未知实体稿。
- `recognize_news_entities(run)` 强模型每篇执行，返回 block_id、Unicode 字符起止、原文片段、类型、身份候选、证据。精确校验边界/重叠/原文匹配；译名由已采纳证据解析，模型不能自行造马名。明确原名但无全站 ID 时允许按 occurrence 保留原名，不自动产生跨模块关联。
- `translate_news_full(run)` 重用普通翻译 provider 及保护恢复工具；保留全文和摘要（摘要仅列表用）。P01 自己持有 stage claim；禁止嵌套触发旧自动改写/发布。`TranslationRun` 仍可记录结果，但不把 registered readonly job 转为普通任务。
- `audit_news_translation(run)` 逐块核原文/译文；姓名、数值单位、日期、名次、否定、计划/已发生、引语归属及正文遗漏。确定性数值检查与模型判决冲突时待处理。每个差异绑定原文与译文 span；未知/模型错误不等于 pass。
- `publish_news_web(run)` 唯一新链 writer，事务中重验资格、质量版本、人工编辑指纹、事件增量与预算状态，写最终全文、公开状态与发布回执；不调用旧 `publish_article_automatically` 的 QQ 副作用，不触发邮件。

新链接入 `tasks.py` 的 ingest/translation/automation/region-window/batch 路由处，文章一旦绑定 active P01 run，旧路径（含重试与手动重译任务）只能转新链或拒绝写入；人工编辑/撤回操作仍可用，但使未提交结果失效。上线前列全 writer 与调用点并完成回归。

## 3 最小数据设计与一致性

新增表均置于 `stable/models.py`，JSON 留证据，业务约束使用数据库字段。采用增量 schema migration；不把全量旧文章回填塞进迁移。

| 模型 | 关键字段及约束 | 用途 |
|---|---|---|
| `NewsProcessingRun` | article FK、input_sha、policy_sha、state/stage、generation、lease_until、next_attempt_at、event FK nullable、priority、primary_region、source_time状态、source/clean/translation/quality快照、target_revision_sha、parent_run FK、manual_target及editor provenance、expected_article_sha；unique(article,input_sha,policy_sha,target_revision_sha) | 输入版本和分阶段状态；历史 run 保留 |
| `NewsStageAttempt` | run FK、stage、seq、claim_uuid、generation、input/output SHA、provider/model/prompt版本、state、reservation金额、实际usage、两类budget FK、timestamps；unique(run,stage,seq)，claim_uuid唯一 | 每次外部请求、未知费用和响应归属；禁止覆盖已完成证据 |
| `NewsModelBudget` | period_kind(day/month)、period_start、currency、cap、reserved、spent、policy_sha；unique(period_kind,period_start,currency)；金额非负；state(open/blocked_overage/blocked_unknown/closed)，overage金额；准入在锁内检查spent+reserved+新预约≤cap，事实账允许spent超cap | P01专用金额额度，不扩张只读工具预算表 |
| `NewsEditorialEvent` | UUID、event_kind、identity_key（可空）、primary_region、version、published_facts JSON；已确认identity_key非空时唯一 | 非赛事新闻也有事件；归并不修改 RaceEvent/HorseProfile |
| `NewsPublicationReceipt` | UUID、run OneToOne、article FK、event FK、source_revision_sha、target_revision_sha、delta_sha、不可变全文/标题/摘要/原文及证据快照、verified_occurrences/verified_relations快照、previous_receipt FK、kind(new_story/correction_story)、publication_key、published_at、visibility状态；unique(event,publication_key) | 发布幂等与增量历史，引用已提交版本 |
| `NewsFeedSnapshot` | UUID、generation唯一、policy_sha、catalog_watermark、cutoff_at、ordered public_entry IDs、headline/hot entry IDs、slots metadata、expires_at | 可重放排序与分页，同一版本无重复漏页 |
| `NewsDiscoveryObservation` | kind(stub/source_window)、source FK、crawl_job FK、source item ID或规范URL、observed_at、source time证据、primary/related地区及unknown、stage/outcome/reason、article/run nullable FK；unique(crawl_job,kind,item_key) | 解析前候选与来源窗口失败，重复轮询按来源项目归并统计首次发现 |
| `NewsPublicEntry` | feed_seq唯一、kind(legacy/p01)、article FK、receipt nullable OneToOne、public_revision、不可变sort_time/主地区/priority/major_until、superseded_at nullable；unique(kind,article,public_revision)，每个P01公开新稿receipt唯一对应一个entry | 最小公开条目索引，统一版本稿和旧文章的稳定分页身份，不复制正文 |

`NewsArticle` 增加 nullable `active_news_run` FK 与 `news_generation`（默认0）用于强制路由和旧任务拦截。新表状态限定 choices + CheckConstraint；完成阶段要求输出 SHA，published run 要有回执（服务事务检查并以回执 OneToOne约束防重）。FK 对证据用 PROTECT，禁止删除绕过去重。索引：run(state,next_attempt_at,priority)、run(article,-created_at)、event(identity_key)、receipt(event,published_at)、attempt(state,reserved_at)、snapshot(expires_at)、discovery(source,item_key,observed_at)、public_entry(primary_region,-sort_time,-feed_seq)。实际 migration 编号由实施时迁移图决定，不预占共享编号。

`input_sha` 覆盖来源 ID/URL、标题、原始正文/HTML、语言、主地区/人工归属锁及源时间证据；`expected_article_sha` 另外覆盖所有最终展示字段、manual flags、workflow/withdrawn、active run/generation。术语/来源/模型/prompt/质量/编辑策略版本纳入 policy_sha。人工更新、原文变化或策略变化都不得让旧结果继续覆盖。

锁顺序固定：budget（月→日）只用于预约/结算短事务；涉及公开/事件归并的业务提交先取publication advisory lock，再按event ID升序 → article → run → attempt；不公开的阶段结果提交只锁article→run→attempt，不同时持 budget 与业务锁。外部请求不持数据库锁。claim 用 select_for_update(skip_locked)，generation递增；结果提交 CAS 重验 generation、lease、版本及未撤回状态。新原文重抓时先落discovery源文证据及新run快照，旧已发布NewsArticle的源文与公开字段均不覆盖；仅在article锁下切内部active run，旧 run=stale，旧 generation的结果只留证不写公开字段。

Celery投递使用 `transaction.on_commit`，再由每分钟扫描未完成 run补偿 DB提交后broker失败；不要求 exactly-once网络。成功 checkpoint可重用；发送后超时/worker失联视为 unknown，先按供应商request ID核对，不能查清则保留费用占用并待处理，禁止自动重发同一次不确定调用。

## 4 调用、重试、预算与容量

新 `news_model_gateway.py` 仅提供 P01固定任务 `event_classify/entity_check/translate_full/fact_audit/body_review`，不提供任意工具执行或自由 URL。文本中指令不获得工具权限。请求模型/schema/prompt/价格配置版本均绑定 attempt；不锁死供应商产品名，型号需通过小样例比较后冻结。

每次调用前同时锁月/日budget并按输入token+max_output_tokens的价格上界预约，写attempt后才请求。币种/费率缺失或输出上界不可计算则拒绝付费；供应商隐式重试关闭。返回usage核账，unknown保留预留；实际支出异常超上界时原子结算到真实spent并设blocked_overage，允许账面超过cap，停止新调用，不伪报余额。预留从reserved扣除、真实费用加spent、attempt结算版本在同一预算事务提交；迟到usage按settlement_version仅处理差额，不能重复扣费。日/月归属固定请求预留时的北京时间期间，跨午夜/跨月结算仍回原bucket，不能占用新bucket掩盖旧超额。blocked_unknown在可靠账单对齐后才清理；overage状态不自动因日期改变恢复，需先完成差额核对及更新明确额度/停用策略。普通翻译同样从news_model_gateway预约后调用现有provider的单次请求能力，provider私有循环不得绕过attempt和总次数。重大稿优先不意味着突破额度。

阶段已知可重试错误最多2次重试，退避1/5分钟，单 run总外部请求最多10次；针对性重译最多1轮（含重译后强审校）。任一上限先到即待处理，不重新建run刷新同一输入的次数。新policy重放需显式批次并计入原期间预算，不能自动无限续命。有效请求已有结果不重复计费；重复投递读取终态。

初始工程容量：每次扫描≤100条，五地区轮转，每区每轮≤20条；P01 model worker并发2、prefetch1；单次调用超时60秒、stage lease180秒。正文超过已验证模型上下文/输入字节上限则标 oversized待处理，禁止静默截断全文；后续需要分块时另补完整覆盖测试。这些是保护默认值，模型小样例验证后可在相同产品范围内调整，不能通过放宽质量标准解决容量不足。

预算未填实为0，网络模型功能不启用。小样例评估先从既有合法缓存选20篇（每区4篇，覆盖困难样例），固定输入及调用清单，至多两个候选强模型；以明确次数、token和金额上界形成评估包，不属于本轮实际付费动作。通过后扩展100篇gold/保留集并配置正式预算。预算不足时重大稿优先、普通稿保留队列，全部超过时效仍记录逾期。

## 5 事件去重、增量与选稿

首版不建全站知识图谱。候选检索按已核身份（赛事届次/马匹/组织）、事件类型与时间窗口召回≤20个事件；全文模型提供同事件证据，程序校验实体、时间、事实引用。来源同稿ID/规范URL只能确定同一来源锚点；必须连同source_revision与事实增量判断重复，不能吞同URL更新；弱名称/标题相似仅作召回。多解或跨届不明进入uncertain，不自动合并。不同地区对同一事件只计主地区。

事实条目格式：`subject_ref + predicate + object + effective_time + modality + source_span`；主体可为强身份，也可为本稿内证据明确的原文实体，不因此写canonical映射。模型做语义比较，程序校验引用，冻结相对于 event.version 的 `new_facts/contradictions/repeated_facts`。进入publish时event锁下若版本变化，重新比较（事务外），不使用过期增量。

事件identity_key采用 `news-event-v1:<kind>:<规范证据元组SHA>`，不是模型自由生成字符串。键必须由程序从验证过的结构化证据生成：

| 类型 | 规范元组与证据 | 防误并条件 |
|---|---|---|
| race | canonical RaceEvent ID；或已核对来源race ID及跨源映射；或组织者+赛场+当地赛日+场次的完整证据元组 | 必含届次/日期，不凭赛事名；同赛赛前/赛果/更正共用事件，通过fact增量区分 |
| retirement / injury | subject_ref + episode_ref；subject为canonical ID或可信source-scoped马匹ID及已核跨源映射；episode为原始公告ID，或明确事件发生日期+事件类型 | 不用报道发布时间充当发生日期；同马再次伤病/复出后再退役需要独立episode |
| policy / appointment | organization_ref + jurisdiction + 官方文号/公告ID；无文号时为明确生效日+条款/职位scope | 转述的发布日期不同不拆事件；不同辖区/生效批次不强并 |

跨源alias只使用已核验映射或可追溯官方交叉链接，不能凭模型同名结论造等价。没有canonical ID但有可信来源稳定ID的稿可以自动生成source-scoped键并保留原名，先查跨源已核映射和事件候选；有证据指向既有事件则绑定其key。若发现疑似跨源同事件但无法确定映射，或episode/date多解，保持candidate/uncertain，在既有待审中允许编辑选择既有事件或以证据创建新事件，留审计后重跑。只有明确无候选且事件元组完整时创建新根。并发使用相同规范key的unique upsert；跨源键若无法归一不允许两条不确定稿同时自行判为新根。

候选检索分主类型/主体/发生区间，取21条用于判断是否超过20；超过时标recall_overflow，不能默默截20后判“无重复”。无法把日期或身份规范成上述元组时不承诺自动处理，明确异常原因；这与“无中文名可正常翻译”分开。现有事件归并由编辑绑定事务处理：按event ID升序锁定、选根、移动未发布候选，已公开fact/receipt合并留痕并检查重复，不静默删已发稿。

首篇从已到达的合格候选按来源证据可信性→正文完整性→首次发现时间选主稿；允许未完全处理的其他来源晚到，不为等它们突破期限。已公开后，只有重大new_facts或可信更正可以新发；仅正文更长不新发。并发来源必须以同一确定identity_key upsert锁定事件；不能确定身份时不凭字符串hash强并，送异常列表。事件判断本身的unknown不能被兜底旧评分发布。

P01选稿明确停用JRA固定加分、榜单抬到自动阈值、soft_fill及旧赛事“第二稿即重复”规则。原有来源合法性、手动锁、撤回、质量条件仍生效。重大稿按deadline优先；regional按轮转地区队列和新鲜度，旧quota仅作容量上限、不能成为降低质量理由。配额与receipt提交同事务，失败释放预约；不要在窗口选中时就算已经公开。

每分钟扫描 due/ready，符合既有合法来源频率内尽量5分钟发现一次；若现有来源允许频率不支持，报告来源时效缺口，不擅自扩抓。保留原文时间到公开可见的端到端延迟，不只计内部处理时间。

## 6 全文展示、异常处理与首页

### 6.1 全文与唯一提交

区分三种版本：source_revision=input_sha；目标译文revision=target_revision_sha（机器初译用固定初始值，人工提交为规范化title/body/summary及编辑批次的SHA）；公开revision=receipt UUID。run唯一键含前三种输入版本（article/input/policy/target），人工改稿不再命中旧失败run。

人工修正通过既有编辑页面的P01分支保存到run.manual_target，不直接写已公开内容；记录编辑者/操作日志/expected_article_sha，保留人工原文。重新审校恰好这份人工目标，不自动再翻译覆盖；审校失败仍可产生下一manual_target版本。成功后人工标志并非永久阻断：若目标SHA、编辑版本、原文和policy仍完全一致，则提交已核验的人工稿；发生新编辑则旧结果stale。

第一篇通过时写不可变receipt并将已审字段投影到尚未公开的NewsArticle供旧接口兼容，清空非人工rewrite_*且验证effective hash。一旦公开，日常P01流程不再修改其标题、正文、摘要、原文快照和发布时间。后续同URL重大事实更新，或需要公开的实质译文/事实更正，都生成新的run、独立receipt和新public entry；不存在current_receipt替换路径，不把旧稿路由指向新内容。仅措辞/排版差异不形成新稿，也不自动修改旧稿。

NewsArticle在存储上仅作来源唯一锚点；每个独立公开稿件以receipt承载完整不可变内容及自己的公开时间。用户确认的是独立稿件行为，不要求复制来源ID或改现有来源唯一约束。新稿使用独立公共稿件URL，页面标明所针对的前稿并链接原稿，旧稿页面和旧正文保持原样。

publication_key由程序规范生成：new_story使用已核重大事实增量的规范键；correction_story使用被纠正receipt ID+原错事实ID+正确事实/原文证据的规范键。事件锁下检查该修正是否已在其他新稿覆盖，只有未覆盖的实质修正可新发，重复人工提交、换模型或换措辞不能多发。所有公开稿统一按(event,publication_key)去重，correction_story不以“原文没有新事实”为由被过滤。

发布事务重验当前目标、质量、人工指纹、事件版本和来源资格。既有人工发布/改稿入口对P01稿调用相同writer；后续重抓在进入upsert前识别已公开P01锚点，源证据只写discovery及待审run，不覆盖旧NewsArticle正文。翻译prompt从run.source_snapshot构造不可变TranslationInput，复用普通provider单次请求能力，不依赖临时改写ORM文章来复用旧translate(article)。第一篇已发布也不阻止后续重大增量run发布。尚未审核的人工改稿不能通过旧有效字段即时出现在公开页。

### 6.2 新旧曝光和稳定分页

P01有receipt的文章由事件增量决定资格，不再受 `RaceNewsExposure` 旧赛事两槽限制；无receipt旧文章继续原过滤。所有公开读取统一消费 `NewsPublicEntry` 引用，详见6.3。撤回/权限/可见性检查在所有查询路径共同执行。原稿与更正稿均独立保留，新稿链接原稿；首页可优先最新实质更正，但不改变旧稿内容和详情。

每5分钟（或重大稿新公开时）生成feed snapshot。取池先按五地区分别取30天内最多100个可见public entry，先活跃major、再按不可变sort_time/feed_seq降序，总首部上限500；不能先全站截500再分区。超量地区记录overflow数，未进首部的已公开稿仍进入档案尾部，不能从公开/漏报分母消失。

重大优先工程初值为首次公开后24小时，major_until写入entry不可变；重抓/重试/换标题不续期。重大新事实新entry独立取得24小时窗口；同事件可信更正立即替代旧版在首页的优先资格，旧版保留详情。过期major进入普通轮选。该值是“重大事件临时倾斜”的初始实现参数，按真实回放校准并版本化，不是用户指定数字。

首部排序：活跃重大稿按最新sort_time优先，其余五地区round-robin；起始地区按滚动7天普通席位时长最少者，区内最新优先，空区跳过。无重大例外占位时，普通前5席在供给齐全时各区至少1席。重大期间可占更多位置，但不能因已过期major长期压住地区普通稿。首部容量不限制网页发布。

### 6.3 公开版本消费合同

- `/news/<article_id>/` 对P01始终读取首稿的固定receipt；新稿统一使用 `/news/stories/<receipt_uuid>/` 独立详情路由，新稿链接前稿。旧slug保留原目标，不自动重定向新稿；无receipt的旧文章保持现有字段读取。
- feed/headline/hot、新闻搜索/档案、详情前后篇、赛事/马匹相关新闻及关注区统一用 `NewsPublicEntry` 的版本引用生成标题/正文/摘要/时间/链接；P01关联必须从该receipt自身的verified_relations读取，并复验目标当前可见性，不能直接继承anchor article的关系。不得一个地方读receipt、另一个地方直接取anchor的最新源文或effective字段。
- 每份receipt冻结本稿verified_occurrences与verified_relations，包含本稿source_sha/occurrence span、实体ID、既有关系证据及版本。首版仅采纳“该稿经核验身份/occurrence”与已有已确认anchor关系的交集，不新增模糊绑定；因此新稿纠正为B而anchor只确认A时，先不展示任何马匹关联，绝不挂到A。旧稿receipt和旧关系不修改；后续P03可按其范围补合法关系。无需全站实体ID的原名仍可正常翻译发布。
- 相关新闻/关注查询必须按receipt关系证据筛选，然后检查对应马匹/赛事的当前公开状态；不能先用anchor关系召回后将全部receipt展开。receipt中的confirmed horse/race ID数组可用JSONB GIN索引，单稿最多128个关系条目，超限记关联缺口而不截断正文；无证据只影响关系展示，不阻止已合格全文发布。旧文章无receipt时继续原关联路径。
- `HomepageHeadlineSelection`和`HomepageHeadlineRecommendation`各增加nullable receipt FK，选定P01稿时绑定精确receipt；旧article-only记录仍按旧语义。保留现有人工选择/取消/有效性检查，不虚称已有TTL或自动改变人工头条。推荐evidence带public_entry和质量SHA，接受时再次验可见性。
- 首篇与每个新稿公开时间分别保存；任何日常更新不刷新anchor初次published_to_web_at。需公开的实质更正也是独立条目，使用自己的公开时间；不能用更正名义将旧内容原位替换。
- 每篇独立稿件按receipt单独撤回，前稿撤回不会自动撤回其他合格新稿；无receipt旧文仍按原article级撤回。明确的整来源撤回操作才隐藏该anchor所有稿件，并列出精确影响清单；新稿发布本身不触发旧稿撤回。receipt内容不可变，仅可见性可经审计writer更新；撤回的链接不指向未审草稿。
- 发布/更正/撤回在事务提交后失效该anchor所有详情别名、相关列表与当前feed缓存；所有读取再次校验可见性，缺失回执不降级输出源文。缓存验证包含Nginx/应用层，不能只清Django缓存。

### 6.4 稳定分页、旧档案与曝光

`NewsPublicEntry`仅作公开索引：P01每个new_story/correction_story receipt各建独立entry；legacy每次真实首次发布/明确重新发布建publication_generation，旧entry标superseded，原URL行为不变。排序键在entry建立后不可修改；纯历史修复不新建entry。模型迁移不自动回填，单独分页backfill已有公开旧文章（按article+既有公开版本幂等，沿用旧发布时间），上线切读前检查索引集合与当前公开文章/receipt一致。

所有新旧公开提交与entry写入在同一短事务中完成，通过数据库事务级publication advisory lock串行分配feed_seq并持锁到提交；快照构建先取得同一锁，读取已提交最大feed_seq为catalog_watermark再释放。这样没有先分配ID后迟提交的条目穿过水位线。锁只覆盖数据库提交，不跨模型调用。发稿批量逐篇短事务，不持锁做全表扫描；锁等待超时进入重试不静默忽略entry。

snapshot首部H冻结所有已占用的头条/热门/混排entry IDs（去重），档案尾部T定义为该水位线内全部公开entry减H，按不可变(sort_time DESC,feed_seq DESC) keyset分页；尾部不从“混排最后一项时间”开始。读取始终过滤现在已撤回/已替代版本，可产生空位但不补新ID。水位线之后的新稿/回填只出现在新generation；实质更正新entry只进入新的generation，旧entry排序键不变。仍可见集合完整遍历应无重复无遗漏，明确撤回/替代导致的排除单列。

无generation的首次请求绑定最新ready snapshot并在响应头/分页链接输出generation；无snapshot时显示可解释暂不可用，不能生成未计量的随机混排。generation有效24小时，过期链接提示刷新，不暗换顺序。服务端校验签名cursor的generation、水位和最后sort key；深页访问也不全表OFFSET。

snapshot记录席位/地区/事件/policy与有效时长，仅表示展示供给。成功响应日志聚合generation+page/cursor摘要，含代理缓存命中；只记匿名聚合，不新增cookie或持久化IP。没有generation的首请求须在响应日志捕获实际选择的generation；曝光只计该响应实际保留的entry（撤回过滤后），不能直接用旧快照ID全量计。日志缺失时仅报席位而不宣称真实曝光完成。热门区不得绕过同事件控制；人工头条例外单列。

## 7 独立的历史修复交付与验证

本节仅承接用户先前确认的定向历史污染/误译清单修复，不能作为日常更新修改旧稿的旁路。新增链完整交付后单独处理 N07/N08。复用news_body_history的冻结清单、每批≤10、前后fingerprint、幂等及回滚；先扩展五地区adapter合同与可写字段依赖测试，移除HRN硬编码必须限于manifest明确来源。没有原始证据或人工变化的条目保持blocked。

历史动作保留原 URL、published_to_web_at、人工字段、撤回状态；不当新稿排到首页，不发QQ/邮件。更新正文关联和曝光时在同一版本上校验；本轮只调整已存在且有确定证据的关系，不借机补采马匹。恢复必须after_sha匹配，发现修复后人工修改则停止该条回滚，不能覆盖。

## 8 交付接口与文档

最小后续模块：`news_pipeline.py`（run与状态）、`news_model_gateway.py`（有界调用）、`news_editorial.py`（事件/选稿）、`news_feed.py`（快照/分页）、`news_quality_report.py`（只读报告）；现有modules只做必要接入。

P03/P04消费只读结果：article ID、input/quality SHA、verified occurrences、可选canonical ID、provenance；不会为了本项目自动创建全站实体。锁定输入/输出schema_v1。更新current_state、decisions，实施后按实际影响补deploy_runbook；不机械重写全部历史状态。


## 实现收尾约束（2026-10-27）

- 人工搁置或驳回会推进文章/run generation；只有当前 generation 的自动处理状态允许阶段推进。迟到调用仍结算实际费用，但不能恢复人工终态。
- 旧公开索引写入集中在三个真实 legacy 发布入口的短事务内，锁顺序为公开索引锁→article；普通 `NewsArticle.save()` 不取全站锁，网络抓取/翻译不持有该锁。
- 模型返回类型错误统一转可解释待审；恢复扫描逐条隔离坏记录。认领同时绑定预期 stage 和 generation，禁止用旧阶段的 payload 执行新阶段。
- 更正幂等键由前稿 receipt、排序后的旧事实 ID、正确事实 ID 组成；引用位置仅作证据。已公开更正先从候选材料排除，避免换引文位置或混合旧/新更正重复公开。
- 事件身份请求包含五类身份的字段组合、来源作用域及示例；空启用时间和 off 策略不进入纳入判断。地区额度复用既有配置解析器。
