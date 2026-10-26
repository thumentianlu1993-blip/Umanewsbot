# 第二批集成状态

2026-10-04 01:25，Asia/Shanghai。最新候选 `06b01aea9041eacb3deae9f46968eb06fd459cb6`、tree `d23998ef537cf4ff7098a4aae0d9efa7987d115d` 已推送到 [Draft PR #236](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/236)。相对 main `907f8de699b31a6fcc80acc78e9ba070aadc4f28` 的 PR 包含尚未合并的 [PR #235](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/235)；第二批自身基于首批 head `39f0bb96f4f24d15b625ca404c50cede9ebf05dd`。

## 范围与状态

第二批包含 Q01 关闭 QQ 发送并解耦网页发布、Q02 入口和专属运行依赖移除、H01 目标集合与只读计数、F02 隔离导出验证接通、U02 七天首页及公开列表来源返回导航。无新增迁移。合并、部署、启用、公开验收均未完成；生产专属服务停用仍待精确交付包。

固定代码和测试映射经原独立 R 审核，原代码/控制绑定 `73ec1da6247e7878a39d7a29a8afe47000ebb730`，最小时钟fixture修复及新候选重绑定经原R `055e193225df95ee58b9b972f64467863cbc5e70` 批准；静态计划为 254 领域、303 标签、19 个控制文件。原 plan、源 inventory 和实际清理收据记录在私有 runtime，机器索引见 [执行台账](dispatch_state.json)。

## 实际验证

- 历史候选 `6251f023` 的 PG126 执行保留 125 PASS、1 个 fixture 插入 ERROR、零 skip，不改写历史结果。
- 修复唯一 fixture 后，`bdfb5c9c` 在固定 Linux/PG16 环境精确补验原失败方法：1 PASS，零 error/failure/skip；20.846 秒，完整清理。
- 同候选独立真实 Gunicorn HTTP：37.307 秒完成 20 请求（19 个 200、隐藏记录预期 404）、8 条固定 journey 断言，最长请求行 3623 字节，小于 3800 预算，Gunicorn22 默认 4094 限制未改。
- collect、PG run、HTTP 三阶段均有 own identity、进程回收、容器移除、namespace PID0、PG 关闭、端口关闭等原始证据；协调者实际限定 label 的 `ps -a` 为空。
- 原独立 R `58ebf4418db67345759646dc5aebfd4dc54d667c` 已批准实际 PG1/HTTP 收据及范围。HTTP cursor/year 使用固定 producer 输入；不能扩大为未执行的完整语义断言，完整应用语义由 PG1 方法覆盖。

新 PG1 与旧 125 项不拼接为新版本 126 全通过，也不等同视觉或生产验收。

## 正式交付已核验，待 G2

原正常 `pull_request` CI [run 37135439940](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/37135439940) 已完成6378项/46批：1 failure、0 error、10 skip，所有native batch complete，结论保持失败。唯一首页赢家测试mock仍指向localdate，未固定首页实际使用的now。最小修复将同一用例的时钟改为now(self.NOW)，数据、赢家与公开门禁断言全部保留；隔离同例原失败复现/修复后通过，原R只读复审已批准，19个control及业务代码未变。

新候选06b的正常CI [run 37137528485](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/37137528485) 于北京时间01:04:36完成：full 6378项/46批，0 failure、0 error、10个既定skip，全部native lifecycle complete。候选目录外 main907 原verifier已完成真实CI镜像加载、独立collection、control blobs、strict/admins和实时base/head核验，正式收据 status=verified。受验merge为 `0932c240f66eff98dbecafcf02e1994982ba6c6f`，tree为 `d23998ef537cf4ff7098a4aae0d9efa7987d115d`，plan digest为 `28935595a67f17499609b3dad568a15dc914573748a00239dd83a5498befebc2`。本次是新合并测试树完整结果，不拼接旧绿项。原最小修复证据仍保留。

私有正式收据 `/Users/mentianlu/.codex/runtime/second-integration-evidence/delivery-06b01aea.json`，SHA256 `47f2340046d82a0de855b6bb8dad451f5b0748c8e0a4d402e47b81123630a894`。原R `345b13a3` 已批准此次固定image artifact运输绑定；缓存只替代精确工件字节传输，原verifier及全部检查保持不变。执行结束root实查本地容器为空。合并确认见[第二批交付材料](second-integration-delivery.md)。

F02 真实新样本仍为 0；O02 最后快照外键、完整一致引用图和整库恢复未完成。A009 新容量 helper、B007 负例镜像及 C011 快照分段方案属于后续在途任务，不在本固定候选中。
