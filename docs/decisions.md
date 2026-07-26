# 关键决策

## 2026-07-24 首页人工头条实现完成（代码就位，待审核与发布）

- 已按审核通过的方案实现 HomepageHeadlineSelection / HomepageHeadlineRecommendation
  模型、服务层、signals 协调、admin 修复、路由、视图和模板。
- 具体实现与 `docs/changes/add-editorial-headline-control/design.md` 的通过版本一致。
- 未实际发布，不授权部署或生产写入。

## 2026-07-24 首页人工头条采用唯一控制行，AI 推荐保持独立记录

- 规划中的首页人工头条不在 `NewsArticle` 增加 `is_headline` 布尔字段。全站唯一头条是跨文章不变量，
  用多文章布尔字段会把替换、并发和残余状态分散到多行，也容易让 Django Admin 绕过资格与审计。
- 方案采用固定 `homepage_primary` slot 的 `HomepageHeadlineSelection` 单例控制行；所有设置、替换、
  取消、接受推荐和失效协调锁同一行，并用 `version` 拒绝陈旧页面。数据库以固定 slot
  CheckConstraint 和 `UNIQUE(slot)` 保证当前版本全库只有一个合法控制位。
- AI 编辑推荐使用独立 `HomepageHeadlineRecommendation` 快照和 active 条件唯一约束。推荐生成只读取
  已保存的赛事优先级、自动分数、封面和发布时间信号，不新增第二套 LLM 调用；生成推荐永不写 selection，
  只有有权限用户明确接受后才可切换人工头条。
- 头条统一资格要求文章当前已发布、网页公开时间不在未来、有效标题/摘要/正文非空；不强制封面。
  人工选择、AI 推荐和算法 fallback 共用该资格；选择失效时清除人工状态并记录审计，保留原有三级时间
  窗口、48 篇合格候选和排序元组，避免无效文章被算法立即选回。
- 首页当前没有页面级或 headline cache，本变更不为头条新增缓存；实时性通过数据库读取和连续请求验证。
  若后续需要 cache，必须另行补 key、TTL、事务提交后失效和故障回退设计。
- 本决策已由同一独立方案 reviewer 三轮收敛并获得 `VERDICT: APPROVED`；最终字段和文件范围以
  `docs/changes/add-editorial-headline-control/` 的通过版本为准。当前只完成规划，尚未授权实现或发布。

## 2026-07-24 已审核空胜绩采用显式证据语义并版本化发布候选

- “没有胜绩记录”不再等同于“胜绩资料缺失”。有实际胜绩沿用原判定；没有实际胜绩时，只有最新
  非 ignored 的 `major_wins` 候选为 `applied`、审核结论为 `approved`、payload 精确为空列表，
  且记录执行人、执行时间，才表示“已审核确认无胜绩”。未审核、非空 payload、pending、
  conflict、rejected 均继续阻断，不伪造胜场、不绕过严格完整度。
- 完整度语义会改变同一审核输入能否提交，因此属于发布候选的安全属性。新 artifact 和 candidate
  统一绑定 `p0-horse-full-profile-completeness.v2`，所有 candidate/v2 release 加载与重算路径
  必须精确校验；历史 v1 artifact 继续可信 v1 dry-run 验证兼容，任何 v1 commit 明确拒绝。
- 手工 ready 复审无胜绩马时，新的 `major_wins` 审计必须继续保存空列表，不能写入较新的非空
  手工标记而使档案立即重新不完整。
- 旧 candidate 即使已有正式批准，只要尚未完整落库，就不能跨策略版本恢复。保留旧
  candidate/release/ledger 作为审计证据；部署新受审版本后从冻结 bundle 重做 prepare-release。
  发布授权必须在最新成功 review 后取得，review 前的持续授权或预授权不替代该门禁；对象、动作
  或公开范围漂移必须 fail closed。

## 2026-07-23 P0 正式提交拆分为无批准候选与独立批准

- 人工 xlsx 内容复审不等于生产写入批准。bundle 之后先执行 `prepare-release`，冻结完整子集、
  commit artifact、预计数据库动作与自动首发范围到精确 candidate SHA；candidate 不含
  `approved_by`，不写 `release_approved`，不写业务表或公开状态。
- 新 rolling release 只生成 `p0_horse_production_release_manifest.v2`，并反向绑定真实 candidate
  SHA；v1 仅用于历史证据的只读复验，不再允许 builder 新建 v1 批准。正式 commit 和 standalone
  apply 都必须验证 candidate 普通文件、完整 SHA、batch/state、准备事件与有序批准账本；
  superseded 或 abandoned candidate 永久 fail closed。
- 自动首发授权集合来自已复审 artifact，而不是地区 batch manifest。只有冻结 disposition 为
  `attempt_publish_after_commit` 的对象可进入 live gate；hidden、manual lock、already published
  以及未进 artifact 的 blocker 只进入排除审计，后续状态放宽不能扩大原批准。
- 文件证据采用按 SHA 命名的不可变快照；账本严格解析 malformed/partial 行并在 append 后
  flush/fsync。候选替换顺序固定为“写新 manifest（未批准）→ supersede 旧批准 → approve 新
  manifest”，防止崩溃时新旧同时 active。
- batch state lock 保护产物与 checkpoint 的短事务，execution lock 串行化正式批准、DB apply、
  publish/retry 与 abandon。abandon 只允许尚未落库批次；已 committed 的数据库事实不能通过改
  state 伪装撤回。execution lock 必须按同线程同 batch 可重入实现，锁顺序固定为
  execution -> state；standalone v2 同样从 validation 持锁到数据库事务退出。artifact 尚未
  committed 时必须复验 current batch manifest/combined SHA；只有精确 artifact path+SHA 的
  committed completion run 可改用不可变 snapshot 恢复。
- publish completed 是一次性终态证据，不是“可重新计算”的当前 gate。相同 candidate 的普通
  重复 commit 必须返回冻结 publish checkpoint/report，不得因人工降级、解除 manual lock 或其他
  gate 放宽再次调用发布。publish 未完成或失败只允许显式 `--retry-publish`；普通 commit 不兼任
  发布恢复入口。
- `prepare` 也属于同 batch execution window；锁顺序固定为 `execution -> state`，不得让 commit
  在 prepare 的 artifact、workbook 或 checkpoint 更新中途读取证据。
- prepare-release 的锁合同必须位于 public service，而不能只依赖 management command。所有 direct
  caller 先取得同 batch execution lock，再进入 state serial lock；等待后必须复读 manifest/state。
  committed 或 abandoned 终态只允许零写拒绝，不得生成新 candidate 或补写 state/ledger。
- completed 重放不是仅凭 state checkpoint 的快捷返回。它必须在任何 dry-run/DB apply/publish 前
  复验冻结 candidate、artifact/release、commit/publish checkpoint、committed completion run，
  并要求唯一精确匹配的 v2 `auto_first_publish` 成功账本事件。证据缺失、重复或报告计数/ID/
  frozen exclusions 不匹配时只允许人工审计，禁止自动补账本、重算 checkpoint 或写数据库。

## 2026-07-23 task 5.2 分叉生产线执行决定

- 本次已批准 task 提交与生产 HEAD 从共同父提交分叉：切换会回退并行已上线功能，合并会产生
  未获本次精确授权的新 SHA。为同时保住生产运行态和授权对象，本次只把目标 Git tree 构建为带
  完整 revision label 的一次性任务镜像，未替换在线 web/worker/beat/race_live_worker。
- 本次网络权限缩到一次性 prepare 容器：生产 `.env` 和在线应用保持 false，仅该容器覆盖 true。
  容器退出后确认其已不存在、四应用 false，生产 HEAD、马匹计数和 healthz 均未变化。
- 本次一次性执行仅完成 task 5.2 的 prepare/xlsx，不是公网应用版本切换，也没有扩大数据写入
  授权；未执行 bundle、commit 或自动首发。后续动作仍受既有精确 artifact/hash 授权边界约束。
## 2026-07-23 Codex 原生流程增加“用户确认实现”，HRN 正文按来源可信容器修复

- 项目主流程更新为“探索 -> spec/design -> 方案审核 -> 用户确认实现 -> 测试先行 -> 子代理实现 ->
  独立 reviewer 会话 `/review` -> 用户授权后发布”。方案审核通过后必须汇报根因、范围、测试/RED、
  历史数据边界、风险/回滚和 reviewer 结论；用户明确确认实现前不得写测试、改应用代码/配置/迁移、
  启动实现 subagent 或重处理历史数据。
- HRN 正文边界问题按来源 DOM 结构解决：真实正文容器 `.article-body` 是主边界，选择器缺失时 fail-closed；
  不使用文章 ID、公开中文词黑名单、翻译 prompt 或模板/CSS 隐藏替代抓取修复。
- 新采集修复、历史候选识别、历史文章重处理和生产部署是独立门禁。历史识别只读、分批并输出哈希；
  部署前已存在的 HRN 文章一律留在历史 scope。历史写入必须绑定精确批准 manifest 及 file SHA，在事务锁行后
  复核全集与逐篇输入/输出哈希，任一漂移整批零写入；备份和另一次明确授权仍是前置条件，人工正文默认不自动覆盖。
## 2026-07-23 netkeiba 解析版本、旧批处置与生产授权拆分

- 会改变 canonical payload 的 netkeiba 解析规则必须递增显式 parser version；版本同时
  绑定批次输入 fingerprint 与日本 netkeiba canonical cache。只失效 checkpoint 而继续
  命中旧 cache 仍会绕过新解析器，因此不接受。
- stale netkeiba cache 在网络刷新成功后必须通过独立 sidecar 文件锁与 `os.replace` 原子
  替换；竞争调用若已发布当前版本则复用该 payload。普通 cache 首写仍使用 no-clobber，
  JBIS 和其他地区不进入替换路径。
- prepared 批次中的 blocker payload 也按候选成功落 checkpoint。解析器变化后不手改
  state、不直接 resume 旧 approved manifest；旧批保留证据并 abandon，重新 select/approve。
- 页面事实不足时继续阻断：Haru Aube 的空着顺水沢行不因存在马号/骑师就推断为实际出赛
  或取消；部分 expected identity 继续要求完整四字段，不因来源页面本身完整而放宽候选锁。
- 生产授权按不可变对象拆分：受审代码版本绑定部署/触网授权；prepare 与人工 xlsx 复审后
  再冻结 bundle/hash；生产 commit 与自动首发必须取得绑定精确 bundle/hash、完整子集和
  公开范围的新授权。触网窗口在 prepare 成功或异常后立即恢复 false，不跨人工审核。

## 2026-07-22 日本滚动补全来源：netkeiba ID 直取优先，JBIS 检索兜底

- 日本候选持有 netkeiba key 时，select 阶段 `source_namespace` 直接取 netkeiba 并走
  `_NetkeibaClient`（马匹页 + 战绩页 + 血统页 3 页直取，provider-bound 身份）；无 key
  候选保持 `_JBISClient` 名称检索。其余多 key 场景保持 identity_keys 顺序扫描（不用
  frozenset 迭代，保证跨进程确定性）。
- netkeiba 与 JBIS 身份空间不同源：netkeiba key 不代表 JBIS ID；不做 netkeiba 失败
  中途回退 JBIS（预算与身份语义都不允许）。日本每候选请求预算 3→4（3 页 + 1 次
  redirect 余量）。
- netkeiba 页面解析不猜值：结构不识别、年份生日、未白名单毛色、未知单字产地一律
  fail closed 阻断候选；生涯总数取马匹页「通算成績」并与逐场对账（不一致由既有
  adapter gap 逻辑处理）；异常状态 `取消/除外` 不计出赛、`中止/失格` 计出赛。
- ExternalHorse 存量空四字段（12,405 条）不在本 change 批量修复，仅随批次自然覆盖；
  批量修复如需进行另立专项。

## 2026-07-22 发布资格时间、积压时效和历史恢复

- `first_seen_at` 表示“系统何时看见新闻”，不能代表“新闻何时通过全部发布门禁”。新增
  `publish_ready_at` 作为唯一发布资格时钟；只在非 ready→ready 时设置，重复任务不得续期。
  历史值不猜测、不回填，避免旧稿被伪装成新稿。
- 自动消费时效固定为 `0–24h`；`24–72h` 只人工复核，`>72h` 只显式处置。实时候选和积压候选
  各自有查询上限，积压默认关闭并按地区灰度。任何通道都不改变原有每窗口、每地区或全站配额，
  不放宽来源、门禁、去重、评分或 QQ 规则。
- 当前历史候选一律先生成 SHA manifest，默认 `keep_manual`。逐篇恢复必须由独立 decisions
  文件、reviewer、封印后的精确 SHA 和 apply 确认共同授权；内容、状态、门禁或更新时间漂移即
  跳过。恢复只刷新通过完整重校验文章的 `publish_ready_at`，不直接公开也不创建 QQ delivery。
- 用户已确认 2026-07-22 manifest 中的精确 21 篇全部舍弃。舍弃使用新增
  `discard_ignored` 审核动作，沿用后台“忽略候选新闻”语义，将 workflow/review/automation
  三层状态统一改为 `ignored` 并记录 `ignored_at`；不物理删除文章。该动作仍受 reviewer、原始
  快照、新 manifest SHA、逐行锁和漂移拒绝约束，并记录在
  `decision_reason.publish_ready_recovery`；重复 apply 必须幂等，公开和 QQ 账本不得变化。
- 生产灰度顺序仍是“部署且开关关闭 → 只读预览 → 单地区 4 个窗口 → 五地区 → 24 小时观察”；
  这不是 shadow，但开关和地区 allowlist 仍是即时止损面。

## 2026-07-22 遗留 CrawlJob 使用 SHA manifest 和条件终态

- `CrawlJob(status=started)` 超过 60 分钟不等于执行已死亡。dry-run 必须记录 Celery active/reserved 和有效生产窗口租约；Celery 无回应、任务无法映射来源或租约未过期时 fail closed。
- apply 必须绑定不可覆盖的 manifest 和 SHA-256，逐行加锁复核 status/started_at/source 未漂移，并使用有界批次。历史审计数 `32` 只作基线，不是直接写入清单。
- 抓取执行只能以 started→success/failed 条件更新抢占终态。未抢到终态的迟到任务只记录 `terminal_state_already_claimed`，不得覆盖 CrawlJob 或 `NewsSource.last_crawl_*`。

## 2026-07-22 P0 BASIC 层公开发布门禁与自动首发

- 公开展示最低门槛为 BASIC 层：名称 + 五地区地区 +（`horse_identity_verified_keys`
  含 netkeiba/nar/hkjc/sporting_life 认可 namespace 的 key，或父/母/出生日期三字段
  齐全）。verified 身份只由 fail-closed 身份回填 commit 或人工批准批次 commit 写入；
  sync 按名称归属写入的扁平 `horse_identity_keys` 不产生公开信任。
- 滚动批次地区 commit 通过幂等复验后自动首次发布本地区马（含批次 create_new 新建马，
  经 completion run 反查）；`published_by` = 批次 commit 审核人，不设系统用户；
  `auto_first_publish_enabled` 死字段保持预留不启用，opt-out 用
  `manual_lock_flags.auto_publish_blocked`。
- hidden 或曾 hidden（`hidden_at` 非空）的马任何自动/批量通道都不得发布，必须人工
  重新发布；这是隔离 `mark_profile_completion_ready` 把 hidden 复活为 ready 的既有行为。
- 发布失败不得进入批次 committed 终态；同 artifact 全量重 commit 会被快照漂移检查
  fail closed（既有行为），发布失败恢复走 `--retry-publish` 专用阶段，且 retry 必须核验
  commit artifact 的 `idempotent_verification.passed`。
- 主规格 `horse-profile-pages`"只有管理员审核发布后才进入前台"按三种发布路径（人工 /
  批次审核后自动首发 / 批准的存量批量发布）修订，全部经同一 `transition_review_status`
  审计通道；首批验收（2026-07-21 已完成）前仍只允许人工发布。
- 未完整公开马统一显示「资料补全中」徽章；`空壳/仅基础资料/部分血统` 等内部措辞不出现在
  公开页，`completeness_status` 仍是唯一事实源。

## 2026-07-22：去让赛混合标记对象一律进 review；最终复审沿用 Claude Code 等价复审

- 代码复审 P1：term 5087（`THE KWANGTUNG HANDICAP CUP (HANDICAP)` / `广东让赛杯(让赛)`）原文同时含未括号 handicap（赛事名组成部分）与括号 (HANDICAP)（补充说明），既有兜底删除会错改为「广东杯」。决策：凡原文去除括号标记后仍含 handicap 完整词或四种中文让赛标记的对象，一律进 review 桶保持原值，不写入；京成杯锁定例外（`京成杯秋季让赛`→`京成杯秋季赛`）显式豁免该守卫。term 5087 与 5570 留待人工决定展示名，另走受控流程。
- 本任务最终复审沿用 2026-07-21 先例：codex CLI 不可用、原 codex reviewer 会话无法恢复，由 Claude Code 对精确候选做等价完整只读复审（首轮 REVISE → 修复 → 同一 reviewer 限定复审 APPROVED，P0/P1/P2 清零，审前/审后 fingerprint `2889f4b2…` 一致）；不以测试通过或普通 diff 替代复审。
- 发布授权：用户 2026-07-22 针对精确版本（提交 `5b491561` + artifact SHA `30d85d1a…`，168/1550/2/0）回复「发布吧」；发布报告见 `docs/changes/remove-handicap-markers-from-race-names/release_report.md`。

## 2026-07-22 P0 身份回填写入门禁加固

- 离线冲突 fingerprint 为裸 SHA-256 hexdigest（64 字符），"offline" 作用域编进被哈希
  内容而不是字符串前缀；任何指纹格式必须满足 `HorseIdentityConflict.fingerprint`
  `max_length=64`，禁止再以 SQLite 不校验长度为由放行超长值。
- 批准后的 manifest 在 commit 时必须重算哈希并与存储值、操作者提供值双重比对；只比
  存储值等于把批准后的 manifest 篡改视为可信。artifact 文件 SHA 另独立校验。
- commit 是第二道 fail-closed 防线：dry-run 之后 profile 发生漂移（同 namespace 出现
  其他 key、四字段与证据矛盾）时整个候选丢弃并记冲突，不写部分身份；identity key
  一律 casefold 写入（含 HKJC 字母数字 ID），原始大小写只留在 `identity_evidence`。
- 证据判级按行来源 namespace 核验：可识别为其他 provider 的 `horse_id` 不得贴上本
  地区预期 provider 的标签（如 UK 行上的 racing_post ID 不得写成 sporting_life key）；
  无法识别来源的行保持既有行为并留待后续治理。

## 2026-07-21：赛事展示名让赛处理以原文括号形式为准，京成杯为例外

- 用户明确修订让赛清理规则：原文名（RaceEvent.original_name / RaceSeries.canonical_name_original / TermEntry.source_ja）中 handicap/让赛 被括号圈住时，视为赛事补充说明，中文展示名删除该标记；未被括号圈住时，视为赛事名组成部分，保留。所有案例按此规则判定，不再设"条件描述型豁免"的独立逻辑。
- 京成杯是唯一例外：凡展示名为"京成杯秋季让赛"的对象（日本 RaceSeries 285、术语 1972/15215）一律改为用户此前逐字锁定的"京成杯秋季赛"，与 2026-07-21 已写入生产的系列 6125、Event 96 和 2010–2025 共 16 场历史赛事保持一致；该例外不与"Keisei Hai Autumn H 原文 H 无括号"的新规则冲突处理，而是显式锁定值。
- 删除机制沿用"只删不补"：仅删除四种中文让赛标记及直接包裹该标记的中英文括号，不补写"锦标""大赛"等新词；删除后无中文字符、同地区重名等校验失败的对象只报告、不写入。
- 本规则取代 2026-07-20"让赛不展示一律删除"的口径；范围仍限定赛事日历对象与 race 术语 target_zh，不回填历史文章、不新增术语。

## 2026-07-20 P0 来源地区与幂等修复边界

- `HorseProfile.racing_region` 是既有档案属性，不因本批样本归属自动覆盖；
  `HorseP0Source.racing_region` 必须记录已审核候选的 `sample_region`。候选地区与研究顶层
  地区冲突时，artifact 生成直接失败，不允许以旧档案地区替代本批审核事实。
- 旧 artifact 的幂等重跑只允许修复仍属于同一 artifact、同一 completion run 且状态为
  active 的确定性来源地区。来源已撤销、已转属新 run 或 evidence artifact SHA 不同，
  均 fail closed；不得借幂等重跑覆盖后续人工决定、证据、状态或审计归属。
- 首次成功 run 的 summary 固定保存首次写入结果；后续幂等核验写入独立
  `last_idempotent_verification`，不得把首次 `database_write_count` 覆盖为 `0` 或修复数量。
- P0 完整资料落库与首次公开继续分离。无中文译名马可以完整、待发布并在翻译中保护原文，
  但本批不自动发布；每地区首批公开样本仍需单独人工动作和公开面验收。

## 2026-07-20 P0 PostgreSQL 迁移事务边界

- 对会更新已有 `HorseRaceRecord` 的字段回填，不在同一原子迁移的后续 operation 创建该表
  的索引或约束。迁移按 schema fields、data backfill、indexes/constraints、authority
  顺序拆为 `0049-0052`，让前一事务的 trigger events 在后续 DDL 前结束。
- 每个迁移继续使用 Django 默认原子事务；禁止用 `atomic=False` 留下可见的半 schema。
  生产首次失败已完整回滚，二次 Phase A 必须从确认的 `0048` 状态重新开始。

## 2026-07-20 P0 美国组合来源批准与生产提交边界

- 用户/项目负责人确认当前冻结批次采用以下美国组合来源可满足项目严格完整标准：HRN 为逐场
  主记录；Fort George 由 Sporting Life 与 Racing Post 补齐；Equibase 只承担官方总出赛数、
  身份和颜色对账。该批准是批次限定、经独立批准的组合来源完整，不得表述为 Equibase 官方
  逐场履历，不得全局放宽 HRN 或 `count_aligned_records_unverified`。
- 冻结 v1/v2 JSON 字节保持不变：v1 SHA-256
  `55d80abed2b76a2d7fcf0cb97aadff800c3130c3815e84d8e6eb5b1c16b4befd`；v2 SHA-256
  `a1184dbfb0257ecbe2a4ddbc4e729b0a74d73f911c8d52a20ab65854520325b7`，并继续保留原口径
  `40/50`。独立批准 manifest SHA-256 为
  `29091d69573bab907cda2e9a081ae4684838b92d1f9b052a7601b6109a541077`；由此生成的 v3
  研究派生物 SHA-256 为
  `98a7019a400f10a4bf961d869f38f770e9e98afab76b557a3c784d4eff6e470e`，只在研究层达到
  `50/50`，不能反向改写冻结 v2。
- prepare 只能生成 pending 准备稿；当前 pending SHA-256 为
  `8aba561b856ffbdcd03c2a59228b166315174b539f20aef4ae6412bfe03b1b61`。apply 必须同时绑定
  固定 v2 SHA、可信 manifest SHA、调用方显式 SHA 和实际文件 SHA；记录、身份、来源、计数
  漂移或重复记录必须 fail closed。
- research module review SHA-256
  `1440550a3e4d203b604b9dba74b89b2f49ee7075bc168f35e756e54830f31db1` 的独立 reviewer
  第三轮结论为 `APPROVED`，只批准研究模块及该批次来源组合，不替代生产 artifact、formal
  dry-run 或准确集成版本的生产授权。
- production readiness report SHA-256
  `8cc36106091708827852401927a791a5575f2d6d490d1a306297e450612ed2c5` 仅为
  `static_schema_compatibility_check`，明确
  `safe_simulation_performed=false`、`commit_artifact_compatible=false`、
  `decision=blocked`、`database_write_count=0`。用户本次“继续推进”不构成生产写入授权；
  正式 commit artifact 与 formal production dry-run 完成后仍须重新申请精确授权。

## 2026-07-19 P0 父母出生年、全局来源身份与 v2 冻结规则

- `116` 条已审核血统证据必须解析为 `55` 个唯一父母来源身份；每条 v2 `source_identity`
  必须同时含 `horse_name`、`sire_name`、`dam_name`、`birth_year`，不得保留 name-only 或
  name + known sire legacy method。
- 父母出生年使用独立 approved artifact
  `runtime/horse_profile_completion/pedigree-research-20260719/reviewed_parent_birth_year_evidence.json`，
  SHA-256 为 `ed9f6419dccd41485b96884410ea9ab5976d8ab5ba2acfb97e03837a7a3deb54`，
  `reviewed_by=codex_manual_source_review`。这 `55` 个出生年不记为项目负责人逐字段提供或审核；
  parent identity manifest 只绑定该独立证据及既有审核上下文。
- provider namespace 可以规范化，external horse ID 必须在搜索候选、出生年证据、逐行 manifest、
  v2 JSON 和工作簿全链路按不透明原值精确一致；同 provider 不允许大小写、标点删除或其它
  近似匹配改变 ID。
- 自动 Netkeiba 父母候选只接受精确
  `https://en.netkeiba.com/db/horse/<id>/`。URL 含凭据、显式端口、query 或 fragment 时必须
  fail closed，即使主机名和路径前缀看似正确也不能进入 v2。
- Kentucky Wood 的父系 Balko 必须保留显式纠错审计：Netkeiba `000a02bd3f` 是 1925 年同名马，
  只留在冻结 v1；v2 使用 Racing Post `595446`、出生年 2001、父 Pistolet Bleu、母
  Ella Royale。纠错不得回写或重造 v1。
- 冻结 v1 JSON / workbook SHA-256 分别为
  `55d80abed2b76a2d7fcf0cb97aadff800c3130c3815e84d8e6eb5b1c16b4befd` /
  `4b68b87a076793eab0acc2357762afbd0c0fcaf2282fcf4122e3a2a855c2b696`；最终 v2 JSON /
  parent identity manifest / workbook SHA-256 分别为
  `a1184dbfb0257ecbe2a4ddbc4e729b0a74d73f911c8d52a20ab65854520325b7` /
  `b211d9040814b0b56ec30e8ef8930fdc10f4140a3a660cf491fcae12d0b6ab2b` /
  `f67ad84408e68af69f14e2eef06e7135ca0b19cfc4fd18faf8925798acdbb1eb`。
- 工作簿 builder 默认读取 v2 JSON、输出 `-v2.xlsx` 和 `previews-v2`，环境变量优先于配置；
  冻结 v1 workbook 与 previews 目录是拒绝写入目标。本决定只固定只读审核产物和生成边界，
  不授权生产写入、部署、发布或网络 career crawl。

## 2026-07-19 P0 来源缓存必须自证身份、计数证据和安全出站目标

- `p0-horse-source-cache.v2` 不得用当前请求的马名补齐缓存身份。所有地区复放前必须由缓存
  `identity.horse_name` 或缓存 alias 命中请求马名；美国或提供了预期血统的候选还必须完整命中
  父名、母名和出生年份。
- 来源总出赛数只有在同时保存非空来源名、HTTP(S) 来源 URL 和带时区核验时间后才可参与
  `complete` 判定。数量相等但三项证据任一缺失时保留 `partial`，不虚增数量缺口。
