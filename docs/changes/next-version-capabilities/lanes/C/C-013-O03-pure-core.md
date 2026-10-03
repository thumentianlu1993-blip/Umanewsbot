# C013 O03 来源无关纯 leaf

状态：纯 leaf 已实现并完成本地离线 RED→GREEN；待 root 送原 R 代码 review，未合并/发布。仅拥有 `server/stable/services/public_probe_contracts.py`、`server/stable/test_public_probe_contracts.py`、本文件。起点 `0bde91b1`；依赖 F01 固定 `06b01aea9041eacb3deae9f46968eb06fd459cb6`；C012 原 R 审核 `10fa4d99a9dc0f24793d86cf46cabf478ba301b0`。不依赖待修 A013。

## 冻结叶子合同（实现前记录）

输入仅严格 JSON dict/string，F01 `_read` 负责禁止自定义容器、重复 JSON key、非有限数、循环、深度>64、节点>100000、编码>1048576 bytes。批量 receipts/events 最多256项；不截断、不跳分母。所有 schema 字段 required，未列出字段拒绝；nullable 只表示未知，不推导为成功。返回 frozen wire DTO，to_dict 为脱离副本，不保留调用者可变对象。复用 F01 `_entity / _version / CAPABILITIES / _time / _hash / _count / _read / _encode / _sha`，不复制公共 enum/wire guard；这些当前为私有纯 helper，后续 root 可统一公共出口，本线不改 F01。

外部 `anchor`：`scope_ref,candidate_sha,expectation_sha,input_version,entity`。scope非空，candidate/expectation为小写SHA256；F01实体和input_version完整形状验证；entity规范化一致。anchor必须来自调用方独立固定对象，不从receipt回显构造。shape/digest绑定不授予抓取/发布权限。C工作树没有F01，测试运行目录按固定Git blob提取依赖，不复制到本仓库文件。

API一 `compare_public(expected, receipt, *, anchor, as_of)`：

- expected：`schema_version=o03.expected.v1,scope_ref,candidate_sha,input_version,entity,capability,surface_ref,audience_ref,generation,revision_ref,permission_version,content_digest,visibility`。完整expected规范wire的SHA须等于外部expectation_sha；entity/input_version与anchor一致；capability复用F01；visibility=visible/withdrawn；revision/permission/digest nullable，其余非空字符串。generation显式稳定引用，不从时间推断。
- receipt：`schema_version=o03.read.v1,scope_ref,candidate_sha,expectation_sha,input_version,entity,capability,surface_ref,audience_ref,generation,receipt_id,request_started_at,response_completed_at,clock_error_ms,status,complete,conflict,denial_verified,marker,body_digest`；marker nullable，否则严格含 `revision_ref,permission_version,content_digest`（三项nullable）；body_digest nullable；status整数100..599；三个bool严格类型。仅接fake已规范化摘要，不解析HTML，不声称真实字段映射存在。
- 引用绑定不符/非法输入稳定ContractError；缺证、unknown钟误差、截断、冲突、marker/body/expected版本摘要不一致返回 visibility_unverified。全部一致且HTTP200才public_read_verified；withdrawn只接受新权限版本正确403/404拒绝、denial_verified=true且无资料body/digest，返回withdrawal_verified且public_read_verified=false。公开实体未verified/canonical未绑定不通过。
- as_of 与所有时间用F01严格UTC Z；start≤end≤as_of，未来/倒序拒绝；clock_error_ms nullable非负整数。保留request原始有证区间与误差，SLA固定unverified，不计算met/late/复制A013时延数学。

API二 `evaluate_cycles(policy, receipts, *, anchor, as_of)`：

- policy：`schema_version=o03.cycles.v1,scope_ref,candidate_sha,expectation_sha,epoch,epoch_started_at,period_ms,consecutive_misses,clock_error_ms,host_watchdog_bound`；period/threshold>0；epoch显式实例引用；clock nullable；host bool。
- receipt：`receipt_id,scope_ref,candidate_sha,expectation_sha,epoch,started_at,completed_at,coverage_complete,all_healthy`；completed nullable，all_healthy nullable bool，其余required；only started/partial coverage不满足完成槽；completed含失败可证明执行活性，但不等业务健康。
- 期望槽为 `[epoch_start+jP,epoch_start+(j+1)P)`；as_of减policy钟误差后才算槽关闭。completed在本次started所在槽且完成时间±（注入总误差）整体落在槽内才有槽完成证据；右边界属于下一槽，跨槽不回填。按最后关闭槽向前连续缺槽计，不按收到几条失败计。小于阈值但有缺槽为gap，不健康；达到阈值stalled；无关闭槽not_evaluable。未知clock直接unknown。
- same receipt_id同内容幂等；同ID异内容冲突；唯一条目started有序、同start按ID有序；未来/旧epoch/epoch开始前/倒序拒绝。同一槽两个可证明completed拒绝，不任取一个掩盖冲突。host绑定缺失始终host_unverified，即便执行fresh不证明宿主失活可发现。

