# P02 验证用例与证据

当前全部业务用例 NOT_RUN；本轮只验证文档。实现时先在隔离环境取得有意义的行为 RED，再 GREEN。既有测试通过历史不能继承。

| ID / 对应规格 | 输入/故障与预期 | 必须抓住的错误 |
|---|---|---|
| T01 / S01,S02 | 九地区清单含无来源/无 canonical/日期赛、AE/SA；G1/JpnI/J-G1/人工重点及普通赛 | 漏项从分母消失；同名错配；全部比赛误作重点 |
| T02 / S03 | 单一 netkeiba 等合格第三方完整确定资料可发布；官方旧资料不能压过新合格资料；缺用途能力不准入 | 官方独占；把站点名单当完整性证据 |
| T03 / S03,S05 | 同源镜像、三名摘要、错误 generation、过期/未知资格、冲突冠军；策略变更后的 A→B→A 用当次观测生成新 epoch 凭据，旧 Publication 不变；撤销授权、重复消息与 reader 回读 | 抓取晚者胜；旧授权复用；reader 借旧 primary_observation；重复 hash 违反约束 |
| T04 / S04 | 截止前 1 微秒/恰好/之后，预想 t−30m、临时结果 t+60m；相同名单内容仅成熟度变确定时 epoch 递增，清缓存/重启后保留确定、临时 deadline 清空；worker/缓存失效失败 | 内容去重吞掉确认；成熟度丢失；后台停机导致过期内容持续展示 |
| T05 / S04,S05 | 名单冲突不隐藏无冲突结果；结果冲突同步隐藏冠军卡/JSON/结构化数据，保留其他内容 | 仅隐藏表格却泄露相同错误结果 |
| T06 / S06 | 跨日/DST/延期/取消/日期精度；旧 job 与新 generation 并发；时间到但无开赛/完赛证据 | 00:00 伪造；超时直接判完赛；旧 job 复活取消 |
| T07 / S06 | 完整名单含 WD/NR/DNF/DQ/并列、零 finishers、取消；比分与身份缺口分开 | 把退赛当缺行；名次强行连续；只匹配马名 |
| T08 / S07 | 首次确认后 24h、7d 边界；首日/第 2–7 天/长期未确认各阶段，资料恰在一次发现后发布，验证 60/120 秒内发现与 300/600 秒公开；更正不重置窗口，7d 后明确更正仍可进入 | 窗口关闭拒绝合法更正；把每日完整检查当及时发现 |
| T09 / S02 | 首发精确/区间/全未知；全部追踪存量峰值、低额度、429、索引遗漏更正、发现故障切备；探针见旧缓存 | fetched_at 伪装首发；未证明索引覆盖；遗漏 7 天存量预算；越额请求 |
| T10 / S08 | 一场多错误/多超时只计一次；未知不当正确；修复保留历史失败；跨窗 outstanding | 小字段稀释、移动窗口删除失败、占位当成功 |
| T11 / 原子性 | PostgreSQL 双 worker 同时提交、过期 lease、owner/policy 撤销、重复/乱序消息 | SQLite 掩盖锁问题；发布前校验与事务之间有竞态 |
| T12 / 原子性 | revision/items/epoch publication/state/outbox 任意一步抛错；提交后崩溃、consumer 取得 running lease 后崩溃、完成操作但 ack 前崩溃；过期 running 被 CAS 夺回，旧 token 迟到 ack 拒绝 | 部分结果公开；running 永久卡住；重复下游事件；旧 worker 确认新租约 |
| T13 / 兼容 | 空库迁移、生产形状匿名历史数据；中断/重复 backfill；未入选赛事旧路径；旧 phase | 全表隐藏；假造历史确认；混合新旧读取 |
| T14 / 回滚 | schema only、shadow、启用后各阶段回退；停止新 claim、在途 fence、关闭开关、旧 epoch 缓存 | rollback 重新公开已撤销错误值；回退程序读不了 schema |
| T15 / S09 | 每地区完整真实赛日：名单→变化→完整结果→公开版本；7 天观察分别记录 | 只验 parser 即交付；拿回放充真实数据 |
| T16 / 性能 | 地区峰值赛事/来源规模×2 的合成压力，批量页 100 场，多路故障、DB/Redis 故障 | N+1、抢占重点额度、刷新风暴、长事务网络 |

