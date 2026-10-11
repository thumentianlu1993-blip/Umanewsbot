# B105 同文章译名候选持久读取方案

状态：PLAN_ONLY，交原R审核；未实施/执行。依赖固定 `047e3305cd287f6630eac546e156d831e94b0941` / tree `67e755d385725fa7404cba822bf65d74f50403cf`，等价已合并 `1dd5e0a508957672bcddd1c33e454fbbef1b75c1` 的产品树。合同M03 tasks:510、TC-A02；B104来源回执已交付，不重复。具体源码SHA列于新runtime inputs.json。仅内部翻译候选，不核验HorseProfile身份，不开放URL/任意词典搜索/发布或新生产路由。

## 新私有合同及顺序

新增 receipt_version=3，固定 `(managed-source-terms-v3, source_terms_v3, readonly-result-v3)`；job/origin分别 `readonly_translation_retry_v3/program_fixed_translation_retry_v3`。固定步骤仍两步：`source_excerpt:1/source_terms_v3/{body_chars:256}` → `translation_result:1/translate_full_source_v1/{}`。source step key不变；root.allowed_tools只有新query版本。原1逻辑工具读取、2模型requests、2quality rounds、600秒不变，多条内部SQL不冒称一条SQL。新工具不能被模型选择或追加。v1/v2 codec/默认登记/原对象重投保持；既有root不能升版。

1. 原claim/parent→readonly root→Article→Run锁序确认版本/grant/permission_epoch/nonce/PID-thread/源SHA/期限；提交原一个read slot及inflight step，再按原permit进入锁外ORM读取。
2. 同一次工具调用先做受限Article SELECT（原publication v2投影保留），从实际标题/正文生成候选keys，再读有限词典/外部别名及英文关联赛事材料。各行是真实ORM记录。不得由用户传term IDs/名字/URL或成功resolution。source SHA仍对完整合法输入计算，超过本片上限拒绝，不能切正文再算新SHA。
3. 构造原ArticleEntityIndex，调用原 `terms.resolve_article_entities(..., preloaded_index=index, structured_entities=...)`；不调用会自行无界查询的 `resolve_article_entities_for_article`。保存候选快照/材料manifest与source结果为一个真实step UUID/canonical SHA。finish前原grant/源/期限复验；所有查询在原业务事务/锁外，不为词典另持业务锁。
4. v3 consumer从已完成step还原ArticleEntityResolution传给原provider.translate；不再在consumer:803重新查词典。read_ready/完成重投复用同一step；checkpoint_saved沿原免费apply。model_started不明不重新发送。旧v1/v2仍原临时resolver。

## 精确schema

v3外层为v2完整result字段（query/result版本替换）加唯一 `term_snapshot`；外层step_uuid的真实mint/绑定沿原finish。term_snapshot精确键：`schema=article-term-snapshot-v1, article_id, input_sha256, source_language, read_started_at, read_finished_at, inputs, resolution`。inputs按固定kind顺序数组：`term,alias,external_alias,runner,result`；每项包含精确公共键 `{kind,id,updated_at,row_sha256}`，并按kind追加以下最小值（不能只存摘要）：term无附加键；alias追加`term_id`；external_alias追加`external_horse_id`；runner/result追加`event_id,article_id,horse_name_key`。这些值均来自实际ORM投影，horse_name_key按原normalize_horse_entity_key生成；来源均来自实际投影，按(kind,id)唯一。结构evidence字串由已保存kind/id/event_id确定性生成，不接受额外外部输入。完整原投影仍计入row SHA，但摘要不用于恢复关联值。不输出任意SQL或完整notes/原文作指令。

