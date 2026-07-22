# design：2026 赛历赛事中文展示名补齐

## 现状

- `RaceEvent.chinese_name` 是赛历与详情页主显示字段（`race_calendar.html:56`）；空或非 CJK 时用户看到原文。
- 573 场目标赛事中 563 场所属 2026 日历系列的 `chinese_name` 同为原文回退（系列是 2026 赛历独立建卡，与已翻译历史系列双卡片并存），8 场系列为空，2 场系列已有中文名。
- 既有可复用资产：
  - 术语库 race 术语（含译名）——覆盖经典赛名；
  - 已上线历史译名（1984–2025 全部非 2026 已发布赛事 `chinese_name`）——同一批赛事的历年译名，风格权威；
  - 已锁定风格先例：冠名剥离、让赛标记剥离、「X锦标/X杯」译法、地区括注（如「First Lady锦标（Keeneland）」）。
- 去让赛 change（`5b491561`）已建立可复用的受控写入骨架：dry-run artifact → 用户审核 → 备份 → 单事务 CAS 写入 → verify → OperationLog。本 change 复用同一模式，不复用其代码（规则不同）。

## 架构与数据流

```text
生产只读导出 573 场目标行（id/original_name/chinese_name/region/series 信息）
  + 术语库 race 术语、历史已发布赛事译名（只读导出）
  -> 本地候选生成器（新管理命令，默认 dry-run）
       L0 系列继承 -> L1 术语库规范化匹配 -> L2 历史译名匹配（原名 -> 去冠名基名）-> L3 新翻译候选
  -> review.csv（573 行，含来源级别与匹配依据）
  -> 用户审核定稿（可改可否决）
  -> manifest 生成器：从定稿文件构建 artifact（before=生产导出值，SHA-256 锁定）
  -> 生产备份（custom-format + pg_restore -l）
  -> --commit：artifact SHA + 备份身份 + 授权信息；单事务、before CAS、幂等 OperationLog
  -> --verify：写入值 == 审核值；kept/veto 未动；无让赛标记残留
  -> 前台抽检
```

## 匹配规则（候选生成器）

1. **规范化**：原文与候选键统一 lowercase、去标点/空白（`[^a-z0-9]` 去除）后比较。
2. **冠名剥离（保守）**：
   - 尾缀 `[...]` 括号段、`Presented by ...`/`presented by ...` 起至结尾一律可剥；
   - 前缀冠名只剥**显式名单**（Betfair、William Hill、Unibet、Virgin Bet、BetMGM/Betmgm、Coral、Sky Bet、JCB、Trustatrader、Dornan Engineering、AIS、SBK 等，名单来自 573 场实际盘点并随 artifact 公示）；名单外前缀一律不剥，转人工；
   - 剥离结果为空或与原名相同 → 视为未剥离。
3. **L0 系列继承**：`race_series.chinese_name` 含 CJK → 候选取该值（来源 `series`）；同样需过让赛/冠名守卫（守卫命中转人工），且必须经用户审核。
4. **L1 术语库**：匹配键 = `source_ja` 与 `aliases_ja` 各别名的规范化集合，命中条件 = `translation_status=translated` 且 `target_zh` 非空（`has_translation`）；同键对应多个不同译名 → 转人工。
5. **L2 历史译名**：规范化原名（先全名、后去冠名基名）== 历史已发布赛事（全部非 2026 年份）`original_name` 规范化 → 采用该赛事 `chinese_name`；同一键对应多个不同中文名 → 转人工（歧义不自动取舍）。历史 `Stp.` 与 2026 `Chase` 等术语差异通过基名再匹配覆盖，仍不中转人工。
6. **L3 新翻译**：按已上线风格生成（冠名不进名、级别后缀按地区先例、术语库既有译词优先），生成时附「建议理由」列；全部必须经用户审核才进入 manifest。
7. 让赛规则与去让赛 change 一致：原文括号让赛标记 → 候选不含让赛字样；原文未括号 handicap → 转人工。
8. `manual_lock_flags.chinese_name` 锁定的赛事：导出即转人工桶、不进写入集；commit 对赛历对象做与去让赛先例一致的 manual_lock_flags 快照 CAS + 锁定硬拒绝。

## 状态与并发

- 写入单事务；`select_for_update` 锁定 573 行；before CAS（`chinese_name` 与导出值逐行比对 + `manual_lock_flags` 快照比对），漂移整批回滚；批次 OperationLog 幂等拒绝重复 commit。
- 写入只能用 `bulk_update([chinese_name, updated_at])`：`RaceEvent.save()` 会在 `update_fields` 强制附加 `slug/series_key`（`models.py` 1095-1106），禁止逐对象 `save()`。
- 无新增模型/迁移；不写 `RaceSeries`、术语库。
- 取舍记录（F-008）：去让赛骨架的 SHA/canonical-json 工具函数与 artifact 加载校验层为规则无关机械层，但本 change 是一次性批次，接受整份 fork（约 300 行）而不抽公共模块——抽公共模块会改动已上线的去让赛模块，扩大复审面；批次完成后 fork 代码随 change 归档，不承担长期双份维护。

## 迁移/回滚

- 回滚 = 从写前 custom-format 备份恢复，或按 SHA 锁定 manifest artifact 中的 before 值反向受控写回（另授权）。
- 候选生成与 manifest 均在本地/只读通道，生产唯一写入口是 `--commit`。

## 性能与可观测

- 573 行规模，单次事务与全量 verify 均为秒级；导出、候选、verify 输出计数必须逐层一致（573 = written + veto + 漂移拒绝）。

## 关键决策（待用户方案审核确认）

1. 范围锁定 573 场 2026 已发布赛事，系列/术语库不动（双卡片另案）。
2. 冠名一律不进中文名（沿用历史已上线风格）。
3. L3 新翻译候选由 Claude 生成、用户工作簿逐行审核后才可写入；无全自动写入路径。
