# A075：R04 普通 snapshot 影子 mapper 合同

依据受审A074 `cbeadd7f8`／原R `9415dd1c697a973c777d77f94acbe8ca48c1c395` 和ROOT路径A选择。仅新mapper/test/本文，精确复用A073 bf2d纯核，不改kernel/policy/provider/writer/schema/hook/R02/R03。不调用apply/record/runfallback；project_current=False也不是本卡执行许可。

先冻结 `r04-shadow-input.v1`：plain builtin dict/list/scalars，严格顶层及包/clock/assessment/row/freshness/legacy字段；一个current（可null）及一个candidate，对应caller单observation分支。aware ISO字符串由标准库转为固定offset datetime。最多128共同持久runner IDs、每包128行、depth8/nodes20000/总文本1MiB；引用≤256、行值≤4096。未知类型/extra/cycle/超限failclosed诊断，不裁名单或触发ORM/lazy属性。

目标schedule_generation与包captured_schedule_generation显式int或null，缺失不推0/owner代次。content_clock仅显式content_at+basis_ref；observed/fetched/recorded/watermark/permission-valid/poll时点留transport_clocks，禁止映成content时钟。admission/health/identity/revocation/origin/freshness-producer及已完成rows/strong identity/terminal/roster验证投影缺项即gap；200/OFFICIAL/空error/自算hash不补它们。这些投影仍是assertions，mapper不认证真实来源。

共同runner_id来自caller持久映射，None/0/重复/遗漏/额外均gap。每runner一条canonical JSON ResultField，position/status/time/margin/barrier/weight和统一条件下名字；null保留null、无0占位。compare_names全包共享：有current且同provider，或candidate corrected且correction_marker为true，则两个包都include，否则两个都exclude；未知corrected条件gap，不允许provider分别选择口径。每个evidence_ref须属同observation的normalized_payload/participants数字pointer（固定main实际字段），所有原数组位置覆盖唯一、单包refs，不编未持久ID。终态status/position范围须与已声明normalizer结果相容，明显矛盾仅报gap，不重解析原网页或给资格。原normalized SHA不当A073字段摘要或freshness认证；verdict/digest/producer必须原样给定，由已有pure核验证绑定。

输出冻结ShadowResult：action/reason、有限gap、统一compare_names、映射content_times、可选A073建议与legacy快照hash；apply/publication/execution/authenticated始终false。不改变legacy对象/flags/输入，不写诊断存储。缺必需事实先NEEDS_EVIDENCE，不调用core造SELECT；真实rule/producer/clock/捕获代次未齐仍不可实接。先以混合watermark的有效DTO＋no-op得到行为RED，再GREEN；本卡不声称实际hook或真实SELECT，完整九地区/writer-CAS/SLA义务保留。

实际RED：原14方法得到13个AssertionError失败、0ERROR，首项混合watermark→NEEDS_EVIDENCE断言失败（无missing import/setup失败）。固定main核对后只校正fixture pointer为真实participants、非完赛enum为did_not_finish，未放宽业务断言。GREEN最终17个mapper方法通过；低成本并跑23个获审A073方法，仅验证薄层复用后兼容，不移植它们为真实来源/DB资格。

新runtime `/Users/mentianlu/.codex/runtime/a075-r04-shadow-snapshot-mapper-tdd-001` 保留原RED/source/tests、最终GREEN、受审输入绑定、旧成果前后八属性及handoff/index。全部输入明示synthetic，freshness/basis/验证投影ref是asserted而非真实认证；不声称真实SELECT/hook，scope、时钟、origin/health/捕获代次及真实producer仍要ROOT明确证明。源码只标准库与精确A073纯核，无模型/ORM/文件/环境/系统时钟/网络/provider调用，未修改任何共享源文件或旧封包。

## A075-R01 跨行排名一致性返修

原R `3800c56a08a187f01f6937736db80cd42b63ff4d` 指出duplicate finished/1、finished/1+3、全withdrawn/None仍被shadow选择。新检查仅复用固定main `_normalize_result_rows` 134–163已有语义：至少一个positive finish；按每名次出现次数递进的competition ranking；并列名次各行须dead_heat、非并列須finished。结合原逐行终态/范围规则，两侧任一矛盾均NEEDS_EVIDENCE＋具体ranking gap、recommendation=null；不排序改名次、不补状态、不裁名单、不因rows_normalized=True略过。

新runtime `/Users/mentianlu/.codex/runtime/a075-normalized-ranking-repair-001` 保存固定旧191ae8e1/source和R原始反例输入。新增current/candidate两侧六个独立方法，每次重新绑定精确投影digest避免其他拒绝遮掩，旧mapper真RED 6FAIL/0ERROR，新同方法GREEN。合法dead_heat/1+1、1+1+3、DNF/null和排列稳定仍通过，单独dead_heat或混合tie状态拒绝。原17 mapper和23 core保留，最终26＋23＝49PASS；新9方法覆盖上述异常与合法控制。只改mapper/tests/本文，获审A073、policy/normalizer、原日志/index和他线不改。全部synthetic/标准库，无真实hook/认证/DB/来源/资源或merge/deploy，交原R窄复审。
