# 测试用例

## 1. Inventory 与到期分母

| ID | 场景 | 必须捕获的错误 |
|---|---|---|
| I01 | 59 条 event row、50 个 race group、9 组跨系列重复候选 | 不得把 50 个 group 误当作 50 条底层记录 |
| I02 | 有 `race_datetime` 且未到 T+30m | 不得提前进入赛果应到分母 |
| I03 | 无 `race_datetime`、已过当地次日零时 | 必须进入应到分母 |
| I04 | 非法/缺失时区或日期 | 必须 blocker，禁止按服务器日期猜测 |
| I05 | cancelled/postponed | 不进入赛果应到分母，保留明确状态 |
| I06 | inventory 后 event/results/series/visibility 漂移 | prepare/apply 必须拒绝旧 manifest |
| I07 | 所有目标 accounted 但仍有 blocker | accounted 可通过，completion 必须失败 |
| I08 | 基线分解 | 精确证明 `59 = 40 missing + 9 duplicate-zero + 9 duplicate-confirmed + 1 provisional` 及 `50 = 40 + 9 + 1` |
| I09 | 40 场 source map | event ID 集合精确等于日本 6、英国 11、法国 4、美国 19；924 与 9 条重复产品行不得混入 |

## 2. Identity 与 canonical link

| ID | 场景 | 必须捕获的错误 |
|---|---|---|
| D01 | 同日期同名、不同系列、未审批 | 不得跨 event 投影 |
| D02 | 批准 duplicate→canonical | 创建 active link，日历只展示 canonical |
| D03 | self link | 数据库 constraint 与服务层均拒绝 |
| D03A | 跨地区或跨年度 | 事务服务层拒绝；不得声称跨 FK 数据库 constraint 可表达 |
| D04 | canonical 自身又是 duplicate、链式或环 | 服务层拒绝且整场零写 |
| D04A | 两事务并发创建共享端点 link | PostgreSQL advisory/row lock 串行化，后提交者重检后拒绝链或环 |
| D05 | 旧详情 URL 直接访问 | 仍返回 200，并提供 canonical 链接 |
| D06 | rollback canonical link | link inactive，公开选择恢复，底层赛事不删除 |
| D06A | rollback 后改选另一 canonical | 创建新的 active link，旧 inactive 审批行和值完整保留；同一 duplicate 不得有两条 active |
| D07 | migration 往返与旧数据 | 新表为空迁移、constraint/index/PROTECT 正确；回迁前存在审计 link 时按 rollout 阻断，不销毁证据 |

## 3. 结果专用编排与来源层级

| ID | 场景 | 必须捕获的错误 |
|---|---|---|
| C01 | recovery purpose 仅请求 results | 不要求 runners/history_winners |
| C02 | 普通编排只给 results | 继续按旧三模块规则拒绝 |
| C03 | adapter 返回多模块 | aggregate 只保留批准 results |
| C04 | 某地区应到但零候选 | 逐 event blocker，不得缩分母 |
| C05 | TRA 或两个第三方来源一致 | 只能 provisional/candidate，不能 confirmed |
| C06 | 官方 route host/path/marker/contract 任一不符 | evidence 拒绝 |
| C07 | evidence 含凭据或受限 raw body | schema/安全测试拒绝落盘 |
| C08 | manual-only route 被 recovery 自动请求 | transport 前拒绝，network request count=0 |
| C09 | route registry/terms/contract 过期或 digest 漂移 | receipt、dry-run、apply 三处全部拒绝 |
| C10 | recovery receipt 含同着与 SCR/DNF/DSQ | repeated/null official position 合法，internal order 唯一且状态保真 |
| C11 | live manual receipt 误用于 non-live | 因缺 live allowlist/incident/tracking/authorization 拒绝，不补造控制面 |

## 4. Projection owner、revision 与 apply

| ID | 场景 | 必须捕获的错误 |
|---|---|---|
| P01 | event 924 owner=live 且前置完整 | 走既有 manual official transition，不得抢 owner/direct write |
| P01A | 任一 live 前置缺失 | blocker、零写，不得退回 recovery historical service |
| P02 | owner=historical | 在当前 generation 创建 official revision 后投影 |
| P03 | owner=unmanaged | CAS 晋级 historical、generation+1、绑定 manifest |
| P04 | owner=manual_paused | 整场 blocker、零业务写 |
| P05 | generation/current revision 漂移 | 写前 fail closed |
| P06 | 官方并列名次、SCR/DNF | internal order 唯一，official position/status 保真 |
| P07 | official 替换 provisional 集合 | 只执行批准的 result create/update/delete，旧 revision 保留 |
| P08 | 事务后段 OperationLog/ledger 发布失败 | event、control、revision pointer、results、canonical link 全回滚 |
| P09 | 相同 artifact 幂等重放 | 所有业务/审计表及 updated_at 零变化 |
| P10 | rollback | 恢复旧 owner/current revision/projection/status/confirmed_at/link，不删 revision/evidence |
| P11 | non-live 无 participant | 仅按受审 source runner ID 或 manifest 绑定官方原名+马号创建 participant/source identity |
| P12 | participant 重名、马号冲突或模糊命中 | 整场 blocker，不按中文译名/相似度绑定 |
| P13 | ledger 已发布、DB 未提交即崩溃 | verifier 标 `prepared_not_applied`，禁止 rollback；重跑不覆盖原文件 |
| P14 | ledger 发布/OperationLog 后段失败 | 本进程拥有的 ledger 清理且数据库事务全回滚；外部同名文件绝不删除 |
| P15 | recovery management command phase | crawl network-only、apply write-only、verify neither；runner allowlist/参数分类缺失即拒绝 |

## 5. 页面、性能与非影响

| ID | 场景 | 必须捕获的错误 |
|---|---|---|
| U01 | confirmed canonical event | 全部/重点/已完赛一致显示冠军 |
| U02 | blocker event | 不展示虚构冠军 |
| U03 | cancelled/postponed | 不进入已完赛 |
| U04 | active duplicate link | 日期轴和日历只出现 canonical 一次 |
| U05 | 59 条 inventory 与 40 场日历读取 | inventory `<=25 SQL`，公开日历保持既有 `<=12 SQL` 硬门禁，无逐 event N+1 |
| U06 | apply 前后非目标快照 | 新闻、QQ、窗口外赛事、未来赛事和公开开关不变 |
| U07 | 自动化测试 | 禁止真实网络、生产数据库和本地 secret 依赖 |

## 6. 生产形状验证

- PostgreSQL 覆盖 owner/generation CAS、`select_for_update`、并发 apply 与 rollback。
- 五地区 adapter 使用离线 fixture 覆盖字段、非完赛状态、并列和来源 URL。
- 生产只读 inventory、网络 prepare、正式 apply 分别使用不同授权和不可变 SHA。
- 浏览器验收覆盖 1440px、390px、全部/重点/已完赛、五地区、canonical/旧详情 URL、console 和横向溢出。
- candidate network prepare 总请求硬预算 `<=75`、单请求超时 `<=30s`、source cache
  `<=512 MiB`；缓存命中与 resume 不得重复请求，预算耗尽按 event blocker。
