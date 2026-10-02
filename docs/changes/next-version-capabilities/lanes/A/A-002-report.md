# A-002 / F01 可执行共享合同交付（待Linux回归与原R代码复审）

输入方案：7c78f67d04cc156520d21916f3eb0a3ef066305e（原R APPROVED/F01-M-01 CLOSED）。
任务DDL 2026-10-04 18:00 Asia/Shanghai。当前F01未标全部完成，下游未解锁集成。
worktree `/Users/mentianlu/.codex/worktrees/5482/umanews`；branch `codex/next-version-race-data-20261003`。
代码base 907f8de6，A-002直接base为7c78f67d；固定实现head以Git及协调消息为准。

已完成：content_contracts无ORM/网络/隐式时钟DTO、严格parser/生产者serializer、私有/公开字段边界；
15项stdlib行为测试通过；新增显式测试映射。接口见[A-002-interfaces.md](A-002-interfaces.md)。
未修改writer、业务调度、schema、第三方权限策略或公开端点。

测试先行证据（运行目录 `/tmp/umanews-a002-evidence`）：

| 阶段 | 命令/观察结果 |
|---|---|
| 首轮RED | `PYTHONPATH=server python3 -m unittest stable.test_content_contracts`；3项测试6个子例ERROR，正常导入API骨架后调用parse_input抛目标NotImplementedError；无import/环境失败 |
| 首轮GREEN | 同命令3/3通过，DTO独立快照/未知与0/四组往返 |
| 严格边界RED | 同命令11项：26 fail/7 error，非法schema/字段/摘要未拒绝及build/public API缺失 |
| 严格边界GREEN | 同命令11/11通过 |
| 公开错实体RED | 同命令15项：1 failure（ContractError not raised），公开摘要错canonical未阻断 |
| 最终局部GREEN | 同命令15/15通过；无DB/Redis/网络 |

完整日志各为red.log、green-round1.log、red-round2.log、green-round2.log、red-round3.log、green-round3.log。
测试mutation目标见[test_cases.md](test_cases.md)。API骨架仅供RED导入，不包含行为；JSON文档工具不作为行为GREEN证据。
workflow contract PASS/4 tests PASS、文档fixture 4正例/5反例 PASS、diff check PASS。

影响诊断：以7c78f67d为base生成本地plan，full/247 domains/294 labels。
原因是rules/catalog映射演进，保留原base+候选完整覆盖；没有为省开销改工具选择算法/skip规则。
Linux交付：专用Colima umanews-impact-ci由协调者恢复；固定候选的一套full待运行，最多2批并发，每批<=200。
宿主GREEN只是开发证据；Linux完整集合、收尾、skip与候选外收据未取得时不得称交付测试已通过。
原R代码复审待协调者派发，映射补丁单独列审；后续finding按原reviewer返修。

当前额度最新每周已用93%、剩7%；无子代理/模型CLI。持续检查与用户<=1%停止约束保持。
临时异常按2s/5s最多3次有界恢复，未知写入结果先读收据，不重复派单或改生产。
