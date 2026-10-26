# B016 完整载体 v3 有限方案输入

2026-10-05，Asia/Shanghai。当前 `1MiB` 合同继续有效；本文只指定下一张静态方案卡的候选与待证明事项，不改变实现、资源分配或生产边界。人工确认仅引用根 [AGENTS.md](../../../AGENTS.md)。

## 已定事实与目的

原 R `5ec33895e6d76bb5679eeb22bdb99ffd9a196e6f` 静态关闭 B `5e862862` 的实际FD身份缺口、`92479f1c` 的Receipt schema计量错误。四组修正后再计FD实际82字节的下界为1369995/1463324/1155492/1214892；Index/Receipt/source/instrumentation仍不完整，完整包尚无合法成功原件。现完整对象整件SHA去重节省0，已经评估的两项局部引用编码不足以关闭缺口。继续拼同一1MiB包没有意义。

下一卡只准备**保持现有canonical JSON对象和逻辑帧的 v3 有界载体方案**。ROOT选定先评估总2MiB的单一候选，避免同时开发压缩、二进制编码或多种分块协议。2MiB只是待证的候选上限，不是已获准新预算、已证足够容量或完成生产安全评估。若有限核算不成立，报告具体缺口并停止，不自动继续加额或造完整包。

## 候选预算分配（总2097152字节）

| 计量域 | 候选硬上限 | 含义 |
|---|---:|---|
| artifact及Registry池 | 1179648 | 所有真实传输原件、foundation/chunk/descriptor均计；别名不重复传但不得隐藏新增对象 |
| capability与case frames合计 | 393216 | 两链全部canonical帧；各链原64帧/操作约束保持 |
| 完整Index | 327680 | 实际canonical完整Index，不用下界或aliases替代；同时受明确top-level解码/节点/深度约束 |
| Receipt | 32768 | 继承原独立Receipt上限，完整对象及来源/FD/时间字段 |
| prepared Intent/Input合计 | 32768 | 每次实际发送的完整准备对象 |
| 外层编码、分隔和传输封装 | 131072 | 必须指定真实格式与实际字节收费，不能当无需说明的免费缓冲 |

六项相加精确等于2MiB，每项同时受自身上限；不得借另一项空余额豁免，所有wire byte只归属一个域。声明未传输的review/log/negative原件不能混入传输计量。无压缩、隐式共享、遗漏cap/失败帧、缩小fixture/逻辑步骤或增加重试/操作分母。

## 必须在固定方案中闭合

1. **版本和权限面**：明确新的Input/Index/Receipt/Registry/引用字段版本及兼容拒绝矩阵，旧1MiB合同不被静默改写；不新建任意kind、自由路径或访问权限。方案只消费既有synthetic固定对象及同来源范围，不生成真实provider资格。
2. **全量计量**：以v10四组实际pool/帧/prepared及v11修正为基础，有限计算具体Index和Receipt载体的最坏可接受字段成本、外层封装费用、剩余空间与每类未知费用。不能用数学下界或24KiB见证投影保证可装入；不能把未知记0，也不能以最长字段全部同时取值为合法事实。每个未来真实包必须在读入/分配前受候选总额与分类上限拒绝；给出四组可闭合或仍缺证的明细。
3. **解析边界**：逐项明确raw/Registry/Operation展开、Index全树、Receipt全树与外层流的bytes/nodes/depth/引用数量/缓存/访问计费。保留原artifact/frame8192、Operation2048、Registry record2048/chunk8192/总131072及128records、Operation展开16384/depth64/nodes1024、累计work16777216。旧Index `_decode`的1MiB/depth64/nodes100000并非v3实现资格；新Index候选320KiB需明确同层节点/深度计量，不能把全Index误塞Operation nodes1024，也不能豁免解析成本。Receipt保持32768和明确独立解码边界。所有source/反引用访问计入累计work，缓存不能让重复访问免费或允许自环。逐解析角色映射既定AS/进程/时间限制，给出有界临时表示与缓存成本；总字节候选增加不能自动扩大内存、CPU或时限，静态成本也不冒性能实测。
4. **Receipt来源与FD表达**：九个foundation临时FD的allocation_ref目前不能直接塞旧全局identity_ref。提出一种exact有界typed引用关系，指向已收齐最终Index中的实际bootstrap记录及其raw证据，明确允许字段、目标类型、同execution/scope/FD生命周期与已关闭终态；不得以later consumer/aggregate替代first producer，不得循环到Receipt自身或后来产生的Index SHA。Receipt绑定最终Index SHA、最后event、受认证返回与独立receipt clock，不能假造首次采集或来源资质。
5. **失败及完整性**：正常和故障四组均保原步骤/返回/12输出/21slot、19旧negative/13clock及新增8FD反例；列明还缺的失败prefix/instrumentation如何计数和计费。source/hash图保持无环；原首slice3op、retry8、单链64帧等不变，不能把raw acquisition暗算为已经实现的Operation。
6. **候选验证计划**：列出后续必须先RED的边界用例、纯parser实现范围、独立复审、资源资格与完整wire执行证据的依赖。此次只方案及至多有限JSON示例/算术，不编写新parser，不改现helper、43tests或执行候选/协议/OS/native/container。native/source资格继续MISSING。

## 本卡产出与停止

只在B自有新revision目录和B报告写一个可审静态方案。机器工件不超过40件，避免重建上万finite样本；旧v1–v11原件及保护文件全保留。输出固定文档/manifest式索引、四组分类账及未知项、唯一typed-ref候选与循环/预算反例、检查点和待实施清单。

本批以最新used55开始，used56或全局停止条件先到时保存最小检查点；不足时交明确缺件，不自动追加批次。固定包回ROOT及同原R先审。ROOT待审查结果后再决定下一范围；本卡不使2MiB生效、不分配运行窗口、不扩大抓取/付费/生产权限，不标B016完整完成。
