# 工程方案审查

## 审查结论

- Change：`backfill-race-events-to-1984`
- Review mode：Full
- Profile：`feature`
- 本次复审轮次：2
- 最终结论：**APPROVED**

本结论批准进入“先编写完整测试用例，再执行实现”的阶段，不代表允许直接开启公开展示。1998–2026 详情抓取和生产写入可在测试、实现、代码 review 与复审无问题后按批准批次执行；正式展示开关必须保持关闭，直到该阶段全量重复/漏抓审计和前台验收通过。

## 本次第一轮发现与返修

1. 规格仍残留“当前首批必须包含1980年代”和旧批次 `1996–2005 / 1984–1995`，与已经批准的分阶段顺序冲突。
   - 已统一为先执行1998–2026：首批覆盖2000年前后、中间年份和近年，随后按 `2016–2025 -> 2006–2015 -> 1998–2005` 推进；公开验收后才调研、建账和验收1984–1997。
2. 现有选择器只接受 `ready + RaceEvent`，但生产新总账30,917条目标均为 `pending`，日期发现和首批选择会互相等待。
   - 已改为两阶段固定范围：先从批准总账按身份和时间锚点固定约45个 `target_id`，日期发现apply后仍使用相同target_id生成详情计划，并绑定apply后的新target SHA。
3. 目录解析器假设 `local_date.year == year`，无法表达2001届布里斯托尔新秀跨栏赛于2002-01-11举行等跨年届次。
   - 已锁定“届次年份”和“实际日期”双语义：URL与系列年度仍使用届次年份；跨年日期必须提供actual_year、原因、权威证据和人工批准。
4. 日期apply只写 `local_date/source_refs`，没有把目标转为ready并materialize，后续编排器仍无法消费。
   - 已要求同一事务完成非破坏来源合并、pending到ready、draft/cancelled RaceEvent materialize、OperationLog和前后target SHA输出；任一步失败整批回滚。

## 本次第二轮发现与返修

1. 直接来源URL若只依赖已批准artifact，仍可能被污染为任意网络请求入口。
   - 已增加adapter级HTTPS host白名单，并要求校验候选URL、重定向链和最终URL；内网、非HTTP(S)与未批准host均fail closed。
2. 五地区距离单位没有形成明确契约，英国 `3m 210y` 可能被误读为米制数字。
   - 已要求保留来源 `distance_text`，显式记录value/unit/measurement system；英国mile/furlong/yard与米制metre分开解析，裸数字不得猜测，派生换算不得覆盖原文。
3. cancelled赛事可能没有赛果页，若统一要求result URL会错误阻断。
   - 已增加 `cancellation_url`：批准的预定日期和权威取消证据可使cancelled目标ready并materialize，但不得创建虚假runners/results。
4. 任务清单仍把1998–2026建账写成未完成的1984–当前总账，无法反映生产真实状态。
   - 已将1998–2026总账生成、身份审核和生产commit标记完成；1984–1997调研、审批、早期验收和抓取保留为公开1998–2026之后的独立任务。

## 最终复审

- 架构：保持Django单体，复用 `HistoricalRaceEventTarget`、`RaceEvent`、现有编排器、adapter、source cache、OperationLog和artifact审批，不新增模型或独立服务。
- 数据流：批准总账 -> pending预发现抽样 -> date/source discovery -> 人工审批 -> 原子ready/materialize -> 同target_id详情plan -> coverage/diff -> 受控写入，边界完整。
- 身份安全：series/year/expectation不由日期apply修改；跨年只改变实际日期语义；apply前后SHA可追溯。
- 来源安全：五地区来源矩阵、声明/实际出走/退出/赛果/取消证据分离、host白名单、重定向与磁盘/请求预算均有实现和测试任务。
- 产品顺序：1998–2026全量详情完成并审计后才打开该阶段展示；随后再推进1984–1997目录，符合用户批准顺序。
- 测试：98项任务格式和编号唯一；新增测试覆盖五地区离线fixture、日期冲突、跨年、取消、原子回滚、SHA漂移、同target_id复核、URL边界和距离单位。
- 静态验证：`openspec validate backfill-race-events-to-1984 --strict`、`openspec validate --all --strict`、`git diff --check` 均通过。

最终未发现剩余可修复的方案问题。真实来源的可访问性和历史覆盖深度仍必须由首批source cache证据与gap ledger验证，不能用计划假设代替生产事实。

## 2026-07-13 权威基础字段批量入口补充复审

