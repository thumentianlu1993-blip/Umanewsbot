# 四地区分级赛目标 census（2026-08-29）

> 本文件保留 parser 修复前的初始 census 作为审计基线，不是当前 denominator。当前重编译结果为
> `12,047 / 26 conflicts / 9 scope blockers`，跨年份 series 消歧后的 ledger SHA 为
> `f04a7d5886c91de9c300598cd9d752b48960342ca6d334bdb75c2e3edef69481`；见
> `research/target_ledger_conflict_diagnosis_20260829.md`。

## 结论

对生产冻结的 TJCIS 2000–2026 PDF 逐文件核验 SHA/size/source URL 后，当前 parser 生成
`12,039` 个范围内目录目标：英国 `3,188`、爱尔兰 `1,957`、法国 `1,890`、美国 `5,004`。
target-ledger SHA-256 为
`bc6f0d52441e505dc0a55d6fb41e3ba771cc2ee8b0176244ee2db8edd598066c`。

这不是最终 denominator。共有 `30` 个 region/year/discipline 的 parsed count 与 Blue Book
declared count 不一致；冲突 canonical payload SHA-256 为
`8ae8da8bc282c892d90b9f03c725ed2b3c6101b32efd534437ffb5f4b87b10f3`。其中 `12` 个会改变本次
范围内数量，当前净少解析 `10` 个目标。产物必须标记 `needs_source_conflict_review/PREPARED`，
不得发布 `COMPLETE`。

## 范围统计

| 维度 | 数量 |
| --- | ---: |
| 2000–2020 G1 | 5,312 |
| 2021–2026 G1/G2/G3 | 6,727 |
| 平地 | 8,352 |
| 跳栏 | 3,687 |
| G1 | 6,907 |
| G2 | 2,014 |
| G3 | 3,118 |
| 总计 | 12,039 |

TJCIS 目录没有逐场日期，因此首版 ledger 的 `due_state` 均为 `date_unknown`。后续必须用赛事日期/
正式赛果把当前年度未来赛事分为 `not_due`，不能把目录出现等同于已经举行。

## 逐年数量

| 年份 | 数量 | 年份 | 数量 | 年份 | 数量 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 2000 | 222 | 2009 | 263 | 2018 | 271 |
| 2001 | 224 | 2010 | 260 | 2019 | 270 |
| 2002 | 225 | 2011 | 259 | 2020 | 269 |
| 2003 | 231 | 2012 | 260 | 2021 | 1,133 |
| 2004 | 238 | 2013 | 264 | 2022 | 1,137 |
| 2005 | 237 | 2014 | 265 | 2023 | 1,132 |
| 2006 | 242 | 2015 | 271 | 2024 | 1,123 |
| 2007 | 246 | 2016 | 270 | 2025 | 1,105 |
| 2008 | 255 | 2017 | 270 | 2026 | 1,097 |

## 会改变本次 scope 数量的 12 个冲突

`scope_delta = parsed - declared`；2000–2020 只比较 G1，2021–2026 比较全部 G1/G2/G3。

| 年份 | 地区 | discipline | scope delta | parsed/declared total | parsed/declared G1 |
| ---: | --- | --- | ---: | ---: | ---: |
| 2000 | 法国 | flat | -1 | 106/107 | 25/26 |
| 2000 | 美国 | flat | -2 | 474/478 | 96/98 |
| 2001 | 法国 | flat | -1 | 106/107 | 25/26 |
| 2002 | 英国 | flat | -1 | 112/112 | 27/28 |
| 2003 | 英国 | flat | -1 | 123/123 | 28/29 |
| 2008 | 美国 | flat | +1 | 475/475 | 111/110 |
| 2012 | 美国 | flat | -1 | 464/464 | 111/112 |
| 2023 | 美国 | flat | -1 | 438/439 | 97/97 |
| 2025 | 法国 | flat | -2 | 114/116 | 28/27 |
| 2025 | 美国 | flat | -1 | 410/411 | 93/93 |
| 2026 | 法国 | flat | +1 | 114/113 | 28/28 |
| 2026 | 美国 | flat | -1 | 406/407 | 92/92 |

另外 `18` 个冲突在当前两段 scope 规则下不改变总目标数，但会改变 grade 分配或完整目录计数，仍需
保留在 review payload 中，不可静默忽略。

## 与生产当前账本对比

生产只读基线（held、非 superseded、同年份/等级过滤）为英国 `3,169`、法国 `1,890`、美国
`5,004`，合计 `10,063`，当前没有 Ireland region。新 draft 中法国和美国总数与生产一致；英国
为 `3,188`，多 `19`；新增爱尔兰 `1,957`。英国差额必须逐 target reconciliation，不能直接把
`12,039 - 10,063` 全部视为爱尔兰新增量。

## 下一步

1. 对 12 个 scope-impacting 冲突逐场找出 missing/extra/grade-shift，优先使用当年 Blue Book
   显式行和 BHA/HRI/France Galop/TOBA 官方或受审目录。
2. 对剩余 18 个冲突形成保留/修正结论，并把 review 文件和完整冲突 payload SHA 绑定。
3. 只有修正后 parser declared count 全绿，或 reviewed approval 的 keys 与完整 payload SHA 精确一致，
   才允许目标 artifact 写 `COMPLETE`。
4. 将 `12,039` draft 与生产现有 `10,063` 逐一做 series/year/discipline 对账，再生成新增/既有/
   ambiguous 清单。
