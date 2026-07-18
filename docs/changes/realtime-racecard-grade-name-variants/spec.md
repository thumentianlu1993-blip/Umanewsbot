# 英国 racecard 级别后缀精确匹配规格

## 背景与已验证根因

生产准实时 racecard 增量已部署，但 scheduler、runner 和公开读取仍关闭。首个英国
event `924` prepare 对 today/tomorrow 两个固定 GB endpoint 请求均为 HTTP 200，严格匹配
返回 `racecard_not_found`，没有生成 manifest 或写入赛事事实。

2026-07-18 的一次只读、单请求诊断复用了生产镜像的 TLS、schema 和字段白名单，只输出
客观候选摘要且未保存 raw、未写数据库。诊断确认来源并非缺场：

- 生产赛事名：`HALLGARTEN AND NOVUM WINES HACKWOOD STAKES`
- `normalized_grade=G3`
- TRA 名称：`Hallgarten And Novum Wines Hackwood Stakes (Group 3)`
- 赛场/日期：`Newbury / 2026-07-18`
- `off_dt=2026-07-18T15:02:00+01:00`
- `external_race_id=rac_13000002795`
- participant 数量：`7`

现有 NFKC/casefold/标点空白归一化后，两侧只差末尾 `group 3`。这是级别装饰形式差异，
不是 substring、编辑距离或时间近似问题。

## 目标

1. 保留现有 `GB + London local date + normalized course + approved name + unique match`
   全部门禁。
2. 对英国 `normalized_grade=G1|G2|G3` 的赛事，从已批准英文名称集合确定性派生唯一的
   末尾 `Group 1|Group 2|Group 3` 精确变体。
3. 让 `Name` 与来源 `Name (Group N)` 在级别一致时精确命中。
4. 级别不一致、非 G1-G3、额外文字、substring 和多候选继续 fail closed。
5. 不新增生产 alias、不猜测开赛时间、不保存 raw、不放宽初始化或公开门禁。

## 范围

### 名称来源

基础名称集合继续只来自：

- `RaceEvent.original_name`；
- active、非中文且不含汉字的 `RaceEventAlias`；
- `RaceSeries.canonical_name_original`；
- 同年度有效、active、非中文且不含汉字的 `RaceSeriesName`；
- 同年度 active `MajorRaceEvent` 的英文名称与 aliases。

本变更不新增、更新或删除上述数据库行。

### 级别变体

仅允许以下映射：

| `RaceEvent.normalized_grade` | 允许派生的末尾 token |
| --- | --- |
| `G1` | `group 1` |
| `G2` | `group 2` |
| `G3` | `group 3` |

对每个已经归一化的基础名称 `base`，先识别其中全部独立的
`group 1|2|3` token，再执行 fail-closed 分支：

1. 恰好一个 token、位于字符串末尾且与 event 映射相同：只保留 `base` 一次，不再追加。
2. 存在异级、非末尾或多个 Group token：`base` 不进入获准集合，也不得继续派生。
3. 名称中没有受识别 Group token：保留 `base`，并额外加入精确字符串
   `<base> <mapped-token>`。

因此 G3 event 的已批准名称若错误写成 `Foo (Group 2)`，既不能直接授权来源
`Foo (Group 2)`，也不能派生 `foo group 2 group 3`。

以下情况不得生成变体：

- `normalized_grade` 为空、`L`、`OP`、Jpn、J-G 或其他值；
- 基础或来源名称末尾携带与 event 不一致的 Group 级别；
- 来源名称在正确 Group token 后仍有额外文本；
- 只在名称中间出现 Group token；
- 需要删除 sponsor、handicap、stakes 或其他业务词才能命中。

### 既有门禁保持不变

- 仅固定 The Racing API GB today/tomorrow 路由。
- London 当地日期必须精确相等。
- 赛场归一化后必须精确相等。
- 必须恰好一个候选；零命中/多命中均无 manifest。
- 外部赛事 ID 不得跨 event 重用。
- baseline、人工锁、现有 live/result 占用、registry/terms/host budget、artifact 原子性、
  initializer schema v2 和 replay/CAS 契约不变。

## 非目标

- 不实现 fuzzy/substring/edit-distance 匹配。
- 不自动写 `RaceEventAlias` 或 `RaceSeriesName`。
- 不支持 sponsor 增删、简称、拼写错误或赛场别名。
- 不扩展到法国、美国、日本或香港。
- 不改变 parser、请求路径、请求预算、registry digest、模型、迁移或 Compose。
- 不在本变更中运行 initializer apply、开启 shadow、scheduler、runner 或公开模式。
- 不购买或升级 The Racing API 订阅。

## 验收标准

1. G3 event 的 approved base name 可精确命中同名末尾 `(Group 3)` 的 TRA racecard。
2. G3 event 不得命中 `(Group 2)`、`(Listed Race)`、`(Group 3) Sponsored`、
   `Group 2 Group 3` 或 substring；已批准名称自身末尾 Group 级别错误时也必须排除。
3. 非 G1-G3 event 不得获得 Group 变体。
4. event original、active alias、series canonical、有效 series name 和 MajorRaceEvent
   name/normalized_name/aliases 的同级别末尾变体均被直接测试，并继续遵守原 active、年度、
   语言和汉字排除门禁。
5. 两个同样满足条件的来源候选仍输出 `racecard_ambiguous` 且无 manifest。
6. 既有无级别精确匹配、London instant、HostBudget、artifact、initializer 与 runner 测试不变。
7. 无模型或 migration 变化；Django check、migration drift、目标测试和受影响回归通过。
8. 生产验证只允许一个显式英国 G1-G3 event、最多两个既有 Free 请求；blocker run 继续无
   manifest。成功 manifest 仍需用户单独批准后才可 initializer apply。
