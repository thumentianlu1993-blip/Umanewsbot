# 英国 racecard 级别后缀精确匹配设计

## 现状

`race_live_racecard_sync._event_names()` 先把 event、alias、series 和 major event 的获准英文
名称归一化为 set；`_match_events()` 再要求 TRA `race_name` 的归一化值精确属于该 set。
生产 event `924` 的 base name 与 TRA 候选除末尾 `(Group 3)` 外完全一致，因此现有代码
安全地得到零命中。

直接向生产添加单场 alias 可以修复 event 924，但会把来源格式规律变成逐场人工数据维护，
且后续 G1-G3 仍可能重复失败。删除全部括号内容或使用 substring 又会放宽身份门禁。设计
选择在 event 侧从已审核 `normalized_grade` 派生有限、可证明的精确名称变体。

## 代码设计

### 1. 纯函数生成级别 token

在 `server/stable/services/race_live_racecard_sync.py` 内新增私有常量或纯函数：

```text
G1 -> group 1
G2 -> group 2
G3 -> group 3
其他 -> 无 token
```

不从 `grade_text` 自由解析，不接受 Roman numeral、`G3`、Listed、Jpn 或 J-G 变体；首版只
实现真实证据所需的 TRA `Group N` 形式。

### 2. 在候选名称集合上过滤并派生 suffix variant

`_event_names()` 继续完成全部原始名称的 active/year/language/汉字过滤，再在函数末尾用
固定正则扫描归一化字符串中全部具有空格边界的 `group ([123])` token：

1. 读取 `event.normalized_grade` 的固定 token。
2. 遍历当前基础名称 set，构造新的获准 set，不在原 set 上原地追加。
3. 恰好一个 Group token、位于字符串末尾且同级时只加入原 `base`，不重复派生。
4. Group token 异级、非末尾或数量大于一时不加入原 `base`，也不派生。
5. 名称中没有 Group token 时加入原 `base` 和 `<base> <token>`。
6. 非 G1-G3 event 维持现有基础名称 set，不执行上述 Group 过滤或派生。

变体使用已经归一化的字符串拼接，不重新读取来源数据、不改变数据库、不改变 response
canonical hash。候选 `race_name` 仍只调用一次 `normalize_identity_text()` 并执行 set 精确
membership。受识别的授权形式仍只限唯一且位于末尾的 `Group N`；中间或多个 Group token
只用于拒绝，不新增对任意括号、前缀、Roman numeral 或 `G3` 文本的自由解析。

### 3. 匹配与审计保持不变

`_match_events()` 的地区、London 日期、赛场、唯一性、external ID、off time 冲突和
participant manifest 逻辑不变。report/request/manifest schema 和 SHA 绑定不变，因此无需
registry、parser、模型、migration 或 initializer 修改。

## 数据与并发

- 无数据库 schema 变化。
- prepare 仍只可能更新共享 `RaceLiveHostBudget` 控制面。
- 不写 alias 或赛事时间；只有后续获准 initializer 才可能在原子事务中补时间和 shadow 行。
- 网络期间无数据库事务；名称变体只在已经加载的 event 快照上计算。
- 时间/空间增量为每个 event 最多把 approved name set 扩大一倍，现有 event batch 上限 500，
  不新增查询。

## 测试设计

在 `server/stable/test_race_live_racecard_sync.py` 先补真实 RED：

- event `normalized_grade=G3`、base `Hallgarten And Novum Wines Hackwood Stakes`；
- 来源 `Hallgarten And Novum Wines Hackwood Stakes (Group 3)`；
- 当前代码应返回 `racecard_not_found`，目标实现后生成 manifest。

同一测试组覆盖：

- `(Group 2)` 不匹配 G3；
- 已批准基础名称末尾 `(Group 2)` 在 G3 event 中被排除；
- 不产生或命中 `Group 2 Group 3`；
- 已批准基础名称末尾同级 `(Group 3)` 只保留一次；
- 已批准基础名称含非末尾或多个 Group token 时整条排除；
- `(Group 3) Sponsored` 不匹配；
- `normalized_grade=L/空` 不生成 Group 变体；
- 原 substring 拒绝测试继续通过；
- 两个同级候选继续 ambiguous；
- event original 与 active alias 的 suffix 变体；
- `RaceSeries.canonical_name_original` 的正向 suffix 命中；
- 年度 series name 的正向命中和 expired/inactive 拒绝；
- MajorRaceEvent name/normalized_name/aliases 的正向命中，以及 inactive、年份不符、含汉字
  拒绝。每类测试以目标来源名称只存在于该路径的方式捕获“只对部分名称派生”的 mutation。

## 生产验证设计

1. 代码发布前只使用合成测试，不保存 2026-07-18 API raw。
2. 发布时保持 scheduler false、runner disabled、public policy off；本变更无 migration。
3. 若仍处于 event 924 的 London 当日窗口，可用新 run-id 对 event 924 运行同一受控 prepare；
   若窗口已过，则选择下一个明确的英国 G1-G3 event，并先做同样的只读候选摘要核对。
4. prepare 仍最多两个请求；核对 response/report/request SHA、权限、唯一名称、London off time、
   participant 数量和无禁止字段。
5. blocker run 停止。成功 run 只提交 manifest 审核，不在本任务授权中自动执行 initializer。

## 回滚

- 代码发布前：删除独立 worktree 即可。
- 仅代码发布：回滚到上一镜像；flags 始终关闭，无业务数据回滚。
- prepare blocker：保留审计 artifact 与 HostBudget 状态，无业务事实回滚。
- 成功 prepare：manifest 尚未 apply，仅撤销后续批准即可。
- initializer 不属于本变更默认执行范围；若后续单独获准，沿用既有 ownership/CAS/备份回滚契约。

## 风险

- `normalized_grade` 错误会生成错误级别变体；因此仍需日期、赛场、base name 和唯一命中四重
  门禁。已批准名称存在异级、非末尾或多个受识别 Group token 时会整条排除，避免其直接
  授权或形成矛盾级别派生。
- TRA 未来改用其他装饰形式时仍会 fail closed；本变更不预先支持未观察格式。
- event 924 的当日窗口可能在发布前结束；它仍作为可复现测试证据，生产 shadow 可选择后续
  同类 G1-G3 event，不回填或伪造过期赛前数据。
