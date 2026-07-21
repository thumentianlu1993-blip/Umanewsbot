# 已审核赛事中文名统一导入与生产写入规格

## 目标

将日本、中国香港、美国、英国、法国五份已审核 Excel 中的 `2023` 个展示名分组转换为可审计、可重复验证的统一 manifest；先完成生产只读 dry-run，再在备份、逐对象 compare-and-swap 和用户授权门禁后执行一次原子写入及独立验证。

## 范围

- 锁定五份最终工作簿的绝对路径、SHA-256、工作表结构和明细行数。
- 将最终工作簿的序号、当前展示名、年份、年度赛事数、RaceSeries Key / ID 逐行对照 `docs/collected_complete_race_names_missing_zh_20260719.md`；审核文件不得改变原始身份列。
- 仅接受 `审核状态=已确认` 且中文名、RaceSeries Key / ID、年份和来源均完整的行。
- 生成 RaceSeries 中文名候选和 RaceEvent 中文名候选。
- 对香港 `SURFACE Bauhinia Sprint Trophy(H)` 2012 行执行一条显式身份修正：目标 RaceSeries ID 从 `6019` 改为 `5963`。
- 对生产当前值执行只读比较，输出新增、已一致、冲突、缺失、超范围和身份修正统计。
- 保存每个拟更新对象的导入前字段值，作为后续回滚 manifest 的依据。
- 生成便于用户复核的 Excel 预演报告。
- 按用户最终更正把日本 `Keisei Hai Autumn H` 的中文展示名锁定为“京成杯秋季赛”。
- 提供默认只读、显式 `--commit` 才写入的生产 apply 工具；写入前逐对象比较完整 before 字段和 `updated_at`。
- 正式写入前生成并独立校验 PostgreSQL custom-format 备份；写后独立核对全部目标值和香港身份修正。

## 非目标

- 不修改正式术语库、原始赛事名称、来源证据或公开状态。
- 不删除 RaceSeries ID `6019`，不自动合并任何其他 RaceSeries。
- 不因不同 RaceSeries 使用同一中文名而自动建立关系或改变身份。
- 不修改新闻、翻译、QQ、调度或部署配置。
- 不修改模型、迁移、新闻、调度或公开开关；一次性 apply 工具通过现有生产 web 容器执行，不要求重建或重启服务。

## 输入

| 地区 | 最终工作簿 | SHA-256 | 预期行数 |
|---|---|---|---:|
| 日本（修订前基线） | `outputs/translate-race-names-20260719/日本_已完整赛事中文名翻译审核表_20260719_AI翻译完成.xlsx`（2026-07-21 起为权威路径，由 `/Users/mentianlu/Downloads/` 同字节复制，SHA 未变） | `57a40984e2723251db554f6a6c7c7a9b2661991fee16ad89b69ed3e902c81fad` | 176 |
| 日本（最终输入） | `outputs/translate-race-names-20260719/日本_已完整赛事中文名翻译审核表_20260719_京成杯秋季赛修订.xlsx` | `e244a0fb366ab1cf259b3c2f714cfea2066e8abbf21a79076c64443220b26eb1` | 176 |
| 中国香港 | `outputs/translate-race-names-20260719/中国香港_已完整赛事中文名翻译审核表_20260719_AI翻译完成.xlsx`（2026-07-21 起为权威路径，同字节复制，SHA 未变） | `20153db5217a8b05ff7b98b0af9640dea52ead58b17a8a91d35eedd154fa705f` | 91 |
| 美国 | `outputs/translate-race-names-20260719/美国_已完整赛事中文名翻译审核表_20260719_已审核.xlsx` | `f2481cdeea456bbf6ac5faf9102928cb5d67d520082d8b5c47ffecd41aa46c00` | 724 |
| 英国 | `outputs/translate-race-names-20260719/英国_已完整赛事中文名翻译审核表_20260719_AI翻译完成.xlsx`（2026-07-21 起为权威路径，同字节复制，SHA 未变） | `f0a80a5f55244224698fab6f3d56f0d5a7d776eb01ba02bf75c7d5f33d45488b` | 794 |
| 法国 | `outputs/translate-race-names-20260719/法国_已完整赛事中文名翻译审核表_20260719_AI翻译完成.xlsx`（2026-07-21 起为权威路径，同字节复制，SHA 未变） | `8234a68a16dc6c8e13b2cbef7a5eaf91a31ceeb0b0b561fcda4b596d5ffe02da` | 238 |

规范身份基线为 `docs/collected_complete_race_names_missing_zh_20260719.md`，其分组快照 SHA-256 为 `c9c209e686bbce669bfdfd161bade5f4dfae357cc899fa649e908a749cfa966d`。工具必须重新解析该文件并逐行比对，不得只读取工作簿自报计数。

