# 2025 分级赛参赛马补全与生产导入规格

## 背景

正式 run `31269803408` 已从 UmaFans 公开页产出 2025 七文件 artifact，但结果为
`outcome=partial`。五个既有地区共有 `1063` 场、`9292` 条参赛记录、`4965` 匹年度去重马；
澳大利亚、德国和中东没有公开赛事入口。名称/profile 缺口不能通过重复运行同一 workflow 消除。

用户已选择“先补全再导入”：允许使用各地区权威来源，继续禁止 Wikipedia/Wikidata；通过新
artifact 和导入门禁后，再把完整资料写入生产马匹信息。

## 目标

1. 修正研究 artifact 中已存在但未被接受的英文马名证据。
2. 以官方赛历和正式赛果补齐澳大利亚、德国、阿联酋、沙特、卡塔尔、巴林的 2025 G1/G2/G3
   参赛范围，不把未分级、Listed、报名或退赛马算作实际参赛。
3. 对全部年度参赛马生成稳定身份，优先绑定生产已有 HorseProfile，不按马名盲目新建。
4. 补全基础资料、二代血统和完整生涯履历；主胜鞍只能由导入的完整履历计算，不能复制来源摘要。
5. 通过 reviewed artifact、dry-run、写前备份、精确批准、事务 apply 和 verifier 写入生产；默认
   不自动公开新档案。
6. 修复线上同一身份的空档案、重复档案和错误名称/地区/履历，不删除无法证明等价的对象。

## 数据范围

- 年份：仅 `2025`。
- 地区：日本、中国香港、美国、英国、法国、澳大利亚、德国和中东。
- 中东国家：阿联酋、沙特阿拉伯、卡塔尔、巴林。
- 等级：日本沿用 G/J-G/Jpn G1–G3；其他地区只接受本地或国际 G1/G2/G3。
- 参赛语义：正式赛果中有实际起跑证据的马；退赛/non-runner 排除，未知状态阻断该行。

## 来源政策

### 赛事覆盖与参赛事实

- 既有五地区：以生产已审核 `RaceEvent`、`RaceEventResult`、source cache identity 和公开页 artifact
  交叉绑定，不再依赖公开 horse search 是否能看到 draft profile。
- 澳大利亚：Racing Australia 官方赛果。
- 德国：Deutscher Galopp 官方 Renntage/Ergebnis。
- 阿联酋：Emirates Racing Authority 官方 calendar/racecard/results。
- 沙特：Jockey Club of Saudi Arabia 官方 meetings/races/results。
- 卡塔尔：Qatar Racing and Equestrian Club 官方 season program/results；没有稳定正式赛果页时保持
  gap，不用媒体报道代替参赛表。
- 巴林：Bahrain Turf Club 官方 racecards/results。

赛事来源只证明赛事和参赛事实，不自动证明马匹完整身份。每个 provider 必须保存 provider race ID、
horse ID（若有）、canonical URL、内容 SHA、抓取时间和解析版本。

### 马匹资料

- 优先复用现有受控区域适配器及其身份合同：JBIS/Netkeiba、HKJC、Sporting Life/Racing Post、
  France Galop/Geny、Equibase/HRN。
- 新地区先使用对应官方 horse/profile/performance 页面；官方页面不含完整字段时，补充来源必须保留
  provider-bound identity，并经过逐字段 authority review。
- 禁止 Wikipedia/Wikidata、无来源自动音译、只按模糊马名合并、把赛事国家直接当出生国。

## 身份规则

1. 同 provider horse ID 是首选稳定身份；同名但 provider ID 不同必须保持独立。
2. 没有 provider ID 时，只有原名、父、母、完整出生日期四字段一致才允许自动绑定。
3. 只有马名时仅生成 review candidate；不得创建或更新生产 HorseProfile。
4. 生产已有档案匹配顺序：provider identity → 完整四字段身份 → 唯一受控 alias 加出生事实。
5. 多个生产候选保持 `ambiguous`，由 reviewed mapping 决定；不自动选择第一个。
6. 新建档案必须使用确定性 identity key，并在同一 artifact 重放时幂等。

## 名称规则

- 正式赛果行的纯拉丁 `horse_display_name` 是该 occurrence 的英文名证据；不要求先找到公开 profile。
- 中文名尽量复用生产受控 TermEntry/HKJC/JRA 等现有证据；缺失时允许档案保持待译，禁止自动音译。
- 日文名只接受明确日文来源或已审核 alias；缺失时允许进入复核队列。
- 日本和香港英文名允许为空；其余六地区导入生产前英文名必须存在。

## 完整资料和主胜鞍

- 基础资料必填：国家、性别、毛色、出生日期、马主、练马师、生产者。
- 二代血统必填：父、母、父父、父母、母父、母母。
- 完整生涯必须有来源声明的总出赛数，且导入后实际起跑履历数与之对齐；差异保持 blocked。
- 主胜鞍由 `HorseRaceRecord` 中 `result_status=won` 且规范等级为 G1/G2/G3 的履历确定性计算；来源
  自带的 major wins 文本只可作为对账证据，不直接写入计算结果。

## Artifact 与导入门禁

补全 artifact 必须绑定：2025 研究 artifact digest、collector/tool SHA、provider policy SHA、全部
source cache SHA、production identity census SHA、mapping review SHA 和生成时间。

导入分三层：

1. `prepare`：只读生成候选、预计 create/update/record/alias 数和 blocker。
2. `dry-run`：在当前生产快照上验证身份、完整度、幂等、主胜鞍和 verifier 预期；零业务写入。
3. `apply`：只接受精确 reviewed manifest/SHA，在写前备份和 maintenance 内单事务执行。

apply 后 verifier 必须证明：scope 守恒、无未审核新身份、无同 provider 重复、完整履历计数一致、
主胜鞍重算一致、artifact 重放零写、未自动公开、服务健康。

## 人工门禁

- 当前 G1 已通过：补全八地区、允许权威来源、禁止 Wikipedia、通过后导入生产。
- commit/push/Draft PR 属于已确认范围内机械步骤。
- 合并/部署在完整测试和独立 review 后触发 G2。
- 正式扩大外部网络全量采集和批量生产写入分别按根 `AGENTS.md` 触发精确 G3；若 G2 发布包已明确
  包含同一动作，则不重复询问。

## 验收标准

- 八地区赛事覆盖不再是 `classification_incomplete`；任何官方结果缺口逐项列出，不伪造 complete。
- 六个强制英文地区 `required_english_missing=0`。
- 每个可导入 HorseProfile 均达到基础资料、二代血统、完整生涯门禁；其余保持 blocker，不部分冒充
  完整。
- 生产 dry-run 对全部候选给出唯一 disposition；ambiguous/unreviewed 为零才可申请 apply。
- apply/verifier 后线上 scope 与 reviewed artifact 精确一致，错误数据被修正且没有额外公开行为。
