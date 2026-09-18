# 赛事信息归一化：代码实现方案

日期：2026-09-18。版本：v2，独立子 agent 复审 APPROVED；后续已按用户“开始实现吧”实施，见 [implementation.md](implementation.md)。原方案阶段边界保留为历史记录。审阅过程见 [REVIEW.md](REVIEW.md)。

## 1. 目标、授权与基线

用户已认可规则清单，并要求补充实现方案、交子 agent 审阅。本轮交付方案与审阅记录；不实现业务代码、不运行生产清洗、不发布。

产品仍为中文赛马新闻与赛事数据平台。本次使赛事信息在日历、详情、首页、新闻关联卡片、马匹生涯中一致展示。规则见 [归一化清单](../../race_information_normalization_proposal.md)。

证据边界：

- 当前主工作区 `horse_data@7ec0e4f0` 有大量已有改动，不作为未来实现基线，不切换或清理。
- 已只读检查本地远端跟踪快照 `origin/main@91410e7aa077a0b3ea963cccfcd64b935f4369d1`；从该 SHA 导出 `/private/tmp/umanews-normalization-plan-xhiRsj` 供代码核对。它不是本轮联网确认的最新远端，也不是已核验生产版本。
- 下文文件名和行为以该固定主线快照为准。实施开始时刷新远端、创建干净 `codex/normalize-race-information` worktree，复核变化及当前仓库规则；如相关入口变化，更新本方案和审阅范围。
- 本轮没有生产读取；线上异常条数、归一化覆盖率、开关状态未知。仓库的采集恢复记录不等于本轮实时运行态。

## 2. 已有能力与实际缺口

| 现有文件／能力 | 已核对事实 | 本方案处理 |
| --- | --- | --- |
| `services/race_field_normalization.py` | 已有距离、等级、名次、场地、资格纯函数；距离用 float、部分解析按数字大小猜 m、裸数字作米、未知 token 可能被部分消费；`display_text` 仍为原文 | 在同一模块增加严格的展示解析合同，复用安全词表；不另起第三套分散规则 |
| `services/race_grades.py` | 老等级解析器仍供优先级／自动化使用，Jpn/J-G 罗马数字正则存在前缀误识别风险 | 本发布不改变自动化优先级；新展示路径使用完整 token 的严格等级解析，旧解析行为及将来治理范围单独记录 |
| `models.py` | RaceEvent、HorseRaceRecord 已有规范距离、精度、场地、条件和版本字段；`grade_badge_label` 截前4字符；`display_distance_text` 按地区猜单位并可能输出 f/m | 展示不直接信任旧派生值；替换公开展示入口，不新增同义数据库列 |
| `services/race_events.py`、`horse_race_records.py` | 已在写入路径保存部分派生值，现有版本与 input hash 不足以证明符合新展示规则 | 本次保留写入合同，公开读取从原值及可证明的上下文重新计算 |
| `services/race_term_display.py` | 已有请求内 RaceTermResolver，仅处理赛事／马场；主值和别名分阶段选取 | 扩展成统一批量解析，主值＋别名先合并候选、按实体去重再决策 |
| `views.py` | 马名／骑师另有 `_attach_race_term_display_names`；实时赛果有 visible 判定；赛前 preview 可能返回非 ORM 行 | 在既有公开权限／赛果可见性判定之后构建展示对象，支持 ORM、dict 与 preview 行 |
| 公共模板 | 多处直接读 grade_text、distance_text、trainer_name、finish_time；马匹页只部分接入新术语能力 | 全部列入入口矩阵，不只修改赛事详情 |

## 3. 架构与本次范围

采用“原始业务数据＋请求内标准展示对象”。本次数据库 schema 迁移为0，历史业务回写为0，新增 Celery 任务为0，不新增 AI 调用。已有归一化写入服务、赛果确认、身份、调度、筛选与统计合同继续独立。

```text
现有公开查询与可见性检查
  → 一次收集本页事件／行／来源上下文
  → 批量术语候选解析 ＋ 严格字段解析
  → EventDisplay / RunnerDisplay / ResultDisplay / HistoryDisplay
  → 同一组公共模板字段

离线快照／受限只读盘点 → 同一展示服务 → 差异报告（无 apply）
```

新增 `services/race_information_display.py` 负责协调和格式化；扩展 `race_field_normalization.py` 负责可测试的严格解析；扩展 `race_term_display.py` 负责批量实体译名。纯函数不查库、不取当前时间、不访问网络，时间与词库结果由调用者传入。

