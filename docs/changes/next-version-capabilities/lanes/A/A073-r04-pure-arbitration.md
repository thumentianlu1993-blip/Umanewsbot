# A073：R04 完整赛果纯仲裁技术合同

先冻结合同再TDD；依据受审A072 `17e7a5e08`、原R `03ca90e5bc728fdb8a28954b930f9b8084ba814b` 及ROOT“先消费显式fresh/stale/unknown，不指定真实TTL/producer”的答复。仅新纯模块与语义测试／本文，不修改既有policy/provider/writer/页面/schema；无真实来源或集成资格。

有限输入：一个event、非负int generation、aware as_of、最多256个candidate Observation及最多1个current；字符串引用≤256、字段名≤128、字段值≤4096 UTF-8 bytes；完整包最多128个ResultField，输入总体文本≤1MiB。expected_fields非空唯一tuple。原件/版本/来源/独立origin ref明确，priority只消费既有100/200/300；admission、health、identity、maturity、freshness均固定枚举，qualified/complete/revoked/manual严格bool，不兼容truthy或默认身份。

content_at与freshness assessed_at/valid_until须内置timezone固定offset的aware datetime（UTC或显式偏移，无任意tzinfo回调）；以UTC真实瞬间比较，要求content_at≤assessed_at≤as_of＜valid_until。verdict的observation/version refs及result_sha256必须匹配包，rule_ref必须给出；有效时段是注入verdict自身有效边界，不制定TTL。缺项/未来/不匹配/撤销/错event或generation/未准入/质量不足无SELECT；未知current不能静默替换。manual仅KEEP既有版本，不输出合格摘要或selected字段，不能洗成认证。

normalized result SHA只绑定排序后的字段名/精确字符串值，不含provider/evidence ref；不改变值、不把摘要当真实性。字段覆盖严格等于expected_fields，完整性及来源资格本身仍是外部可信producer负责的输入事实。等价重放按规范签名去重；相同observation ref但不同版本/内容/资格等数据拒绝。候选顺序与字段顺序不影响输出，aware等时区表示等价。

所有fresh且qualified完整确定/更正包（包括有效current）在rank前比较摘要；same-origin或independent矛盾均CONFLICT，不用镜像数/等级/新时间消掉冲突。有效current同内容KEEP防振荡。否则排序按priority降序、内容时刻降序、provider/observation/version字符串升序选单包；rank不解决值冲突，corrected标签不赋supersedes权。stale当前＋fresh候选SELECT_BACKUP，无current选SELECT_CANDIDATE；无可用包NEEDS_EVIDENCE。

输出冻结Arbitration：行动/有限原因、retained_version_ref、selected observation/version、normalized SHA、单选中包字段引用、reject原因及补证refs；仅result可blocked。authenticated/publication_authorized始终false。数据结构/类型或资源上限违规ValueError，合法但缺业务证据NEEDS_EVIDENCE。不读时钟/环境/目录，不importDjango/DB/网络；现成Python3.14标准库unittest，无新工具/runner/PG/Docker/VM。

A072计数更正：旧receipt写20是错误，原before/after实际19（A070 runtime12＋A071 runtime5＋两doc）。新runtime保留19项实际索引和当次核对，旧receipt/index不改，不补假第20项。原19及A072包/report合计25个保护对象八属性核对，实际数量分别报告。

实际TDD：先以有效DTO＋空入口执行18个方法，原始RED含23个AssertionError失败（含subTest，0ERROR），首项stale300→freshqualified100的SELECT_BACKUP断言明确失败。完善摘要绑定时fixture builder加入独立规范SHA，方法业务断言不因新增字段改为宽松断言；最终23方法GREEN，0skip。追加缺／错摘要、值变而verdict未变、极端日期1微秒排序、naive内容/评估时间、坏field类型、总文本限额、空字段值及UTC历法范围溢出反例。没有DB/框架或业务来源调用，不跑已有R02/R03/H03测试。

代码与测试仅标准库；无系统时钟默认或读环境，无来源/文件/生产读写、模型/付费、PG/Docker/VM/nativecopy/新runner。现有policy及其300/200/100不修改，first-slice排序不是权威冲突裁决。真实rule/producer未认证，字符串/ref/hash/枚举不造资格，authenticated/publication_authorized始终false；实接缺项仍NEEDS_EVIDENCE。完整各能力/九地区/单writer/CAS/SLA与真实来源义务保留，提交后由ROOT交同原R代码审，未merge/deploy。
