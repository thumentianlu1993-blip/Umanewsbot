# C265 — horse_profiles 最小 guard 产品源码

实现源码已本地提交，待 ROOT 核固定包并交原 R_C 源码审。仅源码，不预报 GREEN。

HEAD `d8f8e9e6757b997e6545b917d5db6d4268ce7c5a` / TREE `d8c36586d87bf19aaf9b437884de2fbc2c513b9e` / parent `69e9856282a41048ac9434fc1928c0d9fc53359f`。唯一变更 `server/stable/services/horse_profiles.py`：216增/16删，1015行/44287B，SHA `4b0868d7e9893501644cb76575a3f49cfe6ad76c1407996a27d5966e27b315f8`。原24测试SHA502c5625…、catalog8da0453c…、reader e36daf50…及其余25受保护pin不变。设计b547保持原untracked，未改未提交；tracked无未提交变化。

## 实现与审计边界

原 `_article_horse_link_protection` 不变；旧WITHDRAWN（article）、manual/removed/marked完整保护优先。只有仍有实际弱动作的pair才进入新观察；无动作直接返回且不查Index。

article保留原desired/旧计划及当前PK/profile CAS、mutable_statuses。原atomic中Article父锁→当前Link锁后，取可执行delete/create/update有限pair并集，固定顺序去重，全部分类后才开始DML。history命中/坏候选/冲突都过滤该pair三类动作；当前有行时protected_ids只加实际current PK，缺行不造历史PK。

profile/global仍逐pair原atomic；Article锁后精确pair显式PK排序锁读当前Link，先复核旧保护，再准入/观察，最后才允许原get_or_create/update。保留原matcher、计数和独立NO_INDEX弱policy，不新增公开blocked计数，不声称整个global任务回滚。

两个写路径均显式绑定原QuerySet/atomic/写操作using别名，并验证实例和冻结reader的默认连接别名相同；不支持另alias SHOW代写连接背书。原atomic内真实SHOW transaction_isolation只接受read committed；非RC/无法确认报稳定PairHistoryTransactionError及pair_history_requires_read_committed，SHOW本身driver错原样抛。无SET TRANSACTION/SESSION、新连接或retry。只读reader本身不变；preview在只读atomic中按相同历史分类过滤、不要求RC、不缓存为commit许可。

17键DTO精确检查schema/pair/恒边界/weak_mutation_allowed=false/四状态/引用字段；INDEXED引用正整数与SHA格式，UNKNOWN引用全空；畸形协议报PairHistoryContractError。UNKNOWN_NO_INDEX仅未命中新保护，不证明never-strong也不授新许可；原规则继续独立决定普通pair。

16个不同动作pair预检查，基于**未改reader每pair最多2data SELECT、单份原始UTF8最多4MiB**预留最坏值，分别不超过32/64MiB；只顺序持有reader结果和小的reason map，不同时保留原始archive。该组合上界是源码合同，不是动态计数或Python堆硬限证明。超过预算在读/关系DML前报稳定pair预算ValueError。

父/Link锁后仅新增history读阶段临时设置transaction-local statement/lock timeout=min(调用方非零更严值,2s)，0按无限制临时收紧；正常读完恢复原SHOW字符串。异常无finally恢复SQL，直接由原atomic/savepoint回滚GUC，保原DB/driver首因；软elapsed从新观察阶段开始，在每次读前后、恢复后及关系DML前核对5秒，超限稳定ValueError，不宣称抢占Python解析或为父锁/整个global补总预算。固定测试30秒窗口预算未改。

guard不写新audit/档案/marker，不改tasks/CLI/reprocess合同；正常显式reprocess仍可保存tags/metadata及旧成功审计，技术错误沿既有外层atomic回滚，public wrapper另记失败审计。未把关系零DML夸为全部audit零写。

## 静态验证与未执行项

stdlib AST/compile仅生成未执行代码对象；git diff --check通过。原有函数仅reconcile_article_horse_links/scan_article_horse_links改变，其余旧函数AST相同。新增2内部异常类/6辅助，均在同文件；不改测试或缩oracle。

26受保护pin仅horse_profiles为本卡授权变化，其他25一致；固定24测试和catalog字节不变。74已封包（含C264两个封包）/5907成员全部seal和bytes/SHA复核，旧RED原件未覆盖。C264真实RED已由R_C接受（20业务/需求FAIL，2driver控制未达），不倒写C259 preRED或C257首失败历史。

本卡未import/执行候选/helper，未测试/collect/DB/CI/网络/push/迁移/回填/生产启用。三SQLSTATE、5.1真实等待、GUC恢复、16/17实际预算、普通NO_INDEX后续conflict、preview后commit和12窗口的实现后GREEN均**NOT_RUN**，源码自审不替代独立审或执行验证。

下一步：ROOT核hash→同原R_C源码审；通过后再单独授权固定新SHA正常GREEN。本卡停止。
