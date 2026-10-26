# B016 摘要域、foundation FD 终态与候选输入映射窄修

任务 B016-WIRE-V3-DIGEST-FD-PLAN-REPAIR-001；基线656e5f3865fddbb1932a98239b960f4314e59051。原R d108fa7896ae607599572ae4ceea29bec33e4bc5 的 R02/R04/R05 本轮返修，交同原R窄复审；作者不提前关闭 finding。R01全状态费用上界、R03 source/auth/独立clock/AS-time仍未闭合，整体 REVISE / NOT_ADOPTABLE。现1MiB有效、candidate_enabled=false、2MiB未生效；六cap、资源/时间和逻辑分母不变。旧v12所有文件冻结。本轮仅B自有新报告和v13有限字节/算术原件，无parser/helper/43tests/native/OS/FD/container/network/协议执行。

## R04：单一无环摘要域

本节替代C21对 body_sha/完整body digest的不精确措辞，其余C21保持。使用标准SHA256对下面精确串求摘要；domain label作为代码中的常量前缀参与hash，不另加wire字段或收费。没有算法选择分支。

1. 每item摘要 `item_sha = SHA256(body)`，body是现有完整原始/canonical对象精确bytes，不带domain label、category或分隔符。header item也同规则，对完整canonical header body求摘要。
2. header.body_sha唯一为 `SHA256(b"B016-WIRE-V3-PAYLOAD-SHA256\x00" + payload_bytes)`。payload_bytes是下面所有P/A/F/I/R item的完整文本prefix+body+尾LF精确串接，排除magic、整个H item、后产authentication与接收clock载体。不是对象SHA集合、decodedJSON或裸body相加。
3. 后产返回绑定的final_wire_sha唯一为 `SHA256(b"B016-WIRE-V3-FINAL-SHA256\x00" + core_wire_bytes)`，core_wire_bytes恰为magic+完整H item+payload_bytes。包含magic、header prefix/body/LF及每payload item prefix/body/LF；排除后产authentication、接收clock、任何携带该final_wire_sha的后产载体。final_wire_sha不放入H、Index或Receipt，避免自含。受信后产载体必须同时绑定此摘要、header.body_sha和上下文；真实性仍属R03缺口，hash不授认证。
4. Input/Receipt的旧bundle_sha继续指原固定bundle对象域，既有计算/校验不变；既有Index、Receipt、final_event的SHA各保持原对象算法，不得用上述domain摘要互换。header内index_sha/receipt_sha/final_event_sha是其既有完整对象摘要；manifest/input规则不变。

magic固定13 bytes `B016-WIRE-V3\n`。每item的精确文本编码 `category[1 ASCII byte] || decimal_len[7 ASCII digits, zero-padded] || item_sha[64 lowercase hex ASCII] || LF || body[decimal_len bytes] || LF`；额外74 bytes。非ASCII category、大小写SHA变体、变宽数字、CRLF、错length/SHA、缺尾LF和多余尾bytes均拒绝，不canonical化修复。长度上界沿各类别/单件更严者；空body按原对象合法性拒绝，不因framing能表示而新开放。

唯一顺序为H、P(Intent、Input恰两件)、A、F、I、R：A恰完整provided pool，包括scope/Registry/chunks和业务原件，按完整item_sha小写ASCII升序、同SHA仅一件；同SHA不同body或不同重复条目拒绝。F先cap链，严格原cap链帧序（不得按SHA重排），后case链，严格seq序；具体cap/index引用和case seq/prev沿原规则核对。I和R各恰1且I在R前。P角色靠位置及固定schema辨认；I/R不能挪入A。H item_counts/category_bytes从这些实际item body核算；它们是final core计数，不是假称全session发送次数。改变有序数组或对象canonical bytes影响其SHA，不能排序后悄悄恢复。

构造先后：冻结preparedP及早产sources → 完整A/F → Index → Receipt → 排好payload items并求payload domain SHA → header canonical bytes和H item SHA → core_wire及final domain SHA → 独立接收观察/受信authentication。header不影响payload SHA；payload影响header.body_sha并经H传到final SHA；后产carrier不影响二者。这只是静态构造顺序，不是本轮协议执行或时间资格。

