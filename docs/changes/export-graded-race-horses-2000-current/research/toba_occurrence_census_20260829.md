# TOBA 2000–2024 actual-held occurrence census

诊断日期：`2026-08-29`

## 结论

TOBA official history 一次解析得到 `11,223` 个美国分级赛历史行。按本 change 范围过滤后：

- `2000–2020` 仅 G1，`2021–2024` G1/G2/G3；
- 实际举行 occurrence 共 `3,941`；
- 在未应用 9 项 source-conflict review、也未增加 occurrence alias review 的 v2 target draft 上，
  自动唯一绑定 `3,728` 行；
- 已确认同一 series/year 多次举行产生至少 `4` 个额外 occurrence，不能被 series target 去重；
- 剩余问题为 source-side unmatched `204`、target-side match missing `232`、grade conflict `12`、
  source identity reused `16`、match not unique `1`。这些类别有重叠，不能直接相加推导缺失场数。

这不是失败的 API 导出结果，而是网络导出前的安全 reconciliation。未匹配行保留官方日期、马场、
等级、冠军和 field size；在 alias/grade review 关闭前不生成付费任务。

## 逐年结果

| 年份 | TOBA scope held | 自动绑定 occurrence | blockers |
|---:|---:|---:|---|
| 2000 | 96 | 92 | target missing 4; source unmatched 4 |
| 2001 | 98 | 94 | target missing 5; source reused 2; source unmatched 3 |
| 2002 | 100 | 96 | target missing 4; source unmatched 4 |
| 2003 | 101 | 97 | target missing 4; source unmatched 4 |
| 2004 | 100 | 96 | target missing 4; source unmatched 4 |
| 2005 | 96 | 90 | target missing 8; source reused 2; source unmatched 5 |
| 2006 | 104 | 97 | target missing 7; source unmatched 7 |
| 2007 | 106 | 93 | target missing 13; source unmatched 13 |
| 2008 | 109 | 103 | target missing 8; source unmatched 6 |
| 2009 | 113 | 109 | target missing 6; source unmatched 4 |
| 2010 | 112 | 102 | target missing 11; source unmatched 10 |
| 2011 | 112 | 101 | target missing 11; source unmatched 11 |
| 2012 | 112 | 98 | target missing 14; source unmatched 14 |
| 2013 | 111 | 104 | target missing 7; source unmatched 7 |
| 2014 | 110 | 97 | target missing 11; source reused 2; source unmatched 12 |
| 2015 | 110 | 102 | target missing 8; source unmatched 8 |
| 2016 | 109 | 102 | target missing 7; source unmatched 7 |
| 2017 | 107 | 101 | target missing 6; source unmatched 6 |
| 2018 | 106 | 101 | target missing 5; source unmatched 5 |
| 2019 | 103 | 96 | target missing 5; source reused 2; source unmatched 6 |
| 2020 | 93 | 85 | target missing 13; source reused 2; source unmatched 7 |
| 2021 | 434 | 411 | target missing 32; source reused 2; source unmatched 22 |
| 2022 | 446 | 430 | grade 1; target missing 18; source reused 4; source unmatched 13 |
| 2023 | 429 | 418 | grade 3; target missing 16; not unique 1; source unmatched 11 |
| 2024 | 424 | 413 | grade 8; target missing 5; source unmatched 11 |

## 解释与下一门禁

1. `target missing` 不等于实际漏赛：其中包含 TJCIS 计划赛事未举行、赛事更名/赞助名和 source grade
   与 target grade 冲突；必须逐项分类。
2. `source unmatched` 是官方 held occurrence 没有唯一 target，必须优先关闭；不能只看 target-side
   输出率。
3. `source reused` 表示同一官方 result identity 同时被两个目录目标吸收，通常是别名重复或短名称误吸收，
   必须删除重复 target 或人工选择，不能复制同一场。
4. `grade conflict` 使用当届 TOBA grade 与 TJCIS 行逐项对照；2022 Bed o' Roses 已在 9 项 source
   review 中有明确修正，其余仍需 occurrence review。
5. 2000–2009 TOBA 行通常没有 Equibase result URL，但有冠军 anchor；这部分应在 target binding 完成后
   生成 targeted-horse seeds。2010+ 有 direct result URL 时优先走直接 result，再对 provider gap 使用
   targeted fallback。

当前 evidence cache：`/tmp/umanews-toba-history.html`，SHA-256
`553f1dd210ff88d4f83837e8c6454e47d90492f3370edd2c4f0958d53fffe166`，size `12,835,556`，
source URL `https://toba.org/graded-stakes/history/`。`/tmp` 只用于本轮诊断；正式审批/执行前必须复制到
不可变 artifact 根并由 manifest 重新验证，不能在 review JSON 中引用临时路径。