- 受控来源 client 采用登记 HTTPS 主机白名单、禁止凭据 URL 和非 443 端口、关闭 transport
  自动重定向并逐跳校验 `Location`；重定向请求继续消耗同一单马预算。当前登记主机仅为
  JBIS、HKJC、Sporting Life、Geny 和 HRN 的实现目标。
- 引入逐场权威状态时，旧的未核验 `complete` 不仅降级生涯状态；若聚合状态为
  `complete_profile_full`，也必须降为 `complete_pedigree_2gen`。跨来源正式赛果覆盖旧
  `unknown` 时保留旧直接展示值，标准原始值和归一化值改用正式来源证据。
- 候选来源与资料 payload 来源不同时，来源内 external ID 不能互证；候选必须提供完整四字段
  身份并与 payload 一致，或以后使用显式人工审核的跨来源绑定。只有同名/alias 时 fail closed。
  同 provider 也只有在候选和 payload 都携带一致 external ID 时可直接绑定；显式来源 namespace
  与 `external:<provider>:...` key 冲突时必须拒绝。
- 总数证据门禁必须同时存在于 cache validator、履历 normalizer、数据库生涯 evaluator 和
  整匹马聚合 evaluator，不能假设所有调用都经过同一入口。研究 JSON 与工作簿只有
  `source_records_verified` 可显示完整，其它或非法 authority 均保持受阻/待审。
- `source_start_count=0` 是合法官方事实；此时空逐场列表可通过数量对齐校验。总数大于零时，
  空列表仍是完整履历缺口。
- 同 provider 比较对 provider namespace 做 NFKC/大小写归一，但 external horse ID 按来源
  原值精确比较；名称大小写不能绕过 ID 冲突。总数 URL 使用 Django `URLValidator`，不以
  scheme/netloc 粗判替代合法 URL。
- `IGNORED` 表达“本次建议不采用”，不是撤销既有已应用证据。模块完整度读取最近一条非
  ignored 审核状态；若不存在此前 APPLIED，或最近非 ignored 状态为 conflict/pending，仍阻断。
- 一次性研究转换必须在函数内部从实际逐场记录复算数量，真实离线 replay 样本纳入测试；不能
  依赖调用环境残留变量或仅测试冻结最终 JSON。
- 逐场结果状态必须使用 `HorseRaceResultStatus` 的正式枚举；第 4 名及以后和来源 `finished` /
  `unplaced` 统一归一为 `unplaced`。只有 `race_date_precision=exact` 的记录可满足逐场核心
  证据门禁；年份精度记录照常保存，但不能在 dry-run 中先宣称完整。
- 所有人工字段证据 URL，包括主来源、佐证来源、血统证据、逐场结果和官方总数，都必须通过
  Django `URLValidator` 的 HTTP(S) 严格校验；仅检查 scheme/netloc 或 `https://` 前缀不足以
  进入冻结审核产物。
- 自动补充来源与主来源的合并也必须做强身份检查。同 provider 只有双方 external ID 完整且
  精确一致时可直接补空；其它情况要求双方各自完整匹配马名、父名、母名、出生年份，不能因
  地区相同或马名相同放行。
- 来源总数、来源名、来源 URL 和带时区核验时间按一个原子证据组更新。新审核候选缺任一项时
  整组清空，禁止与数据库旧字段拼接。研究摘要有官方总数时优先采用官方总数，否则才采用
  备用来源总数。
- source cache 的“非空”不等于“有效”：硬字段必须是预期类型，出生年份在合理范围，精确日期
  必须为合法 ISO 日期。审核行、模块、逐场记录与数据库 `source_refs` 均执行相同 HTTP(S)
  URL 门禁。
- 父母实体反查不能把“搜索只有一个同名结果”当作强身份。自动采用只允许预期 external ID
  精确一致，或已知父名与候选完整来源身份共同命中；provider 名可规范化，external ID 是
  opaque string，只去首尾空格并精确比较。
- 已审核的历史 name-only 血统字段不直接改写旧产物。必须用 manifest 逐行绑定旧输入 SHA、
  目标马强身份、父母实体 external ID、字段值、既有审核上下文和独立出生年证据，再生成
  新版本；任一漂移即拒绝。独立出生年证据的 `reviewed_by` 不得被改写为项目负责人逐字段
  审核。历史 APPLIED profile/pedigree 模块的 URL 由最终 evaluator 再次严格校验。

## 2026-07-19 P0 马人工字段补证与美国履历数量对齐口径

- 人工字段证据保留地区元数据，但身份匹配优先使用“来源 namespace + 来源马 ID”；来源身份
  不可用时才回退到“马名 + 父名 + 母名 + 出生年份”。出生年份缺失必须拒绝，同一字段重复、
  身份不匹配或与既有非空值冲突时整项拒绝。马名归一化须跨地区生效，地区不得进入唯一身份键。
- 基础字段人工补证必须保留直接原始值、归一化值、转换规则、来源 URL、核验时间和证据说明。
  应用前缺口快照是冻结审核输入，重复执行不得覆盖或把补后状态伪装成补前状态。
- Fort George 缺失的 7 条逐场履历可由 Sporting Life/Racing Post 结果页补齐数量，但
  Equibase 只核验了 Career Starts 总数。因此美国样本在 `13/13` 或其它数量对齐后仍必须保持
  `count_aligned_records_unverified` / `count_aligned_per_record_officiality_pending`，不得升级为
  官方逐场完整。
- HRN 备用逐场履历只能在 HRN 页面与已核验候选的马名、父名、母名、出生年份四项全部存在且
  一致时接收；直接 slug、搜索结果和缓存复放遵守同一门禁。任何缺项、同名不同年份或父母冲突
  均阻断。来源证据没有 external horse ID 时，去重键必须携带完整四字段身份，不能只按赛事 ID
  跨马去重。
- 新增逐场权威性字段时，既有 `complete` 履历不能沿用旧结论；迁移必须把权威状态非
  `source_records_verified` 的旧完整记录降为 `needs_review`。同场的 `unknown` 可由正式结果
  补齐，但两个互相矛盾的正式结果不得自动合并。
- 本决定只适用于只读研究产物、审核工作簿和后续安全应用能力，不授权生产批量写入、网络抓取、
  自动发布、部署或为普通比赛强建 `RaceEvent`。

## 2026-07-18 P0 马网络批次必须绑定冻结审核 manifest

- `--allow-network` 不能只信任审核 CSV 内自报的 `reviewed/decision`，也不能只依赖 CSV 与
  manifest 彼此自洽；必须同时显式提供冻结的 `review_manifest.json` 和预先批准的 SHA-256。
  CLI expected SHA、服务端 `HORSE_PROFILE_COMPLETION_REVIEW_MANIFEST_SHA256` 与实际 manifest
  字节 SHA 必须三方一致，随后再核对 artifact 类型、确认决定、CSV basename、SHA-256、大小和
  50 行分母。所有校验在解析 manifest 和创建任何 source client 前完成。
- transport 调用一旦开始，无论返回 HTTP 响应还是在连接、TLS、读取阶段抛异常，都计为一次
  请求尝试并更新跨候选限速时间；manifest 不得把已尝试的失败请求记为 0。
- reviewed batch 的业务文件和两层 manifest 必须先在同父目录 staging 中完整生成、逐文件
  校验并 `fsync`，再原子发布最终目录；失败清理 staging，不允许留下无法安全重跑的半批 artifact。
- 该加固只提高审核输入、请求审计和 artifact 发布可靠性，不授权新的网络地区、生产写入、
  自动发布、Git 合并或部署，也不改变 P0 范围和五地区资料完整门槛。

## 2026-07-18 P0 马首批 50 匹全部纳入

- 项目负责人确认生产只读样本中的法国、中国香港、日本、英国、美国各 10 匹全部纳入首批 P0 马资料补全。
- “确认纳入”只决定批次成员，不代表身份已确认或资料已完整；`needs_identity_enrichment`、同名歧义、完整生涯和硬字段门禁继续生效。
- 真实资料写入前继续采用离线 artifact、模块人工审核和显式 commit 门禁；本决定不授权自动首次发布或生产写入。

## 2026-07-18 P0 参赛马必须先只读提取，马名本身不构成跨赛事唯一身份
## 2026-07-18：P0 参赛马先只读提取，马名不构成跨赛事唯一身份

- 赛事详情完成后，先生成只读观察、候选和五地区人工样本，再决定是否同步 P0 来源。
- 来源内 external horse ID 可跨赛事归并；跨来源归并必须完整命中马名、父名、母名和出生年份。只有马名时不得自动视为同一匹马。
- 同一观察可携带多个强身份键并按连通关系聚合；连通后指向多个 profile 或出现血统冲突时必须转人工审核。
- 预样本只验证来源和 adapter；只有人工确认并完成全部硬字段后，才能计入每地区 10 匹完整资料验收。

## 2026-07-19：coupled runner 身份与 rollback Gate D 修复边界

- 来源中的参赛号码是客观展示字段，不是 live runner 唯一身份。合法 coupled entries
  可以由不同非空 external runner ID 共享号码；系统不得改写为猜测的 `1A/1B`、合并
  马匹或因页内无关 coupled race 拒绝整页。重复 external ID 仍必须 fail-closed。
- legacy `RaceEventRunner` 的 live 身份改为 `event + nonempty external_runner_id`；
  历史空身份行不做大表猜测回填。只有 external ID 唯一命中，或在无 external ID 时
  号码/名称形成唯一匹配，才允许更新动态字段；歧义必须零写入并计数。
- P0 身份按来源 `source_key + external_runner_id` 统一关联 runner/result；相同号码不
  参与强身份归并，不同来源的相同外部 ID 也不得自动合并。legacy 新列与 source refs
  同时非空却不一致时，在任何 racecard refresh/replay 写入前 fail-closed。
- 后续准实时代码发布在切换镜像前必须生成受审、不可变、绑定完整候选 image ID 和
  filtered env SHA 的 rollback manifest。四层 policy 先以单事务进入 maintenance，
  再按 coarse restore、重新验证、event restore 的固定阶段恢复；缺 manifest、状态混合、
  tracking/claim/settings 漂移或阶段乱序时不得切换镜像或扩大公开范围。
- rollback manifest 同时冻结 current revision pointer；validator 和 policy restore
  都要求 scheduler/monitor=false、enabled regions 为空，并在行锁内、任何恢复写入前
  对 current pointer 做 CAS。pointer 漂移时保持当前恢复阶段不变，禁止重新开放 event。

## 2026-07-19：event 924 的 15 分钟 SLA 不追溯补证，下一场重新验收

- event `924` 唯一 BHA 截图观察时间早于 promotion，receipt 的后续应用时间不能替代
  promotion 后的新浏览器 probe；该场 15 分钟 SLA 继续明确记为未通过，不以数据库
  incident 已 resolved 覆盖证据缺口。
- 用户决定不为 event `924` 追溯补证，改由下一场获准公开灰度赛事在 promotion 后
  15 分钟内重新执行官方来源 probe。该决定不豁免下一场 SLA，也不授权开启 scheduler、
  扩大 allowlist 或增加其他公开赛事。
- 用户同时明确授权 event `924` 实际 disable、公开隐藏验证和 restore；演练完成后恢复
  该赛事的暂定赛果公开，客观赛果、publication、observation 和 incident 事实均保留。

## 2026-07-19：event 924 使用已存 shadow 的无网络 operator promotion

- event `924` 的首个公开灰度不重新请求 TRA，也不伪造 runner claim/checkpoint。受审
  prepare 从数据库一致快照生成 promotion、disable、restore 三份独立 CAS manifest；
  operator 路径按 `control -> tracking -> event -> source/observation/revision/items ->
  policy/allowlist` 锁序，在同一事务内复用 runner 的唯一 admission core。
- promotion 只修改 manifest 精确列出的四层 policy 和 event allowlist，物化既有
  provisional revision，创建唯一 publication/incident，并停止该 event 的后续 tracking。
  `claim_generation`、provider attempt/success/hash/failure 和 host budget 均保持不变；
  scheduler 继续 false，tracking/allowlist universe 必须仍精确为 `[924]`。
- shared global/region/source policy 可作为版本化 public cap 保留；每个 event policy
  仍是强制层。resolver 的单条和批量读取在 event policy 缺失时都 fail closed；
  initializer 可复用合法 shared v2+ cap，但新 event 只允许建立精确 `event:ID shadow
  v1`，不能因 shared cap 或 allowlist 自动公开。

## 2026-07-19：暂定公开与 BHA 人工官方复核解耦

- TRA 继续固定为 supplemental authority；完整 TRA 结果可先以明确
  `provisional_public` 展示。赛事粗状态随成功物化变为 finished，但
  `result_confirmed_at` 保持空，页面只显示“冠军 · 暂定”“尚待官方来源复核”和“补充
  来源”，绝不误标正式。
- BHA 当前路线固定为版本化 `manual_browser_only` registry，禁止自动抓取、页面后端 API
  或批量下载。registry 中的 terms evidence digest 是受审条款证据记录的摘要，不是
  BHA HTTP response body 的摘要；发布前仍须 release operator 用普通浏览器确认入口、
  条款和 route 有效。
- 人工 receipt 只持久化客观 marker、participant/position 和私有截图/打印件 SHA，不保存
  第三方页面 raw、评论、评级、赔率或逐马版权描述。服务自行比较 provisional 顺序：
  match 只关闭 incident、不把页面升级为 official；conflict 同事务执行预生成 event
  disable；unavailable 保持明确 provisional/open，记录一次告警和后续人工探针时间。
- public admission/read 必须同时验证 route contract digest 和 terms evidence digest。
  allowlist/incident 保存同一版本化摘要，manual due 为 promotion commit + 15 分钟；
  event off + 2h 后仍 open 时 verify 明确报告 overdue。

## 2026-07-18：英国 Group 级别装饰只从审核级别派生精确名称变体

- TRA 英国 G1-G3 racecard 赛事名可在基础名末尾携带 `(Group 1/2/3)`。首版只在英国且
  `RaceEvent.normalized_grade` 明确为 G1、G2、G3 时，用固定映射生成规范化
  `group 1/2/3` token；不从自由文本 `grade_text` 或来源字符串推断级别。
- 派生输入继续限于原有获准 event、active 非中文 alias、series canonical、当年有效
  series name 和 active 同年度 MajorRaceEvent 名称。名称中零 Group token 时才保留基础
  名并增加唯一同级 suffix；恰好一个、位于末尾且同级的 token 只保留一次；异级、非末尾
  或多个 token 时整条排除。非 G1-G3 与非英国赛事完全保留原有名称集合。
- 来源候选仍须通过地区、Europe/London 日期、赛场和归一化赛事名 exact membership，并且
  唯一命中。不得扩为 substring、编辑距离、任意括号删除、sponsor 删除、Roman numeral、
  `G3` 文本解析或自动数据库 alias 写入；未观察到的新格式继续 fail closed。

## 2026-07-18：赛前开赛时间只通过受控 racecard manifest 初始化

- 首期只处理调用方显式列出的英国 event ID，并只请求 TRA Free 的
  `today/tomorrow + region_codes=gb` 两条固定路由。绑定必须同时精确满足英国地区、
  `Europe/London` 当地日期、赛场名和已审核赛事名/有效别名；不使用 substring、编辑
  距离、邻近时间或人工猜测自动绑定。
- prepare 对赛事业务事实只读，但允许创建/更新共享 `RaceLiveHostBudget` 控制面以保证
  1 RPS。真实网络不持有数据库锁；最多等待并重试一次，单次等待不超过 2 秒。产物只含
  客观 racecard 字段、响应摘要和审计元数据，不保存 raw、赔率、form、评级、奖金、血统
  或评论。
- schema v2 manifest 必须与同目录 `requests.jsonl/report.json` 的 SHA 绑定。initializer
  在锁内分类 fresh/replay，以 status、local date、timezone、旧时间、`updated_at` 和
  owner manifest 做 CAS；fresh 在单事务补齐时间并建立 shadow 行，相同 manifest 精确
  replay，任何不同 manifest 或 partial 状态拒绝。schema v1 继续兼容。
- 赛前有效 claim 不调用 results API，也不把等待记为成功/失败 observation；它以专用
  `pre_off_wait` checkpoint 清 claim、保持 failure counter、推进 next poll。只有到达
  off time 才原子晋级 `awaiting_result` 后发请求，stale claim/owner mismatch 零写入。
- secret 和 artifact 只永久挂载给独立 `race_live_worker`：secret 为 ro、artifact 为
  rw。initializer 的 one-off web 只临时只读挂载获准的完整 run 目录，不读取 secret；
  web、普通 worker 和 Beat 不得永久获得 secret 或 artifact root。

## 2026-07-18 历史公开状态与抓取权限门分离

- 历史赛事是否对外展示，以逐赛事持久字段 `visibility_status=published` 且 `data_quality_status=complete` 为准；不新增一个会让未完成赛事误公开的全局展示布尔值。
- 批量公开必须使用固定 target ID 和逐目标 artifact SHA 的不可变 scope，并依次执行最新备份、dry-run、整批原子 apply、事务内逐目标校验和独立 verifier。manifest 只读取一次，同一字节同时用于 SHA 校验和 JSON 解析，避免校验与执行之间的文件漂移。
- `HISTORICAL_RACE_BACKFILL_ENABLED` 只允许在受控 apply 进程中临时为 true；网络门始终为 false。apply 完成后常驻写门、网络门和准实时 scheduler/runner 都保持关闭，已公开数据不受这些运行权限门影响。
- 纯数字历史距离只在展示层补单位：日本、中国香港、法国为米，美国及英国平地为弗隆，英国障碍为英里；已带单位的字符串保持原样。原始数据库值、来源证据、导入和验收口径不做推断性重写。
- `8,867` 个 imported 目标全部公开，只代表已完整导入层；`30,917` 条正式总账中仍有 pending、来源不可得、身份待审和 ready 目标，必须在进度报告中分开统计。

## 2026-07-18 PostgreSQL 身份写入只锁业务基表

- 身份批次需要同时读取 `RaceEvent.race_series`，但该外键可空，PostgreSQL 不允许对 `select_related` 生成的 nullable `LEFT OUTER JOIN` 整体执行 `FOR UPDATE`。
- 正式锁顺序保持为：先按主键锁定全部相关 `RaceSeries`，再按主键锁定 `HistoricalRaceEventTarget` 和 `RaceEvent` 基表；后两者使用 `select_for_update(of=("self",))`，系列仍可预取但不通过外连接重复加锁。
- 该调整不降低并发保护，也不改变审核动作、manifest 或数据语义。任何未来增加的 nullable 预取都必须保持“基表显式锁 + 关联对象独立锁”的 PostgreSQL 回归。

## 2026-07-17 AI 赛事身份初审的正式执行语义

- 接受工作簿中的 `228` 条“同意合并并关联”、`21` 条“保持独立”和 `18` 条“非同赛／忽略”作为本轮正式产品输入，但生产执行仍受精确 manifest、独立 approval、备份、dry-run 和 verifier 门禁约束。
- “合并并关联”不是删除重复系列：把审核指定的年度 `RaceEvent` 从来源系列改挂到主系列，关联正式目标，并保留来源系列及一条审核通过的 `MERGED_INTO` 沿革。这样可保留历史来源和回滚证据，避免级联破坏 slug、别名和历届赛事。
- “保持独立”和“非同赛／忽略”都写入对称的禁止自动合并标记，并保留决定类别、依据和证据。误命中允许跨地区，也允许候选赛事已经正确归属于第三个系列；执行器不得为完成拒绝决定而改动该赛事或现有目标。
- 身份决定与字段校正分离。John C. Harris Stakes 的 `surface=turf` 只作为带 before/after 和事件身份的显式 repair 应用；以后迁址、距离、场地或年份修正也不得隐含在系列合并中。
- 同一事件、同一序列或正负决定发生冲突时整批拒绝；生产基线在 prepare 与 apply 之间漂移时整批拒绝。成功 apply 后必须逐动作证明目标关联、系列归属、关系、负向锁和字段修复均与 artifact 一致。

## 2026-07-17 未来赛程与历史正式目标采用关联而非复制

- `not_due` 只表示尚未进入赛果验收期，可以关联既有公开赛程，但不得变为 `imported`；历史物化器不得为 `not_due` 创建赛事。
- 自动关联只认同一 `race_series + official year` 的唯一既有赛事，并核对年份、地区和状态。名称只用于发现同名异线或一对多冲突，不作为自动合并依据。
- 历史、当前和赛果使用三个独立分母：历史截至 2024，当前从 2025 开始，赛果只统计超过宽限期且实际举办的正式目标。展示扩展赛事不进入正式分母。
- 完整赛果必须同时满足 `finished + imported + module_statuses.results=complete + result_confirmed_at + 全部结果 is_confirmed`；只有冠军或部分赛果不得计为完整。
- 生产修复只建立已批准关联，不创建、删除或合并 `RaceEvent`，不改变可见性和详情；artifact、approval、apply、rollback 和 verifier 全部使用不可变身份与整批原子事务。
## 2026-07-16：准实时赛果采用不可变修订、持久来源权限和独立 worker

- 产品状态固定为 `scheduled -> racecard_ready -> awaiting_result -> provisional_result -> official_result -> corrected_result`，只允许审核设计中的显式边；当前不做比赛进行中的逐秒位置或沿途排名。
- `RaceEventRunner` / `RaceEventResult` 继续作为当前投影，来源事实先写 append-only observation，再形成 immutable revision/items/evidence；current 与 last-known-good pointer 受 event/kind、owner generation 和 claim CAS 约束。shadow 不物化公开赛果，晋级公开必须留下唯一 publication audit。
- official authority 只能来自持久、已审核的 source identity，调用方参数不能提权。The Racing API 只能作为 provisional/交叉验证来源，不能单独推进 official；公开只保留客观赛事事实，不复制评级、评论或第三方版权正文。
- 用户在 `2026-07-17` 明确确认相信 The Racing API 商业接口的赛果准确性。对已完成覆盖 proof、赛事/参赛马身份绑定和完整性校验的目标赛事，TRA 改为暂定赛果公开主链：`provisional_public` 开启后可在官方二次复核前直接推到前台。JRA/NAR/HKJC/BHA/France Galop/Equibase 等官方来源仍必须异步复核并决定 official/corrected；这项决定不授予 TRA official authority，也不放宽空结果、缺马、身份冲突、人工锁或条款门禁。
- 调度采用 Beat 轻量 due-selector + 独立 `race_live` queue/worker；普通 worker 固定只消费 `celery`。数据库 HostBudget 是正确性层，所有真实网络仍须通过 source permission、host 预算、有限轮询窗口和短 claim/checkpoint。
- 历史一期收口只解除“先完成历史任务”顺序门禁，不自动移交任何赛事写入权。来源 proof 必须业务 DB 零写入；进入 shadow 前仍要用精确 event allowlist/owner generation 和 SHA handoff 明确无 active historical lease/checkpoint，并经最新代码 review 和用户发布授权。
- 日本和香港正式范围按用户确认推进：香港 G1/G2/G3；日本 G1/G2/G3、JpnI/JpnII/JpnIII、JG1/JG2/JG3。JG1-3 只有在 90 天、必要时延长至 180 天的独立 proof 仍无法达标后，才可凭带 SHA、等级/赛事明细和复核日期的用户批准 artifact 暂时 deferred。

## 2026-07-16：历史覆盖分层与详情导入 receipt 成为正式门禁

- 历史期定义为截至 2024 年；2025 年及以后属于新赛事正式范围。日本、中国香港继续沿用既有官方来源和正式总账 hard 标准；英国、法国、美国历史 G1 为 hard，历史 G2/G3 为 best-effort，已有数据继续保留和补充，显式 gap 单独报告但不阻断历史 hard 验收；2025 年及以后英法美 G1-G3 属于正式展示范围。
- 已完成的 batch 和详情 package 一律复用，不因政策分层倒退或重跑。零星身份歧义、缺页和普通 G2/G3 缺口进入统一 gap/review ledger；hard 缺口只有权威取消、未举行或永久不可得证据才可记账通过。
- 正式详情导入按 source bundle/chunk 执行。bundle 必须精确覆盖冻结 package scope，并把 source bytes、cache identity、request evidence、target identity、layer、cutoff、chunk 与 approval SHA 全部写入 manifest；只保存 identity 而不带来源对象字节的 bundle 不得进入生产。
- 每个 chunk 使用独立 `HistoricalRaceDetailImportReceipt`。receipt 的 STARTED/COMPLETED/ABANDONED 三态及 supersedes 链不可覆写；业务写入和 COMPLETED 必须同事务，STARTED 只有证明零业务写后才能显式 abandon。runner owner token、全局数据库锁和 artifact/current-step/plan binding 共同构成 fencing，不能只凭 run ID 执行。
- verifier 只核 receipt 固定的本次 APPLIED candidate，不以“event 下存在某个候选”代替精确写入证明。2026 当前到期 descriptor 必须按 target 身份 materialize，强制保持草稿和不完整状态，并在任何失败时整批回滚。
- 历史公开继续关闭。代码通过最新零问题复审并生成正式不可变 artifact 后，仍须取得用户对当前固定发布内容的明确授权，才能执行生产备份、迁移、镜像切换和写入；授权后不得再改变发布内容。

## 2026-07-15：项目协作切换为 Codex 原生规划、测试先行与独立子代理审核

