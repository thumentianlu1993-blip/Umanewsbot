# C021 目标解释器诊断：先保留实际观察，再判断表示差异

2026-10-05，Asia/Shanghai。接续唯一 `C021-TARGET312-METADATA-PROBE-EXEC-001`。本方向只调整尚未取得数据的离线诊断工具，不修改业务实现、测试验收或 GREEN 身份规则；人工确认统一引用根 [AGENTS.md](../../../AGENTS.md)。新固定包仍须原 R 静态审核及 ROOT 新窗口。

## 已取得的事实

- 固定源 `433e0cfef1a19f9f2e8feddbd54d33fa91bc621c`、1928 文件索引 `fd5953cf6e215e46d6d9f3f497b11020ba466b4339fad62ff24f29cc2daadfb9`、两源32白名单catalog保持。
- `f96846b3ec8283255257e05c462da4d72d17fd9ba8f101e07804101a7125c956` 的单次目标3.12.3诊断在第一源 AST hash 比较处失败。report `84de4c936f5aff65379f1a431842a28840773f60e1c9181feaa7cc8189abfbb2`、receipt `90b38d6782f20059d22aa63ff7f00d3aa0d8c6ff314fb197c66478a0a7b9f412`；实际 observations=0，未进入 compile/dis，业务/生成代码/framework执行均0。
- report 仅给 `ast_sha`，没有实际 AST dump/hash 或首个具体条目，当前不能断定是哪个 lambda 或跨版本表示差异，更不能据此放宽业务接受规则。
- ROOT 08:26:02 独立核 exact CID不存在、nonce/running/旧runner为空、1928源全集一致；postrun SHA `d1035e8bee66ca54ace09b678340004521771a8304c4aa9d32885c2ce3ce8635`。原窗口已消费，不重试。

## 新诊断候选

1. 旧失败包及runner rev1冻结，另建revision。保留受审runner原始inspect先存后解析、严格absence、身份清理、单次/时限及资源控制；如诊断schema需变，只作精确派生并重新冻结hash。
2. 继续在目标解释器检查真实源字节SHA、固定两路径/尺寸、32catalog条目、每个lambda与body位置及源片段字节绑定。它们是数据入口约束；源内容不匹配时仍停止，不执行生成代码。
3. 在任何 AST 摘要比较前，将当前source/条目stable_id、lambda/body span、期望摘要、目标实际dump及摘要、实际节点字段名称和目标版本写入有界观察检查点。保存实际差异与逐字段比较结果，不用宿主重算覆盖目标数据。AST dump字符串单条至多64KiB，全部新增AST观察累计至多2MiB，并计入原8MiB report总界；超限保留最后有界检查点及准确失败阶段，不能裁剪成通过。
4. **仅在此metadata-only诊断中**，同一冻结源与位置已核但目标 AST 表示摘要不同，是需要保留的诊断观察，不是阻止compile/dis的资格前提。明确标记 `ast_representation_match=false` 和不具备业务身份资格，继续有限读取编译元数据。缺源、位置不唯一、尺寸/节点预算超限等仍记录后停止；不得按遍历ordinal推断身份。
5. 保持512 CodeType/深32/8192 constants、每lambda2048 bytecode/1024 positions及instructions、32lambda、8MiB report与4096失败预留。记录真实None/零宽/CACHE及strict匹配zero/one/many和原因；diagnostic_complete只表示指定观察收齐，不表示AST一致、lambda业务身份合格或GREEN。
6. `generated_code_executions=0`、`business_methods_executed=0`、framework/helper/candidate import=0与 `product_green_eligible=false` 不变。不得删除原strict evaluator、改业务测试分母/expected或据未知AST差异自行制定兼容规则。先取得真实目标数据，再由ROOT据证据定兼容实现。
7. 此卡仅源码、AST/JSON/hash和有限静态关系验证，不执行新worker/runner、host compile诊断源、container/业务。交固定source/manifest/index/receipt与实际失败报告，同原R核诊断观察与业务验证分离后，ROOT才分新的metadata-only单次窗口。
