## 0. Pre-declared hypotheses

- [x] 0.1 (operations) 在实现前确认首批验收阈值：日本、中国香港、英国、法国、美国各 10 匹新版 P0 马必须达到完整资料状态；失败样本只能进入 blocker/替补池，不得计入完成。
- [x] 0.2 (operations) 在实现前确认完整资料硬字段：身份/P0 来源证据、国家/地区、性别、毛色、出生日期、马主、练马师、生产牧场、二代血统、完整赛事履历、主胜鞍、来源 URL 和人工审核记录必须齐备；`intro`、相关新闻和站内相关赛事链接不作为硬门槛。
- [x] 0.3 (operations) 在实现前确认 commit 阈值：只允许审核通过的模块写入；重复 commit 不得产生重复 `HorseRaceRecord`；人工锁定字段必须计入 `manual_lock_skipped`；若出现未审核行写库或公开页触网，则 BLOCKER。
- [x] 0.4 (operations) 在更新 proposal 后重新执行 `plan-eng-review`，并将 review 结果写入 `.openspec.yaml`。

## 1. P0 范围、术语和数据模型

- [x] 1.1 (application) 设计并新增 P0 来源结构，记录 `term_active_with_zh`、`major_race_participant`、赛事、等级、地区、source URL、审核状态、active/revoked 状态和证据摘要。
- [x] 1.2 (application) 升级 `TermEntry`，允许 horse term 暂无中文译名，并新增 `translation_status` 或等价字段区分 `pending` 与 `translated`。
- [x] 1.3 (application) 新增或扩展 `HorseProfile` 完整资料状态、赛马生涯状态或等价同步标记，区分现有 `complete_pedigree_2gen`、退役马完整生涯履历和在役马截至最近同步时间的完整已知履历。
- [x] 1.4 (application) 设计并新增 P0 补全 run / batch 记录模型或等价持久化结构，记录范围、参数、状态、artifact 路径、统计摘要、错误信息和操作者。
- [x] 1.5 (application) 新增迁移，并确保 P0 来源、batch 记录、`HorseIdentityConflict`、候选记录、`HorseProfile` 和 `HorseRaceRecord` 可互相反查。
- [x] 1.6 (application) 将生涯履历完整度从资料/二代血统完整度中拆分，新增来源总出赛数、已采集实际出赛数、缺口数、已关联/未关联赛事数、海外出赛数、独立状态和最后核验时间，并以安全迁移回填现有异常结果的实际出赛语义。

## 2. 术语识别、翻译保护和前台展示

- [x] 2.1 (integration) 更新术语解析与应用逻辑：有中文译名术语可参与中文替换；无中文译名 horse term 只参与实体识别和原文保护。
- [x] 2.2 (integration) 更新翻译提示、占位符保护和译后校验，确保命中的无译名 P0 马名至少在最终译文中保留一次原文，标题命中时标题或正文首段保留原文。
- [x] 2.3 (integration) 更新核心术语门禁，使无译名 horse term 不触发“中文译名缺失”式替换校验，但会触发原文保留校验。
- [x] 2.4 (application) 更新后台术语表单、CSV 导入导出、API 和列表筛选，支持 `target_zh` 为空且显示“中文名待补”状态。
- [x] 2.5 (application) 更新马匹前台和后台展示：中文名缺失时使用外文原名作为主展示，并显示“中文名待补”质量提示。

## 3. P0 范围同步与队列

- [x] 3.1 (integration) 实现新版 P0 范围同步服务，从 active 有译名 horse term 和五地区重点赛事参赛/赛果证据生成 P0 来源。
- [x] 3.2 (integration) 支持重点赛事等级集合 `G1/G2/G3/JG1/JG2/JG3/JPN1/JPN2/JPN3`，并排除 Listed、Open、`LOCAL_GRADE`。
- [x] 3.3 (integration) 重点赛事、出赛表或赛果导入后，能够刷新 P0 范围、创建缺失 `HorseProfile` 并触发补全队列。
- [x] 3.4 (integration) 实现 P0 补全队列生成服务，按地区、资料缺口、近期新闻、重点赛事证据、术语优先级、外部匹配信号、候选状态和人工标记输出排序原因。
- [x] 3.5 (application) 扩展或新增管理命令，支持预览队列、按地区/profile id/limit 选择批次，并保证队列预览不写资料字段。
- [x] 3.6 (integration) 实现两层马匹身份判定：同场先按马号/来源身份分组，来源内 external horse ID 直接匹配；跨来源对数据库已有马使用多语种马名、父名、母名、出生年份四元组唯一匹配，歧义写入可无 profile 的专用 `HorseIdentityConflict`。
- [x] 3.7 (integration) 新增重点赛事参赛马只读候选提取，兼容历史导入的 `source_refs.primary/source_kind`，输出完整观察、保守去重候选池、五地区人工样本和 SHA-256 manifest；仅马名证据不得跨赛事合并。

