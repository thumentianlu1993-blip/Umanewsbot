# B139：shadow DTO/envelope 与有界 preflight/copy 合同

2026-10-14，入口冻结草案，待原 R 确认；只有本文与 [test_cases.md](test_cases.md)，无功能/测试源码、无执行证据。固定父对象 `d065b62efde24821f7f3501ef4d279ea5df456c1`，含已审 content_review_decisions 内核，禁止修改其 schema/算法、N01、任务/hook/metadata、模型或共享登记。B138原文固定 `fc5d33a24ef7a9353972c04fcecc11f90c8dceaa:docs/changes/next-version-capabilities/lanes/B/B138-n02-existing-caller-shadow-adapter-plan.md`（SHA ee9133677a7482244c9423b5e8a33adc5dc5322b86b5969f69459c6f125e3d4d），原R报告 `5ff02edf84fef75ed32d6233890ca38a67d7f447` 已 APPROVED 方案；本合同只补其要求的具体 DTO/copy/test 入口，不把方案批准当实现批准。

后续拟新增仅 `server/stable/services/content_review_shadow.py`、`server/stable/test_content_review_shadow.py`。本轮不创建这两个文件。门禁唯一引用根 AGENTS.md。按已读 `.codex/skills/tdd/SKILL.md`，功能代码前先冻结完整 test_cases 并交方案审核；原 R 确认后同任务系列立即开始最小 RED，不另询问用户开始。

## 1. 函数与 envelope

```python
shadow_review_draft(snapshot, *, caller_context, profile, copy_limits, attempt, verdict)
```

所有关键字均为必传参数，无 profile/attempt/copy_limits 业务默认。忘传参数由 Python 调用签名 TypeError 表示调用错误，不算真实 RED；显式 None/错误类型则按本合同返回固定 blocked envelope。B138 的函数名字沿用；显式 copy_limits 是本轮冻结的 adapter 技术参数，不修改内核 profile。此模块不提供 DB/dataclass 投影器、capture issuer、CLI/runner、route 或 SDK。

envelope exact dict，只有 `adapter_gaps`（exact list of 固定码 exact str）和 `review`（None 或隔离后的原内核结果 exact dict）：

- preflight/copy/来源一致性失败：`adapter_gaps=[唯一首因码]`，review=None；没有 candidate、旧正文、用户原文或伪成功标记。
- preflight 合法：adapter_gaps=[]，review 完整保留原内核结果；不改变 status/reason/diff/quality_gaps/input_digest/decision_digest 或两 flag。
- kernel review_blocked 不转成 adapter 成功候选；review 保留其 candidate_text=None/diff=[]/qualified=False/publish_eligible=False。
- 有效 unknown protection 只能 needs_manual_review；known 也仅 candidate_valid，不是质量/发布合格。合法与失败均不改变既有 caller/draft，不影响任务计数或旧发布路径。

固定 adapter 首因码：copy_limits_invalid、input_type_invalid、input_cycle、input_depth_limit、input_node_limit、input_container_limit、input_field_limit、input_byte_limit、snapshot_shape_invalid、context_shape_invalid、source_binding_mismatch、capture_binding_mismatch、body_binding_mismatch、output_copy_limit。静态编程缺陷/不可控进程终止不伪装成已成功 blocked；不捕获 BaseException，不承诺进程崩溃恢复。内核原固定码照原样保留，不包装为 provider error。无原文异常日志/runtime写入。

## 2. DTO exact 类型与字段

所有数据必须 type(x) 等于 builtin dict/list/str/int/bool 或 x is None；float/bytes/tuple/set/dataclass/Tag/ORM/Mapping/任意子类/自定义对象均拒绝，先 type 检查才允许 len/遍历。通用 int 支持 bit_length<=63；语义计数/版本/范围沿内核 exact int，bool不冒充计数。bool只在通用 JSON层可表示，不自动成为字段合法值。精确类型和 schema 不通过 str/getattr/iter/encode hook 转换；枚举由 snapshot owner 外部显式转普通 str。本函数只面对普通副本，不接受 actual CanonicalNewsDraft 对象。

