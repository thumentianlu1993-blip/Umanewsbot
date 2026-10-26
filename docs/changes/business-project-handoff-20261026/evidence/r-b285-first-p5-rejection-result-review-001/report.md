# R B285 首次2g/1g实验P5拒绝与次数上限结果审查

结论：**ACCEPT_FIRST_P5_GATE_REJECTION_EVIDENCE_WITH_STOP_CAP_BREACH_ERRATUM; REPAIR_REQUIRED_BEFORE_NEXT_PG**。原native五方法ok成立，组件gate只接受P1/P2/P3/P6a、正确拒绝未满足冻结前件的P5，整套PG5仍NOT_QUALIFIED。另有必须补录的计数冲突：实际pg_stop4次，超过manifest上限3。不是retry，但不能称全部尝试上限保持。本R只读审查，没有重演/运行候选、PG、SQL、Docker或附加清理。

审前按要求读取额度：本review周窗used51%、剩余49%，普通使用允许；未消耗reset。与执行开始前原记录used50%是不同时间快照，不改原值。

固定结果包 `/Users/mentianlu/.codex/runtime/b285-realpg5-2g1g-once-result-001`：77成员/372785字节逐项size/hash/集合一致。作者report SHA `f11afda441c11178e340ffb669c0ab6501526a022408dec42795ed6530580437`；index `a9d31f51364022936ab65f002dfb7289a065cde5eec402cab53af5fd772073e3`；binding `3397d1eb76c4ce625a4275753fff0303f64876e2dc53c0b142be06c02ccfd496`。

## 一次身份、真实运行与原件

固定B284输入与R-B284保护包所有成员仍匹配；host argv/env、manifest/hash、新唯一output及supervisor-start/result一致。controller68084、host PID=PGID68088，真实wait75/reapedTrue，25.015382167秒，timeoutFalse/killFalse，attempt1/retry0。七个Docker CLI为原host的一次既定调用链，没有第二次rm/absence或重试证据。已记录ps只核本次controller/host/七CLI共9个已知PID退出，不外推全机无其它进程；本R没有再查进程。

原output result-index `640af2002c3ab2ea1e109537fb41b0bfe340ee605bdb9b8ad76e5a61fa62a4dc`，自排除22成员/100350B，原目录/复制目录集合与每项bytes/size/hash相同。42嵌入日志strict base64解码、原bytes/hash及decoded副本逐项匹配，原文包括tester默认库不存在FATAL均保留，不据此改首因。

容器preflight实际Python3.12.3、/venv/bin/python、PID1/UID=GID10001/namespace pid:[4026532436]；四份实际postmaster日志为PostgreSQL16.15/x86_64。不是单靠image标签，仍不外推initdb/pg_ctl单独version命令或长期binary资格。实际到preflight/五方法，结合固定runner顺序可推知v2 suffix整份request生成/验证未中止，非逐函数trace。

原inspect独立核exact image/name/owner label，Memory2147483648、Tmpfs1g选项精确dict、CPU2/Pids256、networknone、readonly/nonroot及三bind来源/RW相符。State.OOMKilledFalse只是一轮观察，不证明实际峰值、持续容量、root/image整体通过。

## native与独立gate必须分开

原stderr五个精确header/顺序均ok，Ran5 in24.336s/OK，fail/error/skip0。methods/summary原件同时保留gate4接受/1拒绝：

| 项 | 实际关键记录 | 审核结论 |
| --- | --- | --- |
| P1 | PG20=0、worker30=0、stop31=0，均真实reaped | 本次组件接受 |
| P2 | PG45=0、worker55=7、stop56=0，均reaped | 本次组件接受，worker7未伪零 |
| P3 | PG70=-9/reaped/timed_outTrue/signals9，stop80=1/reaped；primary PG_STOP_EXIT:1，secondary PG_DIRECT_WAIT_TIMEOUT/PG_POSTMASTER_EXIT:-9 | 本次独立gate接受，未回填B268当时拒绝 |
| P6a | initdb81=1/reaped，PG/worker/stop NOT_STARTED/null | 本次组件接受，未伪造PG0 |
| P5 | PG97=-9/reaped、stop107=1/reaped、worker NOT_STARTED；primary PG_STOP_EXIT:1，secondary PG_POSTMASTER_EXIT:-9 | 原native可通过，但冻结P5前件未满足，gate拒绝必须保留 |

P5首因UNEXPECTED_HANDLE:pg_stop，完整三项errors为UNEXPECTED_HANDLE:pg_stop、NOT_STARTED:pg_stop、ERROR_POLICY:P5。container summary只聚合首项不等于其余原因不存在；不能用native5ok推翻gate或把primary改成PG_EXIT_BEFORE_STOP。

五份receipt均v2、completeFalse。P1/P2/P6a有真实ECHILD errno10；P3与P5分别有5个REAPED事件（72/73/75/76/77，99/100/102/103/104），raw256→exit1/namespace与orphans双射，再末尾ECHILD10。独立核23个保存Popen句柄均与record PID/argv/exact数字rc/reaped对应，10个adopted wait不混为直接Popen或全部OS进程总数。此证据支持本次实际回收，不能代替标准Session.execute complete/native/full。

## [P2] P5异步故障前件与冻结gate不对齐，并实际突破stop3上限

