# B037：自动重试 claim/fence 实施准备

任务 B037-M02-CLAIM-FENCE-IMPLEMENT-001。当前仅测试准备，**未执行真实 RED，未修改应用代码**。ROOT 已确认原 R `6e05cc18ccc78364cb5d41babbfe4f5f367ee194` 关闭 B036-R01，APPROVED_PLAN_ONLY；该确认不是实现审核或发布授权。

从固定集成 `2c72521c55b6cdc24f7650d172b48079cbff969a` 创建独立树 `/Users/mentianlu/.codex/worktrees/b037-m02-claim-fence/umanews`、分支 `codex/b037-m02-claim-fence`。只从 `82b0c7253a4410cec7a1de31302345f2ba6f986e` 提取最终 B036 方案原字节作输入，未 cherry-pick 旧 B035 实现或 ROOT 协调记录；旧 B035/B034/C028 树未改。

ROOT 分配本线负责 tasks.py 仅 translate_article_task/必要相邻调用、translation_recovery.py 受管 claim/release/stale/terminal、translation.py 受管 run 及独立测试/B报告。models/settings/migration/catalog不改。当前这三处代码逐字保持固定集成基线；不覆盖他线。

[测试清单](B037-m02/test_cases.md) 首批五项使用现有 selector/task入口及可控交错；目标失败是重复provider消费、旧成功/异常污染新领取、终态通知前run未原子失败及run保存失败后的状态/通知无法回滚。不依赖新函数签名，不连接 provider/mail/broker。已做语法 AST 与 diff 检查，尚未导入 Django/收集或执行测试；这些检查不是 RED。

C029 当前独占 collector。准确 labels、执行命令和单批资源预算见测试清单，已准备交 ROOT 分配现有隔离 PG 窗口；未自行启动容器/数据库或安装资源。收到窗口后先跑此固定测试提交并记录真实 RED，随后方可开始应用代码。各扩展场景继续先 RED 后 GREEN；PG真并发与相邻回归按 ROOT 安排，正式 mapping/full另行集成。

边界保持已审方案：普通/force兼容、指定受管run、外部调用无事务、article+确切run同库原子终态、同轮fence与提交后终态snapshot通知。累计费用预算/SDK跨轮边界、响应恢复、可靠outbox仍是完整M02缺口，不扩大本片。没有生产、真实DB/Redis、模型调用、外发、QQ/后台扩张、push/PR/合并/发布或新增Docker。