| 对象 | exact 必需字段；额外键拒绝 | 语义与来源 |
| --- | --- | --- |
| snapshot | source_site,source_article_id,source_url,canonical_source_site,body_ja_raw,body_ja_normalized,metadata | 除 metadata 为dict、canonical_source_site 为非空str或None，其余exact非空str；从已经完成的同一draft投影；正文不得隐式trim/补齐 |
| snapshot.metadata | body_parse_status,body_selector,body_cleaning,source_url,discovered_source_site | status/selector/URL/discovered均exact str；trace exact dict交原内核完整验证，不能过滤其任何内部键；status不ok/selector空触发snapshot_shape_invalid，绝不补body/main |
| caller_context | expected,capture_ref,policy_ref,protection,template | expected/protection/template exact dict；capture_ref/policy_ref exact非空str，空/None为context_shape_invalid |
| caller_context.expected | source_site,source_article_id,source_url,body_html_sha256 | 四者exact非空str，SHA为64小写hex；owner独立持有的绑定材料，不从本次snapshot即时制造expected |
| protection | state,ref,protected_ids | 原内核形状；state known或unknown，ref非空str或None，IDs exact list[str]；所有进一步known/ref/ID合法性由原核处理，不能从模型/字段锁推导 |
| template | state,ref,version | 原核形状；不从selector/哈希猜known，不制造模板version；进一步合法性由原核处理 |
| profile | id,purpose,source_site,policy_ref,limits | 完整原核exact形状/限额，None或无效由原核验证，不调用私有profile helper，不复制测试值为默认 |
| attempt | exact str | 原核 available/unavailable/refused/timeout/invalid，未知状态由原核阻断；不猜网络状态/超时/费用 |
| verdict | None 或exact dict | available的完整decision shape由原核验证；其他attempt仍对输入作有界builtin预检，但核不会用其产生候选；不默认keep-all |

所有字符串均须合法UTF-8，可保留原Unicode；禁 NFC/静默替换未配对 surrogate。profile/trace/protection/template/verdict 的字段集合由已审内核最终验证，adapter不得删除额外字段让它变合法。最外 snapshot/context/expected/metadata 和 copy_limits 的集合由adapter精确验证；任一缺/额外键不忽略。

source 绑定要求：snapshot.source_site == metadata.discovered_source_site == expected.source_site；snapshot.source_article_id==expected.source_article_id；snapshot.source_url==metadata.source_url==expected.source_url。canonical_source_site 可是 TDN，而实际 cleaner/discovered site 是 tdn_france；canonical 字段仅诊断材料，不替换site/重算block ID/更改digest。仅canonical变化不赋新权限，也不更改kernel packet。

capture绑定：完整body_cleaning中body_html_sha256==expected.body_html_sha256；它是清理前正文容器SHA，不能换成original_content_html整页SHA、URL或时间。trace不存在/无法读取相应普通字段为snapshot_shape_invalid，合法但不匹配为capture_binding_mismatch。核内 capture_sha256 原值沿用。body绑定：trace.after_text == snapshot.body_ja_raw，且 normalize_whitespace(snapshot.body_ja_raw)==snapshot.body_ja_normalized；三者保持完整正文，无256字/source_excerpt替代。缺值或错配body_binding_mismatch，不再parse、不修复/猜blocks。

packet映射唯一：source={site:snapshot.source_site,article_ref:snapshot.source_article_id,capture_ref:context.capture_ref}，capture_sha256=trace.body_html_sha256，policy_ref=context.policy_ref，status/trace从snapshot完整取，protection/template从context完整取，schema_version=1。profile完全显式。verdict必须绑定同packet/profile input_digest；adapter不重写旧digest、不接受模型自报trusted。capture/policy/protection真实发行与可信N01来源仍属caller责任；核/adapter只核普通副本绑定，不能认证重新伪造过的一致包。没有真实expected/capture context的实际链路停blocked。

## 3. copy_limits 与复制前预检

copy_limits exact六键dict：`input_bytes, output_bytes, field_bytes, container_items, nodes, depth`。全部positive exact int<=2^31−1，depth<=64只是递归支持界，无默认值。先检查dict exact类型/键值对数=6及每key exact str，再比较固定literal字段集合，values先检查exact类型与bit_length，不调用用户对象方法；invalid直接返回固定copy_limits_invalid。limits自己只是一组固定六数支持配置，不参与用户payload byte预算；不在检查前复制/JSON序列化未知输入。TEST_ONLY测试常量见test_cases，真实调用者必须明确提供，任何测试常量不构成生产预算。

