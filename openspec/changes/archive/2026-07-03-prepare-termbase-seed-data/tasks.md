## 0. 预声明假设与来源确认

- [x] 0.1 (integration) 固定首轮来源边界：HKJC 只做稳定 HTML/文本入口，不做 `racecards` PDF 或排位表全量抽取；WP Stud 先确认可抓取页面、字段和样本。
- [x] 0.2 (integration) 预声明首轮 sample-run 验收口径：fixture 模式必须生成非空候选、冲突清单可为空但文件必须存在、网络失败或反爬导致的来源缺失必须标记为 incomplete。

## 1. 种子数据模型与服务层

- [x] 1.1 (integration) 定义术语种子候选、来源证据、冲突记录和输出摘要的轻量数据结构，不新增数据库模型。
- [x] 1.2 (application) 选择并接入繁简转换实现；若新增轻量依赖，必须更新 `requirements.txt` 并验证测试环境可导入。
- [x] 1.3 (integration) 实现繁简转换封装，确保 `target_zh` 和 `aliases_zh` 输出为简体中文，并保留原始繁体证据。
- [x] 1.4 (integration) 实现候选归一、同源去重、跨来源合并和地区排序规则，保证香港优先、日本最后。
- [x] 1.5 (integration) 实现 HKJC 优先、WP Stud 补充的主译名和别名选择规则；默认 HKJC 候选 `priority=100`，只有 WP Stud 的民间候选 `priority=80` 且标记 `requires_review=true`。
- [x] 1.6 (integration) 实现冲突检测与 `seed_conflicts.csv` 记录生成逻辑。

## 2. 来源抓取与解析

- [x] 2.1 (integration) 对 HKJC 与 WP Stud 做 source discovery/spike，记录首轮固定 URL、支持实体类型、字段映射、不可用入口和失败原因。
- [x] 2.2 (integration) 实现 HKJC 本地马匹资料解析，抽取英文名、繁体中文名、来港前名和可用证据 URL。
- [x] 2.3 (integration) 实现 HKJC 海外赛事转播资料解析，抽取海外马、赛事、骑师、练马师、赛马场等术语候选。
- [x] 2.4 (integration) 实现 HKJC 术语说明或赛绩指引解析，抽取固定表达候选。
- [x] 2.5 (integration) 实现 WP Stud 术语资料解析，抽取马名、赛事名和其他支持类型候选，并标记为民间来源。
- [x] 2.6 (integration) 为 HKJC 与 WP Stud 解析器增加 fixture 样本，覆盖英文、繁体中文、日文原文和简体化目标译名。
- [x] 2.7 (integration) 实现受控网络客户端或复用现有低频请求模式，记录 URL、状态码、错误原因、请求数量、`max_requests`、`request_interval_seconds` 和 `timeout_seconds`。

## 3. 管理命令与输出文件

- [x] 3.1 (application) 新增术语种子准备管理命令，支持 `--source`、`--region`、`--output-dir`、`--allow-network`、`--limit-pages`、`--max-requests`、`--request-interval-seconds` 和 `--timeout-seconds`。
- [x] 3.2 (application) 管理命令在未传 `--allow-network` 时只允许读取 fixture、缓存文件或本地输入，不得触网。
- [x] 3.3 (application) 管理命令生成 `seed_candidates.csv`，表头严格为 `term_type,source_language,source_ja,target_zh,aliases_ja,aliases_zh,priority,is_active,notes,race_grade`。
- [x] 3.4 (application) 管理命令生成 `seed_conflicts.csv`，记录冲突类型、HKJC 译名、WP Stud 译名、推荐主译名、别名和证据。
- [x] 3.5 (application) 管理命令默认输出到 `runtime/termbase_seed/<timestamp>/`，不得覆盖 `server/stable/data/terms_seed.csv`。
- [x] 3.6 (application) 管理命令输出摘要，包含来源、地区、请求数量、候选数、冲突数、是否完整、失败摘要和输出路径。

## 4. 文档与审核流程

- [x] 4.1 (operations) 新增术语种子数据准备文档，说明 HKJC/WP Stud 来源边界、地区顺序、繁简转换、人工审核和后续导入步骤。
- [x] 4.2 (operations) 更新术语上传模板 CSV 与说明，补充 `source_language`、简体目标译名和种子候选审核注意事项。
- [x] 4.3 (operations) 更新 `docs/current_state.md` 和 `docs/project_status.md`，记录本 change 的计划边界和未入库安全边界。

## 5. 验证

- [x] 5.1 (application) 添加测试：`seed_candidates.csv` 表头严格兼容现有 `import_terms` 字段，并可被 dry-run 预检。
- [x] 5.2 (integration) 添加测试：繁体中文来源输出简体 `target_zh`，原始繁体证据被保留。
- [x] 5.3 (integration) 添加测试：HKJC 与 WP Stud 同时命中时 HKJC 为主译名，WP Stud 为别名或佐证。
- [x] 5.4 (integration) 添加测试：只有 WP Stud 命中时生成候选并标记 `source_tier=community` 与 `requires_review=true`。
- [x] 5.5 (integration) 添加测试：香港候选优先输出，日本候选最后输出。
- [x] 5.6 (application) 添加测试：种子准备命令不写 `TermEntry`、`TermAlias`、`TermCandidate` 或 `External*` 表，不派发翻译、发布或 QQ 推送任务。
- [x] 5.7 (application) 添加测试：未指定 `--output-dir` 时输出到独立 runtime 目录，且不覆盖正式 `terms_seed.csv`。
- [x] 5.8 (integration) 添加测试：未传 `--allow-network` 不触网；网络非 2xx、超时或解析失败时运行摘要标记来源 incomplete。
- [x] 5.9 (integration) 添加测试：首版不支持的 HKJC PDF/racecard 全量抽取被拒绝、跳过或标记 deferred。
- [x] 5.10 (application) 执行 `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python server/manage.py test stable` 或相关聚焦测试。
- [x] 5.11 (operations) 执行 `openspec validate prepare-termbase-seed-data --strict`、`openspec validate --all` 和 `git diff --check`。
