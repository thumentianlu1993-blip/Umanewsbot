# 修复设计（方案复审通过，实施中）

## 1. 问题分层

“采集到”分三层：保存的可见网页/表格原文；解析后候选或来源观测；正式业务字段。只有经过公开展示核验才算闭环。不能把数据库与网页相同当作与来源完整一致。

- 距离与冠军计时：正式值已存，展示合同缺口。
- 开赛时间：空中锦标现已由现有正式接管写入；历史档案有钟点但没有采集时区证据，不能安全转换。
- 奖金/条件/方向/场况：保存的来源原文已有，法国解析器及正式投影未提取；模板也没有全部展示入口。
- 旧卡表：来源卡、结果观测与赛果表已有数据，既有 runner 的保留策略不补原空值。

## 2. 复用现有链路

沿用 `france_sources.py` → `france_pre_race.py` / `race_data_source_adapters.py` → 现有 observation/candidate 与字段仲裁 → `RaceEvent`/runner/result → `race_information_display.py` → 公开模板。不给所有来源放宽 schema，不建新调度器、队列或通用恢复框架。

法国基础资料增加版本化 `france_basic_v1` 来源合同：字段值、原文、单位/币种/时区、来源 URL、原文 SHA、observed_at、parser_version。放在既有 observation.field_provenance / candidate.raw_payload 与 event.source_refs 的受限命名空间；不得把这些元数据作为任意可写字段。既有结果 payload 的严格 schema 保留，法国解析完成后单独校验基础资料合同。逐字段 authority/change 使用现有模型记录，值和证据同时更新。

缺失代表“此快照未提供”，不代表删除正式已有数据。旧快照、未知单位、身份冲突、人工锁及较新来源优先级冲突不得自动覆盖。联网读取在事务外完成，事务内复验 baseline/owner/lease。

## 3. 逐字段设计

### 距离

读取已绑定官方目录/可见卡表中的明确米单位，填充现有 `source_refs.field_units.distance_text=metre` 与逐字段证据，再走现有距离展示。不能只因为 country=france、primary=Geny 或字符串含 m 就认为单位可信。现有 pdf 引用可帮助验证，但不能无验证地继承旧字段证明。保持原 distance_text，不为展示重写数值。

### 开赛时间

2026-11-10 用户明确确定：**抓到开赛时间即可更新，不等待正式出马表接管。**“即可更新”指本轮成功采集处理内，完成必要校验后写入正式赛事时间，事务提交时刷新相关公开缓存；不等待下一次调度、名单齐全或来源阶段晋升。该规则已进入实现与隔离验收。

时间更新与名单阶段解耦：报名、预计、正式卡或尚无可发布名单时，只要同场来源已明确给出有效时刻及时区，就可更新。复用当前 pipeline 的 schedule_apply、字段权限仲裁、来源新旧比较、人工锁和 lifecycle generation 处理，将时间应用整理为共用入口，由法国赛前采集和正式卡链路调用；不另建一套直接save逻辑，也不只在模板临时覆盖。

处理顺序为：校验赛事身份与时区 → 提取有效时间 → 校验当前写入owner/lease及字段权限 → 原子更新race_datetime、local_start_time、timezone_name及来源审计 → 提交后使详情/日历缓存失效。沿用既有生命周期调整机制，不凭一次时间更新发布名单、切换名单阶段、标记正式卡接管或改变赛果状态。若现有owner限制使合法时间只能等到接管，须在该owner的受控入口内完成时间更新，不能以取消owner校验解决。

时间变化独立参与内容比较与幂等判断：名单未变但开赛时刻修订，也必须处理；没有名单或not_published的提前返回不能丢弃有效时刻。后续更正依据同一仲裁规则及时更新；重复输入不重复写，旧快照不覆盖新值，来源空值不清掉已有时间。00h00、缺时区、身份不匹配、人工锁或权限拒绝时保留原值并记录具体原因，不能算作即时更新成功。

