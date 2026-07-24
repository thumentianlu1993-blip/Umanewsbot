# 测试用例与 RED/GREEN 计划

## RED 原则

用户授权实现后，先由测试 subagent 新增专用测试并运行。RED 必须来自当前代码的真实行为：pending horse 分支仍生成 13 条 warning、alias lexical 入口仍直接保护、uncertain 仍产生 warning、或实时/批量结果不一致。fixture、导入、语法、数据库初始化或环境错误不算 RED。

计划 RED 命令：

```bash
cd server
DB_ENGINE=sqlite python manage.py test stable.test_external_english_horse_context_gate --noinput
```

记录失败 test id、预期/实际 issue code 与 classification；不以修改 production fixture 取得 RED。

## 核心矩阵

### A. article 9595 等价正文

- 建立 13 个 active、pending、英文 horse `TermEntry`，notes 与生产一致为 `p0_major_race_participant_auto_created`。
- 使用经最小化但保留完整局部语境的 9595 等价正文。
- 断言 13 个词逐 occurrence 为 `common_word`，无 `pending_horse_original_missing`、`external_horse_not_preserved`、`background_term_missing` 或其他 horse warning/blocker。
- 断言 `Logician` 为 `confirmed_horse`，reason 包含 stallion/winner 实体信号；accepted term 正式译名逻辑仍有效，且 `needs_preserve=False`，不强制保留英文原文。
- 断言 `send_high_value_warning_notification()` 不因这些 13 个分类发送邮件。

### B. 强马名语境

分别覆盖：

- `Brilliant won at Ascot.`
- `Brilliant finished second.`
- `Brilliant, ridden by Ryan Moore, starts from stall four.`
- `Brilliant is trained by John Smith.`
- `Brilliant (IRE) heads the field.`
- `winner-turned-stallion Logician`

对 pending `TermEntry` 与 alias-only 两种来源分别断言 `confirmed_horse`、`needs_preserve=True`、缺失原名时产生正确马名 gate issue；另以已译正式 `Logician` 断言 confirmed 但 `needs_preserve=False`。

### C. occurrence 独立性

正文同时包含 `Brilliant won at Ascot` 与 `a brilliant performance`。断言前者 confirmed、后者 common；span/context 不相互污染，只有 confirmed occurrence 参与保护。

### D. uncertain 审计

- alias-only 标题 `Brilliant Result Announced`，无强马名或普通句法证据；显式证明多词 Title Case 本身不能升级为马名。
- 对照正文 `Brilliant Result won at Ascot`，相同 surface 在强赛马关系中必须 confirmed。
- 断言 classification=`uncertain`、severity=`info`（或只存在于持久审计 details）、不进入 warning signature、不发送高价值 warning。
- payload 必含 matched_text/context/span、reason、confidence、external horse ID。
- pending 正式 horse 的相同 uncertain 用法也遵循相同告警语义。

### E. 来源优先与合并

- 同一 span 同时命中正式 `TermEntry` 与 `ExternalHorseAlias`。
- 断言只有一个 occurrence；正式 canonical/译名保留，payload 附带 external horse IDs；不重复告警。

### F. 实时/批量一致

- 同一组文章分别走 article-aware 实时 translation/validation/discovery 与 `build_validation_batch_context()+validate_rewrite()`。
- 对 classifications、issue code/severity、external IDs 和 `needs_preserve` 做结构化相等断言。
- `term_discovery` 只为 confirmed horse 生成 finding；common/uncertain 不进入 horse candidate。
- 分别建立 active、candidate、removed `ArticleRaceLink`：只有 active link 的 runner/result evidence 可升级 confirmed，且实时 translation metadata、实时 validation 和 batch classification 完全一致。

### G. 性能

- 10 与 20 篇 article-aware batch 的查询数相同且均 `<=8`。
- 100 篇完整 dry-run 总 SQL `<=35`，runner/result evidence 固定各 1 次，且 `ExternalHorseAlias`、`TermEntry`、`TermAlias` 无逐文章/逐 alias 查询。
- 验证移除旧重复 lexical prefetch 后没有查询数回退；若计数器语义调整，断言实际查询而非伪造旧计数。

### H. 语言与术语回归

- 日文片假名未知马名与日文 external alias。
- 繁中 external alias。
- 正式中文术语替换。
- race/jockey/trainer 等非 horse 英文正式术语。
- 已翻译多词马名与 pending horse 原名保护。

### I. published audit-only apply

- exact-ID + reviewed manifest 才可执行；缺参数、manifest/input/settings/term snapshot drift 均 fail closed。
- article 9595 等价 published fixture 执行后，仅 gate audit allowlist 字段变化。
- `workflow_status`、`automation_status`、`review_mode`、`risk_level`、`publish_ready_at`、`ranked_revived_at`、`published_to_web_at`、译文、公开状态、QQ deliveries 和既有 NotificationLog 逐项不变。
- 断言路径未调用 `apply_validation_outcome()`、未发送 notification。

## GREEN 验证

```bash
cd server
DB_ENGINE=sqlite python manage.py test stable.test_external_english_horse_context_gate --noinput
DB_ENGINE=sqlite python manage.py test stable.test_english_term_context_gates stable.test_contextual_news_entities stable.test_term_gate_reprocessing --noinput
DB_ENGINE=sqlite python manage.py test stable.tests.TermRecognitionTests stable.tests.AutomationPublishGateTests --noinput
DB_ENGINE=sqlite python manage.py check
cd ..
git diff --check
```

实际类名以探索后仓库现有测试类为准；实现 subagent 必须记录命令、数量和耗时。

## GREEN 证据（2026-07-23）

使用仓库虚拟环境和 SQLite 运行本 change 专用测试：

```bash
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate --noinput -v 1
```

结果：14/14 通过。覆盖 9595 等价正文、Logician、五类强语境、同文双角色、
alias/formal 同 span 合并、uncertain 审计、active structured evidence、10/20 篇查询边界，
以及 published exact-ID audit-only dry-run/apply 与 drift fail-closed。

直接受影响回归：

```bash
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate \
  stable.test_contextual_news_entities \
  stable.test_term_gate_reprocessing --noinput -v 1
```

结果：106/106 通过；其中 100 篇 dry-run 查询预算测试通过。`manage.py check` 与
`git diff --check` 均通过。既有 `stable.test_english_term_context_gates` 尚有 6 个旧断言
要求 uncertain 继续产生 warning/blocker，和本 change 已审核规格“uncertain 仅 info/audit”
直接冲突；未为兼容旧断言恢复高价值告警污染。

## RED 证据（2026-07-23）

测试文件先通过语法/import 静态检查：

```bash
python3 -m py_compile server/stable/test_external_english_horse_context_gate.py
```

随后使用仓库既有虚拟环境和 SQLite，仅运行三个最小目标测试：

```bash
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_article_9595_common_words_do_not_create_horse_warnings \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_title_case_alias_only_match_is_uncertain_audit_not_warning \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_pending_term_strong_contexts_are_confirmed_and_preserved \
  --noinput -v 2
```

结果：发现 3 个测试，数据库迁移、Django system check 和 fixture 均成功；实际执行 0.023 秒，退出码 1，得到 7 个 assertion failures。

- `test_article_9595_common_words_do_not_create_horse_warnings`：预期 13 个普通词没有 horse issue；实际恰有 13 个 `core_term_missing`/horse issues。首条 `Africa` 被判为 `term_semantic_classification=uncertain`、`reason=insufficient_context_evidence`，并以 blocker 进入 gate。
- `test_title_case_alias_only_match_is_uncertain_audit_not_warning`：预期 `Brilliant Result` 为 `classification=uncertain`、`needs_preserve=False`、info/audit；实际 payload 没有 occurrence `classification` 字段，且为 `entity_type=horse`、`evidence=[external_horse_alias,strong_horse_context]`、`needs_preserve=True`。证明 Title Case 仍会被自动升级。
- `test_pending_term_strong_contexts_are_confirmed_and_preserved`：五个强语境均预期 `classification=confirmed_horse`、`needs_preserve=True`；实际所有 payload 都没有 `classification` 字段，且正式 pending term 的 `needs_preserve=False`。其中 `Brilliant, ridden by ... stall four` 还被实际判为 `common_word`，其余四句虽为 `entity_type=horse` 仍未保护原文。

这些失败均由本 change 锁定的 occurrence 三分类、pending horse 保护语义和 ordinary-context 门禁尚未实现导致，不是语法、import、迁移、fixture 或环境错误，属于有效 RED。首次直接运行 `python`/`python3` 分别遇到命令不存在和全局环境缺少 Django，已改用仓库既有 `.venv` 后消除环境因素；Docker 权限路径不作为 RED 证据。

## GREEN 证据（2026-07-23）

实现落地后，先将既有英文 horse context 测试从文章级旧语义迁移到 occurrence 新语义：

- uncertain title/background：从 `core_term_missing` blocker 或 `background_term_missing` warning，改为 `english_horse_occurrence_uncertain` info/audit，且不进入 warning。
- common word：从 `english_term_common_word_downgraded` warning，改为只在 `english_term_classifications` / `article_entities` 保存 `classification=common_word`，不产生 warning。
- `off` / `shadow`：英文 horse occurrence 也使用统一 resolver，不再保留旧污染；shadow 仍不得持久修改文章状态。
- confirmed horse：强语境仍产生 blocker；payload 明确为 `classification=confirmed_horse`、`term_semantic_classification=proper_noun`。
- 批量 common 计数改为 occurrence 数；`Contact` fixture 的标题 1 次加正文 8 次，预期为 9，而不是旧文章级计数 1。

实际测试命令与结果：

```bash
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_english_term_context_gates --noinput -v 1
# 17 tests，OK，0.125s

DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.tests.TermResolverTests stable.tests.AutomationFlowTests --noinput -v 1
# 61 tests，OK，0.290s

DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate \
  stable.test_english_term_context_gates \
  stable.tests.TermResolverTests \
  stable.tests.AutomationFlowTests \
  --noinput -v 1
# 92 tests，OK，0.470s

DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_contextual_news_entities stable.test_term_gate_reprocessing \
  --noinput -v 1
# 92 tests，OK，0.707s
```

仓库不存在原计划中的 `stable.tests.TermRecognitionTests` 与 `stable.tests.AutomationPublishGateTests`，因此按测试职责定位并使用最接近的现有 `TermResolverTests` 与 `AutomationFlowTests`。上述运行均通过 Django system check；`AutomationFlowTests` 触发静态目录不存在的既有 warning，但不影响测试结果。

## Reviewer findings RED 证据（2026-07-23）

代码 reviewer 提出的 P1/P2 finding 先各新增一项专用回归，并执行：

```bash
python3 -m py_compile server/stable/test_external_english_horse_context_gate.py
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_horse_entity_noun_context_does_not_override_strong_race_relation \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_live_and_reprocessing_batch_share_visible_text_and_ignore_hidden_aliases \
  --noinput -v 2
```

结果：2 tests，2 assertion failures，退出码 1；数据库迁移、fixture 与 Django system check 均成功。

- P1：pending `Brilliant` 在 `The Brilliant filly won at Ascot` 中预期 `confirmed_horse / needs_preserve=True`，实际为 `common_word / needs_preserve=False`，reason=`ordinary_adjective_context`。同一测试也锁定 alias-only `The Splendid filly won ...` 的相同期望；首个 pending 断言已先证明当前优先级错误。
- P2：实时 validation 只得到可见正文中的 `Visible Star`；批量 reprocessing context 除 `Visible Star` 外，还实际产生隐藏 `<nav>` 中的 `Hidden Runner` 和 `<aside>` 中的 `Sidebar Horse`，三者均被判为 `confirmed_horse / needs_preserve=True`。预期实时和批量 occurrence 完全一致，且隐藏 alias 不产生实体或 issue。

两项均由 reviewer 指出的目标行为缺失直接导致，不是 fixture、import、数据库或环境错误。P2 测试只要求批量路径复用实时 validation 已有的可见文本表示，不新增或修改 HTML 提取、正文清洗规则。

## Reviewer 第二轮 findings RED 证据（2026-07-23）

同一 reviewer 复审提出的 3 个 P1 与 1 个 P2 均先新增精确回归：

```bash
python3 -m py_compile server/stable/test_external_english_horse_context_gate.py
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_entity_noun_relations_win_but_ordinary_adjectives_remain_common \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_structured_jockey_and_trainer_names_do_not_confirm_horse_aliases \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_structured_horse_evidence_is_scoped_to_the_actual_occurrence \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_non_english_batch_skips_structured_loader_while_english_still_uses_it \
  --noinput -v 2
```

结果：4 tests，6 assertion failures，退出码 1；数据库迁移、fixture 与 Django system check 均成功。

