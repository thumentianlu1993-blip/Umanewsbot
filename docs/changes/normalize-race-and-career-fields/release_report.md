# `normalize-race-and-career-fields` 发布报告

> 发布时间：2026-07-25（Asia/Shanghai）

## 发布版本

- **Merge Commit**：`9b58bfd4`（PR #21）
- **基线**：`origin/main@f8e09c3b` → `9b58bfd4`
- **分支**：`codex/normalize-race-and-career-fields`（已 squash-merge 到 main）
- **生产镜像**：`b1f125342388`（`umanewsbot:prod`）
- **审查指纹**：`bd8232c42ae30697ee276294d7d8dbc46e6d10d22b77aa2ff7e5d2c4bde6bb09`

## 迁移

| Migration | 内容 | 结果 |
|-----------|------|------|
| `0054_race_field_normalization_schema` | 新增规范化字段 + Run/Receipt 模型 | OK |
| `0055_race_field_normalization_indexes` | `(horse_profile, normalized_finish_position)` 索引 | OK |
| `0056_race_field_normalization_brought_down` | BROUGHT_DOWN 枚举补丁 | OK |
| `0057_merge_20260725_0448` | 合并 `0054_homepage_headline_control` | OK |

## 生产 dry-run

- **输出目录**：`/tmp/norm-dry-run`（容器内）
- **处理行数**：12,817（RaceEvent 9,867 + HorseRaceRecord 2,950）
- **分类**：
  - `normalized`（有变更）：538
  - `preserved`（无变更/已规范）：12,265
  - `unknown`：14
  - `conflicts`：0
- **Manifest SHA-256**：`2e0149176e7303db2cf10f3ffb797a394c6e77a4f8b7a138789beaab2b4a8ec1`

## 生产回填

| 指标 | 数值 |
|------|------|
| 执行次数 | 2（首次全量 + 幂等复验） |
| Run #1 | `completed`，planned=12,817，actual=12,817，skipped=0，receipts=12,817 |
| Run #2 | `completed`，planned=12,817，actual=1,197（checkpoint 恢复），receipts=1,197 |
| 幂等复验 | 通过（第三次 apply 复用 checkpoint，零新增写入） |

## 数据质量验证

### 关键修复验证

| 指标 | 旧逻辑（修复前） | 新逻辑（修复后） |
|------|-----------------|-----------------|
| `"01"` → 识别为冠军 | 遗漏（`startswith("1")` 不匹配） | **80/80** 全部归一化为 position=1 |
| `"10"` → 误计为冠军 | 误计（`startswith("1")` 匹配） | **0** 不再计入 |
| DINOZZO (`21607`) 胜场 | 9（含误计） | **5**（正确） |
| Art Power (`7669`) 胜场 | 17（含误计） | **10**（正确） |
| 前导零显示 | `"06"/"08"` 直接显示 | 去零显示为 `6/8` |

### 页面验收

| 页面 | HTTP 状态 | 备注 |
|------|----------|------|
| `/healthz/` | 200 | healthy |
| `/horses/21607/`（DINOZZO） | 200 | 名次无前导零，统计正确 |
| `/horses/7669/`（Art Power） | 200 | 名次无前导零，统计正确 |
| `/races/` | 200 | 日历正常 |
| `/horses/` | 200 | 马匹列表正常 |

## 功能开关

| 开关 | 初始值 | 最终值 | 启用时机 |
|------|--------|--------|---------|
| `RACE_FIELD_NORMALIZED_DISPLAY_ENABLED` | false | **true** | 回填完成后 |
| `RACE_FIELD_NORMALIZED_STATS_ENABLED` | false | **true** | 覆盖率 100% 验证后 |

## 容器状态

| 容器 | 状态 |
|------|------|
| web | Up (healthy) |
| worker | Up |
| beat | Up |
| db | Up (healthy) |
| redis | Up (healthy) |
| nginx | Up |
| onebot | Up |

## 回滚信息

- **代码回滚**：将两个 `RACE_FIELD_NORMALIZED_*` 开关恢复 `false`
- **数据回滚**：通过 `RaceFieldNormalizationReceipt` 记录按 run 回滚
- **Migration 回滚**：不立即 drop column，优先代码级停用

## 已知事项

1. `production_head` 在容器内 dry-run 时为空（容器无 git），manifest 文件中该字段为空字符串；不影响 apply 校验。
2. 第三次幂等 apply 会从 checkpoint 恢复并重新扫描，但零新增写入（所有记录已是最新版本）。
3. `HomepageHeadlineRecommendation` 模型在 main 合并时丢失了 `created_at`/`updated_at` 字段和 Meta 约束，应在后续 change 中修复。