API三 `reconcile_episodes(events, *, anchor, as_of)`：

- 输入有限有序不可变历史，事件字段 `event_id,scope_ref,candidate_sha,expectation_sha,recorded_at,generation,supersedes_generation,required_reasons,checks`；supersedes nullable；required_reasons非空排序唯一字符串列表；checks键须完全匹配，每项healthy/unhealthy/unknown。这是O03本地核验结论，不复制F01执行状态enum、不做发送。
- 按 `(recorded_at,event_id)` 严格有序；同ID同内容重复忽略、异内容拒绝；未来拒绝。同代际required_reasons不可变；新generation必须显式supersedes当前代际，旧代际回流拒绝，旧开放episode保留为open并记录superseded_by，不标恢复。
- 每代际单episode：初次任一unhealthy/unknown产生OPEN；相同原因状态/纯时间推进不CHANGED。unknown不能抹已知unhealthy；部分healthy可实质CHANGED但其余unknown/unhealthy仍open；只有全部required检查healthy才RESOLVED。重开增加episode序号，保留旧历史；generation后继不删除旧开放问题。输出事件是纯事件建议，不是投递证明。全历史重复调用输出相同，不持久化。

API四 `check_budget(budget, usage)`：

- budget：`targets,period_ms,request_timeout_ms,overhead_ms,request_cap,wire_cap,decoded_cap,cycle_cap`；除overhead可0外严格正整数；usage为≤256项，每项 `request_bytes,wire_bytes,decoded_bytes` 非负整数。N必须等usage条数才能coverage_complete，不截取分母；空/不足为coverage_unknown，超出为count_conflict。
- 可行性 `N*t+k≤P`，每请求request/wire/decoded≤各cap，cycle=sum三类计量（保守同时计wire和decoded）≤cycle_cap；等号可行；所有整数复用F01计数上限且拒绝bool。fixtures数值仅验证算法，不生成生产配置/每日成本宣称。

## 测试设计、mutation与范围

| 组 | 核心及负例 | 必须抓住的mutation |
|---|---|---|
| public | 全匹配、旧body/marker、权限/audience漂移、unknown/截断/冲突、拒绝撤回、immutable、strict JSON/引用/时间 | 去掉body比较、用管理面替代匿名、NULL当成功、403当公开成功、重算receipt自带锚点 |
| cycles | 半开边界/误差/缺槽、started与partial、失败completed、epoch/顺序/ID冲突、宿主unknown | started续命、failed当healthy、错用收到条数/右边界、忽略epoch、unknown当PASS |
| episodes | OPEN/静默/实质CHANGED/部分恢复/全恢复/重开、unknown保持、后继保旧、乱序/未来/ID冲突 | 每轮CHANGED、unknown关闭、部分关闭、代际换key丢旧问题、重复回执重开 |
| budget | 等号/不可行、三类bytes/总额/条数、bool/未知/负数/上限 | 忽略decoded/总额、预算跳分母、bool当1、超限截断 |

使用仓库tdd技能；每组先运行明确行为缺失的RED（stub返回unimplemented而非导入错误），再实现该组GREEN；原始命令、stdout/stderr、退出码与阶段文件SHA保存在专用runtime目录。仅unittest及F01必要回归；无Django setup、DB/Redis/PG/容器/HTTP/真实解析/调度/通知。根test映射不修改；proposal与证据收尾补本文件。

G1已由root派单覆盖上述来源无关范围；本轮不涉及共享主线或生产，G2/G3未执行。R01/O01/O03真实依赖仍未闭合；离线通过不等TC-O01、自然窗口或送达验收。


## 已完成实现与本地证据

四个API及不可变wire DTO已实现；第五组边界测试额外捕获了 `True == 1` 可误过版本比较与wire DTO接受dict两项真实缺口，已复用F01严格version校验与wire_string guard修复。输入没有修改；无额外依赖、公共enum副本、A013数学或业务接入。周期结论为当前连续尾部缺槽/活性，不能作完整自然窗口覆盖率；episode全历史重放返回确定建议，调用方仍须后续批准的持久化去重/投递适配，本文不承诺投递幂等。