- P1 / 实体名词关系优先级：pending `The Brilliant filly is trained by...` 与 alias-only `The Splendid filly is trained by...` 均预期 `confirmed_horse / needs_preserve=True`，实际均为 `common_word / False`，reason=`ordinary_adjective_context`。同一测试还锁定 `Brilliant/Splendid mare, trained by...` 必须 confirmed，以及 `a brilliant/splendid performance` 必须继续 common；后两类当前断言通过。
- P1 / 角色类型隔离：实时 loader 对 jockey=`Brilliant`、trainer=`Splendid` 的同名 external aliases 均为 uncertain；reprocessing batch structured map 却把两者分别以 `race_runner:...:jockey_name` / `trainer_name` 证据升级为 horse，导致 live 与 batch payload 不相等。
- P1 / occurrence 独立：linked runner `Brilliant` 的真实 `Brilliant won...` 正确 confirmed；同文后续 `a brilliant performance` 预期 common，实际因 normalized spelling 的 structured runner evidence 广播全文而成为 `confirmed_horse / needs_preserve=True`。
- P2 / 非英文查询边界：混合 Japanese + English 批量 resolver 中，英文 `Brilliant won...` 仍正常 confirmed；Mock 证明 structured loader 实际收到 `[japanese.id, english.id]`，预期只收到 `[english.id]`，说明非英文文章仍触发 runner/result loader。

上述失败均是 reviewer 指定能力尚未实现造成，不是 fixture 或环境错误。测试不扩大结构化证据来源、不改变正文提取规则，也未放松普通 adjective、confirmed horse 或英文 structured loader 的既有行为。

## Reviewer 第三轮 findings RED 证据（2026-07-23）

本轮锁定 rollout 三态语义与翻译 occurrence span：

```bash
python3 -m py_compile \
  server/stable/test_english_term_context_gates.py \
  server/stable/test_external_english_horse_context_gate.py
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_english_term_context_gates.EnglishTermContextModeTests.test_off_keeps_legacy_gate_result \
  stable.test_english_term_context_gates.EnglishTermContextModeTests.test_shadow_records_difference_without_changing_legacy_result \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_unknown_horse_placeholders_only_protect_confirmed_occurrence_spans \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_translated_formal_mapping_only_replaces_confirmed_occurrence_span \
  --noinput -v 2
```

结果：4 tests，5 assertion failures，退出码 1；数据库迁移、fixture 与 Django system check 均成功。

- P1 / mode=off：普通 `Brilliant` 旧 gate 预期继续产生 legacy `core_term_missing`，实际 blocker 为空，说明 occurrence suppress 被错误应用于 off。
- P1 / mode=shadow：预期保留同一 legacy blocker，同时只记录 `would_remove_blocker` shadow detail 且文章状态不持久变化；实际 blocker 为空，在首个 legacy 结果断言即失败。现有 enforce 测试继续锁定只有 enforce 才采用 common/uncertain/confirmed 三分类结果。
- P2 / pending placeholder：同文第一处 `Brilliant won...` confirmed、第二处 `a Brilliant performance` common；provider 输入预期只有 confirmed span 替换成一次 `__UMA_KEEP_1__`，实际出现 2 次。
- P2 / alias-only placeholder：同样预期一次 placeholder，实际 2 次。
- P2 / 已译正式 mapping：预期只把 confirmed occurrence 映射为 `辉煌`，保留普通 occurrence 的 `Brilliant`；实际两处都被全局替换为 `辉煌`。

翻译测试直接检查 provider 的受保护原文输入和 mapping 输出，不调用真实网络，不改变正文提取/清洗规则。失败来自 placeholder 与 mapping 仍按 surface form 全局替换，而非 fixture 或环境问题。

## 第三轮修复后的测试配置契约与 GREEN（2026-07-23）

仓库默认 `ENGLISH_TERM_CONTEXT_MODE=off`。`AutomationFlowTests` 中 5 个明确验证 occurrence/enforce 行为的测试此前未显式声明 mode，导致它们在默认 legacy 模式下失败。测试修复仅为以下 5 个方法增加最窄方法级 `ENGLISH_TERM_CONTEXT_MODE="enforce"`，未修改断言、应用代码或整个 legacy 测试类：

- `test_english_high_ambiguity_horse_match_is_audited_without_blocker`
- `test_english_common_word_context_downgrades_review_seed_terms`
- `test_english_common_seed_with_race_marker_defaults_to_common_word_without_entity_context`
- `test_english_common_word_weak_racing_title_context_still_downgrades`
- `test_reprocess_term_gate_blocked_articles_reports_common_word_downgrades_and_region_summary`

实际验证：

```bash
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.tests.AutomationFlowTests --noinput -v 1
# 37 tests，OK，0.243s

DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_english_term_context_gates \
  stable.test_external_english_horse_context_gate \
  --noinput -v 1
# 39 tests，OK，0.297s

DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_contextual_news_entities \
  stable.test_term_gate_reprocessing \
  stable.tests.TermResolverTests \
  --noinput -v 1
# 116 tests，OK，0.759s
```

所有运行均通过 Django system check；`AutomationFlowTests` 仍有既有 staticfiles 目录 warning，但无测试失败。

## Reviewer 第四轮 findings RED 证据（2026-07-23）

本轮为 1 个 P1 与 2 个 P2 新增 4 个精确测试：

```bash
python3 -m py_compile server/stable/test_external_english_horse_context_gate.py
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_validation_requires_the_confirmed_occurrence_to_be_preserved \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_html_source_offsets_protect_only_visible_confirmed_placeholder_span \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_html_source_offsets_map_only_visible_confirmed_formal_span \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_rewrite_maps_provable_generated_occurrence_without_source_span_indexing \
  --noinput -v 2
```

结果：4 tests，4 assertion failures，退出码 1；数据库迁移、fixture 与 Django system check 均成功。

- P1 / validation occurrence preservation：source 中第一处 `Brilliant won...` 为 confirmed，第二处 `a Brilliant performance` 为 common。目标稿删除 confirmed 对应句但保留 ordinary `Brilliant` 时，预期 `pending_horse_original_missing`，实际 issues 为空；对照稿正确保留 confirmed occurrence 的断言也已锁定。
- P2 / HTML placeholder offset：resolver 基于现有 visible representation 产生 span；raw source 含隐藏 `nav/aside` 与可见 `<p>`。预期可见 confirmed `Brilliant` 产生 1 个 KEEP placeholder、普通 occurrence 与隐藏 `Hidden Runner` 不处理；实际 placeholder 数为 0。
- P2 / HTML mapping offset：相同 HTML 结构下，预期只映射可见 confirmed span 为 `辉煌`，保留 hidden 与 ordinary `Brilliant`；实际可见 confirmed 也未映射。
- P2 / rewrite 生成文本：provider 输出把可证明的 `Brilliant won at Ascot` 移到不同位置，并保留普通 `Brilliant performance`。预期前者确定性映射为 `辉煌`、后者不改；实际前者因错误复用 source span 而 no-op。

测试只锁定已有 visible text 语义、translation/provider 输入与 rewrite 输出安全契约，不修改或扩展 HTML 提取/清洗规则，也不调用真实网络。

## Reviewer 第五轮 findings RED 证据（2026-07-23）

本轮为中文译文 occurrence preservation 与 published-audit 操作者身份门禁新增 7 个精确测试：

```bash
python3 -m py_compile server/stable/test_external_english_horse_context_gate.py
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_pending_horse_valid_chinese_racing_relations_preserve_confirmed_occurrence \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_external_alias_valid_chinese_racing_relations_preserve_confirmed_occurrence \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_chinese_ordinary_occurrence_does_not_mask_confirmed_source_horse \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_service_requires_and_binds_normalized_identities \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_apply_requires_matching_prepared_operator \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_command_requires_explicit_identities \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_command_normalizes_and_forwards_identities \
  --noinput -v 2
```

结果：7 tests，5 assertion failures、2 capability errors，退出码 1；数据库迁移、fixture、语法检查与 Django system check 均成功。2 个 error 均是目标 service/command 尚不接受显式身份参数造成的 `TypeError`/unknown argument，不是环境或 fixture 错误。

- P1 / 合法中文赛马关系：pending 与 alias-only 的 source occurrence 均为 confirmed；`Brilliant获胜/将参赛/复出/由...策骑/由...训练` 已通过，但 `Brilliant赢得了比赛` 均被误报为未保留，分别产生 `pending_horse_original_missing` 与 `external_horse_not_preserved`。
- P1 / occurrence 防回退：source 同时含 confirmed `Brilliant won...` 和 ordinary `Brilliant performance`，target 只保留普通 `Brilliant表现` 时预期仍报 missing，实际 issues 为空，证明不能退回纯全文 contains。
- P2 / service 身份：当前 dry-run 未要求显式 operator/reviewer，且 API 不接受 `operator_identity` / `reviewer_identity`，无法规范化并绑定 selectors、result payload 与 manifest；apply 同样不接受 prepared operator 匹配参数。
- P2 / command 身份：无 operator/reviewer 的 published-audit dry-run 当前可执行；显式 `--operator` / `--reviewer` 当前被判为 unknown arguments，无法将规范化身份传入 service。

本轮只修改专用测试与 change 文档；未修改应用代码、命令实现、数据库迁移、正文提取或清洗规则。

## Reviewer 第五轮实现后的独立 GREEN（2026-07-24）

测试所有者使用项目 `.venv` 与 SQLite 独立复跑第五轮新增 7 项：

```bash
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_pending_horse_valid_chinese_racing_relations_preserve_confirmed_occurrence \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_external_alias_valid_chinese_racing_relations_preserve_confirmed_occurrence \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_chinese_ordinary_occurrence_does_not_mask_confirmed_source_horse \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_service_requires_and_binds_normalized_identities \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_apply_requires_matching_prepared_operator \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_command_requires_explicit_identities \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_command_normalizes_and_forwards_identities \
  --noinput -v 2
# 7 tests，OK；Django system check 无问题
```

结果确认：

- pending 与 alias-only confirmed horse 在 `赢得了比赛`、`获胜`、`参赛`、`复出`、`由...策骑`、`由...训练` 等紧邻中文赛马关系中均视为已保留。
- source 同时存在 confirmed 与 ordinary occurrence、target 只保留普通 `Brilliant表现` 时，仍产生马名缺失 issue，未回退到纯全文 contains。
- published-audit dry-run 强制显式 operator/reviewer；空身份 fail closed，首尾空白被规范化。
- 规范化后的 operator/reviewer 同时绑定到 run selectors、result payload 与 manifest。
- apply 缺少或漂移 operator 均 fail closed；相同 operator 经规范化后可提交。
- management command 强制 `--operator` / `--reviewer`，并向 service 传递规范化身份，不再用随机值冒充操作身份。

专用模块与相关最小回归：

```bash
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate --noinput -v 1
# 33 tests，OK

DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_english_term_context_gates \
  stable.test_term_gate_reprocessing \
  stable.tests.TermResolverTests \
  stable.tests.AutomationFlowTests \
  --noinput -v 1
# 118 tests，OK
```

两次回归均通过 Django system check。118 项运行只有既有 `server/staticfiles/` 目录不存在 warning，无测试失败。

## Reviewer 第十轮 findings RED 证据（2026-07-24）

本轮锁定 formal 同源多译名歧义，以及 formal/external 同 span 的告警优先级：

```bash
python3 -m py_compile server/stable/test_external_english_horse_context_gate.py
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_conflicting_formal_horse_targets_remain_ambiguous_and_are_not_mapped \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_single_formal_horse_target_still_maps_generated_strong_occurrence \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_pending_formal_and_external_alias_same_span_emit_only_formal_missing_warning \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_alias_only_confirmed_missing_still_emits_external_warning \
  --noinput -v 2
```

结果：4 tests，2 个目标 assertion failures、2 个安全对照通过，退出码 1；数据库迁移、fixture、语法检查与 Django system check 均成功。

- P1 / formal 同源冲突：两个 active English horse TermEntry 均为 `Twin Star`，targets 分别为“双子星”“孪生之星”。resolver 当前对同一 span 生成两个 `confirmed_horse` entities，各自携带 target，而非一个无 target 的 ambiguous entity；因此 mapper 存在按顺序任取译名的风险。
- P1 / 目标契约：冲突 span 应合并为一个 `confirmed_horse / needs_preserve=True` entity，`term_id=None`、`target_zh=""`、包含 `ambiguous_formal_horse_name` conflict flag；两个冲突 target 均不得进入 accepted terms 或 generated mapping candidates，生成文本保持 `Twin Star`。
- P1 / 单一 formal 对照：唯一 `Solo Star -> 独星` 在 `Solo Star won at Ascot.` 中仍正确映射为“独星”，该对照 GREEN。
- P2 / 同 span 双告警：pending formal `Brilliant` 与 ExternalHorseAlias 同 span confirmed，译文漏名时当前 issues 同时包含 `external_horse_not_preserved` warning 与 `pending_horse_original_missing` blocker；预期只保留一条正式 pending missing。
- P2 / evidence 与 precedence：entity 已正确合并 formal term ID 和 external horse ID，必须继续保留 external IDs 作为 evidence；recognized source 应为 `formal_pending_term`，不得因附带 external ID 被改写为 `external_alias`。
- P2 / alias-only 对照：仅有 ExternalHorseAlias 且 confirmed occurrence 漏名时仍产生单独 `external_horse_not_preserved`，该对照 GREEN。