- 项目主流程固定为“探索 -> spec/design -> 方案审核 -> 测试先行 -> 子代理实现 -> reviewer 会话 `/review` -> 用户授权后发布”。新任务在 `docs/changes/<slug>/` 保留 `spec.md`、`design.md`、`test_cases.md`、`tasks.md` 和 `rollout.md` 五份 durable artifacts，不把聊天记录作为唯一项目记忆。
- 探索使用 Codex 原生只读调研/规划；需求不清或高风险时可使用 `grill-me-codex`。进入方案审核阶段且缺少合适原生能力时自动使用 `plan-eng-review`，无需用户再次点名。
- 自动化测试必须先于实现，并实际产生由缺失目标行为导致的 RED，再进入 GREEN/REFACTOR。仅不改变运行时行为的纯文档或纯配置整理可豁免；flags、队列/路由、权限、依赖、容器/部署顺序和数据行为配置必须测试先行。
- 任何 subagent（实现、测试、审核、调研或其他用途）运行期间，直到全部 active subagent 结束，主代理只能继续派新 subagent 或等待/接收结果；不得读/改/测/调研、向其他任务发消息或处理无关工作。写密集任务默认串行，并行任务必须没有文件边界重叠。实现代理不提交、不发布，只返回摘要、路径、测试证据和风险。
- 同一需求首次方案审核与首次代码审核各建立 reviewer 会话；首次代码 reviewer 必须未参与实现并实际调用内层只读 Codex 原生 review。后续方案复审和代码复审分别复用各自原 reviewer 的同一会话与上下文；只有会话不可恢复时才新建，并记录原因、上轮 findings 与已知问题交接。
- 复审严格限于上轮具体漏洞、对应修复及直接触及路径。只有该漏洞的直接 P0/P1 回归可新增阻塞；其他新发现记录为后续建议后结束，禁止扩展为无关 P2/P3 加固或通用发布协议。completed/exit 0 仅表示原生 review 执行成功。
- 发布授权只对当前任务有效，必须在最新成功 review 后由用户明确给出。成功 review 记录完整 fingerprint、approved parent 与 `content_manifest_sha256`；授权后 staging 前完整 fingerprint 必须不变。显式 stage 全部受审改动后允许 status/index 表示变化，但 HEAD 必须仍为 approved parent、无 unstaged/untracked/conflict，且 index content hash 必须等于受审值；漏 stage、夹带或内容变化均停止。不另引入 receipt 或 CAS 发布协议。
- 部署后 evidence-only closure 的精确文件 allowlist 只有 current state、project status、deploy runbook、必要发布 decisions 和本任务 release report；仅追加已发生证据并复用同一需求既有代码 reviewer 会话审核。代码、测试、配置、迁移、spec、tasks、skills、agents 均禁入；超出集合或改变行为/治理时返回完整 review + 新授权。
- 活跃 `grill-me-codex` 仅是一问一答的 Codex 原生只读探索 skill：先查仓库、每题给推荐答案与理由、用户可随时停止；不写 PLAN/spec/design，不启动其他模型或 nested review。原 Claude 双阶段版本完整归档，仅作恢复依据。
- `openspec-explore`、`openspec-propose`、`openspec-apply-change`、`openspec-archive-change`、`openspec-sync-specs` 及 OpenSpec workflow-spine 停用。既有 OpenSpec artifacts 原地保留为历史/在途上下文，OpenSpec CLI、phase 和 journal 不再是新流程门禁。
- `2026-07-15` 已在途任务先完成当前原子操作并停在安全检查点，再按“读取现存规格 -> 补齐/更新 test_cases -> 对尚未实现行为取得真实 RED -> subagent 实现 -> 复用同一需求既有 reviewer 会话（没有时首次建立）”迁移。不得伪造已经错过的历史 RED，也不得重做已完成生产动作；旧文档里的 OpenSpec “下一步”自此仅为历史记录，不再是现行指令。
- 本迁移由用户直接要求立即建立规则；最早一批编辑发生时新流程及 `docs/changes/codex-native-workflow-migration/` 尚不存在，因此不追溯伪称前置 artifacts 已完成。目录建立后的 helper 强化必须保留真实 RED/GREEN 证据。
- `codex-native-workflow-migration` 当前尚未发布；其他现有 worktree 不批量改写 tracked
  治理文件，以免破坏在途工作，只在安全检查点通过 handoff/rebase/main 同步。base/commit
  审核只接受 clean tree；未提交发布前改动统一走 `--uncommitted`。

## 2026-07-15：重型历史解析留在本地，详情匹配必须先消除距离歧义

- France Galop 年度 PDF、逐场详情扫描及其他高内存解析只在本地固定镜像执行；生产 runner 只接收已缓存、已校验的轻量 artifact 做 verifier/apply。生产主机发生资源异常或 SSH 不可达时，不在未知状态下重启、重建或继续写入。
- `m` 必须结合地区和值域解释：法港日以及 `>=100m` 为 metres；英美短值如 `3m` 为 miles。不能把英国 `3m` 当 3 metres，也不能把美国 `1600m` 当 1600 miles。详情匹配在名称评分前优先使用兼容距离缩小候选，并继续保留 URL 一对一和复用拒绝门禁。
- 年度目录标题可能包含赞助名、注册名或历史胜马文本。详情解析应同时使用审核后的系列 alias、年度目录名和总账原始名，但只有日期、场地、距离及唯一来源 URL 共同通过时才接受；名称相似不能覆盖距离冲突。
- 地区内并发分片可以使用共享 host interval artifact：请求次数仍按 shard 独立记账，所有 worker 通过同一 `fcntl` 锁共享上次启动时间。共享文件必须位于共同受控挂载根；正式 runner 在尚未支持父级共享挂载前必须清除该环境变量，不能从宿主继承任意路径。

## 2026-07-15：正式历史批次按冻结输入、证据 gap 和只读验收推进

- batch006 及后续正式抓取必须由 tracked plan builder 生成结构化 runner plan；selection、approval、batch manifest、descriptor、image revision 和 tool SHA 均为不可变身份，typed recipe 必须从实际 CSV/JSONL 内容证明与 shard scope 精确一致，禁止手写任意 argv 或使用 `tmp/` 工具。
- complete 与 gap 共同构成 selection 的精确分母。来源冲突、无效或暂不可得可以进入带证据的 gap 并继续其他目标；人工补证的 target SHA 或旧值漂移只把该目标转为 conflict gap。无证据遗漏、complete/gap 重叠、来源缓存漂移和结构不合法的补证仍整体 fail closed。零星歧义累计到最终统一审核，不中断整批正式总账收集。
- 数据库 verifier 检查冻结候选身份对写后 target/event 状态的结果，不把写前 target hash 与合法写后的当前 target hash 机械比较。PostgreSQL verifier 必须在事务第一阶段设置 READ ONLY，任何完整或 gap target 的赛事均不得为 published；同模块历史 APPLIED candidate 允许保留，但必须按 `applied_at/id` 核验最新一条。
- 地区距离单位保留来源原文及 provenance；英美 `m/f/y`、法港日公制等不在合并层强制换算。只有来源明确给出单位时才补单位，不能凭地区猜测。

## 2026-07-15：新闻重跑发布与未知马名门禁

1. 7 月 13 日起新闻按创建时间冻结清单重跑；重复稿不重复处理，可处理稿必须有明确成功、人工复核或忽略终态，不能以“命令执行过”代替逐篇对账。
2. 来源框架、编辑注、与正文无关的导航链接和博彩推广必须在翻译前清除；赔率以及作为赛事标题、马主等专名组成部分的博彩公司名称允许保留。
3. 完整未知马名必须原样保护，不能按术语子串拆译；普通词、人物和机构只有在上下文支持时才能作为马匹实体。未知马名占位出现多次继续阻断发布，省略主语由有界重试改写成“该马/其”，不得降低 `validate_rewrite()` 门槛。
4. 日文普通词必须正常翻译；产驹、追切时间、赛后访谈和出马表采用确定性格式。术语库补充社台与北方马公园的日英中别名。
5. 存量重新发布不主动补发 QQ。冻结清单中 `8337/8413/8424/8425/8450` 在早期中断窗口产生 5 条 delivery；最终排空已在队列中的自然任务时，`8429` 又产生 1 条合规 delivery，六条均保留审计。本次受控发布的 47 篇 Sponichi 稿新增 QQ delivery 仍为 0。
6. 新闻上线不解除 historical runner 的独立资源门禁。生产磁盘低于 5 GiB 时 batch006 保持关闭，即使新闻健康检查和队列均已恢复正常。

## 2026-07-14：Gold 合格不能覆盖生产差异人工复核失败

- Gold 的 `qualified=true` 只证明冻结样本达到覆盖和指标门槛，不等于当前 72 小时生产文章可安全上线。只要全部主地区变化或 `needs_review` 中存在明确错标，本轮仍为 no-go，必须修规则、补回归并重新生成完整 run。
- 主地区遵循 precision 优先：赛事或赛场的明确证据高于参赛马来源；ASCII 单词实体、嵌套在机构全名内的赛事词和正文历史背景不得轻易夺取主地区。无法可靠裁决时允许漏标或进入 `needs_review`，不得为提高 recall 制造错标。
- 日本来源报道当前日本成就、仅把海外赛事作为未来梦想时，主地区保持日本，海外目标进入相关地区。正文首段赛事只在标题没有可靠赛事、且首段仅出现一个非歧义赛事地区时补充主地区证据。
- 每次规则修复后必须重跑完整 72 小时 `all_articles`，人工检查全部主地区变化和全部 `needs_review`；不能复用修复前的 Gold 指标或审核结论批准 Shadow。

## 2026-07-14：全量归属审计不再隐式执行发布门禁，Gold 漂移采用保守续签

- `--scope all_articles` 用于验证归属差异，不用于恢复术语门禁；默认不得逐篇调用 `validate_rewrite()`。确需同时复核门禁时必须显式传 `--include-gate-validation`，默认 `gate_candidates` 仍保持原门禁补跑语义。
- 持久 dry-run 是审计真相。报告进程中断后应使用同一 run ID 与 manifest 导出，不重复推断；导出必须验证 manifest 和 candidate fingerprint，原子写新文件并拒绝覆盖既有证据。文章缺失/漂移必须进入必审清单，不能拿旧归属结果校验已变化正文。
- Gold 输入 SHA 只可在原审核身份、来源 URL、规范化标题、正文长度/语义以及当前推断与人工结论均稳定时自动刷新。重复 key/article、正文异常缩短、标题变化或推断变化均保持漂移，不以“凑足 150 条”为由放宽。
- 相关地区质量门槛只评估五个实际运营频道；`other` 可保存为证据，但不计入五频道 precision/recall。低置信度主地区变化只有在同时违背人工期望时才算无依据变化，避免把 Gold 明确认可的变化反向计为错误。

## 2026-07-14：historical runner 资源门禁必须由宿主与应用双层强制

- crawl phase 的 `RACE_EVENT_CRAWL_*` 不能直接继承 plan 或宿主环境。runner 父进程必须用批准 settings 覆盖子进程，并让同一 run 的所有 step 共用 artifact 根目录下的请求账本和 source-cache manifest。
- 请求预算必须为 `1..250`，source cache 必须为 `1..2147483648` bytes，请求间隔至少 1 秒，磁盘底线不得低于 `5368709120` bytes。`0` 不得解释为无限；直接调用 Django 管理命令也必须执行同一边界校验。
- 宿主脚本在 `docker create` 前检查 phase env 数值和 artifact 文件系统实时可用空间；Django 服务在取得数据库租约前重复检查容器内文件系统。任一层失败都不得创建 runner、取得租约或执行网络 step。
- 每个 crawl step 后将请求账本与 cache manifest 的存在状态、大小和 SHA 保存为 checkpoint 顶层身份；下一 step、resume 和 completed 幂等检查都必须重新核验。资源账本漂移一律 blocked，不能把删除后的空账本视作新额度。
- crawl 取得双锁后必须在首个 step 前保存资源基线；任何已启动 step 的失败收尾必须在释放锁前刷新资源身份，无法收尾的强杀恢复由基线漂移 fail closed。
- 生产 `/app/runtime/tools` 不再接受“镜像内任意 SHA 匹配脚本”，只允许显式赛事发现、缓存、详情解析、打包、导出和 smoke 工具。新增历史工具必须更新白名单、测试和固定镜像；术语或其他直接联网脚本不得借 crawl egress 绕过赛事预算。
- `orchestrate_race_event_crawl` 内部的 AdapterRunner 不得重新生成自己的请求账本/cache 路径覆盖 runner 父级。父级路径原样继承；请求数/cache bytes 使用父子较小值，请求间隔/磁盘底线使用父子较大值。
- 生产磁盘不足时只能清理可再生构建上下文/镜像或扩容，不能临时降低 5 GiB 底线。第一版 runner smoke 后发现这一旁路时，batch006 仍未发出真实网络请求，因此按本决策先修补、重新 review/部署/smoke，再开始正式抓取。

## 2026-07-14：batch006 起扩大标准批次并使用独立 historical runner

- batch005 继续完整遵守旧标准，即单地区最多 50 场；只有 batch005 全部写入和验收结束后，batch006 及后续标准批次才把单地区上限提高到 250 场。
- 扩容不能只修改一个命令行默认值。选择器、地区进度护栏、artifact 摘要、测试和运行手册必须使用同一口径；既有排除 snapshot、100 场地区领先护栏和待审 gap 记账规则继续有效，除非后续产品审核另行修改。
- 后续历史批次使用独立 runner 容器，固定到已验收镜像 revision，显式挂载 runtime artifact，并设置资源限制。普通 web/worker/beat 部署不得重建、停止或接管 runner，也不得借此重建 DB、Redis 或共享网络。
- runner 必须具有数据库级与应用级互斥锁、心跳、可恢复 checkpoint 和失联接管门禁；迁移前必须安全暂停。抓取阶段只允许 `network=true / write=false`，落库阶段只允许 `network=false / write=true`，任何阶段都不能同时获得两种权限。
- 该能力在当时必须走 OpenSpec、工程评审、完整测试、实现和反复代码 review，并在部署验收通过后才允许启动 batch006；其中技术验收事实继续有效，但流程入口已由本文件顶部 `2026-07-15` 新流程取代。历史公开展示继续保持关闭。
- 实现采用三张独立控制表、PostgreSQL 租约与 `fcntl` 双锁；过期租约不能被普通启动覆盖。接管必须同时证明旧容器不存在、`pg_stat_activity` 无对应 `application_name`、runtime/DB checkpoint 一致，并写入操作者与原因。
- owner token 原文只能位于 artifact 外的 0600 文件；resume/takeover 也不得通过命令行传 token。crawl control role 对 event 表只允许 append，不能删除审计事件，更不能读取或写入赛事、新闻、术语等业务表。
- 普通部署首次引入 `0031` 时只能显式设置一次 initial-install 门禁；后续迁移必须让 active runner 安全暂停。数据库、Redis 和共享网络只允许由独立 bootstrap 首次创建，普通 deploy/rollback 永远不隐式补建。
- 子进程 stdout/stderr 不通过无界内存 pipe 累积，也不把未脱敏原文写入 artifact；先写入 runner 容器受限 `/tmp` tmpfs，结束后统一脱敏并原子写正式日志。stale takeover 只能核对 artifact 根目录固定 `runner-state.json`，不接受任意替代文件。
- crawl runner 不写旧的业务 `TaskExecutionLog`，网络步骤审计统一进入 append-only `HistoricalBatchRunEvent`；普通非 runner 管理命令仍保留原任务日志。这样 control role 无需获得任何业务表权限。
- stale takeover 必须从宿主执行 `historical_runner.sh takeover`：脚本先通过 Docker 实际确认固定名称旧容器不存在，再用同 revision、同 phase 数据库凭据、internal-only 网络和只读 artifact 挂载执行接管探针。不得直接把管理命令的 `--container-absent` 当成人工声明使用。
## 2026-07-14：归属生产验收必须显式使用全量近期文章范围

- `reprocess_multiregion_attribution_gates` 的默认 `gate_candidates` 范围继续只用于术语门禁候选恢复，保持现有运维兼容；它不能作为多地区归属生产资格证据。
- 生产 72 小时验收必须显式使用 `--scope all_articles` 且不传 `--limit`。范围包含已发布文章，排除 duplicate/rejected/withdrawn/archived/ignored；任何 `scope_complete=false` 的输出均不得用于 go/no-go。
- 人工清单必须覆盖全部主地区变化、全部 `needs_review` 和全部人工锁定跳过，再从其余文章按五个运营地区做内容指纹确定性抽样。人工锁定文章在 dry-run manifest 中必须保留原主地区与相关地区。
- `all_articles` run 的 commit 只应用已审核的主/相关地区与归属审计字段，不重写门禁状态、不设置 `ranked_revived_at`、不改变 published 身份或 QQ 交付；默认 `gate_candidates` commit 才保留原来的门禁恢复语义。
- `all_articles` run 若因显式 `--limit` 产生 `scope_complete=false`，即使 Gold 指标合格也必须拒绝 commit；人工清单行保留标题、来源 URL、来源站点和发布时间，避免脱离原文只审核数字 ID。
- `scope/scope_complete/commit_policy` 必须作为 `_run_contract` 写入 manifest 已绑定的 metrics；commit 不得信任可独立修改的 selectors 来决定是否重跑门禁。旧 run 仅为兼容读取 selectors，新全量 run 即使 selectors 后续漂移也仍按锁定契约执行。

## 2026-07-14：单审 Gold Set 可在完整门槛和 Shadow 验收后支持 Enforce

- `provisional_single_review` 继续作为审核来源和审计事实保留，但不再无条件判定 no-go，也不得伪造 reviewer B 或裁决状态。
- 单审与双审使用同一首发覆盖和质量门槛：有效样本至少 150 条、五个运营地区各至少 10 条、跨地区至少 20 条；总体/分地区准确率、相关地区 precision、无依据变化、过度扩散、锁定覆盖和 PostgreSQL 性能门槛不降低。相关地区 recall 首发门槛从 90% 调整为 50%，因为漏标通常不可感知，而错标不可接受；多人审核存在冲突时仍必须裁决。
- Gold Set 达标只允许进入 shadow，不能直接 enforce。shadow 必须至少观察 24 小时，并人工检查全部主地区变化和全部 `needs_review`；通过后仅对新文章 enforce，相关地区查询仍独立关闭。
- Gold Set 是持续增长的数据产品，不是一次性验收文件。新增来源、规则改版、shadow 误判和运营争议样本均应进入新版本并保留版本间指标变化。
- 当前 159 条单审集合的最少运营地区样本为法国 11 条、跨地区 24 条；主地区准确率 98.11%、相关 precision 100%、recall 54.84%、过度扩散 0%，覆盖与质量门槛均通过，因此允许进入 shadow。该结论不等于允许直接 enforce。
- recall 线上下降只告警并暂停扩大灰度，不自动关闭当前功能；precision 跌破 95%、明显错标或过度扩散超过 1% 时，才按相关地区查询 -> 归属 enforce 的顺序回退。
- 250 篇真实规模 PostgreSQL 测试必须绑定实际 `NewsSource`。本次先发现 `254 SQL` 的来源懒加载 N+1，修复后五轮稳定为 `5 SQL / 1.66–2.14s / 约49 MiB`；以后不得使用无来源空 fixture 掩盖批处理查询问题。

## 2026-07-14：生产只读检查不得使用 `docker compose run`

- 生产环境查看管理命令帮助、Django 状态或只读数据时，只允许使用已存在容器的 `docker exec`；不得使用 `docker compose run`，因为 Compose 仍可能按依赖图重建 DB/Redis，即使目标命令本身只读。
- 如果确实需要一次性容器，必须先检查 Compose 依赖、使用显式 `--no-deps`，并在单一生产协调线程批准后执行；默认仍优先使用现有 `web` 容器。
- 当同一表出现两个不同索引的结构/唯一性异常时，不按单索引修复结束：应暂停 beat、停止 worker 消费、排空 active、生成并校验完整备份、顺序扫描确认真实重复、合并重复记录及外键审计，再对整表执行并发重建和 `VACUUM ANALYZE`。
- 生产身份重复合并必须保留事故前最早的权威文章，迁移快照、翻译运行、自动化日志和窗口决策，写入操作日志后才删除冗余行；不得只删除“看起来较新”的文章而丢失审计关系。
## 2026-07-14：日文固定译词必须以字段级占位符守恒并在边界恢复

- 日文普通赛马词不依赖模型自由选同义词；已接受的种子术语在标题/正文按绝对 span 转为字段级占位符，模型必须逐出现次原样返回，最终由系统恢复术语库目标。遗漏、重复、跨字段、新造或畸形占位符一律重试并最终显式失败。
- 完整未知马名和结构化格式优先于内部短术语。拍卖产驹、追切、赛后访谈和出马表采用窄上下文格式计划；未知母马、父马和出马表马名保留完整原文，不做全局组件替换。
- 模型可能在占位符旁自行补写同一中文词。恢复阶段只移除两个及以上字符的明确后缀/前缀重叠，以及 `公开级 + 级别` 的受控单字重叠；其他单字重叠保留，避免把“拍卖会会场”错误缩成“拍卖会场”。
- 已发布文章重译若连续被完整性或占位符门禁拒绝，不得放宽门禁或保存失败稿。若同一原文已有通过全部门禁的成功 run，可在精确计数、公开身份与 QQ 断言下只修复确定性后处理重复，并写入 `OperationLog`；失败 run 保留审计但不得覆盖公开稿。

## 2026-07-14：国际新闻正文清理必须按可信容器与语义噪声 fail closed

- 国际来源正文选择器未命中时必须返回显式失败，不得回退页面 `body`；站点 DOM 漂移应在后台暴露，而不是把导航、推荐、社交和页脚误当新闻发布。
- 与新闻事实无关的独立 URL、`click here` 行动句、编辑注、完整赛果/活动跳转、责任博彩和博彩推广必须清理。博彩公司名称只有出现在赛事标题、马主等专名或赔率事实中才保留，不能用公司名本身作为整段删除条件。
- 历史公开文的修复必须使用已保存 HTML 离线重解析、显式文章 ID、默认 dry-run、事务 commit 和操作日志；强制重译只能更新译文，必须保持公开状态、原发布时间和 QQ 幂等状态。
- 翻译完整性不能只按英中字符数和标点数判断。日期表、出马表等结构化内容可用非空行覆盖证明完整，但阈值必须向上取整，且尾句完整性和显式列表标记门禁继续生效。

## 2026-07-14：官方来源不提供马号时允许留空，但必须显式记账

- `horse_number` 的完整性以来源实际提供字段为准，不能为了满足统一格式而按结果顺序伪造号码。官方结果文件没有马号时，可保留空值，但马名、骑手、名次和来源缓存身份仍必须完整。
- batch004 的 NSA `target_id=74171` 属于此例：官方 PDF 提供 8 匹出马和 7 条正式赛果，但不提供马号。导入器允许多个空马号，同时继续禁止同一赛事的非空马号重复。
- 这类来源格式差异不阻断其他正式总账数据收集；统一进入最终产品审核清单，后续若取得权威号码来源，再通过独立候选补充，不能回写推测值。

## 2026-07-13：原定场次弃赛不等于年度赛事取消

- 年度赛事身份判断必须继续追踪改期、移师和补赛。原定日期或场地页面标记 `ABANDONED`，只能证明该场次未按原计划举行；同届赛事在其他日期或场地正式跑完时，target 仍为 `held`。
- 2025 Hampton Novices' Chase 以 `2025-01-19 / Windsor / 3m53y` 的正式结果为准，Warwick 原定场次只保留为变更证据。以后遇到相同情形，必须先排查改期和移师，不能直接改成 `cancelled`。

## 2026-07-13：逐届距离必须保留批准来源的原单位

- 不同地区和年代使用公制、mile/furlong/yard 等不同单位；总账裸数字不能作为最终展示值，也不能按地区猜测单位。
- 日期 apply 后必须核对逐届来源距离并通过权威字段门禁写回原文。字段变化会改变 target SHA，后续详情来源和最终候选必须依次重新导出、重新打包。

## 2026-07-14：地区进度护栏只比较仍有可抓目标的地区

- 同一年代带的 100 场领先上限用于同步仍在抓取的地区，不是要求五地区拥有相同赛事总量；正式总账容量较小的地区抓空后必须退出比较，否则较大地区永远无法完成。
- “仍未完成”以本批选择后是否还有未排除、可选的 pending held/cancelled due 目标判断。任一未完成地区即使本批未被手工选中，也仍参与比较；只剩一个未完成地区时没有比较对象，不因护栏拒绝。
- selection snapshot 显式排除的歧义或缺口仍是 pending，继续计入总账分母、remaining pending 和最终统一审核清单；但它们不属于当前可抓集合，不能单独冻结其他地区。
- 批次选择和 artifact 写入前各自重算可抓分母并执行护栏，summary 保存可抓地区集合。该变更不修改 expectation/resolution、不自动解决歧义、不开放历史展示。

## 2026-07-13：年度日历的竞赛类型不得覆盖赛道表面

- `flat / jumps` 是竞赛类型证据，不等同于 `turf / dirt / synthetic` 赛道表面；年度日历未明确给出表面时，保留总帐已经审核的 `surface`。
- Newcastle 的 Hoppings Stakes 不得因为进入英国平地赛日历就被改为 turf；障碍赛也不得仅因实际在草地举行就把模型中的 `jumps` 类型改写为 turf。
- 日期发现 artifact 只处理日期、直接来源和带单位距离；surface 或场地的实质修订继续走独立字段候选、证据 SHA、dry-run 和审核门禁。

## 2026-07-13：新增详情来源必须在三层白名单保持一致

- 一个新来源只有同时登记到直接 URL 的 host/authority/region 校验、补充详情来源 artifact 服务和最终详情 packager 后，才算可用于生产；任一层缺失都应 fail closed。
- NAR `keiba.go.jp` 定义为日本官方来源；Zone-Turf 定义为法国第三方数据库来源。来源缓存必须逐文件绑定原始 URL、大小和 SHA-256，不能把缓存内容配给后来合成的 URL。
- ZEturf 发现器必须保存实际下载并缓存的 URL。即使页面内容匹配另一目标，也不得按命中目标重新合成 URL，否则来源 manifest 与候选身份会分离。

## 2026-07-13：已交代 gap 用历史选样证据排除，不改产品状态

- 上一批已经进入 gap ledger、但仍应保持 pending 的目标，不得反复占用后续标准批次的地区配额；生成新批次时显式传入既有不可变 selection snapshot，在地区 limit 前按 target ID 排除。
- 排除 snapshot 必须自证 schema、inventory SHA、内部 snapshot SHA、target 数量和唯一性，并与当前总账的稳定 series/year/region/inventory 身份一致；当前 target SHA 可因成功导入或权威字段更新而变化，不作为历史排除证据失效条件。
- 新 artifact 必须复制输入 snapshot 原字节，以固定单文件 artifact 键绑定路径、大小和 SHA-256。多份 snapshot 可重复输入，target ID 去重；最终 selection 与排除集合相交时 fail closed。
- 该入口只改变选样，不修改 expectation、resolution、event 或来源证据。被排除的 pending gap 继续留在 available/remaining 分母，直到另行完成产品审核、补源或永久不可得审批。

## 2026-07-13：详情来源审批与最终数据导入必须使用不同形态的候选

- `manage_historical_race_detail_sources` 必须读取仍带 `year / slug` 的原始解析候选，用于按年度赛事建立来源审批 artifact；不得把只含 target 绑定信息的最终导入包反向当作来源发现输入。
- 来源 artifact apply 会把批准证据写入 target 与 RaceEvent，并改变 target SHA。因此来源 apply 后必须重新导出 event input，再运行 `package_historical_race_detail_candidates.py` 生成新的最终导入包。
- `import_historical_race_event_candidates` 只接受这个写后重打包文件，并同时锁定文件 SHA-256、target SHA、inventory artifact SHA、来源 URL 和 source-cache identity。任何来源审批后的旧包都应因 target SHA 漂移而拒绝。
- 该分层只改变技术证据链，不改变产品语义：`ABANDONED`、`not run`、`cancelled`、`not_held` 仍按各自审核规则处理，不能因详情来源存在就自动修改总账。

## 2026-07-13：年度来源的 `not run` 只能生成审核证据，不自动改总账

- TOBA 等权威年度表若将某赛事明确标为 `not run`，来源发现工具应输出结构化 `source_reports_not_run`，保留来源赛事名、场地和状态。
- 该证据说明当前 `held` 预期可能有误，但来源发现阶段不得自行把 target 改为 `not_held`，也不得生成伪结果 URL、RaceEvent 或永久不可得结论。
- expectation 状态变化属于产品总账决策，需经审核后通过受控 artifact 更新；未批准前目标保持 pending，其他无关目标可继续抓取。
- TOBA 单场结果 URL 必须一对一绑定 target；同一 URL 若匹配多个系列，所有冲突候选均 fail closed。名称消歧中的 `Fillies`、`Turf`、`Sprint` 按完整单词判断，避免短名称包含或赞助词子串导致串场。

