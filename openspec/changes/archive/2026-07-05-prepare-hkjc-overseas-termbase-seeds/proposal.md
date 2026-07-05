## Why

多地区新闻与术语库已经上线，但当前 HKJC 正式种子抓取主要覆盖香港本地马，仍不能补齐“主要参赛地区在海外”的海外马、海外骑师和海外赛事中文译名。HKJC 海外转播 Race Card 同时提供英文页与繁中页，并可通过同一赛事参数或 horse profile 参数对齐中英文名称，适合作为第一批海外中文术语种子的官方来源。

## What Changes

- 在现有 `prepare_termbase_seed_data` 审核文件流程中新增 `hkjc_overseas` 来源，用于准备 HKJC overseas simulcast 术语种子。
- 自动发现 HKJC overseas 当前可见 Race Card，支持低频抓取前若干 race card，并保留请求上限、请求间隔和输出目录控制。
- 支持精确指定海外 Race Card 作为可复现输入，例如 `RaceDate/Racecourse/RaceNo`，同时默认流程必须具备自动发现能力。
- 第一版候选类型覆盖 `horse`、`jockey` 和 `race`；练马师、马主、马场、装备等海外字段暂缓。
- 输出继续以人工审核文件为边界，只生成 `seed_candidates.csv`、`seed_conflicts.csv`、`summary.json` 和新增 `source_evidence.json`，不写正式术语库、不写外部马名索引、不触发翻译/发布/QQ。
- HKJC overseas 候选仍作为官方来源，`notes` 标记 `source_tier=official` 和 `requires_review=false`；人工导入仍通过后续审核流程决定。
- 中文目标译名输出为简体中文，原始 HKJC 繁体译名和证据 URL 保留在 `notes` 与 `source_evidence.json`。
- 当前不扩展 `RacingRegion` 枚举；英国、法国、美国、日本映射到现有地区，南非、德国、澳洲、爱尔兰、韩国、阿联酋、新西兰等暂归 `other` 并在证据中保留国家/地区代码。
- 当 Race Card 页面存在但显示“未有资料”或等价状态时，记录为可解释跳过，不将整批标记为失败。

## Capabilities

### New Capabilities

- 无。本变更扩展既有术语种子数据准备能力。

### Modified Capabilities

- `termbase-seed-data-preparation`: 增加 HKJC overseas simulcast 来源、海外 Race Card 自动发现、海外马名/骑师/赛事名候选、独立证据文件、可解释跳过语义，以及与当前 `racing_region` 导入字段一致的候选 CSV 兼容要求。

## Impact

- 主要影响 `server/stable/services/termbase_seed.py` 与 `server/stable/management/commands/prepare_termbase_seed_data.py`。
- 需要新增或扩展 HKJC overseas fixture、解析测试和端到端命令测试。
- 需要更新 `docs/termbase_seed_data_preparation.md`、`docs/current_state.md`、`docs/project_status.md`；若部署或生产抓取本能力，再更新 `docs/deploy_runbook.md`。
- 不需要数据库迁移，不修改 `TermEntry`、`TermAlias`、`ExternalHorse` 或 `ExternalHorseAlias` 数据模型。
