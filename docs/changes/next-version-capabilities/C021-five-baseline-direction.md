# C021 五项基线缺口的技术修订方向

2026-10-05，Asia/Shanghai。协调者依据固定 C `b4e50eb1` 报告、source `12e5d432`、manifest `6164e08d` 的实际单次 run `4d8ed160`、冻结 contract.priority 与 golden mutation 逐项核对。人工确认仅引用根 AGENTS.md；本轮是现有离线测试与合同一致性修复，不改变公开产品规则、真实来源或生产权限。

## 事实与裁决

旧 113 方法运行得到 102 目标失败加 5 非目标失败；完整目标 RED 无效。private 预算和算术参数确已在原资源内通过，旧材料、源字节和收据保留。下面前四例的输入确实同时触发更早错误；N64 则在补缺失 helper 时发现原预期与允许空数组的 schema 不一致。冻结 contract.priority 与 adapter._PHASES 一致。不能为满足旧 golden 改全局优先级、跳过前置校验或把任意拒绝当成功。

| 保留原 ID 和 mutation | 更早冲突及规范主结果 | 独立补充覆盖 |
|---|---|---|
| N07，向四行表追加首行副本 | cardinality 变五行；rank6 的 row_cardinality 在 duplicate_row 之前。新派生预期为 unverified/row_cardinality/6。 | 另造相同行数的重复 token，例如用首行副本替换最后行，保证更早 profile/binding/结构有效；独立要求 unverified/duplicate_row/6。 |
| N23，只将第三马名改为双重 HTML entity | 同 token 的 table 与 podium 值不一致，rank6 related_role_mismatch 先于 rank7 content_mismatch。新派生预期为 unverified/related_role_mismatch/6。 | 对该 participant 的所有相关可见马名同步做同一双重实体变异，保持关联角色一致；独立原始 evidence/expected body 不变，要求 unverified/content_mismatch/7。 |
| N26，向 body 追加 script | 新脚本同时违背冻结 calendar script 的结构位置；rank2 invalid_structure 在 unexpected_script 前。新派生预期为 rejected/invalid_structure/2。 | 另造结构位置有效但类型或属性未授权的脚本，例如仅给原合法 calendar script 增加语法允许但合同不允许的 type 属性；要求 rejected/unexpected_script/2。原 body extra-script 反例仍完整保留。 |
| N72，只截 private template_context 的 results/top_results 并重算 context SHA、重新渲染 | 原完整 profile 仍要求 podium，渲染缺角色；rank4 role_structure 先于 rank5 origin_permission_unbound。新派生预期为 unverified/role_structure/4。 | 独立补充只截 private template_context.results 为首行并重算 context SHA；完整 top_results、winner、原 HTML、独立 evidence/origin/profile/expected 均保持。reference 仍含 podium，通过 envelope 后由行数与 participants 绑定拒绝 unverified/origin_permission_unbound/5。 |
| N64，context.targets 改为 [] | 旧 helper 未分支即抛 assertion，未实际进入 adapter。冻结 targets 为 array/minItems=0，空数组通过 schema，但原 scope_sha256 未重签，先触发 rank4 membership_mismatch；新派生预期为 unverified/membership_mismatch/4。 | 补精确 context_patch 分支，只改 targets=[]，不得重签 scope 或从 marker 补回 required 集合。第五个独立参数只改 targets=None，其余输入不变，要求 unverified/context_schema/3。 |

上述补充是构造方向；作者须证明每例前置条件与身份绑定未产生未声明冲突，原 R 复核后才执行。遇到与冻结规范无法相容的确定反例回协调者，不自行挪动判定顺序。

N72 补充构造于 05:54 按作者反例更正：若同时截 results/top_results，即使保留原 HTML，reference 模板的 `top_results|length > 1` 条件仍会移除 podium，`_envelope_tree` 仅遮罩已有 podium 的内容，不能遮罩角色有无差异；会先触发 rank4 `unmodeled_visible_content`。因此补充仅截 results。原 N72 的双字段截短及重新渲染保持原样。此更正依据冻结模板、`_full_envelope` 和 `_bind` 的静态控制流，不宣称补充已经实际运行通过。

N64 于 06:08 完成静态定案：`_schema_matches` 明确拒绝非 array 的 None，但允许长度0；`_full_envelope` 在索引第一个 target 前调用 `_membership`，后者先核 scope 五字段摘要，再检查非空。root 对旧执行包的固定 v4 card 基线用独立 JSON/SHA 计算得到原摘要 `a2f291a58509c083a6aca92fb55435c4311e05c1b950cfa2e105ce936ca5b6e2`，只改 targets=[] 后为 `0172e936ed87b032fe3b1286b37893b02a1b1b6551fea93c73ae08db6f674e24`，因此原摘要必然不匹配。作者的新派生身份须另算对应摘要并保留 lineage，不套用旧包值。本项修正不执行候选、不新增 scope 重签、不调整 schema 或优先级。

## 不变项与实施边界

- 保留原 72 个行为 ID、base_case、mutation 内容，3 个 meta、25 正例、13 review baseline、114 HTML mutation/102目标/12控制、原94方法/54输出/4反例，所有原件和失败日志不覆盖。原五 case 的旧 expected 留在不可变旧包，并为每个修正记录旧值、新值、冻结 priority/schema 依据和 lineage，不用简单字符串全局替换。
- 新派生 golden 只改上表五个 expected 主结果，并按来源内容变化重新计算完整 candidate/descriptor/源文件绑定；其余业务内容逐值保持。不能修改独立原始 evidence、origin、许可、公开 schema、原优先级表、adapter、预算/算术 helper 或 HTML 两 P2。
- 当前源的行为测试增加单独的补充回归方法，至少五个固定参数，分别严格断言原先五个 reason/status/rank、receipt absent/C013 not_constructed。新增方法计入分母，不继承加载、不替代原 72；实际计划至少114方法，新增参数和输出单列。保留原失败样本，修订说明解释测试 bytes 改动。
- helper 只实现 N64 缺失分支及上述独立补充输入构造；补充输入由有限固定规则生成，不看 adapter 输出选择策略，也不从 expected 反写 observer 输入。先固定测试/构造规则，再形成审包。
- 执行包的验收从原 16 个 required pass 扩到包含补充方法；必须原72全部实际输出并逐值匹配，补充五项全部严格通过，102目标的真实断言失败和 receipt/body_digest witness、12控制与所有既有基线都保留。记录方法、参数、断言和 ledger 数量，不能用总 exit1 代替目标 RED。
- 本轮仅允许本线测试辅助文件、测试文件、派生合同/身份材料、自有 runtime/报告的静态改动和 JSON/AST/hash 核对。固定新包先交同原 R 审新增 oracle、输入因果、来源守恒和完整执行包，再由 root 实时核资源分配单次新窗口；旧已消耗窗口不能复用。本轮不运行 Django/adapter/render/业务测试/算法/容器或 native，不修两项 HTML P2、不执行 GREEN。

责任归 C；协调者只维护本方向与台账，原 R 只读审核。各线不写其他线程工作树。该方向不改变全局优先级、业务接受结果或 fail-closed 边界。
