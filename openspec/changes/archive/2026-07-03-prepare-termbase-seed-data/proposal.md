## Why

当前生产正式术语库和术语候选池仍主要是日文内容，多地区新闻源已经上线，但香港、英国、法国、美国等地区缺少可用的中文术语基础。需要先从含中文译名的可信赛马资料来源中准备一批可人工审核、可追溯、可导入的术语种子，补齐多地区翻译、术语命中、自动标签和发布校验的基础数据。

## What Changes

- 新增“术语种子数据准备”能力，从 `HKJC` 体系和 `WP Stud` 抽取术语候选。
- 第一版覆盖 `horse`、`race`、`jockey`、`trainer`、`racecourse`、`fixed_phrase` 六类术语。
- 输出两份人工审核文件：
  - `seed_candidates.csv`：严格保持现有术语导入字段，必须可通过 `import_terms --dry-run` 预检。
  - `seed_conflicts.csv`：记录来源冲突、推荐主译名、别名、证据和人工审核提示，不直接导入。
- 地区处理顺序固定为香港优先、日本最后；中间地区可按实现便利度处理。
- 中文译名统一输出简体中文；来源为繁体中文时必须执行繁简转换，并在备注中保留原始繁体证据。
- HKJC 与 WP Stud 同时存在译名时，HKJC 作为主译名，WP Stud 作为别名、佐证或备注；只有 WP Stud 时可作为主译名候选，但必须标记为民间来源，等待人工审核。
- HKJC 第一版只承诺稳定 HTML/文本入口；`racecards` PDF、排位表 PDF 或网页排位表全量抽取延后处理。
- 第一版只生成审核产物，不直接写入生产 `TermEntry`，也不自动改变现有文章、翻译、发布或 QQ 推送状态。

## Capabilities

### New Capabilities

- `termbase-seed-data-preparation`：从 HKJC 体系和 WP Stud 准备可人工审核、可导入的中文术语种子候选与冲突清单。

### Modified Capabilities

- `termbase-and-race-priority`：明确种子候选 CSV 必须兼容现有术语导入字段，且目标中文译名必须输出为简体中文。

## Impact

- 新增或扩展 `server/stable/services/` 中的术语种子抽取、归一、合并、繁简转换和冲突检测服务。
- 新增 Django 管理命令，用于按来源触网抓取或读取缓存样本，生成隔离在 `runtime/termbase_seed/<timestamp>/` 下的 `seed_candidates.csv`、`seed_conflicts.csv` 与运行摘要。
- 新增测试覆盖来源优先级、繁简转换、字段兼容、冲突输出、地区排序和不写正式表的安全边界。
- 新增文档说明种子数据准备流程、人工审核方式、CSV 字段约定和后续导入步骤。
- 不新增生产 Celery Beat 调度，不自动写入 `TermEntry`，不改变现有正式术语导入入口。
