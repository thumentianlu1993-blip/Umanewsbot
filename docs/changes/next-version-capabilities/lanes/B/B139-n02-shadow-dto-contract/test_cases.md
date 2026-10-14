# B139 test_cases：现有 draft shadow 接缝入口冻结

2026-10-14，全部 **PLANNED / NOT RUN**；无测试源码、功能源码或RED/GREEN证据。依 [contract.md](contract.md) 的字段/copy预算/首因/envelope定义，基线准确为d065b62efde24821f7f3501ef4d279ea5df456c1。B138方案获原R批准不等于本完整测试入口已确认。逐例列mutation；不复制23个内核测试，不用mock调用次数代替实际候选/失败语义。

## 固定 fixture 与真实 RED 控制

未来 `stable.test_content_review_shadow` 使用unittest.TestCase、现成 `/Users/mentianlu/Code/umanews/.venv/bin/python`，只用既有B135最小Django装载wrapper（`/Users/mentianlu/.codex/runtime/b135-n02-candidate-decisions-tdd-001/run-tests.py`），不新runner/框架/安装；配置models app仅支持枚举import，DB.ensure_connection与socket.socket.connect从django.setup前到整个suite末均拒绝。不能跑manage.py/app suite、DB/PG/Docker/VM。wrapper只用于本地有限证据，正式native/CI另交ROOT。

准备流程（不是本轮执行）：

1. 用原 `HorseRacingNationAdapter().parse_detail_html` 解析 `<div class="article-body"><p>Horse Aurora finished second at Kyoto.</p><p>Explore the members archive on our companion portal.</p><p>The rider confirmed the next race is on Saturday.</p></div>`；URL固定`https://fixture.invalid/b139`。raw三段来自真实N01输出，不能手造trace。原 `normalize_source_payload` 接一个普通构造的 SourceArticleStub（明确TEST_ONLY固定source ID/source mode/固定带时区发布时间/同URL）得到actual CanonicalNewsDraft。
2. 控制断言：status ok，完整trace存在，恰好A/B/C三eligible、均非空kept，IDs唯一，after_text==draft.raw，normalized一致；输入candidate控制是normalize_whitespace(A+B+C)。若任何control不成立，停并修fixture/环境，不称业务RED。
3. 从actual draft具名投影exact builtin snapshot，包括枚举在owner侧转str/None；禁止把dataclass直接交adapter。独立TEST_ONLY caller_context.expected逐字段绑定fixture/site/id/url/containerSHA，capture_ref=`TEST_ONLY:B139:capture:1`，policy_ref=`TEST_ONLY:B139:shadow-v1`，protection显式unknown/ref=None/ids=[]，template显式unknown/ref=None/version=None。expected在fixture准备时冻结，不在变异测试后重造。
4. kernel profile仅测试显式常量：id=`TEST_ONLY:B139:profile`、purpose=TEST_ONLY、site=horse_racing_nation、policy_ref如上；limits.packet_bytes=32768/verdict_bytes=16384/result_bytes=32768/blocks=64/field_bytes=8192/reason_bytes=1024/quote_bytes=8192/depth=12。这些只控制合成fixture，不是生产profile或业务阈值。copy_limits仅测试显式常量：input_bytes=131072/output_bytes=131072/field_bytes=32768/container_items=256/nodes=8192/depth=20。任何真实调用者必须独立明确技术参数，不能隐式使用测试常量。
5. 测试按合同字段构造expected kernel packet，用公开kernel.input_digest算一次同profile摘要；available verdict完整覆盖三个eligible IDs，keep A/delete B/keep C，证据使用各post-N01全文Unicodecodepoint范围与quote，reason标TEST_ONLY。不mock内核；expected candidate=A+C、单条B diff、manual、quality gaps和两flagfalse是oracle，不从adapter返回值生成预期。

首个负载测试必须先 `assertIsInstance(envelope['review'], dict)` 再访问review字段，no-op返回review=None产生明确AssertionFailure，不让None下标导致TypeError假RED。入口批准后先写该测试/fixture，再准备可调用最小no-op同签名stub仅返回 `{adapter_gaps:[],review:None}`（只为有效导入且没有功能），运行S01取得实际业务FAIL/0ERROR并封存命令、exit、stub/tests/控制断言和日志；然后才最小GREEN。若stub意外通过，增强目标断言，不伪报RED。