测试直接比较 horse issue code 列表，防止 warning signature 或高价值通知层收到同一 occurrence 的重复马名告警。本轮未修改应用代码、迁移、正文提取或清洗规则。

## Reviewer 第十轮实现后的独立 GREEN（2026-07-24）

测试所有者使用项目 `.venv` 与 SQLite 独立复跑第十轮 4 项：

```bash
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_conflicting_formal_horse_targets_remain_ambiguous_and_are_not_mapped \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_single_formal_horse_target_still_maps_generated_strong_occurrence \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_pending_formal_and_external_alias_same_span_emit_only_formal_missing_warning \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_alias_only_confirmed_missing_still_emits_external_warning \
  --noinput -v 2
# 4 tests，OK；Django system check 无问题
```

结果确认：

- `Twin Star` 两个 active formal targets 合并为单一 ambiguous confirmed entity，`term_id=None`、target 为空、needs preserve，且冲突 targets 不进入 accepted terms 或 generated mapping。
- 单一 `Solo Star -> 独星` 在强 generated 语境中仍正常映射。
- pending formal `Brilliant` 与 ExternalAlias 同 span 时 entity 保留 external IDs 作为 evidence，recognized source 为 `formal_pending_term`。
- 漏名只产生一条 `pending_horse_original_missing`，不再附加 `external_horse_not_preserved`。
- alias-only confirmed 漏名仍产生 external warning。

专用模块与相关最小回归：

```bash
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate --noinput -v 1
# 59 tests，OK

DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_english_term_context_gates \
  stable.test_contextual_news_entities \
  stable.tests.TermResolverTests \
  stable.tests.AutomationFlowTests \
  --noinput -v 1
# 130 tests，OK
```

两次回归均通过 Django system check。130 项运行只有既有 `server/staticfiles/` 目录不存在 warning，无测试失败。

## Reviewer 第八轮 findings RED 证据（2026-07-24）

本轮锁定 generated 中文关系的统一 decision，以及 PostgreSQL published-audit evidence lock：

```bash
python3 -m py_compile server/stable/test_external_english_horse_context_gate.py
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_generated_chinese_horse_relations_share_mapping_and_validation_semantics \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_generated_mapping_and_validation_call_the_same_public_occurrence_decision \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_postgres_evidence_lock_covers_exact_tables_and_nonpostgres_is_noop \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_postgres_lock_precedes_final_snapshots_and_article_update_in_atomic \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_postgres_lock_failure_is_fail_closed_before_article_update \
  --noinput -v 2
```

结果：5 tests，11 个目标 assertion failures（其中中文关系参数化产生 7 个 subtest failures），退出码 1；数据库迁移、fixture、语法检查与 Django system check 均成功。

- P1 / mapping 与 validation 漂移：validation 已认可 `Brilliant获胜/赢得比赛/参赛/复出/由...策骑/由...训练/在沙田取胜` 为 confirmed preservation，但 `apply_generated_text_contextual_mappings` 对 7 个 case 全部保持 `Brilliant`，预期映射为“辉煌”。ordinary `Brilliant表现` 对照继续要求不映射。
- P1 / 共享 decision：当前缺少公开 `classify_generated_horse_occurrence`；测试要求 mapper 与 `english_horse_name_has_confirmed_occurrence` 均调用该 helper，并在同文 confirmed + ordinary 两个 occurrence 上累计至少 3 次调用，防止未来再次维护两套中文关系规则。
- P2 / PostgreSQL lock 表集：当前缺少 `_lock_published_audit_evidence_tables`。测试用 fake PostgreSQL connection/cursor 要求执行 `LOCK TABLE`，覆盖 `ExternalHorseAlias`、`ArticleRaceLink`、`RaceEvent`、`RaceEventRunner`、`RaceEventResult` 五张精确表；fake SQLite 必须零 lock SQL，保持非 PostgreSQL 兼容。
- P2 / atomic 顺序：apply 测试要求 evidence lock 在 `transaction.atomic()` 内取得一次，随后才执行 alias/structured final snapshot，且两次 final compare 均早于 `NewsArticle` update；所有探针均断言 `connection.in_atomic_block=True`，事务返回后为 false。
- P2 / lock failure：lock helper 抛出 `DatabaseError` 时必须原样 fail closed，article 的 gate issues、decision reason、warning signature 均保持原值。

既有 snapshot/query-budget 对照另行复跑：

```bash
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_manifest_binds_alias_and_structured_evidence_snapshots \
  --noinput -v 2
# 1 test，OK；包含单篇 dry-run <=35 查询断言
```

测试不连接真实 PostgreSQL、不执行生产写入；锁 SQL 由 fake cursor 检查，apply 顺序由 helper/snapshot mock 与 Django execute wrapper 共同记录。本轮未修改应用代码、迁移、正文提取或清洗规则。

## Reviewer 第八轮实现后的精确 GREEN（2026-07-24）

`PublishedEnglishHorseAuditOnlyTests` 继承 Django `TestCase`，测试方法本身已处于外层 atomic。锁顺序测试因此改为记录调用前 `connection.atomic_blocks` 深度，要求 lock、final snapshots 与 article update 均位于更深的 apply 内层 atomic，并断言 apply 返回后恢复原深度；未降低锁表、顺序或失败零更新契约。

```bash
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_generated_chinese_horse_relations_share_mapping_and_validation_semantics \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_generated_mapping_and_validation_call_the_same_public_occurrence_decision \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_postgres_evidence_lock_covers_exact_tables_and_nonpostgres_is_noop \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_postgres_lock_precedes_final_snapshots_and_article_update_in_atomic \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_postgres_lock_failure_is_fail_closed_before_article_update \
  --noinput -v 2
# 5 tests，OK；Django system check 无问题
```

## Reviewer 第九轮 findings RED 证据（2026-07-24）

本轮锁定 published-audit effective enforce 模式，以及 validation 的其余数据库依赖：

```bash
python3 -m py_compile server/stable/test_external_english_horse_context_gate.py
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_uses_and_binds_effective_enforce_mode_when_global_is_off \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_uses_enforce_under_shadow_and_rejects_configured_mode_drift \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_manifest_binds_alias_and_structured_evidence_snapshots \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_apply_fails_closed_on_article_horse_link_snapshot_drift \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_apply_fails_closed_on_related_region_snapshot_drift \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_apply_fails_closed_on_duplicate_corpus_snapshot_drift \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_postgres_evidence_lock_covers_exact_tables_and_nonpostgres_is_noop \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_postgres_lock_precedes_final_snapshots_and_article_update_in_atomic \
  --noinput -v 2
```

结果：8 tests，5 assertion failures、3 个缺失契约字段/helper errors，退出码 1；数据库迁移、fixture、语法检查与 Django system check 均成功。

- P1 / global off：在 `ENGLISH_TERM_CONTEXT_MODE=off` 下，published audit 对 article 9595 等价正文重新产生 12 条 legacy `pending_horse_original_missing` blocker，证明 dry-run 未按 audit 固定的 effective enforce 规则评估。
- P1 / 可审计 mode：prepared/result/selectors/manifest 当前缺少 `configured_rule_mode`、`effective_rule_mode` 与 `effective_settings.ENGLISH_TERM_CONTEXT_MODE=enforce`。测试要求 global off/shadow 均显式记录 configured mode，但 audit effective mode 固定 enforce。
- P1 / apply settings drift：shadow 准备后切换 global mode 为 off，apply 必须因 configured/effective settings snapshot 漂移 fail closed；同一 configured mode 下 apply 必须复用 enforce outcome，禁止提交 legacy issues。
- P2 / snapshot contract：prepared/result/manifest 当前缺少 `article_horse_link_snapshot_sha256`、`related_region_snapshot_sha256`、`duplicate_corpus_snapshot_sha256`。既有 dry-run `<=35` 查询断言在访问新字段前已通过。
- P2 / ArticleHorseLink drift：相关 HorseProfile/Term 在 dry-run 前已存在，dry-run 后仅新增 active ArticleHorseLink；apply 未 fail closed，排除了 term snapshot 偶然代替 horse-link dependency 的可能。
- P2 / related region drift：dry-run 后新增目标文章的 `NewsArticleRelatedRegion`，apply 未 fail closed，且测试要求 article gate fields 零更新。
- P2 / duplicate corpus drift：dry-run 后新增一篇内容完全无关但进入 duplicate corpus 的 published NewsArticle，validation outcome 不变时 apply 仍继续提交；测试要求独立 corpus snapshot 捕获 phantom。
- P2 / PostgreSQL 锁表：现有 evidence lock SQL 未覆盖 `ArticleHorseLink`、`NewsArticleRelatedRegion`、`NewsArticle`。顺序测试还要求新增三类 final snapshot 与 alias/structured snapshots 一样，在 apply 内层 atomic、lock 之后、目标 article update 之前完成；当前对应 helper 均缺失。

测试使用 outcome 不变 fixture，明确区分 dependency snapshot 与 outcome hash；HorseProfile term 在 prepare 前创建，避免 term drift。fake PostgreSQL 不进行真实写入，SQLite no-op 兼容断言继续保留。本轮未修改应用代码、迁移、正文提取或清洗规则。

## Reviewer 第九轮实现后的独立 GREEN（2026-07-24）

测试所有者使用项目 `.venv` 与 SQLite 独立复跑第九轮 8 项：

```bash
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_uses_and_binds_effective_enforce_mode_when_global_is_off \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_uses_enforce_under_shadow_and_rejects_configured_mode_drift \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_manifest_binds_alias_and_structured_evidence_snapshots \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_apply_fails_closed_on_article_horse_link_snapshot_drift \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_apply_fails_closed_on_related_region_snapshot_drift \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_apply_fails_closed_on_duplicate_corpus_snapshot_drift \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_postgres_evidence_lock_covers_exact_tables_and_nonpostgres_is_noop \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_postgres_lock_precedes_final_snapshots_and_article_update_in_atomic \
  --noinput -v 2
# 8 tests，OK；Django system check 无问题
```

结果确认：

- global off 下 article 9595 等价正文按 effective enforce 评估，不再生成 13 个普通词马名告警；global shadow 同样使用 enforce。
- prepared、selectors、result payload、manifest 与 effective settings 均审计 configured/effective mode；configured mode 漂移时 apply fail closed。
- `article_horse_link_snapshot_sha256`、`related_region_snapshot_sha256`、`duplicate_corpus_snapshot_sha256` 与既有 alias/structured hashes 一起绑定 prepared/result/manifest。
- dry-run 后新增 ArticleHorseLink、related region 或 duplicate corpus row 均触发 apply drift，文章 gate fields 零更新。
- fake PostgreSQL lock SQL 覆盖 8 张依赖表：NewsArticle、NewsArticleRelatedRegion、ArticleHorseLink、ExternalHorseAlias、ArticleRaceLink、RaceEvent、RaceEventRunner、RaceEventResult；SQLite 仍为 no-op。
- 五类 final snapshots 均在 apply 内层 atomic 中、lock 之后、目标 article update 之前完成。
- manifest binding 测试中的单篇 dry-run 查询预算继续 `<=35`。

专用模块与相关最小回归：

```bash
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate --noinput -v 1
# 55 tests，OK

DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_english_term_context_gates \
  stable.test_term_gate_reprocessing \
  stable.tests.TermResolverTests \
  stable.tests.AutomationFlowTests \
  --noinput -v 1
# 118 tests，OK
```

两次回归均通过 Django system check。118 项运行只有既有 `server/staticfiles/` 目录不存在 warning，无测试失败。

最终静态验证：

```bash
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py check
# System check identified no issues (0 silenced).

git diff --check
# 退出码 0，无输出
```

## Reviewer 第六轮 findings RED 证据（2026-07-24）

本轮直接覆盖 TranslationWorkflow/provider result 后处理与 reprocessing 自身的 runner/result SQL：

```bash
python3 -m py_compile server/stable/test_external_english_horse_context_gate.py
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_translation_workflow_does_not_map_reordered_ordinary_occurrence_by_source_ordinal \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_translation_workflow_maps_only_generated_occurrence_with_its_own_horse_context \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_validation_rejects_formal_horse_preservation_by_ordinary_generated_occurrence \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_translation_workflow_pending_placeholder_remains_occurrence_safe_after_reordering \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_reprocessing_runner_and_result_queries_are_scoped_to_english_article_ids \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_reprocessing_pure_non_english_batch_avoids_runner_and_result_queries \
  --noinput -v 1
```

结果：6 tests，4 assertion failures、2 个安全对照通过，退出码 1；数据库迁移、fixture、语法检查与 Django system check 均成功。

