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

## 4. 多地区来源候选与完整资料 artifact

- [ ] 4.1 (integration) 定义统一补全候选 payload，覆盖 `basic_profile`、`pedigree`、`race_records`、`major_wins`、`aliases`、`source_evidence`、`raw_payload`、`confidence`、`failure_reason`。
- [ ] 4.2 (integration) 为日本、中国香港、英国、法国、美国实现或扩展受控来源 adapter，支持请求间隔、缓存、单批上限、source URL、raw payload 和字段覆盖统计。
- [ ] 4.3 (integration) 为完整赛事履历生成 `HorseRaceRecord` payload，覆盖退赛、取消出走、未完赛、失格等状态，并记录 `records_synced_through` 或等价同步时间。
- [x] 4.4 (integration) 设计 `HorseRaceRecord` 幂等键，优先使用外部 race/result id；缺失时使用马匹、来源、日期/年份、比赛名、马场、source URL 组合。
- [x] 4.5 (integration) 主胜鞍沿用既有 `HorseRaceRecord` 胜利最高等级 + 人工 `is_major_win` 覆盖规则，不因 P0 来源重点赛事定义而改变。
- [ ] 4.6 (integration) 扩展 artifact 写出，确保 JSONL、CSV、summary、失败/冲突清单和 source evidence manifest 包含审核状态、模块 diff、来源 URL、失败原因样例和下一批建议。
- [x] 4.7 (operations) 在 `.env.example` 和运行文档中补充 P0 补全请求开关、限速、缓存目录、批次大小、人工补录来源 URL 规则和生产默认保守值。
- [x] 4.8 (integration) 扩展 `HorseRaceRecord` 普通比赛快照、日期精度、实际出赛状态和跨来源规范键；支持海外远征多来源去重、来源证据合并，以及未关联普通履历在确认身份后安全回填 `RaceEvent` / `RaceEventResult`。
- [x] 4.9 (integration) 扩展履历完整度计算与 dry-run 指标，报告来源总出赛数、采集实际出赛数、跨来源去重数、缺口数、已关联/未关联赛事数、海外出赛数和逐马独立完整状态。

## 5. 审核应用、后台运营和发布预留

- [x] 5.1 (integration) 收紧 commit 入口，只允许已审核通过的模块写入；未审核、低置信、歧义、来源不可用或字段锁定行必须跳过或创建候选。
- [x] 5.2 (integration) 实现审核后写入 `HorseProfile`、P0 来源、`HorseProfileDataCandidate` 和 `HorseRaceRecord` 的事务逻辑，保留 before/after diff、`source_refs` 和处理摘要。
- [ ] 5.3 (application) 支持按模块应用/忽略/冲突处理，记录处理人、处理时间、结果摘要和 raw payload，不让冲突候选写入主表。
- [x] 5.4 (application) 扩展马匹后台列表筛选和排序，支持 P0 来源、无中文译名、完整资料状态、候选状态、批次来源、履历覆盖、新闻关联和人工锁定状态。
- [x] 5.5 (application) 在后台详情或 ready/发布动作前展示资料质量提示，包含完整资料硬字段、缺失字段、候选冲突、人工锁定跳过、完整履历同步时间和中文名待补状态。
- [x] 5.6 (application) 预留自动化状态和门禁字段，区分已发布马自动增量更新与未发布马自动首次公开；本阶段不启用自动首次公开。
- [x] 5.7 (operations) 对未处理 `HorseIdentityConflict` 建立每日管理员通知，复用现有运营通知通道并提供 Django Admin 筛选 URL、处理人、处理时间和解决资料页。
- [x] 5.8 (application) 将公开马匹详情页固定 20 条截断改为完整履历分页，支持日期正序/倒序；未关联普通比赛显示快照且不生成无效赛事链接。

## 6. 验证与生产试运行

- [x] 6.1 (application) 为 P0 来源同步、无译名术语、翻译原文保护、后台展示、队列生成和公开页面 no-network 边界补充 Django 测试。
- [ ] 6.2 (integration) 为五地区 adapter、artifact 输出、模块审核门禁、人工锁定跳过、完整赛事履历和 `HorseRaceRecord` 幂等写入补充测试。
- [x] 6.3 (operations) 运行本地验证：`DB_ENGINE=sqlite python manage.py check`、目标 Django 测试、`makemigrations --check --dry-run`、`openspec validate complete-p0-horse-profile-data --strict`、`openspec validate --all` 和 `git diff --check`。
- [ ] 6.4 (operations) 先在本地或生产备份副本执行五地区各 10 匹 dry-run，确认 artifact、完整率、冲突、请求量和地区 blocker。
- [ ] 6.5 (operations) 部署前按运行手册确认 UmaNews 生产 `HEAD`、容器、`/healthz/`、外部导入运行数、导入锁、`.env` 备份和数据库备份。
- [ ] 6.6 (operations) 对已审核五地区样本 artifact 执行生产 commit，抽检 `HorseProfile`、P0 来源、`HorseProfileDataCandidate`、`HorseRaceRecord`、无译名展示、翻译保护和后台质量提示。
- [ ] 6.7 (operations) 每地区人工发布 1-2 匹完整资料马，验收公开索引、详情页、移动端、完整赛事履历、主胜鞍、关注入口、新闻 tag 和 no-network 边界。
- [ ] 6.8 (operations) 将 dry-run/commit/公开验收结果、失败原因、下一批建议和是否扩大批次写回 `docs/current_state.md`、`docs/project_status.md`、`docs/decisions.md` 和 `docs/deploy_runbook.md`。
- [x] 6.9 (integration) 为独立生涯完整度、异常结果实际出赛计数、跨来源/海外远征去重、多来源证据保留、未关联普通比赛、后续安全关联、跨单位距离和公开履历分页补充真实 Django 测试。
