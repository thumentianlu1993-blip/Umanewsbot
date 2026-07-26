# 赛事日历自动更新与赛事生命周期测试用例

## 1. RED 原则

取得用户实现授权后，先由测试 subagent 写测试并运行。RED 必须由以下目标能力尚不存在导致：

- lifecycle control/audit 模型不存在；
- 纯时间决策/原子推进服务不存在；
- 新闻 impact assessment/特殊池不存在；
- 来源权威比较不存在。

fixture、迁移依赖、语法、数据库不可用或错误 mock 不算有效 RED。PostgreSQL 并发用例必须在
临时 PostgreSQL 运行，不能用 SQLite 的锁语义冒充。

证据追加格式：

```text
RED: command / timestamp / exit / failed test / expected capability gap
GREEN: command / timestamp / exit / counts
```

当前尚未获实现授权，因此没有编写测试或伪造 RED。

## 2. 阶段 A：生命周期

| ID | 场景 | 预期 |
|---|---|---|
| A01 | 有出走时间，T-1 秒 | 保持 scheduled |
| A02 | 到达 aware `race_datetime` | 单次 scheduled -> running |
| A03 | T+30 分钟无赛果 | finished，result_confirmed_at 仍空 |
| A04 | 来源任务失败 | 时间状态仍推进，不生成 result/revision |
| A05 | 无时间，当地赛事日 23:59 | 不推进 |
| A06 | 无时间，当地次日 00:00 | finished，结果待补全 |
| A07 | `Europe/London` DST 开始/结束 | 边界由 ZoneInfo 正确换算 |
| A08 | `Europe/Paris` DST 开始/结束 | 同上 |
| A09 | `America/New_York` DST ambiguous/nonexistent | 有 offset 正确；无 offset fail closed |
| A10 | `America/Los_Angeles` 与纽约同 instant | 当地日期/时间分别正确 |
| A11 | 日本/香港 | 不受 DST 影响 |
| A12 | 无效 timezone | 不推进，记录错误，不用服务器时区 |
| A13 | cancelled 到点 | 不变 |
| A14 | postponed 旧时间到点 | 不变 |
| A15 | 延期写新时间/generation | 旧 generation task 拒绝，新时间生效 |
| A16 | 同任务重复 10 次 | 只一条有效 transition |
| A17 | 两 worker 同时处理 | 只一次状态更新/审计 |
| A18 | claim 超时 | 后续 scanner 可回收 |
| A19 | dry-run | 零业务/审计写入，返回计划 |
| A20 | shadow | 写候选审计，不改变公开 status |
| A21 | enforce | 原子写 status/audit/control |
| A22 | 事务晚期失败 | status/audit/control 全回滚 |
| A23 | official/corrected 已存在 | 不回退结果 phase |
| A24 | provisional 已存在 | finished 与 provisional 同时成立，confirmed_at 为空 |
| A25 | 无 lifecycle control | 默认不启用、不隐式回填执行 |
| A26 | 显式纳管 manifest apply 两次 | 第一次建档，第二次 replay，零重复 |
| A27 | priority/featured/visibility 失去资格 | 既有 control 关闭，不扫描全表扩容 |
| A28 | 新重点赛事不在 manifest | 不自动纳管 |
| A29 | shadow 三次后首次 enforce | 一条 proposal、一条 applied、状态只改一次 |
| A30 | enforce 再重放 | applied 不重复 |
| A31 | 香港/英国/法国使用其他有效 IANA zone | 全部 fail closed |
| A32 | 日本使用非东京有效 zone | fail closed |
| A33 | 美国 `America/*` 与 manifest 审核 zone 不同 | fail closed |

## 3. 来源权威与字段审计