## 4. 多地区来源候选与完整资料 artifact

- [x] 4.1 (integration) 定义统一补全候选 payload，覆盖 `basic_profile`、`pedigree`、`race_records`、`major_wins`、`aliases`、`source_evidence`、`raw_payload`、`confidence`、`failure_reason`。
- [ ] 4.2 (integration) 为日本、中国香港、英国、法国、美国实现或扩展受控来源 adapter，支持请求间隔、缓存、单批上限、source URL、raw payload 和字段覆盖统计。
- [x] 4.3 (integration) 为完整赛事履历生成 `HorseRaceRecord` payload，覆盖退赛、取消出走、未完赛、失格等状态，并记录 `records_synced_through` 或等价同步时间。
- [x] 4.4 (integration) 设计 `HorseRaceRecord` 幂等键，优先使用外部 race/result id；缺失时使用马匹、来源、日期/年份、比赛名、马场、source URL 组合。
- [x] 4.5 (integration) 主胜鞍沿用既有 `HorseRaceRecord` 胜利最高等级 + 人工 `is_major_win` 覆盖规则，不因 P0 来源重点赛事定义而改变。
- [x] 4.6 (integration) 扩展 artifact 写出，确保 JSONL、CSV、summary、失败/冲突清单和 source evidence manifest 包含审核状态、模块 diff、来源 URL、失败原因样例和下一批建议。
- [x] 4.7 (operations) 在 `.env.example` 和运行文档中补充 P0 补全请求开关、限速、缓存目录、批次大小、人工补录来源 URL 规则和生产默认保守值。
- [x] 4.8 (integration) 扩展 `HorseRaceRecord` 普通比赛快照、日期精度、实际出赛状态和跨来源规范键；支持海外远征多来源去重、来源证据合并，以及未关联普通履历在确认身份后安全回填 `RaceEvent` / `RaceEventResult`。
- [x] 4.9 (integration) 扩展履历完整度计算与 dry-run 指标，报告来源总出赛数、采集实际出赛数、跨来源去重数、缺口数、已关联/未关联赛事数、海外出赛数和逐马独立完整状态。
- [x] 4.10 (integration) 将逐场字段证据拆分为直接原始值、权威标准原始值和内部归一化值，并为三层分别保存来源 URL、时间与转换规则；法国 Class/英制距离在缺少当地权威证据时保持阻断。
- [x] 4.11 (integration) 将官方总数对齐与逐场权威性拆分，支持 `count_aligned_records_unverified`；Equibase 总数不得把 HRN 提升为官方逐场履历，只有独立批准并精确绑定冻结输入/记录唯一性/来源组成的窄批次 MAY 标记组合来源完整，且仍不得称为 Equibase 官方逐场。
- [x] 4.12 (integration) 对 HRN 正式请求、缓存复放和研究解析统一执行马名、父名、母名、出生年份四字段身份锁；迁移时将逐场权威性未知的旧 `complete` 履历降为 `needs_review`。
- [x] 4.13 (integration) 升级 source cache 身份与计数证据门禁：缓存自身马名/alias 必须命中请求马，来源总数必须保留来源名、URL 和带时区核验时间；网络 client 使用地区 HTTPS 主机白名单并逐跳校验重定向。
- [x] 4.14 (integration) 迁移降级旧未核验完整生涯时同步撤销整匹马聚合完整状态；正式赛果覆盖旧 `unknown` 时保留直接展示层并更新标准与归一化证据层。
- [x] 4.15 (integration) 同 provider 直接身份要求双方 external ID 一致且 namespace 不冲突；跨 provider 资料 payload 必须与候选完整四字段身份一致。总数证据门禁同时覆盖 cache、normalizer、数据库生涯 evaluator 和整匹马 evaluator。
- [x] 4.16 (integration) 研究 JSON/Excel 仅允许 `source_records_verified` 显示完整；支持官方总数为零时的空履历快照，并拒绝非零总数的空列表。
- [x] 4.17 (integration) 地区研究转换器从候选逐场 payload 独立复算全部生涯计数；同 provider 名允许规范化比较但 external ID 必须精确一致；官方总数 URL 使用 Django `URLValidator`。
- [x] 4.18 (integration) 将普通完赛归一为模型合法 `unplaced`，只有完整日期可通过生涯核心证据门禁，并对全部人工主 URL、佐证 URL 和血统 URL 使用严格 HTTP(S) 校验。
- [x] 4.19 (integration) 自动补充来源必须通过同源一致 ID 或双方完整四字段身份锁；审核 apply、数据库 evaluator 与 source client 统一严格 URL 门禁，总数证据按原子组替换，cache 硬字段执行类型和日期格式校验，研究摘要优先以官方总数计算缺口。
- [x] 4.20 (integration) 父母实体反查拒绝 name-only 唯一结果，external ID 按不透明原值比较；以输入 SHA 和逐行强身份 manifest 固化已审核历史血统证据，并让最终数据库 evaluator 严格复核历史 APPLIED 模块 URL。
- [x] 4.21 (integration) 将 `116` 条已审核 pedigree evidence 归并为 `55` 个全局唯一父母来源身份，要求每个 v2 `source_identity` 包含马名、父名、母名和出生年；绑定独立 `codex_manual_source_review` 出生年 artifact，并在搜索、证据、manifest、v2 JSON/Excel 全链路执行规范 provider + opaque external ID 一致性。
- [x] 4.22 (integration) 对自动 Netkeiba 父母候选执行精确 `https://en.netkeiba.com/db/horse/<id>/` 门禁，显式审计 Kentucky Wood 的 Balko 同名纠错；工作簿 builder 默认使用 v2 JSON、`-v2.xlsx`、`previews-v2`，环境变量覆盖配置且拒绝冻结 v1 workbook/previews 输出。
- [x] 4.23 (integration) 新增 pending-only prepare 与独立冻结 approved manifest 的美国组合来源审核链，双重绑定可信 v2/approved manifest SHA、10 匹四字段身份、Equibase 总数、记录唯一性与来源组成；仅精确匹配时离线派生 v3，不放宽全局 `count_aligned_records_unverified`。