- P1 / TranslationWorkflow ordinary 重排：source 第一处为 confirmed `Brilliant won...`，后一处为 ordinary `Brilliant performance`；mock provider 只输出且把 ordinary occurrence 放在首位。实际 result 被 source ordinal 错误映射为 `辉煌 performance`，预期保持 `Brilliant performance`。
- P1 / validation 防冒充：正式马名 source 有 confirmed occurrence，target 只保留普通 `Brilliant performance` 且正文长度合法。实际 validation issues 为空，预期产生 `core_term_missing` 或 `background_term_missing`；失败直接来自纯 surface contains 仍把 ordinary occurrence 当作真实马名已保留。
- P1 / 安全对照：provider 生成文本自身含 `Brilliant won...` 与 ordinary `Brilliant performance` 时，当前已只映射前者；pending `__UMA_KEEP_1__` 重排后也只恢复 confirmed occurrence，ordinary 保持不变。两项均 GREEN，修复不得回退。
- P2 / mixed batch SQL：`RaceEventRunner` 查询已只包含 English article ID，但 `RaceEventResult` SQL 仍为 `article_id IN (japanese.id, english.id)`，直接证明 reprocessing result 分支未使用 `english_article_ids`。
- P2 / pure non-English SQL：runner 查询已被空集合消除，但仍实际执行一条 `stable_raceeventresult` 查询；预期 runner/result 均零查询。

SQL 测试为日文、英文文章分别建立 active article-race link、runner 与 result，直接解析捕获 SQL 的 `article_id IN (...)`，未仅依赖 terms loader mock。既有英文查询预算仍由专用批量 query-count 回归锁定。本轮未修改应用代码、迁移、正文提取或清洗规则。

## Reviewer 第六轮实现后的独立 GREEN（2026-07-24）

测试所有者使用项目 `.venv` 与 SQLite 独立复跑第六轮 6 项：

```bash
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_translation_workflow_does_not_map_reordered_ordinary_occurrence_by_source_ordinal \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_translation_workflow_maps_only_generated_occurrence_with_its_own_horse_context \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_validation_rejects_formal_horse_preservation_by_ordinary_generated_occurrence \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_translation_workflow_pending_placeholder_remains_occurrence_safe_after_reordering \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_reprocessing_runner_and_result_queries_are_scoped_to_english_article_ids \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_reprocessing_pure_non_english_batch_avoids_runner_and_result_queries \
  --noinput -v 2
# 6 tests，OK；Django system check 无问题
```

结果确认：

- TranslationWorkflow 不再按 source ordinal 映射 provider generated output；只剩 ordinary `Brilliant performance` 时保持原文，不改成“辉煌”。
- generated output 自身含可证明 `Brilliant won...` 时只映射该 occurrence，ordinary occurrence 保持不变。
- validation 不再允许正式马名以 target ordinary 同形词冒充 confirmed preservation。
- pending KEEP placeholder 在 provider 重排后仍只恢复 confirmed occurrence，不污染 ordinary occurrence。
- mixed Japanese + English reprocessing 中 runner/result SQL 均只查询 English article IDs。
- pure non-English reprocessing 不执行 runner 或 result 查询。

专用模块与相关最小回归：

```bash
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate --noinput -v 1
# 39 tests，OK

DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_english_term_context_gates \
  stable.test_term_gate_reprocessing \
  stable.tests.TermResolverTests \
  stable.tests.TranslationWorkflowTests \
  stable.tests.AutomationFlowTests \
  --noinput -v 1
# 132 tests，OK
```

两次回归均通过 Django system check。132 项运行只有既有 `server/staticfiles/` 目录不存在 warning，无测试失败。

## 第十七轮 P1/P2 测试先行 RED（2026-07-24）

本轮只新增测试与文档，不修改应用代码。目标集：

```bash
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_off_and_shadow_keep_complete_legacy_gate_semantics_when_v2_calls_match_uncertain \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_enforce_uses_occurrence_classification_for_same_uncertain_machine_link_fixture \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_non_english_article_resolvers_keep_raw_translation_source_coordinates \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_english_article_resolvers_keep_visible_clean_coordinates \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_japanese_raw_coordinates_drive_format_and_seed_placeholder_plans \
  --noinput -v 2
```

结果：5 tests，其中 2 项对照 GREEN、3 项测试共 5 个 assertion failure，退出码 1。测试数据库迁移、fixture、语法、Django system check 均正常，属于目标能力尚未实现导致的真实 RED。

- P1 / off 与 shadow 完整 legacy semantics：以 translated `Brilliant`、accepted `Ascot` 及 AUTO/CANDIDATE machine link 为代表，先取得 legacy common-word baseline，再 mock article resolver 将同 occurrence 改为 `uncertain`。当前 off/shadow 的 `machine_entity_type_mismatch` 被 occurrence resolution 绕过，outcome 从 blocker/failed 错变为 warning/passed；测试要求 outcome、reason、issues、blockers、accepted IDs 及 mismatch 与 baseline 完全相等。shadow 仍须额外记录 would-change/classifications，但不得改变 gate。
- P1 / enforce 对照：相同 fixture 在 enforce 下允许 `uncertain` 只进入 info audit、不产生 machine mismatch，且 accepted IDs 只含正式 race term；当前 GREEN，证明 RED 并非 fixture 或 link 无效。
- P1 / published audit 局部例外：沿用已有 `test_published_audit_uses_and_binds_effective_enforce_mode_when_global_is_off` 与 `test_published_audit_uses_enforce_under_shadow_and_rejects_configured_mode_drift`，published exact-ID audit 在 global off/shadow 下仍固定 effective enforce，不应跟随一般实时 gate 的 legacy 分支。
- P2 / language coordinate policy：日文与繁中 article 的 `body_normalized=""`、raw 含 `<nav>/<p>/<aside>` 三次正式术语 occurrence。当前 single/batch resolver 只保留 clean 后的一个 occurrence，span 分别错误为 `[0,3]` / `[0,6]`；测试要求三次 occurrence 全部按实际 translation raw source 的精确位置返回。不得通过修改提取或清洗规则修复。
- P2 / English 对照：相同 HTML 结构的 English article 继续使用 visible-clean 语义，只识别 `<p>` 中 occurrence，span `[0,5]`；当前 GREEN。
- P2 / Japanese format + seed：raw 中 `永森大智騎手(ザガラ＝1着)` 及 nav/p/aside 三处 seeded `レコード`。当前 horse entity span 为 clean 坐标 `[7,10]`，而 raw 正确坐标为 `[27,30]`，导致 format/seed plan 的 entity consumption 坐标不可信；测试锁定 interview format target 为 `永森大智骑手(1着 萨加拉)`，三处 seed placeholder 的 start/end 必须可直接切回 raw `レコード`。

实现边界：`resolve_article_entities_for_articles` 必须按 `source_language` 选择输入表示——仅 English 使用 visible-clean，Japanese、Traditional Chinese 等非 English 使用 `title_ja` 与 `body_ja_normalized or body_ja_raw` 的实际 translation source。不得改新闻 HTML 抓取、正文提取器或正文清洗规则。

## 第十七轮实现后的独立 GREEN（2026-07-24）

测试所有者使用项目 `.venv` 与 SQLite 独立复跑第十七轮 5 项：

```bash
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_off_and_shadow_keep_complete_legacy_gate_semantics_when_v2_calls_match_uncertain \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_enforce_uses_occurrence_classification_for_same_uncertain_machine_link_fixture \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_non_english_article_resolvers_keep_raw_translation_source_coordinates \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_english_article_resolvers_keep_visible_clean_coordinates \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_japanese_raw_coordinates_drive_format_and_seed_placeholder_plans \
  --noinput -v 2
# 5 tests，OK；Django system check 无问题
```

结果确认：

- off/shadow 在同一弱英文 horse occurrence 被 mock resolver 判为 `uncertain` 时，outcome、reason、issues、blockers、accepted IDs 与 `machine_entity_type_mismatch` 均保持 legacy baseline；AUTO/CANDIDATE link 不再绕过 blocker。
- shadow 只追加 occurrence would-change/classifications 审计，不改 gate；enforce 相同 fixture 继续 `uncertain` info-only、不产生 mismatch，三类判定边界未回退。
- Japanese 与 Traditional Chinese single/batch resolver 均保留 raw 中 nav/p/aside 三处 occurrence，并返回可直接切回实际 translation source 的精确 span。
- English HTML 对照继续只识别 visible-clean `<p>` occurrence，span `[0,5]`。
- Japanese interview format 正确得到 `永森大智骑手(1着 萨加拉)`；nav/p/aside 三处 seeded `レコード` 均生成精确 raw start/end 与 target `记录`。

published audit 局部 effective-enforce、语言与 contextual 回归：

```bash
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_uses_and_binds_effective_enforce_mode_when_global_is_off \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_uses_enforce_under_shadow_and_rejects_configured_mode_drift \
  stable.test_contextual_news_entities \
  stable.test_japanese_racing_translation_normalization \
  --noinput -v 1
# 102 tests，OK；Django system check 无问题
```

完整专用模块与相关最小矩阵：

```bash
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate --noinput -v 1
# 91 tests，OK

DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_english_term_context_gates \
  stable.test_term_gate_reprocessing \
  stable.tests.TermResolverTests \
  stable.tests.TranslationWorkflowTests \
  stable.tests.AutomationFlowTests \
  --noinput -v 1
# 132 tests，OK

DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py check
# System check identified no issues
```

所有回归均通过。132 项运行只有既有 `server/staticfiles/` 目录不存在 warning，无测试失败。专用模块中的 article-aware batch query budget 继续通过；本轮未修改新闻 HTML 抓取、正文提取器或正文清洗规则。

## Reviewer 最终两项 finding：RED、修复策略与独立 GREEN（2026-07-24）

最新只读 reviewer 提出两项 actionable finding。测试所有者先只修改专用测试，取得真实 RED：

```bash
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_nested_confirmed_external_aliases_protect_only_longest_complete_horse_name \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_discovery_uses_confirmed_occurrence_field_span_context_instead_of_title_membership \
  --noinput -v 2
# 2 tests，2 assertion failures，退出码 1；Django system check 无问题
```

RED 证据：

- 嵌套 confirmed alias：`International Star won...` 同时命中 `International Star` 与内层 `Star`。当前 metadata 错误产生 `KEEP_1=International Star`、`KEEP_2=Star` 两个 placeholder，实际 prompt 由短 alias 抢占内层 span；预期 longest-overlap-first，只保留并完整保护 `International Star`。
- Discovery occurrence 归属：标题为 ordinary `Brilliant business outlook`、正文为 confirmed `Brilliant won...` 时，finding 实际为 `source_field=title_ja`、空 span、标题 context、无 classification；预期记录正文 `body_ja_normalized`、span `[0,9]`、正文 occurrence context 与 `confirmed_horse`。失败直接证明 `matched_text in title` 会错归字段。

实现采用的窄修复：

- placeholder 选择按 occurrence 长度优先并做全字段 non-overlap；只有被选中的完整 occurrence 对应 placeholder 留在共享映射中，再按 raw span 替换。短 alias 不再抢占长 alias，也不留下未使用的审计项；恢复后正文仍精确为 `International Star won at Ascot under Ryan Moore.`。
- `recognized_horses_from_resolution()` 产出的 occurrence metadata 成为 discovery 唯一定位依据；finding 直接携带 `source_field`、`matched_span`、`matched_context`、`classification` 与 external horse IDs，不再用标题字符串包含关系反推字段。

应用修复后，未参与实现的测试所有者复跑同一命令：

```text
2 tests，OK；Django system check 无问题
```

### 当前去重完整矩阵

使用一个 Django test 命令合并所有 selector，由 runner 自身去重并报告实际收集数：

```bash
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate \
  stable.test_english_term_context_gates \
  stable.test_contextual_news_entities \
  stable.test_term_gate_reprocessing \
  stable.test_japanese_racing_translation_normalization \
  stable.tests.TermResolverTests \
  stable.tests.TranslationWorkflowTests \
  stable.tests.AutomationFlowTests \
  --noinput -v 1
# Found 325 test(s)；Ran 325 tests；OK
```

当前准确总数是 325，不是旧口径 316 或机械加两项后的 318。按互不重叠的当前 selector 拆分为：专用模块 93、contextual 52、日文 normalization 48、其余相关矩阵 132，共 325。全部通过；仅出现既有 `server/staticfiles/` 目录不存在 warning。

### 日文、繁中、正式中文术语回归

```bash
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_japanese_racing_translation_normalization \
  stable.test_contextual_news_entities.FormalLanguageEntityResolutionTests.test_traditional_chinese_horse_term_uses_formal_resolution \
  stable.tests.TermResolverTests \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_non_english_article_resolvers_keep_raw_translation_source_coordinates \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_japanese_raw_coordinates_drive_format_and_seed_placeholder_plans \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_generated_chinese_horse_relations_share_mapping_and_validation_semantics \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_pending_alias_validation_accepts_chinese_result_relations_but_not_ordinary_phrases \
  --noinput -v 1
# Found 77 test(s)；Ran 77 tests；OK
```

