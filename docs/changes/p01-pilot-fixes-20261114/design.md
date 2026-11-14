# 设计

## A 数字等价

在news_numeric_equivalence中扩展有日期语境的Jan.–Dec.常用月份缩写（包括Sep/Sept），
完整日期仍必须有明确年份且验证真实日期；不推年份、不把任意缩写当数字。
在赛马距离差语境识别a length-and-a-half、one-and-a-half lengths、two-and-a-quarter lengths，
与1.5/2.25个马位、一个半/两个又四分之一马位等值；错误数字、丢失数量及非数值专名继续失败。
旧未支持的复合数不随便拆零，数值比较仍只证明数值表面，不证明事实归属。

## B 翻译上下文与轻量硬检查

新增独立纯函数模块，供context-v3的payload、译后检查和发布重放复用：
- 姓名后的中性氏不得产生性别敬称。以实体person的原文位置、同块译名/原名绑定；氏名、普通中文先生、
  原文明示Mr/Mrs/Ms或明确性别称谓有反例保护。无法证明称谓来源则定位到目标块/摘要，走现有一次局部修复。
- 给译者同一文章的名称形式线索与对应原文位置。只提供原文可核的全名/简称候选，不创建全局身份；
  同姓多人或证据不足不合并/不传播译名。摘要不得把候选全名和简称机械并列成两个人各赢若干场。
- 明确赛马血统语法、轻负磅习语、主体和引语归属。审校关注这些关系，保留不确定和失败；不靠占位符齐全宣称事实正确。
- 通用地域/赛马词使用版本化的小型代码词表（国家、Hong Kong/Sha Tin/Happy Valley、重賞、骑师榜、纯血赛马等）；
  只适用于place/race_related/racing_honor等明确类型，不匹配horse/person，不新增人名或马名译名。
  确定性词表输出保留独立provenance及词表版本，译名保护和公开前复核重建相同结果；篡改词条、类型或版本必须失败。
  普通词不必标为实体；固定词表只解决已识别且被保护的通用表达。

实体校验仍逐次出现位置统计，不改已有人工裁决，不把本次五篇变成独立保留集。

## C 选稿引用协议

context-v3提示词让模型返回block_id/quote/context原文引用，由程序使用已有exact_span定位为内部字符跨度，
再走原validate_editorial身份、日期、别名、候选及更正规则。保留旧合法跨度输入的兼容读取，错误跨度不自动纠正。
引用不唯一、引文不存在、额外字段或混合字段拒绝。缺少完整事件身份时按固定六字段返回uncertain；不增加事件kind，
不使用标题/URL/来源发布时间冒充赛事身份。发表回执的选稿证据也走同一转换与验证路径。

## D 审校容量与模型请求

context-v3事实审校保留全部标题、正文块、摘要及逐实体必要字段；不重复发送由blocks可重建的target.body，
不发送实体的整段context、unit_state、数据库identity_evidence等重复审计元数据。payload仍有可核来源/目标摘要，
公开前重建规范payload，防止删除块、改译文或删实体绕审校。无静默截断，不在本轮引入分块调度。

深度调用新增有界reasoning_effort配置（仅low/high/max、仅thinking enabled），校验并绑定进请求/费用回执。
本次deep使用low并将输出上限设为16,384；普通调用保持8,192上限，120秒HTTP、现有lease/task时限不变。
扩大单次输出预约仍受单篇0.50及整批2美元限制；finish_reason非stop仍不得当有效结果。

## 版本及发布兼容

变更只用于新的context-v3策略；提示词/通用词表/载荷版本写入新策略版本与prompt_version，使policy_sha和请求缓存区分。
旧context-v2/legacy输出形状、保护限制及缓存证据不改变。当前生产P01表为空，不重放旧run或覆盖已发布稿。
numeric的错误等价规则修复仍可能影响旧数字复核，必须跑现有数字/发布重放回归；不声称旧不可信回执可自动通过。

不改变数据库模型、队列、并发、重试次数、预算结算或worker超时；只补实际请求参数的有界校验。

## 方案审核补充（第一轮三项修正）

1. 每份紧凑审校payload携带显式audit_payload_version和完整target_sha。target仅删可由blocks按原顺序
   双换行重建的body，其余字段（包括manual）不删除；人工目标保留body块。统一audit_target_from_payload
   验证形状、重建body并校验完整目标SHA。旧payload无版本时保持原读取路径。最终审校与当前目标比较，
   修复前审校与旧原始译文目标比较，深度升级前审校按其自身的旧目标重建；绝不拿最终目标替代历史目标。
   另统一expected_audit_payload重建完整源、紧凑目标、全部实体必要字段和editorial，公开前逐项相等校验。
2. 复测使用新的独立runtime，旧run及收据不可覆盖。实际runner复用业务侧请求参数构造函数，代理允许
   reasoning_effort但仅thinking enabled的low/high/max，base最多8,192、deep最多16,384，载荷仍50KB。
   冻结runner/代理/策略SHA，加入假传输请求探针、超限/额外字段拒绝、同operation只返回既有收据及累计预算检查。
   先补齐缓存source_sha再验证，不能重复上轮评测包装错误。策略prompt_version与词表/载荷版本绑定。
3. context-v3的RESPONSE_SCHEMA与IDENTITY_CONTRACT同步选择quote/context版本；identity.evidence每个值
   和facts[].source_span均在validate_editorial入口唯一定位后转内部跨度；correction.old_body_span及old_text
   继续旧稿证据合同，不对新source引用的转换函数开放该旧稿跨度。uncertain/reject仍严格六个顶层字段。
   v2/legacy请求沿用原schema；v3读取旧合法跨度仅为兼容，不修补错误跨度或身份字段。

血统/轻负磅规则只针对可由原文明确识别的赛马语法或习语，普通命名/同位语不能当作父子关系。
对于同人简称，来源线索只提示候选；摘要将全名/简称并列各取胜的风险可进入审校，不据同姓自动改译名。

## 实现细节

新增 `news_translation_quality.py` 集中承载目录、同篇名称形式候选、中性敬称检查和紧凑审校重建。
`氏` 检查使用当前实体 occurrence 的原文位置及译文姓名，不根据他人的称谓放行；问题定位到正文块或摘要，
进入既有一次局部修复。目录允许项只限明确类型，不新增人名/马名译名；原文独立等级、班次及普通术语
在实体提示词中沿用原类别的排除规则，完整赛事名仍整体保护。

本批新策略：`prompt_version=context-v3-pilot-fixes-20261114`，
`rollout_revision=p01-pilot-fixes-20261114`，`phrase_catalog_version=racing-phrases-v1`，
`audit_payload_version=compact-audit-v1`；deep的`max_output_tokens=16384`、`reasoning_effort=low`。
策略完整JSON保存在独立复测runtime，正式交付时绑定其SHA。现有生产配置未修改。

复测代理system提示词上限从4096放至8192字节（当前审校为2588），user载荷仍50000字节。
业务网关和实际复测plan均使用`chat_request_parameters`。五份缓存审校载荷为6,296–24,764字节；
香港稿24,764字节，没有丢正文块或摘要。代理同operation二次执行只读已落地收据。