## 规则

1. 同一 RaceSeries 内所有分组必须得到唯一中文名，否则整批失败。
2. 所有最终中文名禁止包含“让赛 / 讓賽 / 让步赛 / 讓步賽”；若审核工作簿中文名仍含这些字样，manifest 按用户已锁定规则仅删除对应字样与删除后形成的空括号，不补写其他词，并同时保存审核原值、调整后值和规则说明。原文中的 `(H)`、独立 `H` 和 `Handicap` 不进入中文展示名。
3. RaceSeries 必须同时精确匹配 ID、Key 和地区。
4. 普通赛事只能按 `RaceSeries ID + 年份 + 当前展示名` 精确定位。
5. 香港显式修正行按原 RaceSeries ID `6019`、年份 `2012`、原文 `SURFACE Bauhinia Sprint Trophy(H)` 定位；写入候选同步修改 RaceEvent 的 `race_series_id / series_key / chinese_name` 与其唯一 HistoricalRaceEventTarget 的 `race_series_id`，不改 `original_name`。
6. 审核表范围内 RaceEvent 当前中文名只有为空、等于原文或已经等于建议中文名时才可进入可写候选；其他值为冲突。目标系列范围外、但当前 `chinese_name == original_name` 的 Event 必须按地区、系列和锁状态纳入补充翻译；已有独立中文名的范围外 Event 不覆盖。
7. RaceSeries 当前中文名只有为空或已经等于建议中文名时才可进入可写候选；其他值为冲突。
8. RaceSeries 的 `manual_lock_flags.chinese_name` 为真时阻断系列动作；RaceEvent 的 `chinese_name` 锁阻断中文名动作，`race_series / series_key / identity` 任一锁阻断香港身份修正。
9. 任一输入 SHA、结构、计数、身份、年份覆盖、锁状态或数据库当前值不满足预期时 fail closed，不生成 apply-ready 结论。
10. 正式 apply 只接受最新锁定 dry-run 与 rollback-before；脚本默认只读，只有 `--commit` 才写入，并在单个数据库事务中锁定、复核、更新和写入一条批次 OperationLog。
11. apply 只更新 `1300` 个 `RaceSeries.chinese_name`、`8883` 个 `RaceEvent.chinese_name`（`8663` 个审核表年度赛事、获授权的 2026 Event `96`、以及 `219` 个同系列原文回退 Event），以及香港 Event `16446` 的 `race_series_id / series_key` 和 HistoricalRaceEventTarget `49052` 的 `race_series_id`；不得扩大目标集合。
12. 日本最终输入必须由修订前基线产生。语义差异 allowlist 仅允许序号 64 的“建议中文名”从“京成杯秋季让赛”变为“京成杯秋季赛”；若工具保存所必需，允许该单元格对应的内部文件元数据变化。其余 175 行的全部业务单元格，以及序号 64 的身份、来源、状态、备注均须逐项一致；公式、样式、合并区域、列宽、行高、冻结窗格、筛选和数据验证须保持等价。任何额外业务差异阻断。
13. 生产执行只接受完整受审 bundle。bundle 精确包含 apply 工具、独立 verifier、`input-lock.json`、`normalized-input.json`、`manifest.json`、`production-before.json`、`dry-run.json`、`rollback-before.json`、`execution-metadata.json`、`execution-plan.json`、`artifact-index.json` 和 `bundle-index.json`；后者列出前十一个成员的文件大小与 SHA-256，并以排除自身 `contentSha256` 字段后的规范 JSON 计算内容身份。
14. apply/rollback/verifier 命令必须显式接收审核后锁定的 `bundle-index.json` 原始 SHA-256。宿主机上传前、容器复制后、verify-only 前、commit 前和写后 verifier 前均重算整个 bundle；任何成员、index 内容身份或 index 原始 SHA 不一致即停止。
15. `production-before.json` 和 `rollback-before.json` 对 RaceSeries、RaceEvent 与香港修正关联的 HistoricalRaceEventTarget 保存 Django 模型所有 concrete database fields 的规范化完整行值与完整行 SHA；正式事务锁定精确主键集合后，在任何写入前逐行复核完整行 SHA、人工锁、关联身份与 `updated_at`。
16. 对象级 rollback 是首选恢复路径：只在当前完整行仍精确等于本批 after 快照、对应 apply OperationLog 唯一存在时，才允许以同一事务恢复完整 before 可写字段并写一条 rollback OperationLog；任一 after CAS 漂移即停止并转入人工事故/整库恢复决策，不自动覆盖其他合法写入。
17. 每个工作簿必须一次加载为不可变 bytes；输入 SHA-256 和工作簿解析必须消费同一份 bytes，禁止哈希路径后再次按路径打开。日本修订前基线与最终输入分别锁定 bytes 后，主生成器必须调用授权差异校验并证明全部受检业务值只有 `C68` 一处变化、公式零变化。
18. Markdown 身份基线必须从已解析的 `2023` 行重建原生产分组对象，按 `country_region / event__chinese_name / race_series_id` 的原查询顺序计算规范 JSON SHA-256，并与锁定值比较；禁止只复制文档文本里的 SHA。让赛清理只可删除明确的四种让赛标记及直接包裹该标记的中英文括号，不得折叠其他空格或删除任何无关尾部标点。
19. 独立 verifier 选择 apply/rollback OperationLog 后，必须把日志中的 `bundleIndexSha256 / bundleContentSha256 / toolSha256 / verifierSha256 / manifestSha256 / productionBeforeSha256 / dryRunSha256 / rollbackSha256` 与当前受审 index 和 metadata 逐项匹配；只匹配 batch ID 不足以通过验收。
20. execution plan 必须冻结全部 `queriedSeriesIds` 对应 RaceSeries 的完整 before-row SHA，以及其生产快照中的完整 RaceEvent 集合。apply/rollback 事务先锁定并校验全部父 RaceSeries，再按这些系列查询并锁定完整 Event 集；父系列、子集合、系列归属或非动作行完整 SHA 任一漂移都在业务写入前 fail closed。独立 verifier 必须重查同一完整父子集合。
21. 客户端从保留 JSON 数值词法的 payload 重建快照后，必须逐行重算 `fullRow.rowSha256`，并从完整 lossless content 重算整体 `second.sha256`；任一结果与服务端摘要不一致，不得生成执行计划或 bundle。
22. 生产 metadata 必须在 snapshot 前后各读取一次并精确比较 checkout HEAD、容器 image ID/tag 和 started-at；任一变化表示本次快照运行时身份不稳定，候选生成失败。
23. supplemental Event 仅允许 `chinese_name == original_name` 的同系列回退值和显式 allowlist Event `96`；其他独立中文名无论是否含让赛标记都不得更新。每个 supplemental Event 必须同时匹配 RaceSeries ID、series key 和地区，任一漂移分类为 conflict。

