# test_cases：2026 赛历赛事中文展示名补齐

## 正常用例

1. L1 术语命中：原文规范化 == 术语 source_ja（大小写/标点差异）→ 采用 target_zh，来源标 `term`。
2. L2 历史命中（全名）：2026 原文 == 历史赛事原文 → 采用历史中文名，来源标 `history`。
3. L2 历史命中（去冠名）：`Betfair Cleeve Hurdle` → 基名 `Cleeve Hurdle` → 「克利夫跨栏锦标」；`... Presented by SirDavis ... [TAA]` 尾缀剥离后命中。
4. 尾缀括号剥离：`Cleeve Hurdle[McCoy Contractors]` → `Cleeve Hurdle`。
5. L3 新翻译：无命中时按风格生成候选并标 `new`，附建议理由；review.csv 573 行 = series+L1+L2+L3+manual 之和。
6. 日本假名名（如 `ブルーバードカップ`）走 L3/术语库，产出中文候选。

## 边界用例

7. 前缀名单外不剥：`Jane Seymour Nov. Hurdle` 前缀不在冠名名单 → 不剥，整名进入 L3/人工。
8. 剥离后为空/等于原名 → 视为未剥离，不命中 L2 基名路径。
9. 同一规范化键对应多个不同历史中文名 → `manual`，不自动取舍。
10. 术语库同键多译名 → `manual`。
11. 原文含未括号 handicap（如 `2yo Handicap` 型）→ `manual`（沿用去让赛守卫语义）。
12. 原文括号让赛标记（`(H)`/`(Handicap)`）→ 候选不含让赛字样，可正常命中/生成。
13. 系列已有中文名的 2 场（First Lady/Matron）：候选取系列中文名，来源标 `series`，仍需用户审核；系列名若含让赛标记/冠名守卫命中则转人工。
13b. L1 别名命中：原文规范化命中术语 `aliases_ja` 某别名 → 采用该术语 target_zh；`translation_status!=translated` 或 `target_zh` 为空的术语不参与 L1。
13c. `manual_lock_flags.chinese_name` 锁定的赛事：导出即转 manual 桶；commit 遇锁定或 flags 快照漂移整批回滚（与去让赛先例语义一致）。

## 失败/回归用例

14. manifest 与审核定稿 SHA 不一致 → 拒绝执行。
15. commit 时任一 before 漂移 → 整批回滚，OperationLog 零写入。
16. 重复 commit 同批 → 幂等拒绝。
17. 写入值含四种让赛标记 → 生成期即拦截（该行进 manual）；verify 复验零残留。**例外**：原文含未括号让赛指标（\bhandicap\b、H'Cap、边界裸 H、中文标记）时让赛为赛事名组成部分，build/commit/verify 三层一致放行（先例：id 666「新手让赛跨栏锦标」、两岁马让赛 kept）。
18. 非目标对象（历史赛事、未发布赛事、系列、术语）在 commit/verify 中零触碰（verify 抽样比对 kept 集）。
18b. 写入路径只允许 `bulk_update([chinese_name, updated_at])`：断言 commit 不触发 `RaceEvent.save()` 的 `slug/series_key` 附加写（通过 captured update_fields 或查询日志验证）。
19. review.csv 与 artifact 互相可复现（同一生成器产出，SHA 记录）。

## 集成/运行态

20. SQLite 与 PostgreSQL 16 双跑服务层单测（沿用去让赛测试基线方式）。
21. 生产只读导出 → 本地分桶：573 = 导出数 = review.csv 行数；before 与生产逐行一致。
22. --commit 后 --verify：written == 审核通过数；veto 行保持原值。
23. 前台：以 DB 级 verify 为主；在命中目标赛事的视图/筛选（region/year/q）下无原文回退，跨地区详情页抽查 ≥5 场 200 且显示中文名。

## RED/GREEN 证据位置

- RED：先写服务层单测（匹配/剥离/歧义/守卫/CAS/幂等），未实现时全部失败；记录于 tasks.md 执行记录。
- GREEN：实现后同一批通过；完整 stable 回归 exit 0。