## 5. 审核应用、后台运营和发布预留

- [x] 5.1 (integration) 收紧 commit 入口，只允许已审核通过的模块写入；未审核、低置信、歧义、来源不可用或字段锁定行必须跳过或创建候选。
- [x] 5.2 (integration) 实现审核后写入 `HorseProfile`、P0 来源、`HorseProfileDataCandidate` 和 `HorseRaceRecord` 的事务逻辑，保留 before/after diff、`source_refs` 和处理摘要。
- [x] 5.3 (application) 支持按模块应用/忽略/冲突处理，记录处理人、处理时间、结果摘要和 raw payload，不让冲突候选写入主表。
- [x] 5.4 (application) 扩展马匹后台列表筛选和排序，支持 P0 来源、无中文译名、完整资料状态、候选状态、批次来源、履历覆盖、新闻关联和人工锁定状态。
- [x] 5.5 (application) 在后台详情或 ready/发布动作前展示资料质量提示，包含完整资料硬字段、缺失字段、候选冲突、人工锁定跳过、完整履历同步时间和中文名待补状态。
- [x] 5.6 (application) 预留自动化状态和门禁字段，区分已发布马自动增量更新与未发布马自动首次公开；本阶段不启用自动首次公开。
- [x] 5.7 (operations) 对未处理 `HorseIdentityConflict` 建立每日管理员通知，复用现有运营通知通道并提供 Django Admin 筛选 URL、处理人、处理时间和解决资料页。
- [x] 5.8 (application) 将公开马匹详情页固定 20 条截断改为完整履历分页，支持日期正序/倒序；未关联普通比赛显示快照且不生成无效赛事链接。
- [x] 5.9 (application) 将 `IGNORED` 定义为不采用本次建议的追加式审核记录；完整度继续读取最近非 ignored 状态，避免撤销此前已应用证据。

## 6. 验证与生产试运行