确认日文 raw coordinates/format/seed、繁中 formal resolution、多语言 TermResolver 和正式中文 horse relation 均无无关变化。

### 批量一致性与性能边界

```bash
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_article_aware_live_batch_and_discovery_share_resolution \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_live_and_reprocessing_batch_share_visible_text_and_ignore_hidden_aliases \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_reprocessing_runner_and_result_queries_are_scoped_to_english_article_ids \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_reprocessing_pure_non_english_batch_avoids_runner_and_result_queries \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_article_aware_batch_query_count_is_bounded \
  --noinput -v 2
# 5 tests，OK
```

实时、batch、reprocessing 与 discovery resolution 保持一致；mixed batch 的 runner/result 查询只含 English IDs，pure non-English 为零；10 篇与 20 篇 resolver 查询数相等且 10 篇不超过 8 次，未引入 N+1。

静态验证：

```bash
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py check
python3 -m py_compile <本 change 所有修改的 Python 文件>
git diff --check
# 全部通过
```

diff 范围复核：未修改 `AGENTS.md`、全局 `current_state/project_status/project_overview/decisions/deploy_runbook`，未触碰 source adapter、新闻 HTML 抓取或正文提取器。visible-source helper 是把 validation 既有 `script/style/nav/aside + strip_tags + whitespace` 表示迁移为共享函数，并按语言选择 resolver 输入；未扩充或改变 HTML 清洗标签/规则。

本轮仅完成 finding 修复后的本地独立验证；代码 fingerprint 已变化，必须重新进入同一 reviewer 会话复审。复审成功后仍须取得用户针对当前版本的明确发布授权。当前禁止 commit、push、PR、merge、部署、历史重处理和生产写入。

## Reviewer P1：structured evidence occurrence-local 修复（2026-07-24）

同一 reviewer 会话继续指出：runner/result 的结构化 horse identity 以 surface key 加载后，仍可能把同一文章内所有同形 occurrence 一并升级为马名。测试所有者先新增一个最小 fixture：

- AUTO-linked event 同时具有 `RaceEventRunner.horse_name=Brilliant` 与 `RaceEventResult.horse_name=Brilliant`；
- 正文 occurrence 1：`Brilliant won at Ascot.`，span `[0,9]`，强赛马关系；
- 正文 occurrence 2：`Brilliant Result Announced...`，span `[24,33]`，仅 lexical index 命中，既非 strong 也非 ordinary seed；
- 要求 live、batch、reprocessing 三路径 payload 完全一致；第一处 confirmed/preserve 并携带精确 runner/result evidence，第二处 uncertain/no-preserve、不得携带 race evidence，也不得新增高价值 horse preserve warning。

测试先行命令：

```bash
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_structured_surface_evidence_does_not_confirm_lexical_only_same_article_occurrence \
  --noinput -v 2
```

真实 RED：第二处实际为 `confirmed_horse / needs_preserve=True`，reason=`structured_race_entity`，并错误携带相同 `race_runner` 与 `race_result` evidence；1 test、1 assertion failure、退出码 1。数据库、fixture、语法和 Django system check 均正常。

窄修复策略：

- resolver 先按 normalized surface 统计当前 article 的 occurrence 数量；
- 结构化 identity 只有在该 surface 全文唯一时，才可单独作为 `structured_race_entity` 的确认依据；
- surface 有多个 occurrence 时，每一处必须由自身 strong/local race relation 决定分类；只有已由 occurrence-local 语境 confirmed 的 occurrence 才附加 runner/result evidence；
- 不删除结构化 evidence、不新增停用词，也不改变 ordinary/common 与 non-English 规则。

未参与应用实现的测试所有者复跑同一目标：

```text
1 test，OK；Django system check 无问题
```

结果确认：`[0,9]` 保持 confirmed/preserve 并携带两类精确 evidence；`[24,33]` 为 uncertain/no-preserve、无 race evidence；live、batch、reprocessing 一致，preservable `Brilliant` 仅一处。

### 最新完整与专项验证

```bash
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate \
  stable.test_english_term_context_gates \
  stable.test_contextual_news_entities \
  stable.test_term_gate_reprocessing \
  stable.test_japanese_racing_translation_normalization \
  stable.tests.TermResolverTests \
  stable.tests.TranslationWorkflowTests \
  stable.tests.AutomationFlowTests \
  --noinput -v 1
# Found 326 test(s)；Ran 326 tests；OK
```

当前 Django 去重后的准确总数为 326（专用模块由 93 增至 94，其余 selector 不变）；全部通过，仅有既有 staticfiles warning。

日文、繁中、正式中文术语专项原命令复跑：77 tests，OK。确认 Japanese raw coordinate/format/seed、Traditional Chinese formal resolution、TermResolver 与 generated Chinese horse relation 均无行为变化。

一致性与性能边界：

```bash
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_structured_surface_evidence_does_not_confirm_lexical_only_same_article_occurrence \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_structured_horse_evidence_is_scoped_to_the_actual_occurrence \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_article_aware_live_batch_and_discovery_share_resolution \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_live_and_reprocessing_batch_share_visible_text_and_ignore_hidden_aliases \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_reprocessing_runner_and_result_queries_are_scoped_to_english_article_ids \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_reprocessing_pure_non_english_batch_avoids_runner_and_result_queries \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_article_aware_batch_query_count_is_bounded \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_manifest_binds_alias_and_structured_evidence_snapshots \
  --noinput -v 2
# 8 tests，OK
```

确认 live/batch/reprocessing occurrence payload 一致、English runner/result 查询 scope 正确、pure non-English 零查询、10/20 篇 query count 恒定且 `<=8`、published-audit 单篇 dry-run 继续 `<=35`，未引入 N+1。

`manage.py check`、本 change 相关 Python `py_compile`、`git diff --check` 均通过。diff 未触碰 `AGENTS.md`、全局状态文档、source adapters、HTML extraction 或正文提取器；共享 visible-source helper 仍为此前 validation 既有规则的迁移，没有新增清洗标签或规则。

本轮修复再次改变代码 fingerprint。当前仍须由同一 reviewer 会话对新 fingerprint 给出 `APPROVED`，随后还须取得用户针对该 fingerprint 的明确发布授权；发布继续冻结，禁止 commit、push、PR、merge、部署、历史重处理和生产写入。

## Reviewer 两项 P2：committed replay identity 与 query telemetry（2026-07-24）

Reviewer 继续提出两项 P2。测试所有者先只新增专用测试：

1. Published-audit run 已 committed 后，同 operator replay 若显式传入不同 `reviewer_identity`，必须拒绝；同 reviewer 才返回 `already_committed`。
2. English + Japanese mixed batch 必须让 performance telemetry 反映 `_build_article_entity_index()` 的实际 per-language SQL 构建计划，并验证 2 篇与 20 篇 query 数相等。

测试先行命令：

```bash
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_mixed_language_batch_telemetry_counts_actual_entity_index_queries_without_n_plus_one \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_committed_replay_binds_explicit_reviewer_identity \
  --noinput -v 2
```

真实 RED：2 tests、2 failures、退出码 1。

- committed replay：same operator + explicit different reviewer 未抛 `ValueError`，错误直接返回 committed receipt。
- mixed telemetry：实际 SQL 对 English/Japanese 两个 bucket 各执行一次 `ExternalHorseAlias`，合计 2；telemetry 仍固定上报 `horse_alias_prefetch_count=1`。同一测试继续锁定 entity index 的 TermAlias + TermEntry 为每 bucket 2 次、mixed 合计 `horse_term_prefetch_count=4`，以及 20 篇不得比 2 篇增加查询。

窄修复：

- committed receipt replay 在返回幂等结果前，同时校验 selectors 中 prepared reviewer、result payload 中 committed receipt reviewer 与显式 supplied reviewer；任何 binding/mismatch 均 fail closed。同 reviewer 仍保持零写幂等。
- batch context 根据实际具有 entity candidate keys 的 source-language bucket 数生成 telemetry：每 bucket 计 1 次 ExternalHorseAlias、1 次 TermAlias、1 次 TermEntry；`horse_term_prefetch_count=2 * bucket_count`，`entity_prefetch_count` 继续为 race + alias + horse-term 的真实和。计数不按 article 数增长。

应用修复后，两项目标同命令：2 tests，OK。

### 100 篇旧 query-budget 契约校准

旧 performance 测试仍假定统一 resolver 建索引不查询 horse terms：

```text
实际 horse_term_prefetch_count=2，旧期望=0
```

英文单 bucket 的实际 `_build_article_entity_index()` 计划为：

- ExternalHorseAlias：1
- TermAlias + TermEntry：2
- runner/result：2
- `entity_prefetch_count`：`2 + 1 + 2 = 5`

因此只更新陈旧 telemetry 断言：

```diff
- horse_term_prefetch_count == 0
- entity_prefetch_count == 3
+ horse_term_prefetch_count == 2
+ entity_prefetch_count == 5
```

`sql_query_count <= 35` 总预算、100 篇 candidate count、单次 index build、duplicate corpus prefetch 与 RSS 断言均未放宽。更新后：

```bash
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_term_gate_reprocessing.TermGateReprocessContractTests.test_one_hundred_article_dry_run_stays_within_query_budget \
  --noinput -v 2
# 1 test，OK
```

### 独立完整验证

当前合并 selector 由 Django 实际去重收集：

```text
Found 328 test(s)
Ran 328 tests
OK
```

当前拆分为专用模块 96、contextual 52、Japanese normalization 48、其余 related matrix 132。仅有既有 staticfiles warning。

日文、繁中、正式中文术语专项：77 tests，OK。

Published-audit identity/idempotency/security、2/20 mixed telemetry/N+1 与 100 篇 budget 合并回归：

```bash
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_apply_replay_is_idempotent_and_does_not_touch_side_effects \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_committed_replay_binds_explicit_reviewer_identity \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_apply_locks_run_and_rejects_non_succeeded_first_apply \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_requires_exact_ids_manifest_and_confirmation \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_service_requires_and_binds_normalized_identities \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_apply_requires_matching_prepared_operator \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_mixed_language_batch_telemetry_counts_actual_entity_index_queries_without_n_plus_one \
  stable.test_term_gate_reprocessing.TermGateReprocessContractTests.test_one_hundred_article_dry_run_stays_within_query_budget \
  --noinput -v 2
# 8 tests，OK
```

`manage.py check`、本 change 所有相关 Python `py_compile`、`git diff --check` 均通过。diff 未触碰 `AGENTS.md`、全局状态文档、source adapters、HTML extraction 或正文提取器；未改变 visible-source 清洗规则。

两项 P2 修复及测试契约更新再次改变 fingerprint。必须复用同一 reviewer 会话对当前 fingerprint 取得 `APPROVED`，随后仍需用户明确发布授权；当前继续禁止 commit、push、PR、merge、部署、历史重处理和生产写入。

## 第十六轮扩大验证回归 RED（2026-07-24）

独立 verification 发现旧 contextual regression 后，测试所有者先复跑原测试，再新增专用 Grace Hamilton/Hamilton fixture，并保留第十六轮 uncertain + machine link 对照：

```bash
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_contextual_news_entities.MachineTagsLinksAndValidationTests.test_validation_reports_horse_candidate_suppressed_inside_person_span \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_person_span_suppressed_horse_candidate_is_explicitly_rejected_for_machine_tag \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_uncertain_horse_occurrence_with_machine_link_is_audit_only \
  --noinput -v 2
```

结果：3 tests，1 IndexError、1 assertion failure、1 GREEN，退出码 1；测试数据库迁移、fixture、语法检查与 Django system check 均成功。

- 旧回归：`test_validation_reports_horse_candidate_suppressed_inside_person_span` 稳定因 mismatch 列表为空而 `IndexError`，并非环境或 fixture 错误。
- 专用 fixture：formal horse `Hamilton -> 汉密尔顿` 在 `Grace Hamilton joins...` / person-role context 中确实进入 `suppressed_candidates`，term ID 正确且 conflict flag 明确包含 `inside_person_span`；但 stale machine tag `汉密尔顿` 未产生 `machine_entity_type_mismatch`。
- 根因边界：第十六轮修复把所有 ambiguous/uncertain 排除时，也要求 suppressed candidate 必须 `classification=common_word`。person-span suppression 是结构性明确 rejected candidate，classification 当前为空，因此被误排除。
- 安全对照：普通 lexical uncertain `Brilliant Result` + AUTO/CANDIDATE link 仍为 info-only，当前 GREEN。修复必须仅恢复带 `inside_person_span` / `inside_longer_entity` / `inside_common_word_span` 的明确 suppressed candidates，不能把一般 uncertain occurrence 重新纳入 mismatch。

本轮未修改应用代码、配置、迁移、正文提取、正文清洗或来源适配器。

## 第十六轮扩大验证回归修复后的独立 GREEN（2026-07-24）