| ID | 场景 | 预期 |
|---|---|---|
| B01 | 官方结构化写空字段 | 写入 authority=500 与 field change |
| B02 | 专业 API 后写不同值 | 不能覆盖官方 |
| B03 | 官方新闻覆盖可信媒体 | 允许并升级 authority |
| B04 | 同 authority 同值重放 | 不重复 field change |
| B05 | 同 authority 不同值 | 冲突候选，不覆盖 |
| B06 | 人工 lock | 任一自动来源不覆盖 |
| B07 | 闸位变化 | old/new/source/url/confidence/task 完整 |
| B08 | 骑师变化 | 同上 |
| B09 | 退赛变化 | runner 状态与审计一致 |
| B10 | 时间变化 | instant/local fields/generation 原子一致 |
| B11 | provider omission | 不自动解释为退赛 |
| B12 | 多地区某来源 429 | 仅该来源降频，其他地区继续 |
| B13 | 请求预算耗尽 | 无新网络请求，保留 due/retry 证据 |
| B14 | racecard/result owner 为 live | 历史/普通候选不能抢写 |
| B15 | 同场两匹马分别更新 jockey/barrier | authority/change 以 stable_key 隔离 |
| B16 | participant stable identity merge | 未审核不合并；审核后 provenance 可追溯 |
| B17 | 已付费但非官方聚合 API | authority 仍为 supplemental，不得产生 official |
| B18 | 合同只授权英国 official | 不得把同 provider 的法国/日本数据提升为 official |
| B19 | `provider_contract_version`/schema 变化 | registry fail closed，旧批准不自动继承 |
| B20 | racecard 只覆盖未来 7 天 | 不得伪装满足 P0 T-21/T-14 窗口 |
| B21 | 商业来源超额、停服或合同到期 | fallback 生效，时间状态继续推进，不伪造字段/结果 |
| B22 | JRA external event ID 尝试绑定 NAR/JPN1 | 身份拒绝、零写；不能只按 `JPN1`/地区名称路由 |
| B23 | NAR provider 合同/许可未冻结 | provider 保持关闭，时间生命周期仍推进 |
| B24 | TRA 法国某场 G1 缺失 | 逐场 fail closed/result pending，不从地区库存推断覆盖 |
| B25 | North America entries 省略 runner | 不解释为退赛；只有明确 `changes` 语义才可候选 |
| B26 | 爱尔兰赛事进入 selector | 本 change 拒绝纳管，不映射为英国或 `other` |
| B27 | snapshot 无 `COMPLETE`/签名或 payload hash 错 | 整批零写，消费水位不推进 |
| B28 | snapshot collector/build/schema/contract/token 漂移 | fail closed，旧 token 在轮换后不可重放 |
| B29 | snapshot 重放/乱序/缺前驱 | 重放 noop；乱序和缺前驱零写并告警 |
| B30 | snapshot DB 事务失败 | 字段候选和 high-watermark 同时回滚 |
| B31 | collector split brain | 只有 registry 活动 fencing token 被接受 |

## 4. 新闻特殊放行

| ID | 场景 | 预期 |
|---|---|---|
| C01 | 官方闸位公告＋唯一赛事＋高置信 | 绕过普通分数进入发布流程 |
| C02 | 退赛/骑师/名单/时间延期 | event_type 与 extracted_changes 正确 |
| C03 | 翻译失败 | 仍阻断 |
| C04 | 高度重复 | duplicate 终态/阻断 |
| C05 | 窗口 fingerprint 重复 | 特殊池不选 |
| C06 | 只出现赛事名 | 不特殊放行 |
| C07 | 跨届同名、日期不明确 | review_required |
| C08 | 多个候选赛事 | 不写入 |
| C09 | confidence 89 | 不特殊放行 |
| C10 | confidence 90 且明确变更 | 可绕过软门禁，但仍过 validation |
| C11 | 缺标题/正文/source URL | 阻断 |
| C12 | published_at 未验证 | 阻断 |
| C13 | 核心术语/实体冲突 | 阻断 |
| C14 | 来源未 production approved | 阻断 |
| C15 | 普通地区配额已满 | 使用独立特殊小配额 |
| C16 | 特殊小配额已满 | 延后，不丢失，不占普通配额 |
| C17 | 新闻发布事务失败 | RaceEvent 字段零变化 |
| C18 | 新闻发布成功、candidate apply 失败 | 新闻保持公开，候选可重试 |
| C19 | 可信媒体与官方字段冲突 | 人工候选，不能覆盖 |
| C20 | `possible_duplicate_content` blocker | 仍阻断或转人工，不得特殊放行 |
| C21 | 内容编辑后 hash 漂移 | 旧 assessment 失效，需重评 |
| C22 | 重放 publish task | 不重复公开/AutomationLog |
| C23 | QQ | `(article,target)` 仍唯一，racecard_update 默认不自动 QQ |

