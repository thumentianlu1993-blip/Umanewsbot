## 1. HKJC overseas 来源接入

- [x] 1.1 (integration) 在术语种子服务中新增 `hkjc_overseas` 来源常量、来源配置、Race Card 参数结构和 `source_evidence.json` 数据结构。
- [x] 1.2 (integration) 实现 HKJC overseas Race Card 自动发现，支持默认前 3 个 race card、`--limit-meetings`、`--limit-races`、`--max-requests` 和 `--request-interval-seconds`。
- [x] 1.3 (integration) 实现可重复传入的 `--hkjc-overseas-race RaceDate=YYYY-MM-DD,Racecourse=<code>,RaceNo=<number>` 解析与抓取入口，并在证据中记录每个指定 Race Card 参数。
- [x] 1.4 (integration) 实现 HKJC overseas 直接请求、脚本数据、渲染后缓存和可选浏览器渲染 fallback 的抓取抽象；默认不新增生产浏览器硬依赖，并记录每条证据的抓取方式。

## 2. 候选抽取与合并

- [x] 2.1 (integration) 实现英文页与繁中页的 Race Card 对齐，抽取 `horse`、`jockey` 和 `race` 候选。
- [x] 2.2 (integration) 实现繁体中文到简体中文转换，确保 `target_zh` 与中文别名输出为简体，并保留原始繁体证据。
- [x] 2.3 (integration) 实现 HKJC overseas 地区映射，已支持地区写入现有 `racing_region`，未支持地区写入 `other` 并保留原始地区代码。
- [x] 2.4 (integration) 实现按 `term_type`、英文原文和简体中文译名合并候选；相同原文不同译名写入 `seed_conflicts.csv`。
- [x] 2.5 (integration) 确保 horse profile 的 `h` 或 `simulcastHorseId` 只作为证据和辅助对齐信息，不作为术语去重主键。

## 3. 命令与输出

- [x] 3.1 (application) 扩展 `prepare_termbase_seed_data` 命令，支持 `--source hkjc_overseas`、`--hkjc-overseas-race` 精确 Race Card 参数和现有触网边界参数，并在精确参数格式错误时拒绝执行。
- [x] 3.2 (application) 确保 `seed_candidates.csv` 表头与现有导入器一致：`term_type,source_language,racing_region,source_ja,target_zh,aliases_ja,aliases_zh,priority,is_active,notes,race_grade`。
- [x] 3.3 (application) 在 HKJC overseas 候选 `notes` 中写入 `source=hkjc_overseas`、`source_tier=official`、`requires_review=false` 和必要证据摘要。
- [x] 3.4 (application) 输出 `source_evidence.json`，记录候选证据、冲突证据、跳过 Race Card 和失败原因。
- [x] 3.5 (application) 实现 Race Card 未有资料时的 `skipped_races` 记录；仅真实失败、解析错误、达到限制、指定 Race Card 缺失或渲染 fallback 不可用导致 `incomplete=true`。

## 4. 测试与文档

- [x] 4.1 (application) 增加或扩展 HKJC overseas fixture，覆盖英文页、繁中页、不可用 Race Card、地区映射和冲突样本。
- [x] 4.2 (application) 增加服务层测试，验证马名、骑师、赛事名抽取、繁简转换、合并冲突、证据输出、渲染 fallback 不可用时的失败可见性和无正式表写入。
- [x] 4.3 (application) 增加管理命令测试，验证自动发现、精确 Race Card、精确参数格式错误、触网限制、跳过语义和候选 CSV 可被导入器 dry-run 预检。
- [x] 4.4 (operations) 更新 `docs/termbase_seed_data_preparation.md`、`docs/current_state.md` 和 `docs/project_status.md`，记录 HKJC overseas 种子准备能力、限制和审核流程。
- [x] 4.5 (operations) 若本变更部署或执行生产抓取，更新 `docs/deploy_runbook.md` 记录命令、参数、输出目录和回滚方式。（本次未部署且未执行生产抓取，无需更新）

## 5. 验证

- [x] 5.1 (application) 运行聚焦测试：`DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable` 或更窄的相关测试集合。
- [x] 5.2 (application) 运行 Django 检查：`DB_ENGINE=sqlite python manage.py check`。
- [x] 5.3 (application) 使用 fixture 执行 `prepare_termbase_seed_data --source hkjc_overseas` 冒烟测试，并用 `import_terms --dry-run` 预检 `seed_candidates.csv`。
- [x] 5.4 (operations) 经人工确认后，执行低上限 live dry-run，记录输出目录、候选数量、冲突数量、跳过数量和是否 `incomplete=false`。
- [x] 5.5 (operations) 运行 `openspec validate prepare-hkjc-overseas-termbase-seeds --strict`。