固定 `source/tools/test_impact/test_pg_lifecycle.py:242-246` 仅start→os.kill(SIGKILL)→立即stop_and_wait→断言最终PG=-9/reaped。没有在进入cleanup前用实际数字wait确认postmaster已退出。SIGKILL发送返回不是Popen已观察退出/回收的证明。

`pg_lifecycle.py:441-445` 在初次process.poll()为None时启动pg_stop；只有另一分支才记录PG_EXIT_BEFORE_STOP。真实stop107存在，结合固定源码唯一spawn位置，可推断分支决定时尚未观察到postmaster退出。这是源码控制流推断，不是已录poll值/内核调度trace。pg_stop原日志确为“server does not shut down”及等待失败；不能凭此定论具体signal交付、zombie或调度时序，也没有资源/OOM根因证据。

`control/component_evidence_gate.py:110-116,171-172` 的P5则要求pg_stop未启动、primary PG_EXIT_BEFORE_STOP及原secondary。native只证最终回收，未保证这个更强的pre-stop已退出前件。故目前暴露的是测试前件/资格合同对齐缺口；cleanup对其看到的仍运行Popen走原stop分支、保留真实helper失败，并非已经证明应被修改的生产清理错误。

**次数勘误必须单列**：原manifest.max_attempts.pg_ctl_stop=3；原handles实际stop31、56、80、107共4。其余initdb5/postmaster4/worker2保持上限，readiness原bounded loop共8，直接总数23=5+4+2+4+8。24→23的派生统计更正正确，但未揭示stop4/3冲突。作者report“...五方法上限保持”不能作为本次结果结论，需ROOT在新勘误/账本中注明；不修改原sealed raw/report/index来追认。manifest计数没有成为真实spawn前的强制预算，后置gate拒绝也不能撤销已发生的第4次spawn。

本R此前静态审未识别这一可达额外spawn分支，现以实际原件纠正；不能沿用“stop≤3已保证”的静态预期。

## 最小下一窄修与仍未证分支

优先保持冻结P5 gate和所有数字oracle，修正故障注入的确定性前件：SIGKILL后、cleanup前，以实际保存Popen的数字wait/现有Session wait路径确认退出=-9和回收，再进入cleanup；等待必须在原剩余business/deadline内设短上界、计入原预算，不加固定sleep/猜测轮询次数、不重置cleanup30或增加外层600/foreground540，不新增PG/stop/retry。前件失败就明确失败/UNKNOWN停止，不能补写成P5已达。

这会修改原P5方法/前件，当前“原五方法体不动”约束不能由本R偷偷豁免。ROOT需先明确授权一个窄的测试前件修订/新固定source identity，保留旧P5原件及这次失败，另审修订diff与预算；若坚持原方法字节不变，就保留当前拒绝，不能靠runner拦截信号/伪造poll、事后重分类或给P5增加stop1白名单来晋升。若资格目标本身要改变，也须明确新合同，不能冒称原P5分支已验证。

任何下次PG前，stop≤3须成为可证明的前置约束：确定性P5前件使额外stop分支不可达，或另审spawn前计数准入；不是把cap升4追认本次，更不是先spawn后用gate当次数防线。必要纯边界验证应覆盖“kill后poll尚未退出”的反例仍不冒P5成功、前件超时不继续、确认退出后不spawn stop；保留P1/P2/P3/P6a原语义，不机械重跑全部已过纯套件或本实验。

本轮仍未证明原PG_EXIT_BEFORE_STOP/no-pg_stop P5路径、整套独立组件5/5、Session.execute标准complete/native、full/independent/delivery或长期容量。P3此次signal类型/回收证明与严格absence新True是新证据，不能解释为B268历史已修正或证明当时唯一根因。

## owned清理和停止边界

确证owned CID a3a7fe48cec8d3375c89232b66247372d8f2523b97ac7ba7ce6f21a7cb30b366；run CLI74、docker-wait stdout74（CLI0）、State.ExitCode74，RunningFalse/Pid0/OOMKilledFalse，outer_joinTrue。仅原host一次owned-rm0和absence-inspect1，timed_outFalse，stdout[]+LF、stderr为精确同CID lowercase no-such-object单行+LF，strict owned_cleanupTrue。新True不回填B268旧False。host primary CONTAINER_RUN_FAILED_OR_TIMEOUT是原泛化标签，实际为container74/P5拒绝，不是外层超时；P3局部postmaster timeout另属原预期路径。

所有真实原件、42日志和失败输出保留，已知PID退出不冒全机证明；本R没有第二次inspect/rm/进程查询/清理。live clean bb871949877979226292033f0ab14f8d949cc6b7 / tree c034f4d1188cd6815b60ec40a98de9c4c00a06f9，tracked及B284/R-B284保护成员一致。

本R只本地文件/AST/JSON/hash/base64及只读Git，写本R新runtime checks/report/index；候选/helper/测试/SQL/PG/Docker/网络/CI/附加清理0，无子代理。B268原失败/False、B249 UNKNOWN、B263旧八False与B282新八False成因UNKNOWN保持；B283旧资源BLOCKED不改。PG5 NOT_QUALIFIED_STOPPED，formal/full/independent/delivery NOT_READY、root/image未闭合。停止等待ROOT明确前件/次数合同窄修卡，不自动执行。

本项独立只读技术审核不授予执行或发布权限；项目交付由ROOT按其当前适用的根AGENTS执行。