验收要求：在一次采集任务完成后、没有执行正式卡接管或下一周期任务的情况下，正式库、详情页、日历均已显示正确北京时间。空中锦标“04:17已采到却等到09:05才写入”的历史过程作为待消除的复现用例；09:23正确显示仅证明原链路最终可达，不满足新的同轮更新要求。

47 场历史缺时：在既定范围重新抓取含可靠时区上下文的来源，通过现有浏览器传输记录 source-timezone，使用 ZoneInfo('Europe/Paris') 处理夏令时。旧归档没有时区，不补写伪 meta。12 场已有时刻也对照计划/实际发走定义；不同类型不得互相覆盖。00h00 继续视为未公布。历史修复只改时间相关字段，不重放状态或整份名单，不重启过去赛事的调度。

### 完成时间

增加有明确 Geny 来源证据的法式格式解析，保留原值，输出标准分秒供共用展示。例 `0'55"10` → 55.10 秒，`4'07"4` → 4分7.4秒。引号后是小数位，不能机械按三位毫秒或百进制猜测。来源格式、范围不匹配则仍待核实。覆盖赛果与已确认关联的历史冠军显示，不由名次/差距反推其他马的完成时间。

### 赛种、场地、方向、场况

- 复用 normalized_race_type：Plat→flat；Haies/Steeple→jumps，并在法国来源合同保留细分，显示为栏架/障碍追逐等经确定的中文标签。已有 flat 可直接走共用展示，不再寻找 RaceEvent 上不存在的 race_type_text。
- Gazon→turf，与赛种独立；AQPS 是参赛马类别，不是场地。没有来源时不由马场或“法国障碍”猜草地。
- 用现有 course_layout_text 存方向原值；Droite/Gauche/Ligne droite 分别显示右转/左转/直路。
- 用现有 going_text 存法国场况原值，附 Pén 数值于来源合同；显示法国专属翻译及原文/测量值。不要套用英港场况刻度。解析必须停在场况容器末尾，不能吞入 NP 等后续文字。

### 奖金与参赛条件

建议增加 `RaceEvent.prize_amount`（可空 Decimal(14,2)）和 `prize_currency`（ISO币种，空值可用）；将现有 eligibility_text 从255字符扩为TextField，保留完整条件。这需要一项增量 schema migration，不是纯展示修复。

奖金指本场总奖金，币种明确；例如空中锦标 €73,200。France Galop 同页的128,100/106,140是特定资格下奖金加马主补贴，不能当本场基础总奖金；奖金分配、附加补贴原文另留证据。优先使用显式€的Geny交叉证实；FG纯数字仅在核实的字段/币种合同下准入。

条件原文完整保留；结构化年龄/性别/资格复用 minimum_age/maximum_age/age_open_ended/sex_restriction/eligibility_constraints。中文摘要只来自已覆盖的规则（如3岁及以上雌马、AQPS），复杂胜绩/加磅/报名限制不擅自简化为全部条件；提供完整原文展开区。不使用实时AI翻译作为事实写入前提。

公开基础资料补齐奖金、方向、场况、条件显示位置。当前 event_fields 的 prize_text 主要服务另一个履历对象，RaceEvent没有此字段；不能只加抓取器而忽略存储与模板。

### 旧卡表80行

绑定 source_identity + event + horse_number + 同场马名核对，不用单独马名跨赛事匹配。卡表分配负重来自独立 card[Poids]，调整后负重来自 Déch.；赛果实际负重继续保留在 result。

例 Gaga Girl：卡表分配58.5 kg，不能用赛果负重替换。Huron Bleu 卡表68 kg、D. Bressou、Genybet1.4，当前 runner 三项为空。

补练马师、分配负重、赔率及各自来源/采集时刻，只填空/明确同值补证；非空冲突进入可审差异。马号0/闸位0作为缺失占位处理，但障碍赛本就无闸位时不造闸位。骑师全名与缩写不因文本不同强行替换。保持已接管标志、runner主键、参与者关系和人工锁。

