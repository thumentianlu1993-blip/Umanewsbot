# P01低成本流水线技术方案

## 基线与兼容

复用Django/Celery状态机、NewsProcessingRun/NewsStageAttempt及日月预算账，不更换主干、队列或网页writer。新能力由NEWS_QUALITY_POLICY内显式contract_version=context-v2启用，缺省保持legacy；策略SHA包含v2、模式、风险规则、模型配置、预算及提示词版本。旧run受现有policy_sha失配保护，不能混用新证据。生产配置不在本次改动范围。

现有stage清单保留body_review/event_classify/entity_check/translate_full/fact_audit，升级仍使用同stage的下一attempt，通过price快照中的profile和thinking记录。业务状态存现有JSON字段，不计划新增表/迁移；若安全实现需要迁移，先修改方案并复审。

## 1. 上下文实体契约与定位

v2响应：`{"coverage":"complete|uncertain","entities":[{"block_id":"b0","text":"原名","type":"horse","context":"逐字原文上下文"}]}`。禁止start/end作为v2输入字段，不能靠旧数字跨度旁路必需上下文。

确定性算法：在原始block_map上查找context的所有精确出现，再查找context内text的所有精确出现，组合成候选原文区间；候选区间集合必须恰好一个，否则ContentBlocked。必须含完整text，不使用NFKC/fuzzy或大小写替换定位；上下文可以有前后空白，不能strip后改变引用。去重、128条限制、实体类型、重叠、重复出现逐条验证沿用原门禁。输出内部仍为带start/end/token的规范occurrence，并保留context及contract_version，既有保护和译名解析继续使用。

同名两次且上下文相同/整个context里含两次同名视为歧义，模型应提供分别有区分力的上下文；不能用occurrence_index猜其指代。标题只有名称时允许context==text且唯一。实体coverage=uncertain转待审；初版不自动新增局部实体澄清调用。

## 2. 短证据审校与硬检查

v2全文审校保持九类checks与pass/fail/uncertain；issues使用kind、独立source/target的block_id、quote和context（最终schema固定、禁额外字段）。引用交程序转成内部span，重复引用必须提供唯一上下文；遗漏允许target_quote为空，但必须提供存在于目标块的锚定上下文及明确missing语义，禁止把空引用定位为任意0点。实现可采用统一的quote/context双字段，缺失目标只记录整块待修而不伪造字符跨度。实质更正audit_corrections保持独立，不能被v2适配绕过。

提取可复用的纯函数hard_translation_checks(clean,target)，返回带block_id的结构/数字差异和summary差异。结构和placeholder仍在restore阶段检查；v2只有硬检查无差异才请求全文审校。硬检查失败可构建一次修复任务；不能直接把hard pass视为quality passed。最终validate_audit仍合并模型检查与硬检查。旧审校schema继续由legacy分支处理，v2不接受legacy span-only证据。

## 3. 模式、风险和供应商请求

request_spec增加run/profile上下文：显式base和deep配置，只有配置允许的profile可用；strong仍是能力标签，thinking为disabled/enabled，与quality_tier分别校验。首轮所有base使用Pro非思考，deep使用Pro思考。每次reserve保存有效spec完整快照及prompt_version；发布核验依据当前策略重建同profile spec并检查路由所需等级，不能通过伪造price降级。

风险规则版本化：由原文/事件已验证事实中的明确退役、伤病、禁赛、赛果更正以及correction关系触发深度审校；普通稿仍全文强审校。词法规则只提高风险，不用于选稿或降低门槛。常规审校有效uncertain最多追加一次deep attempt，前一uncertain回执保留并绑定target_sha；无法解析的响应不冒充uncertain免费循环。deep fail进入一次修复，deep uncertain/二次失败待审。风险稿修复后的全文审校仍deep，普通稿若已升级则保留deep，不回落。