resolution为dataclasses的完整存储字段：ArticleEntity全部原字段（不保存as_dict派生matched_span/primary_external_horse_id），ResolvedTerm全部原字段（含priority/notes），ArticleEntityResolution精确 `source_language,entities,suppressed_candidates,accepted_terms,machine_horse_tags`。decoder仅原生builtin精确类型/有限list/深度，不允许自定义对象；用验证后的kwargs还原原dataclass，拒绝未知键/重复ID/坏时间/hash。实体term_id必须存在inputs.term；匹配field/span必须落在本次完整可见title/body范围且matched_text相符；external ID必须属于inputs.external_alias保存值；结构race_runner/race_result证据必须精确匹配inputs同kind/id/event_id，且该项article_id等于外层article_id、horse_name_key匹配对应实体的原normalized span key。alias.term_id必须在捕获term集合（原query未采纳的alias引用可保留但不赋予实体许可；此类引用若不在term集合仅作为未采纳输入，不进入entity/accepted映射）。无词典匹配是合法空候选。candidate/classification/confidence照原语义，不能从term_id推出已核身份。

关联字段类型：id/term_id/event_id/article_id为原生正int64；external_horse_id为非空str≤32字符/128UTF8bytes，horse_name_key为非空str≤255字符/1024UTF8bytes；公共updated_at为有时区DB时间（可以早于读取区间，不误要求落在区间），读取两时刻有时区且started≤finished；row_sha256严格64位lowerhex。不同external行可共享同一external_horse_id，不把其当全局唯一；(kind,id)才是唯一键。decoder重新计算结构token、核ID集合和关联字段，不额外查External/Term/Alias/Runner/Result/ArticleRaceLink。所有新增值参与原8192总bytes限制，溢出整次拒绝，不增额度。

完整span输入明确来自**原live source fence核验的Article**：锁序中取得已加载完整title_ja、所选body_ja_normalized/body_ja_raw、source_language/source_site/source_article_id，translation_input_sha256与snapshot.input_sha256相等；将这些字段组成临时只读source view传入v3 decoder。所有v3 decode调用点（step完成/重放、read-reference、provenance/checkpoint/final）必须显式传入该view，不得用256字符excerpt、临时词典查询或仅canonical摘要替代。只依赖已有Article查询/字段；若缺字段或仍deferred则拒绝，不能触发lazy SELECT补全。live fence下完成纯codec/span检查，之后原provider admission仍复验源/授权/期限。英文使用**原terms.visible_source_parts/clean_visible_source_text**同一规则去script/style/nav/aside、strip_tags、折叠空白；span检查针对这个可见文本，不针对HTML原字节。日文/其他语言保持原title/body语义。decoder不重跑resolver或材料查询，完整正文不另存入8192结果。

inputs是本次捕获材料摘要加上述最小关联值，禁止把其SHA解释为数据库外部签名或全库防篡改认证；实际生产者是封闭reader/原permit，外部调用不能注入result。单改entity ID/step/hash/版本须拒绝；恶意同时改数据库全部权威记录不在现有可信数据库合同内，不新增proof平台解决。

## 有界查询与原算法复用

已核 `terms.py:343–460,1510–1599`：keys按语言生成→active TermAlias匹配→TermEntry直接/alias-term匹配→ExternalHorseAlias匹配；英文还查询关联runner/result。原排序及消歧依赖notes、translation_status、JSON别名、external confidence，不能只读term名称后声称等价。

新调用增私有有界加载路径，普通原API默认不变。复用原keys生成的语义，提取可逐个yield的候选生成器供旧set及新有限收集共用；原候选内容、NFKC/casefold/变体不改。对新路径在yield第129个不同raw key或第257个不同query variant时拒绝，不先生成全部set后截断；非日英分支同样逐项限额。最多raw128/query256；每key至多255字符/1024 UTF8 bytes，拒绝超限。无匹配keys时不查词典。

SQL每类使用原filters/order_by再LIMIT N+1：TermAlias128；TermEntry64；ExternalHorseAlias64；英文runner128及result128。保留原ORDER BY并追加pk作完全相同键的稳定tie-break；完整未溢出的候选仍送原resolver，不截掉竞争候选。Article关联过滤沿原AUTO/MANUAL且removed_at=NULL；rows DISTINCT沿原；不主动增加public/verified资格。不执行全表list或all_source_terms的lazy关联查询。

