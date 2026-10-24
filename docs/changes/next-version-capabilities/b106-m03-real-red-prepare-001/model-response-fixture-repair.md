# B106 RED2 模型响应夹具窄修复

操作 B106-RED2-MODEL-RESPONSE-FIXTURE-REPAIR-001：静态准备，未 collect/执行/资源分配，未取得新的实际 RED/GREEN。沿原 b106 树只改 RED2 必要离线响应与透明诊断，加此交接；业务源码、RED1、成本对账、worker/query捕获、原恢复联合前置与两目标断言不变。

## 实际证据与定位限度

ROOT 原 R-C090 host批准后，在只读包 `/Users/mentianlu/.codex/runtime/b106-cost-fixture-exact2-red-host-binding-002/results/b106-article-term-receipt-red-2.{json,log}` 实际运行 parent `bdc6e5134a62c29a8e8f1c6f6e4f0531f9eee741`。原件先记录 NETWORK_NO_LOCKS/idle、实际 receipt 成功 reconciled/offline_usage_reconciled，后 consumer 返回 translated=False/skipped=True/model_refused，原联合恢复前置 ERROR；RED1 保持目标 FAIL。原生 1 FAIL + 1 ERROR，不是两个 RED；supervisor拒绝的包不能进入实现。

ROOT 提供 closeout `/Users/mentianlu/.codex/runtime/root-b106-cost-fixture-exact2-closeout-002/closeout.json` SHA256 `57c4e3890ad34614e67566bc10fd7d146be334972efb508a6b4f3edc66055761`，owned资源已清理/FD重获/2115seal未变。本卡不重新查询这些资源；旧两个实际包不修改不重跑。

静态发现确定的响应缺陷：原夹具 title/source body 各出现一次 Irad Ortiz Jr.；原 provider 的 deterministic plan 按 source替换成人物占位符，_preserved_placeholder_violations 逐字段比较出现次数。旧 response body 把含 __UMA_TERM_1__ 的整句乘6，产生六次，违反正文仅一次的要求（duplicated，observed_count=6/expected_count=1）。该缺陷能导致原质量retry；原脚本只含一次响应，后续可能触发其他受保护拒绝。但旧运行日志没有打印原provider异常/metadata，不能将具体异常名、retry或第二create当已观察事实。只有实际cost receipt完成和consumer合并原因model_refused是旧运行确认。

## 修复与诊断

响应正文改为含人物占位符的一句 + 不含占位符的普通译文重复6次，保留译文长度/完整句子；标题、正文均各一次TERM1，摘要使用原已有TERM1。新增source与payload逐字段出现次数fixture_requirement，不满足就是ERROR。保留原人物占位符restore方案，由实际provider使用actual resolution恢复中文译名，既不手填词条target，也不构造成功TranslationResult。

透明provider参数observer仍调用real_translate；只增加try/except记录实际异常类、原message、原metadata，然后bare raise原样重抛，不改变consumer原拒绝路径。成功时打印实际TranslationResult长度/usage/attempt；consumer结束后打印实际returned reason、provider次数、read/create数、Run status/progress/checkpoint、requests_reserved，使下一窗口可定位质量、解析、第二request、checkpoint或apply哪个阶段失败。原Article/provider/read重放联合前置及frozen-resolution/零词典SELECT目标原样保留。

后续前置静态核对：JSON字段仍title_zh/body_zh/push_summary_zh，非空且中文句末完整；三字段无新增内部占位符namespace或不完整token，字段人物次数同原source。source长度仍由原短正文乘6+一句组成，未变化；response普通译文长度保留。原provider metadata与原checkpoint接口未改，不新增reserved键；真实journal receipt、一次create、旧read原字节重放、scope/owner/grant/source/deadline仍由原链和原硬前置验证。静态检查不证明这些前置已实际通过，新窗口仍须先实际到达Article终态，才可计目标FAIL。

## 固定交接

新独立runtime `/Users/mentianlu/.codex/runtime/b106-red2-model-response-fixture-repair-001`：prepare.json、source.diff、固定exact2 plan、resource-request、原入口及controls、launcher-command。原两个方法ID/batch、原PG16/image/600秒(570+30)/主+单worker/最多3PG连接/none network/readonly/nonroot等边界不变，仅固定source/plan/runtime/hash/目标FAIL classifier重绑定。原执行器不改，ROOT先核后交原R窄审，再fresh窗口，本卡不执行PG/Docker。

静态校验仅AST与字节核对：唯一RED2方法变更；原联合前置与目标断言AST不变；成本journal→record_usage→reconciled放行片段与worker查询捕获AST不变；RED1/B105/业务源码字节不变；payload字段/一次占位符计数；git diff --check。实际provider具体异常与后续完整终态仍待运行，不能先称已消除model_refused或达到RED。