赔率默认仍单平台 Genybet，不将 PMU 报价合并、也不把赔率排序当热门排名。已存 PMU 原始报价属于可选产品扩展。

## 4. 回填与后续自动更新

一次修复命令同时提供 plan/dry-run/apply/replay。清单包含固定80目标内实际有证据的字段白名单、before/after、source SHA、baseline、锁和冲突结果；名单修复另绑定10场80行，不能全量覆盖整个event。

同一解析与应用逻辑同时服务历史修复和之后自然采集。相同内容重放零变化；异常事务回滚；不因未公布/空响应删除旧字段；基础资料更新使公共缓存失效，并让后台候选基线与正式值保持一致。

本轮实施中，正在收集既定80场的新增来源证据；尚未形成获准生产manifest，未执行生产迁移或业务写入。发布与回滚见 rollout.md。

## 5. 验证与仍需明确的事实

当前已证实源码原因：france_archive.py明确不注入未记录的时区；race_data_sync_results.py保留旧runner字段；race_information_display.py的法国距离合同依赖旧primary PDF且赛种读取另一对象字段；race_field_normalization.py不识别法式计时；公开模板缺方向/场况/奖金展示。

实现前固定法国场况中文词表、奖金币种合同与计划/实际发走语义；这些不是要求用户重新说明既定范围，优先用来源和现有规则完成。若确实出现会改变产品口径的分支，再按根AGENTS处理。2026-11-10独立方案复审已通过；实现后的代码审核仍待完成。

## 6. 方案复审修订：实现边界

### 两套claim的共用写入入口

不将赛前claim伪装成RaceDataSyncClaim，也不绕过正式入口的multisource_claim_required。抽取共用的时间字段仲裁/审计/调度更新内核，入口分别接受经验证的正式RaceDataSyncClaim上下文与受限的FrancePreRaceWriteClaim上下文；内核不自行接收未经验证的event_id直接写库。

FrancePreRaceWriteClaim沿用赛前token/120秒lease，取得时额外冻结projection的owner/owner_generation/owner_manifest_sha256，以及enrollment的state、authority_version、enrollment_generation、source_set_generation/source_set_digest、policy_digest与绑定release（没有控制行时保存明确的无记录基线）。这些guards存入服务器赛前lease状态，返回claim只携带对应token与摘要。complete在同一外层事务重新读取并逐项复验；缺guard、owner变化、新增控制行、过期lease均拒绝，不把原赛前token单独当正式写授权。

法国claim、complete、finish统一在最外层事务起点使用 `_lock_multisource_event` 的 lifecycle→event顺序，并沿正式控制器既有顺序锁projection/enrollment/tracking/checkpoints；遇生命周期控制行创建竞争，按既有机制回滚重试整个事务。正式来源分支继续调用原claim验证器，不改其它地区claim形状。

未登记赛事仅允许unmanaged的赛前时间写入；已登记赛事须data_sync owner、当前有效策略/来源合同/运行release全部一致，且无另一个未过期正式写入claim。若正式claim正活跃，返回明确可重试竞争原因，不抢占、不清掉他人的token；竞争解除后重新取得赛前claim，不复用过期的guards。合法无竞争路径同轮完成，等待名单或正式接管不能成为阻断理由。legacy、unknown、手动owner一律不自动写。

通过此验证后，共用内核按字段仲裁写时间；调度变化使用同一tracking/checkpoint/lifecycle重排逻辑，更新generation与缓存。赛前任务在该事务内用已持有且已验证的上下文收尾，而不再拿已被本次时间更新改变的旧快照调用通用finish；正式任务保留原claim_invalidated收尾。历史修复走独立manifest事务，只改历史字段，不唤醒终态任务。必须以真实PostgreSQL竞争测试证明此衔接，不以mock代替。

### 基础资料指纹与字段准入

