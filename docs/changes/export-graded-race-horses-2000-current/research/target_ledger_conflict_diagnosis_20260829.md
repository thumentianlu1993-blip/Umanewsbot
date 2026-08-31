# 四地区分级赛目标账本冲突诊断

诊断日期：`2026-08-29`

## 结论

- 原始离线账本：`12,039` targets，SHA-256
  `bc6f0d52441e505dc0a55d6fb41e3ba771cc2ee8b0176244ee2db8edd598066c`，
  `30` 个 declared/parsed conflicts，状态 `PREPARED`。
- 修复确定解析缺陷后的 v2：`12,047` targets，SHA-256
  `5deddaa8efc0835ae20fad04a93053b8786efb3b88af85a95ef03bb321d15c92`。
- 随后发现构建器未在全部年份汇总后运行既有全局 series 消歧；修复并在 `--network none` 下重建后仍为
  `12,047` targets，新 SHA-256 为
  `f04a7d5886c91de9c300598cd9d752b48960342ca6d334bdb75c2e3edef69481`。两版事实行零增删，仅
  226 个 series/target key 规范化；`26` 个 conflicts 和 9 个范围 blocker payload 均未变化，仍为
  `PREPARED`。
- 按本次范围过滤后，真正可能改变目标集合的冲突为 `9` 个；其他冲突只涉及
  `2000-2020` 被排除的 G2/G3，不应静默删除，但不应被误报为本次 G1 集合缺口。
- TJCIS 明细表不提供当地日期，因此新账本全部 `date_unknown`。它是等级 inventory，
  不是可直接执行 `/v1/results` 的日期计划。
- 本轮官方来源复核已经给出 9 个阻塞项的逐项建议，但尚未产生由独立审核人签名的
  `status=approved` review。当前账本因此仍必须保持 `PREPARED`，不能把研究者自己的结论
  伪装成独立审批。

## 已确认并修复的解析缺陷

1. 年龄和性别无空格：`3yof`、`3upf` 等此前不能满足 row-complete，导致 Alabama S.、
   Noblesse S. 等显式赛事行被遗漏。
2. 更名跨行：`Golden Jubilee S. G1 (formerly` 下一行包含旧名 `Cork & Orrery S. G2)`，
   此前会丢弃现名 G1 并错误保留旧名 G2。
3. 美国 2025 Matron S. 的年龄数字 OCR 丢失为 `yo f`，但同一行仍有 grade、距离、
   surface 和赛事名；补入 flat row-completeness fallback 后恢复该场 G3。
4. 加入对应回归测试后，TJCIS parser suite `66/66` 通过。

## 剩余会影响本次范围的 9 个冲突

| 年份 | 地区 | 明细 G1/G2/G3 | 摘要 G1/G2/G3 | 影响 |
|---:|---|---:|---:|---|
| 2000 | France | 25/26/55 | 26/26/55 | G1 缺 1 |
| 2000 | USA | 96/154/224 | 98/155/225 | G1 缺 2 |
| 2001 | France | 25/27/54 | 26/27/54 | G1 缺 1 |
| 2008 | USA | 111/153/211 | 110/153/212 | G1/G3 分类相差 1 |
| 2022 | USA | 101/134/215 | 101/135/214 | G2/G3 分类相差 1 |
| 2023 | USA | 97/135/206 | 97/135/207 | G3 缺 1 |
| 2025 | France | 28/23/63 | 27/25/64 | 总数少 2 且等级分布不一致 |
| 2026 | France | 28/24/62 | 28/24/61 | G3 多 1 |
| 2026 | USA | 92/134/180 | 92/134/181 | G3 缺 1 |

## 官方证据复核结果

本次用户范围是“实际举行赛事的实际起跑马”，不是年初计划表中的所有预定赛事。美国 TOBA
历史表直接给出已经举行的 occurrence（日期、等级、马场、冠军和 Equibase result link），
因此美国冲突以 held occurrence 为最终口径；年度计划、取消或 `not_run` 只用于解释差异。

| conflict key | 建议 disposition | 逐项结论 | 目标目录变化 |
|---|---|---|---:|
| `2000:france:flat` | `apply_evidenced_mutations` | France Galop 历史页确认 Prix de l'Abbaye 为 G1；Namid 为 2000 年冠军。补入 2000 Abbaye G1。 | +1 |
| `2000:united_states:flat` | `accept_parsed_held_scope` | TOBA 历史表实际举行 G1 为 96 场；Blue Book 摘要 98 是计划/声明口径，不能补造两场未举行赛事。 | 0 |
| `2001:france:flat` | `apply_evidenced_mutations` | France Galop 历史页确认 Imperial Beauty 为 2001 Abbaye G1 冠军。补入 2001 Abbaye G1。 | +1 |
| `2008:united_states:flat` | `apply_evidenced_mutations` | `CashCall Futurity` 与 `Hollywood Futurity` 是同一届的现名/旧名重复，删除后者；Laurel 官方媒体指南确认 Frank J. De Francis Memorial Dash 2008 未举行，occurrence 阶段标记 `not_run`，不能取 starters。 | -1 |
| `2022:united_states:flat` | `apply_evidenced_mutations` | TOBA 2022 表将 Bed o' Roses 列为 G2；把 TJCIS 的 G3 改为 G2。 | 0 |
| `2023:united_states:flat` | `apply_evidenced_mutations` | TOBA 2023 表确认 National Thoroughbred League Dueling Grounds Derby 于 2023-09-03 举行且为 G3，补入该 occurrence 对应的目录目标。 | +1 |
| `2025:france:flat` | `accept_parsed_held_scope` | France Galop 2025 programme 明细为 28/23/63，共 114 场，与 parser 明细完全一致；TJCIS 摘要 27/25/64 不能覆盖官方明细。 | 0 |
| `2026:france:flat` | `apply_evidenced_mutations` | France Galop 2026 programme 为 28/24/61，未列 Penelope；删除 TJCIS 中该 G3 行。 | -1 |
| `2026:united_states:flat` | `accept_parsed_held_scope` | TOBA 当前表多出的 `Cougar II`、`Californian` 明确为 `not_run`；当前年度只纳入截至运行日已举行 occurrence，不为未举行行生成 starters 任务。 | 0 |

