# B286 P5退出同步前件窄修：源码与新身份准备

**SOURCE_REPAIRED / LOCAL_COMMIT / STATIC_ONLY / NOT_RUN。** 当前新 HEAD `ab651cecd940850a62afe04bfd74551cf9ad3887` / tree `377424d1d2aa02dc54b56077c8c8b2f13c5cb481`，parent bb871949877979226292033f0ab14f8d949cc6b7；只改 tools/test_impact/test_pg_lifecycle.py，103增2删，clean，未push。代码包含原P5故障前件同步和4个必要纯边界测试源码，均未运行。不是RED/GREEN、P5资格或整套组件通过，须ROOT核后交同一原R窄审。

## 先行勘误：B285实际stop4超过cap3

在编辑源码前已单独写 b285-stop-cap-erratum.json：B285原manifest.pg_ctl_stop上限3，实际保存句柄stop31/56/80/107共 **4次**，即4>3。它们不是重试，但原作者report“五方法上限保持”不成立，不能作本次结果结论。P5实际stop107、gate三项拒绝和PG_STOP_EXIT:1主因保持。B285 sealed report/raw/index及原R报告不改、逐成员复核不变；不把cap升4追认。原B285 controller/host/七CLI共9已知PID退出证据沿用，不增加新进程检查或外推全机证明。

## 单一责任及前置约束

生产 Session、host/runner/gate 均原字节不动。只在测试文件加入三个小型测试侧函数：

1. 保存句柄检查只接受同一 session.processes中的Popen、对应同一receipt/records项，以及startedTrue、reapedTrue、精确int -SIGKILL退出，且真实保存Popen.returncode同为int -9。不调用/改写poll、信号handler或returncode。
2. P5原os.kill(SIGKILL)后，调用原Session._wait('postmaster', min(原business_deadline,原deadline,monotonic+3), False)。只有真实数字wait/_finish确认-9及reaped才能继续，原最终两条断言未删减。无固定sleep、猜测poll次数、额外信号、PG/stop/retry、deadline重置。
3. P5直接cleanup及setUp中为此唯一方法注册的cleanup都走同一守卫；不满足上项就session.error(P5_EXIT_PRECONDITION_UNKNOWN)/persist_partial并raise，**不调用原stop_and_wait**。因此前件超时、错误退出或P5启动失败都不能从unittest自动cleanup绕入额外pg_stop。P1/P2/P3/P6a仍注册原bound cleanup，它们的方法与start AST保持原样；RealPGTests仍只有原5ID，顺序与gate/oracle不改。

成功前件下，Popen.wait已把保存Popen.returncode缓存为-9，原cleanup的poll直接返回该值，进入PG_EXIT_BEFORE_STOP分支，再按原数字wait/adopted合同回收，不可达原`poll is None`的pg_stop spawn。失败前件下，原cleanup根本不被调用。P1/P2/P3各最多一次stop、P6a无postmaster，故新五组件路径的stop≤3有**spawn前的结构约束**，不是后置gate销毁第4次spawn；没有加全局计数器、提升cap、monkeypatch Session或runner拦截。

该约束是源码推导、待审待实测。UNKNOWN分支刻意保留session.closedFalse和未闭收据，不伪造reaped/ECHILD/完整日志。它也不运行完整Session清理/日志归档，不能声称该分支得到完整cleanup或所有日志；未来若发生该分支，须原观察器如实记录失败、保留可得原件，只有获准owned容器外层合同可终结资源，不能把容器消失补写为Session回收成功。

## 预算与4个纯边界源

等待短上限3秒取原剩余business/deadline，不增加任何Session/host界限；P5保守startup≤60+确认≤3+cleanup≤30=93，仍在原每方法保守95/整套475估计内。475仅源码估计，不是内核调用/日志I/O墙钟保证。原600外层/540foreground/40cleanup/20reserve、Session570/business540/cleanup30、initdb5/postmaster4/worker2/stop3、suite1/retry0/首fail或UNKNOWN停止均未调高。