事件判断先base；缺少身份依据的uncertain按原规则待审，不继续昂贵翻译。评估可显式diagnostic_continue_editorial=true继续翻译诊断，但报告不得计作发布资格。正文审查payload只提供疑似块及相邻上下文和完整块指纹，模型只能对疑似块给keep/remove，重建clean时核验未修改其他块。

供应商适配显式发送thinking配置及阶段max_tokens，不启用SDK自动重试；检查finish_reason=stop才解析为成功。所有截断按已知失败计费，不无限提高额度。输出预算采用base固定值和翻译长度派生值（上下限由policy固定），不能超出冻结spec。HTTP超时与run lease须一致或通过已有租约机制保障，长请求不能因60秒客户端/短lease制造重复。

## 4. 局部修复

translate_full的payload增加mode=full/repair_blocks、base_target_sha、required_block_ids和repair证据。初次翻译继续完整source；修复时仅发送受影响原文块、对应旧译文、相邻必要上下文和全局实体字典。区块集合由已验证硬检查/模型issue决定，不采信模型自行增加的修改范围。

响应必须恰好覆盖required_block_ids；合并函数验证base_target_sha、块ID唯一、未目标块逐字不变、title/summary明确列为目标时才可替换。使用原始占位文本基线或显式受保护target重建，不从已恢复中文名逆向猜占位符；保存完整受保护译文及其摘要到既有translation_snapshot扩展字段/专用JSON元数据。最终输出结构对旧网页接口保持原样，额外证据不得泄漏正文。

结构缺失、无法安全局部定位、全局性错误可切换一次full repair，记录reason；repair_count仍最多1。最终合并稿全部hard检查后全文审校，最终发布按完整目标hash核验。人工稿仍禁止自动修复。

## 5. 成功结果复用与回执

初版只复用同article不同run的body_review/entity_check；event_classify与fact_audit不跨run复用。缓存键含article/source输入SHA、clean SHA、语言、stage、完整payload SHA、policy SHA、有效spec SHA和prompt SHA。只查completed且原始paid attempt已有可验证输入/输出hash和正常预算状态的结果；不复用cache派生回执以避免长链。原始来源/手动修订变化或model/profile变化失效。

缓存命中创建当前run的派生attempt，保留origin_attempt_id、origin run、cache key与完整结果/输入快照，不产生HTTP、预算预约或费用；源attempt费用保持在历史账。发布核验同时验证当前派生回执及原paid源回执，来源仍为strong且所有hash/策略/预算状态匹配。实体中文名在新run重新resolve并在发布再次查TermEntry。缓存命中不能移除同币种unknown全局阻断，不能缓存用户人工目标或复用旧目标审校。若无需新增派生attempt字段，使用usage.cache_origin和显式provider/cache标记，禁止把cache标记当供应商。

## 6. 单篇预算与并发

保留月→日→attempt既有金融锁顺序，通过新增同一article级预算串行化锁/原子聚合，确保不同run并发也共享单篇上限；锁顺序必须与业务article→run→attempt一致审查，不能引入月→article与article→月逆序死锁。优先使用独立金融锁键（数据库advisory transaction lock按article ID）在预算锁之前取得，覆盖该article全部预约/结算路径；不在网络期间持锁。若使用统一月日预算行串行化，在锁内聚合同文章实际费用+未结算reservation并检查article_cap，也可避免新增article行锁。实现选择后在本方案记录。

单篇聚合包括同文章所有run历史已计费attempt和unknown预留；currency和策略变更不能重置已发生费用，配置币种变化应拒绝混算/要求明确新账域。升级、已知失败及修复同样计入。超单篇上限进入review/article_budget_exhausted，不用每日定时重试绕过；日月额度保留原等待语义。成本输出必须区分spent/reserved/unknown，缓存零费不覆盖历史成本。

## 7. 发布证据与防旁路

check_publication_evidence按contract_version选择实体/审校规范化函数，重建context定位并比较全部occurrence；核验最终全文审校为当前target/source/editorial/policy且满足required profile。局部修复必须有完整重建链；当前receipt引用的原始译文和补丁hash不可变化。cache派生必须重验原始paid receipt及原来源strong能力，不能借空provider逃避预算或请求未决检查。无新增writer，不调用QQ发布函数。