未来最小命令（本轮未运行）：在固定独立实现worktree，`/Users/mentianlu/Code/umanews/.venv/bin/python /Users/mentianlu/.codex/runtime/b135-n02-candidate-decisions-tdd-001/run-tests.py stable.test_content_review_shadow.ContentReviewShadowTests.test_actual_draft_candidate_manual_and_diff`。源码位置在本worktree，sys.path沿已有wrapper的server相对路径；wrapper固定原blob另存证据，不依赖可变化main。无输出捕获截断、无测试执行偷跑。

## 核心正常、失败及来源边界

| ID / 拟测试方法 | 输入变化及断言 | 应捕获的具体 mutation |
| --- | --- | --- |
| S01 test_actual_draft_candidate_manual_and_diff | 原parser+normalizer fixture，unknown protection、删B；review是dict、needs_manual_review、candidate=A+C、B精确diff/quote、完整digest相符、quality gaps含unknown/template/test-only、两flag恒False；adapter_gaps=[] | no-op、不调用kernel、返回旧A+B+C、误删C、unknown升级valid/qualified、伪diff |
| S02 test_keep_all_and_repeat_are_candidate_only | 同实际fixture keepall、显式known TEST_ONLY保护空表/ref，结果全文且candidate_valid、两flagfalse；同输入两次deep-equal但可变输出互不共享 | keepall当publish合格、缓存同一可变结果、重复调用修改原trace |
| S03 test_snapshot_exact_shape_and_no_coercion | snapshot/metadata缺每一必需key、额外html/body_excerpt/trusted字段、canonical非法类型、空selector/status非ok；逐subcase固定snapshot_shape_invalid/None，原件不变 | 忽略额外权限键、默认字段/selector、接受整个dataclass、str或getattr强制转换 |
| S04 test_discovered_site_not_canonical_ingest_site | 用原TDNFranceKeywordAdapter parser+normalizer的合成三段fixture（固定international.py:607，canonical_source_site=TDN），discovered=tdn_france、canonical=tdn；context/profile适用发现site，候选仍正确；仅canonical改变不更改kernel packet digest；discovered/source/expected任一不同则source_binding_mismatch/None | canonical替换site并重算IDs、忽略discovered mismatch、canonical字段造授权 |
| S05 test_source_identity_and_url_against_independent_expected | 分别改snapshot.source_article_id/source_url/metadata.source_url/expected.site/id/url，其他字段合法；对于source_article_id变异可重算其结构仍合法的kernel包verdict，仍须source_binding_mismatch/None；site等破坏内核ID绑定者沿用原verdict，不把input_digest的setup异常当RED；expected不得跟变异重造 | 从snapshot重造expected、只比正文hash、忽略URL/ID、用新digest掩盖来源错配 |
| S06 test_capture_context_missing_and_mismatched | 缺context/expected/capture_ref/policy_ref、ref空/None、expected缺SHA→context_shape_invalid/None；64hex但不是trace容器SHA→capture_binding_mismatch/None | URL/时钟/wholepagehash填capture、跳过expectedSHA、把模型trusted当context |
| S07 test_body_and_trace_binding_without_reparse | 分别改raw/normalized/trace.after_text或移除trace；完整独立expected保持；body不一致→body_binding_mismatch，trace缺→snapshot_shape_invalid；确认adapter没有parser调用 | fallback旧raw、normalize后忽略原全文差异、由HTML重parse补trace、256字excerpt替代全文 |
| S08 test_full_trace_passed_without_filter_or_rebuild | trace额外key、缺block、block重排/重复ID；必要时修改raw/normalized为该trace.after_text使adapterbody绑定可过，沿用原合法verdict；不对已损坏trace调用input_digest以免setup ERROR；原kernel必须blocked，无partial candidate，原trace保持所有原数据 | adapter过滤extra/key补缺、丢removed块、重新编ID/排序让内核看不见漂移；仅作少量透传反例 |
| S09 test_protection_unknown_known_and_context_omission | unknown合法→manual；省protection/context key→adapter None；known TEST_ONLY明确保护B而deleteB→kernel protected_block_delete、无candidate/diff；人工字段锁不在DTO/不推保护 | 缺保护默选known空表、把protected delete当manual部分通过、仅依manually_edited_fields |
| S10 test_attempt_unavailable_refused_timeout_invalid | 四attempt逐项，普通有界verdict=None，返回核review_blocked/model对应码、candidate=None/diff=[]/flagsFalse；repeat无重试；未知exactstr状态按kernel attempt_invalid | 缺verdict自动keepall、unavailable退N01、将timeout重跑SDK、未知状态当available |
| S11 test_missing_profile_and_stale_verdict | 显式profile=None→kernel profile_missing；合法snapshot下旧input_digest/改profile适用性→原核blocked；未换digest或扩profile不自动修旧verdict | 默认测试profile、重签旧verdict.digest、忽略site/policy绑定 |
| S12 test_kernel_unexpected_error_not_fake_success | 仅此异常传播边界用stub kernel公开review_candidate抛RuntimeError，要求异常不被伪装成功候选；无输入写入；不捕获KeyboardInterrupt/SystemExit | catch-all把缺陷藏成success/keepall、捕获BaseException、失败写metadata |

