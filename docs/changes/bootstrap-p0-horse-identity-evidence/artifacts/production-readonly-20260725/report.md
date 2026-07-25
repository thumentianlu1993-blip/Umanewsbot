# 日本重赏 P0 官方身份锚点只读盘点

## 盘点边界

- 生产代码：`9b58bfd437f58dede0de5d11d64537e2e68e214e`
- 时间范围：1998–2026
- 等级：G1/G2/G3、J-G1/J-G2/J-G3、JpnⅠ/JpnⅡ/JpnⅢ
- 数据入口：active `HorseP0Source(source_type=major_race_participant)`，关联
  `RaceEvent`、`RaceEventRunner`、`RaceEventResult` 和 `HorseProfile`
- 初筛：`HorseProfile.racing_region=Japan`
- 操作：生产 PostgreSQL 只读 ORM 查询；未访问 JRA、NAR 或 Netkeiba，未写数据库
- 写前/写后五张核心表计数完全一致，见 `summary.json`

`racing_region=Japan` 和日本赛事地点只能形成潜在候选上界，不能证明日本训练身份。因此下列
7,228 是唯一 profile 行数，不可表述为 7,228 匹已确认日本训练且已正确去重的真实马匹。

## 关键结果

| 项目 | 数量 |
| --- | ---: |
| 潜在日本 profile | 7,228 |
| 已保存 JRA/NAR 马匹详情 ID 或 URL | 0 |
| 只有 JRA/NAR 官方赛事上下文 | 7,164 |
| 唯一 Netkeiba ID | 1,353 |
| 身份底稿已完整 | 60 |
| 身份底稿不完整 | 7,168 |
| 官方赛事上下文 + 唯一 Netkeiba + 底稿不完整 | 1,283 |
| 只有 Netkeiba、没有官方赛事上下文且底稿不完整 | 10 |
| 没有 Netkeiba、没有可识别官方上下文 | 53 |
| 已有结构化日本训练确认 | 0 |

官方赛事上下文中，JRA 为 7,044，NAR 为 120。当前数据库没有任何对象可以直接走
“已有官方马匹锚点”的第一层路线。

## 可立即处理的上界

如果第二层 provider 能从官方赛事上下文稳定解析出唯一马匹详情锚点，则当前最多有 1,283 个
“唯一 Netkeiba ID + 官方赛事上下文 + 身份底稿不完整”的候选可进入后续双源 prepare。按最高
参赛等级拆分：

| 最高等级 | 数量 |
| --- | ---: |
| G1 | 108 |
| G2 | 349 |
| G3 | 789 |
| J-G1 | 1 |
| J-G2 | 5 |
| J-G3 | 5 |
| JpnⅠ | 2 |
| JpnⅡ | 6 |
| JpnⅢ | 18 |

这些数字仍是处理上界，不是通过数。每个对象还必须从官方档案确认日本训练所属，并完成
Netkeiba/JRA 或 Netkeiba/NAR 的马名、父、母、完整出生日期一致。

## 暴露出的方案落差

1. 当前库没有直接 JRA/NAR 马匹锚点，原设计“PoC 优先从第一层锚点完整对象中选择”无法执行。
2. 7,228 个 profile 与 7,228 条资格来源一一对应，而 5,875 个 profile 没有 Netkeiba key；
   这表明现有 profile 行不能直接视为已经跨赛事去重的真实马匹。
3. 现有库没有结构化 `training_evidence`，所有 7,228 个对象都只能视为训练范围未确认。
4. 首个 PoC 应验证“JRA/NAR 官方赛事上下文 → 唯一马匹详情锚点”的解析能力，并只从
   1,283 个拥有唯一 Netkeiba ID 的底稿缺失对象中选样；若不能稳定取得锚点，PoC 必须阻断。

## 结论

任务 1.1 的只读盘点已完成。进入测试与 provider 实现前，需要先修订方案和 PoC 口径：

- 第一层“已有锚点”当前数量为 0；
- 第二层赛事上下文解析应成为一期首要能力；
- 1,283 是目前可尝试双源补证的最大候选池；
- 其余没有唯一 Netkeiba ID 的对象不能进入本轮双源自动处理。