## 8. 实施范围、验证与回滚

预计涉及news_content、news_prompts、news_pipeline、news_model_gateway、news_publication、news_evaluation及相应现有测试模块；按需独立纯函数模块并登记news_quality选测映射。新契约opt-in，旧测试保留；不用修改通用raw numeric和其他业务。方案批准后才编写test_cases与RED，覆盖上下文、模式路由、局部补丁、缓存来源、单篇并发账及发布再验证。固定SHA隔离PG/无网络容器回归；本次按用户补充指令只运行定向受影响测试，不启动7000多项全量CI。

回滚为关闭新契约/流水线并冻结新run，不把v2证据转换成legacy成功；本次不部署，无生产数据动作。实测使用同一生产纯函数及有效请求构造器，固定SHA缓存3篇、本轮0.50美元和历史20美元双限、单篇cap/各阶段token上限均写manifest。请求结果本地/远端持久收据核对；新unknown停止，不重发。

## 9. 首版冻结的细节

- v2审校issue固定为`{kind,source:{block_id,quote,context},target:{block_id,quote,context},missing}`。所有字段必填。source引用必须非空并唯一；非missing目标也须非空唯一。missing=true仅允许target.quote为空、target.context为目标块的非空精确子串且唯一，内部只记录整块修复需求，不伪造空引用的字符定位。pass时issues必须空且checks全true；fail/uncertain无有效证据转待审，不猜问题块。
- `price`有效配置固定包含contract_version、profile、thinking、max_output_tokens、max_input_bytes、http_timeout_seconds、model/provider/prompt_version/quality_tier和费率；配置中的base/deep映射经解析后只保存有效值。base非思考、deep思考，HTTP最大120秒，claim租约至少timeout+60秒。翻译token额度取min(硬上限,max(最小额度,按受保护输入UTF-8字节数乘固定系数向上取整))，预算按实际选中的max_output_tokens预留；代码不偷偷超限。上限不足而截断即失败，按一次修复/待审边界处理。
- 单篇金融并发选择PostgreSQL advisory transaction lock(namespace+article_id的稳定64位键)，所有reserve/settle/mark_unknown先取该锁，再沿用月→日→attempt锁顺序；这些函数不得在持article/run业务行锁的事务内调用。相同文章跨日/月预约也共享锁。v2金融路径要求PostgreSQL，自动测试用隔离PG。币种同文章历史必须一致；费用聚合包含全部run的实际费用和settlement_version=0的已预约费用，缓存派生无预约但保留原始费用记录。日/月cap调整不清除历史单篇支出。
- cache派生attempt使用provider="cache"且usage.cache_origin存原paid attempt ID（单级）。claim请求次数显式排除cache，不用provider空串掩盖来源；publication预算检查须对cache验证origin day/month预算，对普通paid验证自身预算，统一检查全局同币种unknown/overage。cache禁止调用settle_request（没有预约）；在claim之后独立原子完成派生attempt，核验当前run/generation，保留输入/输出hash、model/spec和当前时间。
- 局部修复保存受保护基线在`quality_snapshot.repair_base`，包含原始响应和target_sha；`translation_snapshot`保持原有网页结构。初次翻译恢复前即存原始响应副本，首次审校结果写quality_snapshot时保留基线；补丁逐块替换受保护响应再调用原restore_translation，不做中文名逆向替换。发布时沿attempt输入、原始响应与补丁重建最终目标，对比translation_snapshot。
- 首轮3篇小测单篇上限0.15美元、整批0.50美元、历史累计20美元。各阶段base输出上限8192、deep8192，短阶段可按固定更小上限；价格在实测前查官方并冻结。调用前若最大预约不能放入单篇/整批余额则停止该篇并如实报告，不抬高额度；预算未使用部分不是已付费用。

