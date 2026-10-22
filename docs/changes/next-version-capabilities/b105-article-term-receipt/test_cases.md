# B105 真实ORM RED与回归设计

未实现/未运行。禁止生产DB/Redis/第三方/真实付费SDK。复用原合法offline claim/grant与封闭reader；只stub provider的现有SDK transport/usage。ORM、step、consumer、codec、账本、checkpoint真实运行，不以假manager/resolution成功冒充。

## 首轮真实RED（固定旧047e源码）

在现有test_managed_readonly_steps/test_managed_readonly_translation各新增独立方法，不改旧方法。RED前明确执行候选是否已有版本3入口：若未实现v3，不能把“版本不支持”/import error称目标RED。首轮用现行v2合法业务链创建真实Article/TermEntry/TermAlias，完成实际read，再断言“持久结果含同文章真实term候选材料及可恢复resolution”；预期因该业务字段不存在FAIL（非ERROR）。消费者例在真实read完成、模型开始前中断（原fault/边界），更新真实词典后fresh合法scope续跑；spy只观察原resolver/provider参数不替代它，断言旧快照候选/真实TermEntry ID进入provider且无再次词典SELECT；旧源码临时查词典导致FAIL。历史v2的变化仅作为RED定位，不给v2实现加字段；GREEN将新方法转显式v3，冻结旧RED源码/日志，旧v2另保留兼容断言。

## 实施后六个真实场景组

1. 新v3登记→真实Article源SQL→真实Alias/Term/External与英文关联名单SQL→持久ManagedReadonlyStep→consumer→SDK脚本→checkpoint/final：Article与run/permission/source、step UUID、canonical SHA、TermEntry/TermAlias行ID/更新时间、完整resolution都可回查；read_reserved=1、实际一次材料操作，requests≤2，不把多个内部SELECT称一次SQL。provider观察的resolution应与未越界输入的原resolver完整相等（含notes/priority/conflicts），final引用同step。
2. 来源与身份安全：同名多词条/非马notes/translation pending/无译名/空匹配/英文结构关联；无关Article关联runner及未匹配alias不得进inputs；原分类保持，term ID非HorseProfile核验。改entity.term_id到inputs外、span/外来step UUID、字段/hash/版本/来源参数或夹带指令均拒绝，拒绝前后request/provider create=0。
3. 限额：SQL LIMIT N+1在捕获SQL中可见；alias129/term65/external65/runner129/result129分别读到sentinel即拒绝且后续材料SELECT=0；超长notes/JSON的SQL只投影sentinel且不取原全文；文本UTF8界限、key129/variant257、JSON33项、输入512KiB、resolution33及result8193边界拒绝。超限保留slot/inflight，下次unknown不再query/provider；不“只返回前N个”。未越界tie/重复候选对照原resolver；fixture小于上限的结果原算法逐字段相等。
4. read-completed后异常→真实词典改名/删除别名/is_active变更→fresh合法scope重投：原候选与row hashes/read区间/step UUID相同，词典业务SELECT不增；此为词典历史快照，不声称当前有效。checkpoint_saved免费apply/final重投仍零额外read/request。一次fresh scope不是另进程证明。
5. 缓存亦不能绕过grant revoke/permission epoch、期限、Article源变更、run/claim/version错；只词典更新不等于grant撤销。read期间撤销/源变化在finish拒绝；无结果持久完成/provider，无槽退款。
6. v1/v2默认/精确keys/已登记不可升版、正常成功/unknown拒绝、原35+直接budget和terms回归保持。v3拒绝不能fallback普通provider；普通路径默认不启用新loader。

## SQLite与PG分界

SQLite现有venv/独立内存库可覆盖真实Article/TermEntry/TermAlias/External ORM材料查询的filter/order/LIMIT/projection、纯codec/生成器/完整resolver等价；CaptureQueriesContext是实际SQL证据。不能单用SQLite闭合registered read→step→consumer、PG Substr/Cast差异、select_for_update/并发/admission；不mock pg_backend_pid把它说成PG通过。

完整两条RED及上述消费者组由ROOT安排已存在官方PG隔离窗口；需要的并发只覆盖同一步双消费者单胜者、读期间grant/源变更与锁后截止，保持原parent→root→Article→Run锁序，材料读事务/锁外，最多原主+2worker三连接与有界清理。素材均新合成但业务持久化真实，不需要生产样本/外网；实际资源未申请/启动。并发、真实跨进程和完整M02/M03仍分别挂账，不从单进程case推导完成。

## R01新增真实案例（未运行）

- 真实v3工具完成后删除实际TermEntry/TermAlias/ExternalHorseAlias及原文章赛事关联（保留Article源和grant），fresh scope重投；CaptureQueriesContext按词典/关联表计数为0，允许原Article/live账本SELECT。同一step/row hash/read区间及provider resolution不变；不可查询已删表记录重建关联。
- 原件external行ID→external_horse_id保存后只改entity外部ID，或只改inputs映射使两者不一致，重哈希也拒绝；runner/result证据event ID与保存event_id不同、article_id为另一Article、horse_name_key与可见实体不同均拒绝。验证实际mapper有这些值，不能以row_sha“证明”其存在。当前行更新时间可早于read区间，合法；坏时区/反向区间/重复(kind,id)/非法int/bool拒绝。
- 源正文把实际译名放在第300字符后（256 excerpt外），生成完整可见span并重投；真实source-fenced Article足以核验，无词典查询，不把摘录外合法span判越界。英文正文原HTML `<p>Opening.   Blue <b>Horizon</b> won.</p><nav>Menu</nav>`，按原visible_source_parts得到折叠空白的可见文本；另构造实体跨HTML/连续空白的实际原resolver输出，decoder坐标匹配可见文本而非原HTML。恶意把坐标改为raw HTML offset必须拒绝。
- source变化仍由live fence拒绝；只删除词典/关联不等于grant revoke。decode缺完整已加载Article view/deferred字段拒绝且不触发lazy读取。记录step/read_at/provider参数、完整sourceview SHA，不能用预造成功resolution替代真实producer。

## R02新增收集期案例（未运行）

- 一短名称重复出现，让raw keys/SQL候选均小；统计_make_entity第257次前的拒绝，未完成step，最终集合不作为成功结果；provider create=0，slot/inflight保留，fresh重投unknown且词典SELECT=0。单独做最终33个与中间≤256场景，证明两种上限独立。
- 同span多词条：40中间对象在resolver中间预算内完整参加原归并成1，与不带budget的原resolver逐字段相等（此项专测真实ORM材料进入resolver的中间行为，不能假称其含40行inputs的整份回执必定小于8192；最终codec若超界仍独立拒绝）；不能第33个提前按最终限额截断。另构造同类>256或byte硬界，整次拒绝且不返回前N竞争者。
- 多外部alias共span触发991–995附加及1048后ID/evidence归并：覆盖四类list的第65项、累计第1025项、字符串/分账/总byte超界，观察拒绝发生在追加/重赋值前；原列表不增长超过界。重复ID仍按归并输入收费，不靠去重规避累计成本。
- 英文保护span/共同名字大量产生suppressed，日文person_alias_owner/protected_spans，其他语言candidates→suppressed/accepted迁移均触发独立collection预算；patch仅spy各预算事件，不替代真实resolver或DB材料。不以最终small集合证明中间无上界。
- 全部合法小输入日/英/其他三个分支带budget与原None逐字段一致（含suppressed、accepted notes/priority、external IDs/evidence及排序）。捕获resolver返回前预算事件，覆盖每增长点；未覆盖点为finding。只有SDK脚本fake，业务函数/ORM真实。