旧 normalizer 的签名、返回类型、版本号和默认行为不直接修改，避免无意改变采集与统计。严格入口命名 `parse_display_distance`、`parse_display_grade` 等，使用独立 `RACE_INFORMATION_DISPLAY_VERSION = race-information-display.v1`。共同安全词表在原模块集中定义，兼容适配器不得反向把新展示字符串写入原始字段。未来合并写入合同另行评估，不把它当本次前置条件。

适用范围包括清单里的所有已有展示字段。天气、奖金、枠番等当前入口没有独立数据时，不新增空卡片、不猜数据；在 formatter registry 中明确 `unsupported_missing_source`。条件文本含未支持片段则整字段待核实，保留管理员原文。缺字段与格式处理完成率分开计数。

## 4. 返回合同与失败策略

统一不可变 `DisplayField`：`text`、`state`（normalized/preserved/unknown/conflict/missing）、`reason_code`、`rule_version`、`input_sha256`。距离另携 Decimal 米值、单位 token、来源近似标记；等级携内部代码与展示标签；名次携数字值与状态。摘要对有类型的规范 JSON 编码求 SHA，包含原值、上下文、规则／来源配置版本，不能只 hash 原文。

- 正常字段只显示标准格式。
- 距离、等级、负重、币种、赔率制式等有歧义时，不将裸原值混进标准字段：显示“待核实”；真正空值用“—”。
- 专有名词未匹配可保留原名，state=preserved；同级实体冲突不任意挑一个。通用未翻译术语进入报告。
- 来源明确未公布／赛期待定时才使用“未公布／待定”；不能从 null 猜原因。
- 模板自动转义所有展示值，不允许 mark_safe；原始值只在已有后台授权界面或受限报告中查看，不塞进公开 title/data-* 或日志。
- 不将“已结束”变成“正式赛果”。展示异常不自动改变 `visibility_status`、`is_confirmed`、`result_confirmed_at`、业务状态、关联ID或排名排序。

## 5. 距离、等级与普通字段的明确算法

### 5.1 距离

1. 局部清理全角数字、单位变体、空白；保留来源原文。识别 `米/metre/meter/メートル/km/公里` 和 `mile/英里/foot/feet/ft/英尺/furlong/fur/f/yard/yd/y`，最长单位优先，整字符串必须被语法消费。
2. `m`、裸数字、`1m2f` 等依赖来源格式：只有经 fixture 验证的 source profile 或明确结构化单位才解释。不能仅因日本／英国、平地／障碍或数值大小猜。`m` 在明确公制 profile 中为米，在英制 profile 中为英里；缺上下文为 `ambiguous_unit`。
3. source profile 使用 `(provider, adapter/schema version, field path, source language)` 白名单，并保留来源证据；adapter 提取现有 source_refs/raw_payload，禁止按 URL 域名或 country_region 单独推定。无法从旧记录确认版本时，明确单位文本仍可解析，含糊文本待核实。实现必须用现有 fixture 逐项证明 profile 才启用；不为覆盖率放宽规则。
4. 全过程使用 Decimal 或有理数：英里1609.344、弗隆201.168、码0.9144、英尺0.3048米。拒绝负值、0、NaN/Inf、分母0、过长输入（上限512字符）、未知 token 与单位冲突；不部分解析成功。
5. 公制直接显示如 `1600米`，保留有效小数。英制按固定顺序选格式：原为纯英尺时保留英尺；否则总英尺为660的整数倍时换成精确英里小数（整弗隆）；其余拆成整数英里＋余数英尺（0英里省略）。英尺有限小数原样精确表达，无限小数用约分分数，不靠截断丢精度；这使相同输入只有一个结果。附注米值按 ROUND_HALF_UP 至整米，总是含“约”。例：`1m 2f`（已验证英制 profile）→ `1.25英里（约2012米）`；`1m 110y` → `1英里330英尺（约1710米）`；`1 1/16 mile` → `1英里330英尺（约1710米）`。
6. 来源“约”保留，如 `约1英里（约1609米）`。官方公制与换算值不一致时，除非来源合同明确两者分别为名义／实测距离，否则 `conflict`；不随意设宽容阈值。明确定义的两种口径分开标注，不相互覆盖。
7. 已格式化中文串重复输入须解析为相同展示值并验证附注四舍五入一致；正常业务始终读取原始值，不对展示值再处理。旧 `distance_meters_normalized` 不能仅因非空而覆盖原文。

### 5.2 等级

