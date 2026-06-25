## 1. 识别服务实现

- [x] 1.1 (integration) 在 `server/stable/services/terms.py` 或相邻服务中新增结构化马名识别结果类型，区分 `formal_term`、`external_alias` 和 `heuristic` 来源。
- [x] 1.2 (integration) 实现候选 token 提取、NFKC 标准化、`ExternalHorseAlias.normalized_name__in` 批量查询、长词优先和文章出现顺序去重。
- [x] 1.3 (integration) 保留兼容旧调用的字符串列表接口，使现有翻译和校验调用可以逐步迁移。
- [x] 1.4 (integration) 确保正式 `TermEntry(term_type=horse)` 优先于外部马名索引，且外部索引命中不会进入 `apply_term_mappings()`。
- [x] 1.5 (integration) 对同一 `normalized_name` 命中多个 `ExternalHorseAlias.external_horse_id` 的情况保留全部 horse ID，并确定展示用主 ID 的排序规则。
- [x] 1.6 (integration) 实现普通词与外部马名同名时的强马名上下文消歧，缺少强上下文时不得返回外部已知马名。

## 2. 翻译与发布校验接入

- [x] 2.1 (integration) 调整翻译阶段，使用结构化识别结果生成外部已知马名和启发式疑似马名占位符，并在 metadata 中保存识别来源。
- [x] 2.2 (integration) 确保外部已知但无中文译名的马名在译文中还原为原始日文，不被自动替换为中文。
- [x] 2.3 (integration) 调整发布校验，外部已知马名未保留时记录独立 warning，payload 包含日文名、外部 horse ID 列表、来源和置信度。
- [x] 2.4 (integration) 确保只命中 `ExternalHorseAlias` 的马名不触发核心术语或背景术语缺失校验。

## 3. 术语候选发现接入

- [x] 3.1 (integration) 调整术语候选发现，新闻中出现、外部索引命中且无正式中文术语的马名均以 `external_horse_alias` detector 进入候选池。
- [x] 3.2 (integration) 保留启发式疑似马名候选发现，但继续应用普通词过滤，避免 `タイトル` 等普通词入池。
- [x] 3.3 (integration) 确保外部索引命中但已有正式马名术语或日文别名时不创建重复候选。
- [x] 3.4 (application) 如现有候选详情证据展示不足以区分 detector，补充后台展示或测试断言，确保工作人员可看到外部索引来源。

## 4. 测试与验证

- [x] 4.1 (application) 增加单元测试：`マヤノライジン` 存在于 `ExternalHorseAlias` 时被识别为外部已知马名，翻译保护但不中文替换。
- [x] 4.2 (application) 增加单元测试：`タイトル` 未命中外部索引且在普通词过滤表中时，不进入未知马名列表、校验 warning 或马名候选池。
- [x] 4.3 (application) 增加单元测试：同一日文马名同时存在正式 `TermEntry` 和 `ExternalHorseAlias` 时，正式术语优先。
- [x] 4.4 (application) 增加单元测试：外部马名缺失于发布稿时产生独立 warning，且不产生正式术语缺失 issue。
- [x] 4.5 (application) 增加候选发现测试：外部索引命中但无正式中文译名的马名进入候选池，detector / reason 可追溯。
- [x] 4.6 (application) 增加候选发现测试：正文背景段落中的外部索引命中马名也进入候选池。
- [x] 4.7 (application) 增加识别测试：普通词与外部马名同名时，普通语境不识别为马名，强马名语境才识别。
- [x] 4.8 (application) 增加识别或校验测试：同一日文马名对应多个外部 horse ID 时，payload 保留全部 ID。
- [x] 4.9 (application) 运行 `DB_ENGINE=sqlite python manage.py check`。
- [x] 4.10 (application) 运行相关 `stable` 测试，至少覆盖术语识别、翻译、校验和候选发现用例。
- [x] 4.11 (operations) 运行 `openspec validate use-external-horse-alias-for-name-recognition --strict`。
- [x] 4.12 (operations) 更新 `docs/current_state.md` 和必要决策文档，记录外部马名索引已接入识别链路但不写入正式术语库。
