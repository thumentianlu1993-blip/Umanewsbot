# B057 冻结 E04–E10 七方法集中源码准备

## 基线与状态

固定基线 `50c39b918e794d963bc8de60c60a3bc40b82ab42` / tree `84a0876b775c4d2326a46fafcc19e26cb8c9f3d8`。B056原三项actual已由原R `f84d3ac207d627e12e6deae842537534ad06a317` 独立接纳，receipt SHA `bd5cf4388d01626332f2d32f2fd6451791e011a588c290042acc0c8d599d9bb8`，限定 `ACCEPT_ACTUAL_EXACT3_SYNTHETIC_GREEN_ONLY`。该历史证据不证明本新七条结果。

原B050 `fd7b0772` 的plan/test_design/evidence_map和B051十方法映射冻结不改。本候选集中补齐七方法及必要helper，十方法源码存在，尚未import/collect/native/PG执行。完整设计分母仍为10＋23＋2＝35，原23实际上是19条只读测试＋4条兼容回归；两个原SDK方法单列。obligations.json保留完整35 ID并区分原三项基线GREEN、新七条未知及旧25回归未重跑。M02未完成。

隔离分支 `codex/b057-remaining7-end-to-end`；旧chat cwd失效，原生create_worktree返回Not a git repository，遂从指定精确基线执行git worktree add。未切换/回退旧checkout、PR245/main或C063 catalog/rules。已有G1授权覆盖本次测试准备；没有G2/G3交付/生产/真实provider动作。

## 真实fixture与变更边界

只修改test_managed_readonly_translation.py、新增readonly_translation_e2e_fixture.py及本中文映射。七方法追加在原三方法之后，原三方法与原共享fixture方法完整源码段保持字节。测试类增加无setUp的mixin，旧setUp/scope/user action/消息登记及原继承fixture不变；完整差异供原R审该继承变更。所有业务service/tasks/schema/0081、原23/两SDK所在五文件与基础fixture均按基线原字节核对。

每例先真实admin retry→OperationLog/due→selector/claim→登记；不手填目标read/model/checkpoint/final终态。首子场景复用原setUp文章，避免遗留due文章抢占batch_size=1；后续真实新文章/操作/root独立。普通task OperationLog/执行日志仍可能写，不声称全task零写。

真实ORM/正常schema/真实reader/真实provider解析、owner授权及保存路径保持。仅替换原closed SDK的有限wire/response边界（调用原实现或有限退出/屏障），broker边界原capture。存储故障在具体save/QuerySet.update处抛明确DB异常，其他写入调用原ORM；commit观察调用原update后注册on_commit或在实际final CAS后有限暂停，不伪造授权/成功。围栏负例仅通过真实ORM注入明确source/control/version/epoch漂移，grant通常调用原revoke接口；授权前持parent锁的特例在parent→read事务内提交真实grant撤销。没有provider.translate、read查询结果、claim/admission/save/final成功mock。

## 七条业务映射

| ID | 源码场景和真实断言 |
|---|---|
| E04 双质量轮 | 真实provider第一轮缺body，usage已提交后独立主连接synthetic receipt，第二轮成功；read1/request2、每create已提交预留和序号、同final免费重投。额外允许max_attempts3但两次独立对账后仍固定request2，第三wire0且无final |
| E05 tool耗尽/unknown | 登记后真实tool0策略漂移拒绝（固定tool1合同可先拒绝plan，不伪造耗尽ledger）；timeout前/后、reservation/read后退出保留真实inflight UUID/token和slot，重投不接管/重读/退款，SDK0 |
| E06 model unavailable | 缺SDK入口拒绝且业务字段不变/read0；合法有限SDK timeout在真实completed read后保留read_reference与显式model_start_unknown gap、reserved attempt；授权缓存可查相同结构化材料，不重读，撤权后不披露；Article无伪译文 |
| E07 model-started/usage unknown | CAS＋slot真正提交、wire前退出（create0）、SDK退出/timeout/缺usage、usage后response消费前退出；原owner、slot/read证据保留，甚至独立补known receipt也不能fresh接管，不重发、不应用 |
| E08 围栏 | read-completed和checkpoint-committed两状态覆盖workflow/query/result版本、source/body/pair、claim UUID、epoch、grant、deadline及schema/type/namespace/null；授权前真实PG锁等待中撤权或跨原deadline；授权后create前、usage后save前、checkpoint后final前独立连接撤权/跨期；final事务先锁写后grant worker真实阻塞并等待commit，先合法应用不逆转；已final后source/version/grant/deadline重投不披露旧receipt |
| E09 两worker | 从registered未读状态真实竞争，不能用预completed read掩盖inflight竞态；另从真实completed read竞争model owner。主连接真实parent锁与两worker实际阻塞图，释放后winner wire期间检查无业务事务/tuple/transactionid锁，败者退出不blocked/close活跃winner；至多一create/one final，重复消息same receipt、不重复业务apply |
| E10 存储/恢复 | plan/read reservation/read result/model attempt/model CAS/usage/checkpoint/checkpoint progress/final Article/final Run十故障点实际抛错，stage/cause明确，原子rollback/已提交账保留。checkpoint提交后退出及final事务失败均fresh免费apply无新read/SDK。metadata reserved键全次拒绝、真实wire未知控制字段不能覆盖plan；bool/float/UUID/SHA/time/缺多字段/未知namespace/大小节点深度/重复JSON严格codec；普通helper拒绝registered绕过 |

场景用subTest聚合，尤其E09读竞争与owner观察分开，第一业务FAIL不会被预设完成态隐藏。方法可有多个subTest失败记录，未来host不得把“七方法”误当“恰好七个FAIL”；须以真实report/trace逐场景判定。正常前置、schema/import/gate/连接异常为ERROR；基于正常真实返回/持久结果的目标断言不满足为FAIL。故障注入预期异常不算失败；已有行为正确可直接GREEN，不删除实现制造RED。

## 资源与交接

源码约束600/570/30总窗保持，max3PG＝主连接＋最多两worker，同时间没有第四连接；所有scope/PID/thread在各worker重新建立。实际pg_blocking_pids检查direct/transitive链、外来节点与循环拒绝，不用sleep猜锁顺序。8秒event/lock观测有界，worker statement_timeout10秒/lock_timeout8秒，finally释放本fixturegate并每thread join12秒、close_all；最多24秒join预算供30秒清理。网络边界在真实提交后观测，无持业务锁。新图判断8项纯AST合成校准不证明真实PG时序。

未实测总耗时，当前无证据要求扩大资源。建议原R先源码审，然后由ROOT按新SHA/tree安排精确完整七方法的一次实际窗口（不拆每个小case）；若实际570秒不足，保留报告后按方法技术拆分E04–E07、E08–E10两个独立窗口，max3PG/2workers和600/570/30各自不扩大。不能提前以更小分母声称完成35。

本轮只有新stdlib/AST静态校准、diff检查、源码/旧证据指纹与固定commit封存。未业务import/collect、PG/Docker/native/旧suite/SDK/网络/host/allocation。实际七方法RED或直接GREEN未知；下一实现严格由真实结果推进。最终仍须完整35及ROOT/C formal/full回归，真实provider、生产task/UI、费用、公开验收都未完成。
