# A026 分阶段启动候选与不变总预算

2026-10-05，Asia/Shanghai。接续 A026-POSIX-S01-QUALIFICATION-PACK-001；A025 固定 `92a9feeb7c4dd35403956a5aaedd894221ded6bf` 及原 R `de9591f77c1e5176fc21131123ef1582f0dbd7e8` 只批准原静态方案。本文件是协调者对尚缺 launcher 的技术候选定向，须形成新固定包交同原 R；不把旧批准延伸为新启动拓扑通过，不分配或执行资源。人工门禁只引用根 [AGENTS.md](../../../AGENTS.md)。

## 已核问题

A 的未编译提案先从 hard AS 至少 192 MiB 的父进程 fork 三角色，最后才降父层至 64 MiB。若入口已硬 64，则无法提高 worker 到硬 192；若入口未精确受限，预启动无界；即便精确硬 192，先派齐三角色也会达到父192+worker192+guardian64+auditor64+server预留64=576 MiB，超过448。C语言、小baseline和namespace768均不能消除此缺口。

Linux [getrlimit/setrlimit 文档](https://man7.org/linux/man-pages/man2/getrlimit.2.html) 明确非特权进程只能降低 hard limit，fork 继承并跨 exec 保留；因此修订必须只用合法降低，不能增加能力、setuid 或提权。

## 待独立审查的固定顺序

选择**仅 S01 的分阶段初始化候选**。初始化阶段父进程明确计为192 MiB，此后同一 PID 不可逆下降到64；不再声称父进程全程硬64。其余角色预算、未启server预留、总448、namespace1CPU/768MiB/pids16、UID1000、私有guest ROOT及所有时间界不变。此为原未决启动能力的局部方案修订，尚非运行授权。

| 阶段 | 已存在/预留的精确 AS 上限（MiB） | 合计 |
|---|---|---:|
| INIT | native父192；server预留64；worker/guardian/auditor均未出生 | 256 |
| WORKER_FORKED | native父192；唯一worker192；server预留64 | 448 |
| PARENT_DROPPED | native父64；worker192；server预留64 | 320 |
| GUARDIAN_FORKED | native父64；worker192；guardian64；server预留64 | 384 |
| ALL_STARTED | native父64；worker192；guardian64；auditor64；server预留64 | 448 |

1. 最外 T0 先于 native exec。root 未来资源入口必须在动态加载前设精确 soft=hard192（201326592），不是无限或仅 ≥192；不能来自既已 hard64 的测试父层。未取得此受控入口、UID/profile/compiler/binary/实际分配证据仍 BLOCKED。当前不新增控制器、特权或容器动作。
2. 入口仅固定 argv、信号、有限管道/FD 设置；不读 packet/ROOT/proof/credential，不启动 Python assertion/server/额外 helper。有限内存及所有 FD 均在192额度内。先仅 fork worker；worker继承并读回精确192，保持原有限 READY 等待，不开始采样/真实工作。
3. 父进程在第二次 fork 前 setrlimit 软硬同降64，并立即 getrlimit 严格核对。失败、缺读回或超时直接进入本次有限清理；禁止继续创建 guardian/auditor。不能用事后最终64读数替代下降发生顺序。
4. 降限成功才顺序 fork guardian、auditor，二者从 fork 发生时即继承 hard64；各自 pre-exec/exec继承/readback仍按原四层取证。不存在它们短暂继承192后再降低的隐含阶段。
5. 三角色 READY 与父层降限证据及启动身份齐全后才允许 SAMPLE/PROBE。两次独立sample/exceed沿原窗口执行，不能拿一次的顺序或限额证明另一次。
6. 每个失败前缀都登记实际成功 fork 的 PID/start_identity、确切FD/close状态、真实waitpid与尚未出生角色；不能对0/-1/未登记PID发signal。fork/pipe/limit/readback/日志失败不补起或重试。25/26/29/30秒仍从同一最外T0计算；收据写入阻塞也包含在内。

这是每阶段上限之和，不是RSS或观测baseline之和；server64即使未启仍扣款。真实phase证据需连续序号、角色PID及启动身份、limit-before/set/readback、原T0时刻与唯一合法转移，无法确定先后则unknown。任何额外常驻init/监督/测试进程必须明确纳入预算；不能用固定外层宿主工具存在为由偷偷加入guest helper。

## 原作者交付与原 reviewer 检查

A 保留当前原草案/runtime字节作反例，用新revision文件或新子目录形成此候选；同步qualifier、四方法断言、manifest、normalizer和报告，旧core/38tests/12机器合同不变。不把本文件当采纳源码或授予资格。

新增有限静态阶段表与应捕获mutation：父从hard64起步；入口无限/高于192；先fork低额角色；worker后父未降或读回失败仍fork；guardian/auditor实际继承192；额外角色；丢失阶段/顺序/错误PID；INIT失败或worker-only失败清理；迟到READY；sample/exceed错用收据。保留原四方法及32总case，可追加必要资格方法/参数但不以声明数冒执行通过。对旧先三fork草案作静态反例，不能称真实OS RED。

本轮只源码、JSON/AST/hash和有界静态算术，不编译、执行候选/测试、OS probe、fork/AS/FD、container/VM或网络。固定commit/source/index/receipt后同原R审完整新包，先解决实际bootstrap边界、全部失败前缀和计数，再由root决定是否采纳并准备新资源包。S02、P16完整双launch、持久许可和真实采集仍未完成；GB日期窗、F03分母、网络预算均保持。