若以上建议获得独立审核批准，目录账本预计由 `12,047` 变为 `12,048`：新增两届 Abbaye 与
2023 Dueling Grounds Derby，删除 Hollywood Futurity 重复别名与 2026 Penelope，Bed o' Roses
只变更等级、不改变行数。这个 `12,048` 仍是 series/year inventory，不是 held occurrence 的最终
场次数；取消、未举行和同一系列一年举行两次必须在 occurrence ledger 中另行展开。

## 冻结证据身份

| 证据 | SHA-256 | size | 官方 URL |
|---|---|---:|---|
| TOBA 2000–2024 history | `553f1dd210ff88d4f83837e8c6454e47d90492f3370edd2c4f0958d53fffe166` | 12,835,556 | `https://toba.org/graded-stakes/history/` |
| TOBA 2022 annual | `0a051e6e6a6cd6a3fba202a83f5b7be6317947b5504868c9676d9d592e21812e` | 2,033,244 | `https://toba.org/graded-stakes/2022-races/` |
| TOBA 2023 annual | `779b7c9249b383db34a6fb2f9378179772fd1b52cbe71e74611da5e7063b70e1` | 2,030,405 | `https://toba.org/graded-stakes/2023-races/` |
| TOBA 2026 annual | `2c8093dd59aa5929ae0fa3ab51d1d028d5bd249b77f4a067cce07d5ae193c636` | 1,966,284 | `https://toba.org/graded-stakes/2026-races/` |
| TOBA 2008 announcement | `2b2becdb66a40dae38c2111827232b39f89281402bad21aab915629081ae7611` | 114,735 | `https://toba.org/wp-content/uploads/2016/04/American-Graded-Stakes-Committee-Announces-2008-Graded-Stakes-Races-11.28.07.pdf` |
| Laurel 2023 media guide | `cbf23888665e7ad2b7ae67f26586422c33be92bc9a92fda096ce5c49ea6820f7` | 5,725,241 | `https://www.laurelpark.com/wp-content/uploads/2023/03/2023-MJC-MEDIA-GUIDE-FINAL_R2.pdf` |
| France Galop 2025 programme | `9fe2493b501a9f48391a06d753d3055667143b4cb8a94f1a6bc9cb92faeaca9e` | 9,173,555 | `https://www.france-galop.com/sites/default/files/2025-02/groupeslisted_plat_2025.pdf` |
| France Galop 2026 programme | `7eabb26587d53e2b574e05c486c353e6bda6fdff7ce13261c293a713ff418c74` | 3,690,478 | `https://www.france-galop.com/sites/default/files/2026-02/groupes_listed_plat_2026_v7.pdf` |
| France Galop Abbaye history | `5aa18e6b72615179d50e83cb97ceeee3560b35f76c529f81e8ac96c4f01f4a09` | 46,439 | `https://www.france-galop.com/en/content/prix-de-labbaye-de-longchamp-history-final-sprint` |
| France Galop Namid page | `d73973c880b3c87632c86c01f8b1b9217f7473927a6839aa4914b280558517e5` | 70,466 | `https://www.france-galop.com/fr/content/les-gagnants-de-maiden-daout-2020` |

当前 9 项 canonical blocker payload SHA-256 为
`dedf39dff4fb4a342dd3737fa7d096e7c9d641598dd5847ec7f5558e9495d9d1`。审批工件必须逐字绑定
这 9 个 conflict key、上述实际使用证据的 SHA/size/URL、审核人和带时区审核时间；任一源文件或
parser 输出漂移都使审批失效。

## occurrence 主键修正

TOBA 2022 历史结果中，同一系列可能在一个自然年出现两个 held occurrence（例如 Joe Hernandez、
Robert J. Frankel、Las Flores）。因此：

- `target_key=region:year:series_key:discipline` 只定义分级范围，允许一对多关联 occurrence；
- occurrence 强身份至少绑定 `region + local_date + authority/result identity`，并保留马场、赛事名、
  当届等级和 source payload SHA；
- 同名同年不得去重；只有相同官方 result identity 或经审核确认的同场别名才能合并；
- `scheduled/not_run/not_due` 不生成 participant 分母；只有 `held` 且正式赛果存在才进入 starters。

## 审核规则

- 首先逐页证明显式 G1/G2/G3 行与 parser output 守恒；发现格式/OCR 缺陷先修 parser，
  不使用审批绕过代码错误。
- 再用 BHA/HRI/France Galop/TOBA 年度分类表核对赛事名称与当年等级。
- 年鉴摘要只能触发冲突，不能凭一个数字生成没有名称、马场和来源行的赛事。
- 任何接受“明细优先”或地区修正的决定都必须绑定：PDF SHA、conflict payload SHA、
  review 文件 SHA、reviewer、时间和逐项 disposition。
- `COMPLETE` ledger 必须让 bulk runner 能验证审批工件；未审状态保持 `PREPARED`，
  禁止付费批量调用。
- 独立审批只发布 series/year inventory；实际导出还必须经过 occurrence ledger 的 held/status/result
  守恒，不能拿 `12,048` 直接当作 API 日期任务数。
