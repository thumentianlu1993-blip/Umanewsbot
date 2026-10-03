# U01 只读候选清单合成示例

本示例仅消费33个合成案例，不代表生产存量；无实际 event_id/slug，不能用于 apply。

实现SHA：`3ac1e3a750e68bafe7950fa726481a02ecccfad6`。输入SHA256：`55614d310190f6030643604dddaa7ea54da381ce021625751a464d784adfe8be`。生成过程禁止数据库查询，业务数据库写入为0。

候选值只在可信代码非空且与已有规范值不同时建议；冲突/未知仅列人工核验线索。正式存量清单还需固定快照SHA、真实event_id/year/slug和脱敏来源引用，遵循U01-plan合同。

| 合成ID | 原文 | 原规范值 | 可信代码 | 状态/原因 | 候选规范值 |
|---|---|---|---|---|---|
| g1_raw_only | G1 |  | G1 | normalized/normalized | G1 |
| group_roman_1 | Group I |  | G1 | normalized/normalized | G1 |
| fullwidth_1 | Ｇ1 |  | G1 | normalized/normalized | G1 |
| jpn_1 | JpnⅠ | JPN1 | JPN1 | normalized/normalized |  |
| jg_1 | J・GⅠ |  | JG1 | normalized/normalized | JG1 |
| g2_raw_only | G2 |  | G2 | normalized/normalized | G2 |
| group_roman_2 | Group II |  | G2 | normalized/normalized | G2 |
| fullwidth_2 | Ｇ2 |  | G2 | normalized/normalized | G2 |
| jpn_2 | JpnⅡ | JPN2 | JPN2 | normalized/normalized |  |
| jg_2 | J・GⅡ |  | JG2 | normalized/normalized | JG2 |
| g3_raw_only | G3 |  | G3 | normalized/normalized | G3 |
| group_roman_3 | Group III |  | G3 | normalized/normalized | G3 |
| fullwidth_3 | Ｇ3 |  | G3 | normalized/normalized | G3 |
| jpn_3 | JpnⅢ | JPN3 | JPN3 | normalized/normalized |  |
| jg_3 | J・GⅢ |  | JG3 | normalized/normalized | JG3 |
| canonical_only |  | G1 | G1 | normalized/normalized |  |
| case_space |   gRaDe 1   |  | G1 | normalized/normalized | G1 |
| hk_international | G1 | G1 | G1 | normalized/normalized |  |
| conflict | G2 | G1 |  | conflict/grade_conflict |  |
| empty |  |  |  | missing/missing |  |
| ambiguous | G1 G2 |  |  | unknown/unverified_grade |  |
| out_of_range | G10 |  |  | unknown/unverified_grade |  |
| suffix_unverified | G1 Handicap |  |  | unknown/unverified_grade |  |
| local_hk | 香港一级赛 |  |  | unknown/unverified_grade |  |
| local_hkg | HKG1 |  |  | unknown/local_grade_requires_profile |  |
| local_english | Local G1 |  |  | unknown/unverified_grade |  |
| bad_stored |  | OTHER |  | unknown/unverified_grade |  |
| listed | Listed |  | L | normalized/normalized | L |
| open | Open |  | OP | normalized/normalized | OP |
| race_class | 1勝クラス |  |  | preserved/race_class_not_grade |  |
| verified_jra_suffix | GⅢ 京成杯オータムH |  | G3 | normalized/normalized | G3 |
| jra_suffix_no_source | GⅢ 京成杯オータムH |  |  | unknown/unverified_grade |  |
| jra_suffix_wrong_name | GⅢ 京成杯オータムH |  |  | unknown/unverified_grade |  |