## 5. 赛果与现有链路回归

| ID | 场景 | 预期 |
|---|---|---|
| D01 | T+2:59 | 不请求赛果 |
| D02 | T+0 | 只 CAS 到 awaiting_result、next=T+3、transport 调用 0 |
| D03 | T+3:00 | 已批准 tracking 首次调用 provider |
| D04 | provisional | tracking provisional，result is_confirmed=false |
| D05 | official | official authority/marker 后 confirmed=true |
| D06 | supplemental 声称 official | 拒绝 |
| D07 | T+30 来源仍失败 | RaceEvent finished、tracking awaiting、无伪造结果 |
| D08 | 无时间次日 | finished＋补采候选，不直接启动未批准 provider |
| D09 | corrected | official -> corrected 受控前进 |
| D10 | 现有 event 924 | publication/read/kill-switch 行为不回归且不重跑 |
| D11 | scheduler disabled | selector 不 claim/dispatch |
| D12 | race_live_worker | 只消费 race_live queue |
| D13 | 生命周期任务 | 不重复 dispatch 同一 live claim |
| D14 | JRA 三名阶段 | 只能 provisional，`result_confirmed_at` 为空 |
| D15 | JRA 五名阶段重放 | 仍 provisional，审计和 revision 不重复 |
| D16 | JRA 全马但 marker 未登记 | fail closed，不 official |
| D17 | JRA proof 中明确最终 marker | official，且只设置一次 confirmed_at |
| D18 | JRA official 后明确 correction marker | corrected，保留前序 revision |
| D19 | NAR CSV 使用 JRA marker | 拒绝；必须命中 NAR 独立合同 |
| D20 | 美国长期无官方复核 | 保持 provisional/official-overdue，不伪造 official |

## 6. 性能、页面与回归

1. 100 个 due control 的选择不超过 8 个查询，内存由 batch size 限制。
2. 并发 scanner 使用 `skip_locked`，没有全表锁。
3. 日历和详情在同一 commit 后显示一致状态。
4. `RaceEvent` save 与 bulk lifecycle apply 都能失效赛事 cache。
5. 日历 query 继续满足既有 live read `<=12` 门禁。
6. 1440px/390px/320px 日历月份、等级 badge、无横向溢出不回归。
7. 赛事详情的暂定/正式标签不回归；provisional 不显示为“正式赛果”。
8. 字段归一化测试、赛事导入/历史 inventory、racecard sync、race-live、新闻 validation、
   publishing window、QQ delivery 全部回归。
9. `manage.py check`。
10. `makemigrations --check --dry-run`。
11. PostgreSQL 竞争/事务测试。
12. `git diff --check`。
13. 一次性 dry-run 连续执行两次均为零数据库写入/零 Celery dispatch；持久 scanner 不支持
    dry-run mode。
14. rollback baseline manifest 的 SHA、generation 漂移、反向 candidate dry-run 和隔离恢复。

## 7. 推荐测试文件

- `server/stable/test_race_event_lifecycle.py`
- `server/stable/test_race_event_lifecycle_postgres.py`
- `server/stable/test_race_event_field_authority.py`
- `server/stable/test_race_news_impact.py`
- 扩展现有 `test_realtime_race_results.py`
- 扩展现有 `test_race_live_racecard_sync.py`
- 扩展现有 publishing/validation/QQ 测试