Article title/body SQL sentinel仍65537字符，实际新v3标题≤1024 UTF8 bytes、正文≤8192 UTF8 bytes、两者≤8192字符且合计≤9216 bytes；按完整body_field取值判定，任一超限拒绝。旧v1/v2原65536边界不变。publication原4096 bytes保持。SQL只values所需标量，所有文本Substr到各上限字符+1，再核UTF8 bytes：名称/target/alias/name/normalized字段255字符及1024bytes；notes4096字符及4096bytes；JSON aliases_ja/zh各Cast→Substr4097字符，≤4096UTF8bytes后严格解码原生字符串list≤32项，每项≤255字符/1024bytes。notes不能截断后继续，否则非马标记会漂移。

TermEntry投影：id/updated_at/is_active/term_type/source_language/source_ja/target_zh/translation_status/race_grade/priority/notes/aliases_ja/aliases_zh；aliases先按原数据库text匹配，投影id/updated_at/term_id/source_language/alias_type/text；external投影id/updated_at/source/source_language/external_horse_id/name_ja/name_en/normalized_name/confidence/last_seen_at（不follow horse FK）；runner/result投影id/updated_at/event_id/article_link article_id/horse_name。标量优先级/置信度合法范围沿现模型/原语义，不重定身份规则。

最多6个材料SELECT（Article、alias、term、external、runner、result），不含原permit/账本/finish查询；非英文最多4。每类N+1只为检测超限，丢弃整结果、停止后续查询，不把已读前N条当有效候选。输入总投影canonical≤512KiB；最终resolution entities/suppressed/accepted各≤32，tags≤12；精确canonical外层result仍≤8192 UTF8 bytes（不提高旧RESULT_MAX_BYTES）。这与下述resolver内部硬界是两套限制；返回后检查33只落实最终限制，不能代替内部收集预算。否则 `read_terms_limit`；类型/结构错 `read_terms_invalid`。保留已提交slot/inflight，未知执行按原unknown路径，不退款/重读/启动provider。较小8192结果可合法拒绝密集文章，这是私有新版本的覆盖界限，不能宣称全语料支持。

预加载值对象必须具备原TermEntry访问的all_japanese_terms/has_translation语义；无lazy ORM属性。原纯resolver及英文可见正文清理、非马notes、unknown/ambiguous分类、冲突抑制、排序与accepted_terms不改。对全部未越界fixture，新加载器结果逐字段等于原resolver；无法做到等价即原R finding/停实施，不另造算法绕过。

## R02：仅v3的resolver中间累计预算

原API新可选私有`capture_budget=None`，只v3传本调用局部计数器；所有原正常入口默认None。同一预算对象沿resolve_article_entities→日/英/其他resolver→_make_entity→_accepted_terms_from_entities传递，不用全局状态。必须在增长**之前**计量，超限抛read_terms_limit、丢弃整结果；不吞异常/不返回前N项/不进入fallback。具体新私有覆盖硬界：

- 创建实体/抑制/candidate对象累计≤256个，总实体payload累计≤128KiB；每次_make_entity生成时先按实际标量与可迭代附加字段累计核bytes，再构造对象。所有对象均计，包括后来抑制、归并或丢弃的对象；不退款。accepted ResolvedTerm构造也计入这个对象总数/bytes，不以最终accepted32代替中间界。
- 所有中间集合插入/引用追加累计≤1024次，结构payload累计≤128KiB（以被插入值的canonical builtin bytes计，重复引用亦计；全对象列表迁移会重复计量），覆盖dict新键/set新增、索引候选列表、保护span、按span分组、accepted_for_field、merged_ambiguous、entities/suppressed追加/extend、accepted_terms/tags追加。
- external_horse_ids/evidence/entity_evidence/conflict_flags所有追加或归并输入累计≤1024个字符串项及≤128KiB；每对象每此类list≤64项，每字符串≤1024UTF8bytes。从generator逐项charge再追加，dict.fromkeys去重也先charge每个输入；不先造大list/comprehension再检查。合并重赋值和entity_evidence=list(primary.evidence)的复制也计量，不退款。三类byte账总累计≤256KiB，任一分账或总账先到界都拒绝，byte定义为`json.dumps(...ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()`的长度，不作内存大小声明。