## 2026-07-13：法国新鲜度与多地区归属工程评审决策

- 归属采用 `MULTIREGION_ATTRIBUTION_MODE=off|shadow|enforce` 单一模式；旧布尔变量只作兼容映射，相关地区查询仍使用独立开关。
- 新增结构化文章状态字段与 `MultiregionAttributionRun/Lock`；不得复用外键指向术语门禁 run 的 `TermGateReprocessLock`。
- shadow 审计与 applied 审计分命名空间保存；归属 commit 必须绑定成功 dry-run 和 manifest，支持逐篇事务、断点续跑和重复提交幂等。
- gold set 使用真实生产输入快照；本段原双审及 `250/40/50` 硬门槛已由 2026-07-14 决策修订为“单审允许、多人冲突须裁决、首发覆盖 `150/10/20`”，任一地区样本或准确率不足仍为 no-go。
- 批量归属必须预加载术语、别名和赛事证据；250 篇 PostgreSQL 验收目标为 SQL `<=30`、耗时 `<=30s`、RSS 增量 `<=256 MiB`。
- 部署后默认不启用：先 off 部署，再 shadow 验证，再仅新文章 enforce，观察至少 24 小时后才可逐步开放相关地区查询、近期回填和正式群。
- 本地实现完成不等于生产资格通过。测试 fixture 和 CSV 模板不能替代真实生产输入的有效审核；现有 159 条已达到首发覆盖与质量门槛，但未完成生产 dry-run 和 shadow 验收时，change 仍保持 `implementing`，不得直接 enforce。
- 法国时间修复、翻译失败重试和历史归属回填均采用“先 dry-run 生成持久 run/manifest，再人工审核并锁定 commit”的路径；不得通过启动服务或迁移隐式修改旧文章、公开状态或 QQ 交付。
- manifest 必须同时绑定候选结果、规则版本、术语/配置/gold 快照和质量指标；commit 直接应用审核结果，不重新推断，并将归属写入、门禁重校验和 cursor 更新纳入逐篇原子流程。
- `new_articles` 及后续阶段的自然流只对新入库文章 enforce，旧文章重复抓取仅 shadow；历史修改必须走 manifest。`web_test_groups/recent_backfill` 阶段只有显式标记 `multiregion_test_enabled` 的 QQ 群读取相关地区，`formal_groups` 后才扩大到正式群。
- 翻译终态失败邮件默认启用并发送至用户确认的 `754652181@qq.com`；自动 selector 先原子 claim 再入队，避免 worker 积压时重复塞入同一篇文章。

## 2026-07-12：门禁补跑不得复活来源日期可信度不足的历史库存

- 英文术语门禁重处理只负责重新判断术语上下文，不改变来源新鲜度标准；候选仍必须满足其抓取时适用的来源日期和新鲜度要求。
- `NewsSource#21 / CrawlJob#9408` 创建于 TDN France 真实日期修复上线前，批内 `published_at` 为错误兜底时间，因此整批 `20` 篇视为不可信库存并进入 `withdrawn` 终态，不再参与后续自动补跑。
- 本次先发布后发现的 5 篇旧文立即撤回；QQ 未产生交付。其余地区 19 篇保留公开。
- 常驻生产仍使用 `shadow`；只有 manifest 锁定的单次 commit 可临时以 `enforce` 重校验，不能据此提前切换全局模式。

## 为什么英文术语上下文门禁先进入 shadow 而不直接 enforce

术语库中保留 `Exactly / Brilliant / Title` 这类合法单词型马名是正确的，问题应在文章命中级上下文中解决，而不是删除术语。新分类器按每次实际出现区分 `proper_noun / common_word / uncertain`，真实赛事、骑师、练马师和强实体证据继续保守保护；标题、导语 uncertain 仍阻断，背景 uncertain 只 warning。

生产固定 100 篇基准已证明重处理性能达标，但真实四地区小批中仍存在大量 uncertain，且本批 `common_word` 直接命中样本不足以单独证明零误放。因此当前只启用 `shadow`：计算和记录新旧差异，旧门禁仍决定文章状态。至少观察 24 小时并抽检普通词、真实单词型马名和 uncertain 后，才允许切 `enforce`；历史文章只能引用已审核 run ID 与 manifest commit，commit 只恢复发布候选，不直接公开或创建 QQ delivery。

性能门槛不通过时不得通过提高 60 秒或 256 MiB 上限掩盖问题。本次生产基准曾暴露全地区 26,713 条术语、37 万英文 alias n-gram key 和完整重复语料/文章字段加载，最终通过地区预筛、相关快照、字段投影和英文 alias 一次预取消除无效 CPU/内存，保留既定正确性边界。

## 为什么 P0 基础代码上线后不立即执行全量来源同步

生产 dry-run 显示当前范围包含 `21596` 条有译名马术语、`992` 场重点赛事，赛事证据已有 runner `5096` 条、result `4572` 条。直接执行 `p0_horse_profiles --sync-sources --commit` 会一次写入全量术语来源并分析数千条参赛身份，超出已经确认的“日本、中国香港、英国、法国、美国各先抽 10 匹人工跑通”范围。

因此 P0 基础代码和迁移可以先上线，但来源同步 commit 必须继续服从样本优先：先完成五地区 adapter、统一 artifact、每地区 10 匹 dry-run 和人工审核，再选择受控写入方式。上线本身不得隐式启用网络补全、全量来源写入或自动首次发布；当前生产保持 `HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=false`，`HorseP0Source` 为空属于有意状态，不是部署失败。
## 为什么美国历史平地赛优先使用Equibase单场standard PDF

Equibase旧 `eqbPDFChartPlus.cfm` 和整日PDF索引可能返回防护HTML或失效链接，但同一官方体系的单场standard PDF仍可稳定提供完整实际出走、马号、闸位、骑手、练马师、负磅和官方赛果。因此美国历史平地赛继续以Equibase为主源，日期发现阶段直接绑定可验证的单场PDF，不把HTTP 200防护页或404整日索引视为成功证据。

详情生成必须使用target在日期apply时记录的唯一source-cache manifest，并逐文件匹配批准URL、大小和SHA-256；随后再复核PDF页眉日期、赛场和场次。每次只允许一个已批准manifest，禁止把批准manifest与其他manifest中的PDF混用。`1a`等联合投注编号独立保留，runners按马号排序，results按官方完赛顺序保存。

## 为什么 materialize 后发现的详情页使用独立补充来源 artifact

日期发现 artifact 已经批准并把目标 materialize 后，后续可能找到更完整的专业数据库详情页。此时重做原日期 artifact 会破坏既有审批身份，也会让日期证据与详情正文混在一起。因此补充详情页使用独立 detail-source artifact：绑定当前 target SHA、inventory SHA、provider/authority、直接 URL，并复制批准的 source-cache 字节；apply 只向 target 与 RaceEvent 的 `detail_discovery.approved_detail_sources` 追加证据，不改变赛事身份、ready 状态或 draft 可见性。

详情打包必须同时匹配批准 capture 的 `source_url / size / SHA-256`。即使 URL 相同，只要缓存正文不同也必须拒绝，避免网站后来更新的页面无声替代人工批准版本。提交时同时锁定 target 与 RaceEvent，防止并发来源维护互相覆盖。

## 为什么赛事详情来源必须按地区分层，并区分赛前声明与实际出走

不同地区的历史赛果权威入口和保存深度不同，不能使用一个第三方站点覆盖所有地区。日本采用 JRA 主源、netkeiba 历史补源和 JBIS 血统/沿革补源；中国香港采用 HKJC 官方 Race Card / Results；英国采用 Racing Post Full Result 作为历史实际出走与赛果主源，Sky Sports Racecard 补赛前页面，BHA 只承担 2014 年后官方校验；法国采用 France Galop 主源、PMU 补源；美国采用 Equibase historical charts 主源，BRISnet、DRF、BloodHorse 交叉校验，美国障碍赛事补用 NSA。

数据层必须分别保存 `declared_runners_source`、`actual_runners_source`、`non_runner_source` 和 `result_source`。Full Result 或 chart 中的 runners 只证明实际出走，不能冒充赛前声明出马表；找不到历史 racecard 时应明确标记赛前表缺失，而不是从赛果反推。所有来源还需保留原始 URL、抓取时间、来源权威级别和解析版本。

## 为什么同名赛事审核结论要生成新总账而不覆盖原始目录

TJCIS 的简写、赞助名和场地/距离字段会把同名不同赛、迁场沿革及年度改场混在一起。`2026-07-13` 的人工审核把 `102` 个临时 Key 归入 `58` 条正式赛事线，并修正京都雌马、Bristol届次、Louisville 2008、Keeneland First Lady年度名和NYRA Matron 2018等已确认异常。为保留可追溯性，原始 v10 总账保持不变，审核结果写入独立 v11；每个年度目标保留 `provisional_series_key`、正式 `series_key`、身份决策来源和别名。

赛事身份判断以沿革、场地、距离原单位、竞赛类型、年龄性别条件和同年并存情况共同决定，不能仅按裸赛事名或裸距离自动合并。实际年份与届次年份必须分开，例如 Bristol Novices' Hurdle 的 2001 届实际于 `2002-01-11` 举办。Ascot约3m金杯线中文主名确认为 `阿斯科特秋季金杯让磅障碍追逐赛`。高相似名称最终采用“15对名称变体合并、Prince of Wales's与Princess of Wales's保持独立”的审核结论，原始写法继续作为别名留存。

## 为什么历史赛事身份审核必须提供逐届参赛证据并保留距离原单位

同名赛事只比较名称、赛场和裸距离，容易把不同赛事错误合并，也可能把真实举办年份误判为 `not_held`。因此身份审核表必须把系列展开为逐年届次：能取得正式赛果时展示冠军马，能取得出马表或赛果明细时展示1号马；两者都不能可靠取得时保留该年度官方目录链接，不用模糊匹配填充空白。目录状态与官方赛果冲突时只标记待审，不自动修改总账。

不同地区和竞赛类型的距离单位不同，任何身份规则都不得直接比较 `distance_text` 裸数字。审核产物先保留 TJCIS 原始距离文本和竞赛类型；后续标准化模型必须分别保存原始数值、原始单位、统一换算值及换算规则来源，只有单位明确后才允许参与距离一致性判断。

## 为什么技术审查问题默认直接修复，产品能力与交互仍需用户审核

后续 code review 发现的纯技术问题，例如正确性、安全门禁、并发、性能、测试缺口、状态一致性和可维护性问题，默认由 Codex 直接修复、补测试并完成验证，不再逐项等待用户确认。这样可以减少已经明确方向后的重复审批，让技术返修持续推进到全绿。

涉及产品能力、数据范围、运营规则、用户流程、页面交互、公开可见性或文案体验的变更，仍必须先说明影响并交由用户审核。技术修复如果会实质改变上述产品行为，也按产品问题处理，不得借“技术优化”名义直接改变既定能力边界。

## 为什么马匹详情页使用 ID URL、草稿默认不可见并由后台审核发布

马匹名称存在多语言、重名、改译、别名和后续术语合并风险。若把公开 URL 绑定到马名或 slug，后续改名会带来重定向、重复页面和 SEO/缓存一致性问题。

因此马匹详情页 MVP 使用稳定唯一 ID：

- 公开索引：`/horses/`
- 公开详情：`/horses/<HorseProfile.id>/`
- 关注管理：`/horses/follows/`

P0 马匹页可以从 active horse `TermEntry` 默认生成，但生成后状态为 `draft`，前台返回 404；只有后台 `/admin/horse-profiles/` 人工审核、补充资料并手动发布后才公开展示。为了支持运营抢先建入口，管理员即使在资料完全空壳时也可以强制发布，但该动作会记录发布人、发布时间和备注。

## 为什么马匹关注对普通用户开放且只保存 token hash

关注功能的产品目标是让用户在新闻首页看到“关注马及其子孙代”的相关新闻，而不是后台运营专属标记。因此普通未登录用户也可以关注马匹。

实现采用匿名签名 cookie：

- cookie 保存签名后的随机 token，`HttpOnly`、`SameSite=Lax`，HTTPS 配置下启用 `Secure`。
- 数据库 `HorseFollow` 只保存 `token_hash`，不保存明文 token。
- 关注 POST 保持 CSRF 保护。
- 子孙代新闻只通过 `sire_horse_profile` / `dam_horse_profile` 的直接 profile 关系递归查询，纯文本血统不参与后代查询。

## 为什么用 HorseRaceRecord 承载完整参赛履历

马匹页第一版需要展示主胜鞍，但后续目标是每匹马的完整参赛履历。如果只建“主胜鞍表”，未来会重复建模参赛事实，也难以表达参加但未获胜、退赛、未上名等结果。

因此本轮新增 `HorseRaceRecord` 作为马-比赛事实表：

- 可选关联 `RaceEvent` / `RaceEventResult`，同时保存比赛快照字段。
- 覆盖参加过的比赛，不限于赢过的比赛。
- 主胜鞍由最高等级胜利和人工 `is_major_win` 标记共同决定。
- 无胜利、新马/未胜利、无重赏和人工指定场景都可以保守展示。

## 为什么外部血统补全走 dry-run artifact 而不是直接写公开数据

马匹资料需要尝试从外部数据补完整二代血统，但来源覆盖率、命名歧义、地区差异和反爬/限流都会影响准确性。直接从公开页或审核页实时请求第三方，会放大延迟、稳定性和来源合规风险。

因此补全策略是：

- 公开 `/horses/`、`/horses/<id>/`、首页关注模块和新闻详情 tag 只读本地数据库，不访问外部网络。
- `complete_horse_profiles --dry-run` 基于本地 `ExternalHorse` / `ExternalHorseAlias` 缓存生成 artifact、CSV 和 summary。
- summary 必须包含全局/按地区完整二代成功率、未补全占比、逐马失败原因、source URL 和候选 diff。
- `--commit` 必须读取已审核 artifact，并显式提供 `--confirm-reviewed-artifact`，不允许边抓边写。
- `new-village/KeibaScraper` 只作为受控 netkeiba 导入链路的可信数据源参考；项目当前采用本地缓存和低频导入，避免公开请求路径触网。

## 为什么马名和术语匹配一律大小写不敏感

外部赛马数据和新闻源对英文马名、赛事名、骑师名等术语的大小写并不稳定：HKJC 可能使用全大写，新闻标题可能使用标题式大小写，人工术语库也可能保留来源原始写法。如果按大小写精确匹配，会导致同一匹马在补全、新闻关联、术语替换和翻译保护链路中被误判为未命中。

因此所有含拉丁字母的术语匹配采用大小写不敏感规则：

- 术语解析、术语替换和单条术语应用对拉丁字母忽略大小写，并保留英文词边界保护。
- 外部马名 alias 和 `HorseProfile` 补全匹配使用大小写不敏感的规范化 key。
- 前台展示仍保留数据库中的原始写法；大小写不敏感只影响匹配与替换，不自动改写术语主数据。
## 为什么赛事信息编排工具第一版只服务 RaceEvent 产品层

赛事历史回填有两套容易混淆的数据层：

- `RaceEvent*`：产品层赛事，服务 `/races/`、赛事详情页、后台赛事工作台、出走表、赛果、历届冠军和相关新闻组织。
- `ExternalRace*`：外部来源缓存层，服务真实赛马数据库导入、外部马名索引和原始来源证据。

本轮 OpenSpec change `orchestrate-race-event-data-crawls` 的第一版目标是补齐赛事页可展示和可运营的结构化赛事信息，因此只服务 `RaceEvent*`，不写 `ExternalRace*` / `ExternalHorse*`。这样可以避免把“产品层赛事历史回填”和“底层外部数据库导入”混成一个过大的系统，也能让 apply 门禁聚焦在 `RaceEventRunner`、`RaceEventResult`、`RaceEventHistoryWinner` 和 `RaceEventDataCandidate` 的完整性与覆盖风险上。

对应边界：

- 五个目标地区为日本、香港、英国、法国、美国。
- 第一版同时覆盖 `runners`、`results`、`history_winners`，且同一目标范围内三模块历史深度一致。
- 第一阶段只追核心 Group / Grade / Jpn / 交流分级 / 障碍分级等重点赛事，不包含 Listed，也不追所有普通比赛。
- 历史赛事系列必须显式 `series_key` / mapping；名称模糊匹配只能进入待审候选，不得直接写正式赛事详情数据。
- 长周期抓取默认手动分批或一次性容器执行，不加入 Celery Beat，不做无人值守自动 apply。

## 为什么赛事信息编排工具需要 adapter manifest 和目标赛事行预检

现有 `runtime/tools` 详情脚本已经能生成不少候选数据，但它们不是统一命令行接口：有的依赖 `--review-csv`，有的需要 `--source-html`、`--runner-jsonl` 或 `--pdf-dir`，部分产物还使用固定年份或来源特有文件名。因此第一版编排工具不假设所有脚本都有统一 `events_csv/output_dir` 契约，而是通过 adapter manifest 逐个声明脚本路径、参数映射、依赖产物、必需输出、source authority 和输出归一化规则。

深历史详情导入还受现有 importer 约束：`import_race_event_detail_candidates` 在 dry-run 阶段也会按 `year + slug` 查找 `RaceEvent`。如果某个历史年份的目标 `RaceEvent` 行尚不存在，详情候选即使抓到了也不能直接 dry-run 或 apply。因此编排工具必须先做目标赛事行预检；缺失时输出 draft seed review artifact 和 `missing_race_event` blocker，经人工确认或导入目标赛事行后，才能进入详情候选 dry-run 与 apply-check。这个规则避免把“抓到详情候选”误判为“已经可以安全写入公开赛事页”。

## 为什么 coverage、dry-run 和 apply-check 必须绑定候选文件哈希

赛事详情批量 apply 会按模块替换已有正式行，仅凭文件路径或“某个 dry-run 文件存在”不足以证明最终导入的就是已经审计的数据。候选文件可能在 coverage 后被修改，也可能在 apply-check 时通过另一个路径替换；旧日志、空文件或其他批次结果也不能证明当前候选 dry-run 通过。

因此编排工具把候选 JSONL 的绝对路径、大小和 SHA-256 作为批次证据身份：coverage audit、结构化 `dry_run.json` 和最终 apply 文件三者哈希必须一致。adapter manifest 同时作为 provenance 权威声明，标准候选由编排层注入 `adapter_key`、`source_provider`、`racing_region` 和 `source_authority`；缺失、非法或与 manifest 冲突的来源信息直接阻断。若同一赛事的模块使用不同来源或权威等级，coverage 生成稳定策略哈希，apply-check 只有在人工确认显式包含这些哈希时才放行。

同一原则也用于 resume：跳过 adapter 不只依赖输入未变化，还必须确认上次所有必需输出仍存在且哈希一致。这样可以避免运行目录被清理或产物被修改后，state 仍错误地声称该 adapter 可以复用。

## 为什么法国 TDN broad 上线时同时允许 `tdn_france:access` 和 `tdn:access`

`tdn_france_broad` 是法国新闻补充来源，但为了和既有 TDN 去重共用同一篇原文，入库时会使用 canonical source site `tdn`，同时通过 `source_config` 保留“这是法国来源发现的文章”。

生产发布白名单判断会先看文章主来源 `article.source_site:article.source_mode`，不匹配时再看 `source_config_id`。如果只允许 `tdn_france:access`，抓取可以成功，但自动发布策略可能看到文章主来源 `tdn:access` 后判定为 `source_not_allowed`。

因此 `2026-07-07` 上线法国 TDN broad 时，生产 `.env` 同时加入：

- `tdn_france:access`：表达运营意图，即法国补充来源被允许。
- `tdn:access`：匹配 canonical 入库后的文章主来源，避免发布策略误挡。

这不会放开所有 TDN 普通新闻；它只匹配 access 模式，并且文章仍需满足地区、评分、术语门禁、发布窗口配额和 QQ 限流。

## 为什么使用香港 ECS

当前阶段选择香港 ECS，主要基于以下考虑：

- 面向中文用户，访问延迟相对可接受
- 与大陆相比，部署与公网访问流程更直接
- 不需要先被大陆备案流程阻塞
- 适合项目早期先验证真实可用性

## 为什么当前阶段不做大陆备案路线

当前目标是先把产品链路跑通，而不是先投入备案周期。

不优先走大陆备案路线的原因：

- 备案流程会显著拉长首个可用版本上线时间
- 当前更需要先验证抓取、翻译、后台、前台、域名接入是否闭环
- 项目仍处于迭代和修正阶段，先以可运行、可验证为主

后续如果产品稳定、需要大陆更优访问体验，再评估备案与境内部署。

## 为什么继续使用 Django 单体 + Docker Compose 主干

当前继续保留 `Django 单体 + Docker Compose` 主干，而不做大分离或复杂服务化，原因是：

- 后台、前台、任务调度、模型管理都可在 Django 内保持高协同
- 当前团队规模与项目阶段更适合低复杂度架构
- Docker Compose 足以支撑单机阶段的生产部署与维护
- 当前瓶颈主要是上线稳定性与运维闭环，而不是架构扩展性

## 为什么项目记忆要写入仓库文档，而不是只依赖聊天上下文

这是本项目的重要协作原则。

原因包括：

- 聊天上下文天然易丢失，不适合承载长期项目状态
- 新 session 或新协作者需要能从仓库直接恢复上下文
- 生产问题、运行态差异、关键决策必须可追溯
- 文档化后的项目记忆更容易和代码、配置、部署资产一起演进

## 为什么术语合并后保留 inactive 历史主术语

`TermEntry.is_active=false` 不只表示“废弃错误词条”，也可以表示某个历史主术语已经被更完整的正式概念吸收。

HKJC 日语 alias 合并采用这个语义：

- 英文 HKJC 官方概念作为主概念保留 active
- 同一中文译名、同一类型的日语主术语被转换为该主概念的 active alias
- 原日语主术语设为 inactive，并在 notes 中记录 `hkjc_ja_alias_merged_into_term_id=<target>`

这样做可以避免同一马名在后台搜索、翻译替换和文章回填中形成两个 active 概念，同时保留来源可追溯性。后续排查 inactive 术语时，优先看 notes 是否存在合并标记；有标记的记录应视为“已合并历史概念”，不是需要恢复的漏导入。

## 为什么当前先做 HTTP，再补 HTTPS

正式域名接入阶段先做 HTTP，再补 HTTPS，是为了降低并发排障维度。

原因是：

- 如果 DNS、Nginx、Django Host、反代、证书同时变化，定位问题会更困难
- 先完成 HTTP 域名打通，可以确认：
  - DNS 正常
  - 域名已到服务器
  - `nginx` 反代链路正常
  - Django 域名配置正确
- 在 HTTP 稳定后，再接入 HTTPS / Certbot / 强制跳转，排障范围更清晰

## 为什么自动化运营采用“规则优先 + AI 改写 + 校验”

自动发布会直接影响前台内容质量，因此不能把“是否发布”完全交给黑盒模型。

当前实现选择：

- 规则先判断硬性忽略项和必须人工审核项
- 再按来源、内容价值、P0 马、赛事优先级、时效性和结构完整度评分
- AI 负责把基准翻译稿改写成中文资讯稿
- 改写后再做术语、数字、未收录马名、引语等一致性校验

这样可以做到自动化可解释、可回看、可人工接管。

## 为什么自动化默认通过 `.env` 开关灰度启用

自动发布属于生产风险较高的能力，代码完成不等于应立即在线上全量打开。

因此新增 `AUTOMATION_ENABLED` 开关：

- 生产可以先部署迁移但保持关闭
- 后台确认字段、日志和任务正常后再开启
- 如果自动化效果不稳定，可以不回滚代码，只关闭开关

## 为什么通知 MVP 只真实发送邮件

PRD 提到邮件、短信、微信或 QQ 通知，但首版只接入邮件，其他渠道先写 `NotificationLog` 并标记为 `skipped`。

原因是：

- 邮件成本低、接入稳定、适合异常告警 MVP
- 短信需要服务商、费用和模板审核
- QQ / 微信通知涉及账号、风控和协议稳定性
- 先把异常通知留痕和最小真实发送跑通，比一次性接入多个不稳定渠道更可靠

## 为什么 QQ 群自动推送使用独立交付记录

自动推送需要处理多群、重复触发、有限重试和部分失败。如果直接复用手动推送的 `PushLog`，同一篇文章对同一群可能因为 Celery 重试或重复发布触发而产生多条发送尝试，难以保证“只自动推一次”。

因此自动推送新增以“文章 x 群”为唯一粒度的交付记录：

- 成功后后续自动编排不会重复发送到同一群
- 多个群可以分别成功、失败或重试
- URL 检查失败和 OneBot 发送失败可以分开排查
- 手动推送保留原有日志语义，不受自动推送状态机影响

`sending` 只表示当前有任务正在领取并尝试交付，不作为永久锁。若 worker 异常退出或任务在外部 I/O 中断，记录超过 `QQ_PUSH_SENDING_STALE_SECONDS` 后允许后续任务重新领取；这样可以在有限重试内恢复，而不是长期卡在“发送中”。

OneBot HTTP API 的 HTTP 200 也不直接等于发送成功。应用会继续检查 OneBot JSON 中的 `status` / `retcode`，业务失败按 `send_failed` 记录，避免 QQ 群实际未收到消息但交付记录显示成功。

OneBot 网关离线或登录态失效时，自动推送会在真正调用 `/send_group_msg` 之前暂停本次交付，并记录 `send_failed` 错误摘要，但不会增加 `attempt_count`。这样做是因为 QQ 重新扫码登录后，原文章仍然可以继续发送；如果把离线状态当成一次真实发送尝试，短时间内的队列重试会把可恢复交付快速打到失败上限。

## 为什么 QQ 群自动推送默认关闭且默认只推高价值新闻

QQ 群是强打扰分发渠道，上线初期如果全量推送，容易刷屏，也更容易暴露 QQ 账号风控和 OneBot 网关稳定性问题。

因此生产默认：

- `QQ_PUSH_ENABLED=false`：先部署代码和迁移，再配置 Bot、测试群和灰度
- `QQ_PUSH_SCOPE=high_value_only`：首版只推 `score_total >= AUTO_REVIEW_THRESHOLD` 的新闻

如需验证链路或临时全量推送，可以显式切换为 `QQ_PUSH_SCOPE=all_public`。

## 为什么 QQ 重点推送要拆分范围配置和策略配置

QQ 自动推送后续会存在多种“重点”口径：本期按 netkeiba 访问量榜 / 注目数榜推送，后续可能扩展为“榜单 + 每场比赛当天高频推”或重新支持“按分数推”。

因此后续配置需要区分两层含义：

- `QQ_PUSH_SCOPE` 表示推送范围：例如 `high_value_only` 只推重点，`all_public` 临时推所有公开新闻。
- `QQ_PUSH_IMPORTANCE_STRATEGY` 表示“重点如何判定”：本期统一为 `ranked`，即 netkeiba 访问量榜和注目数榜。

这样可以避免把 `high_value_only` 永久绑定到某一个算法，也能让后续策略扩展只修改重点判定函数，而不破坏自动推送交付、去重、重试和多群配置。

