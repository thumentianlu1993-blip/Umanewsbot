# B285 既有隔离 RealPG5 一次实验结果

**FIRST_COMPONENT_GATE_REJECTION_P5 / STOPPED_NO_RERUN。** 原五方法均 native ok，冻结独立组件 gate 接受前四项 P1/P2/P3/P6a，最后 P5 拒绝。整套不是资格通过：container/CLI/wait/inspect退出74，host退出75。未修补参数、oracle、gate或源，未补跑。全部原始输出保留，交 ROOT 转同一原 R 结果审。

## 一次性、版本与真实隔离

本次只按 B284 proposed-command.json 原 argv/cwd/host_child_environment_exact 启动一次 host：PID=PGID **68088**，外层监督器PID 68084，真实wait **75** / reaped True，timeout False / kill False，外层25.015382167秒，attempt1/retry0。精确解释器3.14.6/SHA `b502cb4c5b46b8d4192ec6bcb600ce8922f1afc396fcf646e8765c6eba74a0bf`；包41成员498495B和原 R 两成员逐项先核，开始/结束 pins保持，HEAD/tree与clean状态保持。周窗实时used50%、普通使用允许，未消耗reset。开始前输出不存在，旧命名CLI未见，旧已知PID不存，live agent仅root。结束后本次controller/host/七个Docker CLI已知PID均不存；这不是全机未知进程不存在证明。

原输出 `/Users/mentianlu/.codex/runtime/realpg5-v2-2g1g-execution-83393dba69004ffd87f648d3e43aaf44`；原 result-index `640af2002c3ab2ea1e109537fb41b0bfe340ee605bdb9b8ad76e5a61fa62a4dc`，自排除22成员100350B，逐项hash/size/集合与归档 execution-output 复制一致；原 result-index自身也复制。监督器start/result、host raw stdout/stderr、所有Docker raw与calls、inspect/wait/owned CID、methods/summary/preflight、逐方法完整收据全部保留。decoded-logs 为42个嵌入日志的逐字base64解码，逐项byte数/hash对上原receipt。

实际容器Python **3.12.3**、/venv/bin/python、PID1/UID=GID10001，namespace pid:[4026532436]；四次真实postmaster日志显示 **PostgreSQL16.15 (Ubuntu16.15-0ubuntu0.24.04.1), x86_64-pc-linux-gnu**，不是仅从image标签推断。未额外运行version probe，initdb/pg_ctl各自独立version命令未执行，不外推其单独版本。固定image/context由原host当前inspect核对；actual image `sha256:3dfe2d0415bf03584bab2436ff1b8f40ac7591cf3834d66e6263b018febf2f98`。

实际 post-inspect Memory2147483648 / Tmpfs `{'/tmp':'rw,exec,size=1g,uid=10001,gid=10001,mode=0700'}` / NanoCpus2000000000 / Pids256 / network none / User10001:10001 / readonly / caps ALL/no-new-privileges与三项bind来源/RW均按原host核对，isolation True，ownedlabel/image/name True。State.OOMKilled False。此一次运行未出现该OOM标记，不是峰值、长期容量或root/image整体资格保证。实际执行达preflight/五方法，结合冻结runner控制流可推知v2后半段make_request/validate_request/整份canonical对照未中止；没有新增逐函数trace。

## 方法与收据

| 顺序 | 原方法 / component | native | 组件gate | 直接进程结果与原因 |
|---|---|---|---|---|
| 1 | foreground_pid_and_separate_stop_wait / P1 | ok | ACCEPTED_COMPONENT_ONLY | PG20→0/reaped，worker30→0，stop31→0；主次错误空 |
| 2 | worker7_does_not_hide_stop_wait0 / P2 | ok | ACCEPTED_COMPONENT_ONLY | PG45→0，worker55→7，stop56→0；主次错误空 |
| 3 | sigstop_forces_real_stop_timeout_not_success / P3 | ok | ACCEPTED_COMPONENT_ONLY | PG70→-9/reaped/timed_out True/signals9；stop80→1/reaped；primary PG_STOP_EXIT:1，secondary PG_DIRECT_WAIT_TIMEOUT、PG_POSTMASTER_EXIT:-9 |
| 4 | initdb_failure_has_no_fake_postmaster_zero / P6a | ok | ACCEPTED_COMPONENT_ONLY | initdb81→1/reaped；postmaster/worker/stop NOT_STARTED/null，未伪造0 |
| 5 | early_postmaster_exit_is_reaped / P5 | ok | REJECTED | PG97→-9/reaped；实际stop107→1/reaped；worker NOT_STARTED；primary PG_STOP_EXIT:1、secondary PG_POSTMASTER_EXIT:-9 |