覆盖点表（固定terms.py旧行号用于实施核对）：

| 阶段 | 必须收费的增长点 |
|---|---|
| _make_entity:677–714 | 实体标量和四类附加list；输入iterables逐项，创建前预算；不能构造后才计 |
| 英文:782–1018 | 每次entities/suppressed.append；991–995既有实体附加外部ID/evidence，所有推导证据/冲突list |
| 英文归并:1020–1092 | span分组、targets/term_ids集合、ambiguous_members、merged列表；1048–1078所有ID/evidence/conflict的生成/去重/重赋值、entity_evidence复制；最终filter/extend逐项迁移收费 |
| 日文:1107–1367 | horse/all-term/aliases_by_name索引、每出现的实体/抑制、protected_spans、person_alias_owners；1284外部ID列表必须generator逐项；每append/extend收费 |
| 其他:1379–1432 | 每匹配candidates.append、accepted_for_field、suppressed追加、conflict_flags追加、entities.extend；sorting只使用已限额列表 |
| 收尾:1437–1501 | entries_by_id/seen新增、accepted ResolvedTerm构造/追加、tags去重/追加、最终排序前列表已受预算；既有tags[:12]语义保留，不能先造无限tags |

输入index/预加载结构集合仍受SQL/key/512KiB旧限额；其中列表构建亦使用1024集合插入预算，不允许通过独立预加载漏计。纯只读推导列表/comprehension若在上述链内增长，同样改为预算逐项收集；不是仅搜索append文本。实施按上表和原语言分支做逐项审查，默认None逐字段保持原结果，不为限制改变原匹配/消歧顺序。

256中间对象≠最终32。例如40个同span竞争对象可能归并成1，不能第33个中间对象按最终超限早拒绝；它们完整参与原归并，直到独立256硬界才拒绝。第257个中间对象即使预计最后归并成1仍整次拒绝，这是明确的新私有覆盖限制。任何预算拒绝沿原已占slot/inflight→unknown、不provider、不退款、不重读。

## 快照、撤销与权限

材料是多次autocommit SELECT的有限捕获，read_started_at/read_finished_at是区间，行updated_at为DB记录，不承诺跨表同一原子时点。raw row摘要/完整resolution冻结；词典修改/is_active变更后免费重投仍消费当次候选快照，不称“当前词典有效”或身份许可。grant撤销/permission epoch/源SHA或版本变更/截止则沿原live fence拒绝即使缓存存在，不能把字典变更与授权撤销混为一谈。新源文本必须新claim，不刷新旧step。词典标记is_active仅首次查询候选资格，不是用户权限撤销机制。

## 文件及真实依赖

仅steps/consumer、新窄article_term_receipt.py、terms必要有界loader/生成器共用及上述现有测试模块（terms直接回归按影响），不动models/migration/生产tasks/权限/预算/全局settings。新路径high-risk映射按现政策保留，不写通用runner。源/plan/progress/checkpoint对v3 exact schema同步；具体RED见test_cases。

方案/RED源码/实现不等生产样本或付费模型；provider只用已有离线SDK脚本。完整step→consumer现有reader调用pg_backend_pid且锁合同依赖PG，不能说SQLite覆盖它；SQLite仅新纯codec及有界材料ORM helper，完整RED由ROOT分配原隔离PG后运行。原35/相关预算、terms、v1/v2回归及正式CI仍需，不降低门槛。此限定无新的产品身份/预算分支；若需要扩大输出/轮次/身份认定，停止返ROOT。

## artifact/恢复承载及本次修订

本design承载本片spec（新schema/预算/范围）及rollout限制，本tasks承载实施顺序；按小切片约定不新增独立spec/rollout文件或发布流程。开发中止/代码回滚到只支持v2时，已登记v3对象必须因未知版本fail closed，保留已占账/材料审计，不升降级/转普通provider/重新发起；不得删旧root后“恢复”。此处不是生产回滚授权。

B105-R01/R02技术修订仅本三文档，依赖源码仍047e，父方案b0705f4d及原R da75559a/report d432e800保留；修改待同原R窄复审，不自行声称finding关闭或RED已执行。