无论采用哪种重点策略，QQ 推送都不得绕过自动发布门禁。阻断问题以 `NewsArticle.gate_blockers` 或 `gate_issues.severity=blocker` 为准，QQ 服务只消费现有结构化门禁结果，不重新实现一套独立 blocker 规则。

## 为什么 OneBot API 不公网裸露

OneBot HTTP API 可以直接发送群消息，一旦公网裸露且 token 泄露或配置不当，就可能被滥用。

因此生产部署约束为：

- 优先使用 Docker 内网 `http://onebot:3000`
- 临时宿主机映射只能绑定 `127.0.0.1`
- 必须配置 access token
- 应用日志不得输出 token

## 为什么保留 fallback 改写 provider

真实 AI 改写依赖模型 Key、余额、网络和供应商稳定性。

因此保留 `fallback` 改写 provider：

- 本地测试和 CI 不依赖外部 API
- 模型不可用时仍能保守生成改写稿快照
- 生产可通过 `REWRITE_PROVIDER` 切换到 SiliconFlow 或 OpenAI-compatible provider
- 自动化主流程可以先验证状态机、日志和发布闭环，再优化真实改写质量

## 为什么赛事日历新增“复合赛道”surface

2026 美国 TOBA Grade 批次中存在 `Sur=A` 的 all-weather / synthetic 赛事，例如 Turfway Park 的 Jeff Ruby Steaks。若把这些赛事硬映射为 `dirt`，前台会显示“泥地”，与官方赛道类型不一致。

因此 `RaceEventSurface` 新增 `synthetic=复合赛道`：

- 可以准确承载美国 all-weather / synthetic 赛事。
- 后续英国、法国或其他地区出现 Polytrack、PSF、Tapeta 等复合赛道时可复用同一字段值。
- 仍保留官方原始 surface code 到 `source_refs`，便于之后做更细的赛道材质标准化。
- 这是枚举与展示层补充，不改变 `RaceEvent` 主表结构或现有 turf/dirt/jumps 数据语义。

## 为什么赛果同着使用唯一排序位写库并保留官方名次

JRA 官方赛果会出现同着，例如两匹马同为第 `2` 名。当前 `RaceEventResult` 对 `(event, finish_position)` 有唯一约束，不能直接写入两条相同 `finish_position`。

因此 2026 JRA 详情导入采用两层口径：

- `RaceEventResult.finish_position` 保存唯一排序位，用于数据库约束、排序和稳定渲染。
- `source_refs.official_finish_position` 与 `source_refs.jra_finish_position_text` 保存官方名次。
- 前台赛事日历和赛事详情页优先展示官方名次；没有官方名次时才展示排序位。

这样既不破坏当前数据库约束，也不会在用户可见页面把同着第 `2` 名错误展示成第 `3` 名。后续若要彻底支持同着、DNF、取消和除外的完整赛果语义，可以再扩展 `RaceEventResult` 的展示名次字段或调整唯一约束。

## 为什么法国 2026 赛事详情暂用 ZEturf 作为公开结果源

France Galop 官方结果入口当前会重定向到认证页，不能稳定批量读取出走表和赛果；Geny 对本批 France Galop Groupe 赛事覆盖不足，不能作为唯一来源。ZEturf 的 race detail 页面当前可通过日期和 R/C 编号访问，并提供出走表、非出走标记和到达顺序，因此本轮法国 2026 详情先用 ZEturf 作为可访问公开来源。

## 为什么英文术语发布门禁先用地区过滤和配置化高歧义词清单

多地区英文新闻中，`CLASS`、`CONTENT`、`LINK`、`AGENT` 等既可能是正式术语，也常常只是普通英文词。如果把所有地区、所有英文正式术语都拿来做硬门禁，香港马名会阻断英国新闻，普通词也会把可发布文章打入人工审核。

因此 `fix-english-term-gate-region-filter` 第一版采用保守止血策略：

- 英文文章只校验同地区术语和 `racing_region=""` 全局术语。
- 需要跨地区通用的词条先治理为全局术语，不通过 notes 或 metadata 做隐式跨地区契约。
- 高歧义英文词先由 settings / 环境变量清单控制，降级为 warning/info 并保留审计 payload。
- 短词 / 全大写等自动派生歧义规则只用于非核心命中；未配置的同地区 / 全局高可信核心实体缺失仍然阻断。
- 不新增 `TermEntry` 字段，避免为止血引入迁移和后台维护成本；后续如运营需要可再设计 `publish_gate_level` 等字段。
- 真正同地区或全局高可信核心赛事、马名、骑师名、练马师名缺失仍然阻断自动发布。

为降低同日同场多场赛事误匹配风险，法国详情导入必须用页面 title 的日期、场地和赛事名共同确认；赛事名 token 匹配排除赞助词和场地词，并对短赛事名使用更严格匹配。若后续 France Galop 官方结果页恢复可访问，应优先切回官方源或用官方源复核 ZEturf 数据。

## 为什么已确认非术语进入发布门禁忽略清单

候选池 raw 抽取会保留所有可能触发术语识别的原文片段，其中一部分已经由运营确认不是术语，例如源站导航、产品名、HTML/布局片段、普通赛马词、马名/人名片段或广告文本。这些词如果被误建成 active `TermEntry`，或者被后续规则误识别为核心术语，就会让国际新闻源因为“假术语缺失”进入人工审核。

因此 `2026-07-10` 本地新增 `MULTIREGION_TERM_GATE_IGNORED_SOURCE_TERMS`：

- 命中该清单的 source term 在发布校验中记录为 `non_term_gate_ignored` / `info`。
- 它不产生 `core_term_missing` 或 `background_term_missing`，不阻断自动发布，也不触发高价值 warning 邮件。
- 该机制独立于英文高歧义词清单；高歧义英文词仍用于“可能是术语但风险高”的降级，非术语清单用于“运营已确认不是术语”的忽略。
- 清单通过 settings / 环境变量可调整，便于后续把误加入的项移除，或继续从 raw no 类样本补充。
- 真正同地区或全局高可信核心赛事、马名、骑师名、练马师名缺失仍然阻断自动发布。

## 为什么历史冠军先写当前年度冠军作为第一层

`RaceEventHistoryWinner` 当前用于前台“近年冠军”模块。完整过去年份历届冠军需要按地区继续接入不同官方历史源，范围远大于 2026 当年赛事详情填充。

因此本轮先从已确认 `RaceEventResult` 中抽取每场 `2026` 年冠军写入 `RaceEventHistoryWinner`：已有赛果的已完赛赛事不会再显示“暂无历史冠军资料”，也不会猜测缺赛果赛事。这个数据层只代表当前年度冠军，不等同于完整历届冠军；后续补齐过去年份时，应以地区官方历史源生成完整 `history_winners.items` 后覆盖同一赛事的历史冠军列表。

## 为什么引入 OpenSpec + Codex 领域代理

项目已经进入自动化运营、HTTPS、部署稳定化和运维完善并行推进阶段，跨模块与生产高风险改动会逐渐增加。

因此仓库引入 OpenSpec 作为较大改动的规格驱动工作流：

- 在实现前先形成可版本化的 proposal、spec、design 和 tasks
- 通过 `tasks.md` 保留进度，使新 session 可以从仓库恢复上下文
- 使用 `application / integration / operations` 三个真实仓库领域拆分任务
- 子代理只在明确要求时启用，避免无控制的并行修改
- 小型修复不强制创建 OpenSpec change，但仍遵守现有阅读、验证与文档回写要求

OpenSpec 项目上下文与任务规则以 `openspec/config.yaml` 为准；项目全局状态仍以 `docs/current_state.md` 为准。

## 为什么仓库协作文档默认使用中文

项目面向中文用户，当前主要协作者也以中文进行需求、运营和生产排障沟通。为了降低新 session 恢复上下文、人工审阅规格和运维执行时的理解成本，仓库内由 Codex 新增或维护的协作文档默认使用中文。

具体约定：

- OpenSpec proposal、spec、design、tasks 的说明性内容使用中文
- Codex 代理描述、项目上下文和面向协作者的说明使用中文
- 命令、代码标识符、协议字段、第三方工具强制要求的机器语法可以保留英文
- OpenSpec 规格校验依赖的 `ADDED Requirements / Requirement / Scenario / WHEN / THEN` 等结构关键字保留英文，具体标题和内容使用中文
- 上游工具自动生成且约定不手工修改的文件维持原样

## 为什么术语发现结果必须先进入候选池

专有术语会直接影响翻译、改写、自动分流和重点赛事识别。自动识别仍可能存在误报、实体类型混淆和同名冲突，因此首版采用“发现与确认分离”：

- 规则发现器只创建或更新 `TermCandidate`，不能直接创建 `TermEntry`。
- 与正式术语同类型命中时不创建候选，跨类型命中时保留冲突信息供管理员判断。
- 接受、修改后接受和合并必须由工作人员在后台逐条完成。
- 合并到正式术语时，只有管理员明确勾选后才把候选文本加入日文别名。
- 拒绝和忽略状态在后续重复发现时保持稳定，避免候选池反复污染。

该设计优先保证正式术语库可信，并为后续接入模型识别或更多信息源保留可审计证据。

## 为什么国际化术语库采用“正式术语概念 + 多语言原文别名”

接入日本、中国香港、英国、法国和美国新闻后，同一匹马、同一场赛事或同一个人物可能同时出现日文名、英文名和繁体中文名。如果把每种语言都建成一条独立 `TermEntry`，后台会出现多个“同一实体”，自动评分、标签、翻译校验和候选合并也会越来越难解释。

因此本轮国际化返修采用两层模型：

- `TermEntry` 表示正式术语概念和标准简体中文译名，例如一匹马“春秋分”。
- `TermAlias` 表示该概念在不同原文语言下的名称或别名，例如 `イクイノックス / Equinox / 春秋分`。

文章匹配时只使用与文章 `source_language` 一致的原文别名，避免英文文章误命中日文别名；命中后仍回到同一个 `TermEntry`，用于统一的中文译名、标签和评分。

本轮保留 `TermEntry.source_ja / aliases_ja` 作为兼容字段，迁移会把旧数据回填为 `ja` 别名。后续如果要彻底重命名旧字段，应另起清理 change。

## 为什么 HKJC 日语 alias 合并会停用冗余日语主术语

HKJC 官方英文概念和既有日语主术语如果拥有同一术语类型和同一中文目标，继续保留两个 active `TermEntry` 会让后台搜索、文章术语替换和后续审计出现“同一实体多概念”的歧义。

因此 `hkjc-ja-alias-article-backfill` 采用保守合并策略：

- HKJC 英文 `TermEntry` 作为正式概念承载标准中文译名。
- 日语 source text 写入该概念的 `TermAlias(source_language=ja)`。
- 原独立日语主术语停用，并在 notes 记录合并目标 term id。

这样做不会删除历史记录，也解释了术语库中少量 inactive 术语的来源：它们可能是已经被更完整概念吸收的历史主术语，而不是应继续参与匹配的正式概念。若中文目标、术语类型或 active owner 存在冲突，系统只输出人工复核记录，不自动合并。

## 为什么已发布文章术语回填不重新翻译整篇文章

术语补齐后，历史已发布文章中可能仍保留日文或英文 source text。这个问题的修复目标是“精确替换术语”，不是重做内容生产。

因此文章回填采用字段级 diff/apply：

- dry-run 输出完整 before/after 字段值和人工复核 CSV。
- apply 只替换明确命中的 source text。
- 默认跳过人工编辑过的发布字段。
- 不重新抓取、不重新翻译、不调用 AI 改写、不改变发布、审核、workflow 或 QQ 推送状态。

这能把生产写入范围限制在可审计、可恢复的最小改动内；大范围内容重译或风格重写应另起 change。

## 为什么公开首页升级先做主 OpenSpec change

公开首页从 MVP 页面升级为 Web + 移动 H5 成熟资讯流，虽然主要发生在模板、样式和视图层，但它会影响前台信息架构、后续子能力边界和用户内容消费路径，因此先创建主 OpenSpec change `upgrade-public-home-info-feed` 作为指导规范。

这样做的原因：

- 首页不再只是“已发布文章列表”，而是要定义头条、普通流、热门代理、详情页和响应式布局的长期基础。
- 后续手工置顶、搜索频道、专题、赛事日历、站内热度等能力都可能接入首页，如果没有主规范，容易把不同问题混在一次实现里。
- 当前前台模板直接引用后台 `console.css`，需要先确立公开站点样式解耦方向，避免后台和前台继续互相牵连。
- OpenSpec 主 change 可以明确本轮只做公开资讯消费体验，不改抓取、翻译、自动发布和部署主链路。

## 为什么第一版首页不新增手工置顶或赛事日历模型

第一版首页升级选择复用现有 `NewsArticle`、`NewsSnapshot`、自动评分和赛事优先级字段，先完成算法化头条、普通新闻流和热门代理展示，不新增首页运营控制或赛事日历数据模型。

## 为什么赛事日历 MVP 使用年度 RaceEvent 产品层

赛事日历第一版采用“每年一个赛事页”的 `RaceEvent` 产品对象，而不是直接公开 `ExternalRace` 或把现有 `MajorRaceEvent` 扩成前台赛事页。

原因是：

- 前台赛事页需要可见性、资料完整度、候选确认、人工锁定和新闻纠偏，这些属于产品运营语义。
- `ExternalRace` 继续表示外部原始数据，不能直接承担“已确认可公开”的状态。
- `MajorRaceEvent` 继续服务抓取 / 发布窗口升频，不写入公开可见性、候选资料或赛果。
- 年度粒度符合赛前资料、出马表、闸位、赛果和相关新闻都随年份变化的产品形态。

第一版保留 `series_key`，只作为未来跨年系列聚合的内部伏笔，不提供系列页。

## 为什么赛事候选资料必须人工确认后再公开

赛事信息整体稳定，但指定网站抓取仍可能出现字段缺失、格式差异或来源冲突。第一版因此采用“公开字段”和“候选资料”分离：

- CSV 或后台创建的赛事满足名称、日期、马场、等级等最小条件后可展示。
- 指定网站抓取结果只写入 `RaceEventDataCandidate`，不自动覆盖公开结构化字段。
- 后台按模块应用候选，应用行为写入操作日志或任务日志。
- 已人工编辑或锁定的字段不被普通候选覆盖。

这让自动化能减轻录入工作，但最终可公开资料仍由运营人员拍板。

## 为什么赛事动态字段只对白名单自动刷新

赔率、热门度、出走状态和退赛状态变化快，适合在详情页出马表中作为动态字段刷新；赛事名称、日期、马场、等级、surface、距离、参赛条件等基础资料相对稳定，自动覆盖会增加误伤风险。

因此第一版动态刷新只允许：

- `odds_value`
- `popularity`
- `running_status`
- 退赛 / 取消出走类状态

刷新失败时保留最后一次成功值和更新时间，只在后台记录错误。

## 为什么赔率只放在赛事详情页而不进赛事日历

赛事日历的目标是按时间快速扫描赛事，不承担投注或赔率导向。赔率信息敏感且变化快，放进列表会放大合规和误读风险。

因此第一版约束为：

- 赛事日历移动卡片和 PC 表格不展示赔率。
- 赔率只在赛事详情页概览的出马表中作为普通动态字段展示。
- 赔率不进入详情页 Header，也不建设独立赔率模块。

## 为什么马匹数据库延期

赛事日历 MVP 只需要展示年度赛事、出马表、前几名赛果、历史冠军和相关新闻。完整马匹数据库、马匹详情页、血统、历史战绩会显著扩大数据建模和导入复杂度。

因此第一版只在 `RaceEventRunner`、`RaceEventResult` 和 `RaceEventHistoryWinner` 中保存展示所需的马名文本，不建立独立马匹产品页。未来如要抽出马匹数据库，应另起 change 处理。

原因是：

- 现有字段已经足够支撑“重点内容突出 + 普通内容高密度”的第一版体验。
- 手工置顶会引入推荐位模型、后台表单、排序冲突、开始/结束时间和运营权限规则，更适合作为后续独立 change。
- 赛事日历需要结构化赛事、场地、开跑时间和数据源，不应伪装成已有新闻标签或术语数据。
- 热门榜当前只能使用 netkeiba 上游访问/注目快照或自动评分回退，不能包装为本站浏览量或本站评论。

因此后续规划拆为：

- `upgrade-public-home-info-feed`：主首页与详情页信息流升级。
- `add-homepage-editorial-placement`：手工头条、推荐位和置顶。
- `add-public-topic-search-navigation`：搜索、标签页、频道页和专题页。
- `add-race-calendar-sidebar`：结构化赛事日历和今日重要赛事模块。

## 为什么 QQ 群空地区配置按旧日本行为处理

国际赛马资讯扩展后，QQ 群级配置需要区分“系统能不能推”和“这个群想看什么”。如果把旧群的空 `allowed_regions` 解释为所有地区，部署后既有群会在没有明确订阅的情况下突然收到中国香港、英国、法国和美国新闻。

因此本轮约定：

- `QQ_PUSH_ENABLED` 仍是总开关，只决定是否运行自动推送。
- `PushTarget.allowed_regions` 决定该群允许接收哪些地区。
- 迁移会把既有群回填为 `["japan"]`。
- 运行时如果仍遇到空 `allowed_regions`，也按旧行为仅允许日本新闻，而不是默认允许全球新闻。

这样能让国际新闻源上线后按群灰度启用，不打扰只想继续看日本新闻的旧群。

## 为什么公开首页资讯流升级要求严格 TDD

公开首页升级虽然主要是前台视图、模板和样式改动，但它会改变已发布文章在用户侧的呈现规则，包括发布过滤、头条选择、普通流排序、热门代理和详情页有效稿件字段展示。为了避免实现过程中只凭视觉调试而破坏已有发布链路，`upgrade-public-home-info-feed` 后续实施要求严格 TDD。

执行原则：

- 每个可测试行为单独执行 RED -> GREEN -> REFACTOR：先在 `server/stable/tests.py` 中新增一个失败测试并确认红，再实现该行为的最小代码并确认变绿，最后做局部重构。
- 禁止一次性批量写完全部测试后再实现；发布过滤、普通流排序、头条选择、热门代理、详情页字段和公开静态资源都必须按行为分轮推进。
- 热门代理实现必须在有限已发布候选集内批量读取 `NewsSnapshot` 或使用等价预取方式，避免无上限扫描或逐篇文章查询最近快照。
- 所有 TDD 循环通过后，再跑完整 `stable` 测试。
- CSS 和响应式体验不适合全部单元测试化，因此用桌面/移动浏览器视口验收作为补充验证。

该决策只约束本 change 的实施顺序，不要求为纯视觉像素差异编写脆弱测试。

## 为什么外部赛马数据采用离线低频导入

未知马名识别需要更可靠的马名来源，但不能把新闻抓取、翻译或自动发布链路绑定到实时访问 netkeiba。

因此外部赛马数据采用离线低频导入与本地索引方案：

- 使用 `keibascraper` 作为可替换适配层的数据来源，不让业务代码直接依赖第三方库返回结构。
- 先按近两年比赛、出走、赛果、马匹和履历建立本地缓存，保存结构化字段与原始 payload。
- 从出走表、赛果和可信单马参数派生本地马名索引，后续再让未知马名识别消费该索引。
- 生产默认关闭网络导入，必须人工显式触发，并且强制限速、抖动、批量上限和同一来源互斥。
- 导入失败只写入导入错误记录，不影响新闻抓取、翻译、AI 改写、自动发布和公开前台。

这个方案优先保证生产主链路稳定，也为后续替换为 JBIS、JRA-VAN 或本地公开数据库保留边界。

## 为什么外部马名索引不等同于正式术语库

外部赛马数据导入得到的 `ExternalHorseAlias` 只证明某个日文文本是外部数据源确认过的马名，不证明系统已经有可信中文译名。因此后续接入文章准备、翻译和校验时，必须把“确认是马名”和“有中文译名可替换”拆开。

设计边界如下：

- `TermEntry` 继续作为正式术语库，保存有中文译名、固定译法或人工确认别名的词条。
- `ExternalHorseAlias` 作为本地马名索引，只用于识别、保护、校验和候选发现，不批量写入 `TermEntry`。
- 如果同一马名同时命中 `TermEntry` 和 `ExternalHorseAlias`，以 `TermEntry` 为准，进入中文术语提示和译后替换。
- 如果只命中 `ExternalHorseAlias`，翻译阶段应保护原始日文马名，不能擅自生成或替换中文译名。
- 术语候选池应把新闻中出现、外部索引命中但缺少正式中文译名的马名均作为高置信候选，包括正文背景段落中的马名，让工作人员决定是否补入正式术语库。
- 普通词与外部马名同名时不能无条件信任数据库，必须结合强马名上下文消歧；缺少强马名上下文时不得把普通词当马名。
- 同一日文马名可能对应多个外部 horse ID，识别结果必须保留全部匹配 ID，并只把主 ID 作为展示辅助，避免静默丢弃同名歧义。

## 为什么国际赛马资讯扩展先做多地区承载和 HKJC 导入

项目下一阶段需要从日本赛马资讯扩展到日本、中国香港、英国、法国和美国，但不同地区的新闻语言、数据库开放度、审核可读性和 QQ 群偏好差异很大。因此国际化第一期不直接追求全地区全量抓取，而是先建立可承载多地区、多原文语言和多群推送偏好的主干能力。

具体决策：

- 前台先提供 `综合 / 日本 / 中国香港 / 英国 / 法国 / 美国` 地区 tab，综合流第一期使用已发布文章倒序，不先做复杂推荐或地区打散。
- 新闻正文第一期只支持日文、英文和繁体中文；法国新闻只接英文来源，法语正文不进入人工审核和自动发布主链路。
- 术语库先从 UI 和服务语义上改为“原文术语 -> 简体中文译名”，并增加原文语言；现有 `source_ja / aliases_ja` 物理字段暂时保留兼容，避免在同一阶段做高风险重命名。
- QQ 自动推送从全局范围配置扩展为群级配置，因为不同 QQ 群可能只想看不同地区或不同范围的新闻。
- 外部数据库第一期正式实现 HKJC，因为香港官方数据集中、字段完整、中文用户价值高；美国 `Equibase`、英国 `Sporting Life + BHA`、法国 `France Galop` 先做小样本 spike，确认字段、入口和反爬/语言风险后再进入正式导入。

该决策最初只对应 OpenSpec change `expand-international-racing-coverage` 的规划边界；`2026-06-25` 已在独立 worktree 开始本地实现。当时后续部署要求完整测试、OpenSpec 校验和生产窗口确认；这是历史门禁记录，`2026-07-15` 后新变更以当前 Codex 工作流和任务专属发布授权为准。

review 返修后补充实现边界：HKJC 外部数据导入必须参考 netkeiba 的单来源互斥锁语义，已有运行中导入时拒绝并发写入；在真实网络抓取实现前，`--commit` 不允许写入占位 payload，必须通过 `--payload-file` 提供真实小样本；payload 超过 `max_races / max_horses` 时直接失败，不静默截断或部分写入；`max_horses` 的统计口径必须覆盖顶层 `horses`、赛事 `entries` 和 `results` 中实际会写入缓存或别名的唯一马匹，避免 entries/results 绕过批量上限；多语言术语后处理和自动化评分必须按文章 `source_language` 隔离，避免英语、繁中、日语术语在翻译、改写、重点马和赛事优先级判断中串用。

公开文章 ID 和来源去重键必须分离：公开详情页继续使用本地全局自增 `NewsArticle.id`，减少标题 slug 或上游 ID 变化带来的公开 URL 问题；但抓取入库仍需要稳定的 `source_article_id` 识别同一上游文章，否则重复抓取无法幂等更新。国际新闻源的 `source_article_id` 因此使用完整 URL 派生的低碰撞键，而不是只取 URL 最后一段 slug。

原始 HTML 和轻量 metadata 必须分离：整页 HTML 只保存到 `original_content_html`，`translation_metadata` 只保存来源语言、作者、抓取 URL、模型和 warning 等轻量元信息，避免同一份 HTML 在文本字段和 JSON 字段中重复保存。

排序型入口采用逐源确认策略：类似 netkeiba 访问量榜/注目榜的来源，只有公开 HTML 或公开 API 能稳定慢速抓取并能拿到真实文章时，才作为独立榜单源接入并记录原站排名。本轮只确认 `Sponichi 新闻ランキング` 可稳定抓取，因此先作为 `source_mode=access` 榜单源加入，默认关闭；该页面混有ボート等非赛马内容，适配器必须过滤非赛马文章并保留原站排名，不按过滤后的列表重新编号。`HKJC Racing News`、`SCMP Racing`、`BHA` 暂未发现等价公开热门新闻榜单；`Sporting Life` 有 `MOST READ RACING` 骨架容器但未确认稳定公开 API；`At The Races`、`Paulick Report` 当前 403，`BloodHorse` 有反机器人/空样本风险，均不作为生产自动榜单源启用。

上线前最终新闻源清单以真实 dry-run 可抓到两篇正文为准。第一版生产候选为：日本 `Sponichi latest/access`；中国香港 `HKJC Racing News`、`SCMP Racing`；英国 `Sporting Life Racing`、`Sky Sports Racing latest/access`，官方补充 `BHA official`；法国仅英文来源 `France Galop English News official`、`TDN France keyword`；美国 `TDN`、`Horse Racing Nation latest/access`。其中 `Sky Sports Racing Top Stories` 和 `Horse Racing Nation Trending` 作为弱热门/编辑排序信号，按页面顺序写入 rank；`At The Races`、`Paulick Report`、`BloodHorse` 保留为可单独探测候选，但不进入第一版默认清单或生产启用计划。

`TDN France keyword` 本质上仍来自 `thoroughbreddailynews.com`，与美国 `TDN` 普通源可能发现同一篇 URL。为避免同 URL 在两个 `source_site` 下重复入库，本轮采用简单 canonical 去重：文章主键使用 `TDN + source_article_id`，快照仍记录实际发现来源 `TDN France keyword`，且法国关键词来源会优先保留法国地区归类。这样既减少重复文章，也不丢失“这篇是法国相关稿”的审核和推送信号。

这样可以利用本地马名数据库降低普通词误报和真实马名漏报，同时避免把没有中文译名的外部数据污染正式术语库。

## 为什么自动发布门禁要区分 blocker / warning / info

自动化评分已经能识别高价值新闻，但近期候选池样本显示，很多高分文章不是因为内容不可发布而进入人工审核，而是被低确定性校验误伤：片假名普通词被识别成未收录马名，背景术语在摘要化稿件中被省略，数字一致性校验要求过严，长采访或引语较多也被当成硬失败。

因此后续自动发布门禁采用三层严重级别：

- `blocker`：明确不可自动发布的问题，例如缺标题、缺正文、正文过短、乱码、广告导航页、翻译失败或高度重复内容。
- `warning`：需要人工关注但初期不阻断自动发布的问题，例如疑似未收录马名、背景术语缺失、数字省略或引语较多。
- `info`：仅用于诊断和回看的问题，不影响发布分流，也不触发告警。

初期策略是 warning 不阻断自动发布，但高价值文章出现 warning 时必须邮件告警给工作人员。这样可以让自动化发布先跑起来，同时保留人工接管入口和质量抽检线索。

