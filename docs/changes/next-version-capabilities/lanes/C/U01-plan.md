# C-002 / U01 等级筛选与标签一致性小切片（待 R 审核）

记录日期：2026-10-03，Asia/Shanghai；原 DDL：2026-10-08 18:00。
worktree `/Users/mentianlu/.codex/worktrees/bc9b/umanews`；branch `codex/next-version-product-ui-20261003`；代码 base `907f8de699b31a6fcc80acc78e9ba070aadc4f28`；调查起点 head `6fd64c87155be14f382c6ab09b8f4b5c94284dd4`。
F04 方案已由协调者转达 R 在 `1c90ee2e` APPROVED；真实后台任务计时仍待测。F05-M-01 已在 `6fd64c87` 限定修复，原 R 复审待反馈。当前 U01 只定位与规划，没有新增测试、行为代码或生产动作。

## 事实与根因边界

F05 的两个德国2025URL已经证明：未加 grade 时六张卡片显示G1，加 grade=g1 后为空；不重采网页。真实生产SHA、六对象 normalized_grade/grade_text/source_refs 未读取，因此“这些对象 normalized_grade 为空”只是待验证假设，不能当观测事实。

当前代码足以定位一个确定的合同分叉：

1. `views.py:3150 _public_race_calendar_base_queryset` 的等级筛选与历史重点页直接读 `normalized_grade__in`；`PUBLIC_RACE_GRADE_FILTERS:2958` 只含 G1/JG1/JPN1 等规范值。
2. 模板 `race_calendar.html:118` 经 `{% race_field %}` 显示卡片等级。开关关闭时 `RaceEvent.grade_badge_label:1508` 可回退原始 `grade_text`；开关开启时 `event_grade_field` 调用 `parse_display_grade`，后者可在 normalized_grade 为空时从 `Group I`、`Grade1`、`G1`等明确原文解析G1。
3. `RaceEvent.save:1351` 不保证两等级字段每次自动一致；`race_grades.normalize_race_grade`、`race_field_normalization.normalize_grade`、`parse_display_grade`是不同用途的规则。不能把宽松入库解析（例如名字里碰到G1）直接用于公开可信等级。
4. `_public_weekly_focus_events:3417` 同时存在Python对象路径与独立查询路径，均只看 normalized_grade；历史重点筛选也读该字段。修筛选必须覆盖这些直接消费者，不能只改一个URL。

最小有效缺陷场景：公开德国赛事 `grade_text='G1', normalized_grade=''`、固定2025日期、无canonical duplicate，规范展示开关打开。未筛选卡片可显示G1，但现有 grade=g1 查询必然排除；新增集合一致性测试应因此RED。此fixture是代码结构回放，不冒充生产字段快照。冲突反例 `grade_text='G2', normalized_grade='G1'` 当前可进入G1筛选但规范标签待核实，同样需要一致性约束。

## 范围及建议实现

目标：公开日历的分级标签、颜色、等级筛选、历史重点等级集合及本周G1焦点共用同一个明确等级判定；保留当前地区、时间、canonical去重、排序、分页与签名游标语义。不改取数/入库规则，不覆盖历史原始字段，不加迁移，不开启生产开关，不夹带批量修库。F01尚未交付不阻塞这个已有读合同的最小场景；Q01仍等待F01。

建议先实现**公开读侧等级投影**，复用 `parse_display_grade` 的全串识别与冲突处理，避免用字符串包含推断等级。可信等级候选来自原文明确代码及已有规范字段，两者冲突则显示待核实并排除分级集合；两者为空/不明不计成G1。已有Jpn与跳栏体系保留独立标签，并沿既有g1/g2/g3家族进入筛选。不要把“香港一级赛”“HKG1”“Local G1”无来源上下文提升为国际G1；未知地方体系继续待核实，已存国际G1不因地区香港而排除。

查询必须在分页/日期窗口/页大小限制之前应用同一判定。建议在现有 `race_information_display.py` / `race_field_normalization.py` 增加公开等级共用合同与相应 Django 查询表达式：按完整、受控的等级语法匹配映射代码，已有规范字段与原始解析代码必须无冲突。大小写、空白、罗马数字、NFKC别名与现有解析器的等价性必须测试；不要在取出200条后Python过滤，也不要读取全表ID后拼IN列表。若数据库表达式不能覆盖现有可识别形式，不允许静默缩成少数别名——实施时向协调者报告具体缺口和索引/迁移备选成本，冻结替代方案后继续。

Python展示与查询共享明确语法定义，保留不同体系标签；模板使用查询附着的 grade field/code 控制文字与颜色。C在 `views.py`、服务适配与模板内实现，不直接修改models/migrations（归A）；如必须改模型属性或加物化索引，先交A与协调者安排，不抢占共享文件。