先写4个行为边界测试，再写修订：

- SIGKILL后尚未观察退出：模拟第一次真实wait依赖TimeoutExpired、后一次-9，必须经过原Session._wait完成记录，不能凭kill返回或poll前值当成功；
- 前件timeout：设置已耗尽的合成业务余量，必须失败、registered cleanup守卫拒绝，不spawnstop/不置closed/reaped；
- 确认-9后：原Session cleanup应给PG_EXIT_BEFORE_STOP并且不spawnstop；
- P5启动未完成/未经前件：cleanup不能跌入第4次stop。

这些仅为 P5ExitPreconditionTests 的**4方法源码冻结NOT_RUN**；纯测试对Popen/时间/waitpid依赖使用标明synthetic的替身，不能充当真实PG或实际ECHILD证据。测试源码内固定deadline仅属合成fixture，不是RealPG/生产Session重置。依本卡禁止执行，未观察RED/GREEN，也未执行helper、原五方法、纯32/33、旧8静态控或其他测试。

## 新封包与来源

本包有可审host根/control/source布局，真实Git四文件/commit raw/2182 fulltree从新commit重新导出并重建对象；test_pg_lifecycle.py SHA `ff8babd5df7cdd7998a63c2e1d4c5a27e894322609ef493159eb00e3a2808636`。其余三Git文件、host `188baedbb399862cc4efcf14ce208828b5ae9df6b05a46029f55aafafa3fbcae`、runner `890962062031a96558b4025daa822fdf3a1d381f7d59efed607d9138f4294540`、gate `57b6c3444d557ae6ca11fccf2d81ab1270594d5b665f08f43db2641fa8cf8630` 均逐字原已审源。

不需要runner源码映射修改：它仍从RealPGTests取原五ID，只是源文件和Git身份改变；新增纯类不会被exact5选择器选中。新plan/request完整15字段按原协调参数静态重绑新HEAD/tree/run_id/canonical plan digest；batch-000/django/run/requestnonce a*32/原5ID不变，未执行make_request/validate_request。新manifest `7990b7e727c2a79c534f8e8576bfebc9aa0b1f279515d83d49d33e98e6ddaa57`、control pins/command全部更新；资源仍2g/1g/cpus2/pids256/netnone/nonroot/readonly/caps原形状，无新增metadata/Docker操作或容量保证。

新的唯一未来输出 `/Users/mentianlu/.codex/runtime/realpg5-v2-p5sync-execution-b51eebf7f1bd4e389c3fa21acb9abbf0` 尚不存在；新container owner nonce/name与proposed-command.json绑定。命令是准备件，**本卡不得执行**。localcommit仅此文件，使用命令局部禁用hooks/signing以避免未知hook测试/网络；没有改Git全局配置。静态检查含AST/compile code object后丢弃、diff-check、文件/JSON/hash、只读Git与对象重建；从未exec/import候选/测试/helper。

## 保留与停止

原R-B285 report dbd8da078ba8ef6999c1a0229691509247860a00aab4f1636425fd4842e231b1 / index5d1aeefb7958b2ab02ba6ca6259e7ca2663a6e3afd16208dba491abf0e08c50d已核。周窗used51%、普通使用允许，未reset。本卡无PG/Docker/DB/Redis/第三方网络/CI/push/资源变化/子代理/他线覆盖；原B284、B285、R-B285包逐成员保持。

B285原P5拒绝及stop4/3勘误不洗白；B268旧失败/false、B249 UNKNOWN、旧/新八False成因UNKNOWN与B283旧4g BLOCKED均保留。PG5 NOT_QUALIFIED_STOPPED，formal/full/independent/delivery NOT_READY，root/image NOT_CLOSED。停止于新源码/身份/控制包待原R窄审，下一测试或真实PG须ROOT另卡。