预检对象是逻辑 envelope `{snapshot,caller_context,profile,attempt,verdict}`：顶层5个固定键也计字节/节点，不包含copy_limits；这个临时外层仅持输入引用，不是深复制。根depth=0，dict key和value/list元素都depth+1，每个访问出现计一个node（含keys、重复引用）；dict container_items按键值对数、list按元素数。先检查type、cycle祖先集合、depth、node累计、container长度，然后遍历；超限立即固定码，不遍历剩余元素。祖先cycle拒绝；合法无环共享子对象按每次出现计资源，复制后不保留共享可变alias。

input_bytes定义为上述逻辑envelope完整canonical JSON的UTF-8字节数：ensure_ascii=False，无额外空格，字符串JSON转义；dict按key排序的长度与遍历顺序无关。先做无输出构造的预算遍历：在转UTF-8/JSON字符串前检查字符串码点长度和field_bytes支持边界，再逐码点计UTF-8及JSON转义增量，超过立即拒绝；字符串key同规则。不得先对巨大输入json.dumps/deepcopy/list()/sorted()/repr再检查长度。非字符串dict key拒绝；有限整数先bit_length界再有限格式化；所有累计值是本地普通int。粗略原字符数不代替UTF-8/wire字节计数，控制字符/quote/backslash转义都计入。每个field_bytes只计原字符串UTF-8字节，wire转义由aggregate bytes另计；field/cycle/depth/container/nodes/bytes首个遇到的非法输入按固定顺序报告，不输出数据。

第一遍全部通过后，第二遍在相同caps内手工复制已确认的exact builtin树（不能用用户hook）；再次执行type/cycle/预算防止两遍间调用方改变对象。只支持调用方在单次同步调用期间不并发修改其普通输入的协议；不提供锁/线程快照事务或TOCTOU真实性保证。若二遍察觉变化或不再满足caps则blocked；即使两遍间普通内容改变但未被察觉，也不声称原capture原子性，verdict仍须最终包digest匹配。不能把这项同步副本约定推广为生产并发安全。

复制后才做DTO/identity/body语义检查与调用kernel公开函数；原核自行有界验证packet/profile/verdict/result。adapter不得import/call私有_wire/_packet/_profile/_blocked，不另写input_digest算法；只用公开 input_digest/review_candidate，复用原 normalize_whitespace，不复制cleaner/证据算法。最外context/frame preflight是有限接缝代码，不做通用JSON框架。

输出同样先预检完整envelope（含review）再隔离复制，output_bytes为wire总字节，其他field/items/nodes/depth同一copy_limits。输出超限返回固定output_copy_limit/None，而非半截candidate/diff。所有固定adapter错误envelope是有界无用户内容的控制响应，**豁免output_bytes等小于自身的payload caps**，否则无法表达invalid配置；该豁免只限固定码/None，不允许附原文/任意exception/review。kernel固定错误也是数据，若它加外层不满足输出caps则转固定adapter output_copy_limit，不放大豁免。输入aggregate caps与kernel各packet/verdict/result caps两层独立，任一超限都不截断、不放宽另一层。

输出review与kernel返回对象、所有输入和未来另一调用结果无可变引用共享。函数不setattr、修改nested输入、写metadata/runtime/DB、不调用fetch/parser/normalize_source_payload/任务/存储/模型provider；parser和normalizer仅未来测试的fixture setup里使用。输入冻结、输出隔离并不认证来源或全发布链封堵。

## 4. 失败顺序与独立推进范围

先copy_limits固定支持校验→输入有界两遍copy→snapshot/context外形→source/capture/body绑定→原kernel review_candidate（按原规则验证profile/trace/attempt/verdict）→输出有界副本。一次只返回首个adapter gap；核的合法/blocked由原核原样决定。缺profile在context/body良好时应得到kernel profile_missing，不能填默认；context缺失在前则先context_shape_invalid。unavailable等仍必须输入caps与source上下文合法，随后原核blocked无fallback。

该离线函数没有route/DB/Celery；部署兼容、并发锁、生产恢复、迁移和模型约束不在此片，测试设计明确N/A且验证不新增调用边。原R确认入口后才启动本地最小RED→同例GREEN→必要接缝/旧纯回归；受影响登记/正式CI/发布另交ROOT。当前只完成静态入口冻结，full N02/F02/TC-N01/I2始终未完成。