测试所有者使用项目 `.venv` 与 SQLite 独立复跑旧回归、新增专用 fixture 和 uncertain 安全对照：

```bash
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_contextual_news_entities.MachineTagsLinksAndValidationTests.test_validation_reports_horse_candidate_suppressed_inside_person_span \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_person_span_suppressed_horse_candidate_is_explicitly_rejected_for_machine_tag \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_uncertain_horse_occurrence_with_machine_link_is_audit_only \
  --noinput -v 2
# 3 tests，OK；Django system check 无问题
```

结果确认：

- `Grace Hamilton` person span 内被 suppress 的 `Hamilton -> 汉密尔顿` horse candidate 继续带 `inside_person_span` conflict，并作为明确 rejected candidate 触发 stale machine tag mismatch。
- 原 contextual 回归不再因 mismatch 为空而 IndexError。
- 普通 lexical uncertain `Brilliant Result` + AUTO/CANDIDATE link 仍只产生 info audit，不触发 mismatch；修复未恢复一般 ambiguous/uncertain entity。

扩大回归：

```bash
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_contextual_news_entities --noinput -v 1
# 52 tests，OK

DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate --noinput -v 1
# 86 tests，OK

DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_english_term_context_gates \
  stable.test_term_gate_reprocessing \
  stable.tests.TermResolverTests \
  stable.tests.TranslationWorkflowTests \
  stable.tests.AutomationFlowTests \
  --noinput -v 1
# 132 tests，OK
```

三次回归均通过 Django system check。132 项运行只有既有 `server/staticfiles/` 目录不存在 warning，无测试失败。

## Reviewer 第十五轮 findings RED 证据（2026-07-24）

本轮锁定 bare `is strong` 不得作为马名证据，以及 published-audit apply 的 PostgreSQL term table-level lock 接入与事务顺序：

```bash
python3 -m py_compile server/stable/test_external_english_horse_context_gate.py
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_pending_and_alias_bare_is_strong_are_not_horse_context_but_win_is_confirmed \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_translated_formal_bare_is_strong_is_not_horse_context \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_postgres_term_lock_covers_exact_tables_and_nonpostgres_is_noop \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_term_lock_precedes_final_context_and_article_update_in_atomic \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_term_lock_failure_is_zero_update \
  --noinput -v 2
```

结果：5 tests，4 assertion failures、1 GREEN，退出码 1；测试数据库迁移、fixture、语法检查与 Django system check 均成功。

- P2 / bare relation：pending formal + alias 的 `Work is strong across the team` 以及已译 formal 的相同 occurrence 当前均被 `strong_horse_context` 升为 `confirmed_horse`；`Work is strong.` 同属待锁定负例。测试要求 common/uncertain、无 preserve 与 horse warning。
- P2 / strong control：同一 pending + alias identity 的 `Work won at Ascot` 必须继续 `confirmed_horse / needs_preserve=True`，证明仅移除 bare `is strong` 证据，不削弱合法赛马关系。
- P1 / term lock SQL：既有 `_lock_term_snapshot_tables` 已正确对 `TermEntry`、`TermAlias` 执行单条 `LOCK TABLE ... IN SHARE MODE`，且 SQLite no-op，本项当前 GREEN。
- P1 / apply wiring/order：published-audit apply 当前事件为 `evidence_lock -> final_term_context -> article_update`，完全没有调用 term table lock。测试要求同一 atomic 内固定为 `evidence_lock -> term_lock -> final_term_context/snapshot -> article_update`。
- P1 / lock failure：mock term table lock 抛出 `DatabaseError` 当前未被调用，apply 继续更新 article。测试要求 failure fail closed，NewsArticle 零 UPDATE，gate state 不变，run 保持 `succeeded` 且 result 无 `updated_article_ids`。

既有 dry-run 单篇 `<=35` 查询预算继续由 published-audit manifest binding 测试锁定；本轮不增加逐别名/逐术语查询。本轮未修改应用代码、配置、迁移、正文提取、正文清洗或来源适配器。

## Reviewer 第十五轮实现后的独立 GREEN（2026-07-24）

测试所有者使用项目 `.venv` 与 SQLite 独立复跑第十五轮 5 项：

```bash
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_pending_and_alias_bare_is_strong_are_not_horse_context_but_win_is_confirmed \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_translated_formal_bare_is_strong_is_not_horse_context \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_postgres_term_lock_covers_exact_tables_and_nonpostgres_is_noop \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_term_lock_precedes_final_context_and_article_update_in_atomic \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_term_lock_failure_is_zero_update \
  --noinput -v 2
# 5 tests，OK；Django system check 无问题
```

结果确认：

- pending formal + alias 与 translated formal 的 `Work is strong across the team` / `Work is strong.` 均降为 common 或 uncertain，不产生 preserve、horse warning 或 term missing。
- `Work won at Ascot` 仍为 `confirmed_horse / needs_preserve=True`，bare strong 收窄未削弱合法赛马关系。
- PostgreSQL term snapshot helper 精确锁定 `TermEntry + TermAlias`，使用 SHARE mode；SQLite 保持 no-op。
- published-audit apply 在同一 atomic 内固定执行 `8表 evidence lock -> term table lock -> final term context/snapshot -> article update`。
- term table lock 抛出 `DatabaseError` 时无 NewsArticle UPDATE，gate state 不变，run 保持 `succeeded` 且 result 无提交字段。

专用模块与相关最小回归：

```bash
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate --noinput -v 1
# 80 tests，OK

DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_english_term_context_gates \
  stable.test_term_gate_reprocessing \
  stable.tests.TermResolverTests \
  stable.tests.TranslationWorkflowTests \
  stable.tests.AutomationFlowTests \
  --noinput -v 1
# 132 tests，OK
```

专用模块包含 published-audit 单篇 dry-run `<=35` 查询预算断言并通过。两次回归均通过 Django system check；132 项运行只有既有 `server/staticfiles/` 目录不存在 warning，无测试失败。

## Reviewer 第十六轮 findings RED 证据（2026-07-24）

本轮锁定 uncertain horse + machine link 只审计，以及 PostgreSQL published-audit 的 deadlock-safe NewsArticle table-first 锁序：

```bash
python3 -m py_compile server/stable/test_external_english_horse_context_gate.py
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_uncertain_horse_occurrence_with_machine_link_is_audit_only \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_common_word_machine_link_still_mismatches_and_confirmed_does_not \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_postgres_evidence_lock_covers_exact_tables_and_nonpostgres_is_noop \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_postgres_article_table_lock_is_exclusive_and_nonpostgres_noop \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_article_table_lock_precedes_all_other_locks_and_target_rows \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_article_table_lock_failure_is_zero_update \
  --noinput -v 2
```

结果：6 tests，6 assertion failures，退出码 1；测试数据库迁移、fixture、语法检查与 Django system check 均成功。

- P1 / uncertain machine link：pending `Brilliant Result` occurrence 已正确分类为 uncertain 并生成 info audit，但 AUTO 与 CANDIDATE `ArticleHorseLink` 都额外产生 `machine_entity_type_mismatch` blocker，payload 还错误标成 `entity_type=common_word`。测试要求 uncertain/ambiguous 不进入 rejected machine candidates。
- P1 / common/confirmed 对照：common-word `Agenda` + AUTO link 继续产生 mismatch；confirmed `Work won...` + CANDIDATE link 不产生 mismatch，本项当前 GREEN，证明修复只应把 rejected set 收窄为 common_word 和明确 suppressions。
- P2 / evidence helper：现有 SRX helper 仍包含 `NewsArticle`，新契约要求移出，剩余 ExternalHorseAlias、ArticleHorseLink、ArticleRaceLink、related-region through、RaceEvent、runner、result 共七表。
- P2 / article table lock：独立 `_lock_published_audit_article_table` 当前不存在。测试要求 PostgreSQL 单条 `LOCK TABLE NewsArticle IN EXCLUSIVE MODE`，明确不是 ACCESS EXCLUSIVE；该模式允许普通 ACCESS SHARE 读取，同时冲突 ROW SHARE/ROW EXCLUSIVE 并阻止 duplicate corpus phantom 写入。SQLite 必须 no-op。
- P2 / global order：要求同一 atomic 严格执行 `NewsArticle EXCLUSIVE -> 7 evidence SRX -> term SHARE -> target article row lock -> final context/snapshot -> article update`。helper 缺失使顺序测试在执行前 RED。
- P2 / fail closed：article table lock failure 必须阻止所有 downstream evidence/term locks 与 NewsArticle UPDATE，gate state 不变，run 保持 succeeded 且 result 未提交。现阶段因 helper 缺失无法满足。

第十五轮 term-lock failure 测试继续覆盖后续锁失败零更新；本轮新增最先 article-table lock failure，形成前后两端 fail-closed 证据。本轮未修改应用代码、配置、迁移、正文提取、正文清洗或来源适配器。

## Reviewer 第十六轮实现后的独立 GREEN（2026-07-24）

测试所有者先修正 evidence-lock 测试自身的表名前缀误判：不再用 `assertNotIn("stable_newsarticle", lock_sql)`，而是解析 `LOCK TABLE` 子句内完整 quoted identifiers，要求集合精确等于七张 evidence 表，并明确不含独立 NewsArticle 表。契约未降低。

随后使用项目 `.venv` 与 SQLite 独立复跑第十六轮 6 项：

```bash
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_uncertain_horse_occurrence_with_machine_link_is_audit_only \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_common_word_machine_link_still_mismatches_and_confirmed_does_not \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_postgres_evidence_lock_covers_exact_tables_and_nonpostgres_is_noop \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_postgres_article_table_lock_is_exclusive_and_nonpostgres_noop \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_article_table_lock_precedes_all_other_locks_and_target_rows \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_article_table_lock_failure_is_zero_update \
  --noinput -v 2
# 6 tests，OK；Django system check 无问题
```

结果确认：

- pending `Brilliant Result` uncertain occurrence 与 AUTO/CANDIDATE machine link 均只产生 info audit，不再产生 `machine_entity_type_mismatch` blocker。
- common-word `Agenda` + AUTO link 继续 mismatch；confirmed `Work won...` + CANDIDATE link 正常，无 mismatch。
- 独立 NewsArticle table helper 在 PostgreSQL 使用 EXCLUSIVE mode、SQLite no-op；七表 evidence helper 的精确表集不再含 NewsArticle。
- 同一 atomic 锁序为 `NewsArticle EXCLUSIVE -> 7 evidence SRX -> term SHARE -> target article rows -> final context -> update`。
- 最先 article-table lock failure 阻止全部 downstream locks 与 NewsArticle UPDATE；第十五轮 term-lock failure 对照继续覆盖后续锁失败零更新。

专用模块与相关最小回归：

```bash
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate --noinput -v 1
# 85 tests，OK

DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_english_term_context_gates \
  stable.test_term_gate_reprocessing \
  stable.tests.TermResolverTests \
  stable.tests.TranslationWorkflowTests \
  stable.tests.AutomationFlowTests \
  --noinput -v 1
# 132 tests，OK
```

两次回归均通过 Django system check。132 项运行只有既有 `server/staticfiles/` 目录不存在 warning，无测试失败。

## Reviewer 第十三轮 findings RED 证据（2026-07-24）

本轮锁定 off/shadow 的 legacy horse-term common-word 兼容，以及 published-audit apply 的一次性状态机与幂等重放：

```bash
python3 -m py_compile server/stable/test_external_english_horse_context_gate.py
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_off_legacy_common_word_downgrade_includes_translated_horse_entries \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_shadow_records_occurrence_would_change_but_keeps_legacy_horse_downgrade \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_enforce_keeps_occurrence_classification_for_common_horse_words \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_apply_replay_is_idempotent_and_does_not_touch_side_effects \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_apply_locks_run_and_rejects_non_succeeded_first_apply \
  --noinput -v 2
```

结果：5 tests，3 assertion failures、1 error、1 GREEN，退出码 1；测试数据库迁移、fixture、语法检查与 Django system check 均成功。

- P1 / off legacy：已译 English horse `Agenda`（内置 common seed）与 `Brilliant`（configured common representative）在普通业务/形容词语境均已由 occurrence resolver 判为 common，但 off 路径仍各产生 `core_term_missing` blocker。payload 已明确显示 `term_semantic_classification=common_word`，证明失败来自 legacy 最终分支排除了 `TermType.HORSE`。
- P1 / shadow legacy：相同两个 horse entries 在 shadow 下也错误保留 blocker；测试要求 legacy outcome 与 off 一致为 common-word downgrade，同时 `english_term_context_shadow.terms` 记录 occurrence classifications/would-change 信息，不改变实际 gate outcome。
- P1 / enforce 对照：两词均通过 occurrence 三类判定为 `common_word / needs_preserve=False`，无 core/background blocker，当前 GREEN；修复 off/shadow 不得回退 enforce。
- P2 / replay：首次 apply 成功后，同 run + manifest + identity 第二次 apply 没有提前识别 committed 状态，而进入 snapshot 复核并因 duplicate corpus dependency drift 抛错。测试要求锁定 run 后直接返回明确 `already_committed`，不得再次更新 article `updated_at`、run result/timestamps、QQ delivery 或 NotificationLog。
- P2 / first-apply state：将 prepared run 状态改为 `running` 后，apply 当前仍继续提交且未抛错。测试要求通过 `TermGateReprocessRun.objects.select_for_update()` 锁定 run，并仅允许 `succeeded` 首次 apply；非成功状态在 article 更新前 fail closed，run result/status 与 gate state 不变。