运行目录：`/Users/mentianlu/.codex/runtime/c013-o03-pure-core-001`。固定F01 Git blob与fixture仅位于该目录；该目录包含阶段原始log/json收据、capture.py和最终源/测试字节。第一次capture工具遗漏text模式导致日志保存错误，不计RED；修复采集器后才保存下列有效RED（没有修改对应stub）。

固定运行命令前缀：`python3 /Users/mentianlu/.codex/runtime/c013-o03-pure-core-001/capture.py <phase> <unittest selectors>`。capture实际运行当前Python的 `-m unittest -v`，PYTHONPATH仅设固定运行目录/server；不加载Django。

| 组 | selector / 有效RED | GREEN（含直接相关回归） |
|---|---|---|
| public | `stable.test_public_probe_contracts.PublicComparisonTests`；exit1，unimplemented!=公开/未验证结论、缺绑定拒绝；7 tests，24 failures/1 error（stub缺结果字段） | 同selector；exit0，7 tests |
| cycles | `stable.test_public_probe_contracts.CycleTests`；exit1，缺槽/类型拒绝缺失；7 tests，9 failures/5 errors（stub缺结果字段） | cycles+public；exit0，14 tests |
| episodes | `stable.test_public_probe_contracts.EpisodeTests`；exit1，历史/代际/冲突拒绝缺失；7 tests，8 failures/5 errors（stub缺结果字段） | episodes+cycles+public；exit0，21 tests |
| budget | `stable.test_public_probe_contracts.BudgetTests`；exit1，unimplemented!=budget_exceeded及类型未拒绝；5 tests，37 failures | 本模块；exit0，26 tests |
| boundary | `stable.test_public_probe_contracts.BoundaryTests`；exit1，bool代际误过、dict wire未拒绝；6 tests，2 failures | 本模块+`stable.test_content_contracts`；exit0，49 tests（32本线+17 F01），0 skip |

原始日志分别为 `{public,cycles,episodes,budget,boundary}-{RED,GREEN}.log`，同行json含真实退出码、完整命令、日志SHA与阶段源/测试SHA；errors是合法stub未产出约定结果字段，不是导入/环境错误。有效RED均同时有明确AssertionError行为缺失。最终49项只证明fake规范输入与纯算法；不是Linux交付CI、实际HTML合同、来源首发、真实worker/Beat/probe/宿主停摆、通知送达或自然窗口验收。

最终源SHA256 `a5222f5a47fb9ab9fd3ec66446cc9b0fb32ceffa19d4eb9e23fa43356ae1927f`；测试SHA256 `d5239507d3f3620e563850cfd7438fd81c7c8f5f31ed6eaab943046b2327189d`。固定F01源SHA256 `e804296a73436700581e76cff33f0005ac080b7465944373b5ed4956185d1d2d`，回归测试 `e6f49f701e327afc9484c23098f2e263677f41a7e0ad9476d9a1de25a35ac76f`，fixture `4df8008fcf203c413721a1600afc6206ad4fe8f269bd3035d807e4e2eff77f89`。静态AST确认仅标准库与F01 imports；运行目录最终字节与受测代码一致。

## test映射 proposal（由root整合，本线不改根映射）

新增 `server/stable/services/public_probe_contracts.py` 与 `server/stable/test_public_probe_contracts.py` 的受影响选择建议为 `stable.test_public_probe_contracts` 的 PublicComparisonTests / CycleTests / EpisodeTests / BudgetTests / BoundaryTests，以及固定F01 `stable.test_content_contracts.ContentContractTests`。当前C分支旧基线无F01，root整合须绑定含F01的固定候选；不能直接在本线环境导入后误称生产模块可用，也不能因映射缺失回退旧full/Django suite。每组测试目标mutation见上表；未运行mutation引擎，不声称已取得mutation score。

剩余：原R代码review与返修（如有）、root映射/固定综合CI；O01/R01/O03外部依赖与C012列出的真实合同/资源/覆盖/通知验收均未闭合。未修改现有service、models、migrations、hooks、views/templates、根映射或共享状态。

收尾静态/治理检查：`git diff --check` 通过；`.codex/scripts/check_workflow_contract.py` PASS；`.codex/scripts/test_workflow_contract.py` 4 tests通过（与49项纯合同测试分列）。本地Python 3.14.6。