- 内部仍采用现有 `G1/G2/G3/JPN1/JPN2/JPN3/JG1/JG2/JG3/L/OP`；公开固定映射为 `G1/G2/G3/Jpn1/Jpn2/Jpn3/J-G1/J-G2/J-G3/L/OP`，不改数据库 choices。
- 全角／罗马数字转为匹配形式，先识别完整体系和数字再映射；覆盖 Grade1、Grade 1、Group I、Groupe II 等审核别名，禁止正则把 JpnIII 吃成 JpnI。
- 等级字段可移除白名单说明“重赏”等；若仍有未知后缀、多个不同等级或内部标准值与可解析原文冲突，显示“待核实”并报告。不能从完整赛事名称任意搜一个 G1。
- 已有标准代码合法且原文为空可使用；原文非空却解析失败或互相矛盾则不盲信旧 normalized_grade。
- 地方等级按已验证体系代码显示，不把香港历史本地等级自动转换成国际 G1；年份由当前年度事件／历史记录提供，不能读取系列当前等级覆盖历年。
- 新马、未胜利、胜数条件移入类别文本；无等级证据为“—”，明确无分级才显示“无分级”。徽章与资料栏来自同一结果，去除四字符截断。

### 5.3 其他字段

- 场地材质与赛种分列，使用确定词表；AW 的解释依赖 profile。内外圈／左右转、天气／场地状况分开；各国 going 不跨体系强等价。旧派生字段需来源一致性证明，否则解析原文或待核实。
- 年龄、性别、负重制度：组合 parser 完整保留限制；`3yo+` → `min_age=3/max_age=None/age_open_ended=true` → “3岁及以上”；`3yo` → `min_age=3/max_age=3/age_open_ended=false` → “3岁”。未识别限制不静默删除。负重千克或磅，磅附千克到1位小数；英石组合仅在 profile 证明下换算，不猜 `9-7`。
- 计时解析只接受已声明格式的时长，显示中文分秒，原精度不补零。差距使用审核词表＋马身分数；未知基准不改成“落后冠军”，不将马身换米。
- 赔率本次保持来源制式，统一标签＋标注制式，不自动换制；未证实制式待核实。热门排名独立解析为“第N热门”；“预计／最终”和更新时间保留。
- 金额仅在币种与总额／冠军口径明确时格式化；不做汇率换算。纯数字、编号保留1A等；马号、闸位、枠番不同。
- 名次优先现有经验证的官方名次／同着证据，非完赛状态优先于展示排序数字，不能将 legacy 占位排序当实际名次；展示“并列第N”，内部数值不变。冠军选择和可见性门禁沿用现有服务，不能由 formatter 重新推断。
- 时间保留当前查询、日期分组、排序与状态规则，只统一展示：明确当地日期时间和 IANA 时区，可附北京时间；无时区／DST重复或不存在的本地时刻不擅自转换，显示当地原时间＋时区待核实。来源已给 UTC 与本地字段冲突时待核实，不修改赛程。日期完整值 YYYY-MM-DD，首页相对“今天／明天”标签保留并附完整日期信息。

## 6. 译名、大小写和身份

扩展 `RaceTermResolver` 处理赛事、马场、马匹、骑师、练马师，收敛新展示分支中的 views 重复逻辑。新增显式 `mode="strict_display_v1"`；默认 `mode="legacy"` 原样保持旧候选选择与回退算法。现有 `RaceTermResolver()` 调用、旧 `resolve_batch_race_terms` 等函数默认合同不变；只有新开关开启后的展示服务主动传严格模式，不能通过全局改默认算法改变旧路径。

优先级：经验证的实体关联（类型／启用状态／地区／年度适用性正确）→ 年度已确认中文赛名 → 来源主名与别名的唯一实体命中 → 原名。不得用当前系列译名覆盖历史年度冠名。赛事名不机械删除年份／赞助商／等级片段，拆分需结构化字段或审核别名证明。

候选先合并 primary＋alias，按 term_id 去重；同地区精确命中优先，全局仅在没有同地区候选时使用；同层多个实体为冲突，不能以 priority/pk 选中，也不能再降级全局掩盖冲突。未知语言只允许经过验证的关联或跨语言候选集合中唯一实体；不得默认日语。没有同地区／全局匹配时不跨地区猜。

名称匹配键使用 NFKC、casefold 和折叠空白；显示字符来自正式词库，不把整个英文 title-case。SQL 候选召回使用按类型与地区约束的原字符串及规范形式、大小写不敏感查询，随后 Python 精确键核对；数据库无法召回的特殊 Unicode 别名列待补，不全表扫描或假装覆盖。英文无词库命中只做空白清理，固定机构缩写按审核映射表转换。Stakes 等专名片段不全局替换。

