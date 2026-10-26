# C021 目标解释器身份表示兼容方向

2026-10-05，Asia/Shanghai。仅处理测试证据工具的元数据表示，不改变产品、HTML规则、测试输入或分母。人工确认仅引用根 `AGENTS.md`。

## 固定事实

诊断报告 C `451909fc00b1028ade73759b3cb990b8b2662328`、manifest `7594020918572f3a07f6d5fc16bbd5e8620ef3340a45a73d48701fdaa7227cd3` 的一次目标 Python 3.12.3 运行已完成，原始 report SHA `96f4fad652c3c2ebfc5239fdf1e63829a1eb71bce4f0a99691fa92b0d9be85a0`。32 AST 和 32 CodeType 观察收齐，业务/生成代码执行为零，身份与 GREEN 资格仍为 false。

32 实际 AST 文本包含空列表字段，宿主 3.14.6 的期望文本省略它们；节点类型、完整 `_fields`、字段和值记录逐一相同。32 CodeType 各有一个候选的拒绝原因仅为末尾 `RETURN_VALUE` 的 `(line,line,0,0)` 位置。原有首 `RESUME` 零宽例外仍在；共有 64 零宽、0 None。此关系是拒绝证据，不是已获准的身份匹配。

ROOT 08:54:27.535235 独立核 CID 不存在、nonce/running/本任务 runner 均为零、1928 源文件 SHA 与路径全集不变，无关 exited 容器保留；postrun `/Users/mentianlu/.codex/runtime/c021-root-resource-7594-001/postrun-5d0a.json` SHA `579a05134dd36aced045566cadaf10f27b4f59d0f6bf218ca9f3705729de1a68`，资源已释放。旧诊断和失败包冻结。

## 唯一候选方向（本卡只准备方案）

1. 固定当前源、目录和 32 条 stable catalog，不重算旧 stable ID，不按 ordinal、执行先后或最接近分数建立身份。源 SHA、精确 lambda/body span、源片段 SHA、qualname/filename/firstline、全候选唯一性、body 覆盖保持硬条件。
2. AST 身份比较使用版本化、显式的完整节点结构表示。固定节点类型、字段名及顺序、所有空列表/None、标量类型和值、列表顺序与子节点路径；不得只删除空字段、用字符串替换改 dump 或忽略未知字段。原宿主 dump SHA 作为既有 catalog 的固定来源记录保留；新增结构表示与其同一固定源/位置/片段一一绑定。目标表示必须完整相等，跨版本新增/缺失/类型变化仍拒绝。解释器/image/source 绑定不能被结构相等替代。
3. 仅为已固定目标 Python 3.12.3/image 评估一个新增的编译器位置例外：准确最后 codeunit 的真实 `RETURN_VALUE`，位置严格为 `(co_firstlineno,co_firstlineno,0,0)`。需要直接从实际 CodeType 字节和 dis 指令交叉证明 opcode、末偏移、完整 codeunit/positions 对齐；不能相信报告中的 opname 标签。只能恰有一个末返回位置，保留现有首 RESUME 例外。其他 None/零宽、非末位置、错误行、错误 opcode、未知解释器、CACHE 零宽或位置不一致均拒绝。
4. 除两项精确编译器人工位置外，完整语义位置仍须落在精确 body 内并覆盖完整端点、无缺口；全部候选必须恰好一个匹配。不能以过滤全部零宽、只取最小最大值、弱化同一行五 lambda 的区分或改可见 ID 来通过。
5. 先编写独立的有限反例/后续 RED-GREEN 计划：完整结构相等与空字段差异、未知字段/标量类型/值/顺序变化；合法首末人工位置与伪 opcode/位置/字节长度/多返回/None/CACHE；同一行五 lambda、重复或不存在候选、source/span/片段错配。明确哪些是冻结观察关系，哪些须新目标窗口实测。旧失败不能改写为通过。
6. 输出单一可审技术方案、精确 schema/预算、纯元数据 helper 的拟变更范围及固定候选测试包计划。625 业务调用、既有完整 IDs、14 overlay、业务源和 HTML 输入保持；新的结构/元数据开销须明确计入现有预算，不自动提高上限。

此次不编写或执行新 matcher，不调用旧业务/helper、host compile、生成代码、测试或容器；只可读取固定原始 JSON/源文本，做 AST/JSON/hash/有限字节算术。C 只写自有报告与新 revision，旧源和诊断目录全部冻结。固定方案交 ROOT 与原 R 审核后，再决定最小实现和独立诊断/测试窗口；本方向不是 GREEN 或新资源分配。