此profile选择精确文本core直接传输，不允许额外JSON包裹、转义、hex/base64或压缩。若实际transport需要额外编码，本profile拒绝，交ROOT明确版本/收费设计，不自动实现替代。transport已有不可见overhead或后产carrier的真实bytes仍计E；未取得实际上界保持unknown。若将来另行选定extra编码，必须明确final digest是否覆盖其实际bytes并做版本拒绝，不能沿本版本暗换域。

所有真实重复发送照实收费：每次发送的body归其A/F/I/R/P，prefix/分隔/header/transport额外归E。preparedP若此前发过一次，再放入final core要计P两次、两套prefix计E；没有基于同SHA或“准备阶段”的免计。会话分类账是实际所有传输收费，final core header只是一个core的计数；外部可信transmission ledger缺失时不能宣称完整费用资格。协议不增加wire字段来伪造该来源。内部重发若改变合法item数量/顺序则拒绝；外部重试/重复送达按实际收费，不能用TCP/应用层重试词汇掩盖。当前四场景旧账仅一次对象量，未产生真实transport ledger，不改成已证收费上界。

有限vectors.json为小字节串的hash域向量，body是演示JSON，不是合法Input/Index/Receipt或source。记录完整hex、item/body/payload/header/final SHA与变异；没有运行parser。预期：仅header字段变更或magic变更，payload SHA不变、final SHA变；payload body/prefix/排序/截断变化，两domain SHA都变（SHA碰撞不纳入测试假设）；header prefix变更只变final；后产auth/clock变化不改变这两摘要，其真实性/收费另核。变异只是hash敏感性检查，不将非法frame当合法packet。完整收费仍R01，carrier真实性仍R03。

## R02：局部引用和FD真值表

保持C21唯一exact五字段 `{kind,scope_sha,record_index,raw_sha,action}`，kind=foundation_fd，action=allocate/close，仅N0 foundation_temporary槽两ref字段。object="none"，无新增state/pending/error字段；close_ref仍nullable。引用先解析到已收齐Index中的earlier atomic acquisition/raw，再核同execution/scope/N0/实际FD/成功open生命周期。三种派生状态只在验证器分析中使用，不写入Receipt字段：closed、not_proved_closed、no_known_allocation。close_ref存在只表示一次可定位尝试。

将结构/绑定是否有效与source资格分开：完整一致open raw报告rc=FD≥0、errno_number=0且errno_name=none，才允许建立对应数字槽allocation_ref；source未合格也保留这份reported allocation账，但不证明真实分配或关闭。open rc=-1及一致非零errno是失败，不能凭空建立FD槽；失败raw必须由Index/Registry保留。成功返回伴非零/未知errno、失败返回伴零errno、FD越界、未知primitive或目标/引用错绑定是矛盾/非法输入，拒绝。open结果缺失或无法归一而无确定FD时不造数字槽，保留已有raw/prefix并报告unknown；当前raw无法编码的unknown不得新增自由字段或合成原件，标实例缺件，仍属R01/R03。

