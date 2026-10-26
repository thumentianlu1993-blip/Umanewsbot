# B016 wire 尺寸冲突：待审修订方向

2026-10-05，Asia/Shanghai。关联 `B016-CAP-CONTEXT-CLARIFICATION-001`，本次答复 ID 为 `B016-WIRE-SIZE-REPAIR-DIRECTION-001`。这是未上线纯合同的技术收口方向，尚未获原 R 审核，不是 parser 新语义、native、生产或资源窗口的执行批准。

## 已核事实与限制

root 直接重算了私有目录 `/Users/mentianlu/.codex/runtime/b016-native-pure-contract-v1/cap-material-v1/` 下三份文件的完整 canonical 字节和 SHA256：

|原件|实际 bytes|SHA256|
|---|---:|---|
|runtime-oversize-operation.json|3199|`3d9ed17234fe621f75505870bf611a30941b89ad13ce000cdf4c3d59c1a2266d`|
|runtime-lexical-lower-bound.json|2845|`f9a81a2f1bef1c839a0ab2e6a08370be89344e6655cb8de4b66b8b27fad942c1`|
|seed-size-analysis.json|825|`a8e9209ce12bca26f7ad288fdf23703124fea03e408ece340ed7c7716c7245d4`|

当前 `_primitive_specs` 的 runtime 分支要求完整 expected/runtime、两个 ABI 引用、四个 loadchain 引用以及五个 Step；`_frame` 又对整个 Operation 的 canonical 字节执行 2048 上限。第一份原件已去掉冗余 `artifact_refs`；第二份进一步缩短路径、时间及返回整数并清空可选依赖，仍超限。root 没有 import 作者模块或重新执行测试；字段校验通过来自作者报告。第二份仅用于尺寸定位，不能当作 raw 绑定正例或完整成功包。

已足以阻止把这份旧 wire 成功素材作为实施前提。更一般的所有合法 runtime 最小长度证明，应由 B 在下述审计中列出固定键、固定长度摘要和可变字段的下界，不能仅把一个示例推广为所有对象的数学证明。41 原件、44399 bytes、五个 provider seed 仍只是作者阶段素材，完整索引、闭合和预算尚未验收。

## 技术方向与先后顺序

1. **先完整审计尺寸，再形成一个固定增量包。** 同时检查 cap 的所有 primitive/status、ACK/RELEASE/DONE、其发送/接收 Request 与 Obs、CallRaw、payload BytesRaw、setup chunks；对 case 对应分支单列影响。记录每层 canonical 实际 bytes、上限、引用重复原因、最大实际素材和仍缺素材，不用随机短值声称所有允许值都可容纳。旧 2048/8192/64/1MiB 等限制保持；合法但太大的输入仍必须拒绝。
2. **采用严格 typed artifact 引用方向解决重复的大 Request/Obs。** 优先评估一个 exact payload 原件同时保存完整 Request 与 nullable Obs，减少两个独立引用及 wrapper 的开销；Operation 保留完整 Step/rc/errno/timing/status/reason。B 给出唯一 discriminator、有限 primitive/context allowlist、exact 字段、原件 kind、摘要域与绑定规则，不能把引用解释成任意字典/自由解码器。若独立双原件确有必要，须用实测尺寸和绑定复杂度说明再交 R。
3. **明确尺寸约束的计量对象。** 2048 约束序列化后的 Operation carrier；被引用 payload 按真实原始 bytes 计入既有单原件 8192 和同一全包 1MiB。展开后的语义 DTO 仍按原 exact schema 逐字段校验，新增展开视图的大小/节点/深度上限和缓存、递归工作量必须显式有界。不能声称展开对象也小于 2048，更不能用引用或重复展开规避原件总预算。
4. **保持全部语义与来源。** Request 仍须等于每个 CallRaw 的完整 Request；Obs 仍从对应 raw/Steps 验证。不能省五个 Step、改 union 成伪 runtime 子操作、删 SHA、折叠不同观察或赋予 native 资格。缺失、错 kind、混用 inline/ref、错 primitive/status/reader/object、错 producer/context、嵌套前向/同帧/环/跨 cap-case 引用均拒绝。原件在 frame 之前完成，不能携带本帧或未来 cap/manifest 摘要；Index 的 producer 关联不得制造原件自反边。
5. **按实证限定变体范围。** 初始目标是 cap-only。不得通过 `phase`、自由 scope、调用方开关选择 cap 资格；由已核外层合同和消费图决定。若审计显示 case 的既定必需操作也无法表达，应一起报告具体反例和最小兼容方案，不擅自扩展到 case，也不能以 cap-only 修完掩盖 case 缺口。schema/version 和旧 inline 兼容关系必须写清，不按恰好长度动态猜格式。
6. **先审矛盾与载体，再审完整素材。** 不再要求 B 先交一个已证明当前表达无法容纳的旧 union 成功包。先把尺寸审计、精确变体和一个完整 runtime 原件/引用/raw 闭合示例固定提交，交原 R 做增量静态审核；此阶段不批准 parser 新语义。随后在获认可方向上完成全有限 cap 链，重算每个 SHA、帧编号、FD 生命周期、全部嵌套引用与预算，并连同身份域 C7 回原 R 关闭剩余缺口。完整素材通过前仍不宣称全包 GREEN。

## 文件责任与证据

B 只修改本线 `B-016-native-pure-contract.md` 及专用 runtime 素材；原两个未提交实现文件保留，受新规则影响的 parser/test 实现继续等待。既有 43 个组件方法不重复执行或充当全包证据。新方向不需要增加 syscall、采样、真实网络、付费调用或生产权限。

各阶段使用新目录和实际源码快照，保留旧反例及失败；源 SHA、原件目录索引、canonical 尺寸表与审查范围一起交付。人工门禁仅按根 [AGENTS.md](../../../AGENTS.md)；后续如确实需要改变已批准安全边界，由协调者另行判断，不能借本技术方向扩权。