## 验收标准

- 五份输入 SHA 全部匹配，`2023/2023` 行通过结构和审核状态校验。
- 所有让赛规则调整逐行列入报告；调整后的最终中文名不含让赛字样，原 Excel 保持不变。
- 聚合为 `1301` 个源 RaceSeries，审核表年度赛事目标与审核快照的 `8663` 场一致；精确追加 2026 Event `96`，并纳入 `219` 个同系列原文回退 Event，最终 Event 动作总数为 `8883`。剩余 `2` 个已有独立中文名的范围外 Event 仅提示。若生产发生漂移，报告必须明确差异且结论为 blocked。
- 香港修正必须唯一定位一场 2012 赛事及其唯一历史目标；两者当前系列必须一致，目标系列 5963 在 2012 年不得已有另一场年度赛事或历史目标。
- dry-run 只读取生产数据库；查询前后对全部目标字段按主键排序生成 SHA-256，两个稳定摘要必须完全一致，生产对象 `updated_at`、计数和业务字段前后不变。
- manifest、生产快照、dry-run 报告、回滚前值和 Excel 报告均带 SHA-256 与生成时间。
- 用户可从 Excel 报告看到地区汇总、阻断项、系列动作、年度赛事动作和跨系列同译名提示。
- 日本序号 64 最终建议中文名为“京成杯秋季赛”，影响 2010–2025 共 16 场，任何“京成杯秋季”旧值均不得进入正式 manifest。
- 日本修订前后语义差异报告证明仅一个获授权译名单元格变化；任何额外业务单元格变化的负向用例均会阻断。
- apply 前 custom-format 备份非空、SHA-256 已记录且 `pg_restore -l` 通过；apply 输出 `1300/8883/1 historical target/1 identity correction`，OperationLog 恰有一条对应批次且精确 bundle 身份一致的记录。
- 写后 verifier 逐对象确认 after 值、让赛标记为零、香港唯一修正正确；生产 `/healthz/` 和赛事页面抽检通过。
- PostgreSQL 16 集成测试证明目标行锁、完整行 CAS、条件唯一约束、审计失败回滚、对象级 rollback 和 `updated_at` 行为；生产规模 fixture 在既定查询数、耗时与内存上界内完成。