幂等 fixture 同时固定首次 apply 后的 gate 字段、article/run 时间戳、run result payload、QQ message/status 和 NotificationLog 状态/数量，避免仅凭返回值掩盖二次写入。本轮未修改应用代码、配置、迁移、正文提取、正文清洗或来源适配器。

## Reviewer 第十三轮实现后的独立 GREEN（2026-07-24）

测试所有者使用项目 `.venv` 与 SQLite 独立复跑第十三轮 5 项：

```bash
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_off_legacy_common_word_downgrade_includes_translated_horse_entries \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_shadow_records_occurrence_would_change_but_keeps_legacy_horse_downgrade \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_enforce_keeps_occurrence_classification_for_common_horse_words \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_apply_replay_is_idempotent_and_does_not_touch_side_effects \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_apply_locks_run_and_rejects_non_succeeded_first_apply \
  --noinput -v 2
# 5 tests，OK；Django system check 无问题
```

结果确认：

- off 下 `Agenda` 与 configured `Brilliant` 的已译 horse entries 均走 legacy common-word downgrade，不产生 core/background blocker。
- shadow 保持相同 legacy outcome，同时在 shadow terms 中记录 occurrence classifications；enforce 继续使用 occurrence 三类，二者均为 `common_word / needs_preserve=False`。
- 首次 published-audit apply 返回 committed；同 run + manifest + identity 重放返回 `already_committed`，article `updated_at`、gate state、run status/result/timestamps、QQ delivery 和 NotificationLog 均保持首次提交后的值。
- run 行通过 `select_for_update` 锁定；`running` 等非 `succeeded` 状态不得首次 apply，且 gate/result/status 不变。

第一次扩大回归曾发现强实体语境 common seed/dual-use horse payload 被降为 `uncertain`。实现修正后，测试所有者重新独立验证 `Contact/Live/Action` 与 `Tuesday/GOOD JOB/Fast Track`，均恢复 `proper_noun / confirmed_horse` blocker。

专用模块、AutomationFlow 与相关最小回归：

```bash
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate --noinput -v 1
# 71 tests，OK

DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.tests.AutomationFlowTests --noinput -v 1
# 37 tests，OK

DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_english_term_context_gates \
  stable.test_term_gate_reprocessing \
  stable.tests.TermResolverTests \
  stable.tests.TranslationWorkflowTests \
  stable.tests.AutomationFlowTests \
  --noinput -v 1
# 132 tests，OK
```

三次回归均通过 Django system check。AutomationFlow 与 132 项矩阵只有既有 `server/staticfiles/` 目录不存在 warning，无测试失败。

## Reviewer 第十四轮 findings RED 证据（2026-07-24）

本轮锁定 OpenAI-compatible rewrite 实际 prompt/restore 路径的 occurrence-safe placeholder，以及已译中文马名 target/alias 的语境级 preservation：

```bash
python3 -m py_compile server/stable/test_external_english_horse_context_gate.py
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_rewrite_provider_pending_formal_placeholders_only_confirmed_source_occurrence \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_rewrite_provider_alias_only_placeholders_only_confirmed_source_occurrence \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_translated_horse_target_in_ordinary_chinese_context_does_not_mask_missing \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_translated_horse_target_and_alias_require_generated_horse_context \
  --noinput -v 2
```

结果：4 tests，9 assertion failures，退出码 1；测试数据库迁移、fixture、语法检查与 Django system check 均成功。

- P1 / pending rewrite placeholder：source body 为 `Brilliant won...` 与 `a Brilliant performance`，pending formal 当前未生成任何 `__UMA_KEEP_1__`；测试要求 confirmed body occurrence 恰好一个 placeholder、ordinary occurrence 保留字面值。
- P1 / alias-only rewrite placeholder：当前 `_apply_placeholders` 对同名字符串全局替换，导致 ordinary title `Brilliant performance review` 也变为 `__UMA_KEEP_1__ performance review`；测试还锁定 body 仅 confirmed span 占位，provider 重排后只恢复 token，summary/title 的普通 occurrence 不被占位或映射。
- P1 / actual provider path：测试实际调用 `OpenAICompatibleRewriteProvider.rewrite`，捕获发送给 client 的 messages，并让 provider 输出把 ordinary phrase 排到 confirmed token 前；由此同时覆盖 title/body 字段 span、重排恢复与 summary 不全局替换，而非仅单测底层 helper。
- P1 / translated target ordinary mask：source confirmed horse 被删除、发布稿只剩 `团队表现辉煌` 时，当前 validation issues 为空；测试要求对 `Brilliant -> 辉煌` 产生 core/background horse missing。
- P1 / target + aliases shared context：合法 `辉煌获胜/获得亚军/本场冠军是辉煌` 与 `璀璨获胜`，以及普通 `团队表现辉煌/璀璨` 均只调用 shared helper 检查 source `Brilliant`，未把 target/aliases 送入 occurrence decision。测试要求 target 与 `aliases_zh` 一并通过共享 generated occurrence helper；合法关系通过，普通同形词继续 missing。

本轮未修改应用代码、配置、迁移、正文提取、正文清洗或来源适配器。

## Reviewer 第十四轮实现后的独立 GREEN（2026-07-24）

测试所有者使用项目 `.venv` 与 SQLite 独立复跑第十四轮 4 项：

```bash
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_rewrite_provider_pending_formal_placeholders_only_confirmed_source_occurrence \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_rewrite_provider_alias_only_placeholders_only_confirmed_source_occurrence \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_translated_horse_target_in_ordinary_chinese_context_does_not_mask_missing \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_translated_horse_target_and_alias_require_generated_horse_context \
  --noinput -v 2
# 4 tests，OK；Django system check 无问题
```

结果确认：

- OpenAI-compatible rewrite actual messages 中，pending formal 与 alias-only 的 confirmed body occurrence 均恰好生成一个 KEEP token；ordinary title/body occurrence 保持字面值。
- provider 将 ordinary phrase 重排到 token 前后，只恢复 token 对应的 confirmed occurrence；title 与 summary 普通同形词不被全局 placeholder 或 mapping 污染。
- source confirmed horse 被删除、publish/rewrite output 仅剩 `团队表现辉煌` 时，已译 `Brilliant -> 辉煌` 正确产生 core/background horse missing。
- target `辉煌` 与 alias `璀璨` 均通过 shared generated occurrence helper 判定：获胜、亚军和前置冠军关系通过，普通“团队表现辉煌/璀璨”继续 missing。

专用模块与相关最小回归：

```bash
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate --noinput -v 1
# 75 tests，OK

DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_english_term_context_gates \
  stable.test_term_gate_reprocessing \
  stable.tests.TermResolverTests \
  stable.tests.TranslationWorkflowTests \
  stable.tests.AutomationFlowTests \
  --noinput -v 1
# 132 tests，OK
```

两次回归均通过 Django system check。132 项运行只有既有 `server/staticfiles/` 目录不存在 warning，无测试失败。

## Reviewer 第十二轮 findings RED 证据（2026-07-24）

本轮在既有 occurrence 独立契约上锁定 structured + local race relation 的优先级，以及中文赛果保留表达：

```bash
python3 -m py_compile server/stable/test_external_english_horse_context_gate.py
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_structured_campaign_requires_local_race_relation_to_override_ordinary_purpose_shape \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_generated_chinese_result_relations_share_mapping_and_validation_semantics \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_pending_alias_validation_accepts_chinese_result_relations_but_not_ordinary_phrases \
  --noinput -v 2
```

结果：3 tests，8 assertion failures，退出码 1；测试数据库迁移、fixture、语法检查与 Django system check 均成功。

- P2 / structured local relation：active linked runner 与 alias 均为 `Campaign` 时，首个 `Campaign to win the race...` 已由 structured evidence 确认为马名；但同文 `the Campaign to win the race...` 被 `ordinary_purpose_noun` 提前降为 common，实际 `needs_preserve=False`。测试要求 structured identity 与当前 occurrence 的明确 `to win the race` 关系共同覆盖 purpose 句形。
- P2 / occurrence independence：同一 linked 文章内 `A Campaign performance...` 与 `campaign to improve business` 仍必须为 common 且不得携带 runner evidence，证明修复不能把结构化同拼写广播到全文。live wrapper、batch resolver、term-gate reprocessing payload 继续要求完全一致。
- P2 / generated result mapping：`Brilliant获得亚军/冠军/季军` 与前置关系 `本场冠军是Brilliant` 当前均未映射；`名列第二`、`跑获第三` 既有合法表达继续作为 GREEN 对照。测试同时要求 mapper 与 validation 通过公开 `classify_generated_horse_occurrence` 共享 occurrence 判定。
- P2 / validation preservation：pending formal + ExternalHorseAlias 的 `Brilliant获得亚军`、`本场冠军是Brilliant` 当前仍产生 `pending_horse_original_missing` blocker；预期视为合法保留。普通 `Brilliant获得支持` 与 `冠军是Brilliant表现` 必须继续产生缺失问题，避免扩大为简单的“获得”或“冠军是”字面规则。

本轮未修改应用代码、配置、迁移、正文提取、正文清洗或来源适配器。

## Reviewer 第十二轮实现后的独立 GREEN（2026-07-24）

测试所有者使用项目 `.venv` 与 SQLite 独立复跑第十二轮 3 项：

```bash
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_structured_campaign_requires_local_race_relation_to_override_ordinary_purpose_shape \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_generated_chinese_result_relations_share_mapping_and_validation_semantics \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_pending_alias_validation_accepts_chinese_result_relations_but_not_ordinary_phrases \
  --noinput -v 2
# 3 tests，OK；Django system check 无问题
```

结果确认：

- linked runner + alias `Campaign` 的 `Campaign to win...` 与 `the Campaign to win the race...` 均为 `confirmed_horse / needs_preserve=True`，并保留精确 runner evidence。
- 同文 `A Campaign performance...` 与 `campaign to improve business` 仍为 common，且不携带 runner evidence；structured spelling 没有广播到普通 occurrence。
- live wrapper、batch resolver、term-gate reprocessing 对四个 occurrence 返回完全一致 payload。
- `Brilliant获得亚军/冠军/季军`、`Brilliant名列第二/跑获第三` 与 `本场冠军是Brilliant` 均由 mapper 与 validation 共享公开 occurrence helper 判为合法马名语境。
- `Brilliant获得支持` 与 `冠军是Brilliant表现` 均不映射、不视为已保留；pending formal + alias 的合法表达不再产生 missing blocker，普通负例仍产生马名缺失 issue。

专用模块与相关最小回归：

```bash
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate --noinput -v 1
# 66 tests，OK

DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_english_term_context_gates \
  stable.test_term_gate_reprocessing \
  stable.tests.TermResolverTests \
  stable.tests.TranslationWorkflowTests \
  stable.tests.AutomationFlowTests \
  --noinput -v 1
# 132 tests，OK
```

两次回归均通过 Django system check。132 项运行只有既有 `server/staticfiles/` 目录不存在 warning，无测试失败。

## Reviewer 第七轮 findings RED 证据（2026-07-24）

本轮锁定重复 copula 误判与 published-audit 外部/结构化证据快照：

```bash
python3 -m py_compile server/stable/test_external_english_horse_context_gate.py
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_pending_repeated_copula_phrase_is_not_horse_context \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_formal_repeated_copula_phrase_is_not_horse_context_but_win_is_confirmed \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_external_alias_repeated_copula_phrase_is_not_horse_context \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_manifest_binds_alias_and_structured_evidence_snapshots \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_apply_fails_closed_on_external_alias_snapshot_drift \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_apply_fails_closed_on_structured_evidence_snapshot_drift \
  --noinput -v 2
```

结果：6 tests，5 assertion failures、1 个缺失契约字段 error，退出码 1；数据库迁移、fixture、语法检查与 Django system check 均成功。