原 stderr 精确五headers/顺序/ok，footer **Ran5 in24.336s / OK**；native failure/error/skip0。原 gate 首拒字段 **UNEXPECTED_HANDLE:pg_stop**，同P5完整component_evidence_errors保留 `UNEXPECTED_HANDLE:pg_stop`, `NOT_STARTED:pg_stop`, `ERROR_POLICY:P5`；container summary仅持首个聚合evidence_error，均未重写。P5并未取得冻结gate要求的“stop NOT_STARTED、primary PG_EXIT_BEFORE_STOP”分支，实际走有pg_stop的分支，因此拒绝如实成立，不用native ok推翻它或现场放宽。确切调度/竞态原因尚未另行取证，本卡不追加诊断实验。

23个实际Popen句柄（6+6+5+1+5）逐项与原receipt的PID/argv/真实数字returncode/reaped对上；原生日志中PG默认tester库不存在的FATAL等原文照留，不静默删减或据此重定首因。P1/P2/P6a直接出现实际ECHILD errno10；P3收养PID72/73/75/76/77、P5收养99/100/102/103/104各5个真实waitpid，rawstatus256→exit1，经stdlib按原状态独立对照，然后各有实际ECHILD errno10。五份adopted_wait均status ECHILD/echildTrue/errorNone；orphans[]不是单独的回收证明，完整events/rawstatus/PID namespace保留。所有receipt complete均False，Session.execute标准complete不被宣称。

归档初次数据检查曾将句柄预期总数误写24；核原始逐项记录后仅更正派生统计为23，未重执行候选或改任何运行raw，见observed-checks的postprocessing_note。

## owned退出/清理与失败保留

仅原host合同处理确证owned CID `a3a7fe48cec8d3375c89232b66247372d8f2523b97ac7ba7ce6f21a7cb30b366`。Docker run CLI **74** / Docker wait stdout **74** / State.ExitCode **74** 三方join，State RunningFalse/Pid0/OOMKilledFalse，outer_join True。owned rm返回0，absence inspect返回1，stdout原bytes为[]加LF，stderr恰为lowercase `error: no such object: <同CID>`加LF，timed_out均False，strict predicate给 **owned_cleanup True**。这是本次新结果，不回填B268旧false。

原host外层summary primary保留 `CONTAINER_RUN_FAILED_OR_TIMEOUT`，实际calls及监督器timeout均False，具体失败来自container74/P5 gate拒绝，不误报外层超时。P3直接postmaster局部timeout是原oracle预期路径，不能和外层timeout混同。所有额外命令仅文件/JSON/hash/base64/Git和本次已知PID只读退出核验，没有第二次rm/inspect/Docker调用或附加清理；未动其他容器/daemon或旧现场。

预算原600/540/40/20、Session570/business540/cleanup30、五方法上限保持。没有pure32/33或8静态负控补跑；没有CI/push/merge/deploy、pull/build/load/install/startdaemon/扩容/换backend、生产DB/Redis/第三方网络、子代理或新任务。

**PG5 NOT_QUALIFIED_STOPPED**；B283旧4g/3g BLOCKED保持，B268首拒/owned_cleanup=false/raw、B249 UNKNOWN、B263旧八False与B282新八False成因UNKNOWN均保留；formal/full/independent/delivery NOT_READY、root/image NOT_CLOSED。停止保留，等待原 R 审核和 ROOT 后续卡。