高价值来源只影响评分阶段放行，不绕过 blocker。首批高价值来源规划为 `netkeiba` 访问量榜和 `netkeiba` 注目数榜；如果这类文章缺正文、乱码或与已发布内容高度重复，仍然不得自动进入前台。

重复内容属于发布安全门禁：高度重复内容使用独立重复状态阻断自动发布，中等相似内容转人工审核，不归入初期不阻断的 warning。

短期默认发布内容源采用基准翻译稿，`AUTO_REWRITE_ENABLED=false` 且 `AUTO_PUBLISH_CONTENT_SOURCE=base_translation`。AI 改写字段和任务不删除，后续质量稳定后可通过配置恢复为 `rewrite` 内容源。

## 为什么原文选区快速加入术语库首版不自动重翻译

后台工作人员在候选详情页或编辑台发现新马名、赛事名、固定译法时，需要一个低摩擦入口把原文片段加入正式术语库，但“保存术语”和“让当前稿件重新应用术语”是两个风险不同的动作。

因此 `add-selection-term-quick-add` 首版只做文章上下文快速创建正式术语：

- 术语类型默认 `horse`，因为当前最常见问题是未知马名漏识别；但后台表单必须允许改类型，避免把普通词误写成马名。
- 快速入口复用正式术语校验，不绕过重复、类型、比赛等级和启用状态规则。
- 创建成功只写入 `TermEntry` 和操作日志，并记录来源文章 ID/标题；不改当前文章中文稿、基准翻译稿或改写稿。
- 不自动触发 `translate_article_task`，避免管理员只是补库时意外覆盖正在编辑的稿件。
- 编辑台页面已有外层文章编辑表单，快速术语按钮必须绑定到独立表单，避免浏览器把“加入术语库”误提交成“保存文章”。

后续如果要“新增术语后自动重新应用术语/重翻译”，应作为独立 change 处理，并显式设计覆盖字段、人工确认、失败提示和可回退路径。

## 为什么新增术语后的当前稿联动采用显式动作

`reapply-terms-after-quick-add` 继续沿用“保存术语”和“改当前稿件”分离的原则。新增术语成功后，工作人员可以通过一次性浮层选择“应用该术语到当前稿”；重新翻译保留为页面级能力，不属于术语成功浮层。系统不在保存术语后自动覆盖稿件。

这样设计的原因：

- 创建 `TermEntry` 是低风险补库动作；修改 `NewsArticle` 中文稿是内容编辑动作，应由工作人员明确触发。
- 编辑台里可能已有人工修改，默认覆盖会破坏工作人员刚完成的校对。
- 用户心智是“刚建一个新术语，就把这个术语应用到本文”，因此轻量动作只应用刚创建的指定术语，不重扫整个正式术语库。
- 指定术语应用会替换当前文章相关字段中的所有匹配位置，不限于创建术语时选中的原文片段，因为同一术语可能在文章中出现多次。
- 轻量术语应用不能等同于模型重新理解日文原文，因此需要和页面级“重新翻译”能力保持区分。
- 人工编辑字段由 `manually_edited_fields` 保护；默认指定术语应用只更新机器翻译字段、基准翻译稿和未标记人工编辑的发布稿字段。
- 快速创建成功后的应用入口只出现一次；刷新、离开页面或错过成功反馈后不补常驻入口，避免后台长期暴露容易误点的稿件修改按钮。
- 重翻译继续复用现有 `translate_article_task`，避免新增任务类型，也让最新正式术语库自然进入现有翻译提示和译文纠偏链路；若页面已有重新翻译按钮，不为术语成功浮层新增重翻译入口。

首版不做全站批量重翻译，不自动重新跑自动发布门禁，也不因指定术语应用或重翻译自动发布文章。后续如需要字段级 diff、强制覆盖人工字段或自动重跑门禁，应继续拆独立 change。

## 为什么英法美数据库源本轮仍保持 needs_more_spike

`start-hkjc-data-import-and-global-spikes` 对 `Equibase`、`Sporting Life + BHA`、`France Galop` 做了 2026-06-26 read-only spike。三地公开页面均能返回 `200`，且没有观察到明显访问阻断，但本轮只确认了浅层 HTML 入口和字段信号，没有确认稳定的结构化 API、完整单赛日/单马 URL 参数、分页/历史范围、PDF chart 解析成本或官方补字段路径。

因此本轮准入判断统一保持 `needs_more_spike`：

- 美国 `Equibase`：entries/results 有信号，但 horse profile 与 chart/PDF 仍需更具体小样本验证。
- 英国 `Sporting Life + BHA`：Sporting Life racecards/results/profile 信号较好，优先级最高；BHA 官方搜索、监管和补字段入口仍需单独复验。
- 法国 `France Galop`：英文站浅层页面可访问，但结构化赛程、报名、出马、赛果和马匹资料的稳定查询入口仍未确认；法语新闻正文仍不进入新闻审核、翻译、自动发布或 QQ 推送主链路。

该决策当时要求正式导入英法美数据库源前另起 OpenSpec change，先把每个地区的具体 URL 参数、字段映射、限速、失败恢复、正式表写入边界和回滚口径设计清楚；`2026-07-15` 起等价工作改为新建 `docs/changes/<slug>/` spec/design，不再调用旧 OpenSpec skills。

2026-06-26 `connect-real-global-racing-databases` 追加只读复核后，英法美仍不进入正式写库，但职责边界更清晰：

- 英国优先以 `Sporting Life` 作为正式导入主候选，因为 `racecards`、`fast-results` 和 horse profile 均可访问，且 results 页面暴露具体 racecard/profile 链接；`BHA` 作为官方补字段候选，负责复核 horses、fixtures、feed/search 等权威入口。
- 美国 `Equibase` 可继续作为唯一主候选推进 fixture spike；entries、chart/PDF index 和 horse profile 均可访问，但正式导入前必须先证明 chart/PDF 或 HTML chart 解析成本可控。
- 法国 `France Galop` 仍停留在官方页面浅层信号阶段；在定位稳定结构化查询参数前，不进入正式 parser/importer TDD。

## 为什么本轮全球赛马数据库目标关闭在“能力可用”

`2026-06-27` 用户将本轮目标从“完成最近 2 个月完整大量爬取”调整为“先保证所有地区的数据爬取能力真实可用”。因此本轮完成口径不再要求香港、英国、法国、美国都完成最近 60 天全量赛事与所有涉及马匹 profile 的真实爬取，也不要求生产 `--commit`。

本轮关闭目标的依据是：

- HKJC 已有生产真实 dry-run 批次证据，证明官方 HTML 入口、race batch、马匹详情补抓、低频请求和 dry-run 安全边界可用。
- UK / France / US 已有少量真实 proof，证明 Sporting Life、Geny、Horse Racing Nation 的赛事、赛果和马匹详情入口可访问并可解析。
- 四地 importer 均保留默认 dry-run、显式 `--allow-network`、请求上限、限速、精确批次和严格 `--commit` 门禁。
- proof-only 离线审计可以证明“能力可用”，同时完整 commit 候选审计会继续阻断缺少 plan、混合来源或马匹详情未补齐的输出。

后续若重新追求最近 60 天完整大量抓取，应作为新的执行窗口处理，并从最新 plan-only、逐批 dry-run、离线审计、备份、锁检查和用户显式确认重新开始。

## 为什么多地区新闻常态生产第一期使用配置化策略

日本以外的香港、英国、法国、美国新闻源已经接入，但真实运营仍需要先解决常态调度、人工审核边界、地区观测和 QQ 灰度，而不是马上新增一套地区策略后台模型。

因此第一期选择：

- 使用 `NEWS_SOURCE_POLL_*` 配置驱动通用 enabled 来源轮询，生产默认关闭。
- 继续保留 netkeiba / JRA 固定 Celery Beat，通用轮询默认排除这些固定调度来源，避免重复高频抓取。
- 使用 `MULTIREGION_AUTO_PUBLISH_*` settings 表达地区 / 来源 allowlist、每轮上限、每日上限和术语候选积压阈值，不新增 `RegionPublishPolicy` 模型。
- 非日本新闻默认转人工审核；只有显式配置允许的地区和来源才可能进入自动发布。
- QQ 推送继续以 `PushTarget.allowed_regions` 为群级边界；旧群空地区或非法地区配置仍只按日本兼容，不自动扩展到全球新闻。
- 外部赛马数据库 importer 继续只作为受控数据导入和马名识别底座，不进入新闻 Beat，不自动生成公开新闻、赛果页或 QQ 推送。

这样能先把“可常态运行但默认安全关闭”的闭环落地，后续若运营确实需要后台维护地区策略，再另起 change 设计模型、迁移和 UI。

## 为什么地区生产概览区分今日产能和当前积压

`operate-multiregion-news-production` 代码审查后明确：后台地区生产概览不能把历史累计发布数当成今日生产状态，否则工作人员会误判某地区今天是否真的在持续产出。

因此地区生产概览采用两类口径：

- `今日新增`、`自动发布`、`人工发布`、`公开` 表示服务器当前日期窗口内发生的生产结果。
- `待翻译`、`翻译失败`、`待审核` 表示当前仍需处理的积压队列。

这个口径能同时回答“今天有没有生产”和“现在还堵在哪里”，也避免页面默认依赖全量历史发布计数。

## 为什么正式术语地区字段为空表示全局通用

多地区新闻常态生产需要知道香港、英国、法国、美国各自的术语库准备程度，但现有正式术语长期作为全站词库使用，不能在迁移时强行归属到单一地区。

因此 `TermEntry.racing_region` 采用可选字段：

- 空值表示全局通用术语，适用于所有地区的审计统计。
- 设置地区值时，表示该术语主要用于对应地区，可在术语列表、表单、API、CSV 导入和多地区审计中按地区筛选。
- 本轮先不改变翻译/术语替换的匹配范围，避免因为加地区字段而破坏既有术语应用链路；如果后续要让翻译提示严格按地区匹配，应另起 change 设计回退和兼容规则。

## 为什么多地区新闻增量使用窗口账本而不是直接提高旧任务频率

`increase-multiregion-news-volume` 的核心目标不是单纯“多跑几次爬虫”，而是让抓取、发布和 QQ 推送都能回答同一类运营问题：这个 15 分钟或 5 分钟窗口有没有执行、为什么 0 篇、是否触发上限、能否安全重跑。

因此本轮采用 `ProductionWindow + WindowCandidateDecision + WindowTargetDecision + QuotaLedger`：

- 抓取窗口按来源建账，只有已启用、生产批准、未暂停且未 backoff 的来源进入 15 分钟调度。
- 发布窗口按地区建账，硬门禁、去重、评分、保底和配额都写入候选决策，0 发布不再只能从日志猜。
- QQ 窗口按地区建账，目标群跳过原因、群小时上限和全站小时上限都有持久化记录。
- 重要赛事只改变频率，不叠加单窗口上限；同地区重叠赛事合并为同一个 5 分钟模式。
- 新窗口 Beat 可以常驻，但生产总开关默认关闭；部署、迁移和重启不会自动切入高频生产。

旧 `auto_publish_batch_task` 在新发布窗口开启时直接跳过，避免旧任务和新窗口同时抢发文章。

抓取和 QQ 推送恢复时只执行最近一个缺失窗口，较早缺失窗口只写 `SKIPPED` 账本并标记合并到最新窗口。这样做是因为停机或 worker 堵塞后，连续补跑多个历史窗口会在真实时间内集中请求新闻源或集中发送 QQ 消息，容易触发来源站和 QQ 风控；运营仍能从窗口账本看到哪些窗口被合并跳过，而不会误以为它们正常生产。

已有 `SKIPPED` 或仍可重试的 `FAILED` QQ delivery 再次被窗口选中时，也要重新占用群小时和全站小时配额。原因是这类记录代表“又要尝试一次真实发送”，对 QQ 和用户群的打扰成本与新建 delivery 相同；只有 `PENDING / RETRYING / SENDING / SENT` 这类已经排队、正在处理或已成功的记录，才可以跳过配额，避免重复记账。

抓取窗口不能把“Celery 任务已投递”当成“抓取成功”。投递成功只说明任务进入队列，真实抓取可能仍在排队、运行或最终失败；如果此时窗口已记为成功，而来源 `last_crawl_at` 尚未更新，下一轮调度可能继续派发同一来源，反而提高抓取频率和封禁风险。因此抓取窗口由真实抓取任务完成后回写结果，来源存在 lease 未过期的运行中抓取窗口时直接跳过。

QQ 窗口同样不能把“delivery 已入队”当成“QQ 已成功发送”。OneBot 离线或登录态失效时，真实发送任务会失败，若窗口仍显示成功，运营会误判本轮 QQ 正常。因此 QQ 窗口在占用配额和创建发送任务前先做 OneBot 在线预检；离线时窗口直接记录失败原因，不消耗发送尝试，也不制造新的群消息任务。

## 为什么 ops 摘要通知先接入 UmaFans 测试群

`increase-multiregion-news-volume` 上线后，运营需要能感知窗口失败、0 发布原因和恢复情况；但生产暂时没有单独的内部运营邮箱或专用 QQ 群配置。

因此本次上线先将 `MULTIREGION_OPS_NOTIFICATION_QQ_GROUP_ID` 配置为现有 `UmaFans测试群(1026525240)`：

- 该群已经用于生产 QQ 推送验证，且已显式允许五地区新闻。
- ops 通知服务有独立开关和 30 分钟冷却，不占用用户新闻 QQ 推送配额。
- 本次只验证一次 `production_summary_task`，确认 `NotificationLog #13051` 发送成功，避免上线时额外刷屏。

后续如有正式运营群或邮件地址，应只调整 ops 通知目标，不需要改窗口调度代码。

## 为什么榜单二次命中只唤醒未发布文章而不直接发布

新闻从普通来源进入访问量榜、注目榜或国际榜单，说明它的价值可能被首次评分低估，但榜单本身不等于内容已经适合公开发布。

因此 `revive-ranked-news-for-publish` 的产品语义是“榜单唤醒”，而不是“榜单直发”：

- 榜单命中可以复活低分忽略、价值不足转人工、待翻译或翻译失败的未发布文章。
- 翻译失败或待翻译文章进入榜单后，应自动重试翻译。
- 已翻译文章进入榜单后，应重新评分，并让高价值来源信号参与自动发布判断。
- 发布仍必须经过翻译成功、自动评分、发布校验、发布窗口候选选择、配额和 QQ 限流。
- 人工拒绝、撤回、已发布、高度重复、正文缺失、核心术语缺失等硬门禁不被榜单绕过。

这样可以把榜单价值信号用在“重新认真处理”上，同时保留现有自动发布体系的可解释性和安全边界。

## 为什么榜单唤醒时间使用 `ranked_revived_at` 字段而不是只写 JSON

发布窗口需要稳定查询“最近 3 小时首次入库或最近 3 小时被榜单唤醒”的候选。如果只把唤醒时间写在 `decision_reason` JSON 里，SQLite 测试和 PostgreSQL 生产在 JSON 时间比较、索引和查询性能上都更容易分叉。

因此 `revive-ranked-news-for-publish` 采用双轨记录：

- `NewsArticle.ranked_revived_at` 是候选窗口查询和排序使用的 nullable/indexed 时间字段，历史文章默认 `NULL`，不做回填。
- `decision_reason.ranked_revival` 保存可读审计信息，包括唤醒时间、来源站点、来源模式、原 workflow/automation/translation 状态和执行动作。

这样既保证发布窗口查询简单可靠，也保留后台和窗口账本排查所需的上下文。
## 为什么术语种子数据准备先用 HKJC 体系和 WP Stud 且先审核不入库

当前多地区新闻源已经上线，但正式术语库和术语候选池仍主要是日文内容。为了补齐香港和国际赛马新闻的中文译名基础，第一批术语种子数据准备选择 HKJC 体系和 WP Stud：

- HKJC 体系包含较权威的中英文、繁中/英文对照，适合作为香港和国际赛马译名的主来源。
- WP Stud 属于高质量民间整理，适合作为别名、补充候选和译名冲突佐证，但不直接等同官方译名。
- 当 HKJC 和 WP Stud 都有译名时，以 HKJC 作为主译名，WP Stud 进入别名或备注；只有 WP Stud 时，作为需要人工审核的主译名候选。

第一版只输出 `seed_candidates.csv` 和 `seed_conflicts.csv`，不直接写入 `TermEntry`，原因是：

- 术语会影响翻译、自动评分、标签和发布校验，必须保持正式库可信。
- 种子候选需要人工审核冲突、繁简转换、地区归属和术语类型。
- `seed_candidates.csv` 严格兼容现有 `import_terms` 字段，便于复用已验证的 dry-run 与幂等导入流程。
- 所有中文目标译名统一输出简体中文；来源为繁体中文时，先做繁简转换并保留原始繁体证据。

`2026-07-03` plan-eng-review 后补充锁定：

- 第一版 HKJC 只做稳定 HTML/文本入口，`racecards` PDF、排位表 PDF 或网页排位表全量抽取延后。
- 实现前必须先做 HKJC 与 WP Stud source discovery，固定 URL、字段、fixture 和不可用入口。
- 默认输出目录为 `runtime/termbase_seed/<timestamp>/`，不得覆盖正式 `server/stable/data/terms_seed.csv`。
- 若新增繁简转换依赖，必须同步 `requirements.txt` 并测试；触网执行必须记录 timeout、非 2xx、解析失败和 incomplete 来源。

`2026-07-04` `prepare-hkjc-overseas-termbase-seeds` plan-eng-review 后补充锁定：

- HKJC overseas 精确 Race Card 输入使用可重复的 `--hkjc-overseas-race RaceDate=YYYY-MM-DD,Racecourse=<code>,RaceNo=<number>`，参数格式错误时必须拒绝执行，不能静默回退到自动发现。
- 渲染 fallback 只作为人工审核种子准备的可选能力；本变更默认不把 Playwright、浏览器二进制或图形系统依赖加入生产镜像。
- 若直接请求无法得到 Race Card 内容且没有可用渲染器或渲染后缓存，命令必须记录 `render_fallback_unavailable` 或等价原因，并把结果标记为 `incomplete=true`，不能把缺失当作空数据成功。

## 为什么术语最终导入不强行合并既有日文 alias 占用

HKJC 官方来源适合作为国际和香港赛马术语主译名，但生产库中已经存在大量日本日文主词和自动维护的日文 `TermAlias`。当 HKJC 日本马英文词条需要补日文 alias 时，如果对应日文名已被既有词条或 alias 占用，直接把 alias 迁移或复制到英文词条会产生两个风险：

- 中文目标一致时，强行合并会破坏既有日文词条的历史引用和审核痕迹。
- 中文目标不一致时，例如 `Raijin / ライジン` 或 `Scintillation / シンチレーション`，强行合并会把不同概念或地区译名折叠到同一个词条，影响翻译保护和术语应用。

因此 `2026-07-06/07` 最终术语导入采用保守策略：

- HKJC 英文词条保留官方主译名和地区。
- 只在无冲突时补充日文 alias。
- 已被既有日文主词或 alias 占用的日文名记录为 skipped，不自动迁移、不停用官方英文主词。
- 后续如果要合并个别概念，必须通过人工审核确认是同一匹马、同一中文目标和同一适用地区后，再单条处理。

## 为什么文章地区采用“主地区 + 关联地区”而不是覆盖原字段

`NewsArticle.racing_region` 已被发布窗口、配额、QQ、公开筛选和历史数据大量使用。直接把它改成多值字段会让配额归属和旧查询同时变复杂，也会影响已经发布文章的兼容性。

因此 `2026-07-10` 的多地区归属实现采用：

- `NewsArticle.racing_region` 继续代表主地区，决定发布窗口配额由哪个地区消耗。
- `NewsArticleRelatedRegion` 记录关联地区，用于地区 tab 可见性、QQ 群订阅匹配和运营汇总。
- 自动归属把赛事/赛场信号和国家、对象、机构上下文分开：只有明确赛事或赛场证据可进入“赛事地优先”，一般国家形容词只作为对象/上下文地区；来源 URL 和来源备注不参与内容归属，避免来源路径污染判断。
- 默认开启关联地区查询，但保留 `MULTIREGION_RELATED_REGION_QUERIES_ENABLED=false` 作为回退开关，可以临时让首页地区查询、公开卡片/详情地区展示、发布窗口、QQ 即时推送/窗口和地区审计全部退回只看主地区；关联地区数据不删除。
- 发布窗口可以看见关联地区候选，但未发布文章只由主地区窗口真正发布，避免同一文章被多个地区窗口重复发布。
- 后台归属锁定使用显式开关：勾选后后续自动归属和补跑不得覆盖运营最终判断；取消勾选后允许后续自动识别，普通正文编辑不会强制把开关重新打开。
- 文章编辑页把“新版字段存在但没有选择任何关联地区”解释为明确清空；只有完全没有新版字段哨兵的旧请求才保留已有关联地区，避免兼容逻辑阻止运营纠错。
- 对外展示必须以主地区为第一语义：列表使用“主地区 · 相关：…”紧凑格式，详情页和 QQ 分开显示主地区与关联地区；固定地区排序只用于关联地区内部排序。
- `2026-07-10` 审查决定：本轮不禁止后台将 `other` 保存为关联地区，保持现有兼容行为；服务层仍不把 `other` 当作有效地区集合成员。
- 重处理命令的 `--limit` 表示最多处理多少篇有效门禁候选，而不是最多扫描多少篇人工审核文章；审计输出必须说明扫描数和是否仍有更多候选。

这个设计让法国来源报道英国赛事、法国育马/拍卖相关海外赛事、爱尔兰内容暂归英国等场景可以进入多个地区池，同时保持配额和发布责任单一。

## 为什么 QQ 推送默认不放行所有内容类别

多地区新闻池扩大后，如果 QQ 按“地区命中即可推送”，普通 tips、营销投注建议、一般官方公告、拍卖/育马机构新闻会显著增加群消息量，且比网页发布更容易触发用户疲劳和平台限流。

因此本期 QQ 自动推送采用配置白名单：

- 默认允许 `news / preview / result_brief / feature` 和必要的旧兼容分类。
- 默认不允许 `tips / sales_breeding / official_notice / racecard_update` 自动群推。
- 无法可靠分类的 `other` 默认也不自动群推，必须由生产配置显式放行。
- QQ 群订阅匹配按“群允许地区”和“文章主地区 + 关联地区”求交集；同一文章对同一群仍由 `QQPushDelivery(article, target)` 唯一约束保证只发一次。

如后续运营确认某类内容适合群推，只需调整 `MULTIREGION_QQ_ALLOWED_CONTENT_CATEGORIES`，不需要改代码。

## 为什么人工审新闻补术语先写 pending 文件

逐篇检查已发布新闻时，单篇文章可能同时包含新增词条、既有词条缺跨语言 alias、以及其实已入库但已发布稿未回填的情况。如果每篇都立即写线上术语库，会增加频繁备份、dry-run、导入和回填的操作成本，也更容易把待确认译名与已确认译名混在同一次生产变更里。

因此 `2026-07-07` 起，人工审新闻补术语采用“审阅与生产写库分离”：

- 审新闻时先把待入库记录写入 `runtime/termbase_seed/manual-pending-terms.csv`，记录来源文章、参考源、动作类型、术语类型、原文语言、目标译名、待补 alias 和既有词条 ID。
- `action=create_term` 表示新增正式词条候选；`action=add_alias` 表示只给既有正式词条补跨语言 alias，不能重复建概念。
- 攒够一批后再统一执行生产备份、dry-run、正式导入和验收。
- 成功写入线上库的记录必须从 pending 文件清理或改状态，避免下一批重复导入。
- 已发布文章展示是否更新是另一件事：术语入库后仍需显式回填或重应用术语，不假设历史稿会自动变化。

## 为什么美国 2026 赛事详情先用 TOBA + HRN，而不强抓 Equibase chart

2026 美国分级赛基础范围以 TOBA 官方 American Graded Stakes 表为准；TOBA 表提供赛事、日期、赛场、等级、字段和部分 Equibase chart URL，适合定义“哪些比赛应进入赛事日历”。

赛后详情方面，Equibase chart HTML/PDF 入口当前返回 `Pardon Our Interruption` 防护页，不应尝试绕过风控或把防护页当作可解析来源。因此本轮详情导入采用：

- TOBA 官方表确定 2026 已完赛 Grade 1/2/3 范围，并优先使用 TOBA `chart_url` 中的 RaceNo 辅助匹配。
- Horse Racing Nation track-day 页面作为可访问公开来源，提供出走表和可见结果顺序。
- HRN 马名展示字段剥离 `(IRE)/(GB)/(SAF)` 等国籍后缀，原始写法保存在 `source_refs.horse_name_raw`。
- HRN 未公开 payout / also-rans 结果块的赛事，只导入出走表，不从 TOBA `winner` 字段猜完整名次。

这样能先让前台展示美国已完赛分级赛的出走表和可确认赛果，同时保留来源边界；后续若 Equibase 或赛场官方 chart 有稳定可访问入口，再用更权威来源覆盖对应 `results` 模块。

## 为什么 2026 赛事详情补齐允许显式映射和取消状态修正

2026 年五地区重赏赛事详情补齐时，部分基础赛程表与赛后结果页存在真实世界差异：赛事可能取消、延期、改场地，或者赞助名 / 标题发生变化。如果继续只靠日期、场地和标题模糊匹配，会有两类风险：

- 真正取消或废止的比赛被错误标记为“已完赛但缺赛果”，导致前台长期显示不完整。
- 法国、英国这类标题变化较多的赛事被漏配，或者在同一天多场同级赛之间误配。

因此本轮采用以下规则：

- 源站明确 `ABANDONED` 或 meeting abandoned 的赛事，改为 `cancelled`，不再追赛果；前台显示“取消”，且不显示赛果表。
- 改期 / 改场地赛事，以结果页实际出走日期和场地修正 `RaceEvent.local_date / racecourse`，同时在 `source_refs.manual_detail_import_audit` 留下证据摘要。
- 法国 ZEturf 对漏配的 8 场使用显式 R/C 映射，不再扩大模糊扫描；显式映射只用于已经通过页面标题核对的缺口场次。
- 美国 Equibase chart PDF 后续恢复可访问后，用于补齐 HRN 未公开完整名次的四场赛果；马名仍通过既有 HRN 出走表按马号对齐，避免 PDF 抽取中的缩写或排版误读。
- `RaceEventHistoryWinner` 本轮只从已确认赛果第一名补 2026 当前年度冠军，用于避免前台“近年冠军”空白；这不代表完整历届冠军已经完成。完整历届冠军仍需后续使用地区官方历史源补齐。

## 为什么 2026 历史冠军按地区分层导入

`RaceEventHistoryWinner` 会直接影响赛事详情页的“近年冠军”展示，因此历史冠军不能只靠模糊搜索或二手页面批量填充。本轮采用按地区可信源分层的方式：