## 10. 首轮审查修正（R1–R5）

R1 引用两端独立定位：source.block_id为title或原文块，target.block_id为title/summary/目标块；人工稿允许body。允许跨块，多个来源以多个issue指向同一目标，修复目标ID去重。unsupported_claims的source引用是相关原文核查锚点，不声称原文含有新增断言；该语义仍由全文审校判断。没有任何可核查锚点则待审，不伪造证据。missing=true须目标quote为空且context唯一定位到现有目标块；无法提供锚点转待审。以下为字段形状示例（引用必须实际存在）：

- 摘要数值错误：`{"kind":"numbers_units","source":{"block_id":"b1","quote":"27","context":"The prize is 27."},"target":{"block_id":"summary","quote":"28","context":"奖金为28。"},"missing":false}`。
- 跨块归属错误：`{"kind":"attribution","source":{"block_id":"b0","quote":"trainer","context":"The trainer said it."},"target":{"block_id":"b1","quote":"骑师","context":"骑师表示如此。"},"missing":false}`。
- 遗漏事实：`{"kind":"completeness","source":{"block_id":"b1","quote":"a plan","context":"This is a plan."},"target":{"block_id":"b1","quote":"","context":"比赛消息。"},"missing":true}`。

R2 v2预算账身份仍为period_kind/period_start/currency，policy_sha只记录最近预算策略，不能成为新账域。v2预约取得金融锁后读取并锁定既有账行，按当前day/month cap更新cap/policy_sha但不改spent/reserved/state；额度调低后若占用超限直接拒绝新预约，unknown/overage状态不能靠配置变化清除。旧请求按其原预算FK及原价格结算，不因policy变更拒绝结算。单篇聚合所有run，预约锁内再次检查run.policy_sha等于当前策略，禁止旧worker用过期策略回写cap。legacy入口保持旧策略不匹配拒绝；v2启用后即使旧legacy迟到结算也遵循article金融锁→月→日→attempt的顺序，金融锁不取得业务行锁。

R3 翻译原始响应在restore之前即保存在attempt.result及repair_base，附raw_sha和原attempt_id。字段/块ID顺序完整且文本类型正确时，空块/占位符错误可准确定位到目标块，使用局部修复；缺块、重复块、错误字段、无法安全解析的结构使用一次full repair并记录原因，有限JSON不可解析/超结构限及人工稿直接待审。数字硬检查失败同样只消耗一个repair_count。首次恢复失败没有target_sha时，使用raw_sha绑定补丁基线；完整恢复后再记录最终target_sha。第二次恢复或硬检查失败直接待审。发布重建从原始paid响应开始，允许原始未通过restore但结构安全的补丁路径；核验修复任务ID集合、raw_sha与整篇修复理由，重放后必须通过restore+全部硬检查+最终全文审校。

R4 stable_source只移除clean顶层body_review_attempt_id，其余正文、审查决定、clean/source SHA均保留。所有v2模型输入、缓存键、发布输入重建共用此纯投影，运行回执ID仅保留在run.clean_snapshot。正文审查输入由同一投影派生疑似块+相邻块及完整块指纹。entity缓存跨run遇到不同正文审查回执ID仍可命中，source/规则/模型/语言变化失效；实体payload显式含language，body payload同样含language。

R5 少量实测是独立离线评估账域，不接生产数据库预算账，不向生产路径增加unknown豁免。每篇0.15美元为本批增量，整批0.50美元；历史总额20美元按外层累计守卫，导入既有5.23518714美元占用且继续保留其中0.03872088美元旧unknown。manifest绑定旧2026-10-28批第56次请求的包SHA、请求身份、输入SHA和预留（从原始记录只读取得，不重发），并绑定本批输入、代码、价格与调用限制。原生产路径始终全历史单篇聚合、同币种unknown全局阻断。任何本批新增unknown停止整个批次。报告分别列出评估增量账、历史合计及生产预算隔离测试结果，不能把评估账当生产账验收。
