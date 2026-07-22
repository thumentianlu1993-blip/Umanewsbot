# spec：2026 赛历赛事中文展示名补齐（translate-2026-race-display-names）

## 背景

2026-07-22 生产核验：已发布赛事 9,820 场中 573 场（全部 year=2026）的 `chinese_name`
仍是原文回退值，赛历主显示字段直接展示英文/日文假名。分地区：美国 242、英国 171、
法国 152、日本 8；香港 0。历史年份（1984–2025）已由 `import-reviewed-race-name-translations`
全覆盖。

## 范围

- 仅 573 场 `visibility_status=published`、`year=2026`、`chinese_name` 非空但不含 CJK 的
  `RaceEvent`，写入字段只有 `RaceEvent.chinese_name`（及 `updated_at`）。
- 候选生成四级来源，逐级命中即停：
  0. **系列中文名继承**：所属 `race_series.chinese_name` 已含 CJK（当前盘点 2 场）→ 候选取系列中文名，来源标 `series`（仍需用户审核）；
  1. **术语库复用**：`TermEntry(term_type=race, is_active)` 已有中文译名且原文规范化匹配（当前盘点 67 场）；
  2. **历史译名复用**：已发布历史赛事（1984–2025 全部已翻译年份，风格同一批次统一）同原文/同基名（去冠名后）的中文名（当前盘点 131 场 + 去冠名后可再命中若干）；
  3. **新翻译候选**：剩余场按已上线风格生成新候选，全部进人工审核工作簿（当前盘点约 375 场，去冠名复用后会更少）。
- 候选采用条件（L1）：术语 `translation_status=translated` 且 `target_zh` 非空；匹配键为 `source_ja` 与 `aliases_ja` 的规范化集合；同键多译名歧义转人工。
- `manual_lock_flags.chinese_name` 锁定的赛事不进写入集：导出即转入人工桶，commit 遇锁定整批拒绝（沿用去让赛先例语义）。
- 引用说明：`import-reviewed-race-name-translations` 的工具链与部分文档位于分支 `codex/translate-collected-race-horse-names`（未合入 main），其生产写入已完成；本 change 只复用其结论数据（历史译名），不依赖其工具。
- 沿用已锁定风格规则：
  - **冠名一律不进中文名**（前缀 `Betfair/William Hill/Unibet/Virgin Bet/BetMGM/Coral/Sky Bet/JCB/Trustatrader/Dornan Engineering` 等、括号 `[Sponsor]`、后缀 `Presented by …` 均剥离），先例：`Cleeve Hurdle[McCoy Contractors]`→「克利夫跨栏锦标」、`…Presented by SirDavis…`→「飞马世界杯雌马草地锦标」。
  - 四种让赛标记（让赛/讓賽/让步赛/讓步賽）不进中文名（与 2026-07-22 去让赛规则一致）；原文未括号 handicap 的对象转人工。
  - 级别/条件后缀（G1/G2/G3、2yo、fillies 等）按历史同地区先例处理；人名、马场名遵循术语库与历史既有译法，不新造译名体系。
- 日本 8 场假名名按日本地区既有译法翻译。

## 非目标

- 不修改 `RaceSeries`（2026 日历系列与历史系列双卡片问题另案处理，系列中文化随该案）。
- 不新增/修改术语库，不回填历史文章，不改 `original_name`、别名、公开状态、优先级。
- 不处理未来新增赛事的自动翻译（本 change 是一次性批次；新增赛事原文回退问题记录为后续建议）。
- 不做系列合并/去重。

## 用户行为与验收标准

1. 产出审核工作簿（CSV）：573 行，每场含 region、original_name、当前展示名、来源级别（series/term/history/new(=needs_translation)/manual）、匹配依据（命中源原文）、建议中文名；用户可逐行修改/否决。**否决契约：否决一行 = 清空该行 `final_name`（或填回 before 原值）；`decision` 列仅供参考，若填了否决类值（veto/否决/保持原值等）则 `final_name` 必须为空，否则 manifest 构建拒绝该行集。**
2. 用户审核通过后，从**审核定稿文件**生成 manifest（SHA-256 锁定），生产只读导出 before 值比对零漂移后才允许写入。
3. 写入：custom-format 备份（`pg_restore -l` 校验）→ 单事务 + 逐对象 before CAS + OperationLog 审计（artifact/备份/授权身份）→ 写后 `--verify`：写入值等于审核值、未命中对象零改动、无让赛标记/冠名残留（按规则；例外：原文含未括号让赛指标时让赛为赛事名组成部分，三层一致放行，先例见 test_cases 17）。
4. 前台抽检：以 DB 级 verify 为主（573 行写入值 == 审核值、kept/veto 未动），前台为辅——在命中目标赛事的视图/筛选（region/year/q）下无原文回退展示，跨地区详情页抽查 ≥5 场。
5. 全部 573 场要么写入审核通过的中文名，要么被用户显式否决保持原值（否决行列入报告）。

## 失败边界

- 候选生成阶段任何匹配歧义（同一基名对应多个不同中文名）→ 该行转人工，不自动取舍。
- 冠名剥离规则不得误伤本名（如 `Jane Seymour Nov. Hurdle` 的 Jane Seymour 是人名非冠名；无把握的剥离一律不剥，转人工）。
- 审核定稿与生产 before 漂移 → 整批回滚不写。