| open raw/来源 | close raw/来源 | slot/ref表达 | FD派生与Receipt允许组合 |
|---|---|---|---|
| 一致成功且来源合格 | 同FD一致rc=0/errno=none,0且来源合格 | allocation_ref有效；close_ref有效 | closed；仅此行允许foundation关闭证明；不单独授全Receipt proved |
| 一致成功且来源合格 | 无close采集/未产出/未收到 | 保留slot、allocation_ref；close_ref=null | not_proved_closed；supervision=unknown、expected_fault_verified=false；无其它错误时error_code=cleanup |
| 一致成功且来源合格 | 同FD rc=-1及一致非零errno且来源合格 | 保留slot与失败close_ref | not_proved_closed；supervision=unknown、expected_fault_verified=false；无其它错误时error_code=fd |
| 一致成功且来源合格 | close rc非0但不是合法-1/errno对，或rc=0带非零errno | 不把坏ref改null绕过矛盾 | REJECT，无合法终态组合 |
| 一致成功且来源合格 | close报告成功但errno/source资格unknown | 结构合法且可定位原件时保留close_ref；否则未定位close_ref=null且缺件保持 | not_proved_closed；supervision=unknown、expected_fault_verified=false；无其它错误时error_code=source；若原raw不允许unknown errno则拒绝该raw形状，不制造编码 |
| 一致成功但open来源未合格 | 任意结构一致close或缺失 | 保留已知reportedFD slot与allocation_ref；有合法原件则保留close_ref | not_proved_closed；supervision=unknown、expected_fault_verified=false；error_code按已记录原因，默认source；close合格也不能补open来源 |
| 一致失败open且来源合格 | 无close | 无新FD slot，失败open raw留Index | no_known_allocation；supervision=blocked、expected_fault_verified=false；无其它错误时error_code=fd，不能继续按九次成功init执行 |
| 一致失败open | 试图声称对应FD有close或构造slot | 无成功分配可绑定，不能借他scope/FD | REJECT；失败raw保留不产生Handle权限 |
| open返回缺失/unknown且无确定FD | 缺失或不能匹配close | 不虚构allocation_ref/数字FD；已有slot不删除 | no_known_allocation且实例不完整；supervision=unknown、expected_fault_verified=false；默认source；不得proved |
| 任意open | close_ref跨scope/execution、future/derive代atomic、不同FD、错SHA/primitive | 不删失败原件、不换later consumer | REJECT |

“errno unknown”指不能取得有效的零/非零绑定证据或其来源资格，不把未知等同零。原canonical raw严格字段/有限enum未开放的值继续拒绝；没有本轮合成unknown raw实例。成功close按实际返回证明当次关闭；失败可能已在内核造成关闭也不能据此推断，禁止对不确定FD盲目重试或复用数字槽。后续若有另一合法close尝试，以实际顺序和同生命周期来源明确最后close_ref并保留所有 earlier尝试 raw；不能overwrite未消费证据，费用/work计入，当前未生成这种完整实例。

cleanup原四字段 registered_count/reaped_count/remaining_roles/late继续只描述managed进程角色，不把N0 foundation FD数塞registered/reaped、不给remaining_roles添加N0或新角色。reaped≤registered、原角色枚举及late实际时间语义不变。即使cleanup=(全部reaped,remaining_roles=[],late=false)，任何known foundation FD not_proved_closed仍使完整Receipt不能proved，也不能expected_fault_verified=true。late只据原deadline，失败FD不自动设置late=true；late=true和剩余进程按原终态规则继续阻止proved。来源合格且全部known foundation关闭只是必要条件，旧对象/wait/absence/clock/cleanup证明仍全要。preflight_status=unknown、execution_authorized=false、native_preflight_ready=false继续恒定；当前R03未闭合，所以没有允许真实全Receipt proved的资格实例。

错误组合保留已存在独立业务失败及其真实原件：如果error_code不是none且由既有失败真实支持，保留它，不用本表默认值覆盖；此时仍须用所有source/FD raw推导未知关闭并禁止proved。没有其它失败时按表默认赋fd/cleanup/source；不得error_code=none同时宣称无FD缺口。被原输入/能力/身份失败先阻断的blocked结果，可保留此前known slot和真实失败close，不能因blocked删账；没有先置blocked原因则本表open已成功的关闭不确定行只能unknown。pre-init open失败阻断后必须停止后续本链采集/构造，不能拿预期故障业务case给foundation失败背书。

九个已知v10成功open槽都保留并占原2048槽总数；其已known的unknown/失败close不能删槽，数字不复用。未来partial-init失败没有返回真实FD的尝试无槽、raw照保留；不能为了凑九槽制造negativeFD或虚假open，也不能把“无新槽”解释为旧九账可删。全部2048、FD≤2^31-1、decimal键限制、kind/Role/Operation/HandleRef union及原分母保持。此真值表补语义，有限全状态raw/Receipt实例与全费用上界仍没有产生。

## R05：B owned候选输入映射与ROOT最小回写清单

这是五份总artifact的候选补充输入索引，不修改它们，也不复制全文；目前总文档还未接受本候选，不能说已有实施范围批准。唯一行为门禁引用根[AGENTS.md](../../../../../AGENTS.md)，本表不增门禁。旧PLAN/ledger/matrix/qualification都指冻结v12 continuation-002；本窄修报告及v13向量补足R02/R04语义。