规范展示开关两状态均测试。为满足U01公开一致性，建议等级字段的可信解析统一，其他距离/资格字段和开关不在本切片改变。这会使legacy路径的明确别名显示为规范标签，矛盾等级转为待核实，属于本任务预期行为；若协调者要求保留旧开关回退，应明确旧模式单独的兼容合同并重新绑定方案，不能默默让两个集合仍分叉。

## 文件、责任与直接影响

| 文件/函数 | 拟变更 | 约束 |
|---|---|---|
| `services/race_information_display.py event_grade_field/prepare_context` | 统一公开等级读投影与附着；SQL/Python一致性入口 | 不扩大来源信任、不改变单位处理 |
| `services/race_field_normalization.py parse_display_grade` | 如需抽取现有明确等级语法供查询复用 | 只提取等价语法，入库normalize_grade不借机重构 |
| `views.py _public_race_calendar_base_queryset/_public_weekly_focus_events` | 查询前等级判定；历史重点与焦点复用 | 不改变当前重点priority规则或分页次序 |
| `templates/stable/public/race_calendar.html` | 卡片颜色与文字消费同一投影 | 等级未知不显示成g1颜色 |
| `templates/stable/public/race_detail.html`等直接等级展示 | 确认同一投影通过prepare_context传播，必要时最小适配 | 不改赛果状态或马匹统计 |
| 已有 `test_race_information_display_pages.py`、`test_race_information_display.py`、`test_historical_race_calendar_integrity.py` | 最小RED、边界/历史/分页回归 | 复用已登记模块，避免新增模块造成catalog漂移；最终依实际diff生成选测 |

## RED → GREEN 与影响回归（尚未执行）

1. **有效RED**：在现有page测试中建立德国2025公开G1原文/空规范字段，固定时钟。GET同一year/region/tab=all，未筛选显示G1；GET grade=g1必须含同一对象，并且卡片文字/样式为G1。当前失败应是第二个响应缺对象，不是数据库/权限/fixture错误。
2. **同例GREEN**：实现共用解析/查询适配后通过；额外断言GET前后DB两字段不变，证明读修复没有持久写入。不能仅改模板把卡片G1隐藏来绿测。
3. **边界集合**：G1/G2/G3、Group I/II/III、Grade1、大小写/空白/全角罗马数字、Jpn1/Jpn2/Jpn3、J-G1/2/3；空值/OTHER/未知；G1 G2/G10/G1 Handicap；原始G2+存储G1冲突；未证Local G1/HKG1/香港一级赛；香港明确国际G1。对每个对象，可见可信分级代码与筛选家族归属一一对应，无法解析的保留待核实。
4. **并列及直接回归**：历史重点G1/G2、当前重点priority、所有地区筛选交集、本周焦点两分支、canonical duplicate排除、published限制、year/q跨期分页与游标签名、默认日期窗口。插入混合已知/未知等级跨页样本证明在分页前筛选，不漏可见匹配对象。
5. **隔离运行**：SQLite用于快速定位；PostgreSQL语义用于查询表达式交付证据，比较同一fixture的筛选集合及可信标签，确认查询数量不随对象数线性增长。固定Git树、Linux无网络容器、mock外部调用，不用生产DB/Redis/队列。
6. **选测**：真实修改后按 `scripts/plan_affected_tests.py` 与当前rules/catalog生成计划，再执行要求的核心及领域回归；新增未知路径/意外skip/规则漂移阻断。单批最多200项，超过400项按expanded；当前没有实现diff，不伪造精确选集或测试通过证据。

## 存量候选清单与交接

U01要求的存量差异清单先提供生成合同，不在本方案阶段访问生产全库。后续由获准只读快照生成：`event_id/year/slug`、原始/规范值、判定状态、公开代码、拟候选规范值、reason、证据引用及输入版本。原始冲突与无法识别单列；清单只建议，不apply。H09/O06消费固定快照SHA与候选manifest，生产写入仍由协调者按根AGENTS.md组织。

待协调/R决定：①认可统一可信等级适用于现有展示开关两状态；②未证Local G1保留未知，不新增香港地方等级profile，完整地方体系等F01/来源合同后专项解锁；③若SQL/Python全语法无法等价，先停止该实现路径并评估物化投影，不用全表后过滤兜底。推荐上述最小读侧切片，保持本线不改models/migrations；它可修代码确定的不一致，但生产六对象具体成因与候选清单尚待真实只读快照验证。

方案就绪后提交协调者送原R；审核通过前只准备fixture和合同，不开始依赖本方案的行为实现。资源规则：每轮/长任务前和持续至少每5分钟查周额度；≤3%每工具批次查，≤1%按用户要求暂停；临时错误有界恢复，不以积分/重置券绕过。
