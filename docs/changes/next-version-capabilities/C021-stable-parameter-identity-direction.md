# C021 固定参数身份与同一行 lambda 的技术定向

2026-10-05，Asia/Shanghai。接续 `C021-STABLE-PARAMETER-ID-GREEN-PACK-001`，只修测试 worker 的观测身份；冻结 source `433e0cfef1a19f9f2e8feddbd54d33fa91bc621c`、原测试/业务/fixture 均不改。旧 run40d0 的 product_green_eligible=false 不回写。

## 核实的具体反例

625 次原始调用中的32项携 lambda repr 内进程地址，另593项逐位置一致。32项来自五个固定方法；其中 `test_public_probe_render.py` SHA `b74b685e045c63633f2f8a89b1c24e537ceeb968c89161bdb78c5d1c5986415e` 的第252行包含5个 lambda，body 列范围依次 `[30,41)`、`[51,62)`、`[72,116)`、`[126,172)`、`[182,239)`。它们 firstlineno/module/qualname/name 相同，仅靠这些值无法区分。B/C 源码不因此更换写法。

固定静态清单位于 C 新 runtime `static-lambda-catalog.json`，SHA `7b39bcffd64083e580011f931287977d3039d11a2ccd2e3b8538244513f3f94b`，ROOT 已核 SHA、冻结源与五个 AST/body 位置。原 ContentContractTests 其余27个 lambda 的独立行号仍核。

## 允许的有界元数据方法

采用实际函数的 exact FunctionType/CodeType 与 `co_positions()`，将源位置绑定到预先冻结的 AST。Python 文档说明位置为 `(start_line,end_line,start_column,end_column)`，列为 UTF-8 字节偏移；某些位置可能缺失，不能假定永远可用。[Python 3.12 文档](https://docs.python.org/3.12/reference/datamodel.html#codeobject.co_positions)

- 白名单仍只有固定5个方法、对应 mutation/edit 参数、32个 lambda 源节点。先核测试 source bytes/SHA、模块/qualname/路径与 CodeType；不读取任意对象的属性、不调用参数函数或用户 hook。
- 实际代码位置须唯一对应冻结 AST body 范围，除允许的人工/零宽位置外所有非空指令范围必须落在该 body 内，且合并覆盖范围精确匹配 body 起止。不能仅凭某一个恰好落在区间的点就接受，也不能只凭 invocation ordinal 宣称 lambda 身份。位置缺失、无法排除多个节点、跨 body、边界不符或未知格式，验收失败；不回退地址/单行号/宽泛正则。
- 为明确人工位置/零宽规则并拒绝错误映射，可从相同固定测试 bytes 在**同一解释器**只编译得到 CodeType 元数据，与实际 CodeType 的位置向量及必要的有界 code metadata 比对。compile 结果绝不 exec/eval、构造函数或调用，不导入测试/候选。source 与 AST/清单来自预先冻结输入，不能从待验收实际函数生成预期。
- 本卡明确允许最多这两个已冻结测试文件的 **compile-only 元数据准备**，遍历受限 CodeType 常量树并只提取这32个 lambda；不执行任何编译结果，不导入业务/helper/worker，不跑测试或容器。编译不属于行为 RED/GREEN。输入长度、code tree 节点/深度、co_code 字节、位置条数/字段值均给固定上限；超界拒绝，不无限 list 化 iterator。
- ROOT 在宿主 CPython3.14.6 仅编译冻结 render 测试字节、未执行，观察五个代码对象的非空范围确实覆盖上述五个 body，条数10/10/20/20/20；这是该宿主的方向验证。固定执行镜像实际为 CPython3.12.3，不能将宿主字节码/位置向量当作3.12的执行证明或硬编码到实际验收。独立预期须使用执行解释器在固定源码上的编译元数据，或使用经证明与版本无关的 AST 范围规则；原 R 审清楚后，实际目标解释器核验随新固定窗口进行。

## 保持验收强度

实际报告逐项保留原 raw id/status/error，另记录 stable identity 与来源元数据。预期625稳定序列在执行前冻结：固定源码身份/AST位置、方法与参数键、其余参数值及原序号联合校验；list/str各两次的原 multiplicity保留。32项不能合并为5个函数标签，另593 raw ID不放宽，不把真正 operand、源码或lambda顺序差异规范化掉。

补有界元数据负例：同一行换另一lambda、同qualname/不同列、重复或漏节点、缺/错位置、人工位置全占、跨body、错误source/路径/module、其他callable、改变非函数参数、位置/次数/顺序不符。无 candidate/helper/业务执行的静态材料应明确计为元数据证据，不冒实际625调用。

本修订仍需完整新 manifest/worker/index/稳定清单及原18项业务验收条件保留证明，交同原 R；实际新窗口由 ROOT 另分。原 runner尽量字节保持，原114测试、102目标/12controls、72三元组、25正例、13+5基线、3meta、58budget/78oracle/54输出摘要与所有资源上限不变。当前无新执行分配。