- 日本 JRA：JRA 官方年度重赏一覧历史页覆盖 `2002-2026`，可稳定按赛事名和历史别名映射，因此导入完整年度范围。
- 日本 NAR：`keiba.go.jp` ダートグレード特设页只稳定公开“過去5年の競走成績”，因此导入近 5 年，并为已完赛 2026 场次补当前年度冠军。
- 香港：HKJC 官方 `getSeasonRaces` 接口和繁中单场赛果页能稳定覆盖当前 2025/26 马季对应赛事的 `2023-2026` 结果，因此导入 4 年近年冠军，并统一繁简转换。
- 美国：TOBA 官方年度分级赛表能稳定提供 `2023-2026` 的 Grade 1/2/3 winner 字段，因此导入近 4 年；赛事名变体只处理可解释的赞助前缀、`Invitational`、`S.` 尾缀和 `formerly` 前身，不使用模糊匹配直接写库。
- 英国、法国：官方结构化历史源仍未找到；`2026-07-07` 后续先用 Sporting Life previous-winners 链和 Wikipedia winners table 作为可追溯补充源扩展近年冠军，并保留 `source_refs`，未来找到 BHA / France Galop 官方结构化源时优先覆盖。

美国 `INDIAN SUMMER S.` 在 TOBA `2023-2026` 分级表中没有可靠历史前身，本轮保留为空，后续交由人工或新增官方来源确认后再补。

## 为什么英国 / 法国近年冠军先使用可追溯补充源

`2026-07-07` 继续补齐 2026 年重赏赛事近年冠军时，英国和法国没有找到能批量、稳定映射到现有 2026 底表的官方结构化历史冠军源：

- 英国 BHA 当前官方资料主要适合定义赛程、等级和基础赛事范围；未提供可直接批量解析并映射到 2026 每个赛事 series 的 previous winners 表。
- 法国 France Galop 官方结果入口当前重定向到认证页；官网 `Historique` 页面多为叙述文章，适合人工佐证，不适合作为统一结构化导入源。

为了让赛事详情页先具备可用的“近年冠军”展示，本轮采用以下补充策略：

- 英国使用 Sporting Life 结果页里的 `last_years_winners / previousWinners` 链。该来源已经用于英国出走表 / 赛果补齐，页面可缓存、可追溯；Flat 页面部分可回溯至 `2020`，Jump 页面多数只稳定提供当前年度冠军。
- 法国使用英文 Wikipedia race page 的 winners table，并合并已确认 2026 当前冠军。该来源明确标记为 `wikipedia_winners_table`，不视为 France Galop 官方数据。
- 所有补充来源都写入 `source_refs`；后续若找到 BHA / France Galop 官方结构化历史冠军源，应优先覆盖同一 `RaceEventHistoryWinner` 模块。
- 对无可靠匹配或无结构化表的赛事保留为空，不使用模糊搜索结果强行写库。

## 为什么赛事编排必须使用独立应到清单和运行级请求预算

实际候选不能作为覆盖率分母：抓取器整体失效时，候选文件可能为空；若审计只遍历候选，反而会把“什么都没抓到”误判为没有缺口。因此 `orchestrate-race-event-data-crawls` 在真实网络请求前只根据已校验 plan 与正式 `RaceEvent` 生成不可静默缩减的应到快照，并绑定 plan SHA-256。coverage 必须逐项对照应到清单，空候选、缺失目标、计划外候选和 series 不一致都阻止后续流程。

应到清单本身仍可能因为运营计划漏项而不完整，因此第一批真实抓取增加人工复核层：review CSV 展示赛事中英文名、年份、地区、slug 与预检状态，由用户确认范围；没有确认就不启动首批网络抓取。程序负责发现结构错误和底表缺失，人工负责判断产品范围是否少了或多了赛事，两层彼此独立。

限流必须按整个 run 计算，而不是给每个 adapter 各发一份额度。否则 adapter 越多，总请求量越可能按倍数放大。所有默认网络 adapter 因此共享持久化 `request_budget.json`，失败请求也占额度，resume 继续累计；预算证据损坏时 fail closed。prepare 另行生成 run 级 combined candidate，避免人工拼文件时漏掉某个地区或模块，并让 coverage、dry-run 与 apply-check 始终绑定同一候选身份。

同时，前台模板已调整为只有存在 `history_winners` 时才展示“近年冠军”区块，避免无数据赛事出现空标题。

## 为什么马匹详情页先走受审核的产品层，而不是直接暴露术语或外部表

`2026-07-07` 马匹详情页 MVP 提案已锁定为独立 `HorseProfile` 产品层，不能把 `TermEntry` 或 `ExternalHorse` 直接当成公开详情页。原因是术语库负责翻译保护和概念识别，外部表负责来源抓取证据；公开马匹页需要审核状态、展示名快照、简介、重点新闻、血统、参赛履历、关注关系和人工覆盖痕迹，这些都属于产品层能力。

因此第一版采用以下规则：

- P0 马默认由 active `TermEntry(term_type=horse, target_zh nonempty)` 生成 `HorseProfile` 草稿，但前台不可见；后台审核补充后手动发布，状态为 `draft -> ready -> published -> hidden`。
- 管理员允许强制发布空壳页；未发布或隐藏的马匹详情页在前台返回 `404`。
- 公开 URL 只使用唯一 ID：`/horses/<id>/`，不使用 slug，避免马名、多语言和改名带来的长期兼容问题。
- 展示字段优先使用 `HorseProfile` 快照，再回退到绑定的 `TermEntry`；术语变化不应自动改写已人工确认的马匹页展示。
- 文章马匹关系使用 `ArticleHorseLink`，前台和关注流只消费 `auto/manual`，不重新扫描正文；人工移除写入 `removed` 并保护不被自动重建。
- 关注功能对匿名普通用户开放，使用 `follower_token + cookie`；首页新增“我的关注”模块，展示关注马匹及可选子孙代的相关新闻。
- 马匹与比赛关系使用 `HorseRaceRecord` 记录参加过的比赛，并从获胜记录派生重点胜利；第一版前台先展示重点胜利和关联赛事，不做完整履历表。
- 血统展示必须尽力补齐完整二代，六个文本字段齐全才算补全成功；文本足够用于展示，只有能高可信绑定时才链接 `TermEntry` / `HorseProfile`。
- 外部资料补全覆盖所有地区 P0 马，必须先 dry-run，输出补全成功/失败占比和具体失败原因；高置信唯一匹配才写草稿字段，歧义或冲突进入 `HorseProfileDataCandidate` 供后台审核。
- 日本来源优先参考 `netkeiba` / `JBIS`，并把 GitHub `new-village/KeibaScraper` 作为可信参考来源或可选依赖候选；香港、英国、法国、美国分别以 HKJC、Sporting Life / Racing Post、Geny / France Galop、Horse Racing Nation / Equibase 为第一批候选来源。

## 为什么马匹关注 token 只在 cookie 明文存在，数据库只存 hash

马匹关注第一版不引入注册账号，但匿名 `follower_token` 仍然代表当前浏览器的关注身份。如果把明文 token 写进数据库、日志或 artifact，一旦后台导出、错误日志或调试文件泄露，别人就可能复用该 token 查看或修改关注列表。

因此 `horse-profile-page-mvp` 工程审查后锁定：

- 浏览器 cookie 保存签名随机 `follower_token`。
- cookie 使用 `HttpOnly`、`SameSite=Lax`，并随 HTTPS 安全 cookie 配置启用 `Secure`。
- 数据库 `HorseFollow` 只保存不可反推的 `token_hash`，不保存明文 token。
- 关注 POST 继续使用 Django CSRF；服务端从 cookie 解析 token，前端脚本不读取 token。
- 页面 HTML、URL、日志、补全 artifact 和运行报告都不得输出明文 token。

这样可以保留匿名关注的低门槛，同时降低数据库或运营 artifact 泄露后的横向风险。

## 为什么马匹外部补全 commit 必须读取已审核 artifact

马匹资料补全会写入 `HorseProfile`、`HorseProfileDataCandidate` 和 `HorseRaceRecord`，一旦把错误血统、错误马匹匹配或错误参赛记录写入产品层，会影响公开详情页、关注流和后续人工审核。外部来源又存在限流、同名马、地区差异和字段缺失，不能让 `--commit` 一边实时抓取一边直接写库。

因此本变更要求：

- dry-run 先输出 source evidence、before/after diff、补全状态、失败原因和未补全占比。
- commit 必须读取同一批次已审核 dry-run artifact，并要求显式确认参数。
- commit 只能写入 artifact 覆盖的马匹和字段，不得重新抓取外部来源后绕过审核直接写库。
- artifact 缺少 batch id、生成时间、source 摘要、diff 或审核确认标记时，命令必须拒绝写入。
- 回滚优先使用 commit artifact 中保存的 before 值；大范围异常再使用生产数据库备份。

这个约束和现有术语合并、文章术语回填的“先生成可审 diff，再 apply 已审核 artifact”保持一致。

## 为什么赛事历史抓取必须从已审批应到清单生成输入

赛事抓取器原先可以读取工作区共享 `events.csv`。即使 coverage 最后能发现多抓或漏抓，让真实网络请求先访问计划外赛事仍会浪费请求额度并增加被来源限流的风险。因此 `orchestrate-race-event-data-crawls` 锁定以下门禁：

- run 创建时从 plan 与正式 `RaceEvent` 生成不可静默缩减的 `expected_targets.json`。
- 运营审批固定的 `review/expected_targets_approval.json`；批准状态、批准人、批准时间和应到文件 SHA-256 缺一不可。
- 网络 prepare 从已审批应到清单按地区生成 `input/events_<region>.csv`，adapter 不再以共享旧 CSV 决定范围。
- coverage 只接受显式 `approved` mapping；空模块、缺来源 URL 都视为 blocker。
- apply-check 再次对账应到 SHA-256，完整读取 gzip 备份，并要求每个实际写入范围都有完整批准元数据。

这样即使赛事抓取工具、应到清单或人工文件任一环节损坏，系统也会停止，而不是以不完整数据继续写库。

## Code review 的协作边界

- 纯技术问题，包括正确性、安全性、数据一致性、测试、性能和可维护性，由 Codex 在审查后自行判断并直接修复，不再逐条要求用户批准。
- 会改变产品能力、运营口径、用户交互、公开展示或业务规则的问题，仍需先向用户说明并确认。

## 2026-07-11 赛事抓取第六轮审查取舍

- 修复批量 importer 的部分提交风险：候选保存和正式 apply 必须整批事务化，任一后续模块失败时全部回滚。
- 修复审批后抓取输入漂移：完整 adapter 输入进入应到快照，当前 `RaceEvent` 与快照不一致时必须重新生成和审批。
- 修复混合来源批准拼接：策略 SHA 只认完整 `approved` confirmation。
- 暂不强制所有 importer apply 提供 `--expected-sha256`，保留当前单场人工修复兼容入口；规范流程仍使用 apply-check 生成的带哈希命令。
- 暂不增加请求预算文件锁或 run 并发锁，继续按当前手动、单进程分批方式运行。

## 为什么多地区新闻归属迁移上线后仍保持关闭

`2026-07-11` 生产五地区真实文章 dry-run 表明，当前实体信号可能把来源主地区文章改到另一地区，并可能一次生成三至四个关联地区。例如法国样本 `article_id=7031` 被推断为英国主地区，日本样本也出现改为中国香港主地区。该结果会改变公开地区 tab、发布窗口配额和 QQ 群匹配，属于产品归属口径问题，不能作为纯技术修复自动启用。

因此决定：

- 迁移 `stable.0023_multiregion_news_attribution` 和代码保留在线，避免重复部署与迁移风险。
- `MULTIREGION_ATTRIBUTION_ENABLED=false`、`MULTIREGION_RELATED_REGION_QUERIES_ENABLED=false`，旧行为继续生效。
- 不执行 `reprocess_multiregion_attribution_gates --commit`，不向 `NewsArticleRelatedRegion` 写入本批结果。
- 先由产品侧确认主地区优先级、关联地区最大范围和弱实体信号是否允许改变主地区，再修改规则并重新执行五地区 dry-run。
- 赛事信息编排工具不依赖这两个开关，可独立上线和开始后续应到清单验收。
## 为什么赛事页保留原始人马名并在展示时关联术语库

赛事抓取数据需要保留来源原文，便于去重、追溯、重新匹配和处理术语库后续修订；若把中文译名直接覆盖进赛事明细，术语更新后会产生历史脏数据，也会丢失原始证据。因此赛事页采用展示时批量解析：马名和骑师名精确命中 active 正式术语主原文或别名时显示 `target_zh`，冲突时优先赛事同地区，其次全局，再次其他地区；未命中时原样展示，不自动编造译名。

出马表与赛果是两个不同视图。赛果继续按完赛名次排列；出马表当前五地区按马号自然升序排列，马号缺失时回退闸位，最后才使用来源行序。地区排序映射显式保留，后续若某地区以闸位为主，只调整该地区规则，不改写已抓取数据。
## 五地区分级赛事追溯至 1984 年的范围与完成口径

历史赛事目标采用以下锁定口径：

- 覆盖日本 JRA/NAR、中国香港、英国、法国和美国在 1984 年以来全部 graded/pattern 系列，包含历史停办和降级退出系列，不包含普通赛、让赛和未胜利赛。
- 入选系列从 `max(1984, 创办年)` 保存完整系列史，包含升格前和降级后连续届次，各年使用真实等级。
- 已排期后取消创建 cancelled 年度赛事；当年未举办只记 not-held 证据，不创建虚假 `RaceEvent`。
- 可信完整赛果可派生 runners 并标记来源；年度正式赛果是冠军主事实，缺完整赛果时才使用冠军补位，历届冠军按稳定系列动态汇总。
- 字段冲突按官方当年结果、官方档案/年鉴、高可信专业库、参考来源排序；低级来源只补空，同级或高级冲突人工审核。
- 完整目标可先按批准 scope 写入，暂时不可用和身份待审持续挂账；永久不可得必须双来源证据和人工批准。
- 最终同时报告 accounted rate 和 data complete rate；闭环要求全部年度目标有明确结论，不把永久缺档伪装成数据完整。
- 历史数据不自动创建 HorseProfile、不自动音译正式术语；前台不新增系列页，赛事日历增加年份和名称搜索。
- 达标 historical publication scope 可公开年度赛事并进入分片 sitemap；资料不足、冲突和 not-held 不进入索引。

工程实现使用稳定 `RaceSeries`、年度总账 `HistoricalRaceEventTarget` 和真实年度 `RaceEvent` 三层身份。年度总账拆分客观 expectation 与处理 resolution 状态；逐年分级目录发现入选系列，再通过 lineage/timeline 补足前分级、后降级、取消和缺届。生产网络和 commit 默认关闭，所有批量行为继续绑定 artifact、请求/磁盘预算、备份、原子写入和写后核验。

# 2026-07-12 历史赛事生产执行授权

- `backfill-race-events-to-1984` 准备任务全部完成、测试通过且最终 code review 无 actionable finding 后，Codex 可自主执行生产备份、部署、历史目录抓取、详情抓取、dry-run、分批落库和写后核验，无需逐批再次取得用户确认。
- 自主执行不取消既有安全门禁：总账和批次 artifact 必须锁定 SHA，网络和写入必须受请求/cache/磁盘预算、coverage、备份、原子 scope 和写后计数约束；失败批次停止扩大并保留 gap ledger。
- 生产抓取/写入期间可临时开启 `HISTORICAL_RACE_BACKFILL_ENABLED` 与 `HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK`，但本轮结束时必须恢复关闭。历史年度赛事默认保持 draft，最终线上展示开关暂不开放。

## 2026-07-12 现有年度重复赛事的主记录选择

- 同一年、同一地区的两条记录经官方名称、日期、场地和来源证据确认属于同一届赛事时，不得为了通过系列唯一约束而创建两个伪系列。
- 合并时优先保留已经长期公开、可读且被用户使用的主 slug；后导入记录的官方字段、出马表、赛果、历届冠军、候选和别名迁入主记录，重复子记录在事务断言和备份后删除。
- 本次英国 Gold Cup 保留 `/races/2026/gold-cup/`，BHA 自动 slug 作为搜索别名留存；该规则不授权批量模糊合并，名称相似但实际不同的赛事仍须显式区分。

## 2026-07-12 以 TJCIS 年鉴作为 1998–2026 跨地区目录骨架

- 1998–2026 五地区年度 graded/group 目录先以 TJCIS 官方 International Cataloguing Standards 当年整本年鉴建立共同骨架，再由地区主办方/监管机构正式结果和 timeline 证据补充日期、结果、改名、迁场与前后等级。
- 年鉴是目录权威来源，不凌驾于当年主办方正式赛果；同级冲突继续阻断。Listed/LR 不直接进入本目标 catalog，障碍赛按独立 discipline 解析。
- 该决定不缩短历史深度。1984–1997 必须使用相同产品完成口径继续补源；旧年代未补齐前不得批准完整总账或把部分账本描述为全量完成。
## 2026-07-12 先完成并上线 1998–当前独立年代 scope

- 用户最新执行顺序明确拆为两个完整年代 scope：先补齐并审核 `1998–当前` 总账，再按该总账抓取和写入全部赛事详情，验收后打开该 scope 的正式展示；随后继续调研 `1984–1997` 完整目录。
- 该决定覆盖此前“1984–1997 未齐前不得批准任何总账或详情批次”的门禁，但不降低最终历史深度。`1998–当前` 只有在自身逐年五地区分母完整、来源冲突和身份冲突审核完成、manifest 独立批准后才能写入或公开。
- `1984–1997` 仍是同一长期目标的必做 scope，不得因 1998–当前上线而标记 OpenSpec change 全部完成或归档。
- 两个年代 scope 必须分别保存 source cache、manifest、approval、请求预算、备份和写后核验；公开开关只能在 1998–当前数据全部验收通过后开启。
## 为什么 P0 马范围扩展到五大地区重点赛事参赛马

`horse-profile-page-mvp` 第一版把 P0 马定义为 active 且有中文译名的 horse `TermEntry`，适合先批量生成后台草稿，但会漏掉没有稳定中文译名、却已经参加五大地区重点赛事并具备资料补全价值的马。P0 马资料补全专项的目标不是只补已有中文译名术语，而是为用户提供重点马匹资料入口。

因此 `complete-p0-horse-profile-data` 规划将 P0 马定义扩展为：

- 当前范围：active 且有中文译名的 horse `TermEntry`。
- 重点赛事参赛马：日本、中国香港、英国、法国、美国全部历史与未来已知 `G1/G2/G3/J-G1/J-G2/J-G3/JpnⅠ/JpnⅡ/JpnⅢ` 赛事参赛马。

重点赛事参赛马必须能追溯到结构化赛事、出赛表或赛果证据，不能仅因外部马名搜索命中就进入 P0。Listed、Open、`LOCAL_GRADE` 和其它等级暂不纳入本次 P0 扩容，后续如需扩大范围另起 change。

## 为什么暂无中文译名的马名术语仍可 active

新版 P0 范围会自然引入一批暂时没有合适中文译名的海外马。如果继续要求 horse `TermEntry.target_zh` 必填，系统会被迫在资料补全前先造一个不稳定中文译名，或者让这类马完全绕开术语体系。前者会污染翻译和前台展示，后者会削弱马名识别、翻译保护、文章关联和 P0 同步。

因此后续实现应升级术语库语义：

- `is_active=True` 表示可信实体可被识别，不再等同于“可中文替换”。
- 暂无中文译名的 horse term 可保持 active，但应有 `translation_status=pending` 或等价状态。
- 翻译、改写和发布校验命中这类马名时，必须保留原文，不得音译、意译或替换为空值。
- 只有 `target_zh` 非空或 `translation_status=translated` 的术语才参与中文替换和中文译名保留校验。

这样无译名马可以进入资料补全、ready 和人工发布流程，前台用外文原名展示并提示“中文名待补”；正式中文译名确认后，再自然升级为普通正式术语。

## 为什么马匹地区不属于身份唯一键

马匹会跨地区参加重点赛事，日本马可以参加美国、香港、英国或法国赛事。`HorseProfile.racing_region` 表达马匹自身归属，赛事地区表达一条参赛证据发生在哪里，两者不是同一个维度。因此 P0 同步不得使用“马名 + 地区”直接创建新身份，也不得因海外参赛覆盖马匹自身地区。

身份判定采用两层证据。第一层是来源命名空间内的 external horse ID，它只证明该来源中的身份；同一来源不同 ID 的同名马可以建立独立资料，不同来源的 ID 则不能仅因相同或不同就自动判断为同一匹或不同匹。第二层用于跨来源归并数据库已有马，必须完整且唯一命中“马名 + 父名 + 母名 + 出生年份”。马名和父母名通过正式术语主名、中文译名和多语言 `TermAlias` 归一，因此 `Forever Young` 与 `青春永驻` 可参与同一身份判断。

`racing_region` 不参与身份唯一性，只表达马匹自身地区；重点赛事地区只写入对应 `HorseP0Source.racing_region`。同一赛事参赛者先按马号、再按来源身份分组，不能在身份分析前按同名折叠。跨来源四元组字段不全、命中多匹或只有同名证据时，系统必须写入专用 `HorseIdentityConflict`、不写主表；该记录允许尚无 profile，保存多个候选术语/资料页、原始身份字段、来源证据和人工解决状态，并每天汇总 pending 冲突通知管理员。全量来源对账遇到仍存在但身份待处理或 URL 暂缺的输入时，不得把既有来源误撤销。暂无中文译名 horse term 的原文保护跨地区生效；同一原名命中多个 active horse term 时也必须保留原文，不能任选一个中文译名替换。

同场参赛身份必须持久化为 `HorseP0Source.participant_key`，不能在内存分组后退化回“赛事 + 马名”查询。该键表达某场赛事中的参赛者，不是马匹全局身份：优先使用规范化马号，其次使用来源身份集合摘要，只有赛事内马名唯一时才使用规范化马名。runner/result 采用马号、来源 identity、赛事内唯一马名的分阶段配对；无法唯一配对时保留独立证据并进入歧义处理。同一个 `participant_key` 最多有一条 active 重点赛事来源，身份纠正时撤销旧绑定并新增 active 绑定，以保留历史审计。

人工审核来源不属于某场赛事参赛身份，不能复用空 `race_event + participant_key` 查找。每匹马最多保留一条 active 人工 P0 来源，应用已审核 artifact 时按 `profile + source_type=manual` 独立 upsert，并由数据库条件唯一约束兜底；审核后一匹马不得撤销前一匹马的人工来源。

P0 补全队列的资料缺口优先级必须显式建模，不能直接按 `completeness_status` 字符串排序。顺序为：空资料、仅基础资料、部分血统、完整二代血统、完整资料但需刷新、完整且无需刷新；需刷新包含在役履历过期或缺同步日期、退役同步日期早于最新赛绩，以及生涯状态未知。同一缺口等级内再按人工标记、pending/conflict 候选、近 30 天公开新闻、重点赛事证据、非空外部身份和术语优先级排序。空 `horse_identity_keys` 不得算作外部匹配信号。

`participant_key` 允许随证据增强从 identity 键升级为 number 键，但升级不能新建第二条 active 来源。同步必须同时使用现有键、`race_runner`、`race_result` 和来源 identity 查找旧绑定：同一资料页原地迁移键，另一资料页则撤销旧绑定后新建。runner/result 两边都有马号且不同属于硬冲突，不能再降级按 external ID 或同名合并，必须写 `HorseIdentityConflict` 保存两边马号和原始记录。

马号硬冲突检查必须覆盖整个赛事 participant 集合，而不只覆盖 runner-result 配对。同一来源 identity 关联两条 runner、两条 result 或混合记录时，只要出现多个非空马号，就汇总成一条 pending `HorseIdentityConflict`，保存全部 runner/result ID 与马号，并阻止该冲突组写入 active P0 来源。

马号冲突不能仅凭 `resolved_profile` 恢复写入，还必须填写 `resolved_horse_number`，且该值必须属于 evidence 中的候选马号。共享任一来源身份键的参赛记录必须先形成完整连通组，再生成一条包含全部成员和马号的冲突，不能按身份键顺序覆盖证据。同步只采用最终马号对应的 runner/result；只有所选成员自身或赛事具备来源 URL 时才允许 resolved。若所选成员无法在本轮证据中定位、URL 后续消失或数据绕过后台校验，下一次同步统一恢复为 pending、清空无效解决选择并记录失败原因，使其继续进入管理员通知。冲突 evidence 保存所有成员和 URL，即使全部无 URL也必须落库；URL 等可补充证据不参与 fingerprint，避免证据完善后复制一条新冲突。

## 为什么 P0 commit 必须逐行逐模块审核

artifact 顶层“已审核”只能表示整份文件进入 commit 阶段，不能替代每匹马、每个模块的人工结论。正式写入必须同时满足：有效审核人、行级 `reviewed=true`、模块级 `approved`、最低置信度、无冲突/失败标记和来源 URL 规则。基础资料、血统、赛事履历、主胜鞍四个必需模块都留下 applied 审计后，系统才允许标记 `complete_profile_full`。

旧 `HorseRaceRecord` 在迁移时优先从 `raw_payload`、其次从 `source_refs` 读取 external race/result ID，并为唯一记录回填同一套幂等键；两处都没有外部身份时才使用自然键，已有重复组保持空键等待人工处理。来源命名空间从 `record.source_name` 或证据中的 `source/source_name/provider/adapter` 推导，用于身份键时统一去空格和 `casefold()`；external ID 统一字符串化并去首尾空格，避免来源大小写或证据空格变化生成不同键。运行期接管空键旧记录时也必须先扫描 `raw_payload/source_refs` external identity：唯一命中时接管并补齐来源名，多条命中时在 importer 与后台编辑路径都停止写入并报告歧义，完全无外部身份命中时才退回比赛名、日期、马场和 URL 等自然字段，避免事实字段修正后生成第三条重复记录。新增、修正、未变化必须分别统计，修正必须保留 before/after。P0 普通同步采用追加式更新，不执行撤销；只有操作者显式选择全地区完整对账时，本轮不再成立的受管来源才标记 `revoked`，并保留撤销时间和原因，不删除历史来源。

所有赛绩写入口必须复用共享的 `stable.services.horse_race_records.upsert_race_record()`，包括 P0 artifact、后台人工候选和后续批量导入；不得另行直接 `create()`。共享服务统一校验比赛名、来源名和来源 URL，生成幂等键，接管唯一旧记录，并在多个旧记录同时命中时停止写入。这样“人工审核”和“批量补全”不会因为走不同代码路径而生成重复赛绩。

后台手工新增和编辑也属于上述统一入口。编辑已有赛绩时需要指定原记录，按编辑后自然键重新生成幂等键；若新键或旧自然键已经属于另一记录，应拒绝保存而不是合并或覆盖。当前不额外实现并发请求争用时的自动重查，数据库唯一约束仍作为最终防重复边界。

人工编辑既有 importer 赛绩不得覆盖 `source_refs/raw_payload`；这些字段保存原始来源证据，不是表单当前值的镜像。手工修改的 before/after 应进入 `OperationLog`，只有从后台新建的赛绩才初始化 `entry_method=manual_console`。

若既有赛绩的 `raw_payload/source_refs` 含 external race/result ID，人工编辑普通事实字段时幂等键必须继续使用该 external ID 和原 source namespace，不得退化为比赛名/日期自然键。只有显式更正外部身份的专门操作才可改变外部身份键。

在役马履历新鲜度只使用一个公共截止日期函数，读取 `HORSE_PROFILE_ACTIVE_RECORD_FRESHNESS_DAYS`。完整度判断、后台待刷新筛选、后续队列和定时任务不得各自硬编码“早于今天”。