- P2 / pending：`Enough was enough.` 首个 occurrence 实际为 `confirmed_horse / needs_preserve=True`，reason=`horse_subject_copular_relation`；预期两个 occurrence 均为 common_word 或 uncertain，且不产生马名保护告警。
- P2 / formal：`Work was work.` 首个 occurrence 同样被错误升级为 confirmed；测试同时锁定 `Work won at Ascot.` 必须继续是 confirmed horse。
- P2 / ExternalHorseAlias：alias-only `Work was work.` 首个 occurrence 实际为 `confirmed_horse / needs_preserve=True`，证明该宽泛重复 copula 规则也污染外部马名链路。
- P2 / manifest contract：dry-run 返回值、run result payload 与 manifest 当前均缺少 `external_horse_alias_snapshot_sha256` 和 `structured_horse_evidence_snapshot_sha256`；单篇 dry-run 查询数已先通过 `<=35` 有界预算断言。
- P2 / alias drift：dry-run 后新增与文章 outcome 无关的 `ExternalHorseAlias`，apply 未 fail closed，实际继续提交；测试要求抛出 snapshot/evidence drift 且 article 的 gate fields 保持原值。
- P2 / structured drift：dry-run 后同时移除 active `ArticleRaceLink` 并修改关联 runner/result horse names，文章 outcome 本身不变时 apply 仍继续提交；测试要求独立结构化证据快照捕获漂移并在任何 article 更新前拒绝。

漂移 fixture 特意选择不改变既有 validation outcome 的证据，避免 outcome hash 偶然代替 alias/structured snapshot 契约。无漂移成功对照由同一 manifest binding 测试完成 apply，并受既有 allowlist 测试继续保护。本轮未修改应用代码、迁移、正文提取或清洗规则。

## Reviewer 第七轮实现后的独立 GREEN（2026-07-24）

测试所有者使用项目 `.venv` 与 SQLite 独立复跑第七轮 6 项：

```bash
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_pending_repeated_copula_phrase_is_not_horse_context \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_formal_repeated_copula_phrase_is_not_horse_context_but_win_is_confirmed \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_external_alias_repeated_copula_phrase_is_not_horse_context \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_manifest_binds_alias_and_structured_evidence_snapshots \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_apply_fails_closed_on_external_alias_snapshot_drift \
  stable.test_external_english_horse_context_gate.PublishedEnglishHorseAuditOnlyTests.test_published_audit_apply_fails_closed_on_structured_evidence_snapshot_drift \
  --noinput -v 2
# 6 tests，OK；Django system check 无问题
```

结果确认：

- pending `Enough was enough.`、formal 与 alias-only `Work was work.` 均降为 common_word 或 uncertain，不再产生 preserve warning。
- `Work won at Ascot.` 仍为 confirmed horse。
- 另补合法 coreference 对照：`Work was work. The horse won at Ascot.` 仍以 `proper_name_copular_adjective_contrast` 判为 confirmed，证明规则是收窄而非整段删除。
- dry-run 返回值、result payload 与 manifest 均绑定 64 位 `external_horse_alias_snapshot_sha256` 与 `structured_horse_evidence_snapshot_sha256`。
- 无漂移 apply 成功；alias 或 active link/runner/result 证据漂移时 apply 均 fail closed，且 article 的 gate issues、decision reason 与 warning signature 零更新。
- 单篇 dry-run 查询数保持 `<=35` 的有界预算。

专用模块与相关最小回归：

```bash
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate --noinput -v 1
# 45 tests，OK

DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_english_term_context_gates \
  stable.test_term_gate_reprocessing \
  stable.tests.TermResolverTests \
  stable.tests.AutomationFlowTests \
  --noinput -v 1
# 118 tests，OK
```

两次回归均通过 Django system check。118 项运行只有既有 `server/staticfiles/` 目录不存在 warning，无测试失败。

## Reviewer 第十一轮 findings RED 证据（2026-07-24）

本轮锁定弯/直撇号结构化马名键一致性，以及生成文本中嵌套正式马名的 non-overlap 选择：

```bash
python3 -m py_compile server/stable/test_external_english_horse_context_gate.py
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_apostrophe_normalized_structured_horse_evidence_is_consistent_across_resolvers \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_reprocessing_imports_the_public_terms_horse_entity_key_normalizer \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_generated_nested_formal_horses_use_longest_non_overlapping_mapping \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_generated_nested_formal_horse_mapping_is_stable_for_reverse_order_and_priority \
  --noinput -v 2
```

结果：4 tests，4 assertion failures，退出码 1；测试数据库迁移、fixture、语法检查与 Django system check 均成功。

- P1 / apostrophe identity：结构化 `King’s Gambit` 与正文/alias `King's Gambit won...` 时，live wrapper 与 batch resolver 已取得结构化 evidence，但 term-gate reprocessing 仍退回 `strong_horse_context`，confidence 由 100 降为 98，三路径 payload 不一致。反向组合也纳入同一测试，要求全部为 `confirmed_horse / needs_preserve=True` 并携带精确 `race_runner:<id>:event:<id>:horse_name`。
- P1 / shared helper：`stable.services.terms.normalize_horse_entity_key` 当前不存在；测试要求它成为公开唯一 normalization helper，并要求 `term_gate_reprocessing` 直接导入同一函数对象且在构建结构化 evidence key 时实际调用，禁止保留自建 `unicodedata.normalize(...).casefold()` 分支。
- P1 / nested mapping：`International Star` 与 `Star` 均为 confirmed、targets 分别为“国际之星”和“星”时，当前重叠替换得到 `国际之星n at Ascot...`，证明短词 span 二次破坏长词结果。测试要求 longest-first、priority-independent 的不重叠选择，并验证同文独立 `Star` 及单独生成文本 `Star won...` 仍映射。
- P1 / stability：以反向创建/原文顺序及相反 priority 再现同一损坏，要求结果稳定为 `国际之星 won at Ascot. 星 finished second.`，不能由 ORM 顺序或 priority 改变重叠 span 决策。

本轮未修改应用代码、配置、迁移、正文提取、正文清洗或来源适配器。

## Reviewer 第十一轮实现后的独立 GREEN（2026-07-24）

测试所有者使用项目 `.venv` 与 SQLite 独立复跑第十一轮 4 项：

```bash
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_apostrophe_normalized_structured_horse_evidence_is_consistent_across_resolvers \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_reprocessing_imports_the_public_terms_horse_entity_key_normalizer \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_generated_nested_formal_horses_use_longest_non_overlapping_mapping \
  stable.test_external_english_horse_context_gate.ExternalEnglishHorseContextGateTests.test_generated_nested_formal_horse_mapping_is_stable_for_reverse_order_and_priority \
  --noinput -v 2
# 4 tests，OK；Django system check 无问题
```

结果确认：

- `King’s Gambit` / `King's Gambit` 两种结构化 evidence 与正文/alias 方向均在 live wrapper、batch resolver 和 term-gate reprocessing 返回完全一致 payload，保持 `confirmed_horse / needs_preserve=True` 并携带精确 runner evidence。
- `terms.normalize_horse_entity_key` 已成为公开 helper；reprocessing 暴露的是同一函数对象，并在构建结构化 horse evidence key 时实际调用。
- `International Star` 与 `Star` 均可作为不同正式马名进入候选；嵌套 occurrence 选择完整长词且不再被短词二次破坏。
- 反向创建/原文顺序与相反 priority 不改变结果；独立 `Star won...` 仍正常映射。

专用模块与相关最小回归：

```bash
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate --noinput -v 1
# 63 tests，OK

DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_english_term_context_gates \
  stable.test_term_gate_reprocessing \
  stable.tests.TermResolverTests \
  stable.tests.TranslationWorkflowTests \
  stable.tests.AutomationFlowTests \
  --noinput -v 1
# 132 tests，OK
```

两次回归均通过 Django system check。132 项运行只有既有 `server/staticfiles/` 目录不存在 warning，无测试失败。

## 最新 P1/P2 findings 的 RED 与独立 GREEN（2026-07-24）

测试先行新增两项精确回归，并在应用修复前取得真实 RED：

- P1 / proper-name horse noun priority：`The Brilliant filly impressed observers in the paddock.` 与 `The Brilliant horse arrived at Ascot before the meeting.` 当前 occurrence 均被普通形容词规则抢先降为 `common_word / needs_preserve=False / ordinary_adjective_context`。预期仅当候选保持专名式首字母大写并紧邻明确 horse entity noun 时，覆盖 adjective downgrade，判为 `confirmed_horse`；不得把小写 `versatile filly` 等普通形容词扩大升级。
- P2 / non-English discovery context fallback：日文 alias `ザガラ` 的 resolver 已给出 `body` 与 span `(6, 9)`，但当 entity 自带 `matched_context=""` 时，discovery finding 的 context 仍为空。预期从同一 resolved field/span 的原始翻译源文本截取上下文，保留日文坐标，不回退到英文 visible-clean 表示。

修复后首先精确复跑上述两个测试；Django 报告 `Found 2 test(s)`、`Ran 2 tests`、`OK`。其中首项包含 2 个专名 horse-noun 场景，因此共验证 3 个逻辑场景。

随后独立复验：

```text
article 9595 / Logician / strong / common / versatile filly：Found 7，Ran 7，OK
discovery field-span-context / live-batch-reprocess / structured occurrence scope：Found 6，Ran 6，OK
query budget / mixed-language telemetry / 100-article dry-run：Found 3，Ran 3，OK
published audit identity / state machine / replay security：Found 6，Ran 6，OK
当前去重完整矩阵：Found 330，Ran 330，OK
日文、繁中、正式术语及 raw-coordinate 专项：Found 77，Ran 77，OK
```

完整矩阵为：

```bash
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_external_english_horse_context_gate \
  stable.test_english_term_context_gates \
  stable.test_contextual_news_entities \
  stable.test_term_gate_reprocessing \
  stable.test_japanese_racing_translation_normalization \
  stable.tests.TermResolverTests \
  stable.tests.TranslationWorkflowTests \
  stable.tests.AutomationFlowTests \
  --noinput -v 1
# Found 330 test(s)
# Ran 330 tests
# OK
```

结果确认：

- article 9595 的 13 个普通词不产生 horse preserve warning，Logician 与明确 race relation 继续确认。
- `The Brilliant filly/horse ...` 的专名式 occurrence 由 horse entity noun 优先确认；`She is a versatile filly...` 与其他普通 adjective fixture 继续降级，证明规则是 occurrence-level 收窄而非扩大。
- discovery 在 entity context 为空时只从 resolved field/span 补齐局部上下文，日文 raw source 坐标不变。
- 实时、batch、reprocessing 与 discovery 继续共享分类；structured evidence 不广播到同文 lexical-only occurrence。
- 2/20/100 篇查询预算、实际 entity-index telemetry 与 published exact-ID audit 的身份/状态机/幂等约束均通过。
- Django check 无问题；所有修改 Python 文件通过 `py_compile`；`git diff --check` 通过。
- 边界检查确认未修改 `AGENTS.md`、全局状态文档、source adapters、HTML 抓取、正文提取器或正文清洗规则。

当前 worktree `HEAD=d64c69264df8bf16389e99514fb4ab553ca3f37b`，而本地跟踪的
`origin/main=a5d4a7c64613a35005e90a9714fbe95808efecda`，merge-base 仍为
`d64c69264df8bf16389e99514fb4ab553ca3f37b`。因此先前 reviewer fingerprint
已因代码修复和 base ref 前移而失效；以上 GREEN 不等于 review approval。

## 最终两项核心 P1 的 RED/GREEN（2026-07-24）

测试先行新增三个精确场景。应用修复前运行 3 项：2 项按目标能力真实失败，
中文 target substring 负例通过。

- `a brilliant filly won...` 的小写 `brilliant` 实际被
  `horse_entity_noun_race_relation` 升级为 `confirmed_horse /
  needs_preserve=True`；预期为 `common_word / False`。同文
  `Brilliant won...` 与 `The Brilliant filly won...` 为安全对照。
- source `Logician won...` 已确认为马名，publish text 为
  `焦点转向逻辑学家。` 时，实际仍产生 `core_term_missing`；预期正式
  `target_zh` 的精确提及满足 preservation。
- `逻辑学家族` 仅为 target substring，继续产生 missing issue。

最小修复后运行新增及既有 translated target/alias 正负边界共 5 项，全部
GREEN；随后运行整个 `stable.test_external_english_horse_context_gate`
模块，`Found 101 test(s)`、`Ran 101 tests`、`OK`，Django system check
无问题。

## rebase 后最终验证证据（2026-07-24）

- `git rebase --autostash origin/main` 已成功完成，无冲突；worktree
  `HEAD` 已快进到
  `origin/main=97a38cf5e2a692b7336c8518a4cdd6dfcc511d2a`，本 change 的未提交
  修改已由 autostash 恢复。
- 主线程在该基线上重新运行当前完整去重矩阵：`Found 333 test(s)`、
  `Ran 333 tests`、`OK`。
- 日文、繁中、正式中文术语及 raw-coordinate 语言专项：
  `Found 77 test(s)`、`Ran 77 tests`、`OK`。
- `python server/manage.py check` 通过。
- `python server/manage.py makemigrations --check --dry-run` 返回
  `No changes detected`。
- `git diff --check` 通过。

以上证据只证明 rebase 后测试与静态门禁 GREEN，不等于代码 review 已通过。
下一步必须对新的 worktree fingerprint 执行一轮独立只读 review；review 成功后，
仍须取得用户针对该精确 fingerprint 的明确发布确认。