- [x] 6.1 (application) 为 P0 来源同步、无译名术语、翻译原文保护、后台展示、队列生成和公开页面 no-network 边界补充 Django 测试。
- [x] 6.2 (integration) 为五地区 adapter、artifact 输出、模块审核门禁、人工锁定跳过、完整赛事履历和 `HorseRaceRecord` 幂等写入补充测试。
- [x] 6.3 (operations) 运行本地验证：`DB_ENGINE=sqlite python manage.py check`、目标 Django 测试、`makemigrations --check --dry-run`、`openspec validate complete-p0-horse-profile-data --strict`、`openspec validate --all` 和 `git diff --check`。
- [x] 6.4 (operations) 已完成五地区各 10 匹离线研究批次 dry-run，并确认研究 artifact、完整率、冲突和地区 blocker；因当前研究输入缺真实 production profile/reviewer/module approval，正式 commit-compatible artifact 与 production dry-run 尚未完成，继续 fail closed。
- [x] 6.4.1 (integration) 新增独立 `apply_reviewed_p0_horse_completion` prepare/dry-run/commit 链：显式消费 50 行 profile mapping decisions，绑定 v3/authority/mapping/production snapshot SHA，真实零写入模拟全部 schema 与 action，单事务锁定后幂等写入并整批回滚；能力与测试已完成，但真实生产 mapping artifact、正式生产 dry-run 和 commit 均未执行。
- [x] 6.4.2 (integration) 将正式执行拆为 Phase A prepare-only 与 Phase B trusted release SHA 解锁：candidate 不可自签，JSON 单次冻结字节读取并拒绝 symlink，HORSE term 限定复用，completion run 仅关联 artifact 明确认领记录；加入脱敏 `58f00961` 生产快照/50 行 mapping fixture，并在本地隔离 PostgreSQL 16 容器通过 serializable/advisory lock、同 artifact 并发 identity create 和异常整批回滚测试。当前 trusted allowlist 仍为空。
- [ ] 6.5 (operations) 部署前按运行手册确认 UmaNews 生产 `HEAD`、容器、`/healthz/`、外部导入运行数、导入锁、`.env` 备份和数据库备份。
- [ ] 6.6 (operations) 对已审核五地区样本 artifact 执行生产 commit，抽检 `HorseProfile`、P0 来源、`HorseProfileDataCandidate`、`HorseRaceRecord`、无译名展示、翻译保护和后台质量提示。
- [ ] 6.7 (operations) 每地区人工发布 1-2 匹完整资料马，验收公开索引、详情页、移动端、完整赛事履历、主胜鞍、关注入口、新闻 tag 和 no-network 边界。
- [ ] 6.8 (operations) 将 dry-run/commit/公开验收结果、失败原因、下一批建议和是否扩大批次写回 `docs/current_state.md`、`docs/project_status.md`、`docs/decisions.md` 和 `docs/deploy_runbook.md`。
- [x] 6.9 (integration) 为独立生涯完整度、异常结果实际出赛计数、跨来源/海外远征去重、多来源证据保留、未关联普通比赛、后续安全关联、跨单位距离和公开履历分页补充真实 Django 测试。
- [x] 6.10 (integration) 为五地区真实赛事来源字段、共享强身份键连通去重、后续血统回填与冲突、不同强身份同名马保留、同名弱身份隔离、非 P0 等级/地区排除、只读命令和 artifact manifest 补充回归测试。
- [x] 6.11 (integration) 用真实 HKJC `Overseas` 页面形状、Sporting Life `casualty.reason`、法国 `N/A` 权威补证及 Equibase 总数对齐场景补回归测试，并重新生成五地区 50 匹审核产物。
- [x] 6.12 (integration) 为 HRN 同名/同父母不同出生年、缓存身份错配、旧完整状态迁移降级、`unknown` 赛果正式补齐和 fallback 证据跨马去重补回归测试。
- [x] 6.13 (integration) 将既有 `P0HorseProfileDataCompletionTests` 整类纳入组合回归，并覆盖日本 10 匹离线重放、provider 大小写与 ID 冲突、非法总数 URL、ignored 保留 APPLIED 的真实路径。
- [x] 6.14 (integration) 覆盖第 4 名真实审核落库为 `unplaced`、年份精度在 dry-run/数据库均保持 partial，以及人工主 URL、佐证 URL和血统 URL 的非法主机/端口拒绝。
- [x] 6.15 (integration) 覆盖同名补充来源身份不足、审核与数据库非法 URL、总数证据组借用旧值、cache 类型/日期错误，以及官方总数与备用来源总数不一致的 fail-closed 回归。
- [x] 6.16 (integration) 覆盖父母实体唯一同名不自动采用、external ID 大小写/标点不折叠、历史血统审核 manifest 的输入/逐行漂移阻断，以及历史 APPLIED 非法模块 URL 阻断。
- [x] 6.17 (integration) 覆盖父母来源身份四字段、全局 provider + opaque ID、Balko 纠错、严格 Netkeiba URL、v2 工作簿默认与 frozen v1 保护；最终 Python 组合回归 `282/282`，Node summary/path、公式错误扫描和 9 张预览通过。
- [x] 6.18 (integration) 覆盖 pending-only prepare、自签/可信 SHA、记录唯一性及输入/来源/计数/身份漂移的 fail-closed 回归，验证 Fort George 6/6/1、其余 9 匹 HRN-only 和研究派生 50/50；生成零写入 v3、research module-review 与 blocked 静态 production readiness SHA 链，明确未运行正式 simulation 且不声称 commit-compatible。