术语查询在一个请求内合并同类输入，词库与别名总计不超过10次查询（5种类型×2）；不得在模板、property 或每一行查询数据库。规则与解析结果仅请求内缓存，包含地区、语言、年度、实体类型、原值和 profile，避免跨请求旧译名。实现须用查询计数证明40场列表／大型出马表不会出现N+1。

## 7. 接入矩阵与兼容

| 页面／入口 | 接入点 | 验收 |
| --- | --- | --- |
| 日历／焦点赛事 | `public_race_calendar`、`_group_race_events_by_date`、`_public_weekly_focus_events`；`race_calendar.html` | 等级、距离、场地、马场、时间与详情一致；不改变筛选集合／排序 |
| 赛事详情 | `public_race_detail`；`race_detail.html` | 标题、基础资料、冠军摘要、前五名、出马表、赛果、两段历年冠军全部接入 |
| 首页与侧栏 | `_public_today_races`、`_public_next_key_race`；`feed.html`、`_hot_list.html`、`_flash_race.html` | 事件元数据、冠军名和显示标签统一 |
| 新闻赛事卡片 | public article detail 的 teaser_event；`detail.html` | 只处理结构化卡片，不重翻译新闻正文 |
| 马匹页 | `public_horse_detail`；`horse_detail.html` | 生涯所有分页、主要胜场、赛事链接都接入；关联公开赛事时复用其元数据，无法公开关联时仅使用记录自身可公开数据，不能泄露隐藏赛事内容 |
| 后台候选预览 | `build_candidate_diff`调用侧／候选详情页面及 race_event_form | 原值与标准预览并列；不把格式变化标为已应用，不覆盖人工锁 |

模型 `grade_badge_label`、`grade_badge_class` 和 `display_distance_text` 显式按新开关分支：false执行原实现（包括旧截断／距离推定），true调用无查询 formatter；不能无条件改写其算法。formatter本身不读取设置，由调用者选择。新的模板统一使用 `event.public_display`、`row.public_display`，新路径属性必须总是赋值，禁止遗漏后静默回退原字段。对象可携旧数据引用用于URL／排序，但展示字段只从DisplayField读取。

先完成既有权限、canonical 跳转、live result visible 判定和 preview 选择，再转换行；不能重新查询被隐藏的结果来补展示。ORM runner、dict、SimpleNamespace/preview、历史合成行通过显式 adapter 转换，全部具有来源上下文而非依赖 `.pk` 必然存在。

新增独立 `RACE_INFORMATION_NORMALIZED_DISPLAY_ENABLED`（默认false），覆盖本次全部入口；旧 `RACE_FIELD_NORMALIZED_DISPLAY_ENABLED`／`...STATS_ENABLED` 不改值。新开关true时由新展示路径统一接管，false时返回原路径，4种新旧显示开关组合都测试；统计开关永远不受影响。规则版本进入存在的页面／片段缓存key；当前已核对 `race_event_public_cache.py` 仅缓存数量和年份，无需为本任务清空Redis。实施时核对其余响应缓存。

## 8. 历史数据与只读差异报告

新增 `preview_race_information_normalization` 管理命令，只读，无 `--apply`。支持离线 JSONL 和显式限定的库内对象类型／地区／年份／ID范围；默认最多200条，keyset分页每批200、命令每次最多10000条，续跑携带 last_pk。使用专用只读会话，禁止隐式生产连接；本轮不执行该命令。

报告包含：基线SHA、规则/profile版本、范围、导出开始结束时间、每条主键、相关输入hash、字段原值／展示值／状态／原因；输出JSONL和summary.json，路径显式指定、拒绝覆盖旧报告，不能导出整份raw_payload、凭据或URL敏感查询参数。

统计口径按字段分别列：已有且可规范化、原已合规、缺失、歧义、冲突、未支持；同时按入口和来源分层。现有快照生成的候选与原raw值保持不变，新旧记录在读取时同样归一化，因此本发布无需回填已有派生列。跨批读取可能受并发写入影响，报告注明非一致性快照；上线验收样本须再次核对输入hash。盘点只读任务不持有生产行锁。

上线条件：目标验收样本可解释；确定性字段通过率100%；距离／等级公开字段不得泄露禁用格式；unknown/conflict报告保留且准确，不能宣布全量数据都已归一化。词库待补与来源上下文缺口可继续存在，但必须显示待核实并计入缺口。

## 9. 测试与执行分解

