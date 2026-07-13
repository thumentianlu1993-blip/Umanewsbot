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