- Review mode：Full（profile：`feature`）
- 触发证据：法港英150场日期apply后的生产event input中，123场`distance_text`仍是目录裸数字；批准的`detail_discovery.distance_evidence`已保存显式单位。另有8场官方/高可信赛历场地修正和6场法国平地surface修正尚未进入年度赛事字段。
- 复用边界：继续复用`merge_authoritative_fields()`、`apply_authoritative_event_fields()`、`target_identity()`、`OperationLog`和历史总开关；只新增有界批次服务与Django管理命令，不新增模型、迁移、依赖、Celery任务或网络入口。
- 输入契约：JSONL整文件绑定`--expected-sha256`；每条记录绑定当前target SHA、inventory SHA、字段artifact SHA，并只允许既有基础字段白名单。每个来源候选必须有authority、source ID、HTTPS URL、snapshot SHA和parser version。
- 原子性：服务按target ID稳定顺序锁定整批，先完成全部身份和字段dry-run校验，再进入同一外层事务逐scope调用既有字段服务。任一漂移、冲突、未知字段、证据缺失或中途异常回滚全部event字段、target provenance和OperationLog。
- 数据流：字段批次成功后target SHA必然变化，因此150场详情必须重新导出event input、重新package、重新coverage和dry-run；旧详情候选不能续用。
- 性能与运行：单批最多250个target，查询和日志规模有界；命令不触网，apply继续要求`HISTORICAL_RACE_BACKFILL_ENABLED=true`，生产常驻开关不变。
- 测试门禁：先新增TC-IMPORT-027至032，再实现单位保留、未知字段/证据缺失、人工锁、target漂移、批次中途异常整批回滚和旧详情SHA失效测试；随后执行目标测试、完整stable回归、Django check、迁移漂移、OpenSpec strict/all和代码review复审。

补充复审结论：**APPROVED**。该修复落实既有字段权威和距离单位规格，不改变产品范围；可进入测试先行和实现阶段，生产写入仍须经过候选审计、dry-run、备份与写后核验。

## 2026-07-13 标准批次既有选样排除补充复审

- Review mode：Full（profile：`feature`）
- 审查结论：**APPROVED**
- Scope Challenge：保持现有Django管理命令与批次服务边界，仅增加可重复的`--exclude-selection-snapshot`输入；不新增模型、迁移、依赖、Celery任务、网络入口或产品状态。
- 可复用能力：复用`write_batch_snapshot()`的不可变selection格式、现有日期发现快照校验规则、`select_historical_band_batch_targets()`的稳定排序、`write_band_batch_artifact()`的证据封装，以及既有inventory SHA和artifact identity工具。
- 数据语义：排除只影响本次选样，在地区limit前按target ID跳过；被排除target继续保持pending并留在remaining分母，不修改expectation、resolution或event。历史快照只校验自身身份，不要求其中已导入target仍匹配当前target SHA。
- Artifact契约：命令先完整读取并校验所有排除快照，再查询选样；输出使用固定文件名复制输入原字节，manifest绑定复制件的路径、大小和SHA，且最终selection与排除集合相交时fail closed。
- 失败模式：跨inventory、内部SHA漂移、目标ID无效或单份快照内重复、输出写入前集合相交均有明确错误；无效输入不得产生可批准artifact，也不得发生数据库写入。
- 测试：TC-BATCH-017/018覆盖limit前补位、多个快照去重、原字节复制、manifest身份、remaining分母、跨inventory、SHA漂移和集合相交；测试先于实现落地。
- 性能：每份快照为已批准标准批次的有界JSON，target ID集合用于数据库排除；不增加网络或无界数据库扫描。
- NOT in scope：不把gap改成`not_held`或`permanently_unavailable`，不改变公开开关，不自动批准新批次，不重建或重启生产服务。
- 一致性：`design.md`、增量spec、`tasks.md`和`test_cases.md`已对齐；`openspec validate backfill-race-events-to-1984 --strict`与`openspec validate --all --strict`均通过。

Plan Engineering Review Summary
================================
Review rounds: 1（converged at round 1）

Step 0: Scope Challenge — accepted as-is
Architecture Review: 0 issues found
Code Quality Review: 0 issues found
Test Review: 0 gaps identified
Performance Review: 0 issues found
Consistency check: All artifacts consistent

What already exists: immutable selection snapshot、stable selector、artifact writer、inventory identity helpers
NOT in scope: gap产品状态变更、数据库迁移、网络抓取、公开展示和生产容器切换
Failure modes: 0 critical gaps flagged

Next: Ready for test-first implementation.