S04 已按固定 international.py 核对 TDNFranceKeywordAdapter 名字和 discovered/canonical字段，不调用任何fetch。fixture synthetic并非实网TDN/法国覆盖。S08–S11只是adapter透传责任，不完整重做kernel23例；kernel自身证据/Unicode/全块等算法在旧suite回归。

## 有界 copy 与输入输出隔离

预算oracle在测试源码中是**有限、已知builtin合法样本**用标准json.dumps(ensure_ascii=False,sort_keys=True,separators=(',',':'))测wire长度，不拿未知/巨大/custom/cycle对象先序列化；与adapter预检实现独立。root/key/重复出现的node/depth资源手算的小树用subcase验证；不要从被测私有函数取预期。

| ID / 拟测试方法 | 操作与预期 | 应捕获的 mutation |
| --- | --- | --- |
| C01 test_copy_limits_explicit_exact_support | None/漏一键/额外键/零负值/bool/float/int子类/超31bit/depth65/自定义key/value对象→copy_limits_invalid；spy custom hooks全未调用 | 默认caps、bool当int、先格式化/遍历custom配置、忽略额外字段 |
| C02 test_canonical_wire_input_exact_byte_boundary | 对S01完整合法逻辑envelope，input_bytes=N可通过，N−1→input_byte_limit；加UTF8多字节、quote/backslash/control的合法reason，分别测精确wire预算，field/rawbyte与wireescape区分 | 只计len字符串、ASCII假设、忽略外层keys/标点、<=写成<、忽略转义、超限截断 |
| C03 test_field_utf8_boundary_and_surrogate | 合法context ref或reason把单field原UTF8大小设M，M可过/M−1→input_field_limit；未配对surrogate拒绝input_type_invalid，不替换/NFC；预检优先于kernel | 码点当字节、先整体巨量encode、替换非法字符、unicode隐式归一化 |
| C04 test_container_and_node_budget_occurrences | 最小已知普通树插在允许payload路径用于generic preflight：container_items K/K−1边界；节点按key/value/virtualroot及重复共享出现累计，nodes N/N−1；必要时比gap而非expect最终candidate，因为后续schema可能拒绝 | 先list/sorted再限长、漏dictkeys节点、全局seen跳过第二次共享引用、只数唯一objects |
| C05 test_depth_boundary_and_cycle | root0、keys和值depth+1手算小树，depth D通过preflight（后续shape可blocked）、D−1固定input_depth_limit；list自环/dict自环/跨容器环→input_cycle/None；不递归到RecursionError | off-by-one、只限制list深度、缺祖先cycle检测、递归耗尽后才失败 |
| C06 test_exact_builtin_and_custom_hooks_never_called | 顶层及嵌套dict/list/str/int子类、Mapping、dataclass、Tag-shaped对象、bytes/tuple/set/float、有__deepcopy__/__iter__/__str__/__len__/encoder对象→input_type_invalid；恶意方法若被调用抛AssertionError，calls=[] | isinstance容忍子类、deepcopy/json.default/str/getattr钩子、在type前len/iter |
| C07 test_preflight_stops_before_oversized_tail | 合法builtinlist长度超过container cap，尾部放恶意对象，预期container_limit而非hook执行；单str超field长度早停；不接受partial副本或前几个decision | 先递归尾部才验总长、扫描完整大payload、截断list或quote成为有效输入 |
| C08 test_no_mutation_or_alias_after_input_and_output_changes | 保留actual draft与每输入deepcopy基线；调用后均deep-equal；随后改输入trace/reasons/context.protected_ids/profile.limits/verdict.evidence，旧review不变；再改review.diff/evidence/quality_gaps，输入/draft/第二次结果不变；shared无环子dict在副本不alias | 浅copy metadata/trace/verdict、直接透出kernel引用、缓存共享结果、冻结只顶层 |
| C09 test_output_wire_budget_and_fixed_error_exemption | 对S01输出测wire O，output_bytes=O通过/O−1→唯一output_copy_limit/None无candidate；另用有界普通kernel-return测试替身分别构造输出field/node/depth超限，任一同码（否则真实fixture输入资源可能先超限；不以替身证明kernel真实语义）；copy_limits.output_bytes=1仍能返回固定小型错误envelope且无用户原文 | kernel resultcap当全部envelopecap、先构造/截断输出、扩大error豁免到任意review/echo原文 |
| C10 test_input_and_kernel_caps_are_independent | adapter宽而kernel packet/verdict/result cap不够→原kernelblocked；kernel宽而adapter cap低→adaptergap/None；两边都不改caps、无truncate | 调高profile修adapter超限、以kernel验证替代复制前限额、结果静默截断 |
| C11 test_two_pass_copy_rechecks_supported_rules | 对exactbuiltin无环shared树、重复出现计资源，验证两遍各自检查；测试可通过受控局部preflight/复制之间的测试注入修改为超cap/非法类型，要求二遍blocked；不引入线程/锁或公开callback | 第二遍无检查/保留共享alias、首次通过后信任动态changed输入；只证明注入变化，不宣称原子并发安全 |

