# 美国赛前来源修正发布证据（PR #304）

## 发布身份

用户确认“合并并发布”已绑定最终精确包。PR #304合并 `a4945de0333555e95cf129cd1b36b9cf4e24dc41`；其树与674项范围CI受测树一致。源提交 `10b8eacf39408922f5915b3953407906572b8cf8`，生产候选 `049caf284d1605137688e2a15b286756df0b34b1`，OCI `sha256:8f14c22b23d52b734ace8f2faff1d0f3a98bb18b75ec71abbb86f1c5572cb353`。

- 发布计划SHA256：`58449016133c590aaba0bccc50f7fa34407956b226640d46a6bea280ad2f78de`。
- 执行绑定SHA256：`ad51ea46675e90e54dd33c8aa3dda1ad29041b88b810c4898e278c64ed56f5c0`。
- 数据manifest SHA256：`75ff8d52ca8e59dbb38e4f01ef0146618c3279cf83bf31b987ffb1621d8f066c`。
- 策略SHA256：`2940443e714b6438b3bf081a2c8953217fc9ebc506267120d208da80bf7d0caa`。

## 发布前验证

固定候选PostgreSQL127项、范围CI674项均零跳过；可信交付核验verified，代码及精确发布包独立复审通过。220条真实登记的隔离整包dry-run/apply/probe/replay/精确restore和缺项拒绝通过，公开业务及288条候选保持、零来源网络和历史重导。最终候选与演练候选的应用及测试代码一致。六项实际shell故障注入通过。生产基线、清单闭集、包指纹、合并树均已再次核对。

额外两次普通HTTP只读观察：Pebbles及Manila页面200，现有解析器分别读取19/18匹预想名单；这是来源可读证据，不是自然任务写入证据。

## 已完成生产动作与静态验收

北京时间2026-11-12 19:28:22四应用版本/运行态检查完成，发布脚本退出0。暂停Beat后等待原worker自然排空，220条控制登记原子换绑（美国111、法国60、日本43、香港6），web切换、Nginx重载、双worker就绪及静态验收通过后恢复Beat。QQ关闭，法国浏览器保持，发布锁释放；无迁移、无历史重导、未执行回滚。

生产操作回执的before/after确认RaceEvent、RaceEventRunner、RaceEventResult、RaceEventIdentityKey及RaceEventFieldAuthority完全相同；换绑登记均使用新策略摘要。恢复调度前153个Django详情、1071行赛果、101个来源时刻及109条非美国公开业务保持。恢复后公网153个详情均通过，Glen Cove日历仅列两个子场，父页链接与历年冠军Ground Support/Lion Lake正确；浏览器同时复核Forever Young冠军页及“本年度未举办”页面。

## 自然验收与限制

发布后第一次只读观察中，三目标仍保留发布前失败记录和原退避，尚未在新版本重试：

|目标|event_id|下一次自然到期（北京时间11月12日）|
|---|---:|---|
|Pebbles|568|20:50:40|
|Manila|569|20:50:56|
|Native Diver|602|20:57:36|

实际自然重试已通过，未重置退避或手动派发：

|目标|成功检查时间（北京时间）|自然写入/结果|
|---|---|---|
|Pebbles|20:51:24|candidate41902，19匹预想名单|
|Manila|20:51:43|candidate41903，18匹预想名单|
|Native Diver|20:58:24|not_published，零名单；不再误报缺少报名链接|

三场失败计数均归零、lease释放，恢复正常三小时下一次检查。20:53公网复核Pebbles/Manila页面200，分别显示19/18行“预想参赛名单”，无更新延迟标记；这些尚不是正式出马表。20:58:59只读快照确认40个目标中39场已有成功检查记录、仅Colonial Cup（20926）保留NSA索引HTTP403。39场包含3场预想名单（含此前Commonwealth Turf18匹）、1场未发布及35场覆盖尚未核实，不等于39场资料齐全。本次三目标验收通过；Colonial Cup来源限制、未来正式出马表、赛后节点及完整七天观察仍未验收。

## 证据位置

本机专用目录 `/Users/mentianlu/.codex/runtime/us-preview-source-gaps-20261112/` 包含 `authorization-binding.json`、`merge-proof.json`、`delivery.json`、`production-receipts/`、`production-data-receipt.json.gz`、`production-data-summary.json`、`public-after-audit.json`、`public-division-verification.json`、`browser-after.json`、`natural-initial.json`、`natural-targets-settled.json`、`natural-acceptance.json`、`natural-public-verified.json`、`deployment-outcome.json`。生产收据在宿主发布根的 `runtime/us-preview-049caf28/`。包内“待G2”文字保留为批准时冻结原件，不修改其指纹；本文件及实际回执记录批准后的执行结果。
