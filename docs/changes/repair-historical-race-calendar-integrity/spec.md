# 历史赛事赛历完整性修复规格

## 1. 背景

历史赛事公开链路同时存在四类已确认缺口：

1. 中国香港普通跨年马季的上半季赛事被错误归入后一自然年，公开年份、标题和 URL 与实际比赛
   日期不一致；香港杯抽样显示偏移至少可追溯到 2019。
2. 显式选择年份或搜索后，赛事查询只返回按日期升序排列的前 40 条，同时关闭前后分页，导致
   2024 日本页面表面上停在 4 月 6 日。
3. 美国部分跨栏赛使用 `-` 表示没有马号，年度参赛马采集器却把 `-` 当成真实唯一编号，第二匹
   马即触发 identity conflict。
4. 历史年份“重点”仍按 `priority=P0/P1` 或 `is_featured` 过滤；历史物化赛事默认
   `P2/False`，因此已存在的 G1/G2 也全部消失。

四个问题共享“历史赛事事实身份与公开查询合同不一致”的根因，必须在同一 change 中统一
修复和回归，避免数据修复后仍被旧查询或采集规则再次污染。

## 2. 目标

- 公开赛事年份统一表示实际比赛所在自然年。
- 真正的届次年份独立保存，不再复用公开年份字段表达。
- 修复香港存量错误，并阻止普通马季跨年再次生成错误年份。
- 显式年份和搜索查询能够分页遍历全部匹配赛事，保持所有筛选参数且无重复、无遗漏。
- 显式选择历史年份时，“重点”精确表示 G1/G2 等级族。
- 缺少马号的跨栏赛可以完整采集；真实马号冲突继续 fail closed。
- 所有生产数据变更都经过不可变审核 artifact、数据库备份、显式授权和写后 verifier。

## 3. 术语与年份合同

### 3.1 公开自然年

`RaceEvent.year` 是公开自然年：

- `local_date` 已知时，必须等于 `local_date.year`；
- 公开年份筛选、标题、详情 URL、sitemap 和前台年份列表均使用该字段；
- `local_date` 暂缺的当前/未来赛事暂用受审排期自然年，日期补齐后必须重新校验。

### 3.2 届次年份

新增 `RaceEvent.edition_year` 保存赛事系列的届次身份：

- `HistoricalRaceEventTarget.year` 继续表示届次年份；
- target 与 event 的身份关联比较
  `HistoricalRaceEventTarget.year == RaceEvent.edition_year`；
- 普通香港马季的 9—12 月赛事不构成跨届次举办，届次年份仍应等于比赛自然年；
- 只有真实延期、补跑或来源明确采用不同届次年的赛事，才允许
  `edition_year != year`，并继续要求 `actual_year`、原因、权威证据和人工批准。

### 3.3 等级族

历史“重点”的 G1/G2 包含：

- G1 族：`G1`、`JG1`、`JPN1`；
- G2 族：`G2`、`JG2`、`JPN2`。

## 4. 用户行为

### 4.1 历史年份与地区筛选

- 用户选择 2024、日本、“全部”时，可以从年初连续分页浏览至年末。
- 用户选择历史年份和“重点”时，只返回该年份、地区、搜索词、时间状态等其他条件下的
  G1/G2 等级族赛事。
- 当前年、未来年或未选年份时，“重点”继续使用现有 P0/P1/人工置顶运营口径。
- `grade` 与“重点”同时存在时取交集，例如历史重点 + G1 只显示 G1，历史重点 + G3 为空。

### 4.2 分页

- 单页仍最多展示 40 场。
- 年份、搜索词、地区、重点/全部、等级和比赛状态在前后分页时全部保留。
- 分页使用稳定复合游标，不得仅按日期截断。
- 无效、篡改或与当前筛选不匹配的游标不得产生 500；系统回到该筛选的第一页并不执行越界查询。
- 同一筛选遍历全部页面时不得重复或遗漏赛事。

### 4.3 年份修复后的详情 URL

- 修复后的赛事使用自然年和纠正后的 canonical slug。
- 已公开旧 URL 必须返回永久重定向到新 canonical URL。
- 重定向只能来自明确的路径别名记录；多义、冲突或未审核路径不得猜测目标。

### 4.4 无马号跨栏赛

- `""`、`-`、`–`、`—` 统一表示“未提供马号”，输出规范值为空字符串。
- 占位符不得进入真实马号唯一身份表。
- 缺少马号时依次使用受限来源内稳定 profile/source ID、规范化马名作为身份；仍然多义时
  fail closed，不使用行号或抓取顺序伪造身份。
- 非占位的字母数字马号（例如 `1A`）继续作为真实马号。
- 同一真实马号对应不同马匹时继续报错。

## 5. 全库年份普查与香港数据治理

- 最终自然年数据库约束是全库合同，因此修复工具必须先只读枚举所有地区
  `year != local_date.year` 的赛事。每一行都必须进入 approved action；合法跨届次也必须修复
  event 的公开 `year/slug/path`，只保留原 `edition_year`，不能以“已分类”代替写入动作。任何
  未批准或未执行 action 都会阻断最终约束发布。