## 2026-07-13 法国新鲜度与归属能力采用先部署、后资格灰度

- 允许先将 `badc10e0` 和 `stable.0029` 部署到生产，但归属模式保持 `off`，相关地区查询、翻译自动重试和失败邮件保持关闭。
- 归属能力必须先完成达到 `150/10/20` 首发覆盖的有效 Gold Set，并通过既定准确率、扩散率、锁定覆盖与性能门槛；单审来源可以使用但不得伪造第二审核人，多人冲突必须裁决。不得以代码已部署替代生产资格。
- 失败邮件固定发往 `754652181@qq.com`，但只有在生产 SMTP 参数配置完成并通过测试发送后才允许开启；无 SMTP 时保持关闭并依赖现有后台/运行日志感知失败。
- 本次验收以 HTTP 运行态为准。HTTPS server 块仍未启用，证书接入继续作为独立运维事项，不与本 change 的代码部署混为一谈。
## 2026-07-13 历史第一批允许完整子 scope 独立写入

- 第一批 45 场不要求为了等待某一地区来源而冻结其他已完整目标；满足当前 target/inventory SHA、审核直链、source cache identity、完整 runners/results 和 production dry-run 的 27 场可作为完整子 scope 正式写入。
- 法国 9 场详情缺口、英国 2000 年 3 场日期缺口和美国 2000/2012 年 6 场日期缺口必须继续留在总账，分别保持 `ready` 或 `pending`，不得用空候选、仅冠军信息或推测日期标记完成。
- 本次写入只改变结构化数据状态，不构成 publication scope 批准。36 个已建赛事继续保持 draft，两个历史开关保持关闭；只有补齐五地区样本并完成前台、搜索、历届冠军、可见性和 sitemap 验收后，才讨论扩大公开范围。

## 2026-07-13 IrishRacing 作为英法历史详情备用源

- 当 Racing Post / France Galop / PMU 等主源只提供沿革证据或当前受反爬限制时，允许 IrishRacing 作为较低权威的正式详情备用源。主源链接与交叉核验证据仍保留，不将备用源提升为地区第一权威。
- IrishRacing 结果页只证明 actual runners 与 results，不冒充 declared runners/racecard。马号和闸位分字段保存，出马表按马号排序；并列官方名次保存在 `official_finish_position`。
- 工程上拆为 `uk_irishracing` 和 `france_irishracing`，即使 host 相同也不允许跨地区候选或 artifact apply。HTTP 200 但显示 `Information Not Available` 的页面必须视为抓取失败。

## 2026-07-13 近年日美来源与字段口径

- 2025 美国平地分级赛由 TOBA 年表定位，直接结果使用可缓存的 Equibase Yearbook 单场页；旧 `tvg` 静态整日 PDF 规则只用于已验证旧年份。
- TJCIS 裸距离按地区显式补单位：日本、香港、法国为米，美国平地为 furlong；美国障碍和英国保存来源中的 mile/furlong/yard 组合。
- Equibase 退赛程序号 `SCR` 内部保存为稳定 `SCR-n`；官方并列名次写入 `official_finish_position`，唯一 `finish_position` 仅作稳定存储顺序。
- 年度权威表赛事名唯一且有工程期移师证据时，允许以当年实际场地定位结果，不因此拆分稳定赛事系列。

## 为什么迁移前进后禁止部署旧应用底座

- 历史赛事能力可以在独立分支长期迭代，但每次生产构建前必须先合入最新 `origin/main`，检查当前生产已应用迁移及所有新增非空字段的创建路径，并运行历史链路与新闻主链路组合回归。
- 数据库已应用 `stable.0027–0029` 后，缺少对应模型/服务写入逻辑的旧镜像即使 healthz 正常，也可能让新文章在数据库约束处失败；因此 healthz 不能替代真实新增 smoke 或近期任务错误日志检查。
- 生产发生 schema/application 不兼容时，优先停止新的 one-off 写入、构建和重启，由单一生产协调线程选择短时回滚或兼容镜像替换。历史批次不得抢占新闻主链路恢复。
- 生产兼容镜像已由单一协调线程完成切换；历史回填线程后续只能在既有镜像上执行已批准的数据操作，不得自行重建、retag 或重启生产服务。任何后续代码部署必须先合入最新 main 并重新交付镜像 ID。
- 历史详情来源必须在整个批次内一对一绑定目标；同一详情 URL 即使仅 fragment 不同也视为同一来源页面，发现复用必须阻断，不得用同日同场相似赛事填充。
- 生产当前运行的组合镜像在历史源码完整进入 Git 前属于临时可运行状态；法港英 150 场日期 apply 完成后暂停详情写入，优先提交源码、推送分支、合入最新 main，并从可复现 Git tree 重建 AMD64 镜像。

## 2026-07-13 生产镜像必须同时绑定最新主线和构建上下文

- 服务器 Git HEAD 最新不代表运行容器最新。每次生产切换必须同时核对容器 image ID、镜像内最新迁移、Django settings 和关键管理命令；任一项不一致即停止切换。
- 多个 worktree 并行开发时，后部署任务必须先合入最新 `origin/main` 并跑组合回归。禁止使用旧分支构建后直接覆盖共享 `umanewsbot:prod`，即使该镜像只想修复另一个模块。
- 暂未全部提交的生产镜像必须至少记录内容 commit、构建上下文树 SHA、完整 image ID 和回滚 tag，并尽快将真实生产源码提交推送。它只能作为短期过渡，不能成为长期部署方式。
- 切换共享 worker 前先暂停 beat，等待 active/reserved/one-off 清空；切换完成后立即恢复 beat，并验证自然抓取、数据库非空约束、五地区页面和错误日志。

## 2026-07-14 新闻实体采用文章级统一仲裁与显式重处理

- 同一篇文章的翻译术语、马名标签、发布校验和自动马匹关联必须消费同一份带跨度、实体类型、证据与冲突结果的文章级解析，禁止各链路独立扫描全术语库后得到互相矛盾的实体。
- 英文人物全名及篇内唯一姓氏回指优先于内部马名候选；普通词和高歧义单词型马名只有在强马名语境中才接受。日文连续完整未知马名先整体占位，接受术语只在占位前应用，恢复后不得再次全库扫描而把父马、冠名或普通短词嵌入完整名。
- 历史误识别只通过显式文章 ID 的管理命令修复，默认 dry-run、逐篇事务和操作日志；提交时可清理本轮机器 provenance 与明确目标旧 `AUTO/CANDIDATE`，但必须保留人工标签、`MANUAL/REMOVED` 关联、公开状态/时间及 QQ 幂等。自然流入规则修复不授权全库批量回填。
## 为什么历史赛事基础字段校正必须独立于详情候选

年度清单和日期来源可能只提供裸数字或地区特有的距离写法，直接物化后不能假设数值单位相同。法国、香港的距离证据通常以米为单位，英国则可能使用 mile、furlong 和 yard；任何统一猜测都会把正确数字写成错误语义。

因此基础字段校正采用独立、哈希锁定的 JSONL artifact：每个目标绑定当前 target/inventory 身份和逐来源快照，dry-run 展示 before/after，apply 保护人工锁并整批原子写入。字段变化后 target SHA 必须改变，已有详情候选必须重新导出、重新打包和重新 dry-run，禁止直接复用旧审批结果。场地、surface、等级、日期和名称的权威修正也复用同一门禁，不允许生产 shell 手改。

## 2026-07-13 多地区归属 Gold Set 原始采样与双审口径（已部分修订）

- Gold Set 候选按五个当前文章地区各 `50` 篇分层抽样，并在来源内轮转，避免高产来源独占样本；抽样前按归属输入 SHA 全局去重，同一正文不能重复计入分母。
- 困难样本选择不得调用当前待测归属算法，避免考生参与出题造成选择偏差。只使用独立的宽地区关键词判断是否疑似同时涉及多个地区；正式跨地区数量只认人工确认标签，2026-07-14 起首发最低为 `20`，后续继续扩充。
- 原计划由 `reviewer_a` 与 `reviewer_b` 独立完成；2026-07-14 起允许只有 reviewer A 的单审集进入资格判断，但不得伪造 reviewer B。若后续存在多人审核，不一致项必须由裁决人给出最终主地区、相关地区和理由。
- 真实正文只保存在被 Git 忽略的审核包；仓库中的正式 Gold Labels 只保留 article ID、source URL、输入 SHA、期望主/相关地区、审核角色、理由和裁决状态。正文、URL、哈希或快照发生漂移时必须拒绝合并或从分母排除。
- 生成候选不等于完成 Gold Set。只有有效分母、五地区数量、跨地区数量和零多人未决冲突均达标，且评估器质量门槛通过后，才允许进入生产 shadow。

## 2026-07-13 单审部分样本原限制（已由 2026-07-14 决策取代）

- 当现实条件无法取得第二位审核人，或审核人明确只抽样部分地区时，允许使用显式 `provisional_single_review` 模式保留已完成工作：有主地区的行进入校准标签，明确 `exclude` 保留，全空行按未选中忽略。
- 该模式不得伪造第二审核角色、裁决状态或来源回退答案；`allow_source_fallback` 未填写时保持未知。输入中的别名和自由文本先保留 raw 值，再输出可审计的规范值。
- 当日“单审无条件 no-go”的限制已取消；`provisional_single_review` 现在只记录审核来源。单审集达到 `150/10/20` 覆盖和既定质量/性能门槛后可进入 shadow，多人审核冲突仍须裁决。
- 覆盖门槛的降低只用于允许首轮 Shadow，不降低主地区准确率、相关地区 precision、无依据变化、过度扩散、锁定覆盖和性能门槛，也不允许跳过 shadow 直接 enforce。

## 2026-07-14 多地区归属 V3 校准决策

- 现有 `159` 条单审标签是本轮固定首发 Gold Set；不伪造 reviewer B、不要求用户继续补标。2026-07-14 复评确认其达到 `150/10/20` 覆盖和全部质量门槛，可进入 shadow；Gold Set 后续仍按新增来源、规则变化、shadow 误判和运营争议持续增长。
- 主地区采用“标题叙事中心优先，但必须有强证据”的分层规则：明确队伍/从业者/核心对象行动或成果可高于赛事；否则明确赛事/赛场优先。普通词马名、单词型歧义赛事、正文历史履历和来源 URL 不得单独改变主地区。
- `other` 是合法的归属与审计值，可表达澳洲、爱尔兰、沙特、迪拜等非五地区证据；它不是新的生产地区，不产生独立发布窗口、配额或 QQ 路由。
- Gold 标签要求的相关地区若只来自对象多年历史参赛地，而文章标题/导语没有可靠证据，自动规则不补齐。此取舍优先保证 precision 和不误扩散，相关 recall 的剩余缺口记录为单审标签/数据证据边界。
- 批量术语匹配采用请求内候选索引，最终仍复用原边界匹配器；不引入跨 worker 常驻缓存。enforce 的 `needs_review` 只保存 `review_candidate`，不得写主地区或关联地区。
## 为什么英制距离必须接受来源紧凑写法但保留原文

英国来源会把 mile、furlong、yard 连写为 `2m4f`，也会把四又二分之一 furlong 写为 `41/2f`，组合后出现 `2m41/2f`。这些是带明确单位的来源格式，不应因为缺少空格而进入距离缺口，也不能先改写为裸小数再猜测单位。

正式解析先保留原始 `distance_text`，再把紧凑 token 和粘连分数拆成结构化 mile/furlong/yard 组件并按固定公式派生米值。香港赛季目标若届次年度与实际比赛自然年不同，必须显式保存 `actual_year` 和跨年原因；不得仅靠日期或 season label 隐式推断。

## 为什么生产备份必须验证恢复文件而不能相信脚本成功文案

低成本 Compose 的 PostgreSQL 主机名 `db` 只在容器网络内可解析，宿主机直接运行备份脚本可能在 `pg_dump` 阶段失败；脚本后续依赖或错误处理不完整时，仍可能打印看似成功的备份路径。部署门禁因此以命令退出码、文件非空、`gzip -t` 和 SHA-256 四项为准，缺一项都不能继续 retag 或重建生产容器。

在备份脚本修复前，允许使用数据库容器内 `pg_dump`、宿主机只负责压缩落盘的回退路径。该路径仍必须生成独立的 `pre-<change>-<timestamp>.sql.gz`，完成完整性校验并记录 SHA-256；失败文件不得覆盖或冒充有效恢复点。

# 2026-07-15：年度赛历按地区与届次年分片，汇总来源只作补充证据

- batch006 的年度赛历 request/cache/parse 不按五个地区粗分，而按 11 个“地区+届次年”scope 执行；每片 target 数不超过 250，parser 的 edition year 和地区边界因此可被 typed recipe 精确证明。
- 同一个年度目录 URL 可以服务多个届次年。网络 cache 对 URL 只请求一次，但 ledger 的 target references 必须精确等于 catalog 中所有引用该 URL 的来源 scope 并集；每个 parse shard 仍只输出本 scope targets。
- France Galop 固定列障碍分组汇总表使用 layout-aware PDF 解析，只补齐逐场详细赛程未覆盖的赛事；同等来源质量下详细赛程优先，汇总摘要不得覆盖详细记录。
- 完整 catalog/selection 与 scope 副本均可作为 stage 输入，但必须保留全量身份校验。少量匹配歧义、来源失败或确认事项进入 evidence-backed gap，并继续其他 scope；未知 parser、身份漂移或分母缺失仍 fail closed。

## 2026-07-18 P0 马真实来源字段统一 fail closed

- provider external horse ID 与完整 `horse_name + sire_name + dam_name + birth_year` 四元身份至少
  有一项，才允许统一 payload 通过身份 validator；候选来源 ID 不得借给另一 provider。
- Sporting Life 缺 breeder/完整二代血统、HKJC 缺明确赛事名或硬字段、HRN 缺明确出生/场数、
  JBIS 搜索与 profile 身份不一致、Geny 429/登录墙/部分履历时一律 blocker，不猜测或合成。
- `Race Index`、年龄、赛绩行数、`sire/dam/damsire` 和地区常识不能代替缺失的赛事名、出生年份、
  starts 或完整 pedigree。JBIS 日本区域只有在页面明确给出 `産地` 时才可把 country 设为日本。
- 并发网络结果只允许第一个完整临时文件通过 `os.link` 发布；所有竞争调用重读并严格校验同一
  canonical cache 后再返回，失败清理临时文件，不持锁跨网络。
## 2026-07-18 P0 马人工补录与多来源合并门禁

- 自动补充来源只允许补齐主来源的空字段，不得覆盖不同的非空值；发生冲突时整匹候选 fail closed，进入人工处理。
- 人工补录采用逐字段审核记录，只允许身份、基础资料和二代血统白名单字段。每条批准记录必须有直接 `http/https` 证据 URL、真实来源名、录入人、不同的复核人和 UTC 复核时间。
- 人工补录在 artifact 中必须标为 `entry_method=manual_review`、`evidence_role=manual_supplement`，adapter key 留空；不得把人工查证包装成自动抓取。
- canonical source cache 只能保存纯自动来源快照；读、写两侧都必须递归拒绝人工 outcome、人工 provenance、人工 supplemental source 和 raw manual rows。canonical payload 的容器只接受精确内置 `dict/list` 和字符串对象键，拒绝 tuple/set、自定义容器子类、非有限浮点值等会在序列化时变形或产生非标准 JSON 的值；迭代检查必须在任何复制之前检测当前活动容器中的循环并限制最大深度，随后用 JSON round-trip 生成纯内置类型副本，不调用不可信 `__deepcopy__`，并在规范化副本上再次检查人工标记，防止欺骗型字符串值或键在转换后变成真实标记。独立 canonical purity gate、完整 source validator 和 cache 写入边界都必须遵守该双检查。磁盘 JSON 解码阶段的深度异常也必须包装为来源错误，统一产生领域 blocker，不泄漏 `RecursionError` 或对象自定义复制异常。自动多来源与人工补录两个合并入口也必须先规范化主 payload 和全部补充行，再执行任何合并。历史污染 cache 或自定义 client 混合 payload 不得进入当前批次，人工补录只作用于本批内存工作副本。
- 原子发布 staging 前必须把冻结人工 CSV 的每个批准字段与唯一 outcome 按候选、字段和完整证据指纹一一对账。只允许 `applied/already_applied/blocked/ignored`；缺失、重复、未知状态、证据漂移或无批准输入的旧 outcome 一律整批阻断。
- 完整生涯不能通过人工字段补录通道写入，也不能由重点赛事列表推导。生涯记录仍必须来自可证明来源总出赛数和全部逐场核心证据的主来源。
- 某地区单马探测已知不完整时，不批量跑该地区 10 匹；先修来源或身份，再用同一匹复验。当前只有日本允许保持已完成结论。

## 2026-07-19 P0 马逐场证据与权威性决策

- 逐场字段证据固定分为 `direct_raw`、`canonical_raw`、`normalized` 三层，每层分别保留值、状态、
  来源、URL、时间和转换规则。Sporting Life 对法国赛事的英式展示只属于直接原始值；没有
  France Galop/IFCE SIRE 证据时，不得把 Class/Grade 映射为 Groupe，也不得由舍入英制距离反推
  官方米制。
- Sporting Life 的法国 `N/A` 不统一解释为缺失。只有法国权威来源能决定其是正式名次、未完赛、
  低名次/未映射结果或仍待补；直接 `N/A` 与权威标准结果必须同时保留。
- 生涯数量完整度与逐场权威性是两个独立维度。官方总数与备用来源行数相等时可记录 `gap=0`，
  但逐场状态仍为 `count_aligned_records_unverified`；只有逐场来源也通过权威核验后才能提升。
- HKJC 首列纯文本 `Overseas` 是有效海外履历，不要求 Race Index 包含数字；主表和页面下方重复
  海外表按稳定记录键去重并保留来源。`F/UR/BD` 等正式异常结果属于实际出赛，`WV/SCR/withdrawn`
  属于未出赛，两类计数不得混合。
- Equibase 受 Incapsula 和许可条款限制，禁止将浏览器绕过做成生产爬虫。短期仅允许人工核验
  `Career Starts` 并保存来源与时间；长期使用 Equibase/Equineline/TrackMaster 授权数据或人工
  Full Charts/Lifetime PP。

## 2026-07-19 P0 马祖父母字段的父母实体反查规则

- 当目标马来源只有父、母、母父而缺父父、父母、母母时，允许查询父马和母马各自的父母并回填
  目标马祖父母；每个字段必须保存来源 URL、核验时间、方法和证据等级。
- 父马反查只接受唯一精确同名候选；出现多个同名候选时不自动选择。母马反查除精确同名外，必须
  与目标马已有母父一致；不允许仅以马名、地区或搜索排序合并。
- 自动来源没有唯一安全候选时，允许人工查看目标马完整血统页、父母资料页、官方/拍卖目录或可靠
  血统页补证。人工补证只填空，不覆盖已有不同非空值；身份条件不符或值冲突时 fail closed。
- netkeiba、France-Sire、Tattersalls、媒体血统页和种公马资料页可作为本批字段级二级证据，但不
  自动提升为官方 Stud Book 值。法国长期以 IFCE SIRE/France Galop、英国及英爱马以 Weatherbys、
  香港进口马以原产地 Stud Book、美国以 Equineline/授权数据复核。
- 祖父母字段齐全只表示“本批血统字段已有可审计值”，不代表整匹马资料或生涯完成；基础字段缺口、
  结果状态待补、官方总出赛数未知和逐场权威性仍按独立维度判断。

## 2026-07-19 P0 马来源可见行与实际出赛必须分离

- 马匹来源页的一行不自动等于一次实际出赛。最终出赛名单未包含的早期报名行、取消赛事中的报名行
  可以保留为可审计履历证据，但 `start_status=did_not_start`，不得计入实际出赛总数或未知赛果数。
- `result_status` 与 `start_status` 独立：实际出赛的正式名次、`F/UR/BD/arr` 等必须有非
  `unknown` 结果；已证实未出赛但无法证明具体退赛原因时，结果可保持 `unknown`，不能猜成
  `scratched` 或 `withdrawn`。
- 人工赛果证据必须完整绑定原始马名、来源马 ID、父、母、出生年份、日期、外部赛事 ID、外部结果
  ID 和规范化赛事名，并且只能精确命中一条记录。身份或比赛不一致、重复命中、实际出赛仍为未知
  结果、来源 URL 或核验时间缺失时整条证据 fail closed。
- 来源可见行数、实际出赛数、未出赛数和权威/来源声明总数分别保存。只有人工最终出赛名单与公开
  生涯总数对账一致时，才可标记 `source_reconciled`；该状态不改变逐场来源本身的权威等级。
## 2026-07-19：五地区暂定赛果可先公开，正式赛果采用独立授权

- TRA 商业 API 的合资格结果可以在完整性、身份、来源权限、event allowlist 和
  provisional policy 通过后直接显示为“暂定赛果”，不等待官方二次复核。
- 官方页面只用于客观赛果事实的 manual receipt；用户于 2026-07-19 确认可以使用这些
  来源，但本期仍固定 `manual_browser_only`、`automation_allowed=false`。permission
  evidence、terms evidence 和 route contract 使用三个独立 digest，不以 contract digest
  冒充条款证据。
- official/corrected receipt 与公开授权分离：receipt 可先保存 staged revision；只有精确
  event authorization、global/region/event official coarse gate、TRA source
  provisional gate 和当前 allowlist/audit 全部成立时才发布。缺少授权时 provisional
  保持可见。
- emergency rollback 不倒删 additive schema 或审计；页面先在 maintenance off 隐藏，
  再以 dedicated provisional pointer 原子恢复投影，并按
  global/region/source -> revalidate -> event 的顺序恢复 policy。

## 2026-07-20 P0 范围批量写入与详细资料边界

- P0 来源同步允许按地区拆分事务，并把无五地区归属的既有中文马名术语另行按固定批量提交；
  该拆分只改变事务大小，不改变 P0 定义、身份规则或来源证据。
- 一次大事务因 OOM 被杀时必须先确认数据库完整回滚、恢复健康并核验备份，再继续较小批次；
  不得把进程中断前的内存进度当成已提交数据。
- “已进入 P0 生产范围”不等于“详细资料已经补完”。基础资料、二代血统、完整生涯和逐场权威性
  仍按独立完整度与字段证据门禁写入；身份冲突继续 fail closed，不因批量范围写入而放宽。
- 本次用户授权覆盖 P0 范围批量生产写入，但不授权猜值、跨身份合并、绕过来源许可或把未审核
  详情 artifact 标成已审核。

## 2026-07-23 netkeiba 标题省略状态与错误分类规则

- netkeiba `.horse_title .txt_01` 合法只含“性别年龄 + 毛色”时，允许状态字段为空；仅接受
  空值或既有明确枚举，出现未知非空状态仍以 `netkeiba_profile_structure: title_status`
  fail closed。英文名必须独立读取 `.eng_name`，不得再从整段标题位置推断。
- `partial_career:` 是已知的证据完整度 blocker，应保留原记录序号和错误文本并归类为
  `source_cache_or_adapter_error`；不得标成 `unexpected_adapter_error`，也不得据此猜测空着顺。
- 上述标题解析会改变 canonical payload，因此 parser version 从 v2 递增到 v3；所有 v2
  Netkeiba cache 与 checkpoint 必须按既有版本门禁失效，不能为节省请求绕过刷新。

## 2026-07-23 公开门户 P1–P3 采用一次性整合发布

- P1、P2、P3 作为同一公开门户版本发布，避免生产出现字体、组件、赛事上下文和关注页模板
  版本不一致；生产验收以提交 `bc7e2df047a20a997de1620688f1c7de4a5c52c4` 为准。
- 视觉改版不得弱化实时赛果公开门禁：暂定/正式状态、policy off 隐藏、冲突复核和 stale 标识
  继续沿用主线逻辑；门户模板只改变呈现，不改变发布授权。
- 未来赛事倒计时以“日”为最小精度；仅在已有发走时间时补充显示时间，不据缺失数据推算小时级
  倒计时。

## 2026-07-23 2026 赛事系列身份治理采用完整审核、单批原子写入

- 正式审核包完整覆盖 2026 target 的穷尽分类；探索快照中的 401 条未关联目标全部进入预期表或
  异常清单，但只有“唯一名称匹配”表允许产生本期动作。
- 名称相同只生成候选，不等于批准。所有非 defer 动作必须有人工作结论、非空说明、锁定的公开
  来源 URL，并通过既有身份引擎的依赖、CAS、人工锁和年度冲突检查。
- 原始 manifest 作为审核包独立信任根，绑定机器文件、原始工作簿和 canonical 行；定稿工作簿
  只允许修改 decision/review_note，不能通过同时修改机器列与哈希自证。
- 首批所有正负动作使用一个互斥 manifest 和一个数据库事务，不拆 shard；若容量或互斥性不满足，
  必须停止并重新设计、复审、授权，不能接受部分首批完成。

## 2026-07-25 HRN 同名机构采用来源级确定性译名，不改全局英国词条

- HRN `.article-body` 内的交互式视频 modal 以 `role="dialog"` DOM 语义在文本提取前删除；
  不使用 `Race Video`、乘号或中文污染词黑名单，普通正文中的同词和非 HRN dialog 不受影响。
- `The Jockey Club` 同时可指美国和英国机构。HRN 英文新闻采用来源级确定性映射“美国赛马会”，
  并与人物术语共用经过字段次数校验的 TERM 占位符；冲突英国 glossary 和生成后映射在该来源
  计划内排除。
- 生产中既有英国词条不修改，非 HRN 来源继续使用原术语解析。未来出现不同来源、缩写或新 DOM
  结构时必须用真实样本另行审核，不扩成全局字符串替换。

## 2026-07-26 本次部署后新发现的同结构污染使用独立 cohort

- 本次发布后使用新解析器重跑了完整权威 cohort，因此没有仅以冻结目标的 apply 数量推算
  `source_clean` 增量。
- 新解析器使 8 篇旧 `source_clean` 文章变为 `source_changed`。逐篇 diff 证明它们属于同一
  已审核 DOM 结构后，本次为其建立了独立 ID-set SHA、candidate、批准、receipt 和
  rollback；冻结 36 篇的 completion 保持不变。
- 本次新发现 8 篇均只移除 HRN dialog 的 `Race Video / ×`，独立 cohort SHA 为
  `f70b56c3aaa4d988c827f28aee076c43199312132be9774c1ccd010a4e51e137`。
- 其中已公开且已有 sent delivery 的文章 `9783` 仅按批准正文更新了数据库与网页，没有重发
  QQ；写前/写后逐篇比对确认 delivery 与公开状态未漂移。

## 2026-07-26 赛事生命周期设计决策（阶段 A 已实现）

- 状态推进与赛果权威分离；时间规则按 IANA 时区执行；cancelled/postponed/finished 为终态。
- 时区合同：日本→Asia/Tokyo、香港→Asia/Hong_Kong、英国→Europe/London、法国→Europe/Paris、
  美国→manifest 逐场审核 America/*；其他 region fail closed。
- 默认 mode=off，所有配置关闭；不接入 provider、不改新闻门禁、不 dispatch race-live。