| 正式输入 | 当前已有入口与本候选映射 | ROOT最小必要回写（尚未执行） |
|---|---|---|
| [spec](../../spec.md) §2范围、§5验收、§8接手 | C21 PLAN §1/§6，ledger；本报告状态及R01/R03缺口 | 链接本候选，明确只是禁用静态输入、不是2MiB采纳或新增产品范围 |
| [design](../../design.md) §8 GPT复杂自动化 | C21 §2–5；本报告R02/R04，fd-reference/matrix/qualification | 链接唯一hash域/局部ref及未闭合资格，不粘贴另一个规范版本 |
| [test_cases](../../test_cases.md) §1证据、§2合同、§3分母 | v13 vectors/truth-table，C21拒绝matrix与§6 RED | 列mutation编号和预期拒绝/摘要关系，区分静态向量、RED未来执行及来源资格 |
| [tasks](../../tasks.md) F02(integration) 与测试→实现→验证 | 下述有序待实施清单与C21 §6 | 追加本候选依赖/blocked状态和固定checkpoint链接，不把F02整卡标完成 |
| [rollout](../../rollout.md) §2包、§5中止、§6交接 | candidate-disabled、现legacy保持；下述恢复handoff | 明确无发布包/迁移/资源分配，停止及恢复选择旧profile，不把静态review当执行授权 |

待实施清单保持任务前缀及顺序：(integration) 测试：同R窄复审、先RED边界/FD失败/费用/前解析峰值；(integration) 实现：只有新批明确范围后才最小profile/ref/有界解析及完整I/R/E，R01/R03缺口先作为阻塞；(operations) 验证：另行固定SHA/资源/受信source/clock资格包，原资源不增；(integration) 验证：同R实现及全状态证据复审；(operations) 交接：ROOT决定采纳与实际交付。前步失败停在精确checkpoint，不跳过或自动分配下一阶段。

mutations：DG01 header字段；DG02 magic；DG03 payload prefix（category/length/SHA/LF各变）；DG04 A排序/F链序/P双件顺序；DG05 payload body；DG06末尾截断/余byte；DG07 header prefix；DG08后产auth/clock变动；DG09旧bundle_sha和新域混用；FD01失败open造slot；FD02close缺失；FD03close失败ref非null假closed；FD04errno/source unknown假零；FD05跨scope/execution/FD；FD06partial init删除known槽；FD07cleanup empty冒充FDclosed；FD08失败后仍继续初始化；原cap/时间/node/work/全状态收费RED由原matrix继承。DG向量只算hash关系，合法性拒绝和FD RED都未来执行，不写测试已通过。

安全检查点必须保存固定commit、方向与输入SHA、输出index、六类实际/unknown、candidate_enabled=false、现legacy profile、保护SHA、停止原因和未完项；额度57或全局≤1先到即停，不自动续。类别超限、版本/哈希/FD矛盾、AS/time/source资格失败亦停，不能更换边界继续。

恢复/handoff：读取本报告→v13 index/vector/truth-table→冻结v12 PLAN/ledger/matrix/qualification→同R反馈；核fixed SHA与真实配置candidate-disabled。在尚未执行profile情况下“恢复”只是继续选择现legacy-1MiB，无数据/服务/队列动作、无迁移、无profile启动/重启命令。若未来包曾启candidate，恢复方案须该未来包明确旧profile选择及其实际验证，不能本轮宣称已演练。交接给ROOT→同原R，并逐项区分本窄修已写、R复审待定、R01/R03仍缺；旧v12及保护文件不改。


## 本续批有限静态证据

本批新原件在 `/Users/mentianlu/.codex/runtime/b016-native-pure-contract-v1/wire-v3-digest-fd-plan-repair-v13/continuation-002/`：generate_vectors.py仅stdlib/hash/canonical及有限bytes算术；vectors.json为15种mutation/31条摘要关系断言，toy core1671bytes、header850bytes。truth-table.json对应上表十行及守卫；input-mapping.json为五总artifact的B owned待ROOT回写输入。这些不是合法包、FD/provider返回事实、parser RED/GREEN或运行资格。旧v13 checkpoint冻结，R02/R04/R05窄复审待原R；R01/R03仍未闭合。