- 中国香港是本 change 的强制修复子集。工具必须枚举其相关
  `HistoricalRaceEventTarget`、系列、runner/result、历史冠军、文章链接、P0 来源、canonical
  link、live projection、sitemap/public path 依赖。
- 审核 artifact 必须逐赛事给出：
  - 当前 event/target/series 身份和 SHA；
  - 当前/拟议 `year`、`edition_year`、slug 和 public path；
  - 普通马季纠错或真实跨年届次的分类与证据；
  - 同系列完整 `target -> event -> local_date -> proposed edition` 图；
  - `rotate_year`、`canonicalize_duplicate`、`repair_public_year_keep_edition` 或 `block` 动作；
  - target 重编号、canonical event 选择、依赖重挂/保留、事件改名、旧路径和冲突处理动作；
  - 所有依赖行的写前计数与哈希。
- 不能根据 `year != local_date.year` 自动把所有记录改成自然年；真实延期必须保留独立届次年份。
- 不能只修已知 12 场或只处理 2024/2025。
- 多对一重复不能伪装成年份轮转。artifact 必须明确唯一 surviving canonical event、被合并
  event 的状态、全部 FK 重挂或“禁止自动合并”的理由，以及所有旧 URL 的目标。
- `canonicalize_duplicate` 的固定终态为：
  - survivor event 保留 series、正确 `edition_year/year/slug` 和公开 canonical path；
  - duplicate event 在全部可重挂 FK 完成后设 `race_series=NULL`、公开自然年正确、改用唯一
    tombstone slug、永久 draft，并在 provenance 中绑定 survivor；
  - duplicate target 设为 `SUPERSEDED`、`event=NULL`，保留原 year/证据并通过
    `superseded_by/superseded_at/manifest_sha256` 指向 survivor target；
  - target 唯一约束只覆盖未 supersede 行，因此以后仍可创建该系列该届次的正确 active target；
  - 任一不可安全重挂依赖都会把 action 变为 `block`。
- artifact 中任何未决 canonical 选择、系列年度冲突、目标链断裂、当前状态漂移或未知依赖都会
  阻断对应 action scope；最终数据库约束发布要求全库 blocker/待修复均为 0。
- apply 必须绑定独立不可变 approval：manifest SHA、精确 action IDs、批准人、批准时间和
  approval SHA；布尔确认不能代替审批证据。

## 6. 验收标准

1. 香港普通马季 fixture 不再产生后一自然年的 event/target；真实延期 fixture 能保存独立
   `edition_year`，公开年份仍等于实际自然年。
2. 修复后的旧香港 URL 301 到新 URL，新旧 URL 不产生两张公开卡片。
3. 2024 日本超过 40 场的 fixture 可完整分页，最后一页包含年末赛事，全程无重复、无遗漏。
4. 年份/搜索分页保持 tab、region、grade、when、year、q，篡改游标安全回退。
5. 历史“重点”包含 G1/JG1/JPN1 与 G2/JG2/JPN2，排除 G3 和仅人工置顶的历史 G3。
6. 未选历史年份、当前年和未来年的“重点”行为保持 P0/P1/人工置顶。
7. 多匹 `horse_number="-"` 的跨栏赛可以完成解析；合法 `1A` 保留；真实重复马号冲突仍失败。
8. 全库 census/香港 prepare 为零写入；apply 只接受精确 manifest、approval、action scope 和
   actor，写后 verifier 守恒。
9. Django check、迁移漂移、相关 SQLite/PostgreSQL 测试、完整 stable 回归和 `git diff --check`
   通过。
10. 最终自然年约束发布前，全地区 mismatch 已全部执行 approved action 且未修复/blocker 为 0；
    非香港合法延期已经修复公开 year/path，同时保留 edition fixture 与生产证据。

## 7. 非目标

- 不重抓全部历史赛事或重跑所有历史批次。
- 不改变当前/未来赛事的运营优先级配置。
- 不把 G3、Listed 或普通赛事加入历史“重点”。
- 不用批量设置 `priority=P1` 代替等级筛选修复。
- 不为缺失马号自动生成伪马号。
- 不修改 runner/result 的官方名次、马名或既有来源权威。
- 不自动发布 draft 历史赛事，不启用历史网络抓取或 Celery/Beat 调度。
- 不在本轮部署、执行生产审计、写生产数据库或清缓存。

## 8. 失败边界

- `local_date` 已知但公开自然年不一致：候选不得发布或继续物化。
- 香港审核分类证据不足、target 链冲突或依赖集合漂移：整批拒绝。
- 连续错年形成多对一但没有唯一 canonical/依赖动作：拒绝，不能强行保留全部 event PK。
- legacy path 与现有 registry 路径冲突：拒绝该 artifact，不覆盖原路由。
- 游标签名、版本或筛选指纹不匹配：安全回到第一页，不接受其中位置。
- 缺马号且 profile/source ID 与马名仍无法唯一识别：记录 gap 并失败，不猜测。
- 任何生产备份、HEAD、镜像、schema、artifact SHA 或行级 precondition 不匹配：禁止 apply。
