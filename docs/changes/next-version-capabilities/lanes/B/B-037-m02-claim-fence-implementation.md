# B037：自动重试 claim/fence 实施准备

任务 B037-M02-CLAIM-FENCE-IMPLEMENT-001。当前**首批五项真实 RED→GREEN 已完成，边界/PG真并发/相邻回归待执行**。ROOT 已确认原 R `6e05cc18ccc78364cb5d41babbfe4f5f367ee194` 关闭 B036-R01，APPROVED_PLAN_ONLY；该确认不是实现审核或发布授权。

从固定集成 `2c72521c55b6cdc24f7650d172b48079cbff969a` 创建独立树 `/Users/mentianlu/.codex/worktrees/b037-m02-claim-fence/umanews`、分支 `codex/b037-m02-claim-fence`。只从 `82b0c7253a4410cec7a1de31302345f2ba6f986e` 提取最终 B036 方案原字节作输入，未 cherry-pick 旧 B035 实现或 ROOT 协调记录；旧 B035/B034/C028 树未改。

ROOT 分配本线负责 tasks.py 仅 translate_article_task/必要相邻调用、translation_recovery.py 受管 claim/release/stale/terminal、translation.py 受管 run 及独立测试/B报告。models/settings/migration/catalog不改。不覆盖他线。

[测试清单](B037-m02/test_cases.md) 首批五项使用现有 selector/task入口及可控交错；目标失败是重复provider消费、旧成功/异常污染新领取、终态通知前run未原子失败及run保存失败后的状态/通知无法回滚。不依赖新函数签名，不连接 provider/mail/broker。测试准备提交仅做 AST 与 diff 检查；随后按 ROOT 窗口取得下述真实 RED，静态检查不冒 RED。

C029 释放后 ROOT 明确分配一次五项 RED 的现有镜像/本地 Docker/隔离 PG 窗口；已在固定测试提交 `a4022503945bc7dbb4f286cada1e2b547c87a2ec` 实际执行。五项 failures、零 errors/skips、lifecycle complete、runner exit1；失败分别证明重复消费2次、迟到成功覆盖新轮、迟到异常通知、通知前run未失败、run保存失败后article未回滚。不是签名/导入/环境失败。worker包含准备38.26秒、业务测试2.321秒；诊断证据不冒正式catalog/full。

独立 runtime `/Users/mentianlu/.codex/runtime/b037-m02-red-pg-window-001/red-receipt.json` 绑定SHA/tree/5IDs/镜像/PG/隔离及原日志。实际镜像 `sha256:fcf8cdaf63af51b1b8a6e30e3d2fdf871d127c3c1461bfd00c9fc6d610eab905`；官方django profile启本容器PG16、DiscoverRunner建隔离测试库；nonroot10001、networknone、readonly source/control、2CPU/4GiB、256pids、3GiBtmpfs、capdropALL/no-new-privileges。八受信控制从2c725/6e6导出并与候选字节相等，未修改控制/validator。官方worker无180秒配置，保留600秒控制超时，宿主包装570秒+30秒清理；实际未超预算。

前两启动在进入测试前分别受阻于宿主生成pycache进入controls扫描、macOS默认TMPDIR不在Colima共享面；均实测零运行容器、runner退出，错误原件保留。只改变本runtime启动环境 PYTHONDONTWRITEBYTECODE 与 TMPDIR，第三启动实际执行本五项一次。锁以FD flock自动释放并记录owner/thread/SHA/domain/PID，finally清理后实际containers=[]/runner退出，已报ROOT释放窗口。

有效RED取得后才开始三处应用代码：claim持久化固定身份/阶段/deadline/输入摘要，消费及终态统一article→确切run行锁；task受管路径拒绝外层事务、成功/异常归属核对后回写；翻译服务受管模式不选最新run/独立写终态，普通模式不覆盖受管JSON；受管终态失败同事务保存article+run，on_commit使用终态快照、robust回调，失主/回滚零通知。受管派发失败与stale只终止匹配run。实现提交当时已做AST/diff检查，尚未执行GREEN/PG真并发/相邻回归；候选固定后另申请ROOT新窗口，不沿用已释放RED窗口。

ROOT 新分配首次五项 GREEN 窗口；固定 `bb572df2fb5707062ef55f6c688fd5f0ec71d925` 上同5 IDs一次实际运行，5/5通过、零 failures/errors/skips、lifecycle complete、runner exit0。worker38.03秒，业务测试2.317秒；同官方django/隔离PG16/镜像/八控制与隔离约束。runtime `/Users/mentianlu/.codex/runtime/b037-m02-first-five-green-window-001/green-receipt.json` SHA `c067058d117b50b51e681fb2946ff9325b1abddec13281ee7a8b60b697582ac3`。finally清理后容器=[]、runner已退出、FD锁释放，已回ROOT，不复用窗口。

之后只准备测试扩展，没有新增应用代码：保留首批5方法AST和canonical IDs，提取共用fixture为无测试方法的基类；新增17项边界/两PG连接并发，包含 ordinary人工字段、force published、外层事务拒绝、源版本变化、精确deadline、领取时间不重设、旧/非法envelope、run归属、release/stale局部与回滚、通知失败隔离、真实受管服务metadata及PG并发。只对现有 recovery selector 测试的旧消息断言补入run_id/claimed_at，保持其边界/批量断言，不能继续要求无身份的旧消息契约。源码仍逐字等于首批GREEN候选。

下一诊断批申请准确63IDs：本片22（原5+新增17）、现有recovery22、M01 mock19，全部用官方django profile单runner。AST只是清单准备，尚未实际收集/执行本批；两线程PG测试需分别取得不同backend PID、记录日志并关闭各连接，不冒用顺序交错。真实正式catalog/impact/full及独立review仍ROOT后续安排。

边界保持已审方案：普通/force兼容、指定受管run、外部调用无事务、article+确切run同库原子终态、同轮fence与提交后终态snapshot通知。累计费用预算/SDK跨轮边界、响应恢复、可靠outbox仍是完整M02缺口，不扩大本片。只使用已分配现有镜像的临时隔离测试容器/PG，无生产或真实业务DB/Redis、模型调用、外发、QQ/后台扩张、push/PR/合并/发布或新资源构建。