`france_basic_v1`结构固定为版本、赛事绑定、fields、每字段原文/单位/币种/来源URL/原文SHA、observed_at及parser_version。规范内容摘要覆盖字段值和来源证据（包括同值的新增单位证明）；纯重复抓取的observed_at不单独制造内容修订，但新权威确认必须更新对应权威水位。

为法国card/result观测增加仅法国可用的`france_basic_sha256`受限字段，并校验它精确等于provenance内基础合同摘要；观测去重因此包含基础资料。结果严格schema只增加这一已校验元数据键，不将任意provenance写入事件。赛前candidate的content_sha同步包含基础合同与off_time，not_published也保留独立basic候选；旧观测不可改写。

显式准入映射：`france_basic.distance`→distance_text及单位证据；`france_basic.discipline`→normalized_race_type及细分证据；`france_basic.surface`→surface/normalized_surface；`france_basic.layout`→course_layout_text；`france_basic.going`→going_text及测量证据；`france_basic.prize`→prize_amount/prize_currency原子字段组；`france_basic.eligibility`→eligibility_text及年龄/性别/资格原子字段组。时间沿用off_time/local_start_time/timezone_name三项同时准入，不归入宽泛basic开关。每组必须来源合同允许且运行字段白名单启用，缺一拒绝；发布包列出这些新增准入项。

### 完整条件的边界

FG完整条件从GROUPE等级后首个以Pour开头的条件段开始，保留所有后续条件段落，包括普通/第二次/追加报名日期及费用、加磅/胜绩限制及相连说明，直到条件区域结束（Legal notice/后续名单区域）。用原始DOM区域或保留换行的可见文档作边界，不能只匹配第一行Pour。Geny使用比赛头部的条件区域，结束于Terrain/下注入口/结果表；不得连入侧栏、名单、历届冠军或页脚。调查台账中的raw_fields.conditions单行摘要仅用于确认存在，不能作完整性真值；测试直接使用原始future.json多段文档。

### 迁移与当前生产基线

仓库有0080/0081其它已合并的独立功能迁移，法国当前生产窄候选仍以0079为基础。法国字段增量迁移从0079分支；仓库用单独无操作merge migration汇合0081与法国分支，生产窄候选只携带法国分支迁移，不顺带执行其它lane的0080/0081。最终编号、migration graph、模型差异与生产迁移计划要在固定候选上证明；如实际生产已变化则重新核对，不沿用旧schema假设。

## France Galop 奖金币种合同补证（2026-11-10）

已检查官方[平地年度programme](https://www.france-galop.com/sites/default/files/2026-02/groupes_listed_plat_2026_v7.pdf)第120页（印刷118页）和[障碍年度programme](https://www.france-galop.com/sites/default/files/2026-01/groupes_listed_obstacles_2026_v4.pdf)第57页（印刷55页）的真实渲染：Miesque/Thomas Bryon基础73,200欧元与128,100含补贴行分开，Magalen Bryant基础170,000欧元与195,500含补贴行分开。PDF文本抽取把欧元符号误映为c，已用页面图像核实。

详情页采用相同的基础allocation/名次分配与后续Prime Propriétaire结构，但省略货币符号；解析器仅对France Galop官方详情头部启用EUR合同，取没有补贴后缀的第一条分配行，并验证名次分配之和等于总额。实际金额仍以当前详情为准，不用旧PDF覆盖变动后的金额；不将本合同应用于其它来源或其它币种页面。

## 7. 代码复审收敛

字段修复的持久before/after CAS保留业务值、来源、权限、身份、owner/登记/调度版本和相关field change；`tracking.claim_generation`只属于短期采集claim，正常完成的空读可递增该计数，故不写入持久修复摘要。修复每次执行仍按统一锁序持锁并拒绝活跃正式claim，不能借此忽略owner/权限/字段漂移。

同值赛果佐证返回前，法国已存在runner仍按同场身份、准入、仲裁和手工锁执行独立卡表补空；既有赛果行不改，不在该分支创建名单。