测试分层：
1. 纯合同/决策：现有 test_race_timeliness_contracts、test_race_source_arbitration、test_race_data_sync_policy_v2、test_race_information_display、test_race_result_roster_reconciliation，补上述 mutation/boundary 用例。
2. Django 应用：test_race_data_sync_results、test_race_information_display_pages、test_race_public_coverage 及新 projection/metrics tests；断言真实公开 DTO/HTML 和 revision 一致。
3. 本地独立 PostgreSQL/Redis/Celery：使用专用测试 DB、端口与队列，外部 HTTP stub；并发/事务/锁/重投/恢复不可用 SQLite 代替。所有自动测试禁止真实第三方网络或生产依赖。
4. 预发布回放：冻结至少 300 场，九地区各至少 20 场，其余补异常；首个地区可以先以该区至少 20 场及全部相关异常验收，不等待其他区凑齐。冻结验收集与调参集分开，保存 raw hash/parser/期望证据。
5. 真实验证：按 rollout 绑定的样本清单、时间窗和请求预算执行，与自动测试分开。每个交付地区至少一个完整赛日，没遇到的异常由回放证明，不编造自然覆盖。

阈值严格按 < 比较：100 场 1 错不通过，100 场 3 卡不通过；小样本也报 N/E/U/D/L、时延区间和 coverage。独立验收回放必须零身份错配/零伪造确定、全部必要断言通过。自然样本不足或审核缺失时不作长期达标结论。

性能接受条件：清单/页面批处理 100，查询数不得随赛事数线性增长；重点和常规公开时效分别不超过 300/600 秒，含发现、队列、fallback、缓存和探针。记录队列 p95/p99、最高请求量、超时分子，而不是只报均值。没有真实速率证据不能只凭合成压测宣称容量可用。

## 本轮实际自动化映射

`server/stable/test_race_lifecycle_{storage,publication,multisource,schedule,delivery,metrics,capacity,sources}.py` 为本轮新增回归，使用真实隔离 PostgreSQL。覆盖 T01–T16 的核心负例：缺来源/未知时钟不算成功、完整性/成熟度、精确截止、冲突与明确更正、A→B→A、改期/取消恢复、重复投递/崩溃/双 worker、预算到期、新义务不能借旧 probe、人工字段锁、全站结果表面、DOM可见内容。

这些不是各地区自然赛日或正式生产SLA测试；逐区真实数据与完整覆盖仍按 [implementation.md](implementation.md) 的边界记录。独立 review 发现的11项问题对应本轮测试名和最终结果保存在 [validation.json](validation.json)。

第二轮 review 回归另覆盖：旧 corrected 重放、晚于旧发布但早于冲突的纠错、纠错关闭时的相同事实/成熟度变更、确定→临时倒退、乱序旧冲突及冲突时间倒退、较新明确纠错正向恢复；历史无 display_name 的原版本在新观测授权后继续可见；未知/临时资料义务由确定后继履约，跨 generation 或明确 B 对旧 A 仍拒绝。均使用隔离 PostgreSQL 与本地网页探针替身。

完整原生审核回归另覆盖：关闭纠错仍允许 provisional 首次转 official；相同结果/名单重采保持 epoch 幂等并防止乱序覆盖；组合 race_time+racecard claim 的取消在名单不完整时仍落地，applied_kinds 不虚报名单成功；已核验跨语言映射不产生假冲突，未核验映射拒绝、真实负磅变化保留冲突隐藏。

最后的马号更正回归覆盖实际跨来源 producer、已核验 participant 映射及公开不可变 revision：明确更正更新马号，无标记仍冲突，人工锁优先。