1. **(application) RED：严格字段合同。** 新增 `test_race_information_display.py` 与固定fixtures；覆盖 Grade1/GIII/JpnII/J・GIII、多等级冲突、历史地方等级、英里／英尺／弗隆／码、全半角、十进制与分数、0/负值/分母0/NaN/未知token、含糊m、裸数字、官方名义距离冲突、ROUND_HALF_UP边界、重复格式化、HTML转义。
2. **(application) RED：页面与语义。** 新增 `test_race_information_display_pages.py`；同一fixture贯穿全部入口；Grade与距离标签一致；输入对象含preview dict和历史合成行；隐藏live结果不能被补回；并列、退赛、未知名次不误显示；跨日/DST、条件残留、计时精度、负重与赔率制式。分别断言 `3yo+` 的无上限三元组及“3岁及以上”、`3yo` 的固定年龄三元组及“3岁”，禁止只测字符串能否解析。
3. **(application) RED：术语与开关隔离。** 覆盖大小写／全角键、跨语言、同地区冲突、global fallback、primary与alias冲突、同实体多别名去重、同名不同类型、年度冠名、未命中保留；40场／200行保持查询上界，原始值和数据库前后不变。新旧显示开关四种组合逐项验证：新false时主值／别名跨实体冲突、地区回退、裸数字距离输出与旧基线一致；新true时使用严格结果且与旧显示开关无关；由true关回false后恢复原结果。统计开关两种值均不因本功能改变统计输出。
4. **(application) 实现。** 依次完成严格parser、词库批量resolver、展示DTO、所有页面adapter与模板、无查询模型兼容入口、开关；静态扫描 public 模板中的旧原字段直出并逐项登记豁免（仅关闭开关路径）。
5. **(integration) 盘点工具。** 实现离线／库内只读预览、范围限制、游标、摘要和脱敏；测试无写入SQL、无真实外网、拒绝覆盖报告、重复运行结果可比、分页无跳漏。解析不修改抓取adapter和活跃采集代码。
6. **(application) 回归。** 跑 `stable.test_race_event_distance_display`、`stable.tests.test_race_field_normalization`、`stable.tests.test_term_display`、`stable.tests.test_page_regression`、`stable.tests_legacy.RaceEventPageMVPTests`、`stable.tests_legacy.HorseProfilePageMvpTests`、赛前preview和live可见性相关测试、`stable.test_race_section_gaps`。原距离展示测试预期 f/m 随新开关补充新行为，关闭开关旧断言仍通过。实际测试入口以实施基线发现结果为准，不能虚构通过数。
7. **(operations) 发布准备。** 文档、设置说明、只读预览与开关回滚；独立代码review后按实际主线要求执行完整CI，同基线比较已有失败，不能用局部通过代替整体验收。本轮仅方案审阅，不运行实现测试或声称通过。

所有DB测试使用隔离测试库，PostgreSQL验证大小写查询、JSON及读取性能；测试中隔离Redis/Celery/网络。开关true/false、旧flag组合、统计不变、业务数据不变都要可复现。验收至少日本、中国香港、英国、法国、美国各一组，包含历史与赛前／赛后。

## 10. 发布与回滚设计

本方案的发布包预期为代码＋一个默认关闭的新展示开关，无migration、无生产业务写入、无任务调度或外部通知。实际发布前以当时仓库规则和用户授权为准，本轮方案通过不等于发布授权。

先离线fixture和目标样本差异预览，再部署关闭开关代码，核对旧展示及健康，然后按发布包启用新开关并核对入口矩阵。只在明确的发布窗口重建必要web服务；若部署工具实际还重启worker等，发布包必须列真实影响，不承诺web-only。与正在运行的采集核对共享合同／锁及资源影响，不为方案任务暂停任何作业。

若出现错误换算、译名冲突被误选、赛果泄露、异常查询增长或页面失败，关闭新开关并按配置加载方式重启相应服务，验证旧路径；无数据回写，因此无需逆向业务迁移。若必须代码回滚，使用发布前镜像及既有部署机制。清理范围仅本功能缓存namespace，不清空共享Redis。

## 11. 交付物与待核验项

- 本文是可审阅实现方案，规则清单作为产品规则来源；独立审阅另记 `REVIEW.md`，返修交同一reviewer复核。
- 实施前自动核验：新的主线SHA／入口变化、profile真实fixture与覆盖缺口、现有缓存、测试命令和PostgreSQL基线、生产影响数量。缺证据不猜值，也不把这些检查转成重复询问用户。
- 不存在必须现在向用户索取的业务信息。当前“可以”认可前述归一化方向，本轮授权止于补方案与审阅；代码实现按后续任务推进。