C11 注入仅测试内部边界，可patch新模块有限内部copy入口的受控测试替身以在进入二遍前改变原list；oracle是实际返回blocked和原件仅有测试预设改变，无hook/DB/线程。若最小实现没有合适隔离接缝，原R先确认更窄等价验证方式，不为测试新建公开callback或通用copy框架。普通调用者同步不并发修改输入是协议前提，两遍不能认证敌对并发快照。

## 回归、恢复和责任范围

| ID | 验证与mutation | 本轮状态 |
| --- | --- | --- |
| R01 | 完成新adapter必要用例后只跑新module、旧stable.test_content_review_decisions、stable.test_article_content_trace；原kernel/N01正文/diff/状态保持；mutation=改共享cleaner/kernel以凑adapter测试 | 未运行，不能继承旧35PASS为此片实现证据 |
| R02 | 静态检查新module无fetch/upsert/task/ORM/provider/storage/DB/runtime写/SDK调用边，动态suite guard拒绝DB/socket；可对危险函数装fail-on-call sentinel作防误调用断言，但主oracle仍candidate/blocked；mutation=悄接hook、保存metadata、图片下载 | 无新module，未来检查；sentinel本身不认证全产品零副作用 |
| R03 | 原draft/旧行为控制：离线调用不改变fields/metadata/status、不抛回真实crawl、不改变source counters；不执行crawl/upsert作所谓dry-run；mutation=把候选写draft让下一ingest落库 | 仅未来普通对象前后比较；不测试真实DB行为 |
| R04 | missing/corrupt/timeout/部分decision/输出超限无partial/no旧bodyfallback；合法重复调用结果可再生不持久、无retry/cost/issuer声明；mutation=错误成功、自动恢复/SDK重试 | covered S07–S12/C09；无新恢复runner |

模型约束/查询/迁移：N/A，无模型/DB更改且guard覆盖禁止查询。Celery投递/lease/锁/worker恢复：N/A，无Celery入口或hook，不模拟一个不存在的worker。部署/回滚兼容：N/A，本片route-less且无部署；局部候选还需代码审和ROOT登记/集成，不能据本文称真实任务接入可上线。批次/性能：同步有界copy支持caps是拒绝边界，不能给实际吞吐/延迟SLA；不做大数据benchmark，不新增批处理/并发器。源码静态修改限定拟两个文件，catalog/rules另交ROOT。

## 执行顺序与停止条件

原R冻结入口确认 → 写S01与fixture/guards → control正常 → no-op功能FAIL/0ERROR真实RED → 最小S01 GREEN → 按功能一例/一组推进source/context/body与caps/alias必要RED-GREEN → R01相关纯回归 → 原R代码复审 → ROOT后续集成。不得先完成整adapter再一次性补tests。每次证据附case ID/mutation、固定受测SHA/tree、完整命令/exit/真实断言摘要、guard与input provenance。

任何setup/import/fixture/guard ERROR先停且不记RED；意外PASS不能称功能缺失；缺profile/capture/策略context不补默认；无核认可保护策略继续manual/blocked；review finding按同原R上下文修合同/测试后复核。全N02/F02/TC-N01/I2仍false，无网络/模型/provider/paid/DB/hook写/CIrerun/image下载/merge/deploy。本轮纯文档没有可执行行为变化，豁免RED；仅静态引用/字段一致性/diff-check，不能覆盖未来copy实现或无副作用事实。
